"""
2026-07-28 - the FULL-CATALOG streaming driver. Pushes every catalog card with a stable content
hash through the SAME streaming conveyor (`cardpicker.stage_e_dispatch.dispatch_micro_batch`) the
event trigger, the cron backstop sweep and the Phase 3 shakedown driver all use - OCR extraction
(Stage C) and deduction (Stage D) as ONE workflow, one `PilotRunLedger` row per batch, nothing new
in the conveyor itself. Follows `stage_e_shakedown.py`'s driver shape (explicit, fully-enumerated
cohort chunked and fed in), not `stream_backstop_sweep.py`'s (fill-from-the-backlog).

WHY THIS COMMAND EXISTS RATHER THAN A FIX TO THE SWEEP - the two existing drivers structurally
cannot do a full-catalog pass:

  * `stream_backstop_sweep` is a BACKLOG processor. Both of its selectors are "cards that still
    need work" (backlog (a): no CURRENT full-manifest `ImageEvidence` row; backlog (b): current
    evidence but never a join-key vote/scan-log row), so it SKIPS every card that is already done -
    which is most of the catalog, and precisely the cards a re-extraction pass exists to revisit.
    It also TERMINATES on `exhausted=True` from `_cursor_chunk_walk`, and `exhausted=True` means
    only "this cursor reached the end of the pk space and wrapped", not "the backlog is empty" -
    a full-catalog pass driven that way would end at the first lap boundary.
  * `stage_e_shakedown` has the right driver shape but a hardcoded cohort: the issue-#418 Bug-A
    blank-tier-1 tail, with wave-1 sources and the `ntx-0721` run excluded and a REQUIRED
    `--reextracted-after` epoch filter. None of that is parameterisable into "the whole catalog".

THIS COMMAND NEITHER READS NOR ADVANCES EITHER `StageESweepCursor` ROW, AND CANNOT TERMINATE ON A
CURSOR WRAP. That is a structural property of how it calls the conveyor, not a promise it keeps by
convention: every dispatch passes an EXPLICIT `card_ids=<chunk>` together with
`batch_size=len(chunk)`, so `stage_e_dispatch._select_micro_batch` returns at its very FIRST branch
(`if len(seen) >= batch_size: return seen[:batch_size]`) and never reaches the `_cursor_chunk_walk`
backlog fill below it. No `StageESweepCursor.get_cursor`/`try_advance`/`try_wrap` call happens
anywhere on this command's path, so a full-catalog pass can never advance the Stage C sweep cursor
past pk ranges the backstop sweep has not actually examined, and can never be ended early by a
cursor lap. (`cardpicker.stage_e_signals`'s evidence-change echo is separately suppressed inside
`_run_stage_c` via `suppress_evidence_change_echo`, so this command's own Stage C writes do not
queue echo dispatches that WOULD touch the cursors - see `stage_e_shakedown.py`'s own
EVIDENCE-CHANGE ECHO section for that mechanism.)

STAGE 0 - SCRYFALL FRESHNESS, INSIDE THE RUN, EXACTLY ONCE (GitHub issue #513 item 2, owner
ruling: "Freshness belongs inside the streaming process, not as a pre-step... the streaming run
should verify/refresh Scryfall freshness as an integrated stage rather than relying on an
operator-sequenced step before the train starts"). Before batch 0 is dispatched, this command
verifies that the Scryfall printing-metadata cache matches the remote bulk entry and refreshes it
if it does not, by CALLING `cardpicker.printing_metadata_import`'s own entry points - that module
is not modified, and issue #513 item 1 (replacing its freshness mechanism) is separate, explicitly
not-this-change work.

  * ONCE, AT THE START, NEVER DURING THE RUN - and this is the non-obvious constraint, so do not
    "improve" it later by adding a periodic mid-run refresh. Stage D's illustration deduction
    (`cardpicker.local_illustration`) builds its matching index from `CanonicalPrintingMetadata`,
    which is exactly the table a refresh rewrites. Refreshing mid-traversal would change that
    deduction index underneath a running pass: early batches would deduce against one reference
    set and late batches against another, under a SINGLE `run_id`, producing results that are
    neither comparable across the run nor reproducible from it. Stage 0 therefore runs to
    completion before batch 0 dispatches, and never runs again for the lifetime of the invocation.
  * FAIL BEFORE ANY DISPATCH. Any stage-0 failure - network, partial download, import error -
    aborts with a non-zero exit BEFORE a single batch is dispatched, and writes nothing. For a run
    intended to complete unattended across ~230k cards the acceptable outcomes are "did not start"
    and "ran to completion", never "started against stale or half-imported reference data".
  * REPORT WHAT IT DECIDED, including on a RESUME. The verdict (fresh-and-skipped vs
    stale-and-refreshed), the remote `updated_at` it compared against and the local cache's own
    age are all logged. A REFRESH ON A RESUMED RUN is called out loudly: it has exactly the same
    early/late inconsistency problem as a mid-run refresh, only spread across two invocations -
    the batches the first invocation completed were deduced against the OLD reference data.

  `--skip-freshness` bypasses stage 0 entirely; `--require-fresh` makes it verify-only (fail
  rather than refresh, no network write beyond the bulk-data metadata lookup). `--dry-run` skips
  stage 0 too, since a refresh is a real download and a real DB write and dry-run writes nothing.

  NOT IN SCOPE and deliberately absent: any catalog / Google Drive rescan or `update_database`
  stage. That is a different concern with different risk - a stale CATALOG only shrinks the cohort,
  and is self-healing via the event-driven card-create trigger - and issue #513's ruling does not
  cover it.

COHORT: every `Card` with `content_phash__isnull=False`, ordered by pk. NO eligibility filter -
nothing is skipped for being already done, which is the entire point (the conveyor's own
already-done manifest check is what `--reextract` overrides per-invocation). The walk is
KEYSET-paginated (`pk__gt=<last dispatched pk>` LIMIT batch_size, a pure pk-index range scan
per batch) rather than a materialised 230k-element id list or a long-lived server-side cursor held
open across hours of OCR work.

EVERY TUNABLE IS A COMMAND-LINE FLAG. This is the single most important design property of this
command, and it is a deliberate constraint on how it may grow: the operator's working method is
launch, watch, kill, change a setting, relaunch - so changing ANY setting must cost a kill and a
relaunch, never a rebuild and a redeploy. Nothing this command decides may come from
`settings.py`, an env var, or a constant in this file that an operator would plausibly want to
change mid-campaign. (`--batch-size`'s DEFAULT reads `settings.STAGE_E_MICRO_BATCH_SIZE`, which is
different: the flag always wins when passed.)

RESUME: a pk high-water mark persisted to `cardpicker.models.StageEFullCatalogCursor` (a small
dedicated singleton model - see its own docstring for why `StageESweepCursor` is the wrong model
here: wrap/lap semantics and CAS chunk claiming, both actively harmful for this pass) after every
COMPLETED batch. A killed run resumes exactly where it stopped on the next bare invocation.
`--start-pk` overrides the stored mark and RESETS it, so `--start-pk 0` genuinely restarts the
pass rather than snapping back to the old mark on the following invocation. `--sample` and
`--dry-run` runs never read or write the mark at all (a sample is spread across the whole pk space,
so advancing a real pass's resume point from one would jump it to near the end of the catalog).

THIS IS A ONE-SHOT, RUN-TO-COMPLETION DRIVER, NOT A CRON JOB. It is intended to run UNATTENDED
across the whole 230,753-card catalog in a single invocation. That is the difference that shapes
every stop condition below: `stream_backstop_sweep` may stop on any obstacle because it is
cron-invoked and "the next scheduled sweep picks up where this one stopped" is a real recovery
path. THIS COMMAND HAS NO NEXT INVOCATION. Kill-and-relaunch is the operator's contingency if the
design fails, not the expected operating mode - so a stop condition here must be reserved for
conditions that genuinely require a human, and never spent on one that resolves itself in seconds.

STOP CONDITIONS - the two are DELIBERATELY ASYMMETRIC. A throttle is the system being BUSY; a trip
is the system saying STOP.

  * `halted-open-trip` / `halted-new-trip` - HARD STOP, immediately, no retry, no backoff, ever.
    NO SELF-RESUME is a binding design gate (`stage_e_dispatch.py`'s own note): an envelope trip
    requires an explicit human acknowledgement via `resolve_envelope_trip`, and nothing in this
    command may retry past one, sleep and re-sample hoping it clears, or acknowledge it. The
    resume pk is printed and the pass ends.
  * `throttled-concurrency-cap` - BOUNDED EXPONENTIAL BACKOFF AND RETRY OF THE SAME CHUNK, not a
    stop. A throttle means every `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` slot is currently
    held by another in-flight dispatch; it is transient and SELF-CLEARING as those dispatches
    finish. Ending a multi-hour unattended pass on a condition that resolves in seconds would
    strand the run for no reason. The retry sleeps `--throttle-backoff-initial` seconds, doubling
    per consecutive throttle up to `--throttle-backoff-max`, for at most
    `--max-throttle-retries` CONSECUTIVE throttled attempts; the consecutive counter resets to
    zero on any successful dispatch. Exhausting the budget is the genuine "the cap is not
    clearing, a human needs to look" signal: the command then stops, prints the resume pk, and
    exits NON-ZERO.

    THIS IS NOT A BREACH OF `stage_e_dispatch.py`'s OWN CONCERN, IT IS THE MITIGATION THAT CONCERN
    ASKS FOR. That module's docstring (and `stream_backstop_sweep.py`'s) warns specifically
    against a "hot, backoff-free loop" that "would just re-sample an already-saturated cap with no
    backoff... precisely when the host is already at its concurrency ceiling". The objection is to
    the ABSENCE of backoff, not to retrying: an exponential sleep capped at
    `--throttle-backoff-max` makes re-sampling arbitrarily cheap as saturation persists, which is
    exactly what that paragraph asks for, and the bounded consecutive-retry budget keeps the
    worst case finite. Each backoff is logged with its wait and attempt number so an operator
    reading the log can tell a SATURATED pipeline from a STALLED one.

The resume pk is printed on every exit path, whatever the reason.

`--reextract` AND `--short-circuit`/`--no-short-circuit` ARE INDEPENDENT. They used to be one
setting inside the conveyor (`force_stage_c_reextract=True` hardcoded `short_circuit=False`) -
correct for the shakedown's blank-tier-1 cohort, badly wrong here: forcing the full extractor
escalation ladder on 230k mostly-fine cards is 6 extra tesseract calls per card for no recovery
benefit. See `stage_e_dispatch._run_stage_c`'s own "WHY THE TWO WERE CONFLATED, AND WHY THEY NO
LONGER ARE" docstring note. Omitting both short-circuit flags leaves `short_circuit=None`, which
`image_evidence.compute_card_evidence` resolves from the `STAGE_C_NO_SHORTCIRCUIT` env var AT CALL
TIME (`image_evidence._short_circuit_enabled_by_env`) - i.e. the env default still applies unless
the operator overrides it on the command line.

DEFAULT-OFF, same gate as every other streaming entry point (`settings.STAGE_E_STREAMING_ENABLED`)
- this command exits immediately, doing nothing, whenever that flag is False, matching
`stream_backstop_sweep`/`stage_e_shakedown`'s own explicit early-exit convention rather than
relying on `dispatch_micro_batch`'s own `"disabled"` status to no-op silently mid-loop.

PROGRESS OUTPUT IS BUILT FOR AN UNATTENDED RUN - assume nobody is watching most of the time. The
PER-BATCH line is debug-level (emitted to `logger.debug` always, and to stdout only at
`--verbosity 2` or higher), because 9,231 of them at the default batch size is a log nobody reads.
What stdout always carries is a periodic ROLLED-UP SUMMARY, emitted whenever EITHER
`--progress-every-batches` batches have completed OR `--progress-every-seconds` have elapsed since
the last one (whichever comes first), plus once unconditionally at the end. Each summary carries:
cards done, cards remaining, elapsed, the cards/second rate SINCE THE LAST SUMMARY and cumulatively,
a projected completion timestamp, the cumulative throttle-retry count, and - the load-bearing one -
the CURRENT RESUME PK, so that if the process dies unexpectedly (OOM kill, deploy, host reboot) the
log still contains a recent, valid resume point.

RESUME/IDEMPOTENCY IS A SAFETY PROPERTY, NOT THE HOT PATH. A crash, an OOM kill or a deploy
mid-run must be recoverable without redoing completed work, and it is - but the expected case is
ONE long run that completes, so nothing here trades steady-state throughput for cheaper resume.
The mark write is one single-row UPDATE per batch (`StageEFullCatalogCursor.advance`), against a
batch whose own Stage C/D work is measured in tens of seconds - immeasurable next to the work it
protects, so it stays per-batch rather than being batched up or made lossy.

INSTRUMENTATION: nothing new in the ledger - every batch already gets its own `PilotRunLedger` row
via `dispatch_micro_batch` (`command="stage_e_streaming_dispatch"`, `trigger_reason=
"full-catalog"`, which is what separates this pass's rows from `"shakedown"`/`"backstop-sweep"`/
`"evidence-change"` rows in the ledger). This command writes no ledger row of its own.
"""

