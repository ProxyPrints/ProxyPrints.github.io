"""
Tests for artbox-phash-d0 grouping as a pooling primitive (issue #661) -
`printing_consensus.identity_group_card_ids`/`identity_group_cards`/`identity_group_key`/
`identity_group_expanded_card_ids`/`phash_group_card_ids`: the union of the pre-existing md5
identity group (issue #473) with a new artbox-phash-distance-0 group, which now feeds
`group_printing_votes`/`resolve_printing`/`resolve_and_persist_printing` and `question_feed`'s
answered-set widening in place of the md5-only group those used before.

Companion to `test_md5_group_pooling.py`, which this deliberately does NOT duplicate: the pure
pooling primitive (`vote_consensus.pool_group_votes`) and the full md5-only surface are pinned
there. This file is scoped to what issue #661 actually adds - the phash channel itself, and the
union composition - using REAL `Card.md5_checksum`/`ImageEvidence.artbox_phash` columns (both
real fields on this branch, unlike `test_md5_group_pooling.py`'s `md5_groups` monkeypatch
fixture, which predates the checksum column and is kept there for reasons that don't apply here).
"""

from cardpicker.models import VoteSource, calculator_family
from cardpicker.printing_consensus import (
    agent_dedupe_key,
    build_group_printing_vote_tuples,
    group_printing_votes,
    identity_group_card_ids,
    identity_group_cards,
    identity_group_expanded_card_ids,
    identity_group_key,
    md5_group_card_ids,
    phash_group_card_ids,
    resolve_and_persist_printing,
    resolve_printing,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    CardPrintingTagFactory,
    ImageEvidenceFactory,
)


def phash_evidence(card, phash, content_hash=None, **overrides):
    """
    A CURRENT `ImageEvidence` row for `card` carrying `phash`. `content_hash` defaults to
    `card.content_phash` so the row passes `image_evidence.current_evidence_queryset`'s currency
    check; `md5_checksum` is left at `ImageEvidenceFactory`'s own default (`None`), which is
    null-tolerant under `evidence_transfer.md5_currency_q` and never disagrees with the card's
    own. Passing an explicit `content_hash` that does NOT match `card.content_phash` is how the
    staleness test below builds a deliberately-stale row.
    """
    defaults = dict(
        content_hash=content_hash if content_hash is not None else (card.content_phash or 0), artbox_phash=phash
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def machine_vote(card, printing, anonymous_id):
    return CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=anonymous_id)


def human_vote(card, printing, anonymous_id):
    return CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id=anonymous_id)


class TestPhashGroupCardIds:
    def test_no_phash_is_a_group_of_one(self, db):
        card = CardFactory(content_phash=1)
        assert phash_group_card_ids(card) == [card.pk]

    def test_shared_phash_forms_a_group(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=555)
        phash_evidence(card_b, phash=555)

        assert phash_group_card_ids(card_a) == sorted([card_a.pk, card_b.pk])
        assert phash_group_card_ids(card_b) == sorted([card_a.pk, card_b.pk])

    def test_stale_evidence_row_is_excluded(self, db):
        """A card whose image has changed since its evidence row was written (`content_hash` no
        longer matches the card's own live `content_phash`) must not seed - or join - a phash
        group, the same staleness rule every other Stage C/D reader in this codebase applies."""
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=555)
        phash_evidence(card_b, phash=555, content_hash=999)  # stale: card_b.content_phash is 2

        assert phash_group_card_ids(card_a) == [card_a.pk]

    def test_null_phash_cohort_forms_no_group(self, db):
        """
        The ruling issue #661's own brief calls out by name: cards with no `artbox_phash` are
        NOT a shared group of NULLs. `_current_artbox_phash_queryset`'s `artbox_phash__isnull=
        False` filter is what enforces this - a bare `artbox_phash=None` lookup would otherwise
        match every phash-less card at once, exactly the catastrophic misread this test pins
        against (the same failure mode `_card_md5_checksum`'s own docstring already warns about
        for a checksum-less card).
        """
        cards = [CardFactory(content_phash=n) for n in range(5)]
        for card in cards:
            assert phash_group_card_ids(card) == [card.pk]
        # and the combined group agrees - no cross-card merge via a shared absence of evidence
        all_ids = {card_id for card in cards for card_id in identity_group_card_ids(card)}
        assert all_ids == {card.pk for card in cards}


