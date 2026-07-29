"""
Illustration consensus (`cardpicker.illustration_consensus`) - the reader `CardIllustrationVote`
had been missing since issue #524 landed the model.

THIS SUITE IS THE ONLY EVIDENCE THIS CODE WORKS, and that is not a figure of speech: production
holds THREE illustration votes at the time of writing, against a projection of ~10,277 machine
rows once PR #565's `stage-d-illustration-v2` calculator runs catalogue-wide. Nothing here can be validated by observing live data, so every claim
the module's docstring makes is pinned as an executable assertion below, and every test in this
file was verified to FAIL against a deliberately mutated implementation before being accepted
(the mutations are enumerated in the PR body). A test that cannot fail is worse than no test
here, because it is indistinguishable from one that can.

Grouping mechanism: most tests use the `md5_groups` fixture (the same in-memory stand-in
`test_md5_group_pooling.py` uses - it replaces the three, and only three, functions in
`printing_consensus` that read `Card.md5_checksum`), so a group can be declared without
hand-crafting matching checksum strings. `TestPropagationIsMd5OnlyNeverPhash` and
`TestGroupOfOneIsAByteForByteNoOp` deliberately do NOT use it, and drive the real, column-backed
path directly - the phash test in particular would be worthless against a fixture that has no
notion of a phash at all.
"""

import uuid

import pytest

from django.conf import settings as django_settings
from django.test import override_settings

from cardpicker import illustration_consensus, printing_consensus
from cardpicker.illustration_consensus import (
    UNKNOWN,
    build_group_illustration_vote_tuples,
    get_contested_illustration_card_ids,
    get_illustration_vote_tally,
    group_illustration_votes,
    resolve_and_persist_illustration,
    resolve_illustration,
)
from cardpicker.models import (
    Card,
    CardIllustrationVote,
    IllustrationVoteStatus,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    CardIllustrationVoteFactory,
    CardPrintingTagFactory,
)

ILLUSTRATION_A = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
ILLUSTRATION_B = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")


@pytest.fixture
def md5_groups(monkeypatch):
    """
    Assigns md5 identity groups to `Card` rows via an in-memory stand-in for the
    `Card.md5_checksum` column - byte-for-byte the fixture `test_md5_group_pooling.py` uses, and
    patched at exactly the same three seams, because `illustration_consensus` imports its group
    primitives (`md5_group_card_ids`/`md5_group_cards`) from `printing_consensus` rather than
    reimplementing them. `md5_groups("checksum", card_a, card_b)` puts those cards in one group;
    cards never passed to it stay checksum-less, i.e. groups of one.
    """
    checksum_by_card_id: dict[int, str] = {}

    def fake_card_md5_checksum(card: Card) -> str | None:
        return checksum_by_card_id.get(card.pk)

    def fake_md5_checksums_for_card_ids(card_ids) -> set[str]:
        return {checksum for card_id, checksum in checksum_by_card_id.items() if card_id in set(card_ids)}

    def fake_card_ids_with_md5_checksums(checksums: set[str]) -> list[int]:
        return [card_id for card_id, checksum in checksum_by_card_id.items() if checksum in checksums]

    monkeypatch.setattr(printing_consensus, "_card_md5_checksum", fake_card_md5_checksum)
    monkeypatch.setattr(printing_consensus, "_md5_checksums_for_card_ids", fake_md5_checksums_for_card_ids)
    monkeypatch.setattr(printing_consensus, "_card_ids_with_md5_checksums", fake_card_ids_with_md5_checksums)

    def assign(checksum: str, *cards: Card) -> None:
        for card in cards:
            checksum_by_card_id[card.pk] = checksum

    return assign


def human_vote(card, illustration_id, anonymous_id):
    return CardIllustrationVoteFactory(
        card=card, illustration_id=illustration_id, is_unknown=False, source=VoteSource.USER, anonymous_id=anonymous_id
    )


def machine_vote(card, illustration_id, anonymous_id):
    return CardIllustrationVoteFactory(
        card=card, illustration_id=illustration_id, is_unknown=False, source=VoteSource.OCR, anonymous_id=anonymous_id
    )


