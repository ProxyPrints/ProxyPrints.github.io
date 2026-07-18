"""
Standalone reference implementation of ProxyPrints' federation `content_phash`
recipe (docs/federation/public-export-v1.md §2). Ported line-for-line from
MPCAutofill/cardpicker/local_phash.py + local_fallback.py's real call chain
(compute_content_phash_for_card -> classify_bleed_edge -> compute_card_art_hash
-> normalize_crop_box) so a hash computed here matches what that fork's own
export publishes for the same image - not just "close enough."

Usage:
    python hash_my_cards.py ./my_scans/
    python hash_my_cards.py ./my_scans/ --export-url https://.../export-full.jsonl

Dependencies: Pillow, imagehash. Nothing else - no Django, no database, no
required network access (the --export-url join is the one optional exception).
License: MIT.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Optional

import imagehash
from PIL import Image

# A verdict record as published in the export - {"content_phash": ..., "printing": {...}, ...}.
# Not a TypedDict on purpose: this tool must keep working against a schema that gains fields over
# time (record_version, §1) without needing a matching release of its own.
Record = dict[str, Any]

# --- The exact recipe (docs/federation/public-export-v1.md §2) ---------------------------------

# Standard MTG trim size (63x88mm) + a 1/8" (3.175mm) bleed margin per edge - the same reference
# geometry cardpicker/local_fallback.py's classify_bleed_edge/normalize_crop_box are built from.
_CARD_TRIM_WIDTH_MM = 63.0
_CARD_TRIM_HEIGHT_MM = 88.0
_BLEED_MARGIN_MM = 3.175

TRIM_ASPECT_RATIO = _CARD_TRIM_WIDTH_MM / _CARD_TRIM_HEIGHT_MM
BLEED_ASPECT_RATIO = (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM) / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)
BLEED_CLASSIFICATION_TOLERANCE = 0.03

_WIDTH_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM)
_HEIGHT_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)

# Fraction-of-full-image art crop box (left, top, right, bottom), tuned against bleed-inclusive
# images. Deliberately crude (a fixed fraction, not a real frame-aware detector) - see the spec
# doc for why that crudeness is a feature here, not a shortcut.
ART_CROP_BOX: tuple[float, float, float, float] = (0.07, 0.10, 0.93, 0.58)

HASH_SIZE = 8  # imagehash.phash's own default; 64 bits out (HASH_SIZE**2).

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}

DEFAULT_DISTANCE_THRESHOLD = 20  # empirically tuned against real production data - see spec §2.


def classify_bleed_edge(image: Image.Image) -> Optional[str]:
    """
    Returns "bleed"/"trimmed", or None if the image's aspect ratio is too far from both
    reference ratios to classify confidently (genuinely ambiguous, not a forced guess).
    """
    width, height = image.size
    if height == 0:
        return None
    ratio = width / height
    distance_to_trim = abs(ratio - TRIM_ASPECT_RATIO)
    distance_to_bleed = abs(ratio - BLEED_ASPECT_RATIO)
    if min(distance_to_trim, distance_to_bleed) > BLEED_CLASSIFICATION_TOLERANCE:
        return None
    return "bleed" if distance_to_bleed < distance_to_trim else "trimmed"


def normalize_crop_box(
    box: tuple[float, float, float, float], bleed_class: Optional[str]
) -> tuple[float, float, float, float]:
    """
    Remaps a fixed-fraction crop box (tuned against a bleed-inclusive image) onto a TRIMMED
    image's own coordinate space. No-op for "bleed" or None (already the convention the box was
    tuned against).
    """
    if bleed_class != "trimmed":
        return box
    left, top, right, bottom = box

    def _rescale(fraction: float, margin_fraction: float) -> float:
        return min(1.0, max(0.0, (fraction - margin_fraction) / (1 - 2 * margin_fraction)))

    return (
        _rescale(left, _WIDTH_MARGIN_FRACTION),
        _rescale(top, _HEIGHT_MARGIN_FRACTION),
        _rescale(right, _WIDTH_MARGIN_FRACTION),
        _rescale(bottom, _HEIGHT_MARGIN_FRACTION),
    )


def compute_content_phash(image: Image.Image) -> str:
    """
    The pure hashing function - deliberately dependency-free beyond Pillow/imagehash. Returns a
    16-hex-char string (imagehash.ImageHash's own str() form), matching the export's wire format
    - not the internal signed two's-complement integer this fork's own database uses, which is a
    storage detail, not part of the interchange format.
    """
    bleed_class = classify_bleed_edge(image)
    left, top, right, bottom = normalize_crop_box(ART_CROP_BOX, bleed_class)
    width, height = image.size
    art_region = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
    return str(imagehash.phash(art_region, hash_size=HASH_SIZE))


def hash_folder(path: Path) -> dict[str, str]:
    """Recursively hashes every image in `path`, returning {relative filename: content_phash_hex}."""
    results: dict[str, str] = {}
    for entry in sorted(path.rglob("*")):
        if not entry.is_file():
            continue
        if entry.suffix.lstrip(".").lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        try:
            with Image.open(entry) as image:
                results[str(entry.relative_to(path))] = compute_content_phash(image)
        except Exception as e:
            print(f"Skipping {entry}: {e}", file=sys.stderr)
    return results


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Bit-difference count between two hex-encoded 64-bit hashes."""
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


# --- The join step (CLI-only concern, kept separate from the pure hash function above) ---------


def fetch_export(url: str) -> list[Record]:
    """Fetches and parses a federation export (newline-delimited JSON records)."""
    with urllib.request.urlopen(url) as response:  # noqa: S310 - url is user-supplied by design
        text = response.read().decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def find_matches(
    local_hashes: dict[str, str], export_records: list[Record], threshold: int = DEFAULT_DISTANCE_THRESHOLD
) -> dict[str, list[tuple[Record, int]]]:
    """
    For each local image, finds every export record within `threshold` Hamming distance,
    nearest first. An empty list means no match was found within the threshold - not an error.
    """
    matches: dict[str, list[tuple[Record, int]]] = {}
    for filename, local_hash in local_hashes.items():
        found: list[tuple[Record, int]] = []
        for record in export_records:
            record_hash = record.get("content_phash")
            if not record_hash:
                continue
            distance = hamming_distance(local_hash, record_hash)
            if distance <= threshold:
                found.append((record, distance))
        found.sort(key=lambda item: item[1])
        matches[filename] = found
    return matches


def _describe_printing(record: Record) -> str:
    printing = record.get("printing", {})
    scryfall_id = printing.get("scryfall_id")
    set_code = printing.get("set")
    collector_number = printing.get("collector_number")
    if set_code and collector_number:
        label = f"{set_code}#{collector_number}"
        return f"{label} ({scryfall_id})" if scryfall_id else label
    return str(scryfall_id or "unknown printing")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hash a folder of card images with ProxyPrints' federation content_phash recipe, "
            "optionally joining against a published export."
        )
    )
    parser.add_argument("folder", type=Path, help="Directory of card images to hash (recurses).")
    parser.add_argument(
        "--export-url",
        help="Fetch a federation export (newline-delimited JSON) and report which local images match a published verdict.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_DISTANCE_THRESHOLD,
        help=f"Match distance threshold (default: {DEFAULT_DISTANCE_THRESHOLD}, the spec's own empirically-tuned value).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a table.")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        parser.error(f"{args.folder} is not a directory")

    local_hashes = hash_folder(args.folder)

    if not args.export_url:
        if args.json:
            print(json.dumps(local_hashes, indent=2))
        else:
            for filename, content_hash in local_hashes.items():
                print(f"{content_hash}  {filename}")
        return

    export_records = fetch_export(args.export_url)
    matches = find_matches(local_hashes, export_records, args.threshold)

    if args.json:
        serializable = {
            filename: [{"distance": distance, "record": record} for record, distance in found]
            for filename, found in matches.items()
        }
        print(json.dumps(serializable, indent=2))
        return

    for filename, found in matches.items():
        if not found:
            print(f"{filename}: no match within distance <= {args.threshold}")
            continue
        record, distance = found[0]
        extra = f" (+{len(found) - 1} more candidate/s)" if len(found) > 1 else ""
        print(f"{filename}: distance {distance} -> {_describe_printing(record)}{extra}")


if __name__ == "__main__":
    main()