class TestIdentityGroupComposition:
    def test_group_spanning_multiple_md5s_unions_via_phash(self, db):
        """The headline issue #661 case: two cards with DIFFERENT checksums (different files) but
        the SAME artbox_phash (same art) end up in one combined identity group, even though md5
        alone sees no relation between them at all."""
        card_a = CardFactory(md5_checksum="checksum-a", content_phash=1)
        card_b = CardFactory(md5_checksum="checksum-b", content_phash=2)
        phash_evidence(card_a, phash=777)
        phash_evidence(card_b, phash=777)

        assert identity_group_card_ids(card_a) == sorted([card_a.pk, card_b.pk])
        assert md5_group_card_ids(card_a) == [card_a.pk]

    def test_md5_siblings_join_via_checksum_alone(self, db):
        card_a = CardFactory(md5_checksum="same-bytes", content_phash=1)
        card_b = CardFactory(md5_checksum="same-bytes", content_phash=1)
        assert identity_group_card_ids(card_a) == sorted([card_a.pk, card_b.pk])

    def test_chain_through_a_bridging_card_is_covered_by_one_union(self, db):
        """A-md5-B-phash-C: card_b bridges a checksum edge to card_a and a phash edge to card_c.
        Per `identity_group_card_ids`'s own docstring this is reachable from card_a WITHOUT an
        iterative closure pass, because all three rows carry the identical stamped phash here -
        card_a's own phash lookup already reaches card_c directly."""
        card_a = CardFactory(md5_checksum="same-bytes", content_phash=1)
        card_b = CardFactory(md5_checksum="same-bytes", content_phash=1)
        card_c = CardFactory(md5_checksum="different-bytes", content_phash=2)
        phash_evidence(card_a, phash=42)
        phash_evidence(card_b, phash=42)
        phash_evidence(card_c, phash=42)

        assert identity_group_card_ids(card_a) == sorted([card_a.pk, card_b.pk, card_c.pk])

    def test_identity_group_cards_preserves_callers_own_instance(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=9)
        phash_evidence(card_b, phash=9)

        group = identity_group_cards(card_a)
        assert any(member is card_a for member in group)

    def test_identity_group_key_agrees_for_phash_only_siblings(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=9)
        phash_evidence(card_b, phash=9)

        assert identity_group_key(card_a) == identity_group_key(card_b) == ("phash", 9)

    def test_checksum_takes_priority_in_the_key_but_group_still_includes_the_checksum_sibling(self, db):
        card_a = CardFactory(md5_checksum="same-bytes", content_phash=1)
        card_b = CardFactory(md5_checksum="same-bytes", content_phash=1)
        phash_evidence(card_a, phash=9)

        assert identity_group_key(card_a) == ("md5", "same-bytes")
        assert identity_group_card_ids(card_a) == sorted([card_a.pk, card_b.pk])


class TestVoteTransferAcrossAPhashGroup:
    def test_phash_group_spanning_multiple_md5s_transfers_a_vote(self, db):
        """The measured, headline case from issue #661's brief: two cards, different files
        (different md5), same art (same artbox_phash at d=0) - votes cast across both members
        pool exactly as an md5-identical pair's already do."""
        card_a = CardFactory(md5_checksum="checksum-a", content_phash=1)
        card_b = CardFactory(md5_checksum="checksum-b", content_phash=2)
        phash_evidence(card_a, phash=777)
        phash_evidence(card_b, phash=777)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        assert resolve_printing(card_a) == printing
        assert resolve_printing(card_b) == printing

    def test_resolution_persists_to_the_phash_sibling_with_no_votes_of_its_own(self, db):
        card_a = CardFactory(md5_checksum="checksum-a", content_phash=1)
        card_b = CardFactory(md5_checksum="checksum-b", content_phash=2)
        phash_evidence(card_a, phash=777)
        phash_evidence(card_b, phash=777)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_a, printing, "human-2")

        resolve_and_persist_printing(card_a)

        card_b.refresh_from_db()
        assert card_b.inferred_canonical_card_id == printing.pk

    def test_unrelated_phash_does_not_widen_an_md5_only_group(self, db):
        """Two md5-identical cards resolve exactly as before when a THIRD, unrelated card happens
        to carry a phash that matches neither of them - no accidental widening."""
        card_a = CardFactory(md5_checksum="same-bytes", content_phash=1)
        card_b = CardFactory(md5_checksum="same-bytes", content_phash=1)
        unrelated = CardFactory(content_phash=99)
        phash_evidence(unrelated, phash=12345)
        printing = CanonicalCardFactory()
        human_vote(card_a, printing, "human-1")
        human_vote(card_b, printing, "human-2")

        assert resolve_printing(card_a) == printing
        assert identity_group_card_ids(unrelated) == [unrelated.pk]


class TestCalculatorFamilyDedupeAcrossAPhashGroup:
    def test_same_calculator_family_across_phash_siblings_collapses_to_one_agent(self, db):
        """`agent_dedupe_key`'s own invariant, exercised across the NEW (phash) channel: two
        phash-d0 siblings both carrying the SAME calculator family's vote (a version bump between
        them) must pool to one event, not two - a phash group must not be able to manufacture
        apparent independent agreement any more than an md5 group can."""
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=42)
        phash_evidence(card_b, phash=42)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "stage-d-join-key-v1")
        machine_vote(card_b, printing, "stage-d-join-key-v2")

        assert calculator_family("stage-d-join-key-v1") == calculator_family("stage-d-join-key-v2")
        assert agent_dedupe_key("stage-d-join-key-v1") == agent_dedupe_key("stage-d-join-key-v2")

        votes, is_group = group_printing_votes(card_a)
        assert is_group is True
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert len(vote_tuples) == 1
        assert vote_tuples[0].weight == 0.5

    def test_pooled_machine_weight_alone_still_cannot_resolve_a_phash_group(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=42)
        phash_evidence(card_b, phash=42)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "stage-d-join-key-v1")
        machine_vote(card_b, printing, "stage-d-join-key-v2")

        assert resolve_printing(card_a) is None

    def test_distinct_calculator_families_across_phash_siblings_still_count_separately(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=42)
        phash_evidence(card_b, phash=42)
        printing = CanonicalCardFactory()
        machine_vote(card_a, printing, "stage-d-join-key-v1")
        machine_vote(card_b, printing, "stage-d-fallback-v1")

        votes, is_group = group_printing_votes(card_a)
        vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group)
        assert len(vote_tuples) == 2


class TestIdentityGroupExpandedCardIds:
    def test_expands_through_phash_when_no_checksum_present(self, db):
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        phash_evidence(card_a, phash=9)
        phash_evidence(card_b, phash=9)

        assert identity_group_expanded_card_ids([card_a.pk]) == {card_a.pk, card_b.pk}

    def test_empty_input_returns_empty(self, db):
        assert identity_group_expanded_card_ids([]) == set()

    def test_singleton_input_with_no_evidence_returns_itself(self, db):
        card = CardFactory(content_phash=1)
        assert identity_group_expanded_card_ids([card.pk]) == {card.pk}
