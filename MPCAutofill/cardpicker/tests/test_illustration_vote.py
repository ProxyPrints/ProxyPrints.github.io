import uuid

import pytest

from django.core.cache import cache
from django.urls import reverse

from cardpicker import illustration_vote, views
from cardpicker.illustration_vote import (
    artist_name_indicates_combined_credit,
    cast_illustration_rejection,
    cast_illustration_vote,
    printings_for_card_and_illustration,
)
from cardpicker.models import (
    CardArtistVote,
    CardIllustrationRejection,
    CardIllustrationVote,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardArtistVoteFactory,
    CardFactory,
)


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    # django-ratelimit's counters live in Django's cache, which isn't reset between tests by
    # default - clear it so one test's submissions can't affect another's rate limit (same
    # pattern as test_printing_tags_views.py / test_artist_votes.py).
    cache.clear()
    yield
    cache.clear()


def _printing_with_illustration(name: str, illustration_id: "uuid.UUID | None", artist=None):
    printing = CanonicalCardFactory(name=name, artist=artist) if artist else CanonicalCardFactory(name=name)
    CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
    return printing


class TestArtistNameIndicatesCombinedCredit:
    def test_ampersand_indicates_combined_credit(self, db):
        assert artist_name_indicates_combined_credit("Rebecca Guay & John Avon") is True

    def test_plain_name_does_not_abstain(self, db):
        assert artist_name_indicates_combined_credit("Rebecca Guay") is False

    def test_comma_age_credit_does_not_abstain(self, db):
        # issue #503's census: ', ' alone is a false-positive-only pattern (Unfinity "age N"
        # credits, Jr./Inc. suffixes) - must NOT trigger an abstain.
        assert artist_name_indicates_combined_credit("Aliya, age 5½") is False

    def test_comma_suffix_name_does_not_abstain(self, db):
        assert artist_name_indicates_combined_credit("Ken Meyer, Jr.") is False

    def test_combined_credit_with_a_comma_suffix_still_abstains(self, db):
        # Some combined credits contain BOTH '&' and a comma - '&' alone must still catch this.
        assert artist_name_indicates_combined_credit("Anthony S. Waters & Edward P. Beard, Jr.") is True


