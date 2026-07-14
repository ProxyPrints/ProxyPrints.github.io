from cardpicker.constants import NSFW
from cardpicker.models import Tag, TagModerationClass
from cardpicker.sensitive_tags import SENSITIVE_TAGS, seed_sensitive_tags


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
        assert stats == {"created": 0, "updated": 0}
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
