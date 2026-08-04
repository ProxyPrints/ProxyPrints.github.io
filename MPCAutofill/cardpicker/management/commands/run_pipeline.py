"""
THE MONOLITH - one command that runs the whole identification pipeline end to end.

Owner brief, 2026-07-30: "1 click". Every stage below already existed and every stage below was
run separately, by hand, in an order carried in an operator's head. Nothing here is a new
inference, a new calculator, or a new heuristic: this module is imports, sequencing, `run_id`
threading and error handling. If a future change adds pipeline LOGIC to this file, that logic is
in the wrong place - it belongs in the stage that owns it.

    manage.py run_pipeline

is a complete, working, from-scratch, whole-catalogue run THAT WRITES. That is a hard
requirement, not a nicety (owner rulings: "a bulk run redoes everything from scratch; flags tell
it to narrow", "default the default things, disable them with flags", and - the polarity, stated
explicitly - "the eventual intention for the monolith is that default is to write and flags are
what prevents it. (opposite)"). Every flag on this command either NARROWS the cohort, DISABLES a
stage, or WITHHOLDS the write. None is a precondition.

THE WRITE POLARITY IS INVERTED RELATIVE TO EVERY STAGE THIS COMMAND CALLS, deliberately, and this
is the single easiest thing here to get wrong. `local_calculate_verdicts`' four calculators,
`local_layout_class_cast.run_layout_class_cast` and
`local_attribute_chip_cast.run_attribute_chip_cast` all default to `dry_run=True` - the correct
default for a command an operator invokes deliberately, and a catastrophic one to INHERIT here,
because a monolith that computes a whole 230k-card pass and persists nothing fails looking exactly
like success: full logs, every stage reporting, zero rows. This command therefore passes
`dry_run` EXPLICITLY at every seam and defaults it to False. The pieces whose default had to be
overridden, in full:

    run_join_key_calculator          dry_run=True  ->  passed False
    run_fallback_calculator          dry_run=True  ->  passed False
    run_illustration_calculator      dry_run=True  ->  passed False
    run_slow_path_calculator         dry_run=True  ->  passed False
    run_layout_class_cast            dry_run=True  ->  passed False
    run_attribute_chip_cast          dry_run=True  ->  passed False

(all six via `stage_e_dispatch._run_stage_d`, which already passed False and now takes the flag as
a parameter). `run_image_evidence_cohort` is the one stage already write-by-default; its
`--dry-run` is forwarded rather than overridden. `import_scryfall_printing_metadata` has no
dry-run mode at all, which is why `--dry-run` SKIPS stage 0 rather than pretending to run it -
the same rule `stream_full_catalog` already documents, and for the same reason: a refresh is a
real download and a real DB write.

`--dry-run` IS A REAL PASS THAT WITHHOLDS THE WRITE, not a plan. Every stage runs, every
calculator reports what it WOULD cast, clustering computes and reports what it WOULD propagate,
and `channel_report` still runs so an operator gets the preview in the shape they will read it in
afterwards. It exits 0: it did what was asked.

NOTE ON `add_dry_run_guard_arguments`. The repo's forced-dry-run PRECONDITION (a `--write` refuses
unless a matching COMPLETED dry-run row exists) is a guard on commands whose default is dry-run;
it is not added here, because a command that writes by default has no `--write` to gate and
requiring an operator to have run a dry-run first would put a flag back in front of the working
run. The one place it still applies is inside Stage C's own `--card-ids-file` path, and this
command forwards `--skip-dryrun-check` for exactly that.

THE SEQUENCE, and why it is this sequence
=========================================

    Stage 0   Scryfall reference refresh          once, at the front
    Stage E   envelope preflight                  before anything is written
    Stage C   evidence extraction, pooled         the run's only network stage
    Stage D   the four calculators + three chips  explicit, in dependency order
    Stage C+  md5/phash cluster vote propagation  the pilot capability no engine had
    Stage E   fidelity gate                       machine-only resolutions must be zero
    end       channel_report                      what did every channel actually produce?

STAGE 0 - SCRYFALL AT THE FRONT. Owner ruling: "the scryfall importer is meant to be wired to the
front of the entire monolith, not run separately." This calls
`stream_full_catalog.run_stage_zero_freshness`, the SAME stage-0 `stream_full_catalog` runs (its
body was lifted to module level for this; see its own docstring), which in turn calls
`printing_metadata_import`'s own entry points. `import_scryfall_printing_metadata` is a full-set
VALUE-DIFFING upsert, so re-running it IS the backfill - it repopulates `face_illustrations` and
picks up any drift, and a re-import against an unchanged bulk file issues no row writes at all.

Once, at the front, never during the run. This is the non-obvious constraint and it is inherited
verbatim: Stage D's illustration deduction builds its matching index from
`CanonicalPrintingMetadata`, exactly the table a refresh rewrites. A mid-run refresh would have
early cards deduced against one reference set and late cards against another under a single
`run_id`, producing results neither comparable across the run nor reproducible from it.

THE RUN RECORDS ITS BULK-FILE VINTAGE. `run_stage_zero_freshness` returns the remote `updated_at`
it compared against, the cache path, the cache's mtime age and whether it refreshed; all of it
lands in this run's `PilotRunLedger.counters["stage_0"]`. A run's conclusions can only be dated if
the run says which Scryfall bulk file it reasoned against.

STAGE C - POOLED, RUN-SCOPED. Delegates to `run_image_evidence_cohort` via `call_command`, which
is the whole point: that command owns the pooled engine (ThreadPoolExecutor fetch -> bounded queue
-> ProcessPoolExecutor compute), the priority ordering, the resume filter, the RSS guard, the
md5 evidence-transfer path and its own ledger row. Re-deriving any of that here would be a second
copy to keep in sync. Two properties it already has and this command must not break:

  - A FRESH `--run-id` REDOES EVERYTHING (PR #645). `already_extracted_card_ids(run_id)` scopes
    the resume filter to rows THIS run wrote, so a new run reconsiders every card. Within-run
    resume still survives a crash: re-invoke with the same `--run-id`.
  - `bleed_diff_mm` IS FILLED BY THIS PASS, with no extra wiring and no backfill command. It was
    97.9% NULL only because the field was added without an extractor version bump, so no existing
    row was ever re-extracted. `image_evidence.compute_card_evidence` already calls
    `local_fallback.compute_bleed_diff_mm` unconditionally (image_evidence.py:976) inside the
    `geometry_bleed` group. A from-scratch run re-extracts every card, so every card gets it.

STAGE D - EXPLICIT, NOT BY ECHO. Owner ruling: "everything in the conveyor should be running in
the monolith." This calls `stage_e_dispatch._run_stage_d` DIRECTLY, with `batch_ids=None` (bulk
mode - see that function's own docstring). It deliberately does NOT rely on the pooled runner's
`post_save` echo into the conveyor: that dependency is implicit, it runs one micro-batch at a time
under the streaming envelope, and it is exactly what left the Stage D route unestablished (#618).

Calling `_run_stage_d` rather than re-listing its calls is the point. It is the one place the
order lives, and the order is load-bearing (PR #604): join-key -> fallback -> illustration ->
slow-path, then the three attribute chips. The asymmetry is the correctness argument - a
calculator's `run_id` narrows its OWN progress, never an UPSTREAM verdict. Run-scoping the
upstream selectors would hand downstream calculators an empty pool while reporting success.
`_run_stage_d` also carries the three attribute-chip casters PR #654 wired in (border via
`local_layout_class_cast`, frame-style and bleed-edge via `local_attribute_chip_cast`), which is
how the monolith reaches all three without naming them itself.

STAGE C+ - CLUSTER VOTE PROPAGATION, the capability no engine had. `local_clustering.
compute_two_threshold_clusters` computes distance-0 clusters over stored `content_phash` values -
pure, no fetch, no writes. A d=0 member is an image bit-identical to its representative's.
`local_identify_printing_tags.build_propagated_cluster_votes` (lifted out of `run_pilot`'s closure
for this) then gives every absorbed member its representative's printing verdict, under the same
identity, WITHOUT the member ever being fetched or computed. This is a correctness property first
- identity groups must agree - and a throughput lever second.

WHAT IT PROPAGATES, AND WHY THAT DIFFERS FROM THE PILOT. `run_pilot` propagates its own OCR/phash
votes. The monolith does not carry pilot OCR/phash voting at all (standing owner deferral; Stage
D's join-key already superseded the OCR half). So there is no OCR/phash vote here to propagate,
and the monolith propagates STAGE D's printing verdicts instead - the votes this run actually
cast. Same rule, same guard, same identity discipline, different upstream. See DEVIATIONS in this
change's report.

PILOT OCR/PHASH VOTING IS DELIBERATELY NOT CARRIED. Standing owner deferral: "we have been
deferring the pilot phash until the end, with the expectation that our new pipeline will either
shake out what it needs to identify or render it obsolete." `local_calculate_verdicts.py:221`
records that Stage D's join-key superseded the OCR half.

STAGE E - REUSED, NOT REIMPLEMENTED. `operating_envelope.current_trip` / `check_envelope` and
`stage_e_dispatch._sample_envelope_signals` are called as-is. The throttle behaviour from PR #644
(rate pressure throttles, genuine breaches halt) and the global 7/s ceiling from PR #649 live
BELOW this command, inside `harvest_fetch_limiter` / `harvest_rate_coordinator`, and apply to
Stage C's fetches whether this command knows about them or not - which is why this file does not
mention them again. The fidelity gate is `local_identify_printing_tags.verify_zero_resolutions`,
the same gate `local_calculate_verdicts` runs between its calculators.

END - `channel_report`. Run at the end of the pass, ALWAYS non-gating for this command's own exit
status. Expect exit 1 on the first run: `ZERO_DECLARATIONS` ships empty and there are known-silent
channels. That is the instrument working, and silencing it here would be building the instrument
and suppressing its first reading in the same change.

THE RUN'S IDENTITY IS ITS `run_id`, AND NOTHING ELSE. There is no `--test-mode`, no provisional
marker, no separate table and no weight discount, deliberately. The first run of this command is a
shakedown, but provisionality is a property of our CONFIDENCE, not of the data - it lives in the
ledger and in whatever ruling follows from reading `channel_report`. What makes a later run able
to disregard this one is the from-scratch default: a fresh `run_id` reconsiders every card, and
`local_calculate_verdicts._split_new_printing_tag_votes` supersedes a changed verdict while
`models.purge_stale_machine_votes` archives the old row into `ArchivedCardPrintingTag` first, so
the two generations stay diffable via `local_calculate_verdicts --generation-diff`. The default
`run_id` is therefore self-describing (`monolith-<stage>-<UTC timestamp>`) rather than opaque, and
is printed prominently at the start AND the end so an operator can name this run later.

EXIT CODES - the supervisor contract, matching `stream_full_catalog`'s own table where they
overlap:

    0   the pass ran to completion (or, under `--dry-run`, previewed one). `channel_report`'s
        own verdict is REPORTED, never folded in.
    2   Stage 0 failed. Nothing was dispatched and nothing was written.
    3   the operating envelope halted the run (an open trip, or a fresh breach).
    7   the pass completed but the FIDELITY GATE found machine-only resolutions. Everything is
        written; this is a loud "read this run before trusting it", not a rollback.
"""

