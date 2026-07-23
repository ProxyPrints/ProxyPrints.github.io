from unittest.mock import patch

import pytest

from cardpicker.models import PrintingTagStatus, VoteSource
from cardpicker.printing_consensus import (
    NO_MATCH,
    get_resolved_printings,
    get_vote_tally,
    resolve_and_persist_printing,
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
from cardpicker.vote_consensus import DEDUCTIVE_BACKFILL_ANONYMOUS_ID

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

    @pytest.mark.parametrize("machine_source", [VoteSource.DEDUCTION, VoteSource.OCR])
    def test_machine_only_insufficient(self, db, machine_source):
        # even a large, unanimous pile of machine-sourced votes (deduction or OCR) can never
        # resolve consensus alone - the winning group must contain at least one human-backed vote
        card = CardFactory()
        printing = CanonicalCardFactory()
        for _ in range(4):
            CardPrintingTagFactory(card=card, printing=printing, source=machine_source)
        assert resolve_printing(card) is None

    def test_machine_pooling_cannot_decide_a_live_human_vs_human_contest(self, db):
        # owner-ratified 2026-07-22 vote-weight scenario matrix, decision D1/cell A14 - proof
        # the resolver-core fix reaches the printing path (not just tag path): a human vote
        # plus a machine pile on one side (weight 1.0+4*0.5=3.0 raw) must not be able to tip a
        # contest against a single dissenting human vote (weight 1.0) - this must land as
        # UNRESOLVED (None), not the printing that has more RAW weight.
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        for _ in range(4):
            CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        assert resolve_printing(card) is None

    def test_machine_dissent_cannot_de_resolve_a_human_quorum_valid_winner(self, db):
        # owner-ratified 2026-07-22 vote-weight scenario matrix, decision D4/cell B4 - proof
        # the resolver-core fix reaches the printing path: 2 USER votes already clear quorum on
        # human weight alone (2.0 >= 2), so 3 DEDUCTION dissent votes (weight 1.5) must not be
        # able to drag the winner's share below 0.6 and silently revert RESOLVED -> UNRESOLVED
        # (this is the exact "23k+ deduction votes at scale" concern the matrix flags).
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        for _ in range(3):
            CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.DEDUCTION)
        assert resolve_printing(card) == printing_a

    @pytest.mark.parametrize("dissent_count", [4, 5, 6, 10, 100])
    def test_machine_dissent_cannot_de_resolve_regardless_of_pile_size(self, db, dissent_count):
        # 2026-07-22 hardening: the original D4 fix only checked its trigger against the
        # already-selected winner, so a large enough machine dissent pile (raw weight >= the
        # human group's) could win the winner-SELECTION step outright and then fail the
        # human-backed gate, returning None instead of resolving printing_a. Confirmed
        # empirically at N=4 (order-dependent tie) and N>=5 (deterministic de-resolution); this
        # must stay resolved to printing_a at every N, regardless of vote insertion order.
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        for _ in range(dissent_count):
            CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        assert resolve_printing(card) == printing_a


