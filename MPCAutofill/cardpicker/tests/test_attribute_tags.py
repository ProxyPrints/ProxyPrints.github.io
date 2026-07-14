from cardpicker.attribute_tags import (
    ATTRIBUTE_CHIP_TAG_NAMES,
    ATTRIBUTE_TAGS,
    seed_attribute_tags,
)
from cardpicker.models import Tag


class TestSeedAttributeTags:
    def test_creates_every_configured_tag(self, db):
        stats = seed_attribute_tags()
        assert stats["created"] == len(ATTRIBUTE_TAGS)
        for name, _display_name in ATTRIBUTE_TAGS:
            assert Tag.objects.filter(name=name).exists()

    def test_idempotent(self, db):
        seed_attribute_tags()
        second = seed_attribute_tags()
        assert second["created"] == 0
        assert Tag.objects.filter(name__in=[name for name, _ in ATTRIBUTE_TAGS]).count() == len(ATTRIBUTE_TAGS)

    def test_never_overwrites_a_manual_edit(self, db):
        seed_attribute_tags()
        tag = Tag.objects.get(name="Etched")
        tag.display_name = "Manually Renamed"
        tag.save()

        seed_attribute_tags()

        tag.refresh_from_db()
        assert tag.display_name == "Manually Renamed"

    def test_chip_tag_names_are_all_seedable_or_already_in_default_tags(self, db):
        from cardpicker.default_tags import DEFAULT_TAGS, seed_default_tags

        seed_default_tags()
        seed_attribute_tags()
        default_names = {name for name, _aliases, _display_name in DEFAULT_TAGS}
        attribute_names = {name for name, _display_name in ATTRIBUTE_TAGS}
        assert set(ATTRIBUTE_CHIP_TAG_NAMES) <= default_names | attribute_names
        for name in ATTRIBUTE_CHIP_TAG_NAMES:
            assert Tag.objects.filter(name=name).exists(), f"{name!r} is not seeded by either seed command"