import argparse
import datetime as dt
import logging
import random
import time
from typing import Any, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.management.commands.stream_backstop_sweep import (
    _HALT_STATUSES,
    _THROTTLED_STATUS,
)
from cardpicker.models import Card, StageEFullCatalogCursor

# STAGE 0 (issue #513 item 2 - see this module's own docstring). These are CALLED, never
# reimplemented, and `cardpicker/printing_metadata_import.py` is NOT modified by this change.
# Three of the four are underscore-private names, imported deliberately and with the trade-off
# stated rather than worked around: that module's only PUBLIC refresh entry point
# (`import_scryfall_printing_metadata`) fuses "check freshness" and "download + import" into one
# call with no way to ask it for the verdict alone, so `--require-fresh` (verify-only, no network
# write) and this stage's own "report what it decided" requirement are both unreachable through
# it. The alternative - reimplementing the freshness comparison here - is strictly worse: it would
# duplicate the sidecar/`updated_at` contract in a second place and let the two drift.
from cardpicker.printing_metadata_import import (
    _cache_path,
    _get_default_cards_entry,
    _is_fresh,
    import_scryfall_printing_metadata,
)
from cardpicker.stage_e_dispatch import DEFAULT_MICRO_BATCH_SIZE, dispatch_micro_batch

logger = logging.getLogger(__name__)


