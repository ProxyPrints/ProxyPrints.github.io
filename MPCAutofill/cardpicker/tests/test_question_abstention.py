import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import views
from cardpicker.models import CardQuestionAbstention
from cardpicker.tests.factories import CardFactory


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


class TestPostSubmitQuestionAbstention:
    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_question_abstention),
            {"identifier": "does-not-exist", "anonymousId": "anon-1", "questionType": "confirm_suggestion"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_records_exactly_one_abstention_with_the_right_voter_card_and_question_type(self, client, django_settings):
        card = CardFactory()

        response = client.post(
            reverse(views.post_submit_question_abstention),
            {"identifier": card.identifier, "anonymousId": "anon-1", "questionType": "confirm_suggestion"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["recorded"] is True
        assert CardQuestionAbstention.objects.count() == 1
        abstention = CardQuestionAbstention.objects.get()
        assert abstention.card_id == card.pk
        assert abstention.anonymous_id == "anon-1"
        assert abstention.question_type == "confirm_suggestion"

    def test_repeat_taps_from_the_same_voter_record_the_fact_once(self, client, django_settings):
        card = CardFactory()
        body = {"identifier": card.identifier, "anonymousId": "anon-1", "questionType": "identify_printing"}

        for _ in range(3):
            response = client.post(
                reverse(views.post_submit_question_abstention), body, content_type="application/json"
            )
            assert response.status_code == 200

        assert CardQuestionAbstention.objects.count() == 1

    def test_different_question_types_on_the_same_card_and_voter_record_separately(self, client, django_settings):
        card = CardFactory()

        for question_type in ("confirm_suggestion", "identify_printing"):
            response = client.post(
                reverse(views.post_submit_question_abstention),
                {"identifier": card.identifier, "anonymousId": "anon-1", "questionType": question_type},
                content_type="application/json",
            )
            assert response.status_code == 200

        assert CardQuestionAbstention.objects.count() == 2

    def test_different_voters_on_the_same_card_and_question_type_record_separately(self, client, django_settings):
        card = CardFactory()

        for anonymous_id in ("anon-1", "anon-2"):
            response = client.post(
                reverse(views.post_submit_question_abstention),
                {"identifier": card.identifier, "anonymousId": anonymous_id, "questionType": "confirm_suggestion"},
                content_type="application/json",
            )
            assert response.status_code == 200

        assert CardQuestionAbstention.objects.count() == 2

    def test_skip_writes_no_abstention_row(self, db):
        # Documents the "Skip" side of the contract at the model layer: nothing in this codebase
        # ever calls CardQuestionAbstention.objects.create/get_or_create from a skip path (the
        # frontend's `skip` handler never calls `2/submitQuestionAbstention/` at all - see
        # QuestionFeed.tsx), so an untouched card simply has zero rows here.
        CardFactory()

        assert CardQuestionAbstention.objects.count() == 0

    def test_abstention_is_queryable_by_voter_card_and_question_type(self, db):
        # The shape a future exclusion query (issue #713) needs: "has this anonymous_id already
        # abstained on this card for this question_type" as a single indexed equality lookup.
        card = CardFactory()
        CardQuestionAbstention.objects.get_or_create(
            card=card, anonymous_id="anon-1", question_type="confirm_suggestion"
        )

        assert CardQuestionAbstention.objects.filter(
            card_id=card.pk, anonymous_id="anon-1", question_type="confirm_suggestion"
        ).exists()
        assert not CardQuestionAbstention.objects.filter(
            card_id=card.pk, anonymous_id="anon-1", question_type="identify_printing"
        ).exists()
        assert not CardQuestionAbstention.objects.filter(
            card_id=card.pk, anonymous_id="anon-2", question_type="confirm_suggestion"
        ).exists()