def unknown_vote(card, anonymous_id, source=VoteSource.USER):
    return CardIllustrationVoteFactory(
        card=card, illustration_id=None, is_unknown=True, source=source, anonymous_id=anonymous_id
    )


class TestIsUnknownParticipatesInTheTally:
    """
    The module's stated reading of `is_unknown`: an ORDINARY OUTCOME KEY, not an abstention. All
    three consequences of that reading are asserted, because each fails differently under the
    rejected reading (treat `is_unknown` as an abstention / drop those rows).
    """

    def test_agreeing_unknown_votes_resolve_to_unknown(self, db):
        card = CardFactory()
        unknown_vote(card, "person-1")
        unknown_vote(card, "person-2")
        assert resolve_illustration(card) == UNKNOWN

    def test_unknown_contests_a_named_illustration(self, db):
        # One human names an artwork, one human says there is none. Neither reaches the 2.0
        # quorum, and neither reaches the 0.6 share - a real disagreement, not a resolution.
        # Under an abstention reading the UNKNOWN row would vanish and the uuid would sit
        # uncontested at 100% share (still short of quorum, but the CONTESTED status below is
        # what actually breaks).
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        unknown_vote(card, "person-2")
        assert resolve_illustration(card) is None

        resolve_and_persist_illustration(card)
        card.refresh_from_db()
        assert card.illustration_vote_status == IllustrationVoteStatus.CONTESTED

    def test_unknown_can_outvote_a_named_illustration(self, db):
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        unknown_vote(card, "person-2")
        unknown_vote(card, "person-3")
        unknown_vote(card, "person-4")
        assert resolve_illustration(card) == UNKNOWN

    def test_the_absence_of_a_row_is_the_abstention(self, db):
        # The distinction the module rests on: a card nobody has answered has NO ROWS, which is
        # what UNRESOLVED means. `is_unknown=True` is a different, positive statement, and the
        # two must land on different statuses.
        card = CardFactory()
        assert resolve_illustration(card) is None
        resolve_and_persist_illustration(card)
        card.refresh_from_db()
        assert card.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED
        assert card.inferred_illustration_id is None

    def test_resolved_unknown_stores_no_illustration_id(self, db):
        card = CardFactory()
        unknown_vote(card, "person-1")
        unknown_vote(card, "person-2")
        resolve_and_persist_illustration(card)
        card.refresh_from_db()
        assert card.illustration_vote_status == IllustrationVoteStatus.UNKNOWN
        assert card.inferred_illustration_id is None


class TestHumanBackedGate:
    """
    The ratified invariant, for THIS vote type: machine votes never resolve alone, and never
    override a human. Illustration votes will be ~99.97% machine-authored on arrival, so this is
    the single most consequential property in the module.
    """

    def test_machine_votes_alone_never_resolve_however_many_agents(self, db):
        card = CardFactory()
        for index in range(20):
            machine_vote(card, ILLUSTRATION_A, f"calc-{index}-v1")
        # 20 distinct machine agents = 10.0 weight, five times the 2.0 quorum, 100% share.
        assert resolve_illustration(card) is None

    def test_machine_votes_alone_never_resolve_across_an_md5_group(self, db, md5_groups):
        # Same claim, but with the group multiplier engaged - pooling makes the tally bigger for
        # distinct agents, and the gate still holds.
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b, card_c)
        for index in range(8):
            machine_vote(card_a, ILLUSTRATION_A, f"calc-{index}-v1")
            machine_vote(card_b, ILLUSTRATION_A, f"calc-{index + 100}-v1")
            machine_vote(card_c, ILLUSTRATION_A, f"calc-{index + 200}-v1")
        assert resolve_illustration(card_a) is None

    def test_one_human_vote_promotes_agreeing_machine_weight(self, db):
        # The D2 shape: a lone human plus agreeing machine weight can resolve, exactly as on the
        # printing side. This is the positive control that proves the test above fails for the
        # gate's reason and not because nothing ever resolves.
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        machine_vote(card, ILLUSTRATION_A, "calc-a-v1")
        machine_vote(card, ILLUSTRATION_A, "calc-b-v1")
        assert resolve_illustration(card) == ILLUSTRATION_A

    def test_machine_pile_never_overrides_a_human_quorum(self, db):
        # D4: two humans agreeing on A already clear quorum by themselves, so a machine pile for
        # B - of any size - is excluded from selection entirely rather than out-weighing them.
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        human_vote(card, ILLUSTRATION_A, "person-2")
        for index in range(100):
            machine_vote(card, ILLUSTRATION_B, f"calc-{index}-v1")
        assert resolve_illustration(card) == ILLUSTRATION_A


