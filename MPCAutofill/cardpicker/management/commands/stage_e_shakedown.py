"""
Stage E Phase 3 - the shakedown driver (issue #465, docs/features/stage-e-operations.md's
"Shakedown driver" subsection is the operator-facing runbook this module implements). Routes the
Bug-A blank-tier-1 tail (issue #418) through the LIVE streaming conveyor
(`cardpicker.stage_e_dispatch.dispatch_micro_batch`), per the owner-ratified sequencing
(docs/proposals/stage-e-streaming.md §6 item 1: the tail "does not get a batch pass") and §10(c)
("micro-batch size is measured, not chosen" - this driver's own per-batch `PilotRunLedger` rows are
that measurement's data source, not this command's own contribution).

COHORT (spec point 1): `_bug_a_tail_card_ids` re-derives issue #418's own blank-tier-1 signature
query FRESH on every invocation - `fetch_ok=True`, empty collector number, blank/whitespace raw
text, scoped to CURRENT evidence (content_hash matching the card's live `content_phash`, the same
convention `reparse_collector_evidence._current_evidence_for_card`/
`local_calculate_verdicts`'s own eligibility queries use), excluding `ntx-0721`'s own
already-force-escalated cohort (docs/data/2026-07-23-zeroing-and-buga-sample.md §9(c)) and
excluding wave-1's own top-4-source slice (docs/pipeline-fidelity-gate.md §15 - CLOSED, re-scanned,
reparsed, landed, and Stage D'd already). NEVER hardcode a count - both the 6,535 and 17,531 figures
cited in the design docs above are dated snapshots, neither current by construction
(stage-e-streaming.md §6 item 1's own note).

DRIVER LOOP (spec point 2, mirrors `stream_backstop_sweep.py`'s own stop-on-halt/throttle posture -
`_HALT_STATUSES`/`_THROTTLED_STATUS` imported from that module, not redefined here): the cohort is
chunked into `--batch-size`-sized groups and fed through `dispatch_micro_batch(card_ids=<chunk>,
trigger_reason="shakedown", batch_size=<chunk size>, force_stage_c_reextract=True)` one chunk at a
time. Every existing gate binds UNMODIFIED - streaming-enabled flag, no-self-resume, fresh envelope
sample, concurrency cap, per-batch ledger row (`command="stage_e_streaming_dispatch"`, this driver
writes no ledger row of its own - spec point 6, "nothing new"). STOPS (never retries) the moment a
batch comes back `halted-*` or `throttled-concurrency-cap` - the exact same posture the backstop
sweep already uses for the same reason (module docstring there: "looping here would just re-sample
an already-saturated cap/an already-open trip with no backoff"). `--max-batches` bounds a single
invocation's own worst case.

FORCED RE-EXTRACTION (spec point 3, the one conveyor change - see `stage_e_dispatch._run_stage_c`'s
own docstring for the mechanism): `force_stage_c_reextract=True` is passed on every batch this
driver dispatches, unconditionally - the whole reason this command exists is that tail cards already
carry a CURRENT full-manifest `ImageEvidence` row with blank values, so the conveyor's ordinary
already-done check would otherwise skip every one of them.

RE-INVOCATION / RESUME (spec point 4): `--reextracted-after <iso>` (REQUIRED) additionally excludes
any tail card whose CURRENT evidence `updated_at` already postdates that timestamp - i.e. a card
this same shakedown epoch already force-re-extracted. The operator passes the epoch's own start
time (or the timestamp of a prior, killed invocation of the SAME epoch) so a re-invocation after a
kill never re-pays a fetch this epoch already spent (Google fetch quota is the scarce resource
here, not compute) - it picks up exactly where the killed run left off.

EVIDENCE-CHANGE ECHO (spec point 5, corrected per the §8 Tron pass on PR #467 - the original
"fast, cheap no-op either way" characterization below was WRONG, left here struck through in spirit
by this correction rather than silently rewritten): every `persist_evidence` write this driver's
forced re-extraction performs is an ordinary `ImageEvidence` save, so `cardpicker.stage_e_signals`'s
own `_dispatch_on_evidence_change` receiver fires for it exactly as it would for any other Stage C
write - an async `dispatch_for_card(card_id, "evidence-change")` task queues behind it, independent
of this driver's own dispatch calls. That echo calls `dispatch_micro_batch` with NO `batch_size`
passed, so `_select_micro_batch` backfills the echo's own seed card up to the FULL
`STAGE_E_MICRO_BATCH_SIZE` from the Stage C backlog cursor walk - an echo is never just the one
already-current seed card, it is a complete micro-batch. This is cheap (~3.5s fixed overhead, no
extraction) ONLY while the Stage C backlog is genuinely zero at echo time (nothing for
`_select_micro_batch` to backfill with). If the backlog is non-zero, an echo becomes a real
~25-card extraction batch (~95s observed) that itself persists ~25 more `ImageEvidence` rows,
queuing ~24 FURTHER echoes - a cascade, not a fixed cost. Each echo also holds one of the two
`STAGE_E_MAX_CONCURRENT_DISPATCHES` slots for its own duration, so a live echo stream competes
with this driver's own dispatch calls for the same cap and can throttle-stop the driver
(`"throttled-concurrency-cap"`) well before the cohort is exhausted. ACCEPTABLE at bounded-pilot
scale (frozen at filing, still not suppressed here) - the two are distinguishable in the ledger by
`trigger_reason`: this driver's own batches carry `"shakedown"`, an echo dispatch carries
`"evidence-change"`, so the ledger itself shows whether echoes are staying cheap (batch_size stays
at 1) or cascading (batch_size climbs toward STAGE_E_MICRO_BATCH_SIZE). Tron's own condition
(§8 pass on PR #467): the documented fallback (NOT built here, per the frozen spec's own
instruction not to build it preemptively - a suppress-signals flag on `persist_evidence`) becomes
REQUIRED, not optional, before scaling beyond a bounded pilot, if either (a) throttle-stops
dominate the driver's own ledger output, or (b) the Stage C backlog is measured non-zero at run
time (check before invoking, per the operator runbook in docs/features/stage-e-operations.md).

INSTRUMENTATION (spec point 6): nothing new - every batch already gets its own `PilotRunLedger` row
via `dispatch_micro_batch` (elapsed_s/stage_c_completed/stage_c_fetch_failures/peak_rss_mb/etc.,
unchanged by this driver). `run_id` prefix is
`stage-e-shakedown-b<batch-size>-<microsecond-precision invocation timestamp>-<batch-num>` (a
drill-found `PilotRunLedger.run_id` UNIQUE-constraint collision fix on the original date-only
shape - see `RUN_ID_TIMESTAMP_FORMAT`'s own comment) so the 25/50/100-card waves this shakedown
measures against (§10(c)) separate cleanly in the ledger for the #463 analysis, and every
invocation - including a same-day kill-and-resume - gets its own distinct prefix.

DRILL COMPATIBILITY (spec point 7): kill-safe by construction via the resume contract above (spec
point 4) - see docs/features/stage-e-operations.md's "Shakedown driver" subsection for the exact
§7(a)/(b) drill invocation sequences. The drills themselves are owner-polled live runs, not part of
this build.

OUT OF SCOPE (frozen spec): envelope bars, consensus/vote code (PROTECTED CORE), the backstop sweep
itself, and the batch-size DECISION (issue #463 closes only after the waves run and the ledger is
analyzed - this command produces that ledger data, it does not conclude from it).
"""

