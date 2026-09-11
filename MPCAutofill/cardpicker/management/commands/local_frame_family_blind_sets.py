import json
from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_frame_family import (
    SET_TO_FRAME_FAMILIES,
    _build_exempt_sets,
    _has_alternate_frame_marker,
)
from cardpicker.local_identify_printing_tags import CandidateNameIndex


class Command(BaseCommand):
    help = (
        "Computes which sets in SET_TO_FRAME_FAMILIES have 0% alternate-frame "
        "marker coverage across all their printings in the CandidateNameIndex. "
        "Outputs a JSON object mapping set codes to their printing/marker counts."
    )

    def handle(self, **options: Any) -> None:
        index = CandidateNameIndex()

        set_printing_counts: dict[str, int] = {}
        set_marker_counts: dict[str, int] = {}
        for printings in index._by_name.values():
            for candidate in printings:
                code = candidate.expansion_code
                if code not in SET_TO_FRAME_FAMILIES:
                    continue
                set_printing_counts[code] = set_printing_counts.get(code, 0) + 1
                if _has_alternate_frame_marker(candidate):
                    set_marker_counts[code] = set_marker_counts.get(code, 0) + 1

        exempt = _build_exempt_sets(index)

        result: dict[str, dict[str, Any]] = {}
        for code in sorted(SET_TO_FRAME_FAMILIES):
            total = set_printing_counts.get(code, 0)
            markers = set_marker_counts.get(code, 0)
            pct = (markers / total * 100) if total else 0.0
            result[code] = {
                "total_printings": total,
                "marker_printings": markers,
                "marker_pct": round(pct, 2),
                "exempt": code in exempt,
            }

        self.stdout.write(json.dumps(result, indent=2))
