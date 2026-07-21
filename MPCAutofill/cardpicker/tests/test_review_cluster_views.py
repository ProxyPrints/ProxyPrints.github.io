"""
Tests for the review-cluster API surface (issue #262, docs/features/moderation.md):
2/reviewClusters/, 2/reviewClusterDetail/, 2/confirmReviewCluster/. See
cardpicker.review_clusters for the clustering itself (tested separately in
test_review_clusters.py) - this file is about auth gating, pagination, request/response shape,
and the batch-confirm vote-casting/idempotency/member-mismatch behaviour.
"""

import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.local_calculate_verdicts import (
    SLOW_PATH_ANONYMOUS_ID,
    SLOW_PATH_TO_REVIEW_REASON,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_review_card(*, content_phash=None, symbol_phash=None, legal_line_raw_text="", name=None):
    card = CardFactory(content_phash=content_phash, **({"name": name} if name else {}))
    CardScanLog.objects.create(card=card, anonymous_id=SLOW_PATH_ANONYMOUS_ID, skip_reason=SLOW_PATH_TO_REVIEW_REASON)
    if content_phash is not None:
        ImageEvidenceFactory(
            card=card,
            content_hash=content_phash,
            symbol_phash=symbol_phash,
            legal_line_raw_text=legal_line_raw_text,
        )
    return card


def make_pair_cluster(content_phash: int = 1):
    """Two cards sharing an exact content_phash - the smallest possible real cluster. Returns
    (a, b, cluster_id) - cluster_id is whichever of the two has the lower pk, matching
    cardpicker.review_clusters' own "lowest-card-id member" convention."""
    a = make_review_card(content_phash=content_phash)
    b = make_review_card(content_phash=content_phash)
    cluster_id = a.identifier if a.pk < b.pk else b.identifier
    return a, b, cluster_id


class TestPostReviewClusterList:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def fetch(client, page: int = 1):
        return client.post(reverse(views.post_review_cluster_list), {"page": page}, content_type="application/json")

    def test_anonymous_is_403(self, client):
        response = self.fetch(client)
        assert response.status_code == 403
        assert response.json()["name"] == "Moderator access required"

    def test_authenticated_non_moderator_is_403(self, client, plain_user):
        client.force_login(plain_user)
        assert self.fetch(client).status_code == 403

    def test_moderator_sees_clusters_sorted_by_size_descending(self, client, moderator_user):
        for _ in range(3):
            make_review_card(content_phash=1)
        for _ in range(2):
            make_review_card(content_phash=2)
        make_review_card(content_phash=3)  # singleton - never listed

        client.force_login(moderator_user)
        body = self.fetch(client).json()
        assert body["hits"] == 2
        assert [item["size"] for item in body["items"]] == [3, 2]

    def test_cluster_item_shape(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster(content_phash=123)
        client.force_login(moderator_user)
        body = self.fetch(client).json()
        (item,) = body["items"]
        assert item["size"] == 2
        assert {m["identifier"] for m in item["members"]} == {a.identifier, b.identifier}
        assert item["signals"] == [{"signalType": "content_phash", "value": "123", "memberCount": 2}]
        assert item["clusterId"] in {a.identifier, b.identifier}

    def test_invalid_page_is_a_bad_request(self, client, moderator_user):
        make_pair_cluster()
        client.force_login(moderator_user)
        response = self.fetch(client, page=99)
        assert response.status_code == 400


class TestPostReviewClusterDetail:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def fetch(client, cluster_id: str):
        return client.post(
            reverse(views.post_review_cluster_detail),
            {"clusterId": cluster_id},
            content_type="application/json",
        )

    def test_anonymous_is_403(self, client):
        assert self.fetch(client, "whatever").status_code == 403

    def test_authenticated_non_moderator_is_403(self, client, plain_user):
        client.force_login(plain_user)
        assert self.fetch(client, "whatever").status_code == 403

    def test_moderator_sees_full_member_list(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster(content_phash=7)
        client.force_login(moderator_user)
        response = self.fetch(client, cluster_id)
        assert response.status_code == 200
        cluster = response.json()["cluster"]
        assert cluster["clusterId"] == cluster_id
        assert {m["identifier"] for m in cluster["members"]} == {a.identifier, b.identifier}

    def test_unknown_cluster_id_is_a_bad_request(self, client, moderator_user):
        client.force_login(moderator_user)
        assert self.fetch(client, "does-not-exist").status_code == 400


class TestPostConfirmReviewCluster:
    @pytest.fixture(autouse=True)
    def autouse_django_settings(self, django_settings):
        pass

    @staticmethod
    def fetch(client, cluster_id: str, member_identifiers: list):
        return client.post(
            reverse(views.post_confirm_review_cluster),
            {"clusterId": cluster_id, "memberIdentifiers": member_identifiers},
            content_type="application/json",
        )

    def test_anonymous_is_403(self, client):
        assert self.fetch(client, "whatever", ["x"]).status_code == 403

    def test_authenticated_non_moderator_is_403(self, client, plain_user):
        client.force_login(plain_user)
        assert self.fetch(client, "whatever", ["x"]).status_code == 403

    def test_empty_member_list_is_a_bad_request(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster()
        client.force_login(moderator_user)
        response = self.fetch(client, cluster_id, [])
        assert response.status_code == 400

    def test_unknown_cluster_id_is_a_bad_request(self, client, moderator_user):
        client.force_login(moderator_user)
        response = self.fetch(client, "does-not-exist", ["x"])
        assert response.status_code == 400

    def test_a_single_moderator_vote_does_not_shortcut_default_consensus_thresholds(self, client, moderator_user):
        # under the DEFAULT thresholds (PRINTING_TAG_MIN_VOTES=2), one moderator's own vote
        # (VoteSource.USER, weight 1.0, no privilege boost - printing consensus, unlike tag
        # consensus, never consults moderator privilege) is not enough to resolve a card by
        # itself - it contributes exactly one ordinary human vote, same as any other voter's.
        a, b, cluster_id = make_pair_cluster(content_phash=42)
        client.force_login(moderator_user)
        response = self.fetch(client, cluster_id, [a.identifier, b.identifier])
        assert response.status_code == 200
        for card in (a, b):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
            assert CardPrintingTag.objects.get(card=card).is_no_match is True

    def test_confirm_casts_no_match_votes_and_resolves(self, client, moderator_user, settings):
        # normal consensus rules, no shortcut for a moderator's single vote (issue #262 item 2's
        # own "no shortcuts" ask) - PRINTING_TAG_MIN_VOTES defaults to 2, so one USER-weight
        # (1.0) vote alone would otherwise leave the card UNRESOLVED; lowering it here isolates
        # what THIS view's own wiring does (same convention test_tag_votes.py/
        # test_vote_queue_views.py etc. already use to test single-vote resolution).
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        a, b, cluster_id = make_pair_cluster(content_phash=42)

        client.force_login(moderator_user)
        response = self.fetch(client, cluster_id, [a.identifier, b.identifier])
        assert response.status_code == 200
        body = response.json()
        assert body["clusterId"] == cluster_id
        assert set(body["confirmedIdentifiers"]) == {a.identifier, b.identifier}
        assert body["votesCast"] == 2

        for card in (a, b):
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.NO_MATCH
            vote = CardPrintingTag.objects.get(card=card)
            assert vote.is_no_match is True
            assert vote.source == VoteSource.USER
            assert vote.user == moderator_user
            assert vote.vote_surface == "review_cluster_confirm"

    def test_confirm_is_idempotent_per_user_and_card(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster(content_phash=42)
        client.force_login(moderator_user)

        first = self.fetch(client, cluster_id, [a.identifier, b.identifier])
        assert first.status_code == 200

        # a second identical confirm (e.g. a retried request) must not create a second vote row
        # per card for this same moderator.
        second = self.fetch(client, cluster_id, [a.identifier, b.identifier])
        assert second.status_code == 200
        assert CardPrintingTag.objects.filter(card=a).count() == 1
        assert CardPrintingTag.objects.filter(card=b).count() == 1

    def test_partial_confirm_only_votes_for_the_submitted_subset(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster(content_phash=42)
        client.force_login(moderator_user)

        response = self.fetch(client, cluster_id, [a.identifier])
        assert response.status_code == 200
        assert CardPrintingTag.objects.filter(card=a).exists()
        assert not CardPrintingTag.objects.filter(card=b).exists()

    def test_identifier_not_in_the_cluster_is_rejected_whole(self, client, moderator_user):
        a, b, cluster_id = make_pair_cluster(content_phash=42)
        outsider = make_review_card(content_phash=999)
        client.force_login(moderator_user)

        response = self.fetch(client, cluster_id, [a.identifier, outsider.identifier])
        assert response.status_code == 400
        # rejected as a whole - no vote cast for the valid member either.
        assert not CardPrintingTag.objects.filter(card=a).exists()

    def test_confirm_invalidates_the_list_cache(self, client, moderator_user, settings):
        settings.PRINTING_TAG_MIN_VOTES = 1
        settings.PRINTING_TAG_MIN_SHARE = 0.5
        a, b, cluster_id = make_pair_cluster(content_phash=42)
        client.force_login(moderator_user)

        list_response = client.post(
            reverse(views.post_review_cluster_list), {"page": 1}, content_type="application/json"
        )
        assert list_response.json()["hits"] == 1

        self.fetch(client, cluster_id, [a.identifier, b.identifier])

        list_response_after = client.post(
            reverse(views.post_review_cluster_list), {"page": 1}, content_type="application/json"
        )
        # both cards are now resolved (NO_MATCH) - the cluster no longer exists at all.
        assert list_response_after.json()["hits"] == 0

    def test_different_moderators_each_get_their_own_vote(self, client, moderator_user, plain_user, moderators_group):
        a, b, cluster_id = make_pair_cluster(content_phash=55)
        second_moderator = plain_user
        second_moderator.groups.add(moderators_group)

        client.force_login(moderator_user)
        self.fetch(client, cluster_id, [a.identifier])
        client.force_login(second_moderator)
        self.fetch(client, cluster_id, [b.identifier])

        assert CardPrintingTag.objects.filter(card=a, user=moderator_user).exists()
        assert CardPrintingTag.objects.filter(card=b, user=second_moderator).exists()
