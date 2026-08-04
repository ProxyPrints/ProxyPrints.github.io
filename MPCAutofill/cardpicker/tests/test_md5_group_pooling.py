"""
Group-level vote pooling for md5 identity groups (issue #473 PR-3, owner-ratified 2026-07-25).

Two halves, and the split matters:

1. `TestPoolGroupVotes` exercises `vote_consensus.pool_group_votes` as the pure function it is -
   no database, no models, no md5 anywhere. This is where the two properties docs/theory.md §4's
   group-pooling item actually claims are pinned down: one agent counts once (agreeing votes
   collapse), and an agent that contradicts itself counts for nothing (order-independently).
2. Everything else exercises the real resolver/persistence/feed/recompute paths against real
   `Card`/`CardPrintingTag` rows, with group MEMBERSHIP supplied by the `md5_groups` fixture
   below rather than by a populated `Card.md5_checksum` column - originally because that column
   hadn't arrived yet (issue #473's PR-1, `md5-checksum-substrate`, which this module was first
   written cut BEFORE). PR-1 has SINCE merged to `master` and reached this branch via the
   2026-07-25 master merge - `Card.md5_checksum` is a real column here now - but the fixture is
   kept as the grouping mechanism regardless, since it exercises the exact same real grouping/
   pooling/propagation/feed code paths a column-backed group does (the fixture replaces the three
   - and only three - functions in `printing_consensus` that touch the column:
   `_card_md5_checksum`, `_md5_checksums_for_card_ids`, `_card_ids_with_md5_checksums`) without
   needing every test to hand-craft matching checksum strings. `TestSingletonIsANoOp` and
   `TestGroupExpansionQueryCostWithoutTheChecksumColumn` below deliberately do NOT use the
   fixture, to pin real, column-backed behavior directly.

The SINGLETON NO-OP proof (ruling 3) is deliberately NOT concentrated in one test here: it is
the entire pre-existing consensus/printing/tag/question-feed/recompute suite, which passes
UNMODIFIED, because a card with no checksum is a group of one and every path below degenerates
to its pre-#473 behavior. `TestSingletonIsANoOp` adds the direct, mechanical statements of that
degeneration (group of one, no pooling keys, no extra queries, prefetch still honoured) that the
existing suite asserts only indirectly.
"""

from unittest.mock import patch

import pytest

from django.conf import settings as django_settings

from cardpicker import printing_consensus
from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    run_join_key_calculator,
)
from cardpicker.management.commands.consensus_recompute import run_consensus_recompute
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardPrintingTag,
    PrintingTagStatus,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
    calculator_family,
)
from cardpicker.printing_consensus import (
    agent_dedupe_key,
    build_group_printing_vote_tuples,
    group_printing_votes,
    md5_group_card_ids,
    md5_group_cards,
    md5_group_expanded_card_ids,
    md5_group_key,
    resolve_and_persist_printing,
    resolve_printing,
)
from cardpicker.question_feed import (
    _not_official_art_card_ids,
    _tier_1_confirm_suggestion,
    _tier_2_contested,
    _voter_answered_artist_card_ids,
    _voter_answered_printing_card_ids,
    _voter_answered_tag_card_ids_by_tag,
    get_next_question_feed_item,
    is_likely_resolve_printing,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    ImageEvidenceFactory,
    TagFactory,
)
from cardpicker.vote_consensus import (
    VoteTuple,
    pool_group_votes,
    resolve_vote_weight,
    resolve_weighted_consensus,
)


