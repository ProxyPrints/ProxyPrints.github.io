from cardpicker.deductive_backfill import DEDUCTIVE_BACKFILL_ANONYMOUS_ID
from cardpicker.filename_candidates import (
    FILENAME_CANDIDATES_ANONYMOUS_ID,
    MAX_CANDIDATE_CONFIDENCE,
    NAME_ONLY_CONFIDENCE,
    SIGNAL_CONFIDENCE_BONUS,
    generate_candidates_for_card,
    run_filename_candidate_narrowing,
    select_candidates,
)
from cardpicker.local_identify_printing_tags import CandidatePrinting
from cardpicker.models import CardPrintingTag, PrintingTagStatus, VoteSource
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
)


class _FixedIndex:
    """Test double for `CandidateNameIndex`: returns the same fixed candidate list regardless of
    the name queried, so `generate_candidates_for_card`'s own signal/weighting logic can be
    exercised without a real DB-backed name scan."""

    def __init__(self, candidates: list[CandidatePrinting]) -> None:
        self._candidates = candidates

    def candidates_for(self, name: str) -> list[CandidatePrinting]:
        return list(self._candidates)


class TestGenerateCandidatesForCard:
    def test_no_name_match_abstains(self, db):
        card = CardFactory(name="Nothing Matches This")
        result = generate_candidates_for_card(card, _FixedIndex([]), {})
        assert result.candidates == ()
        assert result.abstain_reason == "no-name-match"

    def test_ambiguous_name_produces_a_weighted_set_not_nothing(self, db):
        # the core owner ruling this module implements: two name candidates, no other signal -
        # both are kept and weighted, never collapsed to no-match.
        card = CardFactory(name="Forest", expansion_hint="", canonical_artist_id=None, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1"),
                CandidatePrinting(pk=2, expansion_code="csp", collector_number="2"),
            ]
        )
        result = generate_candidates_for_card(card, index, {})
        assert result.abstain_reason is None
        assert {c.printing_id for c in result.candidates} == {1, 2}
        assert all(c.confidence == NAME_ONLY_CONFIDENCE for c in result.candidates)
        assert all(c.matched_signals == frozenset() for c in result.candidates)

    def test_single_candidate_no_signals_is_still_weighted_not_a_special_case(self, db):
        card = CardFactory(name="Plumecreed Mentor", expansion_hint="", canonical_artist_id=None, tags=[])
        index = _FixedIndex([CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")])
        result = generate_candidates_for_card(card, index, {})
        assert result.abstain_reason is None
        assert len(result.candidates) == 1
        assert result.candidates[0].printing_id == 1
        assert result.candidates[0].confidence == NAME_ONLY_CONFIDENCE

    def test_expansion_hint_boosts_the_matching_candidate_only(self, db):
        card = CardFactory(name="Forest", expansion_hint="wwk", canonical_artist_id=None, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1"),
                CandidatePrinting(pk=2, expansion_code="wwk", collector_number="2"),
            ]
        )
        result = generate_candidates_for_card(card, index, {})
        assert result.abstain_reason is None
        by_pk = {c.printing_id: c for c in result.candidates}
        assert by_pk[1].confidence == NAME_ONLY_CONFIDENCE
        assert by_pk[1].matched_signals == frozenset()
        assert by_pk[2].confidence == NAME_ONLY_CONFIDENCE + SIGNAL_CONFIDENCE_BONUS
        assert by_pk[2].matched_signals == frozenset({"expansion_hint"})

    def test_expansion_hint_matching_none_is_discarded_not_a_contradiction(self, db):
        # a single signal that agrees with none of the candidates is NOT the narrow
        # "cannot both be true" contradiction this module abstains on - it's simply discarded,
        # and generation proceeds on the unmodified base set.
        card = CardFactory(name="Forest", expansion_hint="zzz", canonical_artist_id=None, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1"),
                CandidatePrinting(pk=2, expansion_code="csp", collector_number="2"),
            ]
        )
        result = generate_candidates_for_card(card, index, {})
        assert result.abstain_reason is None
        assert {c.printing_id for c in result.candidates} == {1, 2}
        assert all(c.confidence == NAME_ONLY_CONFIDENCE for c in result.candidates)

    def test_two_agreeing_signals_stack_confidence_on_the_same_candidate(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        card = CardFactory(name="Forest", expansion_hint="wwk", canonical_artist=artist, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1", artist_name="Someone Else"),
                CandidatePrinting(pk=2, expansion_code="wwk", collector_number="2", artist_name="Rebecca Guay"),
            ]
        )
        result = generate_candidates_for_card(card, index, {artist.pk: "Rebecca Guay"})
        assert result.abstain_reason is None
        by_pk = {c.printing_id: c for c in result.candidates}
        assert by_pk[2].confidence == min(NAME_ONLY_CONFIDENCE + 2 * SIGNAL_CONFIDENCE_BONUS, MAX_CANDIDATE_CONFIDENCE)
        assert by_pk[2].matched_signals == frozenset({"expansion_hint", "artist"})
        assert by_pk[1].confidence == NAME_ONLY_CONFIDENCE

    def test_confidence_never_exceeds_the_cap(self, db):
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        card = CardFactory(name="Forest", expansion_hint="wwk", canonical_artist=artist, tags=["Full Art"])
        index = _FixedIndex(
            [
                CandidatePrinting(
                    pk=1,
                    expansion_code="wwk",
                    collector_number="2",
                    artist_name="Rebecca Guay",
                    full_art=True,
                )
            ]
        )
        result = generate_candidates_for_card(card, index, {artist.pk: "Rebecca Guay"})
        assert result.candidates[0].confidence == MAX_CANDIDATE_CONFIDENCE

    def test_treatment_tag_signal_matches_full_art(self, db):
        card = CardFactory(name="Forest", expansion_hint="", canonical_artist_id=None, tags=["Full Art"])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1", full_art=False),
                CandidatePrinting(pk=2, expansion_code="csp", collector_number="2", full_art=True),
            ]
        )
        result = generate_candidates_for_card(card, index, {})
        by_pk = {c.printing_id: c for c in result.candidates}
        assert by_pk[2].matched_signals == frozenset({"treatment"})
        assert by_pk[1].matched_signals == frozenset()

    def test_contradiction_two_signals_agree_on_disjoint_candidates_abstains(self, db):
        # expansion_hint agrees only with pk=1; artist agrees only with pk=2 - each signal is
        # individually corroborated, but nothing satisfies both. That is the narrow "cannot both
        # be true" case, not merely "failed to agree".
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        card = CardFactory(name="Forest", expansion_hint="ust", canonical_artist=artist, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1", artist_name="Someone Else"),
                CandidatePrinting(pk=2, expansion_code="csp", collector_number="2", artist_name="Rebecca Guay"),
            ]
        )
        result = generate_candidates_for_card(card, index, {artist.pk: "Rebecca Guay"})
        assert result.candidates == ()
        assert result.abstain_reason == "contradiction"
        assert result.contradiction_detail is not None

    def test_single_signal_alone_can_never_trigger_contradiction(self, db):
        # only one signal fired (artist) - by construction there is nothing for it to
        # contradict, regardless of how the base set looks.
        artist = CanonicalArtistFactory(name="Nobody Matching")
        card = CardFactory(name="Forest", expansion_hint="", canonical_artist=artist, tags=[])
        index = _FixedIndex(
            [
                CandidatePrinting(pk=1, expansion_code="ust", collector_number="1", artist_name="Someone Else"),
                CandidatePrinting(pk=2, expansion_code="csp", collector_number="2", artist_name="Someone Else Too"),
            ]
        )
        result = generate_candidates_for_card(card, index, {artist.pk: "Nobody Matching"})
        assert result.abstain_reason is None
        assert {c.printing_id for c in result.candidates} == {1, 2}


