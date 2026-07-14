from cardpicker.default_tags import DEFAULT_TAGS, seed_default_tags
from cardpicker.models import Tag


class TestSeedDefaultTags:
    def test_creates_every_tag(self, db):
        stats = seed_default_tags()
        assert stats["created"] == len(DEFAULT_TAGS)
        assert Tag.objects.count() == len(DEFAULT_TAGS)

    def test_display_name_only_set_for_full_art_and_borderless(self, db):
        seed_default_tags()
        assert Tag.objects.get(name="Full Art").display_name == "Full Art"
        assert Tag.objects.get(name="Borderless").display_name == "Borderless"
        # every other seeded tag has no display_name - it's already a nice Title Case
        # `name`, so frontend fallback (displayName ?? name) covers it without a seeded row
        others = Tag.objects.exclude(name__in=["Full Art", "Borderless"])
        assert all(tag.display_name is None for tag in others)

    def test_rerunning_does_not_duplicate_or_reclobber(self, db):
        seed_default_tags()
        stats = seed_default_tags()
        assert stats["created"] == 0
        assert stats["updated"] == 0
        assert Tag.objects.count() == len(DEFAULT_TAGS)

    def test_backfills_display_name_only_when_null_never_overwrites_manual_edit(self, db):
        Tag.objects.create(name="Full Art", aliases=[], display_name=None)

        stats = seed_default_tags()

        assert stats["created"] == len(DEFAULT_TAGS) - 1
        assert stats["updated"] == 1
        assert Tag.objects.get(name="Full Art").display_name == "Full Art"

        Tag.objects.filter(name="Full Art").update(display_name="Admin's custom label")
        seed_default_tags()
        assert Tag.objects.get(name="Full Art").display_name == "Admin's custom label"
