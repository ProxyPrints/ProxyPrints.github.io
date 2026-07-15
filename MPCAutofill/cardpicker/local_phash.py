"""
L2 engine for the local printing-identification pilot (cardpicker.local_identify_printing_tags,
docs/features/printing-tags.md's Stage 8): perceptual-hash art matching.

`CanonicalCard.image_hash` already exists (added alongside `import_canonical_card_data` - see
"CanonicalCard population fix" in the docs) but is unpopulated in production
(`--skip-image-hash` was used for the real import; confirmed live, 113,224/113,224 rows still
at the placeholder 0) - this module is what actually computes it, lazily, only for candidates a
selected card's name actually produced, never a bulk backfill of the full 113k-row table.
"""

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Optional

import imagehash
import requests
from PIL import Image

from cardpicker.models import CanonicalCard
from cardpicker.utils import twos_complement

if TYPE_CHECKING:
    from cardpicker.local_identify_printing_tags import CandidatePrinting

logger = logging.getLogger(__name__)

SCRYFALL_HEADERS = {"User-Agent": "mpc-autofill/1.0", "Accept": "application/json"}
_HASH_BITS = 64
_HASH_HEX_DIGITS = _HASH_BITS // 4

# Tuned against real production distances (2026-07-15), not the commonly-quoted "under 10"
# imagehash convention - that assumes well-aligned crops, and ART_CROP_BOX's fixed fractions
# are deliberately crude (see its own comment). Sampled ~26 real multi-candidate cards: best
# (minimum) distance across all of them ranged 14-22, never below 14 - a threshold of 10 would
# reject every single real candidate, pass or fail, before the margin check even runs. 20/5
# still rejects the common case where multiple printings share identical official art (reprints
# routinely do) - those cluster within a few points of each other and correctly fail the margin
# check - while accepting cases with real separation.
DEFAULT_DISTANCE_THRESHOLD = 20
DEFAULT_MARGIN = 5

# MTG modern (2015+) frame art window as a fraction of the full card image - deliberately
# crude for a pilot: a fixed box, not a real frame-aware detector. Modern frame reserves
# roughly the top ~8% for the title bar and the bottom ~42% for the type line/rules text/
# bottom border, leaving the art in between; left/right margins trim the frame's own border.
# Older frames (1993/1997/2003) have measurably different proportions - this box is a
# reasonable average, not tuned per-frame-era, which is exactly the kind of imprecision a
# margin-gated match (not just a threshold) is meant to tolerate.
ART_CROP_BOX: tuple[float, float, float, float] = (0.07, 0.10, 0.93, 0.58)


def _hash_to_int(image_hash: "imagehash.ImageHash") -> int:
    return twos_complement(str(image_hash), _HASH_BITS)


def _int_to_hash(value: int) -> "imagehash.ImageHash":
    unsigned = value & ((1 << _HASH_BITS) - 1)
    return imagehash.hex_to_hash(f"{unsigned:0{_HASH_HEX_DIGITS}x}")


def _fetch_scryfall_art_crop_url(scryfall_id: str) -> Optional[str]:
    try:
        response = requests.get(f"https://api.scryfall.com/cards/{scryfall_id}", headers=SCRYFALL_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json().get("image_uris", {}).get("art_crop")
    except Exception:
        logger.exception("Failed to fetch Scryfall card data for %s", scryfall_id)
        return None


def _fetch_and_hash(url: str) -> Optional[int]:
    try:
        response = requests.get(url, headers=SCRYFALL_HEADERS, stream=True, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        return _hash_to_int(imagehash.phash(image))
    except Exception:
        logger.exception("Failed to fetch/hash image at %s", url)
        return None


def get_or_compute_canonical_hash(canonical: CanonicalCard) -> Optional[int]:
    """
    Returns canonical.image_hash, computing and persisting it first if it's still the unset
    placeholder (0 - see module docstring). Cached forever once computed: a printing's art crop
    never changes, so a 0 read back here always means "never computed", not "computed as zero"
    (an all-white or otherwise-degenerate phash of 0 is possible in principle but vanishingly
    unlikely for real card art - not specially handled, matching upstream's own use of the same
    sentinel in import_canonical_card_data).
    """
    if canonical.image_hash != 0:
        return canonical.image_hash

    art_crop_url = _fetch_scryfall_art_crop_url(str(canonical.identifier))
    if art_crop_url is None:
        return None
    computed = _fetch_and_hash(art_crop_url)
    if computed is None:
        return None
    canonical.image_hash = computed
    canonical.save(update_fields=["image_hash"])
    return computed


def compute_card_art_hash(card_image: "Image.Image") -> int:
    width, height = card_image.size
    left, top, right, bottom = ART_CROP_BOX
    art_region = card_image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
    return _hash_to_int(imagehash.phash(art_region))


@dataclass(frozen=True)
class PhashMatch:
    candidate: "CandidatePrinting"
    distance: int
    runner_up_distance: Optional[int]


def find_best_match(
    card_hash: int,
    candidates_with_hashes: list[tuple["CandidatePrinting", int]],
    distance_threshold: int = DEFAULT_DISTANCE_THRESHOLD,
    margin: int = DEFAULT_MARGIN,
) -> tuple[Optional[PhashMatch], str]:
    """
    Returns (match, skip_reason). skip_reason is "no-hashable-candidates" (every candidate
    failed to fetch/hash), "no-clear-winner" (best distance is over threshold, or the runner-up
    is too close behind it), or "" (matched). Requires at least 2 hashed candidates to compute a
    margin at all when there's more than one name-candidate in the first place; a genuinely
    single-candidate name (already excluded by the orchestrator's selection - phash only runs on
    multi-candidate names in practice) would just need the threshold.
    """
    if not candidates_with_hashes:
        return None, "no-hashable-candidates"

    # card_hash and each candidate hash are both plain ints (the DB storage representation) -
    # ImageHash's `-` operator (Hamming distance) needs two ImageHash objects, not raw ints.
    card_image_hash = _int_to_hash(card_hash)
    scored = sorted(
        (
            (candidate, card_image_hash - _int_to_hash(candidate_hash))
            for candidate, candidate_hash in candidates_with_hashes
        ),
        key=lambda pair: pair[1],
    )
    best_candidate, best_distance = scored[0]
    runner_up_distance = scored[1][1] if len(scored) > 1 else None

    if best_distance > distance_threshold:
        return None, "no-clear-winner"
    if runner_up_distance is not None and (runner_up_distance - best_distance) <= margin:
        return None, "no-clear-winner"

    return PhashMatch(candidate=best_candidate, distance=best_distance, runner_up_distance=runner_up_distance), ""


__all__ = [
    "DEFAULT_DISTANCE_THRESHOLD",
    "DEFAULT_MARGIN",
    "ART_CROP_BOX",
    "PhashMatch",
    "get_or_compute_canonical_hash",
    "compute_card_art_hash",
    "find_best_match",
]
