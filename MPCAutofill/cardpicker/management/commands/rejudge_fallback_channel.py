"""
Fallback-channel re-judge tooling (compare-and-retract-on-change for the
`stage-d-fallback-v1` channel): re-derives the fallback calculator's OWN conclusion for each
targeted card via `local_calculate_verdicts.calculate_fallback_verdict` - the EXISTING,
unmodified verdict function, not a re-derivation of its border/artist/symbol sub-check logic -
from the card's CURRENT stored `ImageEvidence` (`layout_class`, `artist_ocr_name`,
`symbol_phash`) and `CanonicalCard` artist/border metadata, then compares that fresh conclusion
against what's actually RECORDED (the card's current `stage-d-fallback-v1` `CardPrintingTag`
vote or `CardScanLog` skip row). Retracts (deletes) the recorded vote/scan-log rows for exactly
the cards where the conclusion changed, so the card becomes eligible again for
`run_fallback_calculator`'s own eligibility query on its next invocation.

ZERO IMAGE FETCHES, ZERO RE-PARSE: unlike `reparse_collector_evidence` (whose whole point is
re-running a PARSER over stored raw text), the fallback calculator's inputs need no parse step
at all - `layout_class`/`artist_ocr_name`/`symbol_phash` are consumed verbatim off the current
`ImageEvidence` row, exactly as `run_fallback_calculator` itself consumes them. A fresh verdict
that differs from the recorded one therefore means one of two things, both genuine re-judge
triggers: the stored EVIDENCE changed underneath the recorded conclusion (a re-extraction
refreshed `layout_class`/`artist_ocr_name`/`symbol_phash` after the vote/scan row was written),
or the calculator's own CODE changed (a future fix to `calculate_fallback_verdict` or one of
its sub-checks). This command never tries to distinguish the two - the recorded-vs-fresh
comparison is the honest signal either way, same as `reparse_collector_evidence`'s own "WHY
COMPARE AGAINST THE RECORDED VERDICT" reasoning.

NEVER TOUCHES `stage-d-join-key-v1` ROWS: fallback eligibility is GATED on the join-key
calculator's no-hit state existing at all (`_fallback_eligible_cards_queryset` - a real
`is_no_match` join-key vote, or a non-rescannable join-key skip in `JOIN_KEY_NO_HIT_SKIP_
REASONS`). Deleting a join-key row would eject the card from the fallback population entirely -
the exact opposite of what a re-judge wants (the card re-eligible for the fallback channel's
OWN next pass). Only `stage-d-fallback-v1` rows are ever deleted here, and only after the
recorded-vs-fresh comparison proves the fallback channel's own conclusion actually changed.

SAFETY GATE (mirrors `reparse_collector_evidence`'s own, deliberately the MORE CONSERVATIVE
card-level reading): never retracts a card whose `printing_consensus.resolve_printing(card)` is
not `None` - this covers BOTH a resolved printing AND a resolved `NO_MATCH` consensus. A stale
machine vote sitting inside an already-settled community decision is safer left for a human to
look at than silently retracted. Gated cards are counted and their pks recorded for human
review, never silently skipped or force-retracted.

TWO-STEP RUNBOOK (same relationship as `reparse_collector_evidence`'s own):

  1. THIS COMMAND - re-derive + retract.
  2. `local_calculate_verdicts` (UNCHANGED by this PR) - once step 1 retracts a card's stale
     fallback vote/scan-log, it is eligible again for `run_fallback_calculator`'s own
     `_fallback_eligible_cards_queryset` and gets a fresh fallback verdict the next time the
     fallback channel runs.

Dry-run by default; `--write` required to persist anything (matches `local_calculate_verdicts`/
`reparse_collector_evidence`/`purge_machine_votes`'s own convention), and `--write` is gated on
a matching COMPLETED dry-run of the EXACT same `--selector`/`--card-ids-file` invocation within
`--dry-run-window-hours` (the issue #362 forced-dry-run guard, via
`cardpicker.pilot_run_lifecycle`).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_calculate_verdicts import (
    STAGE_D_FALLBACK_ANONYMOUS_ID,
    FallbackVerdict,
    _get_cached_candidate_name_index,
    _resolve_candidates_for_card,
    calculate_fallback_verdict,
)
from cardpicker.local_identify_printing_tags import CandidateNameIndex, generate_run_id
from cardpicker.models import (
    Card,
    CardPrintingTag,
    CardScanLog,
    ImageEvidence,
    PilotRunLedger,
)
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)
from cardpicker.printing_consensus import resolve_and_persist_printing, resolve_printing
from cardpicker.utils import (
    find_stale_applied_migrations,
    get_baked_git_sha,
    read_card_ids_file,
)


@dataclass
class RejudgeResult:
    dry_run: bool = False
    run_id: str = ""
    considered: int = 0
    no_evidence: int = 0
    no_prior_fallback_state: int = 0
    unchanged: int = 0
    changed: int = 0
    retracted: int = 0
    gate_refused_card_ids: list[int] = field(default_factory=list)
    # Per-reason breakdown of the recorded->fresh transitions seen across the CHANGED cohort,
    # keyed e.g. "skip:ambiguous -> vote:12345" - persisted onto the ledger row's counters so a
    # re-judge run's own shape is queryable after the fact, not just its totals.
    transitions: dict[str, int] = field(default_factory=dict)
    # capped audit sample, matching ReparseResult/JoinKeyCalculatorResult's own "up to N, for
    # the report" convention elsewhere in this codebase.
    audit: list[dict[str, Any]] = field(default_factory=list)


def select_card_ids_all_channel() -> list[int]:
    """Every card carrying ANY `stage-d-fallback-v1` row at all - a `CardPrintingTag` vote (at
    most one can exist, per that model's own unique constraints) or one or more `CardScanLog`
    skip rows (historical rows from separate runs are never deduplicated away - see that model's
    own docstring). The whole recorded population of the fallback channel, deduplicated to
    distinct card ids."""
    voted = CardPrintingTag.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).values_list("card_id", flat=True)
    scanned = CardScanLog.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).values_list("card_id", flat=True)
    return sorted(set(voted) | set(scanned))


def _current_evidence_for_card(card: Card) -> Optional[ImageEvidence]:
    """The CURRENT `ImageEvidence` row for `card` - the same lookup `run_fallback_calculator`
    itself performs (and `reparse_collector_evidence._current_evidence_for_card`'s own shape,
    deliberately duplicated rather than imported cross-command, matching this codebase's
    established "avoid a hard cross-module coupling for a small helper" convention):
    `content_hash` must match the card's LIVE `content_phash` (a stale evidence row from a prior
    image version is never re-judged against), most-recently-updated row first."""
    if card.content_phash is None:
        return None
    return (
        current_evidence_queryset(card)
        .filter(extractor_versions__has_key="collector_line_ocr")
        .order_by("-updated_at")
        .first()
    )


def _recorded_fallback_state(card: Card) -> Optional[tuple[Any, ...]]:
    """The fallback calculator's own LAST RECORDED conclusion for `card` - a `CardPrintingTag`
    vote (always a genuine match vote, never `is_no_match` - see `FallbackVerdict`'s own
    docstring) or a `CardScanLog` skip row (possibly more than one across separate runs - most
    recent by `scanned_at` wins, matching `_eligible_cards_queryset`'s own "any non-rescannable
    row" exclusion, which doesn't care which run wrote it, only that one exists). `None` means
    the fallback channel has never reached a conclusion for this card at all (only possible
    under an explicit `--card-ids-file` that names a card outside the channel's population) -
    nothing recorded to compare a fresh verdict against, so nothing to retract either."""
    vote = CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).first()
    if vote is not None:
        return ("vote", vote.printing_id)
    scan = (
        CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        .order_by("-scanned_at")
        .first()
    )
    if scan is not None:
        return ("skip", scan.skip_reason)
    return None


def _verdict_state(verdict: FallbackVerdict) -> tuple[Any, ...]:
    """The comparable shape of a freshly-computed `FallbackVerdict` - same (kind, ...) tuple
    shape `_recorded_fallback_state` returns, so the two are directly comparable."""
    if verdict.skip_reason:
        return ("skip", verdict.skip_reason)
    return ("vote", verdict.printing_pk)


def rejudge_and_retract(
    card_ids: list[int],
    run_id: str,
    dry_run: bool = True,
    audit_sample_size: int = 20,
    default_cards_path: Optional[Path] = None,
) -> RejudgeResult:
    """
    The actual re-judge + retract logic (module docstring) - a plain, testable function,
    matching this codebase's own "keep Command.handle() thin" convention
    (`reparse_collector_evidence.reparse_and_retract` / `purge_machine_votes.purge_run`).
    """
    result = RejudgeResult(dry_run=dry_run, run_id=run_id)
    # Lazy, cached `index` (issue #469) - built only once a card actually needs candidate
    # resolution, and shared process-wide with the join-key/fallback calculators themselves,
    # mirroring run_fallback_calculator's own lazy `_get_cached_candidate_name_index()` call
    # rather than reparse_and_retract's older unconditional `CandidateNameIndex()` construction.
    index: Optional[CandidateNameIndex] = None

    for card in Card.objects.filter(pk__in=card_ids).iterator(chunk_size=500):
        evidence = _current_evidence_for_card(card)
        if evidence is None:
            # No CURRENT evidence row to re-derive a verdict from at all (e.g. the card's image
            # changed since the fallback channel recorded its conclusion) - counted and left
            # entirely alone: a re-judge without evidence is not a basis for retraction.
            result.no_evidence += 1
            continue
        result.considered += 1

        recorded_state = _recorded_fallback_state(card)
        if recorded_state is None:
            result.no_prior_fallback_state += 1
            continue

        if index is None:
            index = _get_cached_candidate_name_index()
        candidates = _resolve_candidates_for_card(card.name, index, default_cards_path=default_cards_path)
        fresh_verdict = calculate_fallback_verdict(card.pk, evidence, candidates)
        fresh_state = _verdict_state(fresh_verdict)

        if fresh_state == recorded_state:
            result.unchanged += 1
            continue

        result.changed += 1
        transition = f"{recorded_state[0]}:{recorded_state[1]} -> {fresh_state[0]}:{fresh_state[1]}"
        result.transitions[transition] = result.transitions.get(transition, 0) + 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "recorded": recorded_state, "fresh": fresh_state})

        if dry_run:
            continue

        # SAFETY GATE (module docstring) - card-level, re-checked LIVE (resolve_printing, not the
        # cached printing_tag_status field) - covers BOTH a resolved printing and a resolved
        # NO_MATCH consensus.
        if resolve_printing(card) is not None:
            result.gate_refused_card_ids.append(card.pk)
            continue

        # ONLY this channel's own rows - join-key rows are never touched (module docstring:
        # deleting one would eject the card from the fallback population entirely).
        CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).delete()
        CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).delete()
        resolve_and_persist_printing(card)
        result.retracted += 1

    return result


class Command(BaseCommand):
    help = (
        "Fallback-channel re-judge tooling: re-derives the stage-d-fallback-v1 calculator's own "
        "conclusion from each card's CURRENT stored ImageEvidence (layout_class/artist_ocr_name/"
        "symbol_phash - no re-parse, zero image fetches) and retracts the stale fallback "
        "vote/scan-log for any card whose fallback CONCLUSION changed, so it is eligible again "
        "for run_fallback_calculator's own next pass. NEVER touches stage-d-join-key-v1 rows "
        "(fallback eligibility is gated on the join-key no-hit state existing). Dry-run by "
        "default; --write required to persist anything. --write also requires a matching "
        "COMPLETED dry-run of the SAME --selector/--card-ids-file within --dry-run-window-hours "
        "(forced-dry-run guard, issue #362) - see --skip-dryrun-check to override."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--card-ids-file",
            type=str,
            default=None,
            help="Path to a newline-separated file of explicit card pks to target. Mutually "
            "exclusive with --selector.",
        )
        parser.add_argument(
            "--selector",
            choices=["all-channel"],
            default=None,
            help="all-channel: every card carrying any stage-d-fallback-v1 CardPrintingTag or "
            "CardScanLog row at all - the fallback channel's whole recorded population. "
            "Mutually exclusive with --card-ids-file.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually retract stale fallback votes/scan-logs. Default is dry-run: compute "
            "and count everything without writing. Requires a matching recent COMPLETED dry-run "
            "ledger row for the SAME --selector/--card-ids-file (forced-dry-run guard) unless "
            "--skip-dryrun-check is passed.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        add_dry_run_guard_arguments(parser, write_flag="--write")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        card_ids_file = kwargs["card_ids_file"]
        selector = kwargs["selector"]
        if bool(card_ids_file) == bool(selector):
            raise CommandError("Exactly one of --card-ids-file or --selector is required.")

        # Forced-dry-run guard scope (issue #362): the INPUT that defines this invocation's own
        # target cohort (card_ids_file path, or the selector name) - never the RESOLVED card id
        # set, matching reparse_collector_evidence's own call site and docs/features/catalog-
        # completion-plan.md's "the EXACT same invocation" wording.
        scope = scope_hash("card_ids_file", card_ids_file) if card_ids_file else scope_hash("selector", selector)
        skip_used = enforce_dry_run_precondition(
            command="rejudge_fallback_channel",
            write_mode=kwargs["write"],
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=scope,
        )

        if card_ids_file:
            card_ids = read_card_ids_file(card_ids_file)
        else:
            assert selector == "all-channel"
            card_ids = select_card_ids_all_channel()

        if not card_ids:
            self.stdout.write("No candidate cards found for this selector - nothing to do.")
            return

        run_id = kwargs["run_id"] or generate_run_id()
        dry_run = not kwargs["write"]
        mode = "WRITE" if kwargs["write"] else "DRY RUN"
        self.stdout.write(f"[{mode}] rejudge_fallback_channel run_id={run_id} candidates={len(card_ids)}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="rejudge_fallback_channel",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(scope=scope, skip_dryrun_check_used=skip_used),
        )
        try:
            result = rejudge_and_retract(card_ids, run_id=run_id, dry_run=dry_run)

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the terminal summary prints below - a BrokenPipeError on
            # a severed stdout while printing that summary must never look like this run failed.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            # repurposed for this command: rows this run's own write actually touched (retracted),
            # not "votes cast" (this command casts none) - matches reparse_collector_evidence's
            # own identical repurposing.
            ledger.votes_written = result.retracted
            ledger.counters = merge_counters(
                ledger.counters,
                {
                    "considered": result.considered,
                    "no_evidence": result.no_evidence,
                    "no_prior_fallback_state": result.no_prior_fallback_state,
                    "unchanged": result.unchanged,
                    "changed": result.changed,
                    "retracted": result.retracted,
                    "gate_refused": len(result.gate_refused_card_ids),
                    "gate_refused_card_ids": result.gate_refused_card_ids[:50],
                    "transitions": result.transitions,
                },
            )
            ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])

            with resilient_terminal_output():
                self.stdout.write(
                    f"considered={result.considered} no_evidence={result.no_evidence} "
                    f"no_prior_fallback_state={result.no_prior_fallback_state} "
                    f"unchanged={result.unchanged} changed={result.changed}"
                )
                if dry_run:
                    self.stdout.write(f"(dry-run) would_retract={result.changed - len(result.gate_refused_card_ids)}")
                else:
                    self.stdout.write(f"retracted={result.retracted} gate_refused={len(result.gate_refused_card_ids)}")
                if result.transitions:
                    for transition, count in sorted(result.transitions.items(), key=lambda item: -item[1]):
                        self.stdout.write(f"  transition: {transition} (x{count})")
                if result.gate_refused_card_ids:
                    self.stdout.write(
                        f"HUMAN REVIEW NEEDED - {len(result.gate_refused_card_ids)} card(s) refused "
                        "retraction (currently a RESOLVED consensus - printing or NO_MATCH). Affected "
                        f"card pks: {result.gate_refused_card_ids[:50]}"
                        + (" (truncated)" if len(result.gate_refused_card_ids) > 50 else "")
                    )
                for entry in result.audit[:20]:
                    self.stdout.write(f"  sample: {entry}")
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed) -
            # a no-op if this invocation already reached the COMPLETED save above, otherwise
            # records a triage-able counters["failure_reason"] alongside the FAILED status.
            mark_ledger_failed(ledger, exc)
            raise
