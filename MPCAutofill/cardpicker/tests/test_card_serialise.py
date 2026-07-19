"""
Unit tests for the two additive `Card.serialise()` payload fields Proposal H §4.4′ (issue
#184) hands off to the backend: `suggestedCanonicalCard` (a machine-suggested-but-unresolved
printing) and `tagVoteStatuses` (the suggested-vs-resolved distinction for per-tag votes). See
docs/features/printing-tags.md's "Card payload" section for the field contracts these tests
pin down.
"""
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    PrintingTagStatus,
    TagVoteStatus,
    VoteSource,
    suggested_printing_votes_prefetch,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
    TagFactory,
)

# see test_printing_consensus.py for why this capture-and-restore fixture exists
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
    TagFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


class TestSuggestedCanonicalCard:
    def test_none_when_flag_not_set(self, db):
        # opt-in kwarg: even with a machine vote on record, plain `serialise()` (no kwarg,
        # matching every other existing call site) must not compute or expose it.
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        assert card.serialise().suggestedCanonicalCard is None

    def test_none_when_no_votes_at_all(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        assert card.serialise(include_suggested_printing=True).suggestedCanonicalCard is None

    def test_none_when_only_human_votes(self, db):
        # "machine-suggested" per the issue's own wording - a card with real signal from
        # human votes alone (e.g. contested) is NOT exposed here; that's a distinct concept
        # this field deliberately doesn't cover.
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        assert card.serialise(include_suggested_printing=True).suggestedCanonicalCard is None

    @pytest.mark.parametrize("machine_source", [VoteSource.DEDUCTION, VoteSource.OCR])
    def test_populated_from_machine_vote(self, db, machine_source):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=machine_source)
        result = card.serialise(include_suggested_printing=True).suggestedCanonicalCard
        assert result is not None
        assert result.identifier == str(printing.identifier)

    def test_none_when_resolved_even_with_machine_vote(self, db):
        # never redundant with the already-resolved canonicalCard
        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        assert card.serialise(include_suggested_printing=True).suggestedCanonicalCard is None

    def test_ignores_no_match_machine_vote(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=None, is_no_match=True, source=VoteSource.DEDUCTION)
        assert card.serialise(include_suggested_printing=True).suggestedCanonicalCard is None

    def test_first_vote_by_pk_wins_matching_question_feed_ordering(self, db):
        # mirrors question_feed.py's un-prefetched `ai_vote = ....first()` semantics exactly
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        first_printing = CanonicalCardFactory()
        second_printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=first_printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=second_printing, source=VoteSource.OCR)
        result = card.serialise(include_suggested_printing=True).suggestedCanonicalCard
        assert result is not None
        assert result.identifier == str(first_printing.identifier)

    def test_prefetch_produces_same_result_as_unprefetched_fallback(self, db):
        from cardpicker.models import Card

        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)

        unprefetched = Card.objects.get(pk=card.pk)
        prefetched = Card.objects.prefetch_related(suggested_printing_votes_prefetch()).get(pk=card.pk)

        unprefetched_result = unprefetched.serialise(include_suggested_printing=True).suggestedCanonicalCard
        prefetched_result = prefetched.serialise(include_suggested_printing=True).suggestedCanonicalCard
        assert unprefetched_result is not None
        assert prefetched_result is not None
        assert unprefetched_result.identifier == prefetched_result.identifier == str(printing.identifier)


