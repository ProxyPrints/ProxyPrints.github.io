"""
Tags backing the "What's That Card?" attribute chips (see docs/features/printing-tags.md,
questionFeed section) that aren't already part of the bracket-text taxonomy in
`cardpicker.default_tags`. "Full Art", "Borderless", "Showcase", and "Extended" are reused
as-is from `DEFAULT_TAGS` - this module only seeds the ones with no existing row: the border-
color and frame-era exclusion groups, plus "Etched" (a `frame_effects` value with no bracket-
text precedent).

Same idempotent-seed-command-not-migration pattern as `default_tags.py`/`sensitive_tags.py` -
see either's header comment for why.
"""

from typing import Optional

from cardpicker.models import Tag

# (name, display_name). None of these are sensitive - always TagModerationClass.STANDARD
# (the Tag model default), unlike sensitive_tags.py's seed list.
ATTRIBUTE_TAGS: list[tuple[str, Optional[str]]] = [
    ("Etched", None),
    ("Black Border", None),
    ("White Border", None),
    ("Silver Border", None),
    ("Old Border", None),
    ("Modern Border", None),
    ("Future Frame", None),
]

# The full chip-tag taxonomy the questionFeed confidence overlay computes net-polarity for -
# the four reused tags above plus the seven seeded here. Kept here (not duplicated in
# question_feed.py) since this module owns the "what are the attribute chip tags" question.
ATTRIBUTE_CHIP_TAG_NAMES: list[str] = [
    "Full Art",
    "Borderless",
    "Showcase",
    "Extended",
    "Etched",
    "Black Border",
    "White Border",
    "Silver Border",
    "Old Border",
    "Modern Border",
    "Future Frame",
]


def seed_attribute_tags() -> dict[str, int]:
    """Idempotent - safe to re-run. Creates any tag that doesn't exist yet; never overwrites
    an existing row (mirrors seed_sensitive_tags's "never overwrite a manual edit" contract,
    minus the moderation_class upgrade path - these were never sensitive)."""

    created = 0
    for name, display_name in ATTRIBUTE_TAGS:
        _tag, was_created = Tag.objects.get_or_create(name=name, defaults={"aliases": [], "display_name": display_name})
        if was_created:
            created += 1
    return {"created": created}


__all__ = ["seed_attribute_tags", "ATTRIBUTE_TAGS", "ATTRIBUTE_CHIP_TAG_NAMES"]
