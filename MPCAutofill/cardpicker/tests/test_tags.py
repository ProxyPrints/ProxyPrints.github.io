import pytest

from cardpicker.models import Tag, TagAliasSuggestion, TagSuggestionStatus
from cardpicker.search.sanitisation import fix_whitespace
from cardpicker.tags import Tags
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    SourceFactory,
    TagFactory,
)

# `factory.Sequence` counters are process-global, and some other test modules' snapshot
# assertions hardcode exact sequence-derived values (e.g. "Artist 0"). Capture-and-restore
# keeps this module's use of these shared factories invisible to the rest of the suite,
# regardless of test collection order.
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
    TagFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


class TestMatchTagFuzzy:
    def test_high_confidence_match(self, db, settings):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()
        match = tags.match_tag_fuzzy("Fullart")
        assert match is not None
        matched_tag, confidence = match
        assert matched_tag.name == "Full Art"
        assert confidence >= settings.TAG_MATCH_HIGH_CONFIDENCE_THRESHOLD

    def test_no_match_below_low_threshold(self, db):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()
        assert tags.match_tag_fuzzy("Completely Unrelated Text") is None

    def test_empty_string_no_match(self, db):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()
        assert tags.match_tag_fuzzy("") is None

    def test_synthetic_nsfw_pseudo_tag_is_never_matched(self, db):
        # the NSFW entry in `self.tags` is a `models.Tag(...)` instance that's never
        # saved (pk=None) - it must never be returned as a fuzzy match, since promoting
        # it (aliasing/saving/FK-referencing an unsaved instance) would crash
        tags = Tags()
        assert tags.match_tag_fuzzy("NSFW") is None
        assert tags.match_tag_fuzzy("NSFWW") is None


class TestExtractFuzzyTagPromotion:
    def test_high_confidence_auto_promotes_alias_and_strips_name(self, db):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()

        name, tag_set, _, _, _ = tags.extract("Lightning Bolt [Fullart]")

        # extract() itself doesn't collapse whitespace left behind by a stripped tag -
        # real callers (Image/Folder.unpack_name) apply fix_whitespace() on top, same as here
        assert fix_whitespace(name) == "Lightning Bolt"
        assert tag_set == {"Full Art"}
        tag = Tag.objects.get(name="Full Art")
        assert "Fullart" in tag.aliases
        suggestion = TagAliasSuggestion.objects.get(raw_text="Fullart")
        assert suggestion.status == TagSuggestionStatus.AUTO_ACCEPTED
        assert suggestion.suggested_tag == tag

    def test_second_occurrence_hits_fast_exact_alias_path(self, db):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()
        tags.extract("Lightning Bolt [Fullart]")

        # a fresh Tags() instance picks up the alias that got promoted above
        tags_again = Tags()
        name, tag_set, _, _, _ = tags_again.extract("Lightning Strike [Fullart]")

        assert fix_whitespace(name) == "Lightning Strike"
        assert tag_set == {"Full Art"}
        # occurrence_count was only ever incremented once - the promoted alias short-circuits
        # straight to the exact-match path for every subsequent occurrence, this run or later
        assert TagAliasSuggestion.objects.get(raw_text="Fullart").occurrence_count == 1

    def test_medium_confidence_creates_pending_suggestion_without_applying(self, db, settings):
        settings.TAG_MATCH_LOW_CONFIDENCE_THRESHOLD = 0.4
        settings.TAG_MATCH_HIGH_CONFIDENCE_THRESHOLD = 0.95
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()

        name, tag_set, _, _, _ = tags.extract("Lightning Bolt [Fullish]")

        assert name == "Lightning Bolt [Fullish]"
        assert tag_set == set()
        tag = Tag.objects.get(name="Full Art")
        assert "Fullish" not in tag.aliases
        suggestion = TagAliasSuggestion.objects.get(raw_text="Fullish")
        assert suggestion.status == TagSuggestionStatus.PENDING
        assert suggestion.occurrence_count == 1

    def test_pending_suggestion_occurrence_count_increments_across_runs(self, db, settings):
        settings.TAG_MATCH_LOW_CONFIDENCE_THRESHOLD = 0.4
        settings.TAG_MATCH_HIGH_CONFIDENCE_THRESHOLD = 0.95
        TagFactory(name="Full Art", aliases=[])
        Tags().extract("Lightning Bolt [Fullish]")
        Tags().extract("Lightning Strike [Fullish]")

        assert TagAliasSuggestion.objects.get(raw_text="Fullish").occurrence_count == 2

    def test_rejected_suggestion_is_never_reapplied(self, db, settings):
        settings.TAG_MATCH_LOW_CONFIDENCE_THRESHOLD = 0.4
        settings.TAG_MATCH_HIGH_CONFIDENCE_THRESHOLD = 0.95
        tag = TagFactory(name="Full Art", aliases=[])
        TagAliasSuggestion.objects.create(
            raw_text="Fullish",
            suggested_tag=tag,
            confidence=0.7,
            occurrence_count=5,
            status=TagSuggestionStatus.REJECTED,
        )
        tags = Tags()

        name, tag_set, _, _, _ = tags.extract("Lightning Bolt [Fullish]")

        assert name == "Lightning Bolt [Fullish]"
        assert tag_set == set()
        suggestion = TagAliasSuggestion.objects.get(raw_text="Fullish")
        assert suggestion.status == TagSuggestionStatus.REJECTED
        assert suggestion.occurrence_count == 5  # untouched - a rejected suggestion is a no-op

    def test_below_low_threshold_creates_no_suggestion(self, db):
        TagFactory(name="Full Art", aliases=[])
        tags = Tags()

        name, tag_set, _, _, _ = tags.extract("Lightning Bolt [Zzyzx]")

        assert name == "Lightning Bolt [Zzyzx]"
        assert tag_set == set()
        assert not TagAliasSuggestion.objects.filter(raw_text="Zzyzx").exists()


class TestExtractExpansionHint:
    def test_lone_set_code_is_captured_as_hint_and_stripped(self, db):
        CanonicalExpansionFactory(code="mh3")
        tags = Tags()

        name, tag_set, canonical_card_pk, _, expansion_hint = tags.extract("Lightning Bolt [MH3]")

        assert fix_whitespace(name) == "Lightning Bolt"
        assert tag_set == set()
        assert canonical_card_pk is None
        assert expansion_hint == "mh3"

    def test_no_hint_when_no_expansion_code_present(self, db):
        tags = Tags()
        name, _, _, _, expansion_hint = tags.extract("Lightning Bolt [Foo]")
        assert name == "Lightning Bolt [Foo]"
        assert expansion_hint is None

    def test_no_hint_when_exact_canonical_card_already_resolved(self, db):
        expansion = CanonicalExpansionFactory(code="lea")
        canonical_card = CanonicalCardFactory(expansion=expansion, collector_number="100")
        tags = Tags()

        name, _, canonical_card_pk, _, expansion_hint = tags.extract("Lightning Bolt [LEA] {100}")

        assert canonical_card_pk == canonical_card.pk
        assert expansion_hint is None
