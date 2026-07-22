import pytest

from django.conf import settings

from cardpicker.models import VoteSource
from cardpicker.tests.factories import CardArtistVoteFactory, CardFactory
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    PENDING_PRIVILEGED,
    VoteTuple,
    is_human_backed_source,
    resolve_weighted_consensus,
)

# Shorthand matching the ratified vote-weight scenario matrix's own TEST-SPEC notation
# (`VT(outcome_key, weight, is_human_backed, is_privileged=False, is_implicit=False)`) -
# `VoteTuple`'s field order already matches it exactly, so this is a plain alias, not a
# reduced/adapted shape.
VT = VoteTuple


class TestIsHumanBackedSource:
    """Direct coverage of the 2026-07-15 AI->DEDUCTION/OCR split's single source of truth for
    the human-backed gate - both new machine-derived values must read as non-human-backed,
    same as the old single AI value did. FEDERATED is also non-human-backed, as a defensive
    default before any federation importer exists (see docs/federation-v1.md's
    FEDERATED_VOTE_GATE_MODE design for the eventual real, per-peer-promotable mechanism);
    everything else is human-backed by default."""

    def test_deduction_ocr_and_federated_are_not_human_backed(self):
        assert is_human_backed_source(VoteSource.DEDUCTION) is False
        assert is_human_backed_source(VoteSource.OCR) is False
        assert is_human_backed_source(VoteSource.FEDERATED) is False

    def test_user_and_admin_are_human_backed(self):
        assert is_human_backed_source(VoteSource.USER) is True
        assert is_human_backed_source(VoteSource.ADMIN) is True


