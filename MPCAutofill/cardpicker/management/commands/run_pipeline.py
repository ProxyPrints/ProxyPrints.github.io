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
    build_propagated_cluster_votes,
    verify_zero_resolutions,
)
from cardpicker.management.commands.stream_full_catalog import (
    EXIT_ENVELOPE_HALT,
    run_stage_zero_freshness,
)
from cardpicker.models import Card, CardPrintingTag, PilotRunLedger, VoteSource
from cardpicker.operating_envelope import check_envelope, current_trip
from cardpicker.pilot_run_lifecycle import (
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
)
from cardpicker.stage_e_dispatch import (
    DispatchOutcome,
    _run_stage_d,
    _sample_envelope_signals,
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

            # -- STAGE C ----------------------------------------------------------------------
            cohort_ids: Optional[list[int]] = None
            if options["skip_stage_c"]:
                self.stdout.write("STAGE C skipped (--skip-stage-c).")
                counters["stage_c"] = {"skipped": True}
            else:
                counters["stage_c"] = self._run_stage_c(run_id=run_id, options=options, dry_run=dry_run)

            if options["scope_stage_d"]:
                # The cards this run has evidence for, read back rather than remembered - Stage C
                # ran in its own command and this one deliberately does not reach inside it.
                from cardpicker.models import ImageEvidence

                cohort_ids = list(
                    ImageEvidence.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct()
                )
                self.stdout.write(f"Stage D scoped to this run's own Stage C cohort: {len(cohort_ids)} cards.")

            # -- STAGE D ----------------------------------------------------------------------
            if options["skip_stage_d"]:
                self.stdout.write("STAGE D skipped (--skip-stage-d).")
                counters["stage_d"] = {"skipped": True}
            else:
                counters["stage_d"] = self._run_stage_d_bulk(run_id=run_id, cohort_ids=cohort_ids, dry_run=dry_run)

            # -- STAGE C+ : CLUSTER VOTE PROPAGATION -------------------------------------------
            if options["skip_clustering"]:
                self.stdout.write("STAGE C+ clustering skipped (--skip-clustering).")
                counters["clustering"] = {"skipped": True}
            else:
                counters["clustering"] = self._propagate_cluster_votes(
                    run_id=run_id, cohort_ids=cohort_ids, dry_run=dry_run
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
        The operating envelope, checked ONCE before anything is written - `operating_envelope`'s
        own two entry points, called in the order that module's docstring requires (`current_trip`
        BEFORE `check_envelope`, never the reverse) and with the same no-self-resume rule the
        conveyor has: an open trip refuses outright and is cleared by an owner action
        (`resolve_envelope_trip`), never by a run deciding for itself that it is fine now.

        The rate-pressure half of the envelope (PR #644's throttle-instead-of-halt, PR #649's
        global 7/s ceiling) is NOT checked here and must not be: it lives underneath Stage C in
        `harvest_fetch_limiter`/`harvest_rate_coordinator`, applies per request, and its whole
        point is that rate pressure slows the pass rather than stopping it.
        """
        if skip:
            self.stdout.write("STAGE E envelope preflight skipped (--skip-envelope).")
            return

        existing = current_trip(run_id=run_id)
        if existing is not None:
            raise CommandError(
                f"ENVELOPE HALT: trip {existing.trip_id} ({existing.bar}) is still open. No "
                "self-resume - clear it with `resolve_envelope_trip` after investigating. Nothing "
                "was written.",
                returncode=EXIT_ENVELOPE_HALT,
            )
        fresh = check_envelope(_sample_envelope_signals(), run_id=run_id)
        if fresh is not None:
            raise CommandError(
                f"ENVELOPE HALT: bar {fresh.bar} breached ({fresh.detail}); trip {fresh.trip_id} "
                "persisted. Nothing was written.",
                returncode=EXIT_ENVELOPE_HALT,
            )
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
        self, *, run_id: str, cohort_ids: Optional[list[int]], dry_run: bool = False
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
        _run_stage_d(cohort_ids, run_id, outcome, dry_run=dry_run)

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
        }
        self.stdout.write(f"STAGE D: {result}")
        return result

    # ------------------------------------------------------------------------------------------
    def _propagate_cluster_votes(
        self, *, run_id: str, cohort_ids: Optional[list[int]], dry_run: bool = False
    ) -> dict[str, Any]:
        """
        STAGE C+ - the pilot capability that was reachable from no engine.

        `compute_two_threshold_clusters` groups cards by their stored `content_phash`; a distance-0
        cluster is a set of BIT-IDENTICAL images. `build_propagated_cluster_votes` then gives every
        absorbed member its representative's printing verdict under the same identity, with no
        fetch and no compute for the member. Both functions are called, never reimplemented.

        THE CLUSTER POOL IS THE CATALOGUE, NOT THIS RUN'S SELECTION. `run_pilot` clusters over its
        own eligibility-narrowed selection pool, which makes membership a function of what earlier
        runs already voted on: a genuine 3-card cluster can present as a 2-card one, and dropping
        the lowest-pk member changes which card becomes representative. Clustering over `Card` by
        stored hash - the whole catalogue by default - is what makes the answer independent of run
        history. When `--scope-stage-d-to-cohort` narrows this, that independence is narrowed too;
        that is the cost of the flag and the reason it is not the default.

        `members_already_voted` is one query, up front, per identity - a member that already holds
        a vote under the same `anonymous_id` is skipped, because propagating anyway would violate
        `CardPrintingTag`'s own (card, printing, anonymous_id) uniqueness constraint.
        """
        cards = Card.objects.filter(content_phash__isnull=False)
        if cohort_ids is not None:
            cards = cards.filter(pk__in=cohort_ids)
        selected = [_ClusterInput(card=card) for card in cards.only("pk", "content_phash").iterator()]

        # `compute_two_threshold_clusters` is ANNOTATED against the pilot's `SelectedCard` but its
        # runtime contract is only `.card.pk` and `.card.content_phash` (`SelectedCard` is a
        # TYPE_CHECKING-only import there, and it carries a pilot candidate list this command has
        # no use for). Cast rather than widen that pure module's signature for this caller.
        cluster_result = compute_two_threshold_clusters(cast(Any, selected))
        members_by_representative = cluster_result.members_by_representative
        member_ids = {m for members in members_by_representative.values() for m in members}
        stats: dict[str, Any] = {
            "cluster_count": len(members_by_representative),
            "cards_absorbed_into_clusters": len(member_ids),
            "votes_propagated": 0,
        }
        if not member_ids:
            self.stdout.write(f"STAGE C+: {stats} - nothing to propagate.")
            return stats

        # The representatives' own verdicts, as cast by THIS run's Stage D.
        source_votes = list(
            CardPrintingTag.objects.filter(
                card_id__in=list(members_by_representative.keys()), run_id=run_id, is_no_match=False
            ).exclude(printing_id=None)
        )
        already_voted_by_identity: dict[str, set[int]] = {}
        for anonymous_id in {vote.anonymous_id for vote in source_votes}:
            already_voted_by_identity[anonymous_id] = set(
                CardPrintingTag.objects.filter(card_id__in=member_ids, anonymous_id=anonymous_id).values_list(
                    "card_id", flat=True
                )
            )

        rows: list[CardPrintingTag] = []
        for vote in source_votes:
            if vote.printing_id is None or vote.confidence is None:
                # Cannot happen given the queryset above; asserted here so a later change to that
                # filter cannot silently start propagating a vote with no printing or no weight.
                continue
            rows.extend(
                build_propagated_cluster_votes(
                    representative_card_id=vote.card_id,
                    printing_pk=vote.printing_id,
                    anonymous_id=vote.anonymous_id,
                    confidence=vote.confidence,
                    run_id=run_id,
                    members_by_representative=members_by_representative,
                    members_already_voted=already_voted_by_identity.get(vote.anonymous_id, set()),
                    source=VoteSource(vote.source),
                )
            )
        if rows and not dry_run:
            # The same write rail every other printing-vote writer uses: the purge is atomic with
            # the insert and scoped to exactly the rows being inserted, and a superseded row is
            # archived into `ArchivedCardPrintingTag` before deletion.
            purge_and_write_votes(CardPrintingTag, rows, target_field="card_id")
        stats["would_propagate" if dry_run else "votes_propagated"] = len(rows)
        self.stdout.write(f"STAGE C+: {stats}")
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