from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import F, Q
from django.utils import timezone

from cardpicker.management.commands.stream_backstop_sweep import (
    _HALT_STATUSES,
    _THROTTLED_STATUS,
)
from cardpicker.models import ImageEvidence
from cardpicker.stage_e_dispatch import DEFAULT_MICRO_BATCH_SIZE, dispatch_micro_batch

# Issue #418's own wave-1 phasing (docs/pipeline-fidelity-gate.md §15): the top 4 sources, 10,437 of
# the 16,972-card blank-tier-1 pool, already re-scanned + reparsed + landed + Stage D'd and CLOSED -
# excluded here so this driver's own cohort is exactly the still-open tail #418/stage-e-streaming.md
# §6 item 1 name, never the whole pool.
WAVE_1_SOURCE_NAMES = frozenset({"RustyShackleford", "Berndt_Toast83", "MaleMPC", "WarpDandy"})

# docs/data/2026-07-23-zeroing-and-buga-sample.md §9(c): ntx-0721 force-escalated its own cohort
# ahead of the rest of the blank-tier-1 pool being sized - the pool-sizing query itself excludes it,
# reused verbatim here.
FORCE_ESCALATED_RUN_ID = "ntx-0721"

# Drill-found defect (§7(b), fixed post-#465): a date-only prefix
# (`stage-e-shakedown-b<batchsize>-<date>-<chunk>`) collides with `PilotRunLedger.run_id`'s UNIQUE
# constraint on any SECOND same-day invocation - kill-and-resume (spec point 4's own resume
# contract) and every multi-invocation wave die with IntegrityError at the very first batch's
# ledger create. Fixed by including a microsecond-precision invocation-time component, mirroring
# `dispatch_micro_batch`'s own default run_id convention (`stage_e_dispatch.py`'s
# `f"stage-e-stream-{timezone.now().strftime('%Y%m%dT%H%M%S%f')}Z"`) - every invocation gets a
# distinct prefix while the `b<batchsize>` segment stays greppable for the #463 wave analysis.
RUN_ID_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%f"