class TestEligibility:
    def test_card_already_covered_by_deductive_backfill_is_excluded(self, db):
        printing_a = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="ust"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_a)
        printing_b = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="csp"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_b)
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card,
            printing=printing_a,
            source=VoteSource.DEDUCTION,
            anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
        )
        assert list(select_candidates()) == []

    def test_card_with_own_prior_vote_is_excluded(self, db):
        printing = CanonicalCardFactory(name="Forest")
        CanonicalPrintingMetadataFactory(canonical_card=printing)
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            source=VoteSource.DEDUCTION,
            anonymous_id=FILENAME_CANDIDATES_ANONYMOUS_ID,
        )
        assert list(select_candidates()) == []

    def test_custom_tagged_card_is_excluded(self, db):
        CanonicalCardFactory(name="Custom Card")
        CardFactory(name="Custom Card", tags=["Custom"])
        assert list(select_candidates()) == []


class TestRunFilenameCandidateNarrowing:
    def test_dry_run_writes_nothing(self, db):
        printing_a = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="ust"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_a)
        printing_b = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="csp"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_b)
        card = CardFactory(name="Forest")

        result = run_filename_candidate_narrowing(dry_run=True)

        assert result.cards_with_candidates == 1
        assert result.candidate_set_size_histogram == {2: 1}
        assert result.votes_written == 2
        assert not CardPrintingTag.objects.filter(card=card).exists()

    def test_write_casts_a_vote_per_candidate_and_passes_the_gate(self, db):
        printing_a = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="ust"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_a)
        printing_b = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="csp"))
        CanonicalPrintingMetadataFactory(canonical_card=printing_b)
        card = CardFactory(name="Forest")

        result = run_filename_candidate_narrowing(dry_run=False)

        assert result.gate_violations == []
        votes = list(CardPrintingTag.objects.filter(card=card, anonymous_id=FILENAME_CANDIDATES_ANONYMOUS_ID))
        assert {v.printing_id for v in votes} == {printing_a.pk, printing_b.pk}
        assert all(v.source == VoteSource.DEDUCTION for v in votes)
        assert all(v.is_no_match is False for v in votes)
        # a machine-only card can never resolve - the human-backed gate blocks it regardless of
        # how many DEDUCTION votes this module casts for it.
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_contradiction_writes_no_votes_for_that_card(self, db):
        printing_a = CanonicalCardFactory(
            name="Forest", expansion=CanonicalExpansionFactory(code="ust"), artist__name="Someone Else"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_a)
        printing_b = CanonicalCardFactory(
            name="Forest", expansion=CanonicalExpansionFactory(code="csp"), artist__name="Rebecca Guay"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_b)
        card = CardFactory(name="Forest", expansion_hint="ust", canonical_artist_id=printing_b.artist_id)

        result = run_filename_candidate_narrowing(dry_run=False)

        assert result.cards_abstained_contradiction == 1
        assert result.votes_written == 0
        assert not CardPrintingTag.objects.filter(card=card).exists()
