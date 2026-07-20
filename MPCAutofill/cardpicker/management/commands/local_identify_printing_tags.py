import argparse
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker import local_identify_printing_tags, local_ocr, local_phash
from cardpicker.local_identify_printing_tags import Engine, generate_run_id, run_pilot
from cardpicker.models import PilotRunLedger
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha


class Command(BaseCommand):
    help = (
        "PILOT (see docs/features/printing-tags.md Stage 8): casts OCR-weight (source=ocr) "
        "CardPrintingTag votes from two local, zero-API-cost engines that actually look at a "
        "card's image - L1 Tesseract OCR on the collector-line crop, L2 perceptual-hash art "
        "matching - plus a pass-2 fallback (border/artist/symbol evidence combination) for cards "
        "pass 1 misses. Never resolves a card by itself (the human-backed gate in "
        "vote_consensus.resolve_weighted_consensus still applies). PILOT ONLY: --limit defaults "
        "to 300 - do not scale this up to a full-catalog run without reviewing the pilot's "
        "yield/accuracy report first."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--engine",
            choices=["ocr", "phash", "both"],
            default="both",
            help="Which engine(s) to run. Default: both.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=300,
            help="Cap the number of candidate cards attempted per engine in this invocation. "
            "PILOT default: 300. Do not raise this for a full-catalog run without review.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Select and evaluate candidates without writing anything or running the gate check.",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            default=False,
            help="Acknowledge that a previous invocation already cast some votes under this "
            "pilot's anonymous_ids - purely informational (the underlying selection query "
            "already excludes any card either engine has already voted on, so a plain "
            "re-invocation resumes correctly with or without this flag); prints a summary of "
            "what's already been cast before starting.",
        )
        parser.add_argument(
            "--nice",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Throttle so the live API never starves (os.nice(15) plus periodic CPU-yield "
            "sleeps) - this box serves production. Default: on. Pass --no-nice to disable.",
        )
        parser.add_argument(
            "--crop-box",
            type=str,
            default=None,
            help="Override the OCR collector-line crop box as 'left,top,right,bottom' fractions "
            "of the full image (default: 0.0,0.85,0.30,1.0).",
        )
        parser.add_argument(
            "--phash-max-candidates",
            type=int,
            default=local_identify_printing_tags.PHASH_MAX_CANDIDATES,
            help="Skip phash entirely for a name with more than this many candidate printings "
            "(basic lands/staple commons can have hundreds - 'multi-candidate names first' "
            "ordering would otherwise hit these first and fetch/hash all of them). Default: "
            f"{local_identify_printing_tags.PHASH_MAX_CANDIDATES}.",
        )
        parser.add_argument(
            "--exclude-sources-ocr",
            type=str,
            default="1",
            help="Comma-separated Source pks to deprioritize from OCR selection (their cards are "
            "never selected as candidates by the OCR engine this invocation - existing votes/tags "
            "are untouched, this is a selection-time filter only). Default: '1' (WilfordGrimley - "
            "the OCR engine's own operator's source; excluded by default so a routine invocation "
            "doesn't cast machine votes on the operator's own cards. Pass '' to include it.) "
            "Pass '' for no exclusion.",
        )
        parser.add_argument(
            "--exclude-sources-phash",
            type=str,
            default="",
            help="Comma-separated Source pks to deprioritize from phash selection. Same mechanism "
            "as --exclude-sources-ocr, independently settable. Default: '' (no exclusion).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=local_identify_printing_tags.DEFAULT_BATCH_SIZE,
            help="Flush votes/tags to the DB (and run the gate check) every this many cards "
            "processed, instead of one giant write at the very end - so a killed/interrupted "
            "run keeps whatever it already committed (a plain re-invocation resumes cleanly, "
            "same idempotence mechanism as --resume). Default: "
            f"{local_identify_printing_tags.DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--fetch-budget",
            type=int,
            default=None,
            help="Cap the number of image CDN Worker requests this invocation will make (every "
            "fetched card costs one). Belt-and-suspenders alongside the Worker's own "
            "IMAGE_FULL_TIER_RATE_LIMITER (image-cdn/wrangler.toml) - the enforced protection for "
            "lh4.googleusercontent.com, shared with live PDF export/bulk download traffic - not "
            "the primary safeguard. On exhaustion the run stops cleanly: whatever was already "
            "flushed stays committed, and untouched cards are picked up fresh by the next "
            "invocation - no special resume handling needed. Default: no limit.",
        )
        parser.add_argument(
            "--fetch-dpi",
            type=int,
            default=local_identify_printing_tags.DEFAULT_FETCH_DPI,
            help="Request images from the CDN Worker capped at this dpi (maps to a smaller "
            "re-encoded JPEG height, image-cdn/src/url.ts) instead of full print-quality "
            "original - OCR only needs to read a small corner crop. Empirically validated floor "
            "(pre-scale program item 6/3c): dpi<=150 degrades yield, dpi>=200 matches or exceeds "
            "native-resolution yield with a 2-4x smaller payload. Default: "
            f"{local_identify_printing_tags.DEFAULT_FETCH_DPI} (margin above the empirically-best "
            "200). Pass --fetch-dpi=0 for uncapped native resolution.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=local_identify_printing_tags.DEFAULT_WORKERS,
            help="Concurrent worker threads for the fetch+OCR+phash+fallback compute portion of "
            "each card (pre-scale program item 3d) - the DB-write portion stays single-threaded "
            "regardless. Measured, not assumed (2026-07-15): on this box (2 CPU cores, shared "
            "with 5 live production containers), 2 workers gave only ~5ms extra live-API latency "
            "over the ALREADY-EXISTING single-threaded impact (tesseract's subprocess-based OCR "
            "genuinely parallelizes - the GIL releases during the subprocess wait), for a real "
            "1.61x full-pipeline wall-clock speedup (item 3e's cross-validated figure - a "
            "narrower fetch+OCR+phash-only benchmark showed ~2.1x, but detect_illus_anchor/pass-2 "
            "fallback don't parallelize as cleanly). Default: "
            f"{local_identify_printing_tags.DEFAULT_WORKERS} (matches this box's core count - "
            "more would only add contention, not real parallelism). Pass --workers=1 to disable "
            "concurrency entirely.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        # Iteration safety (docs/features/catalog-completion-plan.md's Part 1) - the hard gate,
        # checked before ANY other work, including the [DRY RUN]/[WRITE] line: refuse to start
        # if this image is older than a previously-deployed one.
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code (see docs/features/catalog-completion-plan.md's rebuild command) before "
                "running this command."
            )
        git_sha = get_baked_git_sha()
        print(f"[GIT_SHA] {git_sha or 'unknown (not baked - non-Docker run?)'}")

        engine = kwargs["engine"]
        limit = kwargs["limit"]
        dry_run = kwargs["dry_run"]
        resume = kwargs["resume"]
        nice = kwargs["nice"]
        crop_box_arg = kwargs["crop_box"]
        phash_max_candidates = kwargs["phash_max_candidates"]
        batch_size = kwargs["batch_size"]
        fetch_budget = kwargs["fetch_budget"]
        fetch_dpi: Optional[int] = kwargs["fetch_dpi"]
        if fetch_dpi == 0:
            fetch_dpi = None
        workers = kwargs["workers"]

        def _parse_source_pks(raw: str) -> list[int]:
            return [int(p) for p in raw.split(",") if p.strip()]

        exclude_source_pks_by_engine: dict[Engine, list[int]] = {
            "ocr": _parse_source_pks(kwargs["exclude_sources_ocr"]),
            "phash": _parse_source_pks(kwargs["exclude_sources_phash"]),
        }

        crop_box = local_ocr.DEFAULT_CROP_BOX
        if crop_box_arg is not None:
            parts = crop_box_arg.split(",")
            if len(parts) != 4:
                raise CommandError("--crop-box must be four comma-separated fractions: left,top,right,bottom")
            crop_box = tuple(float(p) for p in parts)  # type: ignore[assignment]

        if resume:
            from cardpicker.local_identify_printing_tags import (
                OCR_ANONYMOUS_ID,
                PHASH_ANONYMOUS_ID,
            )
            from cardpicker.models import CardPrintingTag

            ocr_already = CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID).count()
            phash_already = CardPrintingTag.objects.filter(anonymous_id=PHASH_ANONYMOUS_ID).count()
            print(f"[RESUME] already cast: local-ocr-v1={ocr_already}, local-phash-v1={phash_already}")

        mode = "DRY RUN" if dry_run else "WRITE"
        run_id = generate_run_id()
        print(
            f"[{mode}] local_identify_printing_tags --engine={engine} --limit={limit} "
            f"--nice={nice} --crop-box={crop_box} --batch-size={batch_size} "
            f"--fetch-budget={fetch_budget} --fetch-dpi={fetch_dpi} --workers={workers} "
            f"--exclude-sources-ocr={exclude_source_pks_by_engine['ocr']} "
            f"--exclude-sources-phash={exclude_source_pks_by_engine['phash']} run_id={run_id}"
        )

        ledger_entry = None
        if not dry_run:
            ledger_entry = PilotRunLedger.objects.create(
                run_id=run_id,
                command="local_identify_printing_tags",
                dry_run=dry_run,
                git_sha=git_sha,
            )

        try:
            results, attributes = run_pilot(
                engine=engine,
                limit=limit,
                dry_run=dry_run,
                nice=nice,
                ocr_crop_box=crop_box,
                phash_distance_threshold=local_phash.DEFAULT_DISTANCE_THRESHOLD,
                phash_margin=local_phash.DEFAULT_MARGIN,
                phash_max_candidates=phash_max_candidates,
                exclude_source_pks_by_engine=exclude_source_pks_by_engine,
                batch_size=batch_size,
                fetch_budget=fetch_budget,
                fetch_dpi=fetch_dpi,
                workers=workers,
                run_id=run_id,
            )
        except Exception:
            if ledger_entry is not None:
                ledger_entry.status = PilotRunLedger.Status.FAILED
                ledger_entry.finished_at = timezone.now()
                ledger_entry.save(update_fields=["status", "finished_at"])
            raise

        gate_violations: list[int] = []
        for name, result in results.items():
            print(f"--- {name} ---")
            print(f"  votes written: {result.votes_written}")
            if result.no_match_votes_written:
                # issue #207: is_no_match votes cast from a genuine whole-candidate-set no-match
                # conclusion (OCR's "parsed-but-no-match", fallback's "eliminated") - reported
                # separately from votes_written (which names a specific printing).
                print(f"  no-match votes written: {result.no_match_votes_written}")
            for reason, count in sorted(result.skip_counts.items()):
                print(f"  skipped ({reason}): {count}")
            if result.skipped_below_resolution_floor:
                print(f"  skipped (below-resolution-floor, never fetched): {result.skipped_below_resolution_floor}")
            gate_violations = result.gate_violations

        any_result = next(iter(results.values()), None)
        if any_result is not None and any_result.fetch_budget_exhausted:
            print(
                f"[FETCH BUDGET EXHAUSTED] stopped after --fetch-budget={fetch_budget} requests - "
                f"{any_result.cards_not_attempted_this_invocation} card(s) not attempted this "
                "invocation, untouched (no vote/outcome recorded) - re-run to pick them up."
            )

        print("--- attributes ---")
        print(
            f"  border votes: {dict(attributes.border_votes_by_class)} (ground truth: {attributes.border_ground_truth_count})"
        )
        print(
            f"  frame votes: {dict(attributes.frame_votes_by_class)} (ground truth: {attributes.frame_ground_truth_count})"
        )
        print(f"  frame abstains: {attributes.frame_abstain_count}")
        print(f"  frame mismatches (printing vote withheld): {len(attributes.frame_mismatches)}")
        print(f"  bleed votes: {dict(attributes.bleed_votes_by_class)}")
        print(f"  bleed abstains: {attributes.bleed_abstain_count}")
        print(f"  uncovered printings closed this run: {attributes.uncovered_printings_closed}")
        print(
            f"  image clusters: {attributes.cluster_count} "
            f"(cards absorbed: {attributes.cards_absorbed_into_clusters})"
        )

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        # issue #207: no_match_votes_written counts real CardPrintingTag(is_no_match=True) rows
        # too - total_written feeds the gate check's own denominator/the ledger's votes_written
        # field, both of which should reflect every vote row this run actually created.
        total_written = sum(r.votes_written + r.no_match_votes_written for r in results.values())

        if gate_violations:
            if ledger_entry is not None:
                ledger_entry.status = PilotRunLedger.Status.FAILED
                ledger_entry.finished_at = timezone.now()
                ledger_entry.votes_written = total_written
                ledger_entry.save(update_fields=["status", "finished_at", "votes_written"])
            raise CommandError(
                f"GATE VIOLATION: {len(gate_violations)} card(s) resolved after a machine-only "
                f"(deduction/ocr) vote, which should be structurally impossible - STOP and "
                f"investigate before continuing this pilot. Affected card pks: {gate_violations[:50]}"
                + (" (truncated)" if len(gate_violations) > 50 else "")
            )

        if ledger_entry is not None:
            ledger_entry.status = PilotRunLedger.Status.COMPLETED
            ledger_entry.finished_at = timezone.now()
            ledger_entry.votes_written = total_written
            ledger_entry.save(update_fields=["status", "finished_at", "votes_written"])

        print(f"run_id: {run_id}")
        print(f"Gate check passed: 0/{total_written} affected cards resolved.")