def bug_a_tail_card_ids(reextracted_after: Optional[datetime] = None) -> List[int]:
    """
    Issue #418's own blank-tier-1 pool query (docs/data/2026-07-23-zeroing-and-buga-sample.md §9(c):
    "the signature query regenerates on demand" - `fetch_ok=True`, empty collector number,
    blank/whitespace raw text, excluding `ntx-0721`), scoped to CURRENT evidence only
    (`content_hash` matching the card's live `content_phash`) and to the still-open tail (excluding
    wave-1's own 4 sources - see module docstring). Re-derived FRESH every call - NEVER cache or
    hardcode a count. Returns a plain, already-evaluated `list[int]` (one query) - every caller
    immediately consumes the whole cohort (chunking, `--limit` slicing, or a test assertion), so
    there's no lazy-evaluation benefit to returning the `QuerySet` itself.

    `reextracted_after`: additionally excludes any card whose CURRENT evidence row's `updated_at` is
    later than this timestamp - spec point 4's resume contract (module docstring).

    Ordered by `card_id` for a stable, deterministic chunk order across a killed-and-resumed
    invocation (so `--limit`/chunking behave the same way twice given the same `--reextracted-after`
    epoch, modulo whatever this same driver has already re-extracted in between).
    """
    queryset = (
        ImageEvidence.objects.filter(
            content_hash=F("card__content_phash"),
            fetch_ok=True,
            collector_line_collector_number="",
        )
        .filter(Q(collector_line_raw_text="") | Q(collector_line_raw_text__regex=r"^\s+$"))
        .exclude(run_id=FORCE_ESCALATED_RUN_ID)
        .exclude(card__source__name__in=WAVE_1_SOURCE_NAMES)
    )
    if reextracted_after is not None:
        queryset = queryset.exclude(updated_at__gt=reextracted_after)
    return list(queryset.order_by("card_id").values_list("card_id", flat=True))


def _parse_reextracted_after(raw: str) -> datetime:
    """ISO 8601, tz-aware or naive (naive is treated as UTC - the server clock is UTC, see
    CLAUDE.md's reporting convention) - raises `ValueError` on anything else, turned into a
    `CommandError` by the caller."""
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