def _sleep(seconds: float) -> None:
    """The throttle backoff's own wait, behind one indirection purely so a test can observe the
    backoff SCHEDULE (`monkeypatch.setattr(stream_full_catalog, "_sleep", recorder)`) without
    actually spending it, and without patching `time.sleep` process-wide for every other thread
    running in the same test session."""
    time.sleep(seconds)


# Same microsecond-precision invocation-timestamp convention `stage_e_shakedown.py` adopted after
# its own drill-found `PilotRunLedger.run_id` UNIQUE-constraint collision (that module's own
# RUN_ID_TIMESTAMP_FORMAT comment): a date-only prefix collides on any SECOND same-day invocation,
# and this command's whole working method is repeated same-day kill-and-relaunch.
RUN_ID_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%f"

TRIGGER_REASON = "full-catalog"

# Throttle backoff defaults (module docstring's STOP CONDITIONS section). Defaults only - every one
# of them is overridable by a flag, per this command's "every tunable is a flag" property. 20
# consecutive retries at this schedule (5, 10, 20, 40, 60, 60, ...) rides out roughly 17 minutes of
# continuous cap saturation before giving up, which is far longer than any transient burst of
# concurrent dispatches can plausibly last and still short enough that a genuinely wedged cap is
# reported the same shift.
DEFAULT_MAX_THROTTLE_RETRIES = 20
DEFAULT_THROTTLE_BACKOFF_INITIAL_S = 5.0
DEFAULT_THROTTLE_BACKOFF_MAX_S = 60.0

# Rolled-up progress summary cadence (module docstring's PROGRESS OUTPUT section) - whichever comes
# first. 25 batches is ~625 cards at the default batch size; 300s bounds how stale the log's own
# resume pk can be when a batch runs long or the pass is riding out a backoff.
DEFAULT_PROGRESS_EVERY_BATCHES = 25
DEFAULT_PROGRESS_EVERY_SECONDS = 300.0


def full_catalog_pk_queryset() -> Any:
    """
    THE cohort: every `Card` with a stable content hash, in pk order, with NO eligibility filter of
    any kind - not the Stage C backlog, not the Stage D backlog, nothing excluded for being already
    done. `content_phash__isnull=False` is not an eligibility filter either: a card without one has
    no stable identity for `ImageEvidence.content_hash` to key against, so `_run_stage_c` skips it
    outright (`if card.content_phash is None: continue`) and `_cursor_chunk_walk` scopes its own
    walk the same way - including such cards would only dispatch batches full of guaranteed no-ops.
    """
    return Card.objects.filter(content_phash__isnull=False).order_by("pk")