class TestResolveWeightedConsensus:
    def test_no_votes_returns_none(self):
        assert resolve_weighted_consensus([], min_weight=2, min_share=0.6) is None

    def test_single_group_clears_thresholds(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_below_min_weight_returns_none(self):
        votes = [VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_tie_below_min_share_returns_none(self):
        # two outcomes with equal weight: share is exactly 0.5, below a 0.6 threshold
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_admin_style_weight_override(self):
        # one high-weight vote (e.g. an "admin") outweighs two conflicting low-weight votes
        votes = [
            VoteTuple(outcome_key="a", weight=5.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_ai_only_votes_never_resolve_even_with_large_weight(self):
        votes = [VoteTuple(outcome_key="a", weight=10.0, is_human_backed=False) for _ in range(5)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_mixed_ai_and_non_ai_can_resolve(self):
        votes = [
            VoteTuple(outcome_key="a", weight=0.5, is_human_backed=False),
            VoteTuple(outcome_key="a", weight=2.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_three_way_split_leader_below_share_returns_none(self):
        votes = [
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="a", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="b", weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key="c", weight=1.0, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None


class TestFederatedWeighting:
    """
    Federation-readiness stub (see docs/federation-v1.md) - no import path creates federated
    votes yet, so these tests exercise the plumbing directly via VoteTuple/settings rather than
    through a real submit view.
    """

    def test_federated_source_uses_the_configured_weight(self):
        assert _SOURCE_WEIGHTS[VoteSource.FEDERATED] == settings.VOTE_FEDERATED_WEIGHT

    def test_federated_vote_with_human_backed_true_satisfies_the_gate(self):
        votes = [
            VoteTuple(outcome_key="a", weight=settings.VOTE_FEDERATED_WEIGHT * 5, is_human_backed=True),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "a"

    def test_federated_vote_with_human_backed_false_does_not_satisfy_the_gate_alone(self):
        # mirrors test_ai_only_votes_never_resolve_even_with_large_weight - a federated vote
        # explicitly marked not-human-backed can never single-handedly clear consensus, same
        # as an AI vote, regardless of how much weight it carries
        votes = [VoteTuple(outcome_key="a", weight=settings.VOTE_FEDERATED_WEIGHT * 100, is_human_backed=False)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None


class TestMachineWeightRename:
    """
    PRINTING_TAG_AI_WEIGHT -> PRINTING_TAG_MACHINE_WEIGHT (terminology fix - the machine votes
    are OCR/phash/deduction, classical algorithms, no AI/ML involved). Direct coverage that the
    rename didn't change any actual weight: DEDUCTION and OCR still resolve to the same
    configured value they always did, just read from the new setting name.
    """

    def test_deduction_and_ocr_use_the_machine_weight(self):
        assert _SOURCE_WEIGHTS[VoteSource.DEDUCTION] == settings.PRINTING_TAG_MACHINE_WEIGHT
        assert _SOURCE_WEIGHTS[VoteSource.OCR] == settings.PRINTING_TAG_MACHINE_WEIGHT
        assert settings.PRINTING_TAG_MACHINE_WEIGHT == 0.5


class TestFederatedModelFields:
    def test_federated_source_and_peer_round_trip(self, db):
        card = CardFactory()
        vote = CardArtistVoteFactory(card=card, source=VoteSource.FEDERATED, peer="peer-instance-1")
        vote.refresh_from_db()
        assert vote.source == VoteSource.FEDERATED
        assert vote.peer == "peer-instance-1"

    def test_peer_defaults_to_none_for_non_federated_votes(self, db):
        card = CardFactory()
        vote = CardArtistVoteFactory(card=card, source=VoteSource.USER)
        vote.refresh_from_db()
        assert vote.peer is None


class TestFederatedWeightPinned:
    """
    Decision DF (owner-ratified 2026-07-22 vote-weight scenario matrix): VOTE_FEDERATED_WEIGHT
    stays 1.0 - a single federated vote is exactly as heavy as a local USER vote toward
    quorum/share (see `_SOURCE_WEIGHTS`'s own comment for why this is deliberate, not an
    oversight); only the human-backed gate (FEDERATED reads `is_human_backed=False` via
    `is_human_backed_source`, unless a future peer explicitly asserts otherwise) stops a
    federated-only pile from resolving on its own. Explicit pin per the matrix's own DF ask,
    phrased exactly as it specifies: 2 FEDERATED alone never resolves; 1 FEDERATED + 1 USER
    resolves.
    """

    def test_two_federated_votes_alone_never_resolve(self):
        weight = _SOURCE_WEIGHTS[VoteSource.FEDERATED]
        human_backed = is_human_backed_source(VoteSource.FEDERATED)
        votes = [VT("X", weight, human_backed), VT("X", weight, human_backed)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_one_federated_plus_one_user_resolves(self):
        votes = [
            VT("X", _SOURCE_WEIGHTS[VoteSource.FEDERATED], is_human_backed_source(VoteSource.FEDERATED)),
            VT("X", _SOURCE_WEIGHTS[VoteSource.USER], is_human_backed_source(VoteSource.USER)),
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "X"


class TestVoteWeightScenarioMatrixTableA(object):
    """
    Direct encoding of the owner-ratified 2026-07-22 vote-weight scenario matrix's Table A
    (non-implicit baseline) against the path-agnostic resolver core - case IDs match the
    matrix's own numbering so a reader can cross-reference directly. Every cell here except
    A14 asserts the SAME outcome the resolver already produced before this change; A14 asserts
    the RATIFIED outcome (decision D1), which differs from pre-2026-07-22 code (see its own
    comment below).
    """

    @pytest.mark.parametrize(
        "case_id,votes,expected",
        [
            ("A1", [VT("X", 1.0, True)], None),
            ("A2", [VT("X", 1.0, True)] * 2, "X"),
            ("A3", [VT("X", 1.0, True)] * 3, "X"),
            ("A4", [VT("X", 5.0, True)], "X"),
            ("A5", [VT("X", 5.0, True), VT("Y", 1.0, True)], "X"),
            ("A6", [VT("X", 1.0, True), VT("Y", 1.0, True)], None),
            ("A7", [VT("X", 1.0, True)] * 2 + [VT("Y", 1.0, True)], "X"),
            ("A8", [VT("X", 1.0, True)] * 3 + [VT("Y", 1.0, True)] * 2, "X"),  # boundary: share == 0.6
            ("A9", [VT("X", 1.0, True)] * 2 + [VT("Y", 1.0, True)] * 2, None),
            ("A10", [VT("X", 0.5, False)] * 2, None),
            ("A11", [VT("X", 0.5, False)] * 100, None),  # volume never wins
            ("A12", [VT("X", 0.5, False)] * 4 + [VT("X", 1.0, True)], "X"),  # D1: no human dissent -> unaffected
            (
                "A13",
                [VT("X", 1.0, True)] + [VT("Y", 0.5, False)] * 4,
                None,
            ),  # winner Y fails the human-backed gate
            (
                "A14",
                # (1 USER + 4 DEDUCTION)(A) vs 1 USER(B): raw weight A=3.0 > B=1.0, but A and B
                # each carry SOME human-backed weight (a genuine human-vs-human contest) - D1
                # excludes A's machine weight entirely, leaving a 1.0-vs-1.0 human-only tie that
                # fails min_share (0.5 < 0.6). RATIFIED CHANGE: pre-2026-07-22 code resolved "A"
                # here (raw weight decided it); the ratified outcome is None (contested).
                [VT("A", 1.0, True)] + [VT("A", 0.5, False)] * 4 + [VT("B", 1.0, True)],
                None,
            ),
            ("A19", [VT("X", 1.0, False)], None),
            ("A20", [VT("X", 1.0, False)] * 2, None),  # DF: FEDERATED-shaped weight still gated
            ("A21", [VT("X", 1.0, False), VT("X", 1.0, True)], "X"),
        ],
    )
    def test_table_a(self, case_id, votes, expected):
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == expected


class TestVoteWeightScenarioMatrixTableB(object):
    """
    Table B (Stage D deduction-pooling arithmetic) - B1/B2/B5 assert the SAME outcome as
    before; B3/B4 assert the RATIFIED outcome (decisions D3/D4 respectively).
    """

    @pytest.mark.parametrize(
        "case_id,votes,expected",
        [
            ("B1", [VT("A", 1.0, True)] * 2 + [VT("A", 0.5, False)] * 3, "A"),
            ("B2", [VT("A", 1.0, True)] + [VT("A", 0.5, False)] * 3, "A"),  # D2 promotion - must still work
            ("B3", [VT("A", 1.0, True)] + [VT("B", 0.5, False)] * 3, None),
            (
                "B4",
                # RESOLVED(2 USER, A) + 3 DEDUCTION dissent(B): A's own human weight (2.0)
                # already clears min_weight, so D4 excludes machine weight from the share
                # denominator entirely - A's share stays 1.0 rather than being diluted to
                # 2/3.5=0.571 by B's machine pile. RATIFIED CHANGE: pre-2026-07-22 code
                # returned None here (de-resolved); the ratified outcome keeps "A".
                [VT("A", 1.0, True)] * 2 + [VT("B", 0.5, False)] * 3,
                "A",
            ),
            ("B5", [VT("A", 1.0, True)] * 2 + [VT("B", 0.5, False)], "A"),
        ],
    )
    def test_table_b(self, case_id, votes, expected):
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == expected


class TestPrivilegedGatePinned:
    """T1/T1b from the matrix's TEST-SPEC - unaffected by the D1/D4 restructure, pinned here to
    guard against a future regression in the same change that touches the group accumulation."""

    def test_t1_no_privileged_cosign_yields_pending(self):
        votes = [VT("APPLY", 1.0, True), VT("APPLY", 1.0, True)]
        result = resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True)
        assert result is PENDING_PRIVILEGED

    def test_t1b_privileged_cosign_in_winning_group_resolves(self):
        votes = [VT("APPLY", 1.0, True), VT("APPLY", 1.0, True, True)]
        result = resolve_weighted_consensus(votes, min_weight=2, min_share=0.6, require_privileged=True)
        assert result == "APPLY"


class TestImplicitVoteCapForm:
    """
    Table C (owner-ratified low-weight+cap form, decision D5): implicit weight per vote is
    `settings.PRINTING_TAG_IMPLICIT_WEIGHT` (default 0.25), capped in SUM per outcome group at
    `settings.PRINTING_TAG_IMPLICIT_CAP` (default 1.0, strictly below min_weight=2 per decision
    S3). C1/C2 hold under either candidate form the matrix considered; C3/C4 are the cells
    that DIVERGE between forms - this is the cap form's own behaviour, the one that shipped.
    """

    def test_c1_implicit_only_never_resolves(self):
        weight = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        votes = [VT("X", weight, False, is_implicit=True) for _ in range(10)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_c2_implicit_agreeing_with_an_already_resolved_side_changes_nothing(self):
        weight = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        votes = [VT("A", 1.0, True)] * 2 + [VT("A", weight, False, is_implicit=True) for _ in range(5)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_c3_implicit_cannot_break_a_genuine_human_tie(self):
        # 2 USER(A) vs 2 USER(B), +3 IMPLICIT on A: D1's live-human-contest exclusion drops ALL
        # non-human weight (implicit included) once both sides carry human-backed weight, so
        # this is an exact 2.0-vs-2.0 human tie regardless of the implicit pile - never resolves
        # in implicit's favour, unlike the (rejected) share-only candidate form.
        weight = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        votes = (
            [VT("A", 1.0, True)] * 2
            + [VT("B", 1.0, True)] * 2
            + [VT("A", weight, False, is_implicit=True) for _ in range(3)]
        )
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) is None

    def test_c4_implicit_dissent_cannot_veto_a_quorum_valid_human_win(self):
        # 2 USER(A) win, 3 IMPLICIT dissent(B): A's human weight alone (2.0) clears min_weight,
        # so D4 excludes B's implicit weight from the share denominator entirely - unlike the
        # (rejected) share-only candidate form, where implicit's full share-denominator
        # contribution (with zero quorum contribution) could veto an otherwise quorum-valid win.
        weight = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        votes = [VT("A", 1.0, True)] * 2 + [VT("B", weight, False, is_implicit=True) for _ in range(3)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_implicit_weight_is_hard_capped_per_outcome_group(self):
        # enough implicit votes on the losing side that their RAW sum would exceed the cap several
        # times over - the cap must clip the group's contribution regardless of vote count.
        weight = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        cap = settings.PRINTING_TAG_IMPLICIT_CAP
        many_implicit_votes = int(cap / weight) + 10
        votes = [VT("A", 1.0, True)] * 2 + [
            VT("B", weight, False, is_implicit=True) for _ in range(many_implicit_votes)
        ]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_implicit_cap_is_configured_strictly_below_min_votes(self):
        # decision S3's own margin requirement, pinned directly against the configured settings
        # values (not just the resolver's behaviour) so a future settings change that violates
        # it fails loudly here rather than silently reopening the "implicit alone forms quorum"
        # failure mode.
        assert settings.PRINTING_TAG_IMPLICIT_CAP < settings.PRINTING_TAG_MIN_VOTES
