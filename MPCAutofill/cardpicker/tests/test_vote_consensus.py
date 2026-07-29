import inspect
from importlib import import_module

import pytest

from django.conf import settings

from cardpicker.deductive_backfill import generate_run_id
from cardpicker.models import AbstractWeightedVote, VoteSource
from cardpicker.tests.factories import CardArtistVoteFactory, CardFactory
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    DEDUCTIVE_BACKFILL_FAMILY,
    DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID,
    PENDING_PRIVILEGED,
    VoteTuple,
    is_human_backed_source,
    resolve_vote_weight,
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


class TestResolveVoteWeight:
    """
    2026-07-23 owner ruling, as clarified by the owner 2026-07-29: the 28,112 votes the
    2026-07-14 deductive-name-backfill RUN wrote carry weight 0.0 in every consensus
    computation, held out as a measurement control - but the METHOD is not disqualified, so a
    vote cast by that same calculator in future carries the ordinary machine weight.
    `resolve_vote_weight` is the one function that mechanism lives in, so it's the unit tested
    directly here (the printing_consensus-level effect is proven separately in
    test_printing_consensus.py).
    """

    def test_a_vote_from_the_frozen_cohort_is_zero_weight(self):
        # THE cohort row shape: all three conjuncts present, exactly as the 28,112 production
        # rows read after migration 0096 stamped them.
        assert (
            resolve_vote_weight(
                VoteSource.DEDUCTION, DEDUCTIVE_BACKFILL_ANONYMOUS_ID, DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID
            )
            == 0.0
        )

    def test_a_new_vote_by_the_same_method_carries_ordinary_machine_weight(self):
        # The 2026-07-29 clarification, stated as a test: same source, same calculator, same
        # method - a DIFFERENT run, so it is not part of the frozen control and it COUNTS.
        # This assertion was red under the 2026-07-28 family-scoped implementation.
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, DEDUCTIVE_BACKFILL_ANONYMOUS_ID, generate_run_id())
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )
        assert _SOURCE_WEIGHTS[VoteSource.DEDUCTION] == settings.PRINTING_TAG_MACHINE_WEIGHT

    def test_an_unstamped_deductive_backfill_vote_is_not_in_the_cohort(self):
        # run_id=None is what every deductive-backfill row looked like BEFORE migration 0096;
        # after it, only the frozen cohort carries the stamp. A NULL run_id therefore means
        # "not the control", which is the correct reading now the ruling is cohort-scoped.
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, DEDUCTIVE_BACKFILL_ANONYMOUS_ID, None)
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    def test_ordinary_deduction_vote_keeps_its_normal_weight(self):
        # a DEDUCTION-sourced vote from a different calculator entirely is unaffected
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, "some-other-anonymous-id", None)
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    def test_another_calculator_carrying_the_frozen_run_id_is_unaffected(self):
        # defensive: the run stamp alone is never enough - all three conjuncts must hold, so a
        # stray re-stamp onto some other calculator's row cannot pull it into a ratified ruling
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, "scryfall-tagger-v1", DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID)
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    def test_ocr_vote_with_the_backfill_identity_is_unaffected(self):
        # defensive: the override requires source == DEDUCTION specifically - an OCR-sourced
        # vote is never written under this anonymous_id in practice (deductive_backfill.py only
        # ever writes DEDUCTION), but the function itself must not zero it out if it somehow was
        assert (
            resolve_vote_weight(VoteSource.OCR, DEDUCTIVE_BACKFILL_ANONYMOUS_ID, DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID)
            == _SOURCE_WEIGHTS[VoteSource.OCR]
        )

    def test_user_vote_with_the_backfill_identity_is_unaffected(self):
        # same defensive point as above, for the human-backed source
        assert (
            resolve_vote_weight(VoteSource.USER, DEDUCTIVE_BACKFILL_ANONYMOUS_ID, DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID)
            == _SOURCE_WEIGHTS[VoteSource.USER]
        )

    @pytest.mark.parametrize("source", [VoteSource.USER, VoteSource.ADMIN, VoteSource.OCR, VoteSource.FEDERATED])
    def test_every_other_source_matches_the_plain_source_weights_table(self, source):
        assert resolve_vote_weight(source, "anonymous-1", None) == _SOURCE_WEIGHTS[source]


