"""
The real descriptor taxonomy for card-name bracket content, seeded from a scan of real
production data (200k cards, ~86k with leftover bracket text) - see `cardpicker.tags`
for how these get matched against filenames during indexing. Excludes set-code-like
tokens (SLD, MH3, WOE, ...), which aren't semantic tags at all - see
`cardpicker.printing_candidates`'s `expansion_hint` handling for those instead.
"""

from cardpicker.models import Tag

DEFAULT_TAGS: list[tuple[str, list[str]]] = [
    ("Borderless", ["Borderless Art"]),
    ("Popout", []),
    ("Extended", []),
    ("Showcase", []),
    ("Retro", []),
    ("Classic", []),
    ("Anime", []),
    ("Full Art", ["Fullart"]),
    ("Custom", []),
    ("Upscaled", ["Upscaled Scan"]),
    ("Placeholder", []),
    ("Token", []),
    ("AI-Generated", ["Midjourney"]),
]


def seed_default_tags() -> dict[str, int]:
    """
    Idempotent - safe to re-run. Creates any tag that doesn't exist yet, and adds any
    alias from `DEFAULT_TAGS` that's missing from an already-existing tag (e.g. if it
    was previously created by hand, or by an earlier version of this list).
    """

    created = 0
    updated = 0
    for name, aliases in DEFAULT_TAGS:
        tag, was_created = Tag.objects.get_or_create(name=name, defaults={"aliases": aliases})
        if was_created:
            created += 1
            continue
        missing_aliases = [alias for alias in aliases if alias not in tag.aliases]
        if missing_aliases:
            tag.aliases = [*tag.aliases, *missing_aliases]
            tag.save(update_fields=["aliases"])
            updated += 1
    return {"created": created, "updated": updated}


__all__ = ["seed_default_tags"]