@pytest.fixture
def md5_groups(monkeypatch):
    """
    Assigns md5 identity groups to `Card` rows via an in-memory stand-in rather than a populated
    `Card.md5_checksum` column (see this module's own docstring, point 2, for why the fixture
    approach is kept even now that the column is real on this branch). Returns a callable:
    `md5_groups("checksum", card_a, card_b)` puts those cards in one group. Cards never passed to
    it stay checksum-less - i.e. groups of one, the ruling-3 degenerate case - exactly as most of
    the catalogue still is pending the backfill (`backfill_md5_checksums`) fully enrolling it.
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


def machine_vote(card, printing, anonymous_id):
    return CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=anonymous_id)


def human_vote(card, printing, anonymous_id):
    return CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id=anonymous_id)


class TestPoolGroupVotes:
    """The pure pooling primitive - no DB, no md5, no models."""

    def test_unkeyed_votes_pass_through_unchanged(self):
        votes = [
            VoteTuple(outcome_key=1, weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key=1, weight=1.0, is_human_backed=True),
            VoteTuple(outcome_key=2, weight=0.5, is_human_backed=False),
        ]
        assert pool_group_votes(votes) == votes

    def test_same_dedupe_key_collapses_to_one_event(self):
        votes = [
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="ocr-bot"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="ocr-bot"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="ocr-bot"),
        ]
        pooled = pool_group_votes(votes)
        assert len(pooled) == 1
        assert pooled[0].weight == 0.5

    def test_distinct_dedupe_keys_are_independent_events(self):
        votes = [
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="ocr-bot"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="fallback-bot"),
        ]
        assert len(pool_group_votes(votes)) == 2

    def test_collapse_keeps_the_maximum_weight(self):
        votes = [
            VoteTuple(outcome_key=1, weight=0.25, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key=1, weight=1.0, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="bot"),
        ]
        pooled = pool_group_votes(votes)
        assert [vote.weight for vote in pooled] == [1.0]

    def test_an_agent_that_contradicts_itself_is_withheld_entirely(self):
        # NOT "keep the heavier side", and specifically NOT "keep whichever came first" - an
        # agent that says two different things about byte-identical bytes is evidence for
        # neither (see `pool_group_votes`' rule 2, and the order-independence test below for the
        # failure the earlier keep-the-max form actually had).
        votes = [
            VoteTuple(outcome_key="first", weight=0.5, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key="second", weight=1.0, is_human_backed=False, dedupe_key="bot"),
        ]
        assert pool_group_votes(votes) == []

    def test_withholding_is_scoped_to_the_contradicting_agent(self):
        votes = [
            VoteTuple(outcome_key="x", weight=1.0, is_human_backed=True, dedupe_key="human-1"),
            VoteTuple(outcome_key="x", weight=0.5, is_human_backed=False, dedupe_key="bot-a"),
            VoteTuple(outcome_key="x", weight=0.5, is_human_backed=False, dedupe_key="bot-b"),
            VoteTuple(outcome_key="y", weight=0.5, is_human_backed=False, dedupe_key="bot-b"),
        ]
        pooled = pool_group_votes(votes)
        assert [(vote.outcome_key, vote.dedupe_key) for vote in pooled] == [("x", "human-1"), ("x", "bot-a")]

    def test_pooling_is_order_independent(self):
        # the concrete defect the 2026-07-25 gate found in the keep-the-max form: with equal
        # weights it resolved a self-contradiction by INPUT order, which in the real caller is
        # `card_id` order - so which sibling happened to have the lower pk decided which outcome
        # a contradicting agent appeared to support, manufacturing correlated agreement.
        votes = [
            VoteTuple(outcome_key="x", weight=1.0, is_human_backed=True, dedupe_key="human-1"),
            VoteTuple(outcome_key="x", weight=0.5, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key="y", weight=0.5, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key="x", weight=0.5, is_human_backed=False, dedupe_key="other-bot"),
        ]
        forward = pool_group_votes(votes)
        reversed_order = pool_group_votes(list(reversed(votes)))
        assert sorted(forward) == sorted(reversed_order)

    def test_pooling_never_increases_total_weight(self):
        votes = [
            VoteTuple(outcome_key=1, weight=1.0, is_human_backed=True, dedupe_key="human-1"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="bot"),
            VoteTuple(outcome_key=1, weight=0.5, is_human_backed=False, dedupe_key="bot"),
        ]
        pooled = pool_group_votes(votes)
        assert sum(vote.weight for vote in pooled) <= sum(vote.weight for vote in votes)
        # and specifically: the one human agent survives intact, the one machine agent's two
        # agreeing observations collapse to one
        assert len(pooled) == 2


class TestSingletonIsANoOp:
    """
    Ruling 3's degenerate case, stated mechanically. The substantive proof is the pre-existing
    suite passing unmodified; these pin the specific properties that make that true.
    """

    def test_checksumless_card_is_a_group_of_one(self, db):
        card = CardFactory()
        assert md5_group_card_ids(card) == [card.pk]
        assert md5_group_cards(card) == [card]
        assert md5_group_key(card) == ("card", card.pk)

    def test_unique_checksum_card_is_a_group_of_one(self, db, md5_groups):
        card = CardFactory()
        other = CardFactory()
        md5_groups("checksum-a", card)
        md5_groups("checksum-b", other)
        assert md5_group_card_ids(card) == [card.pk]
        assert md5_group_cards(card) == [card]

    def test_singleton_votes_carry_no_pooling_key(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        human_vote(card, printing, "human-1")
        votes, is_group = group_printing_votes(card)
        assert is_group is False
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert [vote.dedupe_key for vote in vote_tuples] == [None]

    def test_singleton_read_honours_a_callers_prefetch_and_adds_no_query(self, db, django_assert_num_queries):
        card = CardFactory()
        printing = CanonicalCardFactory()
        human_vote(card, printing, "human-1")
        prefetched = list(Card.objects.filter(pk=card.pk).prefetch_related("printing_tags"))[0]

        with django_assert_num_queries(0):
            votes, is_group = group_printing_votes(prefetched)

        assert is_group is False
        assert len(votes) == 1

    def test_singleton_expansion_returns_its_input(self, db):
        card = CardFactory()
        assert md5_group_expanded_card_ids([card.pk]) == {card.pk}
        assert md5_group_expanded_card_ids([]) == set()


class TestGroupTally:
    def test_one_machine_agent_across_three_siblings_is_one_event(self, db, md5_groups):
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing = CanonicalCardFactory()
        for card in (card_a, card_b, card_c):
            machine_vote(card, printing, "ocr-bot")

        votes, is_group = group_printing_votes(card_a)
        assert is_group is True
        assert len(votes) == 3  # all three rows are read...

        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert len(vote_tuples) == 1  # ...and pool to ONE event
        assert vote_tuples[0].weight == 0.5

    def test_machine_dedupe_denies_a_lone_human_a_fabricated_quorum(self, db, md5_groups):
        # the concrete reason ruling 1 exists: three byte-identical siblings each carrying the
        # same agent's OCR verdict must not add up to 1.5 machine weight behind one human vote.
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing = CanonicalCardFactory()
        for card in (card_a, card_b, card_c):
            machine_vote(card, printing, "ocr-bot")
        human_vote(card_a, printing, "human-1")

        # 1.0 (human) + 0.5 (one pooled machine event) = 1.5, short of PRINTING_TAG_MIN_VOTES=2
        assert resolve_printing(card_a) is None

    def test_distinct_machine_agents_still_count_separately(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "ocr-bot")
        machine_vote(card_b, printing, "fallback-bot")

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert len(vote_tuples) == 2

    def test_human_votes_sum_across_members(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        # two DISTINCT people, 1.0 each, pooled to 2.0 = PRINTING_TAG_MIN_VOTES. This is the
        # intended multiplier: one target, two independent human confirmations of it.
        assert resolve_printing(card_a) == printing
        assert resolve_printing(card_b) == printing

    def test_one_human_answering_two_siblings_is_one_vote(self, db, md5_groups):
        # 2026-07-25 gate on PR #482, condition 1 (its scenario A, reproduced): the SAME
        # `anonymous_id` voting once on each of two byte-identical members must not add up to a
        # 2.0 quorum. One person answering the same image twice under two of its identifiers is
        # one answer - neither card could resolve alone, and the group must not either.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-1")

        votes, is_group = group_printing_votes(card_a)
        assert len(votes) == 2  # both rows are read...
        assert len(build_group_printing_vote_tuples(votes, pool=is_group)) == 1  # ...one agent

        assert resolve_printing(card_a) is None
        assert resolve_printing(card_b) is None

    def test_a_third_distinct_human_still_resolves_that_group(self, db, md5_groups):
        # the complement of the test above: deduping one repeat voter must not make a group
        # unresolvable, only un-inflatable. A second real person tips it exactly as it should.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-1")
        assert resolve_printing(card_a) is None

        human_vote(card_b, printing, "human-2")
        assert resolve_printing(card_a) == printing

    def test_a_self_contradicting_machine_agent_contributes_nothing(self, db, md5_groups):
        # 2026-07-25 gate on PR #482, condition 2 (its scenario B at k=2): one human vote for X
        # plus two OCR agents that each say X on one sibling and Y on the other. Each such agent
        # has contradicted itself about identical bytes, so it withholds entirely - leaving 1.0
        # of human weight, short of quorum. Under the earlier keep-the-max collapse this
        # resolved to X purely because the X rows had the lower card_id.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_a, printing_x, "human-1")
        for index in range(2):
            machine_vote(card_a, printing_x, f"bot-{index}")
            machine_vote(card_b, printing_y, f"bot-{index}")

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert [vote.weight for vote in vote_tuples] == [1.0]  # the human, and nothing else
        assert resolve_printing(card_a) is None

    def test_self_contradiction_handling_is_independent_of_card_id_order(self, db, md5_groups):
        # same shape as above, built twice with the outcomes swapped between the low-pk and
        # high-pk sibling. The tally - and therefore the outcome - must be identical, since
        # nothing about which sibling was created first says anything about the printing.
        def build(x_first: bool) -> list[float]:
            card_low, card_high = CardFactory(), CardFactory()
            md5_groups(f"same-bytes-{x_first}", card_low, card_high)
            printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
            human_vote(card_low, printing_x, f"human-{x_first}")
            machine_vote(card_low if x_first else card_high, printing_x, f"bot-{x_first}")
            machine_vote(card_high if x_first else card_low, printing_y, f"bot-{x_first}")
            votes, is_group = group_printing_votes(card_low)
            assert resolve_printing(card_low) is None
            return sorted(vote.weight for vote in build_group_printing_vote_tuples(votes, pool=is_group))

        assert build(True) == build(False) == [1.0]

    def test_a_self_contradicting_human_alone_does_not_resolve_the_group(self, db, md5_groups):
        # the human-vote analogue of test_a_self_contradicting_machine_agent_contributes_nothing
        # above: ONE human (source=user) voting X on one sibling and Y on the other has
        # contradicted itself about byte-identical bytes, same as a machine agent would, and is
        # withheld entirely - the group must not resolve on that agent's votes alone.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_a, printing_x, "human-1")
        human_vote(card_b, printing_y, "human-1")

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert vote_tuples == []
        assert resolve_printing(card_a) is None
        assert resolve_printing(card_b) is None

    def test_self_contradicting_human_withheld_not_latest_wins(self, db, md5_groups):
        # issue #483: pins WHICH of the candidate contradiction policies this pipeline actually
        # implements. h1 votes X on sibling1, then Y on sibling2 - a self-contradiction, withheld
        # entirely per `pool_group_votes` rule 2. h2 votes Y once. A "latest wins" policy would
        # count h1's most recent vote (Y) alongside h2's Y for a 2.0 quorum on Y and wrongly
        # resolve the group; withhold-entirely leaves only h2's 1.0, short of
        # PRINTING_TAG_MIN_VOTES=2, so the group stays unresolved.
        card_1, card_2 = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_1, card_2)
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_1, printing_x, "h1")
        human_vote(card_2, printing_y, "h1")
        human_vote(card_1, printing_y, "h2")

        votes, is_group = group_printing_votes(card_1)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert [(vote.outcome_key, vote.dedupe_key) for vote in vote_tuples] == [(printing_y.pk, "h2")]
        assert resolve_printing(card_1) is None
        assert resolve_printing(card_2) is None

    def test_a_group_never_resolves_on_machine_weight_alone(self, db, md5_groups):
        # four siblings, four DIFFERENT agents (nothing dedupes), 2.0 of machine weight - which
        # would clear the quorum threshold on arithmetic alone. The human-backed gate holds at
        # group level exactly as it does per card.
        cards = [CardFactory() for _ in range(4)]
        md5_groups("same-bytes", *cards)
        printing = CanonicalCardFactory()
        for index, card in enumerate(cards):
            machine_vote(card, printing, f"bot-{index}")

        votes, is_group = group_printing_votes(cards[0])
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert sum(vote.weight for vote in vote_tuples) == 2.0
        assert all(resolve_printing(card) is None for card in cards)

    def test_human_dissent_across_members_is_one_group_level_contest(self, db, md5_groups):
        # each card, alone, resolves to its own printing; as ONE identification target they are a
        # 2-vs-2 contest (share 0.5, below PRINTING_TAG_MIN_SHARE) and neither wins. Ruling 2:
        # nothing new invented - this is the standard matrix, run on the pooled tally.
        card_a, card_b = CardFactory(), CardFactory()
        printing_a, printing_b = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_a, printing_a, "human-1")
        human_vote(card_a, printing_a, "human-2")
        human_vote(card_b, printing_b, "human-3")
        human_vote(card_b, printing_b, "human-4")

        assert resolve_printing(card_a) == printing_a
        assert resolve_printing(card_b) == printing_b

        md5_groups("same-bytes", card_a, card_b)

        assert resolve_printing(card_a) is None
        assert resolve_printing(card_b) is None

    def test_machine_dissent_cannot_tip_a_group_level_human_contest(self, db, md5_groups):
        # the matrix's no-machine-tipping mechanism, unchanged, on a pooled tally: a machine pile
        # behind one side of a live human-vs-human group contest is excluded from the math.
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing_a, printing_b = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_a, printing_a, "human-1")
        human_vote(card_a, printing_a, "human-2")
        human_vote(card_b, printing_b, "human-3")
        human_vote(card_b, printing_b, "human-4")
        for index in range(6):
            machine_vote(card_a, printing_a, f"bot-{index}")

        assert resolve_printing(card_a) is None


class TestGroupPropagation:
    def test_resolution_is_written_to_every_member(self, db, md5_groups):
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_a, printing, "human-2")

        with patch("cardpicker.documents.reindex_card_safely"):
            result = resolve_and_persist_printing(card_a)

        assert result == printing
        for card in (card_a, card_b, card_c):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.RESOLVED
            assert card.inferred_canonical_card_id == printing.pk

    def test_de_resolution_is_written_to_every_member(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing_a, printing_b = CanonicalCardFactory(), CanonicalCardFactory()
        human_vote(card_a, printing_a, "human-1")
        human_vote(card_a, printing_a, "human-2")
        with patch("cardpicker.documents.reindex_card_safely"):
            resolve_and_persist_printing(card_a)
        assert card_a.printing_tag_status == PrintingTagStatus.RESOLVED

        # an equal-weight human disagreement lands on the SIBLING, not on card_a
        human_vote(card_b, printing_b, "human-3")
        human_vote(card_b, printing_b, "human-4")
        with patch("cardpicker.documents.reindex_card_safely"):
            result = resolve_and_persist_printing(card_b)

        assert result is None
        for card in (card_a, card_b):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
            assert card.inferred_canonical_card_id is None

    def test_only_out_of_step_members_are_reindexed(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_a, printing, "human-2")

        with patch("cardpicker.documents.reindex_card_safely") as mock_reindex:
            resolve_and_persist_printing(card_a)
        assert mock_reindex.call_count == 2  # both members entered RESOLVED

        with patch("cardpicker.documents.reindex_card_safely") as mock_reindex:
            resolve_and_persist_printing(card_a)
        mock_reindex.assert_not_called()  # same outcome, nothing to push

    def test_the_callers_own_instance_is_the_one_written_through(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_b, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        with patch("cardpicker.documents.reindex_card_safely"):
            resolve_and_persist_printing(card_a)

        # no refresh_from_db: the caller reads its own object's status straight after the call
        assert card_a.printing_tag_status == PrintingTagStatus.RESOLVED
        assert card_a.inferred_canonical_card_id == printing.pk


class TestConsensusRecomputeGroups:
    def test_a_group_is_visited_once_and_every_member_is_reported(self, db, md5_groups):
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing = CanonicalCardFactory()
        # votes on all three members: pre-#473 this walked three cards and resolved three times
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")
        machine_vote(card_c, printing, "ocr-bot")

        with patch("cardpicker.documents.reindex_card_safely"):
            with patch(
                "cardpicker.management.commands.consensus_recompute.resolve_and_persist_printing",
                side_effect=resolve_and_persist_printing,
            ) as spy:
                report = run_consensus_recompute(apply=True)

        assert spy.call_count == 1
        assert report["printing"]["checked"] == 3  # every member still counted
        assert report["printing"]["transitions"]["unresolved->resolved"] == 3

    def test_recompute_is_idempotent_over_groups(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        with patch("cardpicker.documents.reindex_card_safely"):
            run_consensus_recompute(apply=True)
            second = run_consensus_recompute(apply=True)

        assert second["printing"]["transitions"] == {}
        for card in (card_a, card_b):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.RESOLVED
            assert card.inferred_canonical_card_id == printing.pk

    def test_dry_run_predicts_the_group_outcome_for_every_member(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        report = run_consensus_recompute(apply=False)

        assert report["printing"]["written"] == 0
        assert report["printing"]["transitions"]["unresolved->resolved"] == 2
        for card in (card_a, card_b):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED


class TestQuestionFeedGroups:
    def test_likely_resolve_reads_the_group_tally(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        # one human vote on one member: the GROUP is one agreeing human vote from resolving, so
        # every member of it is a likely-resolve question, including the voteless one.
        human_vote(card_a, printing, "human-1")

        assert is_likely_resolve_printing(card_a) is True
        assert is_likely_resolve_printing(card_b) is True

    def test_pooled_machine_weight_does_not_make_a_group_likely_resolve(self, db, md5_groups):
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing = CanonicalCardFactory()
        for card in (card_a, card_b, card_c):
            machine_vote(card, printing, "ocr-bot")

        # 0.5 pooled + 1.0 hypothetical human = 1.5, still short of the threshold. Unpooled it
        # would have been 1.5 + 1.0 = 2.5 and this would have read as "one vote from resolving".
        assert is_likely_resolve_printing(card_a) is False

    def test_answered_card_ids_expand_to_the_whole_group(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "voter-1")

        assert _voter_answered_printing_card_ids("voter-1") == {card_a.pk, card_b.pk}
        assert _voter_answered_printing_card_ids("voter-2") == set()

    def test_the_feed_serves_at_most_one_member_per_group(self, db, md5_groups):
        card_a = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        card_b = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "ocr-bot")
        machine_vote(card_b, printing, "ocr-bot")

        # a fresh voter is offered the group (as one of its members)...
        served = _tier_1_confirm_suggestion("voter-1")
        assert served is not None
        assert served.card.identifier in {card_a.identifier, card_b.identifier}

        # ...and once they have answered one member, the sibling is not offered as a second,
        # identical question.
        human_vote(card_a, printing, "voter-1")
        assert _tier_1_confirm_suggestion("voter-1") is None


class TestGroupExpansionQueryCostWithoutTheChecksumColumn:
    """
    Deliberately NOT using the `md5_groups` fixture here: that fixture monkeypatches the three
    checksum-reading functions themselves, so it can't tell us anything about what the REAL
    functions cost - which is exactly the claim being pinned. `Card.md5_checksum` is a real column
    on this branch (issue #473's PR-1 merged to `master` and reached here via the 2026-07-25
    master merge - see this module's own docstring, point 2), so `_md5_checksums_for_card_ids`
    now issues its one checksum-lookup query even for card_ids that carry no checksum at all -
    it returns an empty result rather than skipping the query outright, and its own docstring's
    "zero queries... while the column doesn't exist" clause no longer applies on this branch.
    What stays true, and is what this class actually pins, is the CHEAP-CASE bound: at most ONE
    query for the common no-checksums-set-yet case, never the second (`_card_ids_with_md5_checksums`)
    lookup, because the first query's empty result short-circuits before that second one is ever
    issued. `md5_group_key`/`md5_group_card_ids` are unaffected either way - `_card_md5_checksum`
    is a plain `getattr` on an already-loaded instance, never a query, column present or not.
    """

    def test_group_expansion_issues_at_most_one_query_and_never_the_second_lookup(self, db, django_assert_num_queries):
        card_a, card_b = CardFactory(), CardFactory()

        with django_assert_num_queries(1):
            expanded = md5_group_expanded_card_ids([card_a.pk, card_b.pk])

        assert expanded == {card_a.pk, card_b.pk}

    def test_group_key_and_card_ids_issue_zero_queries_regardless_of_the_checksum_column(
        self, db, django_assert_num_queries
    ):
        card = CardFactory()

        with django_assert_num_queries(0):
            key = md5_group_key(card)
            card_ids = md5_group_card_ids(card)

        assert key == ("card", card.pk)
        assert card_ids == [card.pk]


class TestAnsweredSetComputedOncePerFeedRequest:
    """
    2026-07-25 gate on PR #482, condition f1: `_voter_answered_printing_card_ids` must be resolved
    ONCE per `get_next_question_feed_item` call and threaded down to every tier it consults, not
    recomputed per tier.
    """

    def test_answered_set_is_computed_exactly_once(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "ocr-bot")
        machine_vote(card_b, printing, "ocr-bot")

        with patch(
            "cardpicker.question_feed._voter_answered_printing_card_ids",
            side_effect=_voter_answered_printing_card_ids,
        ) as spy:
            get_next_question_feed_item("voter-1")

        assert spy.call_count == 1

    def test_the_three_new_exclusions_are_each_computed_exactly_once(self, db):
        # 2026-08-04 gate on the phase-C/md5 routing brief: the same f1 condition above now also
        # covers _voter_answered_artist_card_ids/_voter_answered_tag_card_ids_by_tag/
        # _not_official_art_card_ids - each resolved once in get_next_question_feed_item, not
        # once per tier that consults it.
        with (
            patch(
                "cardpicker.question_feed._voter_answered_artist_card_ids",
                side_effect=_voter_answered_artist_card_ids,
            ) as artist_spy,
            patch(
                "cardpicker.question_feed._voter_answered_tag_card_ids_by_tag",
                side_effect=_voter_answered_tag_card_ids_by_tag,
            ) as tag_spy,
            patch(
                "cardpicker.question_feed._not_official_art_card_ids",
                side_effect=_not_official_art_card_ids,
            ) as art_spy,
        ):
            get_next_question_feed_item("voter-1")

        assert artist_spy.call_count == 1
        assert tag_spy.call_count == 1
        assert art_spy.call_count == 1


class TestPhaseCAndTierTwoMd5Expansion:
    """
    2026-08-04 gate on the phase-C/md5 routing brief. Two independent things, both pinned here:

    - `_not_official_art_card_ids` (phase C): a positive, human-backed no-match-reason vote for
      one of `reason_tags.NOT_OFFICIAL_ART_REASON_TAGS` stops the artist question from being
      served for that card's whole md5 group.
    - `_tier_2_contested`'s artist/tag own-vote exclusions, md5-expanded (issue #473's existing
      convention, extended to these two halves - see `_voter_answered_artist_card_ids`/
      `_voter_answered_tag_card_ids_by_tag`'s own docstrings).
    """

    def test_answered_artist_card_ids_expand_to_the_whole_group(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        CardArtistVoteFactory(card=card_a, anonymous_id="voter-1")

        assert _voter_answered_artist_card_ids("voter-1") == {card_a.pk, card_b.pk}
        assert _voter_answered_artist_card_ids("voter-2") == set()

    def test_tier_2_does_not_re_serve_an_artist_question_answered_on_a_sibling(self, db, md5_groups):
        card_a = CardFactory(artist_vote_status=ArtistVoteStatus.CONTESTED)
        card_b = CardFactory(artist_vote_status=ArtistVoteStatus.CONTESTED)
        md5_groups("same-bytes", card_a, card_b)
        artist_x, artist_y = CanonicalArtistFactory(), CanonicalArtistFactory()
        for card in (card_a, card_b):
            CardArtistVoteFactory(card=card, artist=artist_x, anonymous_id="crowd-1")
            CardArtistVoteFactory(card=card, artist=artist_y, anonymous_id="crowd-2")

        # voter-1 answers card_a's artist question...
        CardArtistVoteFactory(card=card_a, artist=artist_x, anonymous_id="voter-1")

        # ...and must not be re-served the identical question via card_b, its byte-identical
        # sibling, even though voter-1 never cast a vote on card_b directly.
        assert _tier_2_contested("voter-1") is None

    def test_answered_tag_card_ids_by_tag_expand_to_the_whole_group(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        tag = TagFactory(name="Full Art")
        CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="voter-1")

        by_tag = _voter_answered_tag_card_ids_by_tag("voter-1")

        assert by_tag[tag.name] == {card_a.pk, card_b.pk}
        assert _voter_answered_tag_card_ids_by_tag("voter-2") == {}

    def test_tier_2_does_not_re_serve_a_tag_question_answered_on_a_sibling(self, db, md5_groups):
        card_a = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        card_b = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        md5_groups("same-bytes", card_a, card_b)
        tag = TagFactory(name="Full Art")
        for card in (card_a, card_b):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
            resolve_and_persist_tag_votes(card)
            card.refresh_from_db()
        assert card_a.tag_vote_statuses[tag.name] == TagVoteStatus.CONTESTED
        assert card_b.tag_vote_statuses[tag.name] == TagVoteStatus.CONTESTED

        # voter-1 answers tag on card_a...
        CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="voter-1")

        # ...and must not be re-served the identical (card, tag) question via card_b's own
        # otherwise-still-contested pair.
        assert _tier_2_contested("voter-1") is None

    def test_a_different_tag_on_the_group_is_still_served_despite_the_widened_exclusion(self, db, md5_groups):
        card_a = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        card_b = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        md5_groups("same-bytes", card_a, card_b)
        tag_a = TagFactory(name="Full Art")
        tag_b = TagFactory(name="Etched")
        for tag in (tag_a, tag_b):
            CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
            CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
        resolve_and_persist_tag_votes(card_a)
        card_a.refresh_from_db()

        # voter-1 answers tag_a on card_a - widened to the whole md5 group for tag_a specifically...
        CardTagVoteFactory(card=card_a, tag=tag_a, polarity=VotePolarity.APPLY, anonymous_id="voter-1")

        # ...but tag_b, untouched, must still be served - the exclusion is per-tag, not
        # per-card, even once widened onto md5 siblings (the regression the identical comment
        # in _tier_2_contested itself warns against).
        result = _tier_2_contested("voter-1")
        assert result is not None
        item, reason = result
        assert reason == "tier_2_contested_tag"
        assert item.tagName == tag_b.name
        assert item.card.identifier == card_a.identifier

    def test_not_official_art_vote_excludes_the_whole_group_from_artist_questions(self, db, md5_groups):
        card_a = CardFactory(artist_vote_status=ArtistVoteStatus.CONTESTED)
        card_b = CardFactory(artist_vote_status=ArtistVoteStatus.CONTESTED)
        md5_groups("same-bytes", card_a, card_b)
        artist_x, artist_y = CanonicalArtistFactory(), CanonicalArtistFactory()
        for card in (card_a, card_b):
            CardArtistVoteFactory(card=card, artist=artist_x, anonymous_id="crowd-1")
            CardArtistVoteFactory(card=card, artist=artist_y, anonymous_id="crowd-2")
        tag = TagFactory(name="custom-art")
        CardTagVoteFactory(card=card_a, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="reporter-1")

        assert _not_official_art_card_ids() == {card_a.pk, card_b.pk}
        assert _tier_2_contested("voter-1") is None


def _join_key_evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        collector_line_set_code="mom",
        collector_line_collector_number="158",
        transferred=False,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestTransferredEvidencePoolsWithItsSource:
    """
    Issue #473 PR-3 (2026-07-25): retiring the interim Stage D guard
    (`local_calculate_verdicts.TRANSFERRED_INTERIM_GUARD_SKIP_REASON`) makes a transferred-
    evidence card exactly as Stage-D-eligible as any other card - see
    test_local_calculate_verdicts.py::TestTransferredEvidenceIsEligible for that half of the pin
    (the guard's ABSENCE is intentional, not a regression). THIS class pins the other half: group-
    level pooling is what actually prevents the guard's old failure mode (a transferred row's vote
    fabricating an independent second confirmation of the same underlying bytes), because the
    source card's REAL extraction and its md5 sibling's TRANSFERRED copy of it are cast by the
    SAME calculator under one fixed `anonymous_id` (`JOIN_KEY_ANONYMOUS_ID`) - so `pool_group_
    votes` collapses them to ONE event, the same rule that collapses one human voting twice.
    """

    def test_transferred_sibling_vote_pools_with_its_source_instead_of_doubling_it(self, db, md5_groups):
        card_source, card_transferred = (
            CardFactory(name="Some Card", content_phash=42),
            CardFactory(name="Some Card", content_phash=42),
        )
        md5_groups("same-bytes", card_source, card_transferred)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _join_key_evidence(card_source, transferred=False)
        _join_key_evidence(card_transferred, transferred=True, transferred_from_card_id=card_source.pk)

        result = run_join_key_calculator(dry_run=False)

        # both cards are Stage-D-eligible and both cast a vote - the retired guard no longer
        # excludes the transferred one (mirrors TestTransferredEvidenceIsEligible's own pin).
        assert result.cards_considered == 2
        assert result.votes_written == 2
        assert CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 2

        # but the GROUP tally pools them to ONE event, since both votes share JOIN_KEY_ANONYMOUS_ID
        votes, is_group = group_printing_votes(card_source)
        assert len(votes) == 2  # both rows are read...
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert len(vote_tuples) == 1  # ...and pool to ONE event
        assert vote_tuples[0].weight == resolve_vote_weight(VoteSource.OCR, JOIN_KEY_ANONYMOUS_ID, None)

        # never enough to resolve alone - exactly the outcome the retired guard used to guarantee
        # by excluding the transferred vote outright, now achieved by pooling instead.
        assert resolve_printing(card_source) is None
        assert resolve_printing(card_transferred) is None

    def test_a_second_distinct_agent_can_still_tip_a_group_containing_a_transferred_vote(self, db, md5_groups):
        """Contrast: pooling doesn't turn the transferred card into dead weight excluded from
        ever influencing an outcome (that WAS the old guard's effect) - a genuinely independent
        second agent's vote on the group still resolves it, same as any other group."""
        card_source, card_transferred = (
            CardFactory(name="Some Card", content_phash=42),
            CardFactory(name="Some Card", content_phash=42),
        )
        md5_groups("same-bytes", card_source, card_transferred)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _join_key_evidence(card_source, transferred=False)
        _join_key_evidence(card_transferred, transferred=True, transferred_from_card_id=card_source.pk)

        run_join_key_calculator(dry_run=False)
        assert resolve_printing(card_source) is None  # 0.5 pooled machine weight, short of quorum

        human_vote(card_transferred, printing, "human-1")
        human_vote(card_source, printing, "human-2")

        assert resolve_printing(card_source) == printing
        assert resolve_printing(card_transferred) == printing


class TestVersionedCalculatorIdentity:
    """
    2026-07-28: `build_group_printing_vote_tuples` keyed pooling on the raw `anonymous_id`, which
    embeds a machine calculator's VERSION ("stage-d-join-key-v1"). "x-v1" != "x-v2", so one
    calculator counted as TWO INDEPENDENT AGENTS the moment its version was bumped - reachable
    in normal operation, because a version bump re-votes cards incrementally and an md5 identity
    group can straddle the migration. The key is now the versionless FAMILY
    (`printing_consensus.agent_dedupe_key` -> `models.calculator_family`).

    Human voters must be COMPLETELY unaffected: their `anonymous_id`s are UUIDs, which can never
    match the machine naming convention, so `calculator_family` returns None for them and they
    keep deduping on their own UUID. That property is VERIFIED here against real UUID strings,
    not assumed.
    """

    # a real client-generated anonymous id shape (frontend/src/common/anonymousId.ts)
    HUMAN_UUID_A = "3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60"
    HUMAN_UUID_B = "b81d5e77-2c93-4f16-8a0b-6d7e9f014c25"

    def test_agent_dedupe_key_is_the_family_for_a_versioned_calculator(self):
        assert agent_dedupe_key("stage-d-join-key-v1") == "stage-d-join-key"
        assert agent_dedupe_key("stage-d-join-key-v2") == "stage-d-join-key"
        assert agent_dedupe_key("local-ocr-v1") == agent_dedupe_key("local-ocr-v17")

    def test_agent_dedupe_key_is_the_raw_id_for_a_human_uuid(self):
        # calculator_family() returns None for a UUID, so the raw id is used verbatim - this is
        # the human-voter escape hatch, stated directly rather than inferred from behaviour.
        assert calculator_family(self.HUMAN_UUID_A) is None
        assert agent_dedupe_key(self.HUMAN_UUID_A) == self.HUMAN_UUID_A
        assert agent_dedupe_key(self.HUMAN_UUID_B) == self.HUMAN_UUID_B
        assert agent_dedupe_key(self.HUMAN_UUID_A) != agent_dedupe_key(self.HUMAN_UUID_B)

    def test_group_straddling_a_version_bump_counts_the_calculator_once(self, db, md5_groups):
        """
        The bug, at the tuple level: two members of one md5 group, the same calculator voting the
        same printing on each, one under -v1 and one under -v2 (exactly what an incremental
        re-vote across a version bump produces). That is ONE agent, so ONE pooled event.
        """
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "stage-d-join-key-v1")
        machine_vote(card_b, printing, "stage-d-join-key-v2")

        votes, is_group = group_printing_votes(card_a)
        assert len(votes) == 2  # both rows are read...
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)

        assert len(vote_tuples) == 1  # ...and pool to ONE event, not two
        assert vote_tuples[0].dedupe_key == "stage-d-join-key"

    def test_a_version_bump_cannot_supply_the_second_agent_a_resolution_needs(self, db, md5_groups):
        """
        The bug, at the outcome level, with the real default weights (min_weight=2.0, machine
        0.5, human 1.0). One human vote plus ONE calculator that voted under two versions used to
        sum to 1.0 + 0.5 + 0.5 = 2.0 and RESOLVE the whole group - a resolution reached by a
        redeploy rather than by evidence. Pooled by family it is 1.0 + 0.5 = 1.5, short of quorum.
        """
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_UUID_A)
        machine_vote(card_a, printing, "stage-d-join-key-v1")
        machine_vote(card_b, printing, "stage-d-join-key-v2")

        assert resolve_printing(card_a) is None
        assert resolve_printing(card_b) is None

        # and a genuinely SECOND, distinct calculator still tips it - the fix removes correlated
        # weight, it does not make the group unresolvable.
        machine_vote(card_b, printing, "local-ocr-v1")
        assert resolve_printing(card_a) == printing

    def test_a_calculator_contradicting_itself_across_a_version_bump_is_withheld(self, db, md5_groups):
        """
        `pool_group_votes`' rule 2 must reach across a version boundary too: v1 said printing X,
        v2 says printing Y (the normal shape of a corrective re-vote). Under the old raw-id key
        those were two different agents, so BOTH claims stayed in the tally and the contradiction
        was invisible. Under the family key it is one agent that contradicted itself about
        byte-identical bytes, and it contributes nothing to either side.
        """
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
        machine_vote(card_a, printing_x, "stage-d-illustration-v1")
        machine_vote(card_b, printing_y, "stage-d-illustration-v2")
        human_vote(card_a, printing_x, self.HUMAN_UUID_A)

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)

        # only the human survives - the self-contradicting calculator is withheld entirely
        assert [(vote.outcome_key, vote.dedupe_key) for vote in vote_tuples] == [(printing_x.pk, self.HUMAN_UUID_A)]

    def test_human_uuid_voters_dedupe_exactly_as_before(self, db, md5_groups):
        """
        The no-regression half. Two DIFFERENT humans on two members are two agents and still sum
        (and here, resolve); ONE human answering both members is still one agent and still
        collapses. Neither behaviour may change, because a UUID has no family.
        """
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()

        # one person, both members: ONE event, 1.0 - short of the 2.0 quorum
        human_vote(card_a, printing, self.HUMAN_UUID_A)
        human_vote(card_b, printing, self.HUMAN_UUID_A)
        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert [(vote.outcome_key, vote.dedupe_key) for vote in vote_tuples] == [(printing.pk, self.HUMAN_UUID_A)]
        assert resolve_printing(card_a) is None

        # a second, distinct person is a second agent: 2.0, resolves
        human_vote(card_b, printing, self.HUMAN_UUID_B)
        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert sorted(vote.dedupe_key for vote in vote_tuples) == sorted([self.HUMAN_UUID_A, self.HUMAN_UUID_B])
        assert resolve_printing(card_a) == printing

    def test_a_human_uuid_is_never_pooled_with_a_calculator(self, db, md5_groups):
        """Defensive: the family mapping must not create a collision between a human and a
        machine agent - distinct key spaces, verified rather than assumed."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_UUID_A)
        machine_vote(card_b, printing, "local-ocr-v3")

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert sorted(str(vote.dedupe_key) for vote in vote_tuples) == sorted([self.HUMAN_UUID_A, "local-ocr"])

    def test_singleton_groups_are_still_unkeyed_after_the_change(self, db):
        """`pool=False` short-circuits before `agent_dedupe_key` is ever consulted, so a group of
        one remains the byte-for-byte no-op ruling 3 requires - including for machine votes."""
        card = CardFactory()
        printing = CanonicalCardFactory()
        machine_vote(card, printing, "stage-d-join-key-v1")
        votes, is_group = group_printing_votes(card)
        assert is_group is False
        assert [vote.dedupe_key for vote in build_group_printing_vote_tuples(votes, pool=is_group)] == [None]


class TestCallerSuppliedGroupMustBeComplete:
    """
    `resolve_printing`/`group_printing_votes`' `group_card_ids` - and, transitively,
    `resolve_and_persist_printing`'s `members` - is an OPTIMISATION whose contract is "the
    COMPLETE md5 identity group", now ENFORCED by `printing_consensus._require_full_md5_group`
    rather than merely documented.

    The hazard is not a hypothetical about a weaker answer. Consensus pools across the whole
    group and deduplicates per AGENT, so the tally is DEFINED over the group: a subset yields a
    DIFFERENT tally and can select a different winning printing, silently - no exception, no log
    line, a plausible resolution computed from part of the evidence and then written onto every
    member. No caller passes a narrowed group today; the batch-scopeability pass (#533/#541) is
    what makes it imminent, since scoping every read by a batch's `card_ids` is correct for the
    batch's TARGETS and wrong for a target's md5 NEIGHBOURHOOD lookup like this one.

    `test_batch_boundary_subset_would_have_picked_a_different_printing` is the load-bearing case:
    it builds a group straddling a simulated batch boundary and shows, by computing the unguarded
    answer alongside the true one, that the guard converts a plausible-but-wrong resolution into
    a loud failure.
    """

    HUMAN_1 = "11111111-1111-4111-8111-111111111111"
    HUMAN_2 = "22222222-2222-4222-8222-222222222222"
    HUMAN_3 = "33333333-3333-4333-8333-333333333333"
    HUMAN_4 = "44444444-4444-4444-8444-444444444444"

    @staticmethod
    def _unguarded_resolution(group_card_ids):
        """
        What `resolve_printing` WOULD have returned for `group_card_ids` before this guard
        existed: `group_printing_votes`' own multi-member query and branch, then the identical
        tuple-building and resolver call, with the completeness check simply absent. Reproduced
        here rather than by monkeypatching the guard off, so the counterfactual is visible in the
        test and the code under test is never run with its guard disabled.
        """
        votes = list(
            CardPrintingTag.objects.filter(card_id__in=group_card_ids)
            .select_related("printing")
            .order_by("card_id", "pk")
        )
        printings_by_id: dict = {}
        vote_tuples = build_group_printing_vote_tuples(
            votes, pool=len(group_card_ids) > 1, printings_by_id=printings_by_id
        )
        winning_key = resolve_weighted_consensus(
            vote_tuples,
            min_weight=django_settings.PRINTING_TAG_MIN_VOTES,
            min_share=django_settings.PRINTING_TAG_MIN_SHARE,
        )
        return printings_by_id[winning_key] if isinstance(winning_key, int) else winning_key

    # ---- the contract holds for every shape a caller actually produces ----------------------

    def test_the_full_group_is_accepted_and_resolves_identically_to_omitting_it(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        full_group = md5_group_card_ids(card_a)
        assert set(full_group) == {card_a.pk, card_b.pk}
        assert resolve_printing(card_a, group_card_ids=full_group) == printing
        assert resolve_printing(card_a) == printing  # omitting the argument: the same answer

    def test_ordering_of_a_complete_group_is_irrelevant(self, db, md5_groups):
        """Order is normalised away deliberately: the value is only ever consumed by a
        `card_id__in` filter and a `len()`, and the pooled tally's determinism comes from that
        query's own `order_by`, never from this argument - so rejecting an unsorted but complete
        group would be a gratuitous failure with no soundness content behind it."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        assert resolve_printing(card_a, group_card_ids=list(reversed(md5_group_card_ids(card_a)))) == printing

    def test_omitting_the_parameter_still_derives_the_group_itself(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        votes, is_group = group_printing_votes(card_a)  # no group_card_ids at all
        assert is_group is True
        assert len(votes) == 2
        assert resolve_printing(card_a) == printing

    def test_a_group_of_one_may_pass_its_own_single_pk(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        human_vote(card, printing, self.HUMAN_1)

        votes, is_group = group_printing_votes(card, [card.pk])
        assert is_group is False
        assert len(votes) == 1

    # ---- every incomplete shape raises ------------------------------------------------------

    def test_a_strict_subset_raises(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card_a, group_card_ids=[card_a.pk])
        message = str(excinfo.value)
        assert f"missing [{card_b.pk}]" in message
        # the message must say WHY, so whoever hits it fixes the wiring rather than the check
        assert "DIFFERENT one" in message
        assert "DIFFERENT WINNING PRINTING" in message
        assert "group_card_ids=None" in message

    def test_a_superset_raises(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        outsider = CardFactory()  # checksum-less: its own group of one, not a member of card_a's
        md5_groups("same-bytes", card_a, card_b)

        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card_a, group_card_ids=[card_a.pk, card_b.pk, outsider.pk])
        assert f"not in the group [{outsider.pk}]" in str(excinfo.value)

    def test_a_foreign_pk_raises_even_at_the_right_length(self, db, md5_groups):
        """Same cardinality as the real group, one member swapped for a stranger - the shape a
        length-only or count-only check would wave straight through."""
        card_a, card_b = CardFactory(), CardFactory()
        outsider = CardFactory()
        md5_groups("same-bytes", card_a, card_b)

        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card_a, group_card_ids=[card_a.pk, outsider.pk])
        message = str(excinfo.value)
        assert f"missing [{card_b.pk}]" in message
        assert f"not in the group [{outsider.pk}]" in message

    def test_an_empty_group_raises(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)

        with pytest.raises(ValueError):
            resolve_printing(card_a, group_card_ids=[])

    def test_a_group_of_one_passed_twice_raises_because_duplicates_flip_the_pooling_branch(self, db):
        """
        Why duplicates are rejected rather than tolerated - and why plain set equality would have
        left this second, narrower hole open. `[pk, pk]` is set-equal to `[pk]`, but
        `group_printing_votes` branches on `len(group_card_ids) <= 1`, so the duplicate takes the
        MULTI-MEMBER branch and pools with `dedupe_key` set. For a genuine group of one holding
        one agent's two contradicting votes that flips the answer outright: pooled, the agent is
        withheld entirely; unpooled - the correct reading for a singleton - its two votes stand.
        """
        card = CardFactory()
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()
        # one agent, two contradicting votes on ONE card - permitted, since the uniqueness
        # constraint is on (card, printing, anonymous_id)
        human_vote(card, printing_x, self.HUMAN_1)
        human_vote(card, printing_y, self.HUMAN_1)

        assert md5_group_card_ids(card) == [card.pk]
        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card, group_card_ids=[card.pk, card.pk])
        assert f"duplicated [{card.pk}]" in str(excinfo.value)

        # ...and the flip that duplicate would have caused is real, not theoretical:
        singleton_votes, singleton_is_group = group_printing_votes(card)
        assert singleton_is_group is False
        assert len(build_group_printing_vote_tuples(singleton_votes, pool=singleton_is_group)) == 2
        assert build_group_printing_vote_tuples(singleton_votes, pool=True) == []

    def test_a_duplicated_member_of_a_real_group_also_raises(self, db, md5_groups):
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)

        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card_a, group_card_ids=[card_a.pk, card_a.pk, card_b.pk])
        assert f"duplicated [{card_a.pk}]" in str(excinfo.value)

    def test_group_printing_votes_rejects_a_subset_directly(self, db, md5_groups):
        """The guard lives at the point of CONSUMPTION, so it cannot be reached around by
        calling `group_printing_votes` instead of `resolve_printing`."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)

        with pytest.raises(ValueError):
            group_printing_votes(card_a, [card_b.pk])

    # ---- the real scenario: an identity group straddling a batch boundary --------------------

    def test_batch_boundary_subset_would_have_picked_a_different_printing(self, db, md5_groups):
        """
        THE SCENARIO THE GUARD EXISTS FOR. Three byte-identical cards; a batch-scopeable pass
        (#533/#541) is processing a batch that happens to contain only two of them, and its
        author threads the batch's `card_ids` into `resolve_printing` exactly the way they thread
        it into every other read in the loop.

        Votes are arranged so the two readings disagree on the WINNER, not merely on confidence:

          HUMAN_1  printing_y on card_a  AND  printing_x on card_c
                   -> contradicts itself across the FULL group, so pooling withholds it
                      entirely; inside the batch it looks perfectly consistent and counts 1.0
                      towards y.
          HUMAN_2  printing_y on card_b        -> 1.0 for y in both readings
          HUMAN_3  printing_x on card_c        -> 1.0 for x, invisible to the batch
          HUMAN_4  printing_x on card_c        -> 1.0 for x, invisible to the batch

        Full group : x = 2.0 (HUMAN_3 + HUMAN_4), y = 1.0 (HUMAN_2), HUMAN_1 withheld
                     -> quorum 2.0, share 0.67  -> resolves printing_x
        In-batch   : y = 2.0 (HUMAN_1 + HUMAN_2), x = 0.0
                     -> quorum 2.0, share 1.00  -> resolves printing_y

        Both are fully gated, human-backed, entirely plausible resolutions. They are different
        printings.
        """
        card_a, card_b, card_c = CardFactory(), CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b, card_c)
        printing_x, printing_y = CanonicalCardFactory(), CanonicalCardFactory()

        human_vote(card_a, printing_y, self.HUMAN_1)
        human_vote(card_c, printing_x, self.HUMAN_1)  # HUMAN_1 now contradicts itself group-wide
        human_vote(card_b, printing_y, self.HUMAN_2)
        human_vote(card_c, printing_x, self.HUMAN_3)
        human_vote(card_c, printing_x, self.HUMAN_4)

        in_batch = sorted([card_a.pk, card_b.pk])  # card_c fell into a different batch
        assert set(md5_group_card_ids(card_a)) == {card_a.pk, card_b.pk, card_c.pk}

        truth = resolve_printing(card_a)  # the whole identification target's own answer
        plausible_but_wrong = self._unguarded_resolution(in_batch)  # what the narrowed call gave

        assert truth == printing_x
        assert plausible_but_wrong == printing_y
        assert truth != plausible_but_wrong  # a DIFFERENT winner, not a weaker signal

        # ...and the guard turns that silent divergence into a loud failure.
        with pytest.raises(ValueError) as excinfo:
            resolve_printing(card_a, group_card_ids=in_batch)
        assert f"missing [{card_c.pk}]" in str(excinfo.value)

    # ---- the persist path --------------------------------------------------------------------

    def test_partial_members_raises_before_anything_is_written(self, db, md5_groups):
        """`members`' completeness is enforced transitively (its pks become `group_card_ids`),
        and the raise lands before the write loop - so a narrowed group cannot leave the group
        half-written and disagreeing with itself, which is issue #473 ruling 1's own invariant."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        with pytest.raises(ValueError):
            resolve_and_persist_printing(card_a, members=[card_a])

        card_a.refresh_from_db()
        card_b.refresh_from_db()
        assert card_a.printing_tag_status == PrintingTagStatus.UNRESOLVED
        assert card_b.printing_tag_status == PrintingTagStatus.UNRESOLVED
        assert card_a.inferred_canonical_card_id is None
        assert card_b.inferred_canonical_card_id is None

    def test_members_must_contain_the_callers_own_card_instance(self, db, md5_groups):
        """An equal-pk COPY satisfies every pk-level check and still strands the caller on a
        stale status, so instance identity is checked separately - at no query cost."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        copy_of_a = Card.objects.get(pk=card_a.pk)
        assert copy_of_a is not card_a and copy_of_a.pk == card_a.pk

        with pytest.raises(ValueError) as excinfo:
            resolve_and_persist_printing(card_a, members=[copy_of_a, card_b])
        assert "unreplaced" in str(excinfo.value)

    def test_the_members_list_md5_group_cards_produces_is_accepted(self, db, md5_groups):
        """The one shape a real caller passes today (`consensus_recompute`) must be unaffected."""
        card_a, card_b = CardFactory(), CardFactory()
        md5_groups("same-bytes", card_a, card_b)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, self.HUMAN_1)
        human_vote(card_b, printing, self.HUMAN_2)

        members = md5_group_cards(card_a)
        assert resolve_and_persist_printing(card_a, members=members) == printing
        card_a.refresh_from_db()
        card_b.refresh_from_db()
        assert card_a.printing_tag_status == PrintingTagStatus.RESOLVED
        assert card_b.printing_tag_status == PrintingTagStatus.RESOLVED
