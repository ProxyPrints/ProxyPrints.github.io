"""
Frame-family tag taxonomy — children of the existing "Showcase" tag that name the specific
alternate-frame family (Pipboy, Vault, Storybook, etc.) a card belongs to.

Same idempotent-seed-command-not-migration pattern as `default_tags.py`/`attribute_tags.py` -
see either's header comment for why.

Source of truth for family names: `local_frame_family.SET_TO_FRAME_FAMILIES` — the same
dict that drives set-narrowing classification. Every key set there that contains at least one
family produces one Tag row per family here; no family is hand-added, no family is omitted.
"""

import re
from typing import Optional

from cardpicker.models import Tag

# ---------------------------------------------------------------------------
# PascalCase -> human-readable display name converter.
# ---------------------------------------------------------------------------

_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    # Acronyms and abbreviations that need explicit casing
    "DMUStainedGlass": "DMU Stained Glass",
    "DNDModule": "DND Module",
    "DNDSourcebook": "DND Sourcebook",
    "FCA": "FCA",
    "FableECL": "Fable ECL",
    "M15NyxShowcase": "M15 Nyx Showcase",
    "M21": "M21",
    "MH2": "MH2",
    "MysticalArchive": "Mystical Archive",
    "MysticalArchiveJP": "Mystical Archive JP",
    "MysticalArchiveJPEN": "Mystical Archive JPEN",
    "MysticalArchiveSOA": "Mystical Archive SOA",
    "PixelTMT": "Pixel TMT",
    "SNCArtDeco": "SNC Art Deco",
    "SNCGilded": "SNC Gilded",
    "SNCSkyscraper": "SNC Skyscraper",
    "SewerTMT": "Sewer TMT",
    "StorybookMUL": "Storybook MUL",
    "StorybookWOE": "Storybook WOE",
    "TARDIS": "TARDIS",
}


def _pascal_to_display(name: str) -> str:
    """Convert PascalCase family name to a human-readable display name.

    Uses overrides for acronyms and abbreviations; otherwise inserts spaces before
    capital letters that follow lowercase letters or before uppercase runs that
    precede a lowercase letter.

    >>> _pascal_to_display("Pipboy")
    'Pipboy'
    >>> _pascal_to_display("ShowcaseMagnified")
    'Showcase Magnified'
    >>> _pascal_to_display("SNCGilded")
    'SNC Gilded'
    """
    if name in _DISPLAY_NAME_OVERRIDES:
        return _DISPLAY_NAME_OVERRIDES[name]
    # Insert space before uppercase following lowercase: "Storybook" -> "Storybook"
    # Insert space before uppercase run ending lowercase: "MysticalArchive" -> "Mystical Archive"
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return spaced


# ---------------------------------------------------------------------------
# Family name roster — derived from SET_TO_FRAME_FAMILIES at module level.
# Rebuilt whenever local_frame_family.py changes its map.
# ---------------------------------------------------------------------------


def _collect_family_names() -> list[str]:
    """Extract every unique family name from SET_TO_FRAME_FAMILIES.

    Returns a sorted list for deterministic seeding. Set codes are filtered out
    (lowercase strings) — only PascalCase family names survive.
    """
    from cardpicker.local_frame_family import SET_TO_FRAME_FAMILIES

    families: set[str] = set()
    for fams in SET_TO_FRAME_FAMILIES.values():
        families |= fams
    return sorted(families)


# Lazily computed once per process, cached on the module.
_FAMILY_NAMES: Optional[list[str]] = None


def _get_family_names() -> list[str]:
    global _FAMILY_NAMES
    if _FAMILY_NAMES is None:
        _FAMILY_NAMES = _collect_family_names()
    return _FAMILY_NAMES


# ---------------------------------------------------------------------------
# Seeding function.
# ---------------------------------------------------------------------------


def seed_frame_family_tags() -> dict[str, int]:
    """Idempotent — safe to re-run. Creates any family tag that doesn't exist yet as a
    child of the pre-existing "Showcase" tag; never overwrites an existing row's
    display_name (mirrors seed_sensitive_tags's "never overwrite a manual edit" contract).

    Returns {"created": N} for the management command to print.
    """
    showcase_tag = Tag.objects.filter(name="Showcase").first()
    if showcase_tag is None:
        raise RuntimeError("Tag 'Showcase' not found. Run seed_default_tags() before seeding frame-family tags.")

    created = 0
    for family_name in _get_family_names():
        display_name = _pascal_to_display(family_name)
        _tag, was_created = Tag.objects.get_or_create(
            name=family_name,
            defaults={
                "display_name": display_name,
                "parent": showcase_tag,
                "aliases": [],
            },
        )
        if was_created:
            created += 1
    return {"created": created}


__all__ = [
    "seed_frame_family_tags",
    "_get_family_names",
    "_pascal_to_display",
]