class TestMd5PoolingCollapsesAgreeingSiblings:
    def test_one_agent_agreeing_across_two_members_counts_once(self, db, md5_groups):
        # THE test for pooling. One person answers two byte-identical images the same way. Two
        # rows, one agent, one event: 1.0 weight, short of the 2.0 quorum. Without pooling this
        # sums to 2.0 and resolves - one human judgement reaching a resolution neither card could
        # reach alone.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_A, "person-1")
        assert resolve_illustration(card_a) is None
        assert resolve_illustration(card_b) is None

    def test_distinct_agents_across_two_members_still_sum(self, db, md5_groups):
        # The other half, and the reason pooling is not just "ignore siblings": two DIFFERENT
        # people, one vote each, on two members of one group, do reach quorum together - a
        # resolution neither card could reach alone, which is the intended multiplier.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_A, "person-2")
        assert resolve_illustration(card_a) == ILLUSTRATION_A
        assert resolve_illustration(card_b) == ILLUSTRATION_A

    def test_pooling_keeps_the_agents_highest_weight(self, db, md5_groups):
        # An admin voting on one member and (under the same identity) on another collapses to one
        # vote at the ADMIN weight, not the lower one - `pool_group_votes` keeps the max.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        CardIllustrationVoteFactory(
            card=card_a, illustration_id=ILLUSTRATION_A, source=VoteSource.OCR, anonymous_id="dual-identity"
        )
        CardIllustrationVoteFactory(
            card=card_b, illustration_id=ILLUSTRATION_A, source=VoteSource.ADMIN, anonymous_id="dual-identity"
        )
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert len(tuples) == 1
        assert tuples[0].weight == django_settings.PRINTING_TAG_ADMIN_WEIGHT
        assert tuples[0].is_human_backed is True


class TestMd5PoolingWithholdsSelfContradictingAgents:
    def test_a_self_contradicting_agent_contributes_to_neither_side(self, db, md5_groups):
        # `person-1` says A about one member and B about a byte-identical one. Withheld
        # ENTIRELY - not counted at its max, not counted for either outcome. So B holds only
        # `person-2`'s single vote (1.0) and nothing resolves. Under a keep-the-max rule B would
        # reach 2.0 and resolve, which is the outcome this asserts against.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_B, "person-1")
        human_vote(card_b, ILLUSTRATION_B, "person-2")
        assert resolve_illustration(card_a) is None

        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert [t.outcome_key for t in tuples] == [ILLUSTRATION_B]

    def test_a_consistent_agent_in_the_same_shape_does_resolve(self, db, md5_groups):
        # Positive control for the test above: identical setup except `person-1` is consistent,
        # so B reaches quorum. Proves the None above comes from the withholding rule and not from
        # the fixture failing to build a resolvable group at all.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_B, "person-1")
        human_vote(card_b, ILLUSTRATION_B, "person-2")
        assert resolve_illustration(card_a) == ILLUSTRATION_B

    def test_withholding_is_order_independent(self, db, md5_groups):
        # Same contradiction, members created in the opposite order, so the `(card_id, pk)`
        # ordering `group_illustration_votes` imposes presents the rows the other way round.
        card_b, card_a = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_B, "person-1")
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert tuples == []

    def test_a_contradiction_between_named_and_unknown_is_also_withheld(self, db, md5_groups):
        # `is_unknown` being a real outcome key means "A here, nothing identifiable there" is a
        # self-contradiction like any other - the same agent said two things about identical
        # bytes.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        unknown_vote(card_b, "person-1")
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert tuples == []