class TestTagVoteStatuses:
    def test_empty_when_no_votes(self, db):
        card = CardFactory()
        assert card.serialise().tagVoteStatuses == {}

    @pytest.mark.parametrize(
        "db_status, expected",
        [
            (TagVoteStatus.RESOLVED_APPLY, "resolved"),
            (TagVoteStatus.RESOLVED_REJECT, "resolved"),
            (TagVoteStatus.CONTESTED, "suggested"),
            (TagVoteStatus.UNRESOLVED, "suggested"),
        ],
    )
    def test_two_way_collapse(self, db, db_status, expected):
        card = CardFactory(tag_vote_statuses={"full-art": db_status})
        result = card.serialise().tagVoteStatuses
        assert result == {"full-art": expected}

    def test_pending_approval_excluded_entirely(self, db):
        # sensitive-tag co-sign queue (docs/features/moderation.md) - must never leak ahead
        # of that review, same reason it's excluded from `tags` today.
        card = CardFactory(tag_vote_statuses={"nsfw-adjacent": TagVoteStatus.PENDING_APPROVAL})
        assert card.serialise().tagVoteStatuses == {}

    def test_mixed_statuses_one_card(self, db):
        card = CardFactory(
            tag_vote_statuses={
                "full-art": TagVoteStatus.RESOLVED_APPLY,
                "borderless": TagVoteStatus.RESOLVED_REJECT,
                "retro-frame": TagVoteStatus.CONTESTED,
                "showcase": TagVoteStatus.UNRESOLVED,
                "sensitive-thing": TagVoteStatus.PENDING_APPROVAL,
            }
        )
        assert card.serialise().tagVoteStatuses == {
            "full-art": "resolved",
            "borderless": "resolved",
            "retro-frame": "suggested",
            "showcase": "suggested",
        }

    def test_available_regardless_of_include_suggested_printing_flag(self, db):
        # tagVoteStatuses is zero-cost (already-loaded JSONField, no query) - unlike
        # suggestedCanonicalCard it is never gated behind the opt-in kwarg.
        card = CardFactory(tag_vote_statuses={"full-art": TagVoteStatus.RESOLVED_APPLY})
        assert card.serialise().tagVoteStatuses == {"full-art": "resolved"}
        assert card.serialise(include_suggested_printing=True).tagVoteStatuses == {"full-art": "resolved"}


def _make_unresolved_card_with_machine_vote(source):
    card = CardFactory(source=source, printing_tag_status=PrintingTagStatus.UNRESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
    return card, printing


class TestPostCardsBulkPayload:
    """
    `POST 2/cards/` (`views.post_cards`) is one of the two bulk Card-payload endpoints this
    feature targets (issue #184) - see `suggested_printing_votes_prefetch()`'s own docstring
    for why this one and `post_explore_search` specifically.
    """

    def test_suggested_canonical_card_present_for_unresolved_machine_suggested_card(self, db, client, django_settings):
        source = SourceFactory()
        card, printing = _make_unresolved_card_with_machine_vote(source)

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedCanonicalCard"] is not None
        assert payload["suggestedCanonicalCard"]["identifier"] == str(printing.identifier)

    def test_suggested_canonical_card_absent_without_machine_vote(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(source=source, printing_tag_status=PrintingTagStatus.UNRESOLVED)

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedCanonicalCard"] is None

    def test_tag_vote_statuses_present_with_suggested_and_resolved_distinction(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(
            source=source,
            tag_vote_statuses={
                "full-art": TagVoteStatus.RESOLVED_APPLY,
                "retro-frame": TagVoteStatus.CONTESTED,
                "sensitive-thing": TagVoteStatus.PENDING_APPROVAL,
            },
        )

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["tagVoteStatuses"] == {"full-art": "resolved", "retro-frame": "suggested"}


class TestBulkPayloadQueryCount:
    """
    Query-count evidence for the "no N+1" constraint (issue #184): `suggestedCanonicalCard`
    must be attachable to a bulk `post_cards` result set via `suggested_printing_votes_prefetch()`
    without the query count scaling with the number of cards requested.
    """

    def test_query_count_does_not_scale_with_result_size(self, db, client, django_settings):
        source = SourceFactory()
        small_batch = [_make_unresolved_card_with_machine_vote(source)[0] for _ in range(2)]
        large_batch = small_batch + [_make_unresolved_card_with_machine_vote(source)[0] for _ in range(6)]

        def _post_and_count_queries(cards):
            with CaptureQueriesContext(connection) as ctx:
                response = client.post(
                    reverse(views.post_cards),
                    {"cardIdentifiers": [c.identifier for c in cards]},
                    content_type="application/json",
                )
                assert response.status_code == 200
            return len(ctx.captured_queries)

        small_query_count = _post_and_count_queries(small_batch)
        large_query_count = _post_and_count_queries(large_batch)

        # same query count for 2 cards as for 8 - if suggestedCanonicalCard ever regressed to
        # a per-card query, this would instead scale linearly with the batch size.
        assert small_query_count == large_query_count