class TestZeroWeightScopeIsTheCohortNotTheMethod:
    """
    2026-07-29 owner clarification. Two earlier revisions of this rule were wrong in opposite
    directions, and this class pins the line between them:

      - the ORIGINAL (2026-07-23) matched the exact string "deductive-backfill-v1", so an
        ordinary redeploy to -v2 would have silently restored all 28,112 control votes to full
        weight - no error, no log line, a ratified ruling reversed by a version string;
      - the REPLACEMENT (2026-07-28) matched the versionless calculator FAMILY, which fixed that
        but zeroed the METHOD - every vote name-matching inference would ever cast, forever. The
        owner ruled on a cohort, not on a method; that implementation claimed more than was
        ratified.

    The scope is now the frozen 2026-07-14 RUN, identified by its stamped `run_id`. Both failure
    modes are closed at once: a version bump cannot un-zero the control (its rows keep the stamp
    whatever the calculator is later called), and a new run cannot be zeroed by it (a new run has
    a new stamp).
    """

    def test_the_family_constant_is_derived_from_the_id_not_written_out_twice(self):
        assert DEDUCTIVE_BACKFILL_FAMILY == "deductive-backfill"
        assert DEDUCTIVE_BACKFILL_ANONYMOUS_ID.startswith(f"{DEDUCTIVE_BACKFILL_FAMILY}-v")

    @pytest.mark.parametrize(
        "anonymous_id", ["deductive-backfill-v1", "deductive-backfill-v2", "deductive-backfill-v10"]
    )
    def test_a_version_bump_cannot_un_zero_the_frozen_cohort(self, anonymous_id):
        # the control rows keep their stamp no matter what the calculator is renamed to later,
        # so the 2026-07-28 fix's actual property is preserved - it just no longer reaches beyond
        # the run. -v2/-v10 do not exist today; that is exactly the point.
        assert resolve_vote_weight(VoteSource.DEDUCTION, anonymous_id, DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID) == 0.0

    @pytest.mark.parametrize(
        "anonymous_id", ["deductive-backfill-v1", "deductive-backfill-v2", "deductive-backfill-v10"]
    )
    def test_no_version_of_the_backfill_calculator_is_zero_weighted_outside_that_run(self, anonymous_id):
        # the correction itself: the METHOD is not disqualified, at any version. Under the
        # 2026-07-28 family-scoped implementation every one of these was 0.0.
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, anonymous_id, generate_run_id())
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    @pytest.mark.parametrize(
        "anonymous_id",
        [
            "local-ocr-v1",
            "local-ocr-v2",
            "stage-d-join-key-v1",
            "stage-d-fallback-v2",
            "local-name-frequency-v1",
            # near-misses: a DIFFERENT family that merely shares a prefix or suffix with the
            # ruled one must not be swept in - the match is family EQUALITY, not containment.
            "deductive-backfill-extra-v1",
            "extra-deductive-backfill-v1",
        ],
    )
    def test_no_other_calculator_family_is_zero_weighted(self, anonymous_id):
        assert (
            resolve_vote_weight(VoteSource.DEDUCTION, anonymous_id, DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID)
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    def test_a_human_uuid_is_never_zero_weighted(self):
        # calculator_family() returns None for a UUID; None must never compare equal to the
        # ruled family, or every human DEDUCTION-labelled vote would silently lose its weight.
        assert (
            resolve_vote_weight(
                VoteSource.DEDUCTION,
                "3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60",
                DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID,
            )
            == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]
        )

    @pytest.mark.parametrize("source", [VoteSource.USER, VoteSource.ADMIN, VoteSource.OCR, VoteSource.FEDERATED])
    def test_the_cohort_match_still_requires_source_to_be_deduction(self, source):
        # the override is (source, family, run_id) TOGETHER - dropping the source conjunct would
        # zero a differently-sourced vote that happened to carry the stamp, which is not the ruling
        assert (
            resolve_vote_weight(source, "deductive-backfill-v2", DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID)
            == _SOURCE_WEIGHTS[source]
        )


