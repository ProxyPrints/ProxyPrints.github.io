import pytest

from cardpicker.models import PrintingTagStatus, VoteSource
from cardpicker.printing_consensus import (
    NO_MATCH,
    get_resolved_printings,
    resolve_printing,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
)

# `factory.Sequence` counters are process-global, and some other test modules'
# snapshot assertions hardcode exact sequence-derived values (e.g. "Artist 0").
# Capture-and-restore keeps this module's use of these shared factories invisible
# to the rest of the suite, regardless of test collection order.
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


class TestResolvePrinting:
    def test_no_votes_returns_none(self, db):
        card = CardFactory()
        assert resolve_printing(card) is None

    def test_consensus(self, db):
        # two user votes agreeing on the same printing clears both thresholds outright
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        assert resolve_printing(card) == printing

    def test_tie_returns_none(self, db):
        # two outcomes each with equal weight (2 user votes apiece): share is exactly
        # 0.5 for the winner, which is below PRINTING_TAG_MIN_SHARE (0.6)
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        assert resolve_printing(card) is None

    def test_contested_returns_none(self, db):
        # a three-way split where the leading outcome clears PRINTING_TAG_MIN_VOTES but
        # not PRINTING_TAG_MIN_SHARE
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        printing_c = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_c, source=VoteSource.USER)
        assert resolve_printing(card) is None

    def test_no_match_wins_consensus(self, db):
        # two no-match votes outweigh a single vote for a specific printing
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=None, is_no_match=True, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=None, is_no_match=True, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        assert resolve_printing(card) == NO_MATCH

    def test_admin_override(self, db):
        # a single admin vote (weight 5) outweighs two conflicting user votes (weight 2)
        # for a different printing - this is the "override" behaviour, arising from the
        # same weighted formula rather than a special-cased branch
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.ADMIN)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        assert resolve_printing(card) == printing_a

    def test_ai_only_insufficient(self, db):
        # even a large, unanimous pile of AI-sourced votes can never resolve consensus
        # alone - the winning group must contain at least one non-AI vote
        card = CardFactory()
        printing = CanonicalCardFactory()
        for _ in range(4):
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.AI)
        assert resolve_printing(card) is None


class TestGetResolvedPrintings:
    """
    `get_resolved_printings` is the shared hard-gate helper consumed by both the search
    re-rank and attribute-filter logic in `search_functions.retrieve_card_identifiers` - these
    tests exist independently of that consumer so the gate itself (RESOLVED in, everything
    else out) is verified without needing ES/HTTP machinery.
    """

    def test_resolved_card_is_present_with_correct_data(self, db):
        expansion = CanonicalExpansionFactory(code="ice")
        printing = CanonicalCardFactory(expansion=expansion, collector_number="61")
        CanonicalPrintingMetadataFactory(canonical_card=printing, full_art=True, border_color="borderless")
        card = CardFactory(
            identifier="resolved-card",
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=printing,
        )
        result = get_resolved_printings([card.identifier])
        assert card.identifier in result
        resolved = result[card.identifier]
        assert resolved.expansion_code == "ICE"
        assert resolved.collector_number == "61"
        assert resolved.full_art is True
        assert resolved.border_color == "borderless"

    def test_resolved_card_without_metadata_defaults_attributes(self, db):
        # a `CanonicalCard` with no `CanonicalPrintingMetadata` sidecar row (e.g. metadata
        # import hasn't run for it yet) must not crash the lookup - full_art/border_color
        # fall back to their "unknown" defaults rather than raising.
        printing = CanonicalCardFactory()
        card = CardFactory(
            identifier="resolved-no-metadata",
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=printing,
        )
        result = get_resolved_printings([card.identifier])
        resolved = result[card.identifier]
        assert resolved.full_art is False
        assert resolved.border_color == ""

    def test_unresolved_card_is_absent(self, db):
        card = CardFactory(identifier="unresolved-card", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        assert get_resolved_printings([card.identifier]) == {}

    def test_no_match_card_is_absent(self, db):
        card = CardFactory(identifier="no-match-card", printing_tag_status=PrintingTagStatus.NO_MATCH)
        assert get_resolved_printings([card.identifier]) == {}

    def test_mixed_statuses_only_resolved_present(self, db):
        printing = CanonicalCardFactory()
        resolved_card = CardFactory(
            identifier="mixed-resolved",
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=printing,
        )
        unresolved_card = CardFactory(identifier="mixed-unresolved", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        no_match_card = CardFactory(identifier="mixed-no-match", printing_tag_status=PrintingTagStatus.NO_MATCH)
        result = get_resolved_printings(
            [resolved_card.identifier, unresolved_card.identifier, no_match_card.identifier]
        )
        assert set(result.keys()) == {resolved_card.identifier}

    def test_identifier_not_in_database_is_absent(self, db):
        assert get_resolved_printings(["does-not-exist"]) == {}
