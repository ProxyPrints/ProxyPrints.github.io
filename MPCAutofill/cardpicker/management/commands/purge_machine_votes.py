from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, QuerySet
from django.utils import timezone

from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardArtistVote,
    CardPrintingTag,
    CardTagVote,
    PilotRunLedger,
    PrintingTagStatus,
    PrintingTagVote,
    TagVoteStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.utils import find_stale_applied_migrations
from cardpicker.vote_consensus import is_human_backed_source

# Machine = NOT human-backed, DERIVED from vote_consensus's single source of truth
# (is_human_backed_source / _MACHINE_DERIVED_SOURCES) rather than a hand-maintained duplicate
# list here - the previous literal {DEDUCTION, OCR} copy of that definition had already gone
# stale: FEDERATED (federation stub, no importer yet) and IMPLICIT (2026-07-22 filter-chip
# signal) are also machine-derived per vote_consensus. A future new machine source now only
# ever needs to be added there. This makes --all-machine's blast radius exactly "every
# non-human-backed source", so the dry-run's per-source breakdown is the operator's
# confirmation step before a write.
_MACHINE_SOURCES: frozenset[str] = frozenset(s for s in VoteSource.values if not is_human_backed_source(s))

# Batched-delete chunk size for --all-machine: one unbounded DELETE covering hundreds of
# thousands of rows holds its locks for the whole statement and bloats the WAL.
_DELETE_CHUNK_SIZE = 5000

# The four vote-table querysets both purge modes operate on - CardPrintingTag/CardArtistVote/
# CardTagVote are per-Card (their card_id feeds the affected-card re-resolution set),
# PrintingTagVote is per-printing (no card FK, no persisted per-printing status to re-resolve).
_VoteQuerySet = QuerySet[CardPrintingTag] | QuerySet[CardArtistVote] | QuerySet[CardTagVote] | QuerySet[PrintingTagVote]


@dataclass(frozen=True)
class PurgeResult:
    dry_run: bool = False
    run_id: str = ""
    all_machine: bool = False
    printing_votes_deleted: int = 0
    artist_votes_deleted: int = 0
    tag_votes_deleted: int = 0
    printing_tag_votes_deleted: int = 0
    affected_card_count: int = 0
    # cards that un-resolved as an EXPECTED, correct consequence of losing machine-only weight -
    # informational, not a violation. See verify_no_machine_only_resolutions' own docstring for
    # why this is the corrected invariant, not "assert status returns to pre-purge state".
    cards_unresolved_by_purge: int = 0
    gate_violations: list[int] = field(default_factory=list)
    # --all-machine only: per-table {source: count} breakdown (the dry-run's confirmation
    # view of the derived _MACHINE_SOURCES blast radius) and the number of PilotRunLedger
    # rows stamped - one per run_id that had votes deleted, not one per purge invocation.
    per_table_source_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    ledger_rows_stamped: int = 0


def verify_no_machine_only_resolutions(card_ids: list[int]) -> list[int]:
    """
    The corrected post-purge invariant (docs/features/catalog-completion-plan.md's Part 1):
    the task's original literal framing - "assert statuses return to pre-run state" - is WRONG
    and would false-positive on the very first real purge. With the real default weights
    (PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MACHINE_WEIGHT=0.5, human vote weight 1.0), 1 human vote
    + 2 agreeing machine votes sums to 2.0 and resolves; purging those 2 machine votes correctly
    drops the weight below threshold and the card LEGITIMATELY un-resolves - that's correct
    consensus recalculation, not a violation.

    The invariant actually worth asserting, mirroring local_identify_printing_tags.
    verify_zero_resolutions' own "structurally impossible but verify against real data" spirit:
    any card still RESOLVED (printing, artist, or a specific tag) after re-resolution must have
    AT LEAST ONE surviving human-backed vote behind that specific outcome. A card resolved with
    only machine-sourced survivors is a real, halting violation - resolve_weighted_consensus's
    own human-backed gate should have made this structurally impossible, so if it happens here
    it means something upstream is broken, not that the purge itself did anything wrong.

    NOTE: this function checks Card-level resolution status only (printing_tag_status,
    artist_vote_status, tag_vote_statuses). PrintingTagVote rows have no persisted per-printing
    resolution status on CanonicalCard today, so per-printing consensus is not checked here.
    When a per-printing resolution status field is added, add the analogous check then.

    Returns the list of violating card pks (empty means clean).
    """
    violations: set[int] = set()
    cards = Card.objects.filter(pk__in=card_ids).prefetch_related("printing_tags", "artist_votes", "tag_votes")
    for card in cards:
        if card.printing_tag_status == PrintingTagStatus.RESOLVED:
            printing_survivors = card.printing_tags.filter(printing=card.inferred_canonical_card, is_no_match=False)
            if not any(is_human_backed_source(v.source) for v in printing_survivors):
                violations.add(card.pk)

        if card.artist_vote_status == ArtistVoteStatus.RESOLVED:
            artist_survivors = card.artist_votes.filter(artist=card.inferred_canonical_artist, is_unknown=False)
            if not any(is_human_backed_source(v.source) for v in artist_survivors):
                violations.add(card.pk)

        for tag_name, status in (card.tag_vote_statuses or {}).items():
            if status not in (TagVoteStatus.RESOLVED_APPLY, TagVoteStatus.RESOLVED_REJECT):
                continue
            tag_survivors = card.tag_votes.filter(tag__name=tag_name)
            if not any(is_human_backed_source(v.source) for v in tag_survivors):
                violations.add(card.pk)

    return sorted(violations)