class TestDeductiveBackfillZeroWeight:
    """
    2026-07-23 owner ruling: the 2026-07-14 deductive-name-backfill's votes (source=DEDUCTION,
    anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID) carry weight 0.0 in every consensus
    computation, permanently - proven here at the `resolve_printing` level (winner selection,
    the quorum/share gate, and promotion), contrasted against unchanged behaviour for ordinary
    (non-backfill) machine votes and human votes.

    Every scenario below casts AT MOST ONE backfill-sourced vote per card, matching a genuine
    DB invariant (not just a test-data choice): `cardprintingtag_unique_printing_vote` is
    unique on `(card, printing, anonymous_id)`, and `deductive_backfill.py`'s own eligibility
    query only ever considers a card with ZERO pre-existing votes of any kind, so it writes
    at most one vote per card, ever - the backfill's own pile size (28,112) is spread across
    28,112 distinct cards, never stacked on one. Stage D's OCR/phash engines ARE allowed to
    vote on a card the backfill already touched (see `pipeline-fidelity-gate.md`'s §3 item 3 -
    the exclusion was deliberately NOT restored), so a card carrying one backfill vote
    alongside separate, ordinary OCR votes is the realistic shape these tests model.
    """

    def test_backfill_vote_alone_cannot_resolve(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        )
        assert resolve_printing(card) is None

    def test_backfill_vote_does_not_help_promote_a_card_an_ordinary_machine_vote_would_have(self, db):
        # 1 human vote (weight 1.0) + 1 ordinary OCR vote (weight 0.5) + 1 backfill deduction
        # vote (weight 0, all agreeing on the same printing): total human-backed weight 1.0,
        # non-human weight 0.5 (only the OCR vote counts) - 1.5 total, below
        # PRINTING_TAG_MIN_VOTES=2, so this must stay UNRESOLVED. If the backfill vote carried
        # its old machine weight (0.5) instead, the total would be 2.0 and this WOULD resolve
        # (see the control test immediately below, which is identical except the backfill vote
        # is swapped for a second ordinary machine vote) - this is the one scenario where the
        # zero-weighting is actually load-bearing for the outcome, not just "still insufficient
        # either way".
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="local-ocr-v1")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        )
        assert resolve_printing(card) is None

    def test_equivalent_shape_with_an_ordinary_second_machine_vote_does_resolve(self, db):
        # control for the test above: the identical shape (1 human vote + 2 machine-weight
        # votes for the same printing), but with a second ORDINARY machine vote (not the
        # zero-weighted backfill cohort) in the third slot - 1.0 + 0.5 + 0.5 = 2.0, share 1.0,
        # so this DOES promote to RESOLVED. Proves the zero-weighting is scoped to the
        # backfill's own anonymous_id, not to VoteSource.DEDUCTION (or "machine evidence") as a
        # whole, and that ordinary human+machine promotion behaviour is unchanged by this
        # ruling.
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="local-ocr-v1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="local-phash-v1")
        assert resolve_printing(card) == printing

    def test_backfill_vote_pooled_on_one_side_cannot_tip_a_human_vs_human_contest(self, db):
        # a single backfill vote pooled behind one side of a genuine human-vs-human contest
        # must not be able to tip it - mirrors test_machine_pooling_cannot_decide_a_live_
        # human_vs_human_contest, with the pooled machine vote specifically the zero-weighted
        # backfill cohort rather than an ordinary DEDUCTION/OCR vote
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(
            card=card, printing=printing_a, source=VoteSource.DEDUCTION, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        )
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        assert resolve_printing(card) is None

    def test_backfill_dissent_does_not_shrink_an_already_resolved_winners_share(self, db):
        # 2 user votes already resolve printing_a outright (weight 2.0, share 1.0); a single
        # backfill dissent vote for printing_b must not be able to drag that share back down -
        # mirrors test_machine_dissent_cannot_de_resolve_a_human_quorum_valid_winner, with the
        # dissenting vote specifically the zero-weighted backfill cohort
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(
            card=card, printing=printing_b, source=VoteSource.DEDUCTION, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        )
        assert resolve_printing(card) == printing_a

    def test_backfill_votes_remain_visible_in_the_raw_vote_tally(self, db):
        # the ruling zeroes CONSENSUS WEIGHT only - the row itself stays on the record forever
        # and must still show up, unweighted, in the raw per-outcome tally (`get_vote_tally`)
        # that display surfaces (e.g. /whatsthat) read from
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        )
        CardPrintingTagFactory(card=card, printing=None, is_no_match=True, source=VoteSource.USER)

        tally = get_vote_tally(card)
        entry_by_printing = {entry["printing"]: entry for entry in tally}
        assert entry_by_printing[printing]["count"] == 1
        assert entry_by_printing[printing]["is_no_match"] is False
        assert entry_by_printing[None]["count"] == 1
        assert entry_by_printing[None]["is_no_match"] is True


class TestResolveAndPersistPrintingReindex:
    """
    `resolve_and_persist_printing`'s ES side effect: reindex exactly when the outcome changes
    what `documents.py` actually indexes (see `_effective_indexed_printing_id`), and never let
    an ES failure take down the vote-submission DB write it rides in on.
    """

    def test_unresolved_to_resolved_fires_one_reindex_call(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        with patch("cardpicker.documents.reindex_card_safely") as mock_reindex:
            result = resolve_and_persist_printing(card)

        assert result == printing
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        mock_reindex.assert_called_once_with(card)

    def test_re_resolve_to_same_outcome_fires_zero_calls(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        with patch("cardpicker.documents.reindex_card_safely"):
            resolve_and_persist_printing(card)  # first call: UNRESOLVED -> RESOLVED, establishes the baseline

        with patch("cardpicker.documents.reindex_card_safely") as mock_reindex:
            result = resolve_and_persist_printing(card)  # same votes, same outcome, re-resolved

        assert result == printing
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        mock_reindex.assert_not_called()

    def test_resolved_to_contested_fires_a_call_and_indexed_fields_clear(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        with patch("cardpicker.documents.reindex_card_safely"):
            resolve_and_persist_printing(card)
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        # an equal-weight conflicting printing splits consensus (2 vs 2: share is exactly
        # 0.5, below PRINTING_TAG_MIN_SHARE of 0.6 - same tie shape as test_tie_returns_none)
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.USER)

        with patch("cardpicker.documents.reindex_card_safely") as mock_reindex:
            result = resolve_and_persist_printing(card)

        assert result is None
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
        mock_reindex.assert_called_once_with(card)
        # `card.canonical_card` is unset (no confirmed indexing match), so once RESOLVED is
        # lost, the fields `documents.py` actually indexes fall all the way back to None -
        # exactly what "the index needs updating" was gated on.
        assert card.get_expansion_code() is None
        assert card.get_collector_number() is None

    def test_es_failure_inside_reindex_does_not_block_the_db_write(self, db, caplog):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        with patch("cardpicker.documents.CardSearch") as mock_card_search:
            mock_card_search.return_value.update.side_effect = Exception("ES is down")
            result = resolve_and_persist_printing(card)  # must not raise

        assert result == printing
        assert "Failed to reindex card" in caplog.text

        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        assert card.inferred_canonical_card_id == printing.pk


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
