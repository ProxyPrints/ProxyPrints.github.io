"""
The sensitive-tag taxonomy for the moderation layer (see docs/features/moderation.md).
Sensitive tags (`Tag.moderation_class == SENSITIVE`) cannot be resolved by crowd consensus
alone - a would-be resolution parks as `pending_approval` until a privileged (moderator/
admin) vote co-signs it; see cardpicker.tag_consensus.

Kept as its own module + manual idempotent management command rather than a data migration,
mirroring cardpicker.reason_tags/cardpicker.default_tags exactly - see reason_tags.py's
header comment for why a data migration breaks the tests that assert on the complete set of
Tag rows.

These tag names are a federation interchange contract (like the no-match reason tags) -
renaming any of them is a breaking data migration, not a refactor. "NSFW" deliberately
reuses the pre-existing `cardpicker.constants.NSFW` name: filename-bracket tagging (e.g.
"[NSFW]" - see cardpicker.tags, which injects a synthetic never-persisted Tag of this name
precisely so unseeded instances still match it) and the frontend's default
`excludesTags: ["NSFW"]` both already speak this exact string, and a lowercase twin would
split mature-content state across two names that each miss half the cards. Once seeded, the
real row simply replaces the synthetic pseudo-tag in the tag matcher (real DB rows win the
lowercased key - see Tags.get_tags).
"""

from cardpicker.constants import NSFW
from cardpicker.models import Tag, TagModerationClass

# (name, description, display_name) - same shape as reason_tags.NO_MATCH_REASON_TAGS.
# `description` is documentation only; `display_name` is seeded presentation text the
# frontend looks up via useTagDisplayName.
SENSITIVE_TAGS: list[tuple[str, str, str]] = [
    (NSFW, "Mature/adult content - excluded from search by default", "NSFW"),
    ("low-res", "Image quality too poor to print", "Low quality"),
    ("incorrect-info", "Card text/details do not match the real card", "Incorrect card info"),
]


def seed_sensitive_tags() -> dict[str, int]:
    """
    Idempotent - safe to re-run. Creates any tag that doesn't exist yet (display_name and
    moderation_class set at creation). For an already-existing tag it backfills display_name
    only if still null (never overwrites a manual edit, same contract as
    seed_no_match_reason_tags) and *upgrades* moderation_class to SENSITIVE if it isn't
    already - an instance that had a plain "NSFW" tag before this feature (e.g. hand-created,
    or a future seeding-order change) must end up with the gate active, or the moderation
    layer silently doesn't apply to the one tag it exists for.
    """

    created = 0
    updated = 0
    for name, _description, display_name in SENSITIVE_TAGS:
        tag, was_created = Tag.objects.get_or_create(
            name=name,
            defaults={"aliases": [], "display_name": display_name, "moderation_class": TagModerationClass.SENSITIVE},
        )
        if was_created:
            created += 1
            continue
        update_fields = []
        if tag.display_name is None:
            tag.display_name = display_name
            update_fields.append("display_name")
        if tag.moderation_class != TagModerationClass.SENSITIVE:
            tag.moderation_class = TagModerationClass.SENSITIVE
            update_fields.append("moderation_class")
        if update_fields:
            tag.save(update_fields=update_fields)
            updated += 1
    return {"created": created, "updated": updated}


__all__ = ["seed_sensitive_tags", "SENSITIVE_TAGS"]