import time
from typing import Any, Optional, cast

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.local_clustering import compute_two_threshold_clusters
from cardpicker.local_identify_printing_tags import (
    EXCLUDED_RESOLVED_TAGS,
    build_propagated_cluster_votes,
    verify_zero_resolutions,
)
from cardpicker.management.commands.stream_full_catalog import (
    EXIT_ENVELOPE_HALT,
    run_stage_zero_freshness,
)
from cardpicker.models import (
    Card,
    CardPrintingTag,
    CardTypes,
    PilotRunLedger,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.operating_envelope import check_envelope, current_trip
from cardpicker.pilot_run_lifecycle import (
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
)
from cardpicker.stage_e_batch_sizing import MODE_BULK, resolve_micro_batch_size
from cardpicker.stage_e_dispatch import (
    DispatchOutcome,
    _drain_verdict_transfer_queue,
    _partition_by_md5_verdict,
    _run_stage_d,
    _sample_envelope_signals,
    dispatch_micro_batch,
)
from cardpicker.utils import get_baked_git_sha
from cardpicker.vote_write import purge_and_write_votes

EXIT_FIDELITY_GATE_VIOLATION = 7

# The cohort bound handed to `run_image_evidence_cohort` when the operator has not narrowed the
# run. That command's own `--limit` defaults to 3000 (a pilot-sized default for a pilot-sized
# invocation); a monolith run is whole-catalogue by default, so this passes a bound larger than
# the catalogue rather than inventing an "unbounded" mode that command does not have.
WHOLE_CATALOGUE_LIMIT = 100_000_000

# Suffix distinguishing THIS command's own `PilotRunLedger` row from the row its delegated Stage C
# invocation writes under the same run identity. See `handle`'s own comment for why the data rows,
# not the summary row, keep the unsuffixed name.
LEDGER_RUN_ID_SUFFIX = "-pipeline"

# MINIMUM WALL-CLOCK GAP BETWEEN ENVELOPE SAMPLES during a pass (`_EnvelopeSentry`). Owner brief:
# "do not re-sample so often it becomes its own load." A sample is one `/proc` load read, one RSS
# read and one DB query (`current_trip`; `check_envelope` only writes on an actual breach), so the
# DB round trip is the real cost, not the host reads. 60s is chosen against what the bar actually
# measures rather than tuned by feel: `HOST_LOAD_CEILING` is compared against the ONE-MINUTE load
# average (`os.getloadavg()[0]`, see `stage_e_dispatch._sample_envelope_signals`), so sampling
# faster than 60s re-reads a number that has not finished moving - it cannot detect a breach any
# earlier, it only multiplies queries. Sampling much slower would let a breach persist for longer
# than the window the signal is derived from.
ENVELOPE_RESAMPLE_INTERVAL_SECONDS = 60.0


class Command(BaseCommand):
    help = (
        "THE MONOLITH: run the whole identification pipeline end to end in one command - Scryfall "
        "refresh, pooled Stage C evidence extraction, all four Stage D calculators plus the three "
        "attribute-chip casters, md5/phash cluster vote propagation, the fidelity gate, and "
        "channel_report. A bare invocation is a complete from-scratch whole-catalogue run; every "
        "flag either narrows the cohort or disables a stage."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-id",
            dest="run_id",
            default=None,
            help=(
                "Identity of this run, stamped onto every row it writes and onto its "
                "PilotRunLedger row. Defaults to a self-describing monolith-<UTC timestamp>. A "
                "FRESH run-id redoes everything from scratch; re-passing an EARLIER run-id "
                "resumes that run where it stopped."
            ),
        )
        # ---- cohort narrowing -------------------------------------------------------------
        parser.add_argument(
            "--limit",
            dest="limit",
            type=int,
            default=None,
            help=(
                "Narrow Stage C to the highest-priority N cards. Default: the whole catalogue. "
                "Stage D still runs in bulk mode unless --scope-stage-d-to-cohort is passed."
            ),
        )
        parser.add_argument(
            "--card-ids-file",
            dest="card_ids_file",
            default=None,
            help="Narrow Stage C to an explicit newline-delimited card-id file.",
        )
        parser.add_argument(
            "--scope-stage-d-to-cohort",
            dest="scope_stage_d",
            action="store_true",
            default=False,
            help=(
                "Scope Stage D and cluster propagation to the Stage C cohort instead of the whole "
                "eligible catalogue. Only meaningful alongside --limit/--card-ids-file, and only "
                "advisable for small cohorts: card ids are pushed into every dependency subquery, "
                "which is a large win at batch size 25 and a pathology at catalogue scale."
            ),
        )
        # ---- Stage C engine tunables (forwarded verbatim) ---------------------------------
        parser.add_argument("--workers", dest="workers", type=int, default=None)
        parser.add_argument("--fetch-threads", dest="fetch_threads", type=int, default=None)
        parser.add_argument("--queue-depth", dest="queue_depth", type=int, default=None)
        parser.add_argument("--max-rss-mb", dest="max_rss_mb", type=float, default=None)
        parser.add_argument(
            "--no-shortcircuit",
            dest="no_shortcircuit",
            action="store_true",
            default=False,
            help="Forwarded to Stage C: extract every card fully rather than short-circuiting.",
        )
        parser.add_argument(
            "--skip-dryrun-check",
            dest="skip_dryrun_check",
            action="store_true",
            default=False,
            help=(
                "Forwarded to Stage C's own forced-dry-run guard, which arms only for a "
                "--card-ids-file write. Prominently logged wherever it applies."
            ),
        )
        # ---- stage disable flags (every stage is ON by default) ---------------------------
        parser.add_argument(
            "--skip-freshness",
            dest="skip_freshness",
            action="store_true",
            default=False,
            help="Skip Stage 0 entirely (tests, bounded trials, a resumed run whose data has not moved).",
        )
        parser.add_argument(
            "--require-fresh",
            dest="require_fresh",
            action="store_true",
            default=False,
            help="Make Stage 0 verify-only: fail rather than refresh.",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help=(
                "Run every stage and report what WOULD be written, without writing anything. THE "
                "WRITE IS THE DEFAULT - this flag is the only thing that prevents it. Stage 0 is "
                "skipped under --dry-run (a Scryfall refresh is a real download and a real DB "
                "write, with no preview mode of its own). Exits 0: it did what was asked."
            ),
        )
        parser.add_argument(
            "--batch-size",
            dest="batch_size",
            type=int,
            default=None,
            help="Override chunk size for the per-chunk C→D loop (default: autoscaled).",
        )
        parser.add_argument(
            "--max-batches",
            dest="max_batches",
            type=int,
            default=None,
            help="Stop after N micro-batches (default: process all cards).",
        )
        parser.add_argument(
            "--force-reextract",
            dest="force_reextract",
            action="store_true",
            default=False,
            help="Force re-extraction of Stage C evidence for every card, ignoring prior runs.",
        )
        parser.add_argument("--skip-stage-c", dest="skip_stage_c", action="store_true", default=False)
        parser.add_argument("--skip-stage-d", dest="skip_stage_d", action="store_true", default=False)
        parser.add_argument("--skip-clustering", dest="skip_clustering", action="store_true", default=False)
        parser.add_argument(
            "--skip-envelope",
            dest="skip_envelope",
            action="store_true",
            default=False,
            help="Skip the operating-envelope preflight. Never appropriate for a real bulk run.",
        )
        parser.add_argument("--skip-gate", dest="skip_gate", action="store_true", default=False)
        parser.add_argument("--skip-channel-report", dest="skip_channel_report", action="store_true", default=False)

    # ------------------------------------------------------------------------------------------
    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        run_id: str = options["run_id"] or f"monolith-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"

        self.stdout.write("=" * 78)
        dry_run: bool = options["dry_run"]
        self.stdout.write(f"MONOLITH RUN  run_id={run_id}  mode={'DRY-RUN (writes nothing)' if dry_run else 'WRITE'}")
        self.stdout.write(f"git_sha={get_baked_git_sha()}")
        self.stdout.write(
            "Every row this run writes is stamped with that run_id. It is the ONLY thing that "
            "identifies this run's output - there is no test marker and no separate table."
        )
        self.stdout.write(f"To resume this run after a stop: --run-id {run_id}")
        self.stdout.write("=" * 78)

        # THE ENVELOPE IS SAMPLED THROUGHOUT THE PASS, NOT ONLY BEFORE IT - see `_EnvelopeSentry`.
        # Constructed here rather than inside the preflight because every stage below shares this
        # one instance: it is what carries the interval gate, so the whole pass samples at one
        # cadence instead of each stage re-deciding.
        # `interval_seconds` passed EXPLICITLY from the module constant rather than inherited from
        # the parameter default, so the cadence is resolvable (and overridable) at CALL time - a
        # default bound at `def` time cannot be reached by a test that needs to prove re-sampling
        # happens at all without making the test sleep for a real minute.
        self._envelope = _EnvelopeSentry(
            run_id=run_id, write=self.stdout.write, interval_seconds=ENVELOPE_RESAMPLE_INTERVAL_SECONDS
        )
        envelope_check: Optional[Any] = None if options["skip_envelope"] else self._envelope.check

        counters: dict[str, Any] = {}
        # THE LEDGER ROW'S OWN id IS SUFFIXED; EVERY DATA ROW'S IS NOT. `PilotRunLedger.run_id` is
        # UNIQUE (models.py), one row per run identity - and Stage C is delegated to
        # `run_image_evidence_cohort`, which writes its own row under the run identity it is given.
        # Two rows cannot share one. The choice is therefore which of the two things gets the clean
        # `run_id`: this command's summary row, or every `ImageEvidence`/`CardPrintingTag`/
        # `CardTagVote`/`CardScanLog` row the run produces. It must be the DATA - `channel_report`
        # scopes a channel's run-column counts by the run_id ON THE ROWS, and a Stage C whose
        # evidence carried a different run_id from the votes would read as a silent channel, which
        # is exactly the reading "nothing is culled" exists to make impossible. So the pipeline's
        # own summary row takes the suffix and the pipeline's OUTPUT keeps the name the operator
        # typed. This mirrors `stream_full_catalog`'s own prefix/per-batch-suffix convention.
        ledger = PilotRunLedger.objects.create(
            command="run_pipeline",
            run_id=f"{run_id}{LEDGER_RUN_ID_SUFFIX}",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            # -- STAGE 0 ---------------------------------------------------------------------
            if options["skip_freshness"] or dry_run:
                why = "--skip-freshness" if options["skip_freshness"] else "--dry-run"
                self.stdout.write(f"STAGE 0 skipped ({why}).")
                counters["stage_0"] = {"skipped": True, "reason": why}
            else:
                counters["stage_0"] = run_stage_zero_freshness(
                    require_fresh=options["require_fresh"],
                    is_resume=bool(options["run_id"]),
                    write=self.stdout.write,
                    warn=self.style.WARNING,
                )

            # -- STAGE E PREFLIGHT ------------------------------------------------------------
            self._envelope_preflight(run_id=run_id, skip=options["skip_envelope"])

            # -- STREAMING C→D ----------------------------------------------------------------
            # Per-chunk loop replaces the subprocess Stage C + bulk Stage D. Each chunk goes
            # through `dispatch_micro_batch`, which handles both evidence (C) and verdicts (D).
            cohort_ids: Optional[list[int]] = None

            if options["skip_stage_c"]:
                self.stdout.write("STREAMING C→D skipped (--skip-stage-c).")
                counters["streaming"] = {"skipped": True, "reason": "--skip-stage-c"}
            else:
                counters["streaming"] = self._run_streaming_stages(
                    run_id=run_id,
                    options=options,
                    dry_run=dry_run,
                    envelope_check=envelope_check,
                )

            if envelope_check is not None:
                envelope_check("stage-c-plus")

            if options["scope_stage_d"]:
                from cardpicker.models import ImageEvidence

                cohort_ids = list(
                    ImageEvidence.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct()
                )
                self.stdout.write(f"Cluster propagation scoped to this run's own cohort: {len(cohort_ids)} cards.")

            # -- STAGE C+ : CLUSTER VOTE PROPAGATION -------------------------------------------
            if options["skip_clustering"]:
                self.stdout.write("STAGE C+ clustering skipped (--skip-clustering).")
                counters["clustering"] = {"skipped": True}
            else:
                counters["clustering"] = self._propagate_cluster_votes(
                    run_id=run_id, cohort_ids=cohort_ids, dry_run=dry_run, envelope_check=envelope_check
                )

            # -- STAGE E : FIDELITY GATE -------------------------------------------------------
            gate_violations: list[int] = []
            if dry_run:
                # Nothing was written, so there is no resolution state for the gate to inspect.
                self.stdout.write("FIDELITY GATE skipped (--dry-run wrote no votes to check).")
                counters["fidelity_gate"] = {"skipped": True, "reason": "--dry-run"}
            elif options["skip_gate"]:
                self.stdout.write("FIDELITY GATE skipped (--skip-gate).")
                counters["fidelity_gate"] = {"skipped": True}
            else:
                gate_violations = self._run_fidelity_gate(run_id=run_id)
                counters["fidelity_gate"] = {"violations": len(gate_violations)}

            # -- END : channel_report ----------------------------------------------------------
            if options["skip_channel_report"]:
                self.stdout.write("channel_report skipped (--skip-channel-report).")
                counters["channel_report"] = {"skipped": True}
            else:
                counters["channel_report"] = self._run_channel_report(run_id=run_id)

            counters["elapsed_s"] = round(time.monotonic() - started, 1)
            # How often the envelope actually got sampled, on the run's own ledger row. A pass that
            # reports one sample is a pass that never re-sampled, which is the PR #660 behaviour
            # this fix exists to end - so it is recorded rather than left to be inferred.
            counters["envelope"] = self._envelope.stats()
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(ledger.counters, counters)
            ledger.save(update_fields=["status", "finished_at", "counters"])

            with resilient_terminal_output():
                self.stdout.write("=" * 78)
                self.stdout.write(
                    f"MONOLITH DONE  run_id={run_id}  "
                    f"mode={'DRY-RUN (nothing written)' if dry_run else 'WRITE'}  "
                    f"elapsed={counters['elapsed_s']:.0f}s"
                )
                self.stdout.write(f"Name this run by its run_id: {run_id}")
                self.stdout.write("=" * 78)

            if gate_violations:
                raise CommandError(
                    f"FIDELITY GATE: {len(gate_violations)} card(s) reached a RESOLVED printing "
                    "state on machine votes alone in this run. Everything this run computed is "
                    f"written and is queryable by run_id={run_id}; this exit is a loud 'read this "
                    "run before trusting it', not a rollback.",
                    returncode=EXIT_FIDELITY_GATE_VIOLATION,
                )

        except Exception as exc:  # noqa: BLE001 - see pilot_run_lifecycle.mark_ledger_failed
            # A no-op when this invocation already marked the row COMPLETED above (the gate-
            # violation CommandError path), matching every other long-running command's
            # counters-before-output convention.
            mark_ledger_failed(ledger, exc)
            raise

    # ------------------------------------------------------------------------------------------
    def _envelope_preflight(self, *, run_id: str, skip: bool) -> None:
        """
        The operating envelope's PREFLIGHT - the first sample the sentry takes, forced rather than
        interval-gated, before anything is written. Delegates to `_EnvelopeSentry` so the preflight
        and every mid-pass re-sample are literally the same check; see that class's own docstring
        for the bars, the halt semantics, and why re-sampling exists at all.
        """
        if skip:
            self.stdout.write("STAGE E envelope preflight skipped (--skip-envelope).")
            return
        self._envelope.check("preflight", force=True)
        self.stdout.write("STAGE E: operating envelope clear.")

    # ------------------------------------------------------------------------------------------
    def _run_stage_c(self, *, run_id: str, options: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        """
        Stage C, delegated whole to `run_image_evidence_cohort` - the pooled engine, its priority
        ordering, its run-scoped resume filter (PR #645), its RSS guard, its md5 evidence-transfer
        path and its own ledger row, none of which is re-derived here. Counters are read back off
        THAT command's ledger row rather than returned, because a `call_command` gives no return
        value and inventing a channel for one would mean editing the command to suit this caller.
        """
        argv: list[str] = ["--run-id", run_id]
        if options["card_ids_file"]:
            argv += ["--card-ids-file", options["card_ids_file"]]
        else:
            argv += ["--limit", str(options["limit"] if options["limit"] is not None else WHOLE_CATALOGUE_LIMIT)]
        for flag, key in (
            ("--workers", "workers"),
            ("--fetch-threads", "fetch_threads"),
            ("--queue-depth", "queue_depth"),
        ):
            if options[key] is not None:
                argv += [flag, str(options[key])]
        if options["max_rss_mb"] is not None:
            argv += ["--max-rss-mb", str(options["max_rss_mb"])]
        if options["no_shortcircuit"]:
            argv.append("--no-shortcircuit")
        if options["skip_dryrun_check"]:
            argv.append("--skip-dryrun-check")
        if dry_run:
            # Stage C is the one delegated stage that is ALREADY write-by-default, so this
            # forwards its own flag rather than overriding a default.
            argv.append("--dry-run")

        self.stdout.write(f"STAGE C: run_image_evidence_cohort {' '.join(argv)}")
        call_command("run_image_evidence_cohort", *argv)

        row = (
            PilotRunLedger.objects.filter(command="run_image_evidence_cohort", run_id=run_id)
            .order_by("-started_at")
            .first()
        )
        return dict(row.counters or {}) if row is not None else {}

    # ------------------------------------------------------------------------------------------
    def _run_stage_d_bulk(
        self,
        *,
        run_id: str,
        cohort_ids: Optional[list[int]],
        dry_run: bool = False,
        envelope_check: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Stage D, called EXPLICITLY - `stage_e_dispatch._run_stage_d`, the single place the
        dependency order lives, invoked in bulk mode (`batch_ids=None`). This is deliberately not
        the pooled runner's `post_save` echo into the conveyor: that route is implicit, runs one
        micro-batch at a time under the streaming envelope, and is what left Stage D unestablished.

        Four calculators in dependency order plus the three attribute-chip casters, all of it
        owned by `_run_stage_d`. `DispatchOutcome` is that function's output channel; it is
        constructed here purely to receive the counters.
        """
        self.stdout.write(
            "STAGE D: join-key -> fallback -> illustration -> slow-path, then the border / "
            "frame-style / bleed-edge attribute chips"
            + ("" if cohort_ids is None else f" (scoped to {len(cohort_ids)} cards)")
        )
        outcome = DispatchOutcome(status="monolith", run_id=run_id)
        # `dry_run` PASSED EXPLICITLY. All six calculators/casters underneath default to
        # dry_run=True; inheriting that here would compute a whole pass and persist nothing while
        # every log line and counter still reported success. See this module's docstring.
        # `envelope_check` THREADED IN (2026-07-30). `_run_stage_d` calls it at each seam between
        # its calculators, which is the finest granularity reachable without refactoring all of
        # them - see that function's own docstring for the residual gap that leaves.
        # Stream B: md5 verdict-transfer gate. When Stage D is scoped to a concrete card list,
        # partition by md5 verdict status: cards with an existing run_id verdict skip D and
        # receive their vote via propagation from the batch's rep instead.
        if cohort_ids is not None:
            unresolved_ids, resolved_ids, md5_groups = _partition_by_md5_verdict(cohort_ids, run_id)
            if unresolved_ids:
                _run_stage_d(unresolved_ids, run_id, outcome, dry_run=dry_run, envelope_check=envelope_check)
            if resolved_ids:
                _drain_verdict_transfer_queue(resolved_ids, md5_groups, run_id, outcome)
        else:
            _run_stage_d(None, run_id, outcome, dry_run=dry_run, envelope_check=envelope_check)

        result = {
            "join_key_votes": outcome.stage_d_join_key_votes,
            "join_key_already_voted": outcome.stage_d_join_key_already_voted,
            "fallback_votes": outcome.stage_d_fallback_votes,
            "fallback_already_voted": outcome.stage_d_fallback_already_voted,
            "illustration_votes": outcome.stage_d_illustration_votes,
            "illustration_already_voted": outcome.stage_d_illustration_already_voted,
            "slow_path_routed": outcome.stage_d_slow_path_routed,
            "border_chip_votes": outcome.stage_d_border_chip_votes,
            "frame_chip_votes": outcome.stage_d_frame_chip_votes,
            "bleed_chip_votes": outcome.stage_d_bleed_chip_votes,
            "verdict_transfer_votes": outcome.stage_d_verdict_transfer_votes,
        }
        self.stdout.write(f"STAGE D: {result}")
        return result

    # ------------------------------------------------------------------------------------------
    def _run_streaming_stages(
        self,
        *,
        run_id: str,
        options: dict[str, Any],
        dry_run: bool = False,
        envelope_check: Optional[Any] = None,
    ) -> dict[str, Any]:
        explicit_batch_size: Optional[int] = options.get("batch_size")
        batch_decision = resolve_micro_batch_size(explicit=explicit_batch_size, mode=MODE_BULK)
        batch_size = batch_decision.batch_size
        self.stdout.write(f"STREAMING C→D: {batch_decision.describe()}")
        self.stdout.write(f"STAGE C: run_stage_e_streaming (micro-batches of {batch_size})")
        self.stdout.write(
            "STAGE D: join-key -> fallback -> illustration -> slow-path, then the border / frame / bleed chips"
        )

        max_batches: Optional[int] = options.get("max_batches")
        limit: Optional[int] = options.get("limit")
        short_circuit = False if options.get("no_shortcircuit") else None

        # Each micro-batch's PilotRunLedger row needs a UNIQUE id (`PilotRunLedger.run_id` is a
        # unique constraint), while every data row this pass writes must stay under the operator's
        # clean `run_id` (channel_report scopes by the run_id on the rows - comment above the
        # pipeline's own ledger create). The attempt timestamp makes the ledger id unique across
        # resumes too: re-running `--run-id <same>` re-dispatches batch 0, and its prior-attempt
        # ledger row must not collide (stage_e_dispatch.dispatch_micro_batch's `ledger_run_id`).
        attempt = timezone.now().strftime("%Y%m%dT%H%M%S%f")

        queryset = Card.objects.filter(content_phash__isnull=False).order_by("pk")

        after_pk = 0
        batch_count = 0
        total_cards_scanned = 0
        acc: dict[str, int] = {
            "stage_c_completed": 0,
            "stage_c_transferred": 0,
            "stage_c_fetch_failures": 0,
            "stage_c_fetch_throttled": 0,
            "stage_d_join_key_votes": 0,
            "stage_d_join_key_already_voted": 0,
            "stage_d_fallback_votes": 0,
            "stage_d_fallback_already_voted": 0,
            "stage_d_illustration_votes": 0,
            "stage_d_illustration_already_voted": 0,
            "stage_d_slow_path_routed": 0,
            "stage_d_border_chip_votes": 0,
            "stage_d_frame_chip_votes": 0,
            "stage_d_bleed_chip_votes": 0,
            "stage_d_verdict_transfer_votes": 0,
        }

        while True:
            if max_batches is not None and batch_count >= max_batches:
                self.stdout.write(f"--max-batches ({max_batches}) reached.")
                break

            chunk = list(queryset.filter(pk__gt=after_pk).values_list("pk", flat=True)[:batch_size])
            if not chunk:
                self.stdout.write("STREAMING C→D: cohort exhausted.")
                break

            after_pk = chunk[-1]
            total_cards_scanned += len(chunk)
            if limit is not None and total_cards_scanned >= limit:
                excess = total_cards_scanned - limit
                if excess > 0:
                    chunk = chunk[:-excess]
                if not chunk:
                    break
                after_pk = chunk[-1]

            if envelope_check is not None:
                envelope_check(f"streaming-batch-{batch_count}")

            if dry_run and batch_count > 0:
                break

            batch_outcome = dispatch_micro_batch(
                card_ids=chunk,
                trigger_reason="pipeline",
                run_id=run_id,
                batch_size=len(chunk),
                force_stage_c_reextract=options["force_reextract"],
                short_circuit=short_circuit,
                dry_run=dry_run,
                ledger_run_id=f"{run_id}-{attempt}Z-b{batch_count}",
            )

            batch_count += 1

            for key in acc:
                acc[key] += getattr(batch_outcome, key, 0)

            batch_info = f"  batch {batch_count - 1}: {len(chunk)} cards, " f"status={batch_outcome.status}"
            if batch_outcome.stage_c_completed:
                batch_info += f", C={batch_outcome.stage_c_completed}"
            if batch_outcome.stage_d_join_key_votes:
                batch_info += f", D_join={batch_outcome.stage_d_join_key_votes}"
            if batch_outcome.stage_d_fallback_votes:
                batch_info += f", D_fb={batch_outcome.stage_d_fallback_votes}"
            self.stdout.write(batch_info)

            if batch_outcome.status in ("halted-open-trip", "halted-new-trip"):
                raise CommandError(
                    f"ENVELOPE HALT during streaming batch {batch_count - 1}: "
                    f"{batch_outcome.status} trip_id={batch_outcome.trip_id}",
                    returncode=EXIT_ENVELOPE_HALT,
                )

        result: dict[str, Any] = {
            "mode": "streaming",
            "batch_size": batch_size,
            "source": batch_decision.source,
            "bound_by": batch_decision.bound_by,
            "batches_dispatched": batch_count,
            "cards_in_cohort": total_cards_scanned,
        }
        result.update(acc)

        if dry_run:
            remaining_count = queryset.filter(pk__gt=after_pk).count()
            if remaining_count:
                remaining_batches = (remaining_count + batch_size - 1) // batch_size
                self.stdout.write(
                    f"DRY-RUN: first batch dispatched (proves the mechanism). "
                    f"{remaining_count} cards remaining (~{remaining_batches} more batches)."
                )
                result["dry_run_remaining_cards"] = remaining_count
                result["dry_run_remaining_batches"] = remaining_batches

        self.stdout.write(f"STREAMING C→D: {result}")
        return result

    # ------------------------------------------------------------------------------------------
    def _propagate_cluster_votes(
        self,
        *,
        run_id: str,
        cohort_ids: Optional[list[int]],
        dry_run: bool = False,
        envelope_check: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        STAGE C+ - GROUP VOTE PROPAGATION. Two grouping keys, run in a fixed order, sharing ONE
        propagation engine (`_propagate_over_groups`).

        MD5 FIRST, AND MD5 IS THE ONE THAT SHARES A PRINTING VOTE (owner ruling, 2026-07-30:
        "the md5 dedupe should only fetch each identical image once across sources and then apply
        votes to the entire group as the fetched card passes through the monolith"). Two cards with
        the same `Card.md5_checksum` are the SAME BYTES, so they are depictions of the same
        printing - a claim of exact identity whose correctness argument is trivial. That is the
        claim a printing verdict needs.

        WHY THE FETCH HALF AND THE VOTE HALF HAD TO BE RE-KEYED ONTO THE SAME GROUP. Before this,
        the two halves were keyed DIFFERENTLY: `evidence_transfer` saves a FETCH on the md5 group,
        while this stage saved a DEDUCTION on the phash distance-0 group. Byte-identical files
        always share a phash, but files sharing a phash are not necessarily byte-identical, so the
        set that got a fetch saved and the set that got a vote propagated were not the same set -
        which is exactly the thing that is hard to reason about and easy to get wrong. The md5
        group now behaves as one unit end to end: fetched once (`evidence_transfer`), deduced once
        (Stage D on whichever member Stage D reached), and the conclusion applied across the group
        here, under the casting calculator's own identity.

        PROPAGATION IS NOT REDUNDANT, WHICH WAS CHECKED BEFORE IT WAS BUILT. `evidence_transfer`
        already gives every md5 sibling its own `ImageEvidence` row with byte-identical extractor
        field values, so it is reasonable to ask whether each member already reaches the same
        conclusion independently, making this stage unnecessary. It does not, for a reason that is
        structural rather than incidental: a Stage D printing deduction is NOT a function of the
        evidence row alone. `local_calculate_verdicts._resolve_candidates_for_card` keys the
        candidate list on `Card.name`, and two md5-identical uploads from different sources
        routinely carry different names (that is the ordinary state of a cross-source catalogue).
        Members also differ on per-card eligibility. So members genuinely reach DIFFERENT
        conclusions, or none at all, from identical evidence - and the group's one sound conclusion
        has to be carried to them deliberately.

        PROPAGATION NEVER OVERRIDES A MEMBER'S OWN INELIGIBILITY. See
        `_members_eligible_for_a_propagated_vote`: a member that is already RESOLVED, already
        confirmed to a `canonical_card`, not a `CARD`, or carrying a resolved `custom-art` /
        `non-english` tag is skipped. Being byte-identical to a card we identified does not entitle
        this stage to overwrite a fact the catalogue already holds about the member, and the
        `custom-art` case is the sharp one: that tag is the catalogue DECLARING the image is not a
        faithful depiction of a printing, so voting a printing onto it would contradict a
        human-visible declaration on the strength of a checksum.

        THE PHASH TIER IS LEFT EXACTLY AS PR #660 SHIPPED IT, and that is a flagged decision rather
        than an accreted default. Issue #661 holds the question of what phash grouping is FOR; the
        owner's stated direction is that phash should eventually share an ILLUSTRATION (same
        artwork, possibly a DIFFERENT printing - a near-identity claim at a grain where a weaker
        claim is appropriate), not a printing verdict. Until that is built, removing the existing
        phash printing propagation would itself be a behaviour change, and it is currently the ONLY
        propagation reaching cards that have no md5 at all (md5 is NULL for every `LOCAL_FILE`
        source by design and is never invented - see `Card.md5_checksum`'s own docstring). So it
        stays, it runs SECOND, and the ordering is the point: md5's exact-identity votes land
        first, and the phash tier can only fill what md5 did not, because
        `_propagate_over_groups` re-reads the already-voted set per tier.

        THE SEAM FOR PHASH-AS-ILLUSTRATION IS THE `groups` PARAMETER. `_propagate_over_groups`
        takes `members_by_representative` and knows nothing about how it was keyed, so adding the
        illustration-grain tier later means computing a different grouping and calling the same
        engine - not restructuring this stage. That is the "single grouping abstraction with the
        key as a parameter" #661 asks for, arrived at here rather than deferred to it.
        """
        stats: dict[str, Any] = {}

        md5_groups = self._md5_groups(cohort_ids)
        stats["md5"] = self._propagate_over_groups(
            groups=md5_groups,
            tier="md5",
            run_id=run_id,
            dry_run=dry_run,
            envelope_check=envelope_check,
        )

        phash_groups = self._phash_distance_zero_groups(cohort_ids)
        stats["phash_d0"] = self._propagate_over_groups(
            groups=phash_groups,
            tier="phash_d0",
            run_id=run_id,
            dry_run=dry_run,
            envelope_check=envelope_check,
        )

        key = "would_propagate" if dry_run else "votes_propagated"
        stats[key] = stats["md5"].get(key, 0) + stats["phash_d0"].get(key, 0)
        self.stdout.write(f"STAGE C+: {stats}")
        return stats

    # ------------------------------------------------------------------------------------------
    def _md5_groups(self, cohort_ids: Optional[list[int]]) -> dict[int, list[int]]:
        """
        BYTE-IDENTICAL GROUPS, keyed on `Card.md5_checksum` - the same key `evidence_transfer`
        already groups on, so the fetch saving and the vote saving now describe the same set.

        A NULL OR UNIQUE md5 IS A GROUP OF ONE (issue #473's ruling 3, inherited verbatim rather
        than re-decided here) and simply does not appear in the result: a checksum is copied from
        the source listing and is NEVER invented, so a card without one groups with nothing. The
        empty string is excluded alongside NULL - `md5_checksum` is a `CharField`, and an empty
        value is an absent checksum, not a value that thousands of cards genuinely share.

        Representative = `min(pk)`, matching `local_clustering._compute_exact_match_clusters`'
        own convention exactly, so the two tiers cannot disagree about what a representative IS.
        Note the representative is only a STABLE NAME for the group here - it is NOT required to be
        the card that holds the vote, because `_propagate_over_groups` looks for source votes
        across every member. That matters: Stage D reaches whichever member it reaches, and there
        is no reason that is the lowest pk.

        THE POOL IS THE CATALOGUE, NOT THIS RUN'S SELECTION - the same property the phash tier's
        own note describes. `--scope-stage-d-to-cohort` narrows it, and narrows that independence
        with it.
        """
        cards = Card.objects.filter(md5_checksum__isnull=False).exclude(md5_checksum="")
        if cohort_ids is not None:
            cards = cards.filter(pk__in=cohort_ids)
        by_checksum: dict[str, list[int]] = {}
        for pk, checksum in cards.values_list("pk", "md5_checksum").iterator():
            if not checksum:
                # Unreachable given the filter above; kept so that "a NULL or empty checksum is a
                # group of ONE" is true by construction rather than by the queryset alone. Fusing
                # every checksum-less card into a single group is the worst failure available
                # here, and it is one narrowed filter away at all times.
                continue
            by_checksum.setdefault(checksum, []).append(pk)
        groups: dict[int, list[int]] = {}
        for card_ids in by_checksum.values():
            if len(card_ids) < 2:
                continue
            representative = min(card_ids)
            groups[representative] = sorted(pk for pk in card_ids if pk != representative)
        return groups

    # ------------------------------------------------------------------------------------------
    def _phash_distance_zero_groups(self, cohort_ids: Optional[list[int]]) -> dict[int, list[int]]:
        """
        The phash distance-0 tier PR #660 shipped, unchanged in behaviour and merely lifted into
        its own method so both tiers hand the SAME shape to the SAME propagation engine.

        THE CLUSTER POOL IS THE CATALOGUE, NOT THIS RUN'S SELECTION. `run_pilot` clusters over its
        own eligibility-narrowed selection pool, which makes membership a function of what earlier
        runs already voted on: a genuine 3-card cluster can present as a 2-card one, and dropping
        the lowest-pk member changes which card becomes representative. Clustering over `Card` by
        stored hash - the whole catalogue by default - is what makes the answer independent of run
        history. When `--scope-stage-d-to-cohort` narrows this, that independence is narrowed too;
        that is the cost of the flag and the reason it is not the default.
        """
        cards = Card.objects.filter(content_phash__isnull=False)
        if cohort_ids is not None:
            cards = cards.filter(pk__in=cohort_ids)
        selected = [_ClusterInput(card=card) for card in cards.only("pk", "content_phash").iterator()]

        # `compute_two_threshold_clusters` is ANNOTATED against the pilot's `SelectedCard` but its
        # runtime contract is only `.card.pk` and `.card.content_phash` (`SelectedCard` is a
        # TYPE_CHECKING-only import there, and it carries a pilot candidate list this command has
        # no use for). Cast rather than widen that pure module's signature for this caller.
        return compute_two_threshold_clusters(cast(Any, selected)).members_by_representative

    # ------------------------------------------------------------------------------------------
    def _members_eligible_for_a_propagated_vote(self, member_ids: set[int]) -> set[int]:
        """
        WHICH GROUP MEMBERS MAY RECEIVE A PROPAGATED PRINTING VOTE AT ALL (owner constraint,
        2026-07-30: "propagation must not override a member's own ineligibility - a card excluded
        for a real reason stays excluded").

        These are CATALOGUE-LEVEL facts about the member, not workload preferences:
          * `printing_tag_status` is still UNRESOLVED - a resolved card's printing is settled.
          * no confirmed `canonical_card` - a human-confirmed indexing match outranks any machine
            vote, and contradicting it from a checksum would be the worst available failure.
          * `card_type=CARD` - tokens and cardbacks are excluded from every printing channel in
            this codebase for structural reasons (`_eligible_base_queryset`'s own docstring).
          * no resolved `custom-art` / `non-english` tag - the sharp one. `custom-art` is the
            catalogue DECLARING this image is not a faithful depiction of a printing. Byte
            identity with a card we identified does not overturn that declaration.

        DELIBERATELY NOT `local_identify_printing_tags._eligible_base_queryset`, and this is the
        one place in this change where a predicate is expressed rather than reused. That function
        computes the same four facts, but bundles them with WORKLOAD rules that are wrong here: a
        scan-log exclusion keyed to the PILOT's own rescannable vocabulary (a Stage D identity's
        vocabulary differs), and a deductive-backfill exclusion that is a "don't spend a scan"
        choice rather than an ineligibility. It also cannot simply be refactored to expose these
        four: its own docstring records that several tests and `stream_backstop_sweep` assert
        against its COMPILED SQL, so re-ordering its `.exclude()` chain to share a helper would
        change that SQL for every legacy caller. `TestPropagationEligibilityMatchesTheBaseQueryset`
        is the drift tripwire that keeps the two honest instead - see its own docstring.

        DELIBERATELY NOT `local_calculate_verdicts._eligible_cards_queryset` either: that one
        additionally requires a CURRENT `ImageEvidence` row, and propagating to a member that was
        never fetched or computed is the entire point of this stage.
        """
        return set(
            Card.objects.filter(
                pk__in=member_ids,
                printing_tag_status=PrintingTagStatus.UNRESOLVED,
                canonical_card__isnull=True,
                card_type=CardTypes.CARD,
            )
            .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
            .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
            .values_list("pk", flat=True)
        )

    # ------------------------------------------------------------------------------------------
    def _propagate_over_groups(
        self,
        *,
        groups: dict[int, list[int]],
        tier: str,
        run_id: str,
        dry_run: bool = False,
        envelope_check: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        THE ONE PROPAGATION ENGINE, shared by every grouping key. It is handed
        `members_by_representative` and knows nothing about how the grouping was computed - which
        is what makes adding a tier (issue #661's illustration-grain phash) a matter of computing a
        different grouping, not restructuring this stage.

        THE SOURCE VOTE MAY BE HELD BY ANY MEMBER, NOT ONLY THE REPRESENTATIVE. PR #660 looked for
        votes on representatives only, which silently propagated nothing whenever Stage D happened
        to reach a non-representative member - and Stage D has no reason to prefer the lowest pk.
        This reads this run's votes across EVERY member of every group, then propagates each one to
        the rest of ITS OWN group.

        ONE SOURCE VOTE PER (GROUP, IDENTITY), CHOSEN DETERMINISTICALLY (lowest card id). Without
        this, two members of one group both holding a vote would each generate rows for the other
        members, producing duplicate `(card, printing, anonymous_id)` rows inside a SINGLE write
        batch - which the already-voted guard cannot catch, because it is computed from the DB
        before any of this batch is written.

        A GROUP WHOSE MEMBERS DISAGREE IS COUNTED, NOT SILENTLY RESOLVED. Two members of one md5
        group can hold DIFFERENT printing verdicts under the same identity, because their
        candidate lists came from different `Card.name`s. Byte-identical images cannot depict two
        different printings, so a disagreement is a real signal about the upstream deduction, not
        noise to average away. The deterministic pick keeps the write well-defined; the counter
        (`groups_with_conflicting_verdicts`) is what makes the condition visible on the ledger
        rather than lost.

        `members_already_voted` is one query per identity, up front, and is RE-READ for each tier
        so an earlier tier's writes are visible to a later one. That is what gives md5 precedence
        over phash without either tier knowing about the other. Propagating to a member that
        already holds a vote under the same `anonymous_id` would violate `CardPrintingTag`'s own
        (card, printing, anonymous_id) uniqueness constraint anyway.
        """
        absorbed_ids = {m for members in groups.values() for m in members}
        stats: dict[str, Any] = {
            "group_count": len(groups),
            "cards_absorbed_into_groups": len(absorbed_ids),
            "votes_propagated": 0,
            "members_skipped_ineligible": 0,
            "groups_with_conflicting_verdicts": 0,
        }
        if not absorbed_ids:
            return stats

        if envelope_check is not None:
            envelope_check(f"stage-c+:{tier}")

        group_of_member: dict[int, int] = {}
        for representative, members in groups.items():
            group_of_member[representative] = representative
            for member in members:
                group_of_member[member] = representative

        # EVERY CARD IN EVERY GROUP, REPRESENTATIVES INCLUDED - not just the absorbed members. Two
        # separate things depend on this and both are wrong if the representative is left out:
        # a representative can HOLD the source vote (Stage D has no reason to reach the lowest pk
        # first), and a representative can equally be a propagation TARGET when some other member
        # holds it. `absorbed_ids` above stays members-only because it reports "how many cards were
        # absorbed into a group", which is a different question from "who participates here".
        all_group_card_ids = set(group_of_member.keys())
        source_votes = list(
            CardPrintingTag.objects.filter(card_id__in=all_group_card_ids, run_id=run_id, is_no_match=False).exclude(
                printing_id=None
            )
        )
        if not source_votes:
            return stats

        # One source vote per (group, identity), lowest card id wins; disagreements counted.
        chosen: dict[tuple[int, str], CardPrintingTag] = {}
        conflicted: set[tuple[int, str]] = set()
        for vote in sorted(source_votes, key=lambda v: v.card_id):
            if vote.printing_id is None or vote.confidence is None:
                # Cannot happen given the queryset above; asserted here so a later change to that
                # filter cannot silently start propagating a vote with no printing or no weight.
                continue
            key = (group_of_member[vote.card_id], vote.anonymous_id)
            incumbent = chosen.get(key)
            if incumbent is None:
                chosen[key] = vote
            elif incumbent.printing_id != vote.printing_id:
                conflicted.add(key)
        stats["groups_with_conflicting_verdicts"] = len({group for group, _identity in conflicted})

        eligible_member_ids = self._members_eligible_for_a_propagated_vote(all_group_card_ids)
        stats["members_skipped_ineligible"] = len(all_group_card_ids) - len(eligible_member_ids)

        already_voted_by_identity: dict[str, set[int]] = {}
        for anonymous_id in {vote.anonymous_id for vote in chosen.values()}:
            already_voted_by_identity[anonymous_id] = set(
                CardPrintingTag.objects.filter(card_id__in=all_group_card_ids, anonymous_id=anonymous_id).values_list(
                    "card_id", flat=True
                )
            )

        rows: list[CardPrintingTag] = []
        for (representative, anonymous_id), vote in chosen.items():
            assert vote.printing_id is not None and vote.confidence is not None
            # Every card in the group EXCEPT the one holding the source vote. Built here rather
            # than reusing `groups` directly because the source vote is not necessarily the
            # representative, so "the others" is relative to the VOTE, not to the group's name.
            others = [pk for pk in ([representative] + groups[representative]) if pk != vote.card_id]
            skip = already_voted_by_identity.get(anonymous_id, set()) | (set(others) - eligible_member_ids)
            rows.extend(
                build_propagated_cluster_votes(
                    representative_card_id=vote.card_id,
                    printing_pk=vote.printing_id,
                    anonymous_id=anonymous_id,
                    confidence=vote.confidence,
                    run_id=run_id,
                    members_by_representative={vote.card_id: others},
                    members_already_voted=skip,
                    source=VoteSource(vote.source),
                )
            )
        if rows and not dry_run:
            # The same write rail every other printing-vote writer uses: the purge is atomic with
            # the insert and scoped to exactly the rows being inserted, and a superseded row is
            # archived into `ArchivedCardPrintingTag` before deletion.
            purge_and_write_votes(CardPrintingTag, rows, target_field="card_id")
        stats["would_propagate" if dry_run else "votes_propagated"] = len(rows)
        return stats

    # ------------------------------------------------------------------------------------------
    def _run_fidelity_gate(self, *, run_id: str) -> list[int]:
        """
        The Stage D fidelity gate - `verify_zero_resolutions`, the same check
        `local_calculate_verdicts` runs between its calculators, applied here once over every card
        this run cast a printing vote for. It answers one question: did any card reach a RESOLVED
        printing state on machine votes alone? The answer must be zero.
        """
        card_ids = list(CardPrintingTag.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct())
        if not card_ids:
            self.stdout.write("FIDELITY GATE: this run cast no printing votes - nothing to check.")
            return []
        violations = verify_zero_resolutions(card_ids)
        if violations:
            self.stdout.write(
                self.style.ERROR(f"FIDELITY GATE VIOLATION: {len(violations)} card(s): {violations[:20]}")
            )
        else:
            self.stdout.write(f"FIDELITY GATE: clear over {len(card_ids)} cards.")
        return violations

    # ------------------------------------------------------------------------------------------
    def _run_channel_report(self, *, run_id: str) -> dict[str, Any]:
        """
        `channel_report`, run at the end of the pass and NEVER folded into this command's own exit
        status. Its exit 1 is expected on a first run - `ZERO_DECLARATIONS` ships empty and there
        are known-silent channels - and that is the instrument working. Gating the monolith on it
        would mean a correct reading of a real gap failing a run that did exactly what was asked.
        """
        self.stdout.write("=" * 78)
        self.stdout.write("CHANNEL REPORT (non-gating for this command's exit status)")
        exit_code = 0
        try:
            call_command("channel_report", "--run-id", run_id)
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
        self.stdout.write(
            f"channel_report exit={exit_code}"
            + (
                "  <- EXPECTED on a first run: ZERO_DECLARATIONS ships empty and there are "
                "known-silent channels. Read the findings; do not silence them here."
                if exit_code
                else ""
            )
        )
        return {"exit_code": exit_code}


class _EnvelopeSentry:
    """
    THE OPERATING ENVELOPE, RE-SAMPLED DURING THE PASS (2026-07-30) - not just before it.

    PR #660 shipped Stage E as a PREFLIGHT ONLY: `current_trip`/`check_envelope` once, before
    Stage C, never again. Owner brief: "host resampling is likely required (for steps that aren't
    fetch) as the same monolith will run for small datasets and large ones so needs to fit the
    available compute appropriately." A single check at launch is right for a 200-card run and
    wrong for a 230k one - the box's free compute at hour six is not what it was at hour zero, and
    this command's whole point is that ONE invocation serves both sizes.

    THREE SEPARATE PROTECTIONS, AND THIS CLASS IS ONLY THE MIDDLE ONE. They are easy to conflate
    and must not be:
      * the 7/s ceiling protects GOOGLE, applies per request, and lives beneath Stage C in
        `harvest_rate_coordinator` (PR #649). Nothing here.
      * THE ENVELOPE protects THIS HOST. That is this class.
      * compute gating paces everything else. Also not here.

    HALT SEMANTICS ARE PRESERVED EXACTLY, and this is the sharp edge. A genuine breach HALTS and
    never self-resumes: `check_envelope` persists an `EnvelopeTrip`, this raises, and the only way
    back is an owner action through `resolve_envelope_trip`. A re-sample is NOT a throttle and must
    never become one - PR #644 converted RATE PRESSURE (429/503) to a throttle precisely so that it
    would stop masquerading as an envelope breach, and converting a host-load breach the other way
    would undo that distinction from the opposite direction. Load average is this box's own
    saturation; going slower on Google does not reduce it.

    WHAT A MID-PASS HALT LEAVES BEHIND, stated plainly because it differs from the preflight's
    "nothing was written". By the time a re-sample fires, real rows exist. They stay - every one of
    them carries this run's `run_id` and is queryable by it, and the run resumes with
    `--run-id <same>` once the trip is acknowledged. That is the same posture the fidelity gate
    already takes (exit 7 is "read this run before trusting it", not a rollback), and it is why
    this raises rather than attempting any unwind.

    INTERVAL-GATED so it cannot become its own load (see `ENVELOPE_RESAMPLE_INTERVAL_SECONDS` for
    why 60s is derived from the one-minute load average rather than picked). `check(..., force=True)`
    bypasses the gate and is used for the preflight, which must always sample.

    `current_trip` BEFORE `check_envelope`, never the reverse - the order `operating_envelope`'s own
    docstring requires. An OPEN trip refuses outright, including a trip some OTHER process opened
    while this pass was running, which is the case a preflight-only design could not see at all.
    """

    __slots__ = ("_run_id", "_write", "_interval", "_last_sampled_at", "samples", "skipped")

    def __init__(self, *, run_id: str, write: Any, interval_seconds: float = ENVELOPE_RESAMPLE_INTERVAL_SECONDS):
        self._run_id = run_id
        self._write = write
        self._interval = interval_seconds
        self._last_sampled_at: Optional[float] = None
        self.samples = 0
        self.skipped = 0

    def check(self, step: str, *, force: bool = False) -> None:
        """
        Sample the envelope unless the interval gate says it is too soon. Raises `CommandError`
        with `EXIT_ENVELOPE_HALT` on an open trip or a fresh breach; returns silently otherwise.
        `step` names the stage about to start and appears in the halt message, so an operator
        reading a halted run knows where in the pass it stopped without correlating timestamps.
        """
        now = time.monotonic()
        if not force and self._last_sampled_at is not None and (now - self._last_sampled_at) < self._interval:
            self.skipped += 1
            return
        self._last_sampled_at = now
        self.samples += 1

        existing = current_trip(run_id=self._run_id)
        if existing is not None:
            raise CommandError(
                f"ENVELOPE HALT before {step}: trip {existing.trip_id} ({existing.bar}) is still "
                "open. No self-resume - clear it with `resolve_envelope_trip` after investigating. "
                + self._written_so_far(step),
                returncode=EXIT_ENVELOPE_HALT,
            )
        fresh = check_envelope(_sample_envelope_signals(), run_id=self._run_id)
        if fresh is not None:
            raise CommandError(
                f"ENVELOPE HALT before {step}: bar {fresh.bar} breached ({fresh.detail}); trip "
                f"{fresh.trip_id} persisted. " + self._written_so_far(step),
                returncode=EXIT_ENVELOPE_HALT,
            )

    def _written_so_far(self, step: str) -> str:
        if step == "preflight":
            return "Nothing was written."
        return (
            f"Everything this run wrote before {step} STAYS WRITTEN and is queryable by "
            f"run_id={self._run_id}; resume with --run-id {self._run_id} once the trip is "
            "acknowledged."
        )

    def stats(self) -> dict[str, Any]:
        return {"samples": self.samples, "skipped_by_interval": self.skipped, "interval_s": self._interval}


class _ClusterInput:
    """
    The two-attribute shape `local_clustering.compute_two_threshold_clusters` reads (`.card.pk`,
    `.card.content_phash`). `SelectedCard`, the type that function is annotated against, is a
    `TYPE_CHECKING`-only import there and carries a pilot candidate list this command has no use
    for; the runtime contract is these two attributes and nothing else.
    """

    __slots__ = ("card",)

    def __init__(self, card: Card) -> None:
        self.card = card