def _source_breakdown(queryset: _VoteQuerySet) -> dict[str, int]:
    return {row["source"]: row["n"] for row in queryset.values("source").annotate(n=Count("pk")).order_by("source")}


def _delete_in_chunks(queryset: _VoteQuerySet, chunk_size: int) -> int:
    """
    Deletes every matching row in primary-key chunks of `chunk_size`, re-reading the surviving
    matching pks each round (a sliced queryset can't .delete() directly, and one unbounded
    DELETE over hundreds of thousands of rows is exactly what --all-machine must not issue).
    """
    deleted = 0
    while True:
        pks = list(queryset.values_list("pk", flat=True)[:chunk_size])
        if not pks:
            return deleted
        queryset.model.objects.filter(pk__in=pks).delete()
        deleted += len(pks)


def _re_resolve_and_count_unresolved(card_ids: set[int]) -> int:
    """
    Re-resolves printing/artist/tag consensus for every affected card via the purge's three
    resolve_and_persist_* calls (same order), returning how many cards un-resolved as an
    EXPECTED consequence of losing machine-only weight - informational, not a violation (see
    verify_no_machine_only_resolutions' own docstring).
    """
    cards_unresolved = 0
    for card in Card.objects.filter(pk__in=card_ids):
        was_resolved = card.printing_tag_status == PrintingTagStatus.RESOLVED
        resolve_and_persist_printing(card)
        resolve_and_persist_artist(card)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        if was_resolved and card.printing_tag_status != PrintingTagStatus.RESOLVED:
            cards_unresolved += 1
    return cards_unresolved


def purge_run(run_id: str, dry_run: bool = False) -> PurgeResult:
    """
    The actual purge logic (docs/features/catalog-completion-plan.md's Part 1) - a plain,
    testable function, matching this module's own convention of keeping Command.handle() thin
    (see run_name_frequency_elimination/run_content_phash_backfill's identical shape).
    """
    printing_votes = CardPrintingTag.objects.filter(run_id=run_id)
    artist_votes = CardArtistVote.objects.filter(run_id=run_id)
    tag_votes = CardTagVote.objects.filter(run_id=run_id)
    printing_tag_votes = PrintingTagVote.objects.filter(run_id=run_id)

    affected_card_ids: set[int] = set()
    affected_card_ids.update(printing_votes.values_list("card_id", flat=True))
    affected_card_ids.update(artist_votes.values_list("card_id", flat=True))
    affected_card_ids.update(tag_votes.values_list("card_id", flat=True))

    printing_count = printing_votes.count()
    artist_count = artist_votes.count()
    tag_count = tag_votes.count()
    printing_tag_count = printing_tag_votes.count()

    if dry_run:
        return PurgeResult(
            dry_run=True,
            run_id=run_id,
            printing_votes_deleted=printing_count,
            artist_votes_deleted=artist_count,
            tag_votes_deleted=tag_count,
            printing_tag_votes_deleted=printing_tag_count,
            affected_card_count=len(affected_card_ids),
        )

    printing_votes.delete()
    artist_votes.delete()
    tag_votes.delete()
    # PrintingTagVote rows are deleted but require no re-resolution - there is no persisted
    # per-printing resolution status on CanonicalCard today, so consensus is computed on demand.
    printing_tag_votes.delete()

    cards_unresolved = _re_resolve_and_count_unresolved(affected_card_ids)

    gate_violations = verify_no_machine_only_resolutions(sorted(affected_card_ids))

    PilotRunLedger.objects.filter(run_id=run_id).update(purged_at=timezone.now())

    return PurgeResult(
        dry_run=False,
        run_id=run_id,
        printing_votes_deleted=printing_count,
        artist_votes_deleted=artist_count,
        tag_votes_deleted=tag_count,
        printing_tag_votes_deleted=printing_tag_count,
        affected_card_count=len(affected_card_ids),
        cards_unresolved_by_purge=cards_unresolved,
        gate_violations=gate_violations,
    )


