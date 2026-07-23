"""
The apply-mode sibling of `consensus_impact_report` (read that command first - this module
reuses its iteration/grouping structure and its module docstring's own flagged "worth doing
before running at scale" batching note, which this command is the one that actually does).

Iterates every voted (card, printing)/(card, artist)/(card, tag) pair on record and calls the
REAL `resolve_and_persist_printing`/`resolve_and_persist_artist`/`resolve_and_persist_tag_votes`
paths (from `cardpicker.printing_consensus`/`cardpicker.artist_consensus`/`cardpicker.tag_consensus`
- PROTECTED CORE, imported and called here, never modified) so persisted status matches what the
current, ratified resolver would produce today. This is the command `consensus_impact_report`'s
own docstring calls out as a later, SEPARATELY gated recompute - it authorizes nothing by its
mere existence; running it against production requires fresh, explicit owner go-ahead (see this
change's own PR description) every time, exactly like `purge_machine_votes` does.

`--dry-run` is the DEFAULT and prints the identical transition-summary shape
`consensus_impact_report` does (same "before->after" transition keys, same sample-identifier
list, zero writes performed - by construction, no `resolve_and_persist_*` call is ever made in
this mode). `--apply` performs the real writes and additionally prints, per domain, how many
rows were actually written and how many pairs changed status.

BATCHING. `consensus_impact_report`'s own docstring flags an unbatched, one-query-per-instance
read shape as "worth doing before running this against the full production vote pool" - fixed
here, for this command, as follows (not backported into that command: see this file's own
`_would_be_printing_status`/`_would_be_artist_status` duplication note below for why that's not
the small, clean lift it might first look like):
  - printing/artist: `resolve_and_persist_printing`/`resolve_and_persist_artist` read
    `card.printing_tags.all()`/`card.artist_votes.all()` - a `prefetch_related` per batch (not
    per card) already makes this ONE query per batch of cards, not one per card, so no further
    batching work was needed here.
  - tag: `resolve_and_persist_tag_votes` already resolves every tag on ONE card in a single call
    (3 queries total per card, regardless of how many tags that card has votes for) - so the
    APPLY path is already card-granular, not pair-granular, and needed no further batching either.
    The one place that genuinely walked one query per (card, tag) PAIR was the DRY-RUN read
    path (`resolve_tag`'s own per-instance query shape, inherited by `consensus_impact_report`'s
    `_would_be_tag_status`) - `_batched_tag_would_be_statuses` below fixes exactly that, by
    calling the same `resolve_weighted_consensus`/`is_privileged_vote`/`privileged_weight`/
    `is_human_backed_source` primitives `resolve_tag` does, just grouped across a whole batch's
    votes in one query instead of one query per pair (the same technique
    `tag_consensus.get_resolved_tag_overlay`/`get_suggested_filter_tags_overlay` already use for
    their own, narrower purposes).

TRANSACTIONAL SAFETY. Every batch of `--batch-size` cards (default 500) is committed in its own
`transaction.atomic()` block, not one transaction for the whole run - an interruption (crash,
`kill`, deploy) leaves every already-committed batch durably applied and only the in-flight
batch rolled back, never a half-written batch. A re-run always completes correctly from
wherever it left off, because `resolve_and_persist_printing`/`resolve_and_persist_artist`/
`resolve_and_persist_tag_votes` are themselves idempotent: each is a pure function of the
CURRENT vote rows or (in the tag/CONTESTED-vs-UNRESOLVED case) the current vote rows plus
`get_moderator_user_ids()`, written back on every call regardless of what was there before -
calling any of them twice with no new votes in between produces byte-identical persisted state
both times (printing/artist always re-`save()`, a redundant but harmless UPDATE; tag's own
`resolve_and_persist_tag_votes` goes a step further and skips its `save()`/reindex entirely
when nothing would change, so a re-run over already-recomputed tag pairs performs ZERO writes).

ELASTICSEARCH. `resolve_and_persist_printing` reindexes a card only when the EFFECTIVE indexed
printing id changes (see that function's own `_effective_indexed_printing_id` gate);
`resolve_and_persist_artist` never touches the index at all (artist fields aren't ES-indexed);
`resolve_and_persist_tag_votes` reindexes only when `card.tags` itself changes (not merely when
`tag_vote_statuses` does). Today's dry run found ZERO printing/artist transitions and ZERO
resolved-status flips on tags (only None->UNRESOLVED status-row materializations, which by
definition never touch `card.tags`) - so applying this recompute against the current vote pool
is expected to trigger approximately zero reindex calls, not a 49k-card ES stampede. This isn't
enforced by any throttle in this command (none was needed given that expectation) - if a future
run's vote pool shape actually does flip many resolved outcomes, the per-batch structure above
still bounds the blast radius to one batch's worth of reindex calls at a time rather than all of
them at once, but a dedicated throttle would be worth adding at that point, not before.
"""

