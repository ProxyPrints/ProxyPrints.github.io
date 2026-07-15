import argparse
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker import local_identify_printing_tags, local_ocr, local_phash
from cardpicker.local_identify_printing_tags import Engine, run_pilot


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

    def handle(self, *args: Any, **kwargs: Any) -> None:
        engine = kwargs["engine"]
        limit = kwargs["limit"]
        dry_run = kwargs["dry_run"]
        resume = kwargs["resume"]
        nice = kwargs["nice"]
        crop_box_arg = kwargs["crop_box"]
        phash_max_candidates = kwargs["phash_max_candidates"]

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
        print(
            f"[{mode}] local_identify_printing_tags --engine={engine} --limit={limit} "
            f"--nice={nice} --crop-box={crop_box} "
            f"--exclude-sources-ocr={exclude_source_pks_by_engine['ocr']} "
            f"--exclude-sources-phash={exclude_source_pks_by_engine['phash']}"
        )

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
        )

        gate_violations: list[int] = []
        for name, result in results.items():
            print(f"--- {name} ---")
            print(f"  votes written: {result.votes_written}")
            for reason, count in sorted(result.skip_counts.items()):
                print(f"  skipped ({reason}): {count}")
            gate_violations = result.gate_violations

        print("--- attributes ---")
        print(
            f"  border votes: {dict(attributes.border_votes_by_class)} (ground truth: {attributes.border_ground_truth_count})"
        )
        print(
            f"  frame votes: {dict(attributes.frame_votes_by_class)} (ground truth: {attributes.frame_ground_truth_count})"
        )
        print(f"  frame abstains: {attributes.frame_abstain_count}")
        print(f"  frame mismatches (printing vote withheld): {len(attributes.frame_mismatches)}")

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        if gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(gate_violations)} card(s) resolved after a machine-only "
                f"(deduction/ocr) vote, which should be structurally impossible - STOP and "
                f"investigate before continuing this pilot. Affected card pks: {gate_violations[:50]}"
                + (" (truncated)" if len(gate_violations) > 50 else "")
            )

        total_written = sum(r.votes_written for r in results.values())
        print(f"Gate check passed: 0/{total_written} affected cards resolved.")