def next_chunk_after(after_pk: int, batch_size: int) -> List[int]:
    """
    One keyset-paginated page of the cohort - a pure pk-index range scan bounded by `batch_size`,
    issued fresh per batch. Deliberately NOT a materialised full-cohort id list held across the
    whole run, and deliberately NOT a `.iterator()` server-side cursor held open across hours of
    OCR work between pages: either would tie a multi-hour pass's memory or its DB session to a
    snapshot taken at launch.
    """
    return list(full_catalog_pk_queryset().filter(pk__gt=after_pk).values_list("pk", flat=True)[:batch_size])


def deterministic_sample_pks(sample_size: int) -> List[int]:
    """
    `--sample N`: a deterministic pseudo-random subset of N cards drawn across the WHOLE pk space,
    returned in ascending pk order. For representative throughput measurement - a pk-ordered PREFIX
    of the catalog is not representative (pk order correlates with import order, hence with source,
    hence with image size, language and OCR difficulty), so measuring on one would mis-size the
    real pass.

    SEEDED FROM `sample_size` ITSELF, never from the wall clock: `random.Random(sample_size)` gives
    a dedicated generator instance (never `random.seed()`, which would mutate global RNG state that
    other code in this process may depend on). Two invocations with the same `N` against the same
    catalog therefore select exactly the same cards - so a measurement can be repeated, and a
    killed sample run relaunched with the same `N` and a `--start-pk` covers the remainder of the
    SAME sample rather than a fresh draw. Returned sorted by pk so chunking, progress reporting and
    `--start-pk` all behave identically to a non-sampled run.

    N larger than the catalog yields the whole catalog (`random.Random.sample` would raise on an
    over-large `k`), which is the sensible reading of "sample more cards than exist".
    """
    all_pks = list(full_catalog_pk_queryset().values_list("pk", flat=True))
    if sample_size >= len(all_pks):
        return all_pks
    return sorted(random.Random(sample_size).sample(all_pks, sample_size))