from collections import Counter, defaultdict
from typing import Any, Iterable, Iterator

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from cardpicker.artist_consensus import UNKNOWN as ARTIST_UNKNOWN
from cardpicker.artist_consensus import resolve_and_persist_artist, resolve_artist
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.management.commands.consensus_impact_report import DEFAULT_SAMPLE_LIMIT
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardTagVote,
    PilotRunLedger,
    PrintingTagStatus,
    Tag,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.moderation import (
    get_moderator_user_ids,
    is_privileged_vote,
    privileged_weight,
)
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    merge_counters,
    resilient_terminal_output,
)
from cardpicker.printing_consensus import (
    NO_MATCH,
    resolve_and_persist_printing,
    resolve_printing,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha
from cardpicker.vote_consensus import (
    PENDING_PRIVILEGED,
    VoteTuple,
    is_human_backed_source,
    resolve_weighted_consensus,
)

DEFAULT_BATCH_SIZE = 500


def _chunked(items: list[int], size: int) -> Iterator[list[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _would_be_printing_status(card: Card) -> str:
    """
    Exact duplicate of `consensus_impact_report._would_be_printing_status` - kept local rather
    than imported (that function is module-private by its leading underscore, and this file's
    own scope is meant to stay a self-contained management command) - see this module's own
    docstring for why the dry-run path needs a non-writing prediction at all, unlike --apply.
    """
    result = resolve_printing(card)
    if result is None:
        return PrintingTagStatus.UNRESOLVED
    if result == NO_MATCH:
        return PrintingTagStatus.NO_MATCH
    return PrintingTagStatus.RESOLVED


def _would_be_artist_status(card: Card) -> str:
    """Exact duplicate of `consensus_impact_report._would_be_artist_status` - see
    `_would_be_printing_status`'s own comment for why this is duplicated rather than imported."""
    result = resolve_artist(card)
    if result is None:
        distinct_outcomes = {
            ARTIST_UNKNOWN if is_unknown else artist_id
            for is_unknown, artist_id in card.artist_votes.values_list("is_unknown", "artist_id")
        }
        return ArtistVoteStatus.CONTESTED if len(distinct_outcomes) > 1 else ArtistVoteStatus.UNRESOLVED
    if result == ARTIST_UNKNOWN:
        return ArtistVoteStatus.UNKNOWN
    return ArtistVoteStatus.RESOLVED


def _batched_tag_would_be_statuses(
    card_ids: Iterable[int], moderator_ids: set[int]
) -> tuple[dict[tuple[int, int], str], dict[int, str]]:
    """
    Batched equivalent of `consensus_impact_report._would_be_tag_status`, for the DRY-RUN read
    path only (--apply never calls this - see this module's own docstring). Resolves every
    (card, tag) pair with at least one vote among `card_ids` using ONE query for votes plus one
    small `Tag` lookup, instead of `resolve_tag`'s own one-query-per-pair shape - by calling the
    exact same `resolve_weighted_consensus`/`is_privileged_vote`/`privileged_weight`/
    `is_human_backed_source` primitives `resolve_tag` does, just grouped across the whole batch
    up front. Returns `({(card_id, tag_id): status}, {tag_id: tag_name})`.
    """
    rows = list(
        CardTagVote.objects.filter(card_id__in=card_ids).values_list(
            "card_id", "tag_id", "polarity", "source", "user_id"
        )
    )
    if not rows:
        return {}, {}

    tag_ids = {row[1] for row in rows}
    tag_meta: dict[int, tuple[str, str]] = {
        tag_id: (name, moderation_class)
        for tag_id, name, moderation_class in Tag.objects.filter(pk__in=tag_ids).values_list(
            "id", "name", "moderation_class"
        )
    }
    tag_names_by_id = {tag_id: name for tag_id, (name, _) in tag_meta.items()}

    votes_by_pair: dict[tuple[int, int], list[VoteTuple]] = defaultdict(list)
    human_backed_polarities_by_pair: dict[tuple[int, int], set[int]] = defaultdict(set)
    for card_id, tag_id, polarity, source, user_id in rows:
        pair = (card_id, tag_id)
        privileged = is_privileged_vote(source, user_id, moderator_ids)
        votes_by_pair[pair].append(
            VoteTuple(
                outcome_key=polarity,
                weight=privileged_weight(source, privileged),
                is_human_backed=is_human_backed_source(source),
                is_privileged=privileged,
                is_implicit=source == VoteSource.IMPLICIT,
            )
        )
        if is_human_backed_source(source):
            human_backed_polarities_by_pair[pair].add(polarity)

    statuses: dict[tuple[int, int], str] = {}
    for pair, vote_tuples in votes_by_pair.items():
        _, tag_id = pair
        _, moderation_class = tag_meta[tag_id]
        resolved = resolve_weighted_consensus(
            vote_tuples,
            min_weight=settings.PRINTING_TAG_MIN_VOTES,
            min_share=settings.PRINTING_TAG_MIN_SHARE,
            require_privileged=moderation_class == TagModerationClass.SENSITIVE,
        )
        if resolved is PENDING_PRIVILEGED:
            statuses[pair] = TagVoteStatus.PENDING_APPROVAL
        elif resolved == VotePolarity.APPLY:
            statuses[pair] = TagVoteStatus.RESOLVED_APPLY
        elif resolved == VotePolarity.NOT_APPLICABLE:
            statuses[pair] = TagVoteStatus.RESOLVED_REJECT
        else:
            statuses[pair] = (
                TagVoteStatus.CONTESTED
                if len(human_backed_polarities_by_pair.get(pair, ())) > 1
                else TagVoteStatus.UNRESOLVED
            )
    return statuses, tag_names_by_id


def _new_report() -> dict[str, Any]:
    return {
        domain: {"checked": 0, "written": 0, "transitions": Counter(), "samples": defaultdict(list)}
        for domain in ("printing", "artist", "tag")
    }


def _record_transition(section: dict[str, Any], before: Any, after: Any, sample: Any, sample_limit: int) -> None:
    if before != after:
        key = f"{before}->{after}"
        section["transitions"][key] += 1
        if len(section["samples"][key]) < sample_limit:
            section["samples"][key].append(sample)


def _recompute_printing(report: dict[str, Any], apply: bool, batch_size: int, sample_limit: int) -> None:
    section = report["printing"]
    card_ids = list(Card.objects.filter(printing_tags__isnull=False).values_list("id", flat=True).distinct())
    for batch_ids in _chunked(card_ids, batch_size):
        with transaction.atomic():
            cards = Card.objects.filter(pk__in=batch_ids).prefetch_related("printing_tags")
            for card in cards:
                section["checked"] += 1
                before = card.printing_tag_status
                if apply:
                    resolve_and_persist_printing(card)
                    section["written"] += 1
                    after = card.printing_tag_status
                else:
                    after = _would_be_printing_status(card)
                _record_transition(section, before, after, card.identifier, sample_limit)


def _recompute_artist(report: dict[str, Any], apply: bool, batch_size: int, sample_limit: int) -> None:
    section = report["artist"]
    card_ids = list(Card.objects.filter(artist_votes__isnull=False).values_list("id", flat=True).distinct())
    for batch_ids in _chunked(card_ids, batch_size):
        with transaction.atomic():
            cards = Card.objects.filter(pk__in=batch_ids).prefetch_related("artist_votes")
            for card in cards:
                section["checked"] += 1
                before = card.artist_vote_status
                if apply:
                    resolve_and_persist_artist(card)
                    section["written"] += 1
                    after = card.artist_vote_status
                else:
                    after = _would_be_artist_status(card)
                _record_transition(section, before, after, card.identifier, sample_limit)


def _recompute_tag(report: dict[str, Any], apply: bool, batch_size: int, sample_limit: int) -> None:
    section = report["tag"]
    card_ids = list(CardTagVote.objects.values_list("card_id", flat=True).distinct())
    moderator_ids = get_moderator_user_ids()

    for batch_ids in _chunked(card_ids, batch_size):
        with transaction.atomic():
            cards_by_id = {c.pk: c for c in Card.objects.filter(pk__in=batch_ids)}
            if apply:
                # ONE query for the whole batch's (card, tag) pairs that actually have votes -
                # `resolve_and_persist_tag_votes` itself resolves every tag on a card in one
                # call, so this only needs to know WHICH tag names to report on afterwards, not
                # to resolve anything itself.
                tag_names_by_card: dict[int, set[str]] = defaultdict(set)
                for card_id, tag_name in (
                    CardTagVote.objects.filter(card_id__in=batch_ids).values_list("card_id", "tag__name").distinct()
                ):
                    tag_names_by_card[card_id].add(tag_name)

                for card in cards_by_id.values():
                    before_statuses = dict(card.tag_vote_statuses)
                    before_tags = list(card.tags)
                    resolve_and_persist_tag_votes(card)
                    after_statuses = dict(card.tag_vote_statuses)
                    if before_statuses != after_statuses or before_tags != list(card.tags):
                        section["written"] += 1
                    for tag_name in tag_names_by_card.get(card.pk, ()):
                        section["checked"] += 1
                        _record_transition(
                            section,
                            before_statuses.get(tag_name),
                            after_statuses.get(tag_name),
                            (card.identifier, tag_name),
                            sample_limit,
                        )
            else:
                pair_statuses, tag_names_by_id = _batched_tag_would_be_statuses(batch_ids, moderator_ids)
                for (card_id, tag_id), after in pair_statuses.items():
                    pair_card = cards_by_id.get(card_id)
                    pair_tag_name = tag_names_by_id.get(tag_id)
                    if pair_card is None or pair_tag_name is None:
                        continue
                    section["checked"] += 1
                    pair_before = pair_card.tag_vote_statuses.get(pair_tag_name)
                    _record_transition(section, pair_before, after, (pair_card.identifier, pair_tag_name), sample_limit)


def run_consensus_recompute(
    apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, sample_limit: int = DEFAULT_SAMPLE_LIMIT
) -> dict[str, Any]:
    """
    Returns the same report shape `consensus_impact_report.compute_consensus_impact_report`
    does, plus a `"written"` count per domain: `{"printing": {"checked": int, "written": int,
    "transitions": {...}, "samples": {...}}, "artist": {...}, "tag": {...}}`.

    `apply=False` (the default) performs ZERO writes - every read goes through
    `resolve_printing`/`resolve_artist`/`_batched_tag_would_be_statuses`, never their
    `_and_persist_*` counterparts, and `"written"` is always 0. `apply=True` calls the real
    `resolve_and_persist_printing`/`resolve_and_persist_artist`/`resolve_and_persist_tag_votes`
    for every voted pair, batched `batch_size` cards at a time, each batch in its own database
    transaction - see this module's own docstring for the idempotence and ES-side-effect
    reasoning.
    """
    report = _new_report()
    _recompute_printing(report, apply, batch_size, sample_limit)
    _recompute_artist(report, apply, batch_size, sample_limit)
    _recompute_tag(report, apply, batch_size, sample_limit)
    return report


class Command(BaseCommand):
    help = (
        "Apply-mode sibling of consensus_impact_report: re-resolves every voted printing/artist/"
        "tag pair through the current, ratified consensus resolver and (with --apply) PERSISTS "
        "the outcome. --dry-run is the default and performs zero writes, printing the same "
        "transition summary consensus_impact_report does. Intended ONLY for the owner-gated prod "
        "recompute window (docs/features/catalog-completion-plan.md) - running --apply against "
        "production requires fresh, explicit owner authorization every time; this command's mere "
        "existence authorizes nothing. Self-records a PilotRunLedger row (RUNNING at start, "
        "COMPLETED/FAILED at end, per-family pairs_checked/rows_written/transitions counters) "
        "matching every other Stage C/D pilot command's own lifecycle. --apply also requires a "
        "matching COMPLETED dry-run PilotRunLedger row from the last --dry-run-window-hours "
        "(forced-dry-run guard, issue #362) - see --skip-dryrun-check to override."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Perform the real writes. Default is a dry run identical in output shape to "
            "consensus_impact_report, performing zero writes. Requires a matching recent "
            "COMPLETED dry-run ledger row (forced-dry-run guard) unless --skip-dryrun-check is "
            "passed.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Cards processed per database transaction (default {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=DEFAULT_SAMPLE_LIMIT,
            help=f"Max sample identifiers recorded per transition (default {DEFAULT_SAMPLE_LIMIT}).",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        # Forced-dry-run guard (issue #362, Phase 0 rails): this command always operates over the
        # WHOLE voted pool (printing/artist/tag) - no caller-chosen cohort narrower than "the
        # whole command", matching local_calculate_verdicts's own reasoning - so the guard below
        # always passes scope=None.
        add_dry_run_guard_arguments(parser, write_flag="--apply")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's own "
                f"code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - this "
                "image is older than a previously-deployed one. Rebuild with the current code "
                "before running this command."
            )

        apply = kwargs["apply"]
        batch_size = kwargs["batch_size"]
        sample_limit = kwargs["sample_limit"]
        dry_run = not apply
        run_id = kwargs["run_id"] or generate_run_id()

        mode = "APPLY" if apply else "DRY RUN"
        suffix = "" if apply else " - zero writes will occur."
        print(f"[{mode}] consensus_recompute run_id={run_id} --batch-size={batch_size}{suffix}")

        skip_used = enforce_dry_run_precondition(
            command="consensus_recompute",
            write_mode=apply,
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=None,
        )

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="consensus_recompute",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(skip_dryrun_check_used=skip_used),
        )

        try:
            report = run_consensus_recompute(apply=apply, batch_size=batch_size, sample_limit=sample_limit)

            total_written = sum(report[kind]["written"] for kind in ("printing", "artist", "tag"))
            total_changed = sum(sum(report[kind]["transitions"].values()) for kind in ("printing", "artist", "tag"))

            per_family_counters: dict[str, Any] = {
                kind: {
                    "pairs_checked": report[kind]["checked"],
                    "rows_written": report[kind]["written"],
                    "transitions": dict(report[kind]["transitions"]),
                }
                for kind in ("printing", "artist", "tag")
            }
            per_family_counters["total_written"] = total_written
            per_family_counters["total_transitions"] = total_changed

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the terminal transition-summary prints below - a
            # BrokenPipeError on a severed stdout while printing that summary must never look like
            # this run failed.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(ledger.counters, per_family_counters)
            ledger.save(update_fields=["status", "finished_at", "counters"])

            with resilient_terminal_output():
                for kind in ("printing", "artist", "tag"):
                    section = report[kind]
                    written_suffix = f", {section['written']} row(s) written" if apply else ""
                    print(f"=== {kind} ({section['checked']} pair(s) checked{written_suffix}) ===")
                    if not section["transitions"]:
                        print("  no transitions - persisted state already matches the ratified resolver.")
                        continue
                    for transition, count in sorted(section["transitions"].items(), key=lambda item: -item[1]):
                        print(f"  {transition}: {count}")
                        for sample in section["samples"][transition]:
                            print(f"    - {sample}")

                if apply:
                    print(
                        f"APPLY complete - {total_written} row(s) written, {total_changed} status "
                        "transition(s) total."
                    )
                else:
                    print("Dry run complete - zero writes performed.")
        except Exception:
            # Only a still-RUNNING row gets marked FAILED here - a run this invocation already
            # marked COMPLETED above must never be overwritten by a later exception (e.g. from the
            # terminal print, if resilient_terminal_output didn't already swallow it).
            if ledger.status == PilotRunLedger.Status.RUNNING:
                ledger.status = PilotRunLedger.Status.FAILED
                ledger.finished_at = timezone.now()
                ledger.save(update_fields=["status", "finished_at"])
            raise
