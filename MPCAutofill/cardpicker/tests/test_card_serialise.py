"""
Unit tests for the two additive `Card.serialise()` payload fields Proposal H §4.4′ (issue
#184) hands off to the backend: `suggestedCanonicalCard` (a machine-suggested-but-unresolved
printing) and `tagVoteStatuses` (the suggested-vs-resolved distinction for per-tag votes). See
docs/features/printing-tags.md's "Card payload" section for the field contracts these tests
pin down.
"""
import pytest

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cardpicker import views
from cardpicker.models import (
    Card,
    CardTypes,
    PrintingTagStatus,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
    attach_suggested_filter_tags_overlay,
    suggested_printing_votes_prefetch,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    SourceFactory,
    TagFactory,
)


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


class TestSuggestedFilterTagNames:
    """
    `Card.serialise(include_suggested_filter_tags=True)` (owner-ratified 2026-07-22 D6
    vote-weight matrix) - the qualifying-condition logic itself lives in and is fully covered by
    `test_tag_votes.py::TestGetSuggestedFilterTagsOverlay`; these tests instead pin down
    `Card._suggested_filter_tag_names`'s own opt-in-kwarg and precomputed-attribute-first
    plumbing, mirroring `TestSuggestedCanonicalCard` above.
    """

    def test_none_when_flag_not_set(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert card.serialise().suggestedFilterTagNames is None

    def test_empty_list_not_null_when_flag_set_and_nothing_qualifies(self, db):
        card = CardFactory()
        assert card.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == []

    def test_populated_from_qualifying_vote(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert card.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == ["Foil"]

    def test_implicit_only_votes_do_not_qualify(self, db):
        # condition-6 regression: an implicit vote is a passive filter-chip-selection
        # by-product, not independent evidence (D6) - must not bootstrap its own suggestion.
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(
            card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.IMPLICIT, anonymous_id="impl-1"
        )
        assert card.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == []

    def test_sensitive_tag_never_suggested(self, db):
        card = CardFactory()
        tag = TagFactory(name="NSFW", moderation_class=TagModerationClass.SENSITIVE)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        assert card.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == []

    def test_resolved_pair_not_suggested(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == []

    def test_precomputed_attribute_avoids_the_per_card_fallback_query(self, db):
        # attach_suggested_filter_tags_overlay stamps the batched result up front - serialise()
        # must read that instead of running its own per-card fallback query
        # (get_suggested_filter_tags_overlay's own two queries, see its docstring).
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        unattached = Card.objects.select_related("source", "canonical_card").get(pk=card.pk)
        with CaptureQueriesContext(connection) as ctx_unattached:
            unattached_result = unattached.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames
        assert unattached_result == ["Foil"]
        assert len(ctx_unattached.captured_queries) == 2

        attached = Card.objects.select_related("source", "canonical_card").get(pk=card.pk)
        attach_suggested_filter_tags_overlay([attached])
        with CaptureQueriesContext(connection) as ctx_attached:
            attached_result = attached.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames
        assert attached_result == ["Foil"]
        assert len(ctx_attached.captured_queries) == 0

    def test_unattached_fallback_produces_same_result(self, db):
        card = CardFactory()
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        unattached = Card.objects.get(pk=card.pk)
        assert unattached.serialise(include_suggested_filter_tags=True).suggestedFilterTagNames == ["Foil"]


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

    def test_suggested_filter_tag_names_present_for_qualifying_vote(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(source=source)
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedFilterTagNames"] == ["Foil"]

    def test_suggested_filter_tag_names_empty_list_when_nothing_qualifies(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(source=source)

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        # opt-in field IS requested by post_cards - empty list, never null, when nothing
        # qualifies (see schema_types.ts:235's null-only-when-endpoint-didn't-request semantics).
        assert payload["suggestedFilterTagNames"] == []

    def test_suggested_filter_tag_names_absent_for_implicit_only_votes(self, db, client, django_settings):
        # condition-6 regression at the API layer: an implicit-only vote must not surface a
        # suggested filter chip through the real endpoint response, not just the underlying
        # overlay function (see TestGetSuggestedFilterTagsOverlay in test_tag_votes.py for the
        # unit-level version of this rule).
        source = SourceFactory()
        card = CardFactory(source=source)
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(
            card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.IMPLICIT, anonymous_id="impl-1"
        )

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedFilterTagNames"] == []

    def test_suggested_filter_tag_names_absent_for_sensitive_tag(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(source=source)
        tag = TagFactory(name="NSFW", moderation_class=TagModerationClass.SENSITIVE)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedFilterTagNames"] == []

    def test_suggested_filter_tag_names_absent_for_resolved_pair(self, db, client, django_settings):
        source = SourceFactory()
        card = CardFactory(source=source, tags=[])
        tag = TagFactory(name="Foil")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()

        response = client.post(
            reverse(views.post_cards), {"cardIdentifiers": [card.identifier]}, content_type="application/json"
        )

        assert response.status_code == 200
        payload = response.json()["results"][card.identifier]
        assert payload["suggestedFilterTagNames"] == []


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

    def test_suggested_filter_tag_names_query_count_does_not_scale_with_result_size(self, db, client, django_settings):
        # attach_suggested_filter_tags_overlay() is exactly two queries (see
        # get_suggested_filter_tags_overlay's own docstring) for the WHOLE cards list, not per
        # card - if this ever regressed to Card.serialise(include_suggested_filter_tags=True)
        # called per card in a loop (the exact anti-pattern that function's own docstring warns
        # against), query count would scale linearly with batch size instead of staying flat.
        source = SourceFactory()
        tag = TagFactory(name="Foil")  # one shared Tag row - Tag.name is unique, see Tag's own docstring

        def _make_card_with_qualifying_tag_vote():
            card = CardFactory(source=source)
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
            return card

        small_batch = [_make_card_with_qualifying_tag_vote() for _ in range(2)]
        large_batch = small_batch + [_make_card_with_qualifying_tag_vote() for _ in range(6)]

        def _post_and_count_queries(cards):
            with CaptureQueriesContext(connection) as ctx:
                response = client.post(
                    reverse(views.post_cards),
                    {"cardIdentifiers": [c.identifier for c in cards]},
                    content_type="application/json",
                )
                assert response.status_code == 200
                for card in cards:
                    assert response.json()["results"][card.identifier]["suggestedFilterTagNames"] == ["Foil"]
            return len(ctx.captured_queries)

        small_query_count = _post_and_count_queries(small_batch)
        large_query_count = _post_and_count_queries(large_batch)

        assert small_query_count == large_query_count

    def test_suggested_filter_tag_names_query_count_does_not_scale_with_result_size_when_no_votes_exist(
        self, db, client, django_settings
    ):
        # get_suggested_filter_tags_overlay's FIRST query (Card.objects.filter(pk__in=...)) still
        # touches every card in card_ids regardless of whether it has any votes - a real
        # grid-selector page is mostly cards with zero tag votes at all, so this is the common
        # shape, distinct from the "every card has a qualifying vote" test above.
        source = SourceFactory()
        small_batch = [CardFactory(source=source) for _ in range(2)]
        large_batch = small_batch + [CardFactory(source=source) for _ in range(6)]

        def _post_and_count_queries(cards):
            with CaptureQueriesContext(connection) as ctx:
                response = client.post(
                    reverse(views.post_cards),
                    {"cardIdentifiers": [c.identifier for c in cards]},
                    content_type="application/json",
                )
                assert response.status_code == 200
                for card in cards:
                    assert response.json()["results"][card.identifier]["suggestedFilterTagNames"] == []
            return len(ctx.captured_queries)

        small_query_count = _post_and_count_queries(small_batch)
        large_query_count = _post_and_count_queries(large_batch)

        assert small_query_count == large_query_count


class TestPostExploreSearchBulkPayload:
    """
    `POST 2/exploreSearch/` (`views.post_explore_search`) is the second of the two bulk
    Card-payload endpoints this feature targets (issue #184) - it's ES-backed (unlike
    `post_cards`), so this exercises the real `get_search()` -> identifier lookup ->
    `Card.objects....serialise(include_suggested_printing=True)` path end-to-end, rather than
    unit-testing the serialise() call in isolation.

    Deliberately self-contained (own `SourceFactory`/`CardFactory` calls, own
    `search_index --rebuild` call) rather than reusing `test_views.py`'s shared
    `all_sources`/`all_cards`/`populated_database` fixtures or its `Cards`/`Sources` test
    constants. `test_views.py`'s own snapshot assertions are pinned to a fixed factory-sequence
    baseline per test (see that file's `_pin_shared_factory_sequences` fixture), so this module's
    use of the same shared factories can't perturb them - and no snapshot assertion is used here
    at all (explicit field assertions only) regardless.
    """

    @staticmethod
    def _search_settings(source_pk: int) -> dict:
        return {
            "searchTypeSettings": {"fuzzySearch": False, "filterCardbacks": False},
            "sourceSettings": {"sources": [[source_pk, True]]},
            "filterSettings": {
                "minimumDPI": 0,
                "maximumDPI": 1500,
                "maximumSize": 30,
                "languages": [],
                "includesTags": [],
                "excludesTags": [],
                "fullArtOnly": False,
                "borderlessOnly": False,
            },
        }

    def _explore_search(self, client, source, query):
        return client.post(
            reverse(views.post_explore_search),
            {
                "searchSettings": self._search_settings(source.pk),
                "query": query,
                "cardTypes": ["CARD"],
                "sortBy": "dateCreatedDescending",
                "pageSize": 20,
                "pageStart": 0,
            },
            content_type="application/json",
        )

    def test_suggested_canonical_card_and_tag_vote_statuses_present(self, db, client, django_settings, elasticsearch):
        source = SourceFactory()
        card = CardFactory(
            source=source,
            card_type=CardTypes.CARD,
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            tag_vote_statuses={
                "full-art": TagVoteStatus.RESOLVED_APPLY,
                "retro-frame": TagVoteStatus.CONTESTED,
                "sensitive-thing": TagVoteStatus.PENDING_APPROVAL,
            },
        )
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        call_command("search_index", "--rebuild", "-f")

        response = self._explore_search(client, source, card.name)

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        [result] = payload["cards"]
        assert result["identifier"] == card.identifier
        assert result["suggestedCanonicalCard"] is not None
        assert result["suggestedCanonicalCard"]["identifier"] == str(printing.identifier)
        assert result["tagVoteStatuses"] == {"full-art": "resolved", "retro-frame": "suggested"}

    def test_suggested_canonical_card_absent_when_resolved(self, db, client, django_settings, elasticsearch):
        # never redundant with the already-resolved canonicalCard, end-to-end through the
        # real ES-backed endpoint (not just the model-level unit test above).
        source = SourceFactory()
        card = CardFactory(source=source, card_type=CardTypes.CARD, printing_tag_status=PrintingTagStatus.RESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        call_command("search_index", "--rebuild", "-f")

        response = self._explore_search(client, source, card.name)

        assert response.status_code == 200
        [result] = response.json()["cards"]
        assert result["suggestedCanonicalCard"] is None