def purge_all_machine(dry_run: bool = False, delete_chunk_size: int = _DELETE_CHUNK_SIZE) -> PurgeResult:
    """
    The --all-machine counterpart to purge_run: deletes EVERY machine-sourced vote (source in
    _MACHINE_SOURCES, derived from vote_consensus.is_human_backed_source) across all four vote
    tables, regardless of run_id. This reaches votes purge_run structurally cannot: NULL
    run_id rows (a per-run purge requires a concrete run_id to filter on). Human-backed votes
    (USER/ADMIN) never match the source filter, so they survive even when they share a run_id
    with deleted machine votes.

    Deletes are pk-chunked via _delete_in_chunks rather than one unbounded DELETE per table,
    then every affected card is re-resolved and the verify_no_machine_only_resolutions gate
    runs, both via the same machinery purge_run uses. Every PilotRunLedger row whose run_id
    had votes deleted gets purged_at stamped; run_ids with no ledger row are skipped silently
    (NULL run_id votes have no ledger row by definition).

    `delete_chunk_size` is a parameter (not just the _DELETE_CHUNK_SIZE constant) so tests can
    prove chunking with 2-row chunks instead of writing 5001 rows.
    """
    printing_votes = CardPrintingTag.objects.filter(source__in=_MACHINE_SOURCES)
    artist_votes = CardArtistVote.objects.filter(source__in=_MACHINE_SOURCES)
    tag_votes = CardTagVote.objects.filter(source__in=_MACHINE_SOURCES)
    printing_tag_votes = PrintingTagVote.objects.filter(source__in=_MACHINE_SOURCES)

    affected_card_ids: set[int] = set()
    affected_card_ids.update(printing_votes.values_list("card_id", flat=True))
    affected_card_ids.update(artist_votes.values_list("card_id", flat=True))
    affected_card_ids.update(tag_votes.values_list("card_id", flat=True))

    per_table_source_counts = {
        "printing": _source_breakdown(printing_votes),
        "artist": _source_breakdown(artist_votes),
        "tag": _source_breakdown(tag_votes),
        "printing tag": _source_breakdown(printing_tag_votes),
    }

    if dry_run:
        return PurgeResult(
            dry_run=True,
            all_machine=True,
            printing_votes_deleted=printing_votes.count(),
            artist_votes_deleted=artist_votes.count(),
            tag_votes_deleted=tag_votes.count(),
            printing_tag_votes_deleted=printing_tag_votes.count(),
            affected_card_count=len(affected_card_ids),
            per_table_source_counts=per_table_source_counts,
        )

    # collected BEFORE deleting - after the chunked deletes these querysets match nothing.
    run_ids_with_deleted_votes: set[str] = set()
    for votes in (printing_votes, artist_votes, tag_votes, printing_tag_votes):
        run_ids_with_deleted_votes.update(
            run_id
            for run_id in votes.exclude(run_id__isnull=True).values_list("run_id", flat=True).distinct()
            if run_id is not None
        )

    printing_count = _delete_in_chunks(printing_votes, delete_chunk_size)
    artist_count = _delete_in_chunks(artist_votes, delete_chunk_size)
    tag_count = _delete_in_chunks(tag_votes, delete_chunk_size)
    # PrintingTagVote rows are deleted but require no re-resolution - there is no persisted
    # per-printing resolution status on CanonicalCard today, so consensus is computed on demand.
    printing_tag_count = _delete_in_chunks(printing_tag_votes, delete_chunk_size)

    cards_unresolved = _re_resolve_and_count_unresolved(affected_card_ids)

    gate_violations = verify_no_machine_only_resolutions(sorted(affected_card_ids))

    ledger_rows_stamped = PilotRunLedger.objects.filter(run_id__in=sorted(run_ids_with_deleted_votes)).update(
        purged_at=timezone.now()
    )

    return PurgeResult(
        dry_run=False,
        all_machine=True,
        printing_votes_deleted=printing_count,
        artist_votes_deleted=artist_count,
        tag_votes_deleted=tag_count,
        printing_tag_votes_deleted=printing_tag_count,
        affected_card_count=len(affected_card_ids),
        cards_unresolved_by_purge=cards_unresolved,
        gate_violations=gate_violations,
        per_table_source_counts=per_table_source_counts,
        ledger_rows_stamped=ledger_rows_stamped,
    )


