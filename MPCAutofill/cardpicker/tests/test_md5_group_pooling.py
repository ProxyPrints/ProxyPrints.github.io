"""
Group-level vote pooling for md5 identity groups (issue #473 PR-3, owner-ratified 2026-07-25).

Two halves, and the split matters:

1. `TestPoolGroupVotes` exercises `vote_consensus.pool_group_votes` as the pure function it is -
   no database, no models, no md5 anywhere. This is where the two properties docs/theory.md §4's
   group-pooling item actually claims are pinned down: one agent counts once (agreeing votes
   collapse), and an agent that contradicts itself counts for nothing (order-independently).
2. Everything else exercises the real resolver/persistence/feed/recompute paths against real
   `Card`/`CardPrintingTag` rows, with group MEMBERSHIP supplied by the `md5_groups` fixture
   below rather than by a populated `Card.md5_checksum` column - because that column arrives in
   this issue's PR-1 (`md5-checksum-substrate`), which this branch is cut BEFORE. The fixture
   replaces the three - and only three - functions in `printing_consensus` that touch the column
   (`_card_md5_checksum`, `_md5_checksums_for_card_ids`, `_card_ids_with_md5_checksums`), so
   every line of grouping, pooling, propagation, and feed logic under test is the real one; only
   the storage of the checksum is faked. Once PR-1 is merged into this branch, these tests keep
   passing unchanged and can be supplemented with column-backed equivalents.

The SINGLETON NO-OP proof (ruling 3) is deliberately NOT concentrated in one test here: it is
the entire pre-existing consensus/printing/tag/question-feed/recompute suite, which passes
UNMODIFIED, because a card with no checksum is a group of one and every path below degenerates
to its pre-#473 behavior. `TestSingletonIsANoOp` adds the direct, mechanical statements of that
degeneration (group of one, no pooling keys, no extra queries, prefetch still honoured) that the
existing suite asserts only indirectly.
"""

from unittest.mock import patch

import pytest

from cardpicker import printing_consensus
from cardpicker.management.commands.consensus_recompute import run_consensus_recompute
from cardpicker.models import Card, PrintingTagStatus, VoteSource
from cardpicker.printing_consensus import (
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
    _tier_1_confirm_suggestion,
    _voter_answered_printing_card_ids,
    is_likely_resolve_printing,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    CardPrintingTagFactory,
)
from cardpicker.vote_consensus import VoteTuple, pool_group_votes


@pytest.fixture
def md5_groups(monkeypatch):
    """
    Assigns md5 identity groups to `Card` rows without `Card.md5_checksum` existing yet (see this
    module's docstring). Returns a callable: `md5_groups("checksum", card_a, card_b)` puts those
    cards in one group. Cards never passed to it stay checksum-less - i.e. groups of one, the
    ruling-3 degenerate case - exactly as every card in the catalogue is today.
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
