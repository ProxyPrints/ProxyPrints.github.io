from cardpicker.default_tags import DEFAULT_TAGS
from cardpicker.models import Tag
from cardpicker.reason_tags import NO_MATCH_REASON_TAGS, seed_no_match_reason_tags


class TestSeedNoMatchReasonTags:
    def test_creates_all_six_reason_tags(self, db):
        stats = seed_no_match_reason_tags()
        assert stats["created"] == len(NO_MATCH_REASON_TAGS)

        names = set(
            Tag.objects.filter(
                name__in=[name for name, _description, _display_name in NO_MATCH_REASON_TAGS]
            ).values_list("name", flat=True)
        )
        assert names == {name for name, _description, _display_name in NO_MATCH_REASON_TAGS}

    def test_display_name_set_at_creation(self, db):
        seed_no_match_reason_tags()
        for name, _description, display_name in NO_MATCH_REASON_TAGS:
            assert Tag.objects.get(name=name).display_name == display_name

    def test_rerunning_does_not_duplicate(self, db):
        seed_no_match_reason_tags()
        count_after_first_run = Tag.objects.filter(
            name__in=[name for name, _description, _display_name in NO_MATCH_REASON_TAGS]
        ).count()

        stats = seed_no_match_reason_tags()

        count_after_second_run = Tag.objects.filter(
            name__in=[name for name, _description, _display_name in NO_MATCH_REASON_TAGS]
        ).count()
        assert stats["created"] == 0
        assert stats["updated"] == 0  # display_name already set on the first run, nothing left to backfill
        assert count_after_first_run == count_after_second_run == len(NO_MATCH_REASON_TAGS)

    def test_backfills_display_name_only_when_null_never_overwrites_manual_edit(self, db):
        name, _description, seeded_display_name = NO_MATCH_REASON_TAGS[0]
        Tag.objects.create(name=name, aliases=[], display_name=None)

        stats = seed_no_match_reason_tags()

        assert stats["created"] == len(NO_MATCH_REASON_TAGS) - 1
        assert stats["updated"] == 1
        assert Tag.objects.get(name=name).display_name == seeded_display_name

        # a second run must never clobber a manual edit make after seeding
        Tag.objects.filter(name=name).update(display_name="Admin's custom label")
        seed_no_match_reason_tags()
        assert Tag.objects.get(name=name).display_name == "Admin's custom label"

    def test_reason_tags_are_case_distinct_from_default_tags(self, db):
        # "upscaled" (reason tag) and "Upscaled" (DEFAULT_TAGS) are deliberately two separate
        # rows covering related but distinct vote populations - see reason_tags.py's header
        # comment. Exact-string collision (not just case-insensitive overlap) would mean
        # seeding silently reused an existing row instead of creating a new one.
        default_tag_names = {name for name, _aliases, _display_name in DEFAULT_TAGS}
        reason_tag_names = {name for name, _description, _display_name in NO_MATCH_REASON_TAGS}
        assert default_tag_names.isdisjoint(reason_tag_names)