def _raise_for_gate_violations(result: PurgeResult) -> None:
    if result.gate_violations:
        raise CommandError(
            f"GATE VIOLATION: {len(result.gate_violations)} card(s) are RESOLVED with only "
            f"machine-sourced surviving votes behind that outcome, which should be "
            f"structurally impossible per resolve_weighted_consensus's own human-backed gate "
            f"- STOP and investigate before continuing. Affected card pks: "
            f"{result.gate_violations[:50]}" + (" (truncated)" if len(result.gate_violations) > 50 else "")
        )


class Command(BaseCommand):
    help = (
        "Deletes machine-cast votes (docs/features/catalog-completion-plan.md's Part 1) from "
        "CardPrintingTag/CardArtistVote/CardTagVote/PrintingTagVote, then re-resolves every "
        "affected card so stored printing/artist/tag status reflects the surviving votes. Two "
        "mutually exclusive modes, exactly one required (no accidental purge-everything): "
        "--run-id purges exactly one invocation's votes; --all-machine purges EVERY "
        "machine-sourced vote (derived from vote_consensus.is_human_backed_source) regardless "
        "of run_id, including NULL run_id votes a per-run purge can never reach."
    )

    def add_arguments(self, parser: Any) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--run-id", help="Purge exactly this run_id's votes.")
        mode.add_argument(
            "--all-machine",
            action="store_true",
            default=False,
            help="Purge every machine-sourced vote across all tables, regardless of run_id "
            "(including NULL run_id). Human-backed votes are never touched.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print counts without deleting anything or re-resolving any card.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        run_id = kwargs["run_id"]
        all_machine = kwargs["all_machine"]
        dry_run = kwargs["dry_run"]

        # argparse's required mutually-exclusive group enforces this for real CLI invocations;
        # this check covers call_command(run_id=..., all_machine=True)-style kwargs
        # invocations, which bypass the parser's own validation.
        if bool(run_id) == bool(all_machine):
            raise CommandError("Specify exactly one of --run-id or --all-machine.")

        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code (see docs/features/catalog-completion-plan.md's rebuild command) before "
                "running this command."
            )

        if all_machine:
            self._handle_all_machine(dry_run=dry_run)
            return

        mode = "DRY RUN" if dry_run else "WRITE"
        print(f"[{mode}] purge_machine_votes --run-id={run_id}")

        ledger_entry = PilotRunLedger.objects.filter(run_id=run_id).first()
        if ledger_entry is None:
            print(f"(no PilotRunLedger row found for run_id={run_id} - proceeding anyway, purge target is unaffected)")
        else:
            print(
                f"ledger context: command={ledger_entry.command} status={ledger_entry.status} "
                f"dry_run={ledger_entry.dry_run} votes_written={ledger_entry.votes_written} "
                f"started_at={ledger_entry.started_at}"
            )

        result = purge_run(run_id, dry_run=dry_run)

        print(
            f"printing votes: {result.printing_votes_deleted}, "
            f"artist votes: {result.artist_votes_deleted}, "
            f"tag votes: {result.tag_votes_deleted}, "
            f"printing tag votes: {result.printing_tag_votes_deleted}, "
            f"affected cards: {result.affected_card_count}"
        )

        if dry_run:
            print("Dry run - nothing deleted, no card re-resolved.")
            return

        print(
            f"{result.cards_unresolved_by_purge} card(s) correctly un-resolved as a consequence "
            "of losing machine-only weight (expected, not a violation)."
        )

        _raise_for_gate_violations(result)

        print(f"Gate check passed: 0/{result.affected_card_count} affected cards resolved machine-only.")

    def _handle_all_machine(self, dry_run: bool) -> None:
        mode = "DRY RUN" if dry_run else "WRITE"
        print(
            f"[{mode}] purge_machine_votes --all-machine "
            f"(machine sources, derived from vote_consensus.is_human_backed_source: {', '.join(sorted(_MACHINE_SOURCES))})"
        )

        result = purge_all_machine(dry_run=dry_run)

        for table, breakdown in result.per_table_source_counts.items():
            per_source = ", ".join(f"{source}={count}" for source, count in sorted(breakdown.items())) or "none"
            print(f"{table} votes: {per_source} (total {sum(breakdown.values())})")
        print(f"affected cards: {result.affected_card_count}")

        if dry_run:
            print("Dry run - nothing deleted, no card re-resolved.")
            return

        print(
            f"{result.cards_unresolved_by_purge} card(s) correctly un-resolved as a consequence "
            "of losing machine-only weight (expected, not a violation)."
        )
        print(f"stamped purged_at on {result.ledger_rows_stamped} PilotRunLedger row(s).")

        _raise_for_gate_violations(result)

        print(f"Gate check passed: 0/{result.affected_card_count} affected cards resolved machine-only.")
