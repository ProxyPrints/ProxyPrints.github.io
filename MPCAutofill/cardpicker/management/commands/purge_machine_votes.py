from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError
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
    TagVoteStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.utils import find_stale_applied_migrations
from cardpicker.vote_consensus import is_human_backed_source

# source not in this set means human-backed - same definition vote_consensus.is_human_backed_source
# uses everywhere else in the app, imported directly rather than duplicated.
_MACHINE_SOURCES = {VoteSource.DEDUCTION, VoteSource.OCR}


@dataclass(frozen=True)
class PurgeResult:
    dry_run: bool = False
    run_id: str = ""
    printing_votes_deleted: int = 0
    artist_votes_deleted: int = 0
    tag_votes_deleted: int = 0
    affected_card_count: int = 0
    # cards that un-resolved as an EXPECTED, correct consequence of losing machine-only weight -
    # informational, not a violation. See verify_no_machine_only_resolutions' own docstring for
    # why this is the corrected invariant, not "assert status returns to pre-purge state".
    cards_unresolved_by_purge: int = 0
    gate_violations: list[int] = field(default_factory=list)


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


def purge_run(run_id: str, dry_run: bool = False) -> PurgeResult:
    """
    The actual purge logic (docs/features/catalog-completion-plan.md's Part 1) - a plain,
    testable function, matching this module's own convention of keeping Command.handle() thin
    (see run_name_frequency_elimination/run_content_phash_backfill's identical shape).
    """
    printing_votes = CardPrintingTag.objects.filter(run_id=run_id)
    artist_votes = CardArtistVote.objects.filter(run_id=run_id)
    tag_votes = CardTagVote.objects.filter(run_id=run_id)

    affected_card_ids: set[int] = set()
    affected_card_ids.update(printing_votes.values_list("card_id", flat=True))
    affected_card_ids.update(artist_votes.values_list("card_id", flat=True))
    affected_card_ids.update(tag_votes.values_list("card_id", flat=True))

    printing_count = printing_votes.count()
    artist_count = artist_votes.count()
    tag_count = tag_votes.count()

    if dry_run:
        return PurgeResult(
            dry_run=True,
            run_id=run_id,
            printing_votes_deleted=printing_count,
            artist_votes_deleted=artist_count,
            tag_votes_deleted=tag_count,
            affected_card_count=len(affected_card_ids),
        )

    printing_votes.delete()
    artist_votes.delete()
    tag_votes.delete()

    cards_unresolved = 0
    for card in Card.objects.filter(pk__in=affected_card_ids):
        was_resolved = card.printing_tag_status == PrintingTagStatus.RESOLVED
        resolve_and_persist_printing(card)
        resolve_and_persist_artist(card)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        if was_resolved and card.printing_tag_status != PrintingTagStatus.RESOLVED:
            cards_unresolved += 1

    gate_violations = verify_no_machine_only_resolutions(sorted(affected_card_ids))

    PilotRunLedger.objects.filter(run_id=run_id).update(purged_at=timezone.now())

    return PurgeResult(
        dry_run=False,
        run_id=run_id,
        printing_votes_deleted=printing_count,
        artist_votes_deleted=artist_count,
        tag_votes_deleted=tag_count,
        affected_card_count=len(affected_card_ids),
        cards_unresolved_by_purge=cards_unresolved,
        gate_violations=gate_violations,
    )


class Command(BaseCommand):
    help = (
        "Deletes exactly one invocation's machine-cast votes (docs/features/"
        "catalog-completion-plan.md's Part 1) - CardPrintingTag/CardArtistVote/CardTagVote rows "
        "stamped with the given run_id, then re-resolves every affected card so stored "
        "printing/artist/tag status reflects the surviving votes. Refuses to run without "
        "--run-id (no accidental purge-everything)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--run-id", required=True, help="Purge exactly this run_id's votes.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print counts without deleting anything or re-resolving any card.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code (see docs/features/catalog-completion-plan.md's rebuild command) before "
                "running this command."
            )

        run_id = kwargs["run_id"]
        dry_run = kwargs["dry_run"]

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
            f"affected cards: {result.affected_card_count}"
        )

        if dry_run:
            print("Dry run - nothing deleted, no card re-resolved.")
            return

        print(
            f"{result.cards_unresolved_by_purge} card(s) correctly un-resolved as a consequence "
            "of losing machine-only weight (expected, not a violation)."
        )

        if result.gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) are RESOLVED with only "
                f"machine-sourced surviving votes behind that outcome, which should be "
                f"structurally impossible per resolve_weighted_consensus's own human-backed gate "
                f"- STOP and investigate before continuing. Affected card pks: "
                f"{result.gate_violations[:50]}" + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        print(f"Gate check passed: 0/{result.affected_card_count} affected cards resolved machine-only.")
