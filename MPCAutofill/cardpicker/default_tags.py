"""
The real descriptor taxonomy for card-name bracket content, seeded from a scan of real
production data (200k cards, ~86k with leftover bracket text) - see `cardpicker.tags`
for how these get matched against filenames during indexing. Excludes set-code-like
tokens (SLD, MH3, WOE, ...), which aren't semantic tags at all - see
`cardpicker.printing_candidates`'s `expansion_hint` handling for those instead.
"""

from typing import Optional

from cardpicker.models import Tag

# (name, aliases, display_name). display_name is None for almost every entry here - these
# names are already nice human-readable Title Case, so they fall back to rendering as `name`
# with no further seeding needed (see frontend useTagDisplayName). The two entries that do
# specify one ("Full Art", "Borderless") aren't renamed or given a *different* display_name -
# they're just given an explicit row so the taxonomy has no silent gaps, matching every other
# actively-displayed tag having a real display_name value rather than relying on fallback.
DEFAULT_TAGS: list[tuple[str, list[str], Optional[str]]] = [
    ("Borderless", ["Borderless Art"], "Borderless"),
    ("Popout", [], None),
    ("Extended", [], None),
    ("Showcase", [], None),
    ("Retro", [], None),
    ("Classic", [], None),
    ("Anime", [], None),
    ("Full Art", ["Fullart"], "Full Art"),
    ("Custom", [], None),
    ("Upscaled", ["Upscaled Scan"], None),
    ("Placeholder", [], None),
    ("Token", [], None),
    ("AI-Generated", ["Midjourney"], None),
]


def seed_default_tags() -> dict[str, int]:
    """
    Idempotent - safe to re-run. Creates any tag that doesn't exist yet, adds any alias from
    `DEFAULT_TAGS` that's missing from an already-existing tag, and backfills display_name for
    the (few) entries above that specify one - only when it's still null, never overwriting a
    manually-edited display_name (see Tag.display_name's help_text: "freely editable").
    """

    created = 0
    updated = 0
    for name, aliases, display_name in DEFAULT_TAGS:
        defaults: dict[str, object] = {"aliases": aliases}
        if display_name is not None:
            defaults["display_name"] = display_name
        tag, was_created = Tag.objects.get_or_create(name=name, defaults=defaults)
        if was_created:
            created += 1
            continue
        changed_fields = []
        missing_aliases = [alias for alias in aliases if alias not in tag.aliases]
        if missing_aliases:
            tag.aliases = [*tag.aliases, *missing_aliases]
            changed_fields.append("aliases")
        if display_name is not None and tag.display_name is None:
            tag.display_name = display_name
            changed_fields.append("display_name")
        if changed_fields:
            tag.save(update_fields=changed_fields)
            updated += 1
    return {"created": created, "updated": updated}


__all__ = ["seed_default_tags"]
