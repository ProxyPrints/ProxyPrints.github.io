"""
See `cardpicker.md5_backfill`'s own module docstring for the full re-walk/reconcile design
(issue #473 PR-1, now covering both md5 and sha256 in the one pass - the command keeps its
original md5-only name since md5 remains the primary, grouping-defining field). This file is
deliberately thin - Command.handle() wires the forced-dry-run guard + PilotRunLedger lifecycle
rails (issue #362/#373 convention, `cardpicker.pilot_run_lifecycle`) around `run_md5_backfill`,
matching every other big write command's own shape (e.g. `reparse_collector_evidence`,
`consensus_recompute`).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.md5_backfill import DEFAULT_BULK_UPDATE_BATCH_SIZE, run_md5_backfill
from cardpicker.models import PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Issue #473 PR-1: re-walks every GOOGLE_DRIVE source's Drive folder listing (metadata "
        "only - zero image fetches) and reconciles each listing's md5Checksum AND sha256Checksum "
        "against the currently-stored Card.md5_checksum/Card.sha256_checksum (owner-approved "
        "sha256 addition, 2026-07-25 evening - same walk, same seam). LOCAL_FILE sources carry "
        "neither checksum in their listings and are always a no-op here (reported, not silently "
        "skipped). Dry-run by default: prints per-field coverage (matched/planned-write counts "
        "for md5 and sha256 separately, since their listing coverage can differ), plus the "
        "md5-only group count and dupe factor for cross-check against issue #442's own sizing "
        "walk (18.87% dupe rate, 24,712/130,960 files, 12,275 groups) BEFORE any --write. "
        "--write requires a matching COMPLETED dry-run of the SAME --source-key selection within "
        "--dry-run-window-hours (forced-dry-run guard, issue #362) - see --skip-dryrun-check to "
        "override. A PilotRunLedger row is written either way."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source-key",
            action="append",
            default=None,
            dest="source_keys",
            help="Restrict the walk to this source key (repeatable). Default: every source "
            "(GOOGLE_DRIVE sources are walked; other source types are reported as skipped, not "
            "walked - see this command's own --help intro).",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually persist reconciled checksums. Default is dry-run: compute and count "
            "everything without writing. Requires a matching recent COMPLETED dry-run ledger row "
            "for the SAME --source-key selection (forced-dry-run guard) unless "
            "--skip-dryrun-check is passed.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BULK_UPDATE_BATCH_SIZE,
            help=f"Cards per bulk_update batch. Default: {DEFAULT_BULK_UPDATE_BATCH_SIZE}.",
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

        source_keys = kwargs["source_keys"]
        write = kwargs["write"]
        batch_size = kwargs["batch_size"]
        dry_run = not write

        # Forced-dry-run guard scope (issue #362 convention): the INPUT that defines this
        # invocation's own target cohort - the sorted --source-key list, or None (matching
        # consensus_recompute's own "no caller-chosen cohort narrower than the whole command"
        # reasoning) when every source is in scope.
        scope = scope_hash("source_keys", ",".join(sorted(source_keys))) if source_keys else None
        skip_used = enforce_dry_run_precondition(
            command="backfill_md5_checksums",
            write_mode=write,
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=scope,
        )

        run_id = kwargs["run_id"] or generate_run_id()
        mode = "WRITE" if write else "DRY RUN"
        self.stdout.write(
            f"[{mode}] backfill_md5_checksums run_id={run_id} "
            f"source_keys={source_keys or 'ALL'} batch_size={batch_size}"
        )

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="backfill_md5_checksums",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(scope=scope, skip_dryrun_check_used=skip_used),
        )
        try:
            result = run_md5_backfill(dry_run=dry_run, source_keys=source_keys, batch_size=batch_size)

            # Counters-before-output (cardpicker.pilot_run_lifecycle's own module docstring
            # point 1) - the ledger row is saved COMPLETED here, before the terminal summary
            # print below.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = result.written
            ledger.counters = merge_counters(
                ledger.counters,
                {
                    "sources_scanned": result.sources_scanned,
                    "sources_skipped_no_checksum_support": result.sources_skipped_no_checksum_support,
                    "sources_unreachable": result.sources_unreachable,
                    "matched_files": result.matched_files,
                    "md5_planned_writes": result.md5_planned_writes,
                    "sha256_matched_files": result.sha256_matched_files,
                    "sha256_planned_writes": result.sha256_planned_writes,
                    "planned_writes": result.planned_writes,
                    "written": result.written,
                    "dupe_groups": result.dupe_groups,
                    "dupe_files": result.dupe_files,
                    "dupe_factor": result.dupe_factor,
                },
            )
            ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])

            with resilient_terminal_output():
                self.stdout.write(
                    f"sources_scanned={result.sources_scanned} "
                    f"sources_skipped_no_checksum_support={len(result.sources_skipped_no_checksum_support)} "
                    f"sources_unreachable={len(result.sources_unreachable)}"
                )
                if result.sources_unreachable:
                    self.stdout.write(f"  unreachable source keys: {result.sources_unreachable}")
                # per-field coverage, reported separately since md5/sha256 listing coverage can
                # differ (owner-approved sha256 addition, 2026-07-25 evening).
                self.stdout.write(
                    f"md5:    matched_files={result.matched_files} planned_writes={result.md5_planned_writes}"
                )
                self.stdout.write(
                    f"sha256: matched_files={result.sha256_matched_files} "
                    f"planned_writes={result.sha256_planned_writes}"
                )
                self.stdout.write(
                    f"dupe_groups={result.dupe_groups} dupe_files={result.dupe_files} "
                    f"dupe_factor={result.dupe_factor:.4%} (md5-only - groups key on md5 "
                    "exclusively, per issue #473 ruling 1)"
                )
                self.stdout.write(
                    "Reconcile the md5 matched_files line and the dupe stats above against issue "
                    "#442's own sizing walk (18.87% dupe rate, 24,712/130,960 files, 12,275 "
                    "groups) before running --write."
                )
                if dry_run:
                    self.stdout.write(f"(dry-run) would_write={result.planned_writes}")
                else:
                    self.stdout.write(f"written={result.written}")
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed) -
            # a no-op if this invocation already reached the COMPLETED save above.
            mark_ledger_failed(ledger, exc)
            raise