class TestZeroWeightCohortScopeIsPinned:
    """
    ANTI-DRIFT. The family-scoped implementation this replaced had one property worth keeping: an
    unrelated change could not silently disable a ratified owner ruling - a rename that broke the
    naming convention failed loudly at import. Re-scoping the rule from the method to one cohort
    must not trade that away for a fragility, so these are the equivalent guards for the new
    mechanism. Every one of them protects against the same failure: a zeroed cohort quietly
    becoming unzeroed, or an unzeroed vote quietly becoming zeroed, with nothing red anywhere.
    """

    def test_the_code_constant_equals_what_the_migration_actually_wrote(self):
        """
        THE LOAD-BEARING ONE. `DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID` is not a setting - it is a
        claim about 28,112 rows in the production database, put there by migration 0096. Editing
        the constant without editing the database would leave the override matching nothing and
        the control cohort silently restored to full machine weight, with no error and no failing
        test anywhere else. Migrations are append-only history, which is what makes comparing
        against one a real check rather than a restatement of the same literal.
        """
        migration = import_module("cardpicker.migrations.0096_freeze_deductive_backfill_zero_weight_cohort")
        assert migration.ZERO_WEIGHT_RUN_ID == DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID
        # and the migration must still be selecting the cohort it claims to select
        assert migration.COHORT_ANONYMOUS_ID == DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        assert migration.EXPECTED_PRODUCTION_ROWS == 28112

    def test_the_frozen_run_id_still_names_the_calculator_it_freezes(self):
        # a run stamp that stopped naming this calculator would be a boundary around nothing -
        # mirrors the import-time assert, pinned here so the assert itself cannot be dropped
        assert DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID.startswith(f"{DEDUCTIVE_BACKFILL_ANONYMOUS_ID}/")

    def test_the_frozen_run_id_fits_the_column_it_is_stored_in(self):
        # a value too long for run_id could not have been stamped at all, i.e. the cohort would
        # be unmarked and the override would match nothing
        max_length = AbstractWeightedVote._meta.get_field("run_id").max_length
        assert len(DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID) <= max_length

    def test_run_id_is_a_required_argument_of_resolve_vote_weight(self):
        """
        `run_id` must never acquire a default. A defaulted `run_id=None` would mean "not in the
        cohort", so a new call site could hand a genuine control row full machine weight purely
        by not knowing the parameter exists - exactly the class of silent scope loss this whole
        change is about. Requiring it forces every call site to answer the question.
        """
        parameter = inspect.signature(resolve_vote_weight).parameters["run_id"]
        assert parameter.default is inspect.Parameter.empty

    def test_a_fresh_backfill_run_can_never_re_mint_the_frozen_stamp(self):
        # the collision guard from the caster's side: if `generate_run_id` could ever produce the
        # frozen value, a future run's votes would silently join the zero-weight control cohort,
        # re-creating the over-broad "this method is disqualified forever" behaviour by accident
        assert all(generate_run_id() != DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID for _ in range(50))


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
        # as a machine vote, regardless of how much weight it carries
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


class TestD4WinnerSelectionRegression:
    """
    2026-07-22 hardening, post-review: D4's original implementation checked its trigger
    condition against the *already-selected* winner (selected by raw `full_weight`), which let
    a large enough machine/implicit dissent pile win the SELECTION outright (its raw weight
    exceeding the human group's), then fail the human-backed gate and return `None` instead of
    correctly resolving the human-backed group. Empirically: RESOLVED(2 USER, A) + N DEDUCTION
    dissent(B) - N=3 correctly stayed "A" (the case the original test suite covered), but N=4
    was ORDER-DEPENDENT (a tie in raw weight, 2.0 vs 2.0, resolved by whichever group's votes
    were iterated/inserted first) and N>=5 deterministically returned `None` (B's raw weight,
    0.5*N, exceeded A's 2.0, so B won the selection and then failed the human-backed gate).

    The fix moves D4's trigger to BEFORE winner selection (`human_quorum_group_exists`, checked
    against every group, not just whichever wins raw-weight selection) - these cases must ALL
    stay "A", independent of N or vote insertion order.
    """

    @pytest.mark.parametrize("dissent_count", [3, 4, 5, 6, 10, 100])
    def test_machine_dissent_never_de_resolves_regardless_of_pile_size(self, dissent_count):
        votes = [VT("A", 1.0, True)] * 2 + [VT("B", 0.5, False)] * dissent_count
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_n4_tie_case_stays_a_when_human_votes_iterate_first(self):
        # the exact N=4 tie shape (raw weight A=2.0 vs B=2.0) - human group inserted first
        votes = [VT("A", 1.0, True)] * 2 + [VT("B", 0.5, False)] * 4
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_n4_tie_case_stays_a_when_machine_votes_iterate_first(self):
        # the same N=4 tie shape, but with the machine dissent votes iterated FIRST - kills the
        # order-dependence the original bug had (dict insertion order no longer matters, since
        # B's non-human weight is excluded from decision_weight entirely once A's human_weight
        # alone clears min_weight, regardless of iteration order).
        votes = [VT("B", 0.5, False)] * 4 + [VT("A", 1.0, True)] * 2
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"

    def test_implicit_dissent_at_the_same_scale_is_equally_safe(self):
        # same regression, IMPLICIT-sourced dissent instead of DEDUCTION - capped well below
        # min_weight per group regardless, but this proves the fix isn't source-specific.
        w = settings.PRINTING_TAG_IMPLICIT_WEIGHT
        votes = [VT("A", 1.0, True)] * 2 + [VT("B", w, False, is_implicit=True) for _ in range(100)]
        assert resolve_weighted_consensus(votes, min_weight=2, min_share=0.6) == "A"


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