class Command(BaseCommand):
    help = (
        "Stage E Phase 3 shakedown driver (issue #465) - routes the Bug-A blank-tier-1 tail "
        "(issue #418) through the LIVE streaming conveyor (cardpicker.stage_e_dispatch), forcing "
        "Stage C re-extraction past the already-done check for tail cards that already carry "
        "current-but-blank evidence. No-op unless settings.STAGE_E_STREAMING_ENABLED is True (the "
        "conveyor's own default-off gate - this command does not bypass it). See this command's "
        "own module docstring and docs/features/stage-e-operations.md's 'Shakedown driver' "
        "subsection."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reextracted-after",
            type=str,
            required=True,
            help="REQUIRED. ISO 8601 timestamp (e.g. 2026-07-25T00:00:00Z) - the operator's own "
            "shakedown epoch start (or a prior, killed invocation's own timestamp, to resume that "
            "same epoch). Tail cards whose CURRENT ImageEvidence.updated_at already postdates this "
            "are excluded from the cohort, so a re-invocation with the SAME value never re-fetches "
            "a card this epoch already re-extracted (spec point 4 - Google fetch quota is the "
            "scarce resource a kill-and-resume must not burn twice).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Bound the cohort to at most N cards, for a bounded pilot run (default: the whole "
            "re-derived tail).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Micro-batch chunk size - both the chunk size this driver slices the cohort into "
            "AND the explicit batch_size passed to dispatch_micro_batch for each chunk. Default: "
            f"settings.STAGE_E_MICRO_BATCH_SIZE ({DEFAULT_MICRO_BATCH_SIZE} if unset).",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help="Safety bound on how many micro-batches one invocation will dispatch, even if the "
            "cohort has more chunks left (default: unbounded - every chunk of the derived cohort).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Argument validation happens BEFORE the streaming-enabled gate below, so a malformed
        # --reextracted-after is always a CommandError, even against a default (disabled) settings
        # environment - a bad invocation should never look like a silent, successful no-op.
        try:
            reextracted_after = _parse_reextracted_after(options["reextracted_after"])
        except ValueError as exc:
            raise CommandError(f"--reextracted-after must be an ISO 8601 timestamp (e.g. 2026-07-25T00:00:00Z): {exc}")

        # Same explicit early-exit convention stream_backstop_sweep.py's own handle() uses - never
        # rely on dispatch_micro_batch's own "disabled" status to no-op silently mid-loop (that
        # status isn't in _HALT_STATUSES/_THROTTLED_STATUS, so a loop that didn't guard this would
        # count every chunk as a "completed" batch that did nothing).
        if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
            self.stdout.write("STAGE_E_STREAMING_ENABLED is False - shakedown driver is a no-op.")
            return

        batch_size: int = options["batch_size"] or getattr(
            settings, "STAGE_E_MICRO_BATCH_SIZE", DEFAULT_MICRO_BATCH_SIZE
        )
        limit: Optional[int] = options["limit"]
        max_batches: Optional[int] = options["max_batches"]

        cohort_ids = bug_a_tail_card_ids(reextracted_after=reextracted_after)
        if limit is not None:
            cohort_ids = cohort_ids[:limit]

        self.stdout.write(
            f"Cohort: {len(cohort_ids)} cards (issue #418 Bug-A tail, re-derived fresh, "
            f"reextracted_after={reextracted_after.isoformat()}, batch_size={batch_size})"
        )
        if not cohort_ids:
            self.stdout.write("Nothing to do.")
            return

        chunks = [cohort_ids[i : i + batch_size] for i in range(0, len(cohort_ids), batch_size)]
        if max_batches is not None:
            chunks = chunks[:max_batches]

        run_id_prefix = f"stage-e-shakedown-b{batch_size}-{timezone.now().strftime(RUN_ID_TIMESTAMP_FORMAT)}"

        batches_dispatched = 0
        total_stage_c = 0
        total_stage_d_votes = 0
        halted_status: Optional[str] = None
        stopped_reason: Optional[str] = None

        for batch_num, chunk in enumerate(chunks):
            run_id = f"{run_id_prefix}-{batch_num}"
            outcome = dispatch_micro_batch(
                card_ids=chunk,
                trigger_reason="shakedown",
                run_id=run_id,
                batch_size=len(chunk),
                force_stage_c_reextract=True,
            )

            if outcome.status in _HALT_STATUSES:
                halted_status = outcome.status
                self.stdout.write(
                    f"[{batch_num + 1}/{len(chunks)}] Envelope halt ({outcome.status}, "
                    f"trip_id={outcome.trip_id}) - stopping (do not retry). Re-invoke with the SAME "
                    "--reextracted-after once the trip is resolved (docs/features/"
                    "stage-e-operations.md's resolve_envelope_trip runbook)."
                )
                break
            if outcome.status == _THROTTLED_STATUS:
                stopped_reason = outcome.status
                self.stdout.write(
                    f"[{batch_num + 1}/{len(chunks)}] Driver stopped: dispatch slots saturated "
                    "(throttled-concurrency-cap). Re-invoke with the SAME --reextracted-after to "
                    "resume."
                )
                break

            batches_dispatched += 1
            total_stage_c += outcome.stage_c_completed
            total_stage_d_votes += (
                outcome.stage_d_join_key_votes + outcome.stage_d_fallback_votes + outcome.stage_d_slow_path_routed
            )
            self.stdout.write(
                f"[{batch_num + 1}/{len(chunks)}] run_id={run_id} status={outcome.status} "
                f"stage_c_completed={outcome.stage_c_completed} "
                f"stage_c_fetch_failures={outcome.stage_c_fetch_failures} "
                f"stage_d_votes={outcome.stage_d_join_key_votes + outcome.stage_d_fallback_votes}"
            )

        self.stdout.write(
            f"DONE batches_dispatched={batches_dispatched}/{len(chunks)} "
            f"cohort_size={len(cohort_ids)} stage_c_completed={total_stage_c} "
            f"stage_d_votes_or_routes={total_stage_d_votes} halted={halted_status} "
            f"stopped_reason={stopped_reason}"
        )
