from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.resolution_tier_probe import (
    CALIBRATION_BASELINE_TIER,
    NATIVE_TIER,
    RESOLUTION_TIERS,
    run_resolution_tier_probe,
)

DEFAULT_SAMPLE_SIZE = 50


class Command(BaseCommand):
    help = (
        "T1/T2 resolution-tier probe (docs/features/catalog-completion-plan.md, 'STAGE B "
        "RESOLUTION DECISION'): fetches real images at native/1200px/925px/800px and measures "
        "T1 (real OCR match rate per tier) and T2 (phash Hamming-distance drift vs. both the "
        "native and the 925px 'full resolution' calibration baseline). Real network cost, no "
        "votes/residue ever persisted."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help=f"Number of cards to probe (default: {DEFAULT_SAMPLE_SIZE}).",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        sample_size = kwargs["sample_size"]
        result = run_resolution_tier_probe(sample_size=sample_size)

        print(f"[resolution-tier-probe] sample_size={result.sample_size} attempted={result.attempted}")

        print("[resolution-tier-probe] T1 - OCR match rate per tier:")
        for tier in RESOLUTION_TIERS:
            print(f"  {tier}: {result.ocr_match_rate(tier) * 100:.1f}%")

        print(f"[resolution-tier-probe] T2 - phash Hamming distance vs. native ({NATIVE_TIER}):")
        for tier in RESOLUTION_TIERS:
            if tier == NATIVE_TIER:
                continue
            distances = result.hamming_distances_vs(tier, NATIVE_TIER)
            if distances:
                mean = sum(distances) / len(distances)
                print(f"  {tier}: n={len(distances)} mean={mean:.2f} max={max(distances)} min={min(distances)}")
            else:
                print(f"  {tier}: no comparable pairs")

        print(
            f"[resolution-tier-probe] T2 - phash Hamming distance vs. the calibration baseline "
            f"({CALIBRATION_BASELINE_TIER}, what docs/features/printing-tags.md's d=0/d<=2 "
            f"thresholds were actually validated against):"
        )
        for tier in RESOLUTION_TIERS:
            if tier == CALIBRATION_BASELINE_TIER:
                continue
            distances = result.hamming_distances_vs(tier, CALIBRATION_BASELINE_TIER)
            if distances:
                mean = sum(distances) / len(distances)
                print(f"  {tier}: n={len(distances)} mean={mean:.2f} max={max(distances)} min={min(distances)}")
            else:
                print(f"  {tier}: no comparable pairs")
