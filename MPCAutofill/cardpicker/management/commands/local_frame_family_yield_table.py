import random
from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_frame_family import (
    SET_TO_FRAME_FAMILIES,
    _build_exempt_sets,
    candidate_frame_families,
)
from cardpicker.local_identify_printing_tags import CandidateNameIndex


class Command(BaseCommand):
    help = (
        "Dry-run yield table for Step 3 (frame narrowing). Samples N random names "
        "from the CandidateNameIndex and measures how many lose/keep their frame "
        "families when narrowing is applied vs. the pre-narrowing baseline."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--sample-size",
            type=int,
            default=2000,
            help="Number of random names to sample. Default: 2000.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for reproducibility. Default: 42.",
        )

    def handle(self, **options: Any) -> None:
        sample_size = options["sample_size"]
        seed = options["seed"]

        index = CandidateNameIndex()
        all_names = list(index._by_name.keys())
        rng = random.Random(seed)
        sampled = rng.sample(all_names, min(sample_size, len(all_names)))

        exempt_sets = _build_exempt_sets(index)

        total_with_families_pre = 0
        total_with_families_post = 0
        total_resolved = 0
        families_cleared = 0
        families_preserved_exempt = 0
        families_preserved_marker = 0

        for name in sampled:
            result = candidate_frame_families(name, index)
            if not result.name_resolved:
                continue
            total_resolved += 1

            if result.families:
                total_with_families_post += 1

            candidates = index.candidates_for(name)
            pre_families: set[str] = set()
            for c in candidates:
                pre_families |= SET_TO_FRAME_FAMILIES.get(c.expansion_code, frozenset())

            if pre_families:
                total_with_families_pre += 1

            if pre_families and not result.families:
                families_cleared += 1
            elif pre_families and result.families:
                has_non_exempt_marker = any(_has_marker(c) for c in candidates if c.expansion_code not in exempt_sets)
                if not has_non_exempt_marker:
                    families_preserved_exempt += 1
                else:
                    families_preserved_marker += 1

        self.stdout.write("=" * 60)
        self.stdout.write("STEP 3 YIELD TABLE (frame narrowing)")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total names sampled:        {len(sampled)}")
        self.stdout.write(f"Names resolved:             {total_resolved}")
        self.stdout.write("")
        self.stdout.write(f"Pre-narrowing families:     {total_with_families_pre}")
        self.stdout.write(f"Post-narrowing families:    {total_with_families_post}")
        self.stdout.write(f"Families CLEARED by Step 3: {families_cleared}")
        self.stdout.write(f"Families kept (exempt):     {families_preserved_exempt}")
        self.stdout.write(f"Families kept (marker):     {families_preserved_marker}")
        if total_with_families_pre > 0:
            pct = families_cleared / total_with_families_pre * 100
            self.stdout.write(f"Cleared rate:               {pct:.1f}%")
        self.stdout.write("=" * 60)


def _has_marker(candidate: Any) -> bool:
    if any(fe in ("showcase", "extendedart") for fe in candidate.frame_effects):
        return True
    if candidate.border_color == "borderless":
        return True
    if candidate.full_art:
        return True
    if candidate.layout and candidate.layout != "normal":
        return True
    return False