class TestPrintingsForCardAndIllustration:
    def test_returns_the_single_matching_printing(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        printing = _printing_with_illustration("Brainstorm", illustration_id)

        result = printings_for_card_and_illustration(card, illustration_id)

        assert [p.pk for p in result] == [printing.pk]

    def test_returns_every_printing_sharing_the_illustration(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        printing_a = _printing_with_illustration("Brainstorm", illustration_id)
        printing_b = _printing_with_illustration("Brainstorm", illustration_id)
        _printing_with_illustration("Brainstorm", uuid.uuid4())  # different illustration - excluded

        result = printings_for_card_and_illustration(card, illustration_id)

        assert {p.pk for p in result} == {printing_a.pk, printing_b.pk}

    def test_scoped_to_this_cards_own_candidates_not_the_whole_catalogue(self, db):
        # Same illustration_id reused (contrived) across two differently-named cards - the
        # narrowing must not leak across card identities.
        illustration_id = uuid.uuid4()
        brainstorm_card = CardFactory(name="Brainstorm")
        brainstorm_printing = _printing_with_illustration("Brainstorm", illustration_id)
        _printing_with_illustration("Opt", illustration_id)

        result = printings_for_card_and_illustration(brainstorm_card, illustration_id)

        assert [p.pk for p in result] == [brainstorm_printing.pk]

    def test_no_match_returns_empty_list(self, db):
        card = CardFactory(name="Brainstorm")
        _printing_with_illustration("Brainstorm", uuid.uuid4())

        assert printings_for_card_and_illustration(card, uuid.uuid4()) == []


class TestCastIllustrationVote:
    def test_1_1_group_casts_a_printing_vote(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        printing = _printing_with_illustration("Brainstorm", illustration_id)

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.printing_vote_cast is True
        assert outcome.resolved_printing == printing
        tag = CardPrintingTag.objects.get(card=card, anonymous_id="voter-1")
        assert tag.printing == printing
        assert tag.is_no_match is False
        # The voter answered a question about artwork, not printing - this write is a
        # DEDUCTION-weight inference, never full human weight, and carries its own vote_surface
        # so it stays distinguishable from a genuine printing-confirmation answer.
        assert tag.source == VoteSource.DEDUCTION
        assert tag.vote_surface == illustration_vote.DERIVED_PRINTING_VOTE_SURFACE

    def test_existing_printing_vote_is_left_untouched(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        _printing_with_illustration("Brainstorm", illustration_id)
        explicit_printing = _printing_with_illustration("Fireball", uuid.uuid4())
        existing_tag = CardPrintingTag.objects.create(
            card=card,
            printing=explicit_printing,
            is_no_match=False,
            anonymous_id="voter-1",
            source=VoteSource.USER,
            vote_surface="question-feed",
        )

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.printing_vote_cast is False
        assert outcome.resolved_printing is None
        tags = list(CardPrintingTag.objects.filter(card=card, anonymous_id="voter-1"))
        assert len(tags) == 1
        assert tags[0].pk == existing_tag.pk
        assert tags[0].printing == explicit_printing
        assert tags[0].source == VoteSource.USER
        assert tags[0].vote_surface == "question-feed"

    def test_two_derived_printing_votes_do_not_resolve_the_printing(self, db):
        # At PRINTING_TAG_MACHINE_WEIGHT (0.5) each, two DEDUCTION votes alone can never clear
        # the human-backed gate - this is the user-visible property the fix protects.
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        _printing_with_illustration("Brainstorm", illustration_id)

        cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )
        cast_illustration_vote(
            card=card,
            anonymous_id="voter-2",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert CardPrintingTag.objects.filter(card=card, source=VoteSource.DEDUCTION).count() == 2
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
        assert card.inferred_canonical_card is None

    def test_n_gt_1_group_casts_nothing_on_the_printing_channel(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        artist = CanonicalArtistFactory(name="Shared Artist")
        _printing_with_illustration("Brainstorm", illustration_id, artist=artist)
        _printing_with_illustration("Brainstorm", illustration_id, artist=artist)

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.printing_vote_cast is False
        assert outcome.resolved_printing is None
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        # the artist channel is independent of the printing-count outcome - both printings
        # share one artist, so the derivation still fires.
        assert outcome.artist_vote_cast is True

    def test_artist_vote_derived_when_absent(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        _printing_with_illustration("Brainstorm", illustration_id, artist=artist)

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.artist_vote_cast is True
        assert outcome.artist_abstain_reason is None
        vote = CardArtistVote.objects.get(card=card, anonymous_id="voter-1")
        assert vote.artist == artist
        assert vote.source == VoteSource.USER
        assert vote.vote_surface == illustration_vote.DERIVED_ARTIST_VOTE_SURFACE

    def test_existing_explicit_artist_vote_is_left_untouched(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        derived_artist = CanonicalArtistFactory(name="Rebecca Guay")
        explicit_artist = CanonicalArtistFactory(name="A Different Artist")
        _printing_with_illustration("Brainstorm", illustration_id, artist=derived_artist)
        existing_vote = CardArtistVoteFactory(
            card=card, artist=explicit_artist, anonymous_id="voter-1", source=VoteSource.USER
        )

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.artist_vote_cast is False
        assert outcome.artist_abstain_reason == "existing_explicit_vote"
        votes = list(CardArtistVote.objects.filter(card=card, anonymous_id="voter-1"))
        assert len(votes) == 1
        assert votes[0].pk == existing_vote.pk
        assert votes[0].artist == explicit_artist

    def test_multi_artist_credit_abstains_from_the_artist_vote(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        combined_artist = CanonicalArtistFactory(name="Rebecca Guay & John Avon")
        printing = _printing_with_illustration("Brainstorm", illustration_id, artist=combined_artist)

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.artist_vote_cast is False
        assert outcome.artist_abstain_reason == "combined_credit"
        assert CardArtistVote.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        # the printing channel is unaffected by the artist abstain - still 1:1.
        assert outcome.printing_vote_cast is True
        assert outcome.resolved_printing == printing

    def test_comma_suffix_artist_does_not_abstain(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        artist = CanonicalArtistFactory(name="Ken Meyer, Jr.")
        _printing_with_illustration("Brainstorm", illustration_id, artist=artist)

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.artist_vote_cast is True
        assert outcome.artist_abstain_reason is None

    def test_no_matching_printing_abstains_with_a_distinct_reason(self, db):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        _printing_with_illustration("Brainstorm", uuid.uuid4())  # unrelated illustration

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.printing_vote_cast is False
        assert outcome.artist_vote_cast is False
        assert outcome.artist_abstain_reason == "no_printing_found"
        assert CardIllustrationVote.objects.get(card=card, anonymous_id="voter-1").illustration_id == illustration_id

    def test_revoting_a_different_illustration_updates_the_single_row(self, db):
        card = CardFactory(name="Brainstorm")
        illustration_a = uuid.uuid4()
        illustration_b = uuid.uuid4()
        _printing_with_illustration("Brainstorm", illustration_a)
        _printing_with_illustration("Brainstorm", illustration_b)

        cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_a,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )
        cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_b,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        rows = list(CardIllustrationVote.objects.filter(card=card, anonymous_id="voter-1"))
        assert len(rows) == 1
        assert rows[0].illustration_id == illustration_b

    def test_is_unknown_path(self, db):
        card = CardFactory(name="Brainstorm")

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=None,
            is_unknown=True,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.is_unknown is True
        assert outcome.printing_vote_cast is False
        assert outcome.artist_vote_cast is False
        row = CardIllustrationVote.objects.get(card=card, anonymous_id="voter-1")
        assert row.is_unknown is True
        assert row.illustration_id is None
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        assert CardArtistVote.objects.filter(card=card, anonymous_id="voter-1").count() == 0

    def test_transactionality_nothing_persists_if_any_write_fails(self, db, monkeypatch):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        artist = CanonicalArtistFactory(name="Rebecca Guay")
        _printing_with_illustration("Brainstorm", illustration_id, artist=artist)

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated failure after the artist vote write")

        # Fails after CardIllustrationVote + CardPrintingTag + CardArtistVote have all been
        # written to the (uncommitted) transaction - if the atomic block works, none of the
        # three persist.
        monkeypatch.setattr(illustration_vote, "resolve_and_persist_artist", _boom)

        with pytest.raises(RuntimeError):
            cast_illustration_vote(
                card=card,
                anonymous_id="voter-1",
                illustration_id=illustration_id,
                is_unknown=False,
                user=None,
                vote_surface="question-feed",
            )

        assert CardIllustrationVote.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        assert CardArtistVote.objects.filter(card=card, anonymous_id="voter-1").count() == 0


class TestPostSubmitIllustrationVote:
    def test_1_1_end_to_end(self, client, django_settings):
        illustration_id = uuid.uuid4()
        card = CardFactory(name="Brainstorm")
        printing = _printing_with_illustration("Brainstorm", illustration_id)

        response = client.post(
            reverse(views.post_submit_illustration_vote),
            {
                "identifier": card.identifier,
                "anonymousId": "voter-1",
                "illustrationId": str(illustration_id),
                "isUnknown": False,
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["printingVoteCast"] is True
        assert body["resolvedPrinting"]["identifier"] == str(printing.identifier)
        assert body["artistVoteCast"] is True
        assert body["isUnknown"] is False
        assert body["illustrationId"] == str(illustration_id)

    def test_is_unknown_end_to_end(self, client, django_settings):
        card = CardFactory(name="Brainstorm")

        response = client.post(
            reverse(views.post_submit_illustration_vote),
            {"identifier": card.identifier, "anonymousId": "voter-1", "isUnknown": True},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["isUnknown"] is True
        assert body["printingVoteCast"] is False
        assert body["artistVoteCast"] is False
        assert CardIllustrationVote.objects.get(card=card, anonymous_id="voter-1").is_unknown is True

    def test_missing_illustration_id_when_not_unknown_is_a_bad_request(self, client, django_settings):
        card = CardFactory(name="Brainstorm")

        response = client.post(
            reverse(views.post_submit_illustration_vote),
            {"identifier": card.identifier, "anonymousId": "voter-1", "isUnknown": False},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_invalid_uuid_is_a_bad_request(self, client, django_settings):
        card = CardFactory(name="Brainstorm")

        response = client.post(
            reverse(views.post_submit_illustration_vote),
            {
                "identifier": card.identifier,
                "anonymousId": "voter-1",
                "illustrationId": "not-a-uuid",
                "isUnknown": False,
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_illustration_vote),
            {
                "identifier": "does-not-exist",
                "anonymousId": "voter-1",
                "illustrationId": str(uuid.uuid4()),
                "isUnknown": False,
            },
            content_type="application/json",
        )

        assert response.status_code == 400


class TestCastIllustrationRejection:
    def test_a_voter_can_reject_several_artworks_for_one_card(self, db):
        card = CardFactory(name="Brainstorm")
        first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=first, user=None, vote_surface=None
        )
        cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=second, user=None, vote_surface=None
        )
        cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=third, user=None, vote_surface=None
        )

        rejected = set(
            CardIllustrationRejection.objects.filter(card=card, anonymous_id="voter-1").values_list(
                "illustration_id", flat=True
            )
        )
        assert rejected == {first, second, third}

    def test_a_rejection_does_not_consume_the_affirmation_slot(self, db):
        # The whole point of the separate model (CardIllustrationRejection's own docstring):
        # rejecting three artworks must not block affirming a fourth, distinct one, through
        # CardIllustrationVote's own unconditional (card, anonymous_id) slot.
        card = CardFactory(name="Brainstorm")
        rejected_ids = [uuid.uuid4() for _ in range(3)]
        affirmed_id = uuid.uuid4()

        for illustration_id in rejected_ids:
            cast_illustration_rejection(
                card=card, anonymous_id="voter-1", illustration_id=illustration_id, user=None, vote_surface=None
            )
        cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=affirmed_id,
            is_unknown=False,
            user=None,
            vote_surface=None,
        )

        assert CardIllustrationRejection.objects.filter(card=card, anonymous_id="voter-1").count() == 3
        affirmation = CardIllustrationVote.objects.get(card=card, anonymous_id="voter-1")
        assert affirmation.illustration_id == affirmed_id

    def test_a_second_reject_of_the_same_artwork_updates_rather_than_duplicates(self, db):
        card = CardFactory(name="Brainstorm")
        illustration_id = uuid.uuid4()

        first = cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=illustration_id, user=None, vote_surface="a"
        )
        second = cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=illustration_id, user=None, vote_surface="b"
        )

        assert first.pk == second.pk
        assert CardIllustrationRejection.objects.filter(card=card, anonymous_id="voter-1").count() == 1
        assert CardIllustrationRejection.objects.get(pk=first.pk).vote_surface == "b"

    def test_machine_and_human_rejections_of_the_same_artwork_are_two_distinct_rows(self, db):
        # Different anonymous_ids are different agents - both rows persist, and
        # eliminated_illustration_ids (tested separately) is what pools/weighs them together.
        card = CardFactory(name="Brainstorm")
        illustration_id = uuid.uuid4()

        CardIllustrationRejection.objects.create(
            card=card,
            illustration_id=illustration_id,
            anonymous_id="stage-d-illustration-v2",
            source=VoteSource.DEDUCTION,
        )
        cast_illustration_rejection(
            card=card, anonymous_id="voter-1", illustration_id=illustration_id, user=None, vote_surface=None
        )

        assert CardIllustrationRejection.objects.filter(card=card, illustration_id=illustration_id).count() == 2


class TestPostSubmitIllustrationRejection:
    def test_end_to_end(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        illustration_id = uuid.uuid4()

        response = client.post(
            reverse(views.post_submit_illustration_rejection),
            {
                "identifier": card.identifier,
                "anonymousId": "voter-1",
                "illustrationId": str(illustration_id),
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["illustrationId"] == str(illustration_id)
        rejection = CardIllustrationRejection.objects.get(card=card, anonymous_id="voter-1")
        assert rejection.illustration_id == illustration_id
        assert rejection.source == VoteSource.USER

    def test_does_not_touch_the_printing_or_artist_channels(self, client, django_settings):
        card = CardFactory(name="Brainstorm")
        illustration_id = uuid.uuid4()

        client.post(
            reverse(views.post_submit_illustration_rejection),
            {"identifier": card.identifier, "anonymousId": "voter-1", "illustrationId": str(illustration_id)},
            content_type="application/json",
        )

        assert not CardPrintingTag.objects.filter(card=card).exists()
        assert not CardArtistVote.objects.filter(card=card).exists()
        assert not CardIllustrationVote.objects.filter(card=card).exists()

    def test_missing_illustration_id_is_a_bad_request(self, client, django_settings):
        card = CardFactory(name="Brainstorm")

        response = client.post(
            reverse(views.post_submit_illustration_rejection),
            {"identifier": card.identifier, "anonymousId": "voter-1"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_invalid_uuid_is_a_bad_request(self, client, django_settings):
        card = CardFactory(name="Brainstorm")

        response = client.post(
            reverse(views.post_submit_illustration_rejection),
            {"identifier": card.identifier, "anonymousId": "voter-1", "illustrationId": "not-a-uuid"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_unknown_card_identifier_is_a_bad_request(self, client, django_settings):
        response = client.post(
            reverse(views.post_submit_illustration_rejection),
            {"identifier": "does-not-exist", "anonymousId": "voter-1", "illustrationId": str(uuid.uuid4())},
            content_type="application/json",
        )

        assert response.status_code == 400