class TestVersionedCalculatorIsOneAgent:
    """
    A calculator's version lives inside its `anonymous_id`, and PR #565 bumps this exact
    calculator from `stage-d-illustration-v1` to `-v2`. A version bump re-votes incrementally, so
    an md5 group straddling the migration holds rows under both strings at once - keying pooling
    on the raw id would make one calculator look like two agents precisely then.
    """

    def test_a_version_bump_does_not_create_a_second_agent(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        machine_vote(card_a, ILLUSTRATION_A, "stage-d-illustration-v1")
        machine_vote(card_b, ILLUSTRATION_A, "stage-d-illustration-v2")
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert len(tuples) == 1
        assert tuples[0].dedupe_key == "stage-d-illustration"
        assert tuples[0].weight == django_settings.PRINTING_TAG_MACHINE_WEIGHT

    def test_a_corrective_re_vote_across_a_version_bump_is_withheld(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        machine_vote(card_a, ILLUSTRATION_A, "stage-d-illustration-v1")
        machine_vote(card_b, ILLUSTRATION_B, "stage-d-illustration-v2")
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert tuples == []

    def test_human_uuids_key_on_themselves(self, db, md5_groups):
        # Human `anonymous_id`s are client-generated UUIDs, which can never match the calculator
        # naming convention, so they fall through to the raw-id branch unchanged.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_uuid = str(uuid.uuid4())
        human_vote(card_a, ILLUSTRATION_A, human_uuid)
        human_vote(card_b, ILLUSTRATION_A, str(uuid.uuid4()))
        tuples = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)
        assert len(tuples) == 2
        assert human_uuid in {t.dedupe_key for t in tuples}


class TestGroupOfOneIsAByteForByteNoOp:
    """
    Ruling 3: a checksum-less or unique-checksum card is a group of one, and every path
    degenerates to the plain per-card tally. Deliberately does NOT use the `md5_groups` fixture -
    these run against the real `Card.md5_checksum` column.
    """

    def test_a_checksum_less_card_is_its_own_group_and_is_not_pooled(self, db):
        card = CardFactory(md5_checksum=None)
        human_vote(card, ILLUSTRATION_A, "person-1")
        votes, is_group = group_illustration_votes(card)
        assert is_group is False
        assert [t.dedupe_key for t in build_group_illustration_vote_tuples(votes, pool=is_group)] == [None]

    def test_a_unique_checksum_card_is_its_own_group(self, db):
        card = CardFactory(md5_checksum="0" * 32)
        CardFactory(md5_checksum="1" * 32)
        assert printing_consensus.md5_group_card_ids(card) == [card.pk]
        assert group_illustration_votes(card)[1] is False

    def test_the_singleton_read_honours_a_prefetch(self, db, django_assert_num_queries):
        # The singleton branch must read `card.illustration_votes.all()`, not an equivalent
        # `filter(card_id__in=[pk])` - only the former is satisfied by a caller's own prefetch,
        # which is what makes batch recomputation one query per batch instead of one per card.
        card = CardFactory(md5_checksum=None)
        human_vote(card, ILLUSTRATION_A, "person-1")
        prefetched = Card.objects.prefetch_related("illustration_votes").get(pk=card.pk)
        with django_assert_num_queries(0):
            votes, is_group = group_illustration_votes(prefetched)
        assert is_group is False
        assert len(votes) == 1

    def test_two_agents_on_a_singleton_resolve_exactly_as_before(self, db):
        card = CardFactory(md5_checksum=None)
        human_vote(card, ILLUSTRATION_A, "person-1")
        human_vote(card, ILLUSTRATION_A, "person-2")
        assert resolve_illustration(card) == ILLUSTRATION_A


class TestPropagationAcrossMd5Siblings:
    """
    The `no-candidate-match` gap (367 of 2,350 considered cards, ~15.6%, in PR #565's
    counterfactual): a member whose decorated name fails candidate resolution casts NO vote at
    all, even though a byte-identical sibling resolved cleanly. Modelled here exactly as it
    occurs - the abstaining member simply has no rows.
    """

    def test_a_voteless_sibling_inherits_the_groups_resolution(self, db, md5_groups):
        resolved, abstainer = CardFactory(), CardFactory()
        md5_groups("shared", resolved, abstainer)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        assert not abstainer.illustration_votes.exists()

        resolve_and_persist_illustration(resolved)

        abstainer.refresh_from_db()
        assert abstainer.inferred_illustration_id == ILLUSTRATION_A
        assert abstainer.illustration_vote_status == IllustrationVoteStatus.RESOLVED

    def test_the_voteless_sibling_resolves_from_its_own_entry_point_too(self, db, md5_groups):
        # Propagation is not an artefact of which member the caller happened to hold: the
        # abstainer's OWN tally is the group's tally.
        resolved, abstainer = CardFactory(), CardFactory()
        md5_groups("shared", resolved, abstainer)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        assert resolve_illustration(abstainer) == ILLUSTRATION_A

    def test_a_non_sibling_does_not_inherit(self, db, md5_groups):
        # The negative control: a card outside the group, with no votes, stays UNRESOLVED.
        resolved, sibling = CardFactory(), CardFactory()
        outsider = CardFactory()
        md5_groups("shared", resolved, sibling)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        resolve_and_persist_illustration(resolved)
        outsider.refresh_from_db()
        assert outsider.inferred_illustration_id is None
        assert outsider.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED

    def test_machine_only_evidence_does_not_propagate(self, db, md5_groups):
        # The honest limit, stated as a test: propagation requires the group to RESOLVE, and the
        # human-backed gate means a machine-only group never does. Nothing is written to the
        # abstainer.
        #
        # SIX distinct machine agents, deliberately: 3.0 weight at 100% share, comfortably past
        # the 2.0 quorum, so the ONLY thing standing between this group and a resolution is the
        # human-backed gate. With two agents (1.0) this test would pass for the wrong reason -
        # falling short of quorum - and would stay green even with the gate deleted.
        resolved, abstainer = CardFactory(), CardFactory()
        md5_groups("shared", resolved, abstainer)
        for index in range(6):
            machine_vote(resolved, ILLUSTRATION_A, f"stage-d-calc-{index}-v1")
        resolve_and_persist_illustration(resolved)
        abstainer.refresh_from_db()
        assert abstainer.inferred_illustration_id is None
        assert abstainer.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED

    def test_a_de_resolution_propagates_too(self, db, md5_groups):
        # Propagation is not write-once: when new votes contest a previously resolved group,
        # every member is walked back together, so the group cannot disagree with itself.
        resolved, abstainer = CardFactory(), CardFactory()
        md5_groups("shared", resolved, abstainer)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        resolve_and_persist_illustration(resolved)
        abstainer.refresh_from_db()
        assert abstainer.illustration_vote_status == IllustrationVoteStatus.RESOLVED

        human_vote(abstainer, ILLUSTRATION_B, "person-3")
        human_vote(abstainer, ILLUSTRATION_B, "person-4")
        resolve_and_persist_illustration(resolved)
        abstainer.refresh_from_db()
        resolved.refresh_from_db()
        assert abstainer.inferred_illustration_id is None
        assert abstainer.illustration_vote_status == IllustrationVoteStatus.CONTESTED
        assert resolved.illustration_vote_status == IllustrationVoteStatus.CONTESTED


class TestPropagationIsMd5OnlyNeverPhash:
    """
    Byte identity is strictly stronger than perceptual proximity, and propagation is only sound on
    the former. Runs against the REAL `Card.md5_checksum`/`Card.content_phash` columns, with no
    `md5_groups` fixture, because the whole point is that a phash - which the fixture cannot even
    express - must not create a group.
    """

    def test_an_identical_phash_does_not_propagate(self, db):
        resolved = CardFactory(md5_checksum="a" * 32, content_phash=1234567890123)
        lookalike = CardFactory(md5_checksum="b" * 32, content_phash=1234567890123)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")

        resolve_and_persist_illustration(resolved)

        resolved.refresh_from_db()
        lookalike.refresh_from_db()
        assert resolved.illustration_vote_status == IllustrationVoteStatus.RESOLVED
        assert lookalike.inferred_illustration_id is None
        assert lookalike.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED

    def test_an_identical_phash_with_no_md5_does_not_propagate(self, db):
        resolved = CardFactory(md5_checksum="a" * 32, content_phash=1234567890123)
        lookalike = CardFactory(md5_checksum=None, content_phash=1234567890123)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        resolve_and_persist_illustration(resolved)
        lookalike.refresh_from_db()
        assert lookalike.inferred_illustration_id is None

    def test_the_same_pair_with_a_matching_md5_does_propagate(self, db):
        # POSITIVE CONTROL, and the reason the two tests above are not vacuous: change ONLY the
        # md5 - same phashes, same votes, same everything else - and propagation happens. Without
        # this, both tests above would still pass against an implementation that propagates to
        # nothing at all.
        resolved = CardFactory(md5_checksum="a" * 32, content_phash=1234567890123)
        sibling = CardFactory(md5_checksum="a" * 32, content_phash=1234567890123)
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")

        resolve_and_persist_illustration(resolved)

        sibling.refresh_from_db()
        assert sibling.inferred_illustration_id == ILLUSTRATION_A
        assert sibling.illustration_vote_status == IllustrationVoteStatus.RESOLVED

    def test_an_empty_string_md5_is_not_an_identity(self, db):
        # "" is not a checksum; grouping every unstamped card into one giant group would be the
        # catastrophic misreading of this degenerate case.
        resolved = CardFactory(md5_checksum="")
        other = CardFactory(md5_checksum="")
        assert printing_consensus.md5_group_card_ids(resolved) == [resolved.pk]
        human_vote(resolved, ILLUSTRATION_A, "person-1")
        human_vote(resolved, ILLUSTRATION_A, "person-2")
        resolve_and_persist_illustration(resolved)
        other.refresh_from_db()
        assert other.inferred_illustration_id is None


class TestPropagatedVoteRowsWouldBeWeightNeutral:
    """
    The module rejects an explicit propagation step that WRITES a copied `CardIllustrationVote`
    row onto the abstaining sibling. The first and heaviest reason given is that such a row would
    contribute EXACTLY ZERO weight, because it carries the same agent identity as the row it was
    copied from and pools with it. That is a falsifiable claim about this code, so it is tested
    rather than merely argued.
    """

    def test_a_copied_sibling_row_changes_no_tally(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        machine_vote(card_a, ILLUSTRATION_A, "stage-d-illustration-v2")
        before = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)

        # exactly what a propagation step would write: the same agent's same claim, on the
        # byte-identical sibling.
        machine_vote(card_b, ILLUSTRATION_A, "stage-d-illustration-v2")
        after = build_group_illustration_vote_tuples(group_illustration_votes(card_a)[0], pool=True)

        assert sorted((t.outcome_key, t.weight, t.dedupe_key) for t in before) == sorted(
            (t.outcome_key, t.weight, t.dedupe_key) for t in after
        )
        assert resolve_illustration(card_a) == resolve_illustration(card_b)


class TestFullGroupCompletenessGuard:
    def test_a_partial_group_raises_rather_than_resolving_differently(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        with pytest.raises(ValueError, match="full md5 identity group"):
            resolve_illustration(card_a, group_card_ids=[card_a.pk])

    def test_a_duplicated_member_raises(self, db, md5_groups):
        card_a = CardFactory()
        md5_groups("solo", card_a)
        with pytest.raises(ValueError, match="full md5 identity group"):
            resolve_illustration(card_a, group_card_ids=[card_a.pk, card_a.pk])

    def test_persist_rejects_a_substituted_card_instance(self, db):
        card = CardFactory(md5_checksum=None)
        copy = Card.objects.get(pk=card.pk)
        with pytest.raises(ValueError, match="unreplaced"):
            resolve_and_persist_illustration(card, members=[copy])


class TestThresholdSettings:
    def test_defaults_match_the_printing_thresholds(self, db):
        # The settings exist so the illustration bar can move independently later; they must not
        # move anything today.
        assert django_settings.ILLUSTRATION_MIN_VOTES == django_settings.PRINTING_TAG_MIN_VOTES
        assert django_settings.ILLUSTRATION_MIN_SHARE == django_settings.PRINTING_TAG_MIN_SHARE

    def test_the_quorum_setting_is_read_at_call_time(self, db):
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        assert resolve_illustration(card) is None
        with override_settings(ILLUSTRATION_MIN_VOTES=1.0):
            assert resolve_illustration(card) == ILLUSTRATION_A

    def test_lowering_the_illustration_quorum_does_not_lower_the_printing_one(self, db):
        # Stated BEHAVIOURALLY, not as a comparison of two settings values (which could not
        # fail): under an illustration-only override, one human vote resolves the illustration
        # and the same voter's single PRINTING vote still does not resolve the printing. The
        # regression this catches is a plausible one - `resolve_printing` reading the new
        # threshold helper because it is the more recently written one.
        card = CardFactory(md5_checksum=None)
        printing = CanonicalCardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="person-1")
        with override_settings(ILLUSTRATION_MIN_VOTES=1.0):
            assert resolve_illustration(card) == ILLUSTRATION_A
            assert printing_consensus.resolve_printing(card) is None


class TestDisplayHelpers:
    def test_the_tally_is_card_scoped_not_group_scoped(self, db, md5_groups):
        # The group is the unit of RESOLUTION; the card is the unit of DISPLAY. A voter must not
        # be shown counts they cannot reconcile with the card in front of them.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_A, "person-2")
        tally = get_illustration_vote_tally(card_a)
        assert [(entry["illustration_id"], entry["count"]) for entry in tally] == [(ILLUSTRATION_A, 1)]

    def test_the_tally_counts_unknown_as_its_own_outcome(self, db):
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        unknown_vote(card, "person-2")
        unknown_vote(card, "person-3")
        tally = get_illustration_vote_tally(card)
        assert tally[0]["is_unknown"] is True
        assert tally[0]["count"] == 2

    def test_contested_card_ids_flags_two_illustrations(self, db):
        contested = CardFactory()
        agreed = CardFactory()
        human_vote(contested, ILLUSTRATION_A, "person-1")
        human_vote(contested, ILLUSTRATION_B, "person-2")
        human_vote(agreed, ILLUSTRATION_A, "person-3")
        assert get_contested_illustration_card_ids() == [contested.pk]

    def test_contested_card_ids_flags_a_named_illustration_against_unknown(self, db):
        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        unknown_vote(card, "person-2")
        assert get_contested_illustration_card_ids() == [card.pk]


class TestGroupScopedContestedStatus:
    def test_two_internally_consistent_members_disagreeing_reads_as_contested(self, db, md5_groups):
        # Neither card is contested by the per-card SQL proxy - each holds one vote - but the
        # GROUP is, which is exactly the case md5 grouping creates and the reason the status is
        # computed from the group's rows rather than from `get_contested_illustration_card_ids`.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        human_vote(card_b, ILLUSTRATION_B, "person-2")
        assert get_contested_illustration_card_ids() == []

        resolve_and_persist_illustration(card_a)
        card_a.refresh_from_db()
        card_b.refresh_from_db()
        assert card_a.illustration_vote_status == IllustrationVoteStatus.CONTESTED
        assert card_b.illustration_vote_status == IllustrationVoteStatus.CONTESTED

    def test_a_single_vote_is_unresolved_not_contested(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("shared", card_a, card_b)
        human_vote(card_a, ILLUSTRATION_A, "person-1")
        resolve_and_persist_illustration(card_a)
        card_b.refresh_from_db()
        assert card_b.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED


class TestReferenceDataIndependence:
    """
    Owner ruling 2026-07-29: `CanonicalCard`/`CanonicalPrintingMetadata` are imported Scryfall
    reference data - informative, possibly stale, with no import timestamp anywhere in the
    database - and code that rests on them must make the dependency explicit. This module's answer
    is that it rests on them NOWHERE: it tallies uuids off vote rows and stores the winner
    verbatim. That claim is asserted here rather than only asserted in prose.
    """

    def test_consensus_resolves_with_no_canonical_rows_in_existence(self, db):
        from cardpicker.models import CanonicalCard, CanonicalPrintingMetadata

        card = CardFactory()
        human_vote(card, ILLUSTRATION_A, "person-1")
        human_vote(card, ILLUSTRATION_A, "person-2")
        assert not CanonicalCard.objects.exists()
        assert not CanonicalPrintingMetadata.objects.exists()

        resolve_and_persist_illustration(card)
        card.refresh_from_db()
        assert card.inferred_illustration_id == ILLUSTRATION_A
        assert card.illustration_vote_status == IllustrationVoteStatus.RESOLVED

    def test_an_illustration_id_no_reference_row_carries_still_resolves(self, db):
        # A uuid that no `CanonicalPrintingMetadata` row references - the shape a snapshot
        # predating, or postdating, the vote would produce. Consensus is unaffected; turning the
        # uuid into printings is a live join every consumer performs itself.
        orphan = uuid.uuid4()
        card = CardFactory()
        human_vote(card, orphan, "person-1")
        human_vote(card, orphan, "person-2")
        assert resolve_illustration(card) == orphan


class TestHumanWritePathRecomputesConsensus:
    def test_two_human_votes_through_the_write_path_resolve_and_persist(self, db):
        from cardpicker.illustration_vote import cast_illustration_vote

        card = CardFactory(md5_checksum=None)
        for voter in ("person-1", "person-2"):
            cast_illustration_vote(
                card=card,
                anonymous_id=voter,
                illustration_id=ILLUSTRATION_A,
                is_unknown=False,
                user=None,
                vote_surface="test",
            )
        card.refresh_from_db()
        assert CardIllustrationVote.objects.filter(card=card).count() == 2
        assert card.inferred_illustration_id == ILLUSTRATION_A
        assert card.illustration_vote_status == IllustrationVoteStatus.RESOLVED

    def test_an_unknown_answer_through_the_write_path_persists_unknown(self, db):
        from cardpicker.illustration_vote import cast_illustration_vote

        card = CardFactory(md5_checksum=None)
        for voter in ("person-1", "person-2"):
            cast_illustration_vote(
                card=card,
                anonymous_id=voter,
                illustration_id=None,
                is_unknown=True,
                user=None,
                vote_surface="test",
            )
        card.refresh_from_db()
        assert card.illustration_vote_status == IllustrationVoteStatus.UNKNOWN
        assert card.inferred_illustration_id is None


def test_module_never_reads_the_perceptual_hash(db):
    """
    Structural backstop for `TestPropagationIsMd5OnlyNeverPhash`: the behavioural tests prove
    today's code does not group on a phash; this proves nobody can add such a read without
    tripping a test. Deliberately paired with those behavioural tests rather than standing alone -
    a source-text assertion on its own would be exactly the kind of test this repo has shipped
    that passes while asserting nothing.
    """
    import ast
    import inspect
    import textwrap

    def executable_source(function) -> str:
        """`function`'s body with its docstring removed - the docstrings deliberately DISCUSS the
        perceptual hash at length (arguing why it must not be used), so a naive source scan would
        be tripped by the very prose that makes the rule clear."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        node = tree.body[0]
        assert isinstance(node, ast.FunctionDef)
        if ast.get_docstring(node) is not None:
            node.body = node.body[1:]
        return ast.unparse(node)

    # The whole membership chain, end to end: this module's two group-consuming functions, and
    # the two `printing_consensus` primitives they delegate membership to. If any of the four
    # ever learns to read a perceptual hash, this fails.
    for function in (
        illustration_consensus.group_illustration_votes,
        illustration_consensus.resolve_and_persist_illustration,
        printing_consensus.md5_group_card_ids,
        printing_consensus.md5_group_cards,
    ):
        assert "phash" not in executable_source(function), function.__name__

    # and the detector is not vacuous - a function that DOES read the phash trips it, and one
    # that only mentions it in a docstring does not.
    def reads_the_phash(card):
        """No mention here."""
        return card.content_phash

    def only_mentions_it_in_prose(card):
        """Discusses content_phash without reading it."""
        return card.md5_checksum

    assert "phash" in executable_source(reads_the_phash)
    assert "phash" not in executable_source(only_mentions_it_in_prose)