class Command(BaseCommand):
    help = (
        "Push the FULL catalog through the Stage E streaming conveyor (cardpicker.stage_e_dispatch) "
        "- OCR extraction and deduction as one workflow, one ledger row per batch. Unlike "
        "stream_backstop_sweep this processes every card with a content_phash, not just the "
        "backlog, and it never reads or advances either StageESweepCursor. Every tunable is a "
        "flag, so changing one costs a kill and a relaunch, never a redeploy. No-op unless "
        "settings.STAGE_E_STREAMING_ENABLED is True. See this command's own module docstring."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Micro-batch chunk size - both the chunk size the cohort is sliced into AND the "
            "explicit batch_size passed to dispatch_micro_batch for each chunk (the two being "
            "equal is what keeps _select_micro_batch off the sweep-cursor path entirely - see this "
            "command's own module docstring). Default: settings.STAGE_E_MICRO_BATCH_SIZE "
            f"({DEFAULT_MICRO_BATCH_SIZE} if unset).",
        )
        parser.add_argument(
            "--start-pk",
            type=int,
            default=None,
            help="Resume from this Card pk, EXCLUSIVE (the walk starts at pk > this value). "
            "Overrides - and resets - the stored high-water mark, so --start-pk 0 genuinely "
            "restarts the whole pass. Default: whatever the last completed batch stored.",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help="Safety bound on how many micro-batches ONE invocation will dispatch, even if the "
            "catalog has more left (default: unbounded - keep going until the catalog is "
            "exhausted or a stop condition fires).",
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=None,
            help="Process a deterministic pseudo-random subset of N cards drawn across the WHOLE pk "
            "space instead of a pk-ordered prefix - for representative throughput measurement. "
            "Reproducible: the draw is seeded from N itself, never from the clock, so the same N "
            "always selects the same cards. A --sample run never reads or writes the stored "
            "high-water mark (it is a measurement, not catalog progress).",
        )
        parser.add_argument(
            "--reextract",
            action="store_true",
            help="Force Stage C re-extraction regardless of manifest completeness - skips the "
            "conveyor's already-done check so every card in every batch gets a fresh fetch + "
            "extract. INDEPENDENT of --short-circuit/--no-short-circuit.",
        )
        parser.add_argument(
            "--short-circuit",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Force the collector-line OCR tier-1 short-circuit ON (--short-circuit) or OFF "
            "(--no-short-circuit) for this invocation. INDEPENDENT of --reextract. OMITTED (the "
            "default) leaves it at None, which compute_card_evidence resolves from the "
            "STAGE_C_NO_SHORTCIRCUIT env var at call time - i.e. inherit the env default. "
            "--no-short-circuit runs the full extractor escalation ladder on every card (6 extra "
            "tesseract calls per card that would otherwise short-circuit) - correct for a "
            "blank-read cohort, expensive across a whole catalog.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the cohort size and the batch plan, then exit without dispatching "
            "anything. Writes nothing at all - no ledger rows, no high-water mark.",
        )
        parser.add_argument(
            "--skip-freshness",
            action="store_true",
            help="Skip stage 0 (the Scryfall printing-metadata freshness verify/refresh) entirely "
            "- for tests, bounded --sample throughput trials, and resumed runs where the operator "
            "already knows the reference data has not moved.",
        )
        parser.add_argument(
            "--require-fresh",
            action="store_true",
            help="Stage 0 becomes VERIFY-ONLY: fail (non-zero, before any dispatch) if the "
            "Scryfall printing-metadata cache is stale instead of refreshing it. No network write "
            "beyond the bulk-data metadata lookup the check itself needs.",
        )
        parser.add_argument(
            "--max-throttle-retries",
            type=int,
            default=DEFAULT_MAX_THROTTLE_RETRIES,
            help="How many CONSECUTIVE throttled dispatch attempts to ride out (with exponential "
            "backoff between them) before concluding the concurrency cap is not clearing and "
            "stopping with a non-zero exit. The counter resets on any successful dispatch. "
            f"Default {DEFAULT_MAX_THROTTLE_RETRIES}. A throttle is transient and self-clearing, "
            "so this is a retry budget, not a stop condition - see this command's own module "
            "docstring for why it does not conflict with stage_e_dispatch.py's 'hot, backoff-free "
            "loop' warning.",
        )
        parser.add_argument(
            "--throttle-backoff-initial",
            type=float,
            default=DEFAULT_THROTTLE_BACKOFF_INITIAL_S,
            help=f"Seconds to wait after the FIRST consecutive throttled attempt, doubling each "
            f"further consecutive one (default {DEFAULT_THROTTLE_BACKOFF_INITIAL_S}).",
        )
        parser.add_argument(
            "--throttle-backoff-max",
            type=float,
            default=DEFAULT_THROTTLE_BACKOFF_MAX_S,
            help=f"Ceiling on the exponential throttle backoff, in seconds (default "
            f"{DEFAULT_THROTTLE_BACKOFF_MAX_S}).",
        )
        parser.add_argument(
            "--progress-every-batches",
            type=int,
            default=DEFAULT_PROGRESS_EVERY_BATCHES,
            help="Emit a rolled-up progress summary every N completed batches (default "
            f"{DEFAULT_PROGRESS_EVERY_BATCHES}). Whichever of this and "
            "--progress-every-seconds comes first wins; the per-batch line itself is debug-level "
            "(stdout only at --verbosity 2+).",
        )
        parser.add_argument(
            "--progress-every-seconds",
            type=float,
            default=DEFAULT_PROGRESS_EVERY_SECONDS,
            help="Emit a rolled-up progress summary at least this often, in seconds (default "
            f"{DEFAULT_PROGRESS_EVERY_SECONDS}). Bounds how stale the log's own resume pk can be "
            "if the process dies unexpectedly.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Argument validation happens BEFORE the streaming-enabled gate below (stage_e_shakedown's
        # own convention): a bad invocation must never look like a silent, successful no-op.
        # Explicit `is None` rather than the `or` idiom the older drivers use: `--batch-size 0` is
        # falsy, so `or` would silently swallow it into the settings default instead of rejecting
        # it, and a driver whose whole interface is flags must never silently reinterpret one.
        batch_size: Optional[int] = options["batch_size"]
        if batch_size is None:
            batch_size = getattr(settings, "STAGE_E_MICRO_BATCH_SIZE", DEFAULT_MICRO_BATCH_SIZE)
        elif batch_size <= 0:
            raise CommandError("--batch-size must be a positive integer.")
        sample_size: Optional[int] = options["sample"]
        if sample_size is not None and sample_size <= 0:
            raise CommandError("--sample must be a positive integer.")
        max_batches: Optional[int] = options["max_batches"]
        if max_batches is not None and max_batches <= 0:
            raise CommandError("--max-batches must be a positive integer.")
        start_pk: Optional[int] = options["start_pk"]
        if start_pk is not None and start_pk < 0:
            raise CommandError("--start-pk must be zero or a positive integer.")

        max_throttle_retries: int = options["max_throttle_retries"]
        if max_throttle_retries < 0:
            raise CommandError("--max-throttle-retries must be zero or a positive integer.")
        backoff_initial: float = options["throttle_backoff_initial"]
        backoff_max: float = options["throttle_backoff_max"]
        if backoff_initial <= 0 or backoff_max <= 0:
            raise CommandError("--throttle-backoff-initial and --throttle-backoff-max must be positive.")
        if backoff_max < backoff_initial:
            raise CommandError("--throttle-backoff-max must be >= --throttle-backoff-initial.")
        progress_every_batches: int = options["progress_every_batches"]
        progress_every_seconds: float = options["progress_every_seconds"]
        if progress_every_batches <= 0 or progress_every_seconds <= 0:
            raise CommandError("--progress-every-batches and --progress-every-seconds must be positive.")

        reextract: bool = options["reextract"]
        short_circuit: Optional[bool] = options["short_circuit"]
        dry_run: bool = options["dry_run"]
        skip_freshness: bool = options["skip_freshness"]
        require_fresh: bool = options["require_fresh"]
        verbosity: int = options.get("verbosity", 1)

        # Same explicit early-exit convention stream_backstop_sweep.py/stage_e_shakedown.py use -
        # never rely on dispatch_micro_batch's own "disabled" status to no-op silently mid-loop
        # (that status is in neither _HALT_STATUSES nor _THROTTLED_STATUS, so a loop that didn't
        # guard this would count every chunk as a "completed" batch that did nothing).
        if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
            self.stdout.write("STAGE_E_STREAMING_ENABLED is False - stream_full_catalog is a no-op.")
            return

        # STAGE 0 (issue #513 item 2, module docstring): runs to completion HERE - before the
        # cohort is even sized, let alone dispatched - and never again for this invocation.
        if skip_freshness:
            self.stdout.write("STAGE 0 skipped (--skip-freshness) - reference data freshness not verified.")
        elif dry_run:
            self.stdout.write("STAGE 0 skipped (--dry-run writes nothing, and a refresh is a real download + import).")
        else:
            self._run_stage_zero_freshness(
                require_fresh=require_fresh,
                # A stored mark means a PRIOR invocation already dispatched batches against
                # whatever reference data was current then - see _run_stage_zero_freshness.
                is_resume=StageEFullCatalogCursor.get_position() > 0,
            )

        # A --sample run is a measurement, not catalog progress: it neither reads nor writes the
        # stored high-water mark (model docstring). --dry-run writes nothing either way.
        uses_stored_mark = sample_size is None and not dry_run

        if start_pk is not None:
            resume_pk = start_pk
            if uses_stored_mark:
                # --start-pk must OVERRIDE the stored mark, not merely be layered on top of it for
                # one invocation: `advance` is monotonic, so without this reset a --start-pk 0
                # restart would run its first batch and then find the stored mark still parked at
                # the old, much higher position on the next bare invocation.
                StageEFullCatalogCursor.reset_to(start_pk)
            mark_source = "--start-pk"
        elif uses_stored_mark:
            resume_pk = StageEFullCatalogCursor.get_position()
            mark_source = "stored high-water mark"
        else:
            resume_pk = 0
            mark_source = "sample/dry-run (stored mark not consulted)"

        sampled_pks: Optional[List[int]] = None
        if sample_size is not None:
            sampled_pks = [pk for pk in deterministic_sample_pks(sample_size) if pk > resume_pk]
            remaining = len(sampled_pks)
            cohort_description = f"deterministic sample of {sample_size} (seeded from N)"
        else:
            remaining = full_catalog_pk_queryset().filter(pk__gt=resume_pk).count()
            cohort_description = "full catalog (content_phash not null, no eligibility filter)"

        planned_batches = (remaining + batch_size - 1) // batch_size
        if max_batches is not None:
            planned_batches = min(planned_batches, max_batches)

        self.stdout.write(
            f"Cohort: {remaining} cards remaining - {cohort_description}; "
            f"resume_pk={resume_pk} ({mark_source}); batch_size={batch_size}; "
            f"planned_batches={planned_batches}"
            + (f" (bounded by --max-batches={max_batches})" if max_batches is not None else "")
        )
        self.stdout.write(
            f"Stage C: reextract={reextract} short_circuit="
            f"{'inherit-env' if short_circuit is None else short_circuit}"
        )

        if dry_run:
            self.stdout.write(
                f"DRY RUN - dispatching nothing. Would dispatch {planned_batches} batches "
                f"covering {min(remaining, planned_batches * batch_size)} cards, starting at "
                f"pk>{resume_pk}."
            )
            return

        if not remaining:
            self.stdout.write(f"Nothing to do. resume_pk={resume_pk}")
            return

        run_id_prefix = f"stage-e-fullcat-b{batch_size}-{timezone.now().strftime(RUN_ID_TIMESTAMP_FORMAT)}"

        cohort_size = remaining
        batches_dispatched = 0
        cards_done = 0
        total_stage_c = 0
        total_stage_c_transferred = 0
        total_stage_c_fetch_failures = 0
        total_stage_d_votes = 0
        halted_status: Optional[str] = None
        stopped_reason: Optional[str] = None
        started_at = time.monotonic()
        batch_num = 0
        sample_offset = 0
        consecutive_throttles = 0
        total_throttle_retries = 0
        throttle_budget_exhausted = False
        last_summary_at = started_at
        last_summary_cards = 0
        last_summary_batches = 0

        while max_batches is None or batch_num < max_batches:
            if sampled_pks is not None:
                # NOT advanced here - only after a batch actually completes, so a throttle retry
                # re-dispatches the SAME chunk rather than silently skipping it.
                chunk = sampled_pks[sample_offset : sample_offset + batch_size]
            else:
                chunk = next_chunk_after(resume_pk, batch_size)
            if not chunk:
                stopped_reason = "cohort-exhausted"
                self.stdout.write("Cohort exhausted - every card in this pass has been dispatched.")
                break

            # Reused verbatim across a throttle retry of the same chunk: a throttled dispatch
            # writes NO PilotRunLedger row, so re-using its run_id cannot collide with the UNIQUE
            # constraint, and the eventually-successful attempt lands under the run_id its batch
            # index says it should.
            run_id = f"{run_id_prefix}-{batch_num}"
            outcome = dispatch_micro_batch(
                card_ids=chunk,
                trigger_reason=TRIGGER_REASON,
                run_id=run_id,
                # batch_size == len(chunk) is LOAD-BEARING, not incidental: together with an
                # explicit card_ids it makes _select_micro_batch return at its first branch, so no
                # StageESweepCursor is ever read or advanced (module docstring).
                batch_size=len(chunk),
                force_stage_c_reextract=reextract,
                short_circuit=short_circuit,
            )

            if outcome.status in _HALT_STATUSES:
                # BINDING DESIGN GATE (stage_e_dispatch.py's "NO SELF-RESUME"): hard stop, no
                # retry, no backoff, no acknowledgement - ever. Deliberately asymmetric with the
                # throttle branch below: a throttle is the system being BUSY and clears itself, a
                # trip is the system saying STOP and clears only via an explicit human
                # `resolve_envelope_trip`. The batch did no work, so its pks are NOT recorded as
                # done - the relaunch re-dispatches exactly this chunk.
                halted_status = outcome.status
                self.stdout.write(
                    f"[batch {batch_num}] Envelope halt ({outcome.status}, trip_id={outcome.trip_id}) "
                    "- stopping (do not retry, never self-resume). Resolve the trip with "
                    "resolve_envelope_trip (docs/features/stage-e-operations.md) and relaunch."
                )
                break

            if outcome.status == _THROTTLED_STATUS:
                # PROACTIVE cap saturation - TRANSIENT and self-clearing as in-flight dispatches
                # finish, so this is a bounded backoff-and-retry of the same chunk, NOT a stop
                # (module docstring's STOP CONDITIONS section, including why this is the mitigation
                # stage_e_dispatch.py's "hot, backoff-free loop" warning asks for rather than a
                # breach of it). Nothing was done, so no counter advances and no pk is recorded.
                if consecutive_throttles >= max_throttle_retries:
                    throttle_budget_exhausted = True
                    stopped_reason = "throttle-retries-exhausted"
                    self.stdout.write(
                        f"[batch {batch_num}] Dispatch slots still saturated after "
                        f"{consecutive_throttles} consecutive retries (--max-throttle-retries="
                        f"{max_throttle_retries}) - giving up. The concurrency cap is not "
                        "clearing; a human should check for wedged dispatches."
                    )
                    break
                wait_s = min(backoff_initial * (2**consecutive_throttles), backoff_max)
                consecutive_throttles += 1
                total_throttle_retries += 1
                self.stdout.write(
                    f"[batch {batch_num}] Throttled (all concurrency-cap slots held) - backing off "
                    f"{wait_s:.1f}s and retrying the same chunk (attempt {consecutive_throttles}/"
                    f"{max_throttle_retries}). The pipeline is SATURATED, not stalled."
                )
                logger.info(
                    "stream_full_catalog: throttled on batch %s, backing off %.1fs (attempt %s/%s)",
                    batch_num,
                    wait_s,
                    consecutive_throttles,
                    max_throttle_retries,
                )
                _sleep(wait_s)
                continue

            # Any successful dispatch clears the consecutive-throttle budget - the budget bounds a
            # CONTINUOUS saturation episode, not the run's lifetime total.
            consecutive_throttles = 0

            batch_low, batch_high = chunk[0], chunk[-1]
            batches_dispatched += 1
            cards_done += len(chunk)
            if sampled_pks is not None:
                sample_offset += len(chunk)
            total_stage_c += outcome.stage_c_completed
            total_stage_c_transferred += outcome.stage_c_transferred
            total_stage_c_fetch_failures += outcome.stage_c_fetch_failures
            total_stage_d_votes += (
                outcome.stage_d_join_key_votes + outcome.stage_d_fallback_votes + outcome.stage_d_slow_path_routed
            )
            resume_pk = max(resume_pk, batch_high)
            if uses_stored_mark:
                StageEFullCatalogCursor.advance(resume_pk, cards_dispatched=len(chunk))

            elapsed = time.monotonic() - started_at
            batch_line = (
                f"[batch {batch_num}] pk {batch_low}-{batch_high} ({len(chunk)} cards) "
                f"status={outcome.status} stage_c={outcome.stage_c_completed} "
                f"transferred={outcome.stage_c_transferred} "
                f"fetch_failures={outcome.stage_c_fetch_failures} "
                f"stage_d_votes={outcome.stage_d_join_key_votes + outcome.stage_d_fallback_votes} "
                f"| done={cards_done} elapsed={elapsed:.1f}s "
                f"rate={(cards_done / elapsed) if elapsed > 0 else 0.0:.3f} cards/s"
            )
            # DEBUG-LEVEL by design (module docstring's PROGRESS OUTPUT section): ~9,200 of these
            # at the default batch size is a log nobody reads. The rolled-up summary below is what
            # an unattended run's log actually carries.
            logger.debug("stream_full_catalog: %s", batch_line)
            if verbosity >= 2:
                self.stdout.write(batch_line)

            # Bumped ONLY here, at the bottom of a COMPLETED iteration (never on a throttle retry -
            # that must re-dispatch the same chunk under the same run_id) - it is both the
            # `--max-batches` bound and the run_id's own uniquifying suffix, and
            # `PilotRunLedger.run_id` carries a UNIQUE constraint (the same drill-found collision
            # class `stage_e_shakedown.RUN_ID_TIMESTAMP_FORMAT`'s own comment documents), so
            # failing to advance it turns the second batch of every invocation into an
            # IntegrityError.
            batch_num += 1

            now = time.monotonic()
            if (
                batches_dispatched - last_summary_batches >= progress_every_batches
                or now - last_summary_at >= progress_every_seconds
            ):
                self._emit_progress_summary(
                    cards_done=cards_done,
                    cohort_size=cohort_size,
                    elapsed=now - started_at,
                    window_cards=cards_done - last_summary_cards,
                    window_seconds=now - last_summary_at,
                    throttle_retries=total_throttle_retries,
                    resume_pk=resume_pk,
                )
                last_summary_at = now
                last_summary_cards = cards_done
                last_summary_batches = batches_dispatched

        # Always one final summary, however the loop ended - so the last thing in the log is a
        # complete, current picture including a valid resume pk.
        final_now = time.monotonic()
        self._emit_progress_summary(
            cards_done=cards_done,
            cohort_size=cohort_size,
            elapsed=final_now - started_at,
            window_cards=cards_done - last_summary_cards,
            window_seconds=final_now - last_summary_at,
            throttle_retries=total_throttle_retries,
            resume_pk=resume_pk,
        )

        elapsed = time.monotonic() - started_at
        self.stdout.write(
            f"DONE batches_dispatched={batches_dispatched} cards_done={cards_done} "
            f"stage_c_completed={total_stage_c} stage_c_transferred={total_stage_c_transferred} "
            f"stage_c_fetch_failures={total_stage_c_fetch_failures} "
            f"stage_d_votes_or_routes={total_stage_d_votes} elapsed={elapsed:.1f}s "
            f"rate={(cards_done / elapsed) if elapsed > 0 else 0.0:.3f} cards/s "
            f"throttle_retries={total_throttle_retries} "
            f"halted={halted_status} stopped_reason={stopped_reason}"
        )
        # Printed on EVERY exit path (module docstring) - the operator's relaunch argument.
        self.stdout.write(f"RESUME resume_pk={resume_pk} (relaunch bare to continue, or --start-pk {resume_pk})")

        if throttle_budget_exhausted:
            # NON-ZERO EXIT, after the summary and the resume pk are already on stdout: an
            # unattended run that gave up on a cap that never cleared is a genuine failure a
            # supervisor/cron wrapper must be able to detect, unlike an ordinary completion.
            raise CommandError(
                f"Stopped after {total_throttle_retries} throttled dispatch attempts "
                f"({consecutive_throttles} consecutive) - the concurrency cap did not clear. "
                f"Resume with --start-pk {resume_pk} once dispatch slots are free."
            )

    def _run_stage_zero_freshness(self, *, require_fresh: bool, is_resume: bool) -> None:
        """
        STAGE 0 (GitHub issue #513 item 2) - verify Scryfall printing-metadata freshness and
        refresh it if stale, ONCE, before any batch is dispatched. See this module's own docstring
        for the three binding properties (once-only and why, fail-before-any-dispatch, report what
        it decided). Every failure path below raises `CommandError`, i.e. a non-zero exit with no
        batch dispatched and nothing written.

        Calls `printing_metadata_import`'s own entry points, never a reimplementation of them.
        `_get_default_cards_entry` is what makes the remote comparison possible at all (it returns
        the live `/bulk-data` entry carrying `updated_at`), `_is_fresh` is that module's own
        verdict, and `import_scryfall_printing_metadata` is the refresh - which repeats the same
        check internally and so re-downloads only if it agrees the cache is stale.
        """
        try:
            entry = _get_default_cards_entry()
        except Exception as exc:  # noqa: BLE001 - any failure here must abort the run, loudly
            raise CommandError(
                f"STAGE 0 FAILED: could not read Scryfall's /bulk-data entry ({exc!r}). Refusing "
                "to start a full-catalog pass against reference data of unknown age. Nothing was "
                "dispatched and nothing was written."
            )

        cache_path = _cache_path()
        age_text = "cache absent"
        if cache_path.exists():
            age_days = (time.time() - cache_path.stat().st_mtime) / 86400.0
            age_text = f"local cache mtime age {age_days:.2f}d"
        fresh = _is_fresh(cache_path, entry)

        if fresh:
            self.stdout.write(
                f"STAGE 0: Scryfall printing metadata is FRESH - skipping refresh "
                f"(remote updated_at={entry.updated_at}, {age_text}, path={cache_path})."
            )
            return

        if require_fresh:
            raise CommandError(
                f"STAGE 0 FAILED: Scryfall printing metadata is STALE and --require-fresh was "
                f"passed (remote updated_at={entry.updated_at}, {age_text}, path={cache_path}). "
                "Refresh it first, or drop --require-fresh to let stage 0 refresh it. Nothing was "
                "dispatched and nothing was written."
            )

        self.stdout.write(
            f"STAGE 0: Scryfall printing metadata is STALE - refreshing now, once, before any "
            f"batch (remote updated_at={entry.updated_at}, {age_text}, path={cache_path})."
        )
        if is_resume:
            # Same early/late inconsistency a mid-run refresh would cause, only spread across two
            # invocations: whatever the prior invocation already dispatched was deduced against the
            # OLD reference set, and everything from here on is deduced against the new one.
            self.stdout.write(
                self.style.WARNING(
                    "STAGE 0 WARNING: this is a RESUMED run and the reference data CHANGED since "
                    "the previous invocation. Batches already completed under the stored "
                    "high-water mark were deduced against the OLD CanonicalPrintingMetadata; "
                    "everything from here on uses the new one. The completed pass will not be "
                    "internally consistent. Consider restarting with --start-pk 0."
                )
            )
            logger.warning(
                "stream_full_catalog stage 0: reference data changed on a RESUMED run - "
                "pre-resume batches used the older CanonicalPrintingMetadata"
            )

        try:
            stats = import_scryfall_printing_metadata()
        except Exception as exc:  # noqa: BLE001 - see this method's own docstring
            raise CommandError(
                f"STAGE 0 FAILED: Scryfall printing-metadata refresh raised {exc!r}. Refusing to "
                "start a full-catalog pass against half-imported reference data. Nothing was "
                "dispatched."
            )
        self.stdout.write(
            f"STAGE 0: refresh complete - created={stats.get('created')} "
            f"updated={stats.get('updated')} deleted={stats.get('deleted')} "
            f"skipped={stats.get('skipped')} no_matching_card={stats.get('no_matching_card')}. "
            "This will NOT run again for the lifetime of this invocation."
        )

    def _emit_progress_summary(
        self,
        *,
        cards_done: int,
        cohort_size: int,
        elapsed: float,
        window_cards: int,
        window_seconds: float,
        throttle_retries: int,
        resume_pk: int,
    ) -> None:
        """The rolled-up, unattended-run progress line (module docstring's PROGRESS OUTPUT
        section). `resume_pk` is the load-bearing field: if the process dies unexpectedly (OOM
        kill, deploy, host reboot) this line is what the log leaves behind to relaunch from.

        `cards_remaining`/`projected completion` are measured against the cohort size sampled ONCE
        at launch - a catalog that grows mid-run makes the projection optimistic, which is stated
        here rather than papered over with a per-summary re-count (an extra full-cohort COUNT every
        few minutes buys nothing an operator would act on)."""
        cards_remaining = max(cohort_size - cards_done, 0)
        cumulative_rate = (cards_done / elapsed) if elapsed > 0 else 0.0
        window_rate = (window_cards / window_seconds) if window_seconds > 0 else 0.0
        if cumulative_rate > 0 and cards_remaining:
            eta_seconds = cards_remaining / cumulative_rate
            projected = (timezone.now() + dt.timedelta(seconds=eta_seconds)).isoformat(timespec="seconds")
            eta_text = f"eta={eta_seconds / 3600:.2f}h projected_completion={projected}"
        else:
            eta_text = "eta=n/a projected_completion=n/a"
        self.stdout.write(
            f"PROGRESS done={cards_done}/{cohort_size} remaining={cards_remaining} "
            f"elapsed={elapsed:.1f}s rate_now={window_rate:.3f} rate_avg={cumulative_rate:.3f} cards/s "
            f"{eta_text} throttle_retries={throttle_retries} resume_pk={resume_pk}"
        )
