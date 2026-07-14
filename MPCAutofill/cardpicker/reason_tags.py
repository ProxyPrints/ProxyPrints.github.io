"""
The "why no match?" reason-code taxonomy - shown as a follow-up strip in the printing-tag
queue after a human casts an explicit "No match" printing vote (see
docs/features/printing-tags.md, "no-match reason tags"). Kept in its own module and its own
management command (mirroring cardpicker.default_tags/seed_default_tags exactly) rather than
a data migration: a data migration would run automatically at DB-setup time (including the
test database), unconditionally seeding these rows into every fresh DB - which breaks every
test that asserts on the *complete* set of `Tag` rows (e.g. test_views.py::TestGetTags, which
documents that a fresh DB has zero real Tag rows besides the synthetic never-persisted "NSFW"
pseudo-tag - see cardpicker.tags). A manual, idempotent command avoids that coupling, exactly
like the existing descriptor taxonomy already does.

These six tag names are a federation interchange contract (see docs/features/printing-tags.md)
- other instances that consume our vote export are expected to recognise these exact strings.
Renaming any of them is a breaking data migration, not a refactor.

Deliberately a separate, lowercase-kebab-case taxonomy from `cardpicker.default_tags`'s Title
Case DEFAULT_TAGS (which parses filename bracket content at upload time, e.g. "Upscaled",
"Custom", "AI-Generated"). `upscaled`/`custom-art`/`ai-art` below cover near-identical
concepts to those but are cast by a human as the *reason* they picked "no match" in the
printing-tag queue, not inferred from a filename - kept as distinct rows rather than reusing
the existing tags so the two vote populations (upload-time inference vs. human no-match
reasoning) don't get silently merged into one consensus.
"""

from cardpicker.models import Tag

# (name, description, display_name). `description` is documentation only (no DB column for
# it - see Tag.display_name's help_text); `display_name` is real, seeded presentation text
# the frontend looks up dynamically (useTagDisplayName) rather than hardcoding, so this list
# is the single source of truth for both the machine key and its human label.
NO_MATCH_REASON_TAGS: list[tuple[str, str, str]] = [
    ("custom-art", "Original or alternate artwork - does not depict a real printing", "Custom art"),
    ("altered-frame", "Real printing's art in a modified frame", "Altered frame"),
    ("upscaled", "AI-upscaled version of an official image", "Upscaled"),
    ("ai-art", "AI-generated artwork", "AI art"),
    ("no-collector-line", "No legible collector line on the card face", "No collector line"),
    ("non-english", "Non-English printing", "Non-English"),
]


def seed_no_match_reason_tags() -> dict[str, int]:
    """
    Idempotent - safe to re-run. Creates any tag that doesn't exist yet (display_name set at
    creation), and backfills display_name on an already-existing tag only if it's still null
    - never overwrites a manually-edited display_name (see Tag.display_name's help_text:
    "freely editable").
    """

    created = 0
    updated = 0
    for name, _description, display_name in NO_MATCH_REASON_TAGS:
        tag, was_created = Tag.objects.get_or_create(name=name, defaults={"aliases": [], "display_name": display_name})
        if was_created:
            created += 1
            continue
        if tag.display_name is None:
            tag.display_name = display_name
            tag.save(update_fields=["display_name"])
            updated += 1
    return {"created": created, "updated": updated}


__all__ = ["seed_no_match_reason_tags", "NO_MATCH_REASON_TAGS"]
