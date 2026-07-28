"""
Tests for POST 2/submitPrintingTagVote/ — cast/update/retract a user vote on whether
a descriptor Tag applies to a CanonicalCard (Scryfall printing). Commit 3 of PR #497.
"""

import json
import uuid

import pytest

from django.test import Client

from cardpicker.models import PrintingTagVote, VotePolarity, VoteSource
from cardpicker.tests.factories import CanonicalCardFactory, TagFactory

_URL = "/2/submitPrintingTagVote/"
_ANON_ID = "test-anon-id-abc123"


def _post(client: Client, payload: dict) -> object:
    return client.post(
        _URL,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_ORIGIN="http://localhost",
    )


@pytest.fixture()
def printing(db):
    return CanonicalCardFactory(identifier=uuid.uuid4(), is_default=True)


@pytest.fixture()
def tag(db):
    return TagFactory(name="external-ip")


class TestSubmitPrintingTagVote:
    def test_apply_creates_vote(self, client, printing, tag):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.APPLY,
            },
        )
        assert resp.status_code == 200
        vote = PrintingTagVote.objects.get(printing=printing, tag=tag, anonymous_id=_ANON_ID)
        assert vote.polarity == VotePolarity.APPLY
        assert vote.source == VoteSource.USER

    def test_not_applicable_creates_vote(self, client, printing, tag):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.NOT_APPLICABLE,
            },
        )
        assert resp.status_code == 200
        vote = PrintingTagVote.objects.get(printing=printing, tag=tag, anonymous_id=_ANON_ID)
        assert vote.polarity == VotePolarity.NOT_APPLICABLE

    def test_update_or_create_changes_existing_vote(self, client, printing, tag):
        _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.APPLY,
            },
        )
        _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.NOT_APPLICABLE,
            },
        )
        # still one row, polarity flipped
        assert PrintingTagVote.objects.filter(printing=printing, tag=tag, anonymous_id=_ANON_ID).count() == 1
        assert (
            PrintingTagVote.objects.get(printing=printing, tag=tag, anonymous_id=_ANON_ID).polarity
            == VotePolarity.NOT_APPLICABLE
        )

    def test_retract_deletes_existing_vote(self, client, printing, tag):
        _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.APPLY,
            },
        )
        assert PrintingTagVote.objects.filter(printing=printing, tag=tag).exists()

        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": 0,  # RETRACT
            },
        )
        assert resp.status_code == 200
        assert not PrintingTagVote.objects.filter(printing=printing, tag=tag).exists()

    def test_retract_with_no_existing_vote_is_noop(self, client, printing, tag):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": 0,
            },
        )
        assert resp.status_code == 200
        assert PrintingTagVote.objects.count() == 0

    def test_unknown_printing_returns_400(self, client, tag, db):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(uuid.uuid4()),
                "tagName": tag.name,
                "polarity": VotePolarity.APPLY,
            },
        )
        assert resp.status_code == 400

    def test_unknown_tag_returns_400(self, client, printing):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": "nonexistent-tag",
                "polarity": VotePolarity.APPLY,
            },
        )
        assert resp.status_code == 400

    def test_invalid_polarity_returns_400(self, client, printing, tag):
        resp = _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": 99,
            },
        )
        assert resp.status_code == 400

    def test_get_method_returns_400(self, client, db):
        resp = client.get(_URL, HTTP_ORIGIN="http://localhost")
        assert resp.status_code == 400

    def test_vote_surface_is_persisted(self, client, printing, tag):
        _post(
            client,
            {
                "anonymousId": _ANON_ID,
                "printingIdentifier": str(printing.identifier),
                "tagName": tag.name,
                "polarity": VotePolarity.APPLY,
                "voteSurface": "printing-tag-picker",
            },
        )
        vote = PrintingTagVote.objects.get(printing=printing, tag=tag, anonymous_id=_ANON_ID)
        assert vote.vote_surface == "printing-tag-picker"
