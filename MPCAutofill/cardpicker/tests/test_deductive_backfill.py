import pytest

from cardpicker.deductive_backfill import (
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    run_backfill,
    select_d1_candidates,
    select_d2_candidates,
    verify_zero_resolutions,
)
from cardpicker.models import PrintingTagStatus, VoteSource
from cardpicker.printing_consensus import resolve_printing
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
)

# `factory.Sequence` counters are process-global - see test_printing_consensus.py's identical
# fixture for the full rationale. Mirrored here since this module uses the same shared factories
# - including SourceFactory/CanonicalArtistFactory, consumed indirectly via CardFactory.source
# and CanonicalCardFactory.artist SubFactories, not just the ones referenced by name above.
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


def _unique_printing(name: str, printings_count: int = 1, **kwargs) -> "CanonicalCardFactory":
    printing = CanonicalCardFactory(name=name, **kwargs)
    CanonicalPrintingMetadataFactory(canonical_card=printing, printings_count=printings_count)
    return printing


class TestD1Selection:
    def test_unique_name_match_is_d1(self, db):
        printing = _unique_printing("Plumecreed Mentor")
        card = CardFactory(name="Plumecreed Mentor")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing.pk
        assert votes[0].tier == "d1"

    def test_parenthetical_suffix_is_stripped_by_normalization(self, db):
        # mirrors real corpus data: many cards carry an "(Style Artist Name)" suffix that
        # to_searchable strips (bracketed content removal) but CanonicalCard.name never has.
        printing = _unique_printing("Kusari-Gama")
        card = CardFactory(name="Kusari-Gama (Modern Tomas Giorello)")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing.pk

    def test_mid_string_the_is_preserved_post_460(self, db):
        # if to_searchable still stripped mid-string "the" (the pre-#460 bug), both of these
        # would normalize to the same string and the match would be ambiguous (2 matches, not
        # D1) instead of each resolving independently.
        printing_with_the = _unique_printing("Adanto, the First Fort")
        _unique_printing("Adanto First Fort")  # deliberately similar but distinct name
        card = CardFactory(name="Adanto, the First Fort")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing_with_the.pk

    def test_ambiguous_name_is_not_d1(self, db):
        _unique_printing("Forest", expansion=CanonicalExpansionFactory(code="ust"))
        _unique_printing("Forest", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Forest")
        assert list(select_d1_candidates()) == []

    def test_printings_count_greater_than_one_excludes_from_d1(self, db):
        # our table has exactly one CanonicalCard row for this name, but Scryfall's own
        # printings_count says there are more real printings we haven't imported yet - the
        # whole point of the cross-check is to not treat this as verified-unique.
        _unique_printing("Gilded Drake", printings_count=2)
        CardFactory(name="Gilded Drake")
        assert list(select_d1_candidates()) == []

    def test_missing_printing_metadata_is_treated_as_unverifiable(self, db):
        # a CanonicalCard with no CanonicalPrintingMetadata sidecar at all (predates that
        # import) must never be silently treated as printings_count == 1.
        CanonicalCardFactory(name="No Metadata Card")
        CardFactory(name="No Metadata Card")
        assert list(select_d1_candidates()) == []

    def test_resolved_card_is_excluded(self, db):
        _unique_printing("Already Resolved")
        card = CardFactory(name="Already Resolved")
        card.printing_tag_status = PrintingTagStatus.RESOLVED
        card.inferred_canonical_card = CanonicalCardFactory()
        card.save()
        assert list(select_d1_candidates()) == []

    def test_card_with_confirmed_canonical_card_is_excluded(self, db):
        printing = _unique_printing("Already Tagged")
        CardFactory(name="Already Tagged", canonical_card=printing)
        assert list(select_d1_candidates()) == []

    def test_card_with_any_existing_vote_is_excluded(self, db):
        # not just an existing deductive-backfill vote - ANY existing vote, since that's
        # exactly the scenario where an added AI vote could tip an already-human-backed
        # group over the resolution threshold (see deductive_backfill.py's docstring).
        _unique_printing("Has A Vote Already")
        card = CardFactory(name="Has A Vote Already")
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        assert list(select_d1_candidates()) == []

    def test_card_with_existing_deductive_vote_is_excluded(self, db):
        _unique_printing("Already Backfilled")
        card = CardFactory(name="Already Backfilled")
        CardPrintingTagFactory(
            card=card,
            printing=CanonicalCardFactory(),
            source=VoteSource.AI,
            anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
        )
        assert list(select_d1_candidates()) == []

    def test_card_with_resolved_custom_tag_is_excluded(self, db):
        # the catalog deliberately allows custom/fan art - once tag-vote consensus has
        # already confirmed "Custom", a name-based printing deduction is meaningless.
        _unique_printing("Custom Art Card")
        CardFactory(name="Custom Art Card", tags=["Custom"])
        assert list(select_d1_candidates()) == []

    def test_non_english_card_is_excluded(self, db):
        # name-matching compares against CanonicalCard.name (Scryfall's English oracle name);
        # a foreign-language card's name isn't a trustworthy signal for it.
        _unique_printing("Foreign Language Card")
        CardFactory(name="Foreign Language Card", language="FR")
        assert list(select_d1_candidates()) == []


class TestD2Selection:
    def test_expansion_hint_narrows_ambiguous_name_to_one(self, db):
        _unique_printing("Snow-Covered Forest", expansion=CanonicalExpansionFactory(code="csp"))
        matching = _unique_printing("Snow-Covered Forest", expansion=CanonicalExpansionFactory(code="wwk"))
        card = CardFactory(name="Snow-Covered Forest", expansion_hint="wwk")
        votes = list(select_d2_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == matching.pk
        assert votes[0].tier == "d2"

    def test_no_expansion_hint_is_not_d2(self, db):
        _unique_printing("No Hint Card", expansion=CanonicalExpansionFactory(code="csp"))
        _unique_printing("No Hint Card", expansion=CanonicalExpansionFactory(code="wwk"))
        CardFactory(name="No Hint Card", expansion_hint="")
        assert list(select_d2_candidates()) == []

    def test_hint_that_still_does_not_narrow_to_one_is_excluded(self, db):
        # hint present, but that (name, expansion) pair matches zero printings (stale/wrong
        # hint) - must not guess.
        _unique_printing("Wrong Hint Card", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Wrong Hint Card", expansion_hint="wwk")
        assert list(select_d2_candidates()) == []

    def test_unambiguous_name_is_not_d2(self, db):
        # D1's territory - a name matching exactly one printing is never D2, hint or not.
        _unique_printing("Solo Printing", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Solo Printing", expansion_hint="csp")
        assert list(select_d2_candidates()) == []


class TestRunBackfillWriteShape:
    def test_d1_vote_row_shape(self, db):
        printing = _unique_printing("Shape Test D1")
        card = CardFactory(name="Shape Test D1")
        result = run_backfill(tier="d1")
        assert result.d1_written == 1
        assert result.d2_written == 0
        assert result.gate_violations == []

        vote = card.printing_tags.get()
        assert vote.printing_id == printing.pk
        assert vote.is_no_match is False
        assert vote.anonymous_id == DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        assert vote.source == VoteSource.AI
        assert vote.confidence == 0.95

    def test_d2_vote_row_shape(self, db):
        matching = _unique_printing("Shape Test D2", expansion=CanonicalExpansionFactory(code="csp"))
        _unique_printing("Shape Test D2", expansion=CanonicalExpansionFactory(code="wwk"))
        card = CardFactory(name="Shape Test D2", expansion_hint="csp")
        result = run_backfill(tier="d2")
        assert result.d2_written == 1

        vote = card.printing_tags.get()
        assert vote.printing_id == matching.pk
        assert vote.source == VoteSource.AI
        assert vote.confidence == 0.90

    def test_dry_run_writes_nothing(self, db):
        _unique_printing("Dry Run Card")
        card = CardFactory(name="Dry Run Card")
        result = run_backfill(tier="d1", dry_run=True)
        assert result.d1_written == 1  # counted, but not persisted
        assert result.gate_violations == []
        assert card.printing_tags.count() == 0

    def test_limit_caps_total_written(self, db):
        # distinct alphabetic suffixes, not digits - to_searchable strips all digits, so
        # "Limit Card 0"/"Limit Card 1" would collide into the same normalized name and
        # make every one of them ambiguous (not D1) rather than exercising the --limit path.
        for suffix in ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]:
            _unique_printing(f"Limit Card {suffix}")
            CardFactory(name=f"Limit Card {suffix}")
        result = run_backfill(tier="d1", limit=2)
        assert result.total_written == 2

    def test_idempotent_on_rerun(self, db):
        _unique_printing("Idempotence Card")
        card = CardFactory(name="Idempotence Card")

        first = run_backfill(tier="d1")
        assert first.d1_written == 1
        assert card.printing_tags.count() == 1

        second = run_backfill(tier="d1")
        assert second.d1_written == 0
        assert card.printing_tags.count() == 1  # no duplicate vote


class TestZeroResolutionsGate:
    def test_backfill_never_resolves_an_ai_only_card(self, db):
        _unique_printing("Gate Test Card")
        card = CardFactory(name="Gate Test Card")
        result = run_backfill(tier="d1")
        assert result.gate_violations == []
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
        assert resolve_printing(card) is None

    def test_verify_zero_resolutions_detects_a_real_violation(self, db):
        # constructs the scenario _eligible_base_queryset is designed to prevent from ever
        # reaching run_backfill - a card with a pre-existing human vote, plus (bypassing
        # selection entirely) a same-outcome AI vote added directly - to prove the detector
        # itself actually catches a resolved card rather than trivially always passing.
        printing = CanonicalCardFactory()
        card = CardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        # two USER votes alone already clear consensus here - assert the fixture itself
        # actually resolves before layering the AI vote on top, so the test is meaningful.
        assert resolve_printing(card) == printing

        violations = verify_zero_resolutions([card.pk])
        assert violations == [card.pk]
