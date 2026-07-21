from cardpicker.constants import NSFW
from cardpicker.models import Tag, TagModerationClass
from cardpicker.sensitive_tags import (
    FORMERLY_SENSITIVE_TAG_NAMES,
    SENSITIVE_TAGS,
    seed_sensitive_tags,
)


class TestSeedSensitiveTags:
    def test_creates_all_sensitive_tags(self, db):
        stats = seed_sensitive_tags()
        assert stats["created"] == len(SENSITIVE_TAGS)

        expected_names = {name for name, _description, _display_name in SENSITIVE_TAGS}
        assert NSFW in expected_names  # the taxonomy reuses the pre-existing constant, not a lowercase twin
        assert "appropriate-bleed" in expected_names  # positive framing - see sensitive_tags.py
        names = set(Tag.objects.filter(name__in=expected_names).values_list("name", flat=True))
        assert names == expected_names

    def test_seeded_tags_are_sensitive_with_display_names(self, db):
        seed_sensitive_tags()
        for name, _description, display_name in SENSITIVE_TAGS:
            tag = Tag.objects.get(name=name)
            assert tag.moderation_class == TagModerationClass.SENSITIVE
            assert tag.display_name == display_name

    def test_rerunning_does_not_duplicate_or_touch_anything(self, db):
        seed_sensitive_tags()
        stats = seed_sensitive_tags()
        assert stats == {"created": 0, "updated": 0, "downgraded": 0}
        assert Tag.objects.filter(
            name__in=[name for name, _description, _display_name in SENSITIVE_TAGS]
        ).count() == len(SENSITIVE_TAGS)

    def test_upgrades_preexisting_standard_row_to_sensitive(self, db):
        # e.g. an instance that hand-created a plain "NSFW" tag before this feature existed:
        # the gate must end up active on it, or the moderation layer silently doesn't apply
        # to the one tag it exists for
        Tag.objects.create(name=NSFW, aliases=[], display_name="Mature")
        stats = seed_sensitive_tags()
        assert stats["created"] == len(SENSITIVE_TAGS) - 1
        assert stats["updated"] == 1
        tag = Tag.objects.get(name=NSFW)
        assert tag.moderation_class == TagModerationClass.SENSITIVE
        assert tag.display_name == "Mature"  # manual presentation text is never clobbered

    def test_backfills_null_display_name(self, db):
        name, _description, seeded_display_name = SENSITIVE_TAGS[1]
        Tag.objects.create(name=name, aliases=[], display_name=None, moderation_class=TagModerationClass.SENSITIVE)
        stats = seed_sensitive_tags()
        assert stats["updated"] == 1
        assert Tag.objects.get(name=name).display_name == seeded_display_name

    def test_default_moderation_class_is_standard(self, db):
        # every tag created outside this taxonomy keeps standard consensus behavior
        assert Tag.objects.create(name="Some Ordinary Tag", aliases=[]).moderation_class == (
            TagModerationClass.STANDARD
        )

    def test_ai_generated_is_not_a_sensitive_tag(self, db):
        # owner decision 2026-07-21 (public issue #261 follow-up): ordinary crowd consensus is
        # fine for AI-Generated, no moderator co-sign required - see this list's own comment.
        expected_names = {name for name, _description, _display_name in SENSITIVE_TAGS}
        assert "AI-Generated" not in expected_names


class TestSeedSensitiveTagsDowngradesFormerlySensitive:
    """Owner decision 2026-07-21: AI-Generated was upgraded to SENSITIVE by PR #263, then
    reverted. `seed_sensitive_tags` must sync that reversal on any instance that already ran the
    #263-era seed and is stuck with the row at SENSITIVE - a prod re-run of this same command is
    the documented fix, not a fresh migration."""

    def test_downgrades_a_row_stuck_at_sensitive_from_the_prior_seed(self, db):
        Tag.objects.create(name="AI-Generated", aliases=["Midjourney"], moderation_class=TagModerationClass.SENSITIVE)
        stats = seed_sensitive_tags()
        assert stats["downgraded"] == 1
        assert Tag.objects.get(name="AI-Generated").moderation_class == TagModerationClass.STANDARD

    def test_rerunning_after_downgrade_is_a_no_op(self, db):
        Tag.objects.create(name="AI-Generated", aliases=[], moderation_class=TagModerationClass.SENSITIVE)
        seed_sensitive_tags()
        stats = seed_sensitive_tags()
        assert stats["downgraded"] == 0
        assert Tag.objects.get(name="AI-Generated").moderation_class == TagModerationClass.STANDARD

    def test_a_never_sensitive_row_is_left_alone(self, db):
        # the common case: a fresh instance, or one that only ever seeded AI-Generated via
        # seed_default_tags (STANDARD by model default) - no downgrade to report.
        Tag.objects.create(name="AI-Generated", aliases=[], moderation_class=TagModerationClass.STANDARD)
        stats = seed_sensitive_tags()
        assert stats["downgraded"] == 0
        assert Tag.objects.get(name="AI-Generated").moderation_class == TagModerationClass.STANDARD

    def test_a_missing_row_is_not_created_by_the_downgrade_sync(self, db):
        # seed_sensitive_tags must never create a FORMERLY_SENSITIVE_TAG_NAMES row that doesn't
        # already exist - that taxonomy is owned by seed_default_tags now, not this module.
        stats = seed_sensitive_tags()
        assert stats["downgraded"] == 0
        assert not Tag.objects.filter(name="AI-Generated").exists()

    def test_unrelated_sensitive_tag_is_never_touched_by_the_downgrade_sync(self, db):
        # a hand-set SENSITIVE tag with a name this taxonomy has never managed must be immune -
        # the sync is scoped to FORMERLY_SENSITIVE_TAG_NAMES by exact name, never "every
        # SENSITIVE row not currently in SENSITIVE_TAGS".
        Tag.objects.create(
            name="Some Admin Set This Sensitive", aliases=[], moderation_class=TagModerationClass.SENSITIVE
        )
        seed_sensitive_tags()
        assert Tag.objects.get(name="Some Admin Set This Sensitive").moderation_class == TagModerationClass.SENSITIVE

    def test_formerly_sensitive_tag_names_contains_ai_generated(self):
        assert FORMERLY_SENSITIVE_TAG_NAMES == frozenset({"AI-Generated"})
