from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
    run_fallback_calculator,
    run_join_key_calculator,
    run_slow_path_calculator,
)
from cardpicker.local_identify_printing_tags import (
    generate_run_id,
    verify_zero_resolutions,
)
from cardpicker.models import CardPrintingTag, PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
)
from cardpicker.printing_metadata_import import ensure_scryfall_cache_present
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "Stage D (docs/features/catalog-completion-plan.md, public issue #152): the join-key "
        "calculator - the fast-path deduction step over Stage C's ImageEvidence rows (collector-"
        "line OCR + set-symbol phash tie-break, plus a copyright-year era cross-check) - then the "
        "fallback channel calculator (Stage D's own port of local_fallback.py's pilot 'Pass 2' "
        "border/artist/symbol evidence-combination model, run only over cards the join-key "
        "calculator found no confident hit for) - then the slow-path routing calculator (owner "
        "decision, issue #220) that sends every card NEITHER of the two calculators above could "
        "confidently resolve to the human review queue, carrying its raw extracted signals. Casts "
        "CardPrintingTag votes via the existing, unmodified vote-consensus machinery; never "
        "resolves a card by itself - the slow-path half casts no votes at all. Defaults to dry-run "
        "and requires an explicit --write to actually write, matching local_residual_classify's "
        "own convention. --write also requires a matching COMPLETED dry-run PilotRunLedger row "
        "from the last --dry-run-window-hours (forced-dry-run guard, issue #362) - see "
        "--skip-dryrun-check to override. Refuses to start at all if the Scryfall bulk-data cache "
        "(scryfall_cache/default_cards.json) is missing (issue #402) unless "
        "--allow-missing-scryfall-cache is passed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write CardPrintingTag/CardScanLog rows. Default is dry-run: compute "
            "and count everything without writing. Requires a matching recent COMPLETED dry-run "
            "ledger row (forced-dry-run guard) unless --skip-dryrun-check is passed.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--chunk-size", type=int, default=500, help="Queryset .iterator() chunk size. Default: 500."
        )
        parser.add_argument(
            "--allow-missing-scryfall-cache",
            action="store_true",
            default=False,
            help="Explicitly accept a missing Scryfall bulk-data cache (scryfall_cache/"
            "default_cards.json) instead of refusing to start (issue #402's fail-loud guard - "
            "see printing_metadata_import.ensure_scryfall_cache_present). Without this flag, a "
            "missing cache is a hard CommandError, not the silent degraded-to-empty back-face "
            "lookup this command used to run with.",
        )
        # Forced-dry-run guard (issue #362, Phase 0 rails): this command has no caller-chosen
        # cohort narrower than "whatever's currently eligible" (unlike reparse_collector_evidence's
        # --selector or retract_stage_d_by_run_id's --run-id), so the guard below always passes
        # scope=None - ANY matching recent dry-run of this command satisfies it.
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

        # Fail-loud staleness guard (issue #402): must run before any card-by-card work below,
        # which otherwise silently degrades to an empty back-face lookup (get_back_face_names'
        # own soft-fail path) if the cache file is missing - see
        # ensure_scryfall_cache_present's own docstring.
        if not kwargs["allow_missing_scryfall_cache"]:
            ensure_scryfall_cache_present()

        run_id = kwargs["run_id"] or generate_run_id()
        dry_run = not kwargs["write"]
        mode = "WRITE" if kwargs["write"] else "DRY RUN"
        print(f"[{mode}] local_calculate_verdicts run_id={run_id} git_sha={get_baked_git_sha()}")

        skip_used = enforce_dry_run_precondition(
            command="local_calculate_verdicts",
            write_mode=kwargs["write"],
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=None,
        )

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="local_calculate_verdicts",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(skip_dryrun_check_used=skip_used),
        )

        try:
            result = run_join_key_calculator(run_id=run_id, dry_run=dry_run, chunk_size=kwargs["chunk_size"])
            votes_written = result.votes_written + result.no_match_votes_written
            would_cast = result.votes_would_cast + result.no_match_votes_would_cast
            print(
                f"[join-key] considered={result.cards_considered} "
                f"votes={'written=' + str(result.votes_written) if not dry_run else 'would_cast=' + str(result.votes_would_cast)} "
                f"no_match_votes={'written=' + str(result.no_match_votes_written) if not dry_run else 'would_cast=' + str(result.no_match_votes_would_cast)} "
                f"skip_counts={dict(result.skip_counts)}"
            )
            for entry in result.audit[:10]:
                print(f"  sample: {entry}")

            if not dry_run:
                # result.audit is capped (audit_sample_size) - the gate check needs the FULL
                # touched set, so it's re-derived from this run's own freshly-written votes
                # (scoped by run_id + anonymous_id, both exact-match) rather than the sample.
                touched_card_ids = list(
                    CardPrintingTag.objects.filter(run_id=run_id, anonymous_id=JOIN_KEY_ANONYMOUS_ID).values_list(
                        "card_id", flat=True
                    )
                )
                violations = verify_zero_resolutions(touched_card_ids)
                if violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(violations)} card(s) resolved to a printing from "
                        f"this single-anonymous_id machine pass alone, which should be "
                        f"structurally impossible per resolve_weighted_consensus's own human-"
                        f"backed gate - STOP and investigate. Affected card pks: "
                        f"{violations[:50]}" + (" (truncated)" if len(violations) > 50 else "")
                    )
                print(f"Gate check passed: 0/{len(touched_card_ids)} touched cards resolved machine-only.")

            # Fallback channel calculator (PIECE 1 of this PR's pre-fire prep bundle): runs AFTER
            # the join-key pass above in the SAME invocation/run_id - it only ever consumes cards
            # the join-key calculator found no confident hit for (see
            # _fallback_eligible_cards_queryset's own docstring), so sequencing here matters.
            # Ordered BEFORE slow-path routing below deliberately: a card this calculator resolves
            # must not also get routed to human review in the same invocation (see
            # _slow_path_eligible_cards_queryset's own new exclusion for the wiring this depends on).
            fallback_result = run_fallback_calculator(run_id=run_id, dry_run=dry_run, chunk_size=kwargs["chunk_size"])
            votes_written += fallback_result.votes_written
            would_cast += fallback_result.votes_would_cast
            print(
                f"[fallback] considered={fallback_result.cards_considered} "
                f"votes={'written=' + str(fallback_result.votes_written) if not dry_run else 'would_cast=' + str(fallback_result.votes_would_cast)} "
                f"skip_counts={dict(fallback_result.skip_counts)}"
            )
            for entry in fallback_result.audit[:10]:
                print(f"  sample: {entry}")

            if not dry_run:
                # same rationale as the join-key gate check above - re-derived from this run's own
                # freshly-written votes (scoped by run_id + anonymous_id) rather than the capped
                # audit sample.
                fallback_touched_card_ids = list(
                    CardPrintingTag.objects.filter(
                        run_id=run_id, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID
                    ).values_list("card_id", flat=True)
                )
                fallback_violations = verify_zero_resolutions(fallback_touched_card_ids)
                if fallback_violations:
                    raise CommandError(
                        f"GATE VIOLATION: {len(fallback_violations)} card(s) resolved to a printing "
                        f"from this single-anonymous_id machine pass alone, which should be "
                        f"structurally impossible per resolve_weighted_consensus's own human-"
                        f"backed gate - STOP and investigate. Affected card pks: "
                        f"{fallback_violations[:50]}" + (" (truncated)" if len(fallback_violations) > 50 else "")
                    )
                print(
                    f"Gate check passed: 0/{len(fallback_touched_card_ids)} fallback-touched cards "
                    "resolved machine-only."
                )

            # Slow-path routing (owner decision, issue #220): runs AFTER both calculators above in
            # the SAME invocation/run_id - it only ever consumes their own no-hit output (see
            # run_slow_path_calculator's own docstring), so sequencing here matters even though all
            # three ship in this one command. Casts no CardPrintingTag at all (it has no printing
            # to vote for), so there is no analogous gate check to run for it.
            slow_path_result = run_slow_path_calculator(run_id=run_id, dry_run=dry_run, chunk_size=kwargs["chunk_size"])
            print(
                f"[slow-path] considered={slow_path_result.cards_considered} "
                f"routed={'written=' + str(slow_path_result.routed_written) if not dry_run else 'would_cast=' + str(slow_path_result.routed_would_cast)} "
                f"reason_counts={dict(slow_path_result.reason_counts)}"
            )
            for entry in slow_path_result.audit[:10]:
                print(f"  sample: {entry}")

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the terminal summary print below - a BrokenPipeError on
            # a severed stdout while printing that summary must never look like this run failed.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = votes_written
            ledger.counters = merge_counters(ledger.counters, {})
            ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])
            with resilient_terminal_output():
                print(
                    f"[{mode}] done. run_id={run_id} "
                    f"total_votes={'written' if not dry_run else 'would_cast'}={votes_written if not dry_run else would_cast}"
                )
        except Exception as exc:
            # Shared FAILED-transition rail (cardpicker.pilot_run_lifecycle.mark_ledger_failed,
            # docs/proposals/stage-e-streaming.md §3 decision (6)/§10) - a no-op if this invocation
            # already reached the COMPLETED save above (a later exception from the terminal print,
            # if resilient_terminal_output didn't already swallow it, must never overwrite that
            # completion), otherwise records a triage-able counters["failure_reason"] alongside the
            # FAILED status, closing the "empty-failed-row" gap that helper's own docstring cites.
            mark_ledger_failed(ledger, exc)
            raise
