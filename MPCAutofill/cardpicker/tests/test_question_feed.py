from django.urls import reverse

from cardpicker import views
from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardScanLog,
    PrintingTagStatus,
    QuestionFeedServedLog,
    QuestionFeedServedPool,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.question_feed import (
    _tier_1_confirm_suggestion,
    get_next_question_feed_item,
    get_remaining_estimate,
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
    TagFactory,
)


def make_ai_suggested_card(anonymous_id: str = "ai-bot") -> tuple:
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=anonymous_id)
    return card, printing


def make_pending_pair(tag_name: str = "sensitive-tag") -> tuple:
    # printing/artist already resolved so this card would only ever match the old tier-3
    # moderation candidate set (now removed from this feed entirely - see
    # test_pending_approval_pairs_never_appear_in_the_feed below) - isolates it from tiers 2/4,
    # which would otherwise also match this card via its (irrelevant, default-unresolved)
    # printing/artist status
    card = CardFactory(
        tags=[], printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
    )
    tag = TagFactory(name=tag_name, moderation_class=TagModerationClass.SENSITIVE)
    for index in range(2):
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id=f"crowd-{index}")
    resolve_and_persist_tag_votes(card)
    card.refresh_from_db()
    return card, tag


class TestGetNextQuestionFeedItem:
    def test_no_data_returns_none(self, db):
        assert get_next_question_feed_item("anon-1") is None

    def test_tier_1_returns_confirm_suggestion_with_the_ai_suggested_printing(self, db):
        card, printing = make_ai_suggested_card()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier
        assert item.suggestedPrinting.identifier == str(printing.identifier)

    def test_tier_1_excludes_cards_this_voter_already_voted_on(self, db):
        make_ai_suggested_card(anonymous_id="ai-bot")
        # the only tier-1 candidate has this same anonymous_id's own vote already
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        # falls through past the excluded tier-1 card - no other data exists, so None
        assert item is None or item.card.identifier != card.identifier

    def test_tier_1_excludes_a_confirm_suggestion_card_after_a_no_match_vote(self, db):
        """
        Owner-reported "dedup doesn't work" bug (docs/features/printing-tags.md's questionFeed
        section): a single-candidate card's confirm_suggestion question kept resurfacing to the
        same voter after they answered "No". Root cause traced to the frontend
        (QuestionFeed.tsx's rejectSuggestion): the singleton "No" path never actually called
        `submitPrintingTag`, so no `CardPrintingTag` row ever existed for that (card,
        anonymous_id) pair - this exclusion query below had nothing to match against, and the
        exact same question came back on the next feed fetch. This test proves the backend half
        was never the problem: an `is_no_match=True` vote excludes a card from tier 1 for that
        voter exactly like a real positive vote does (see
        test_tier_1_excludes_cards_this_voter_already_voted_on above) - once the frontend fix
        actually writes this row the moment "No" is tapped, the resurfacing stops. Scoped to
        `_tier_1_confirm_suggestion` directly (not the full `get_next_question_feed_item` union)
        because this card - like any fresh `CardFactory` row - also defaults to an unresolved
        artist question, and the card legitimately reappearing there afterwards is fine per the
        task's own semantics ("falls out of the confirmable pool or to a different question
        type") - it's only a *repeat* confirm_suggestion question that's the bug.
        """
        card, _ = make_ai_suggested_card(anonymous_id="ai-bot")
        CardPrintingTagFactory(
            card=card, printing=None, is_no_match=True, source=VoteSource.USER, anonymous_id="anon-1"
        )

        item = _tier_1_confirm_suggestion("anon-1")

        assert item is None or item.card.identifier != card.identifier

    def test_a_second_voters_own_exclusion_does_not_affect_a_first_voter(self, db):
        card, _ = make_ai_suggested_card()

        item_for_second_voter = get_next_question_feed_item("anon-2")

        assert item_for_second_voter is not None
        assert item_for_second_voter.card.identifier == card.identifier

    def test_tier_2_contested_printing_wins_over_tier_4_fresh_unresolved(self, db):
        # tier 4 candidate: a plain unresolved card with no votes at all
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # tier 2 candidate: a contested card (two different printings voted for)
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == contested_card.identifier

    def test_tier_4_fresh_unresolved_printing_when_nothing_higher_priority_exists(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == card.identifier

    def test_tier_4_prioritizes_a_card_one_vote_from_resolving_over_a_totally_fresh_one(self, db):
        # zero votes at all - the common case, 28k+ of these exist at once
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # one AI vote + one *agreeing* human vote (weight 1.5 < PRINTING_TAG_MIN_VOTES=2, so
        # not yet resolved) - excluded from tier 1 (has a human vote) and not contested
        # (agreeing, not conflicting), so it falls through to tier 4 same as a fresh card,
        # but is one vote closer to actually resolving than one with zero votes.
        almost_resolved = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.USER)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == almost_resolved.identifier

    def test_tier_4_artist_when_no_printing_candidates_remain(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "artist"
        assert item.card.identifier == card.identifier

    def test_pending_approval_pairs_never_appear_in_the_feed(self, db):
        # pending-approval (card, tag) pairs used to surface here as a moderator-only tier 3 -
        # that hijacked the whole feed for moderators for as long as any report stayed pending
        # (see this module's docstring) and has moved to a dedicated Moderation tab
        # (`POST 2/moderationQueue/`, tested in test_moderation_views.py); get_next_question_
        # feed_item no longer even takes a `user` argument, since nothing here needs one any
        # more - this feed must never serve a pending-approval pair again, for any role
        make_pending_pair()

        assert get_next_question_feed_item("anon-1") is None

    def test_own_vote_exclusion_is_scoped_to_the_specific_tag_not_the_whole_card(self, db):
        """A voter who already answered one contested tag on a card must still be served a
        *different* still-open contested tag on the same card - own-vote exclusion must not
        be card-level (regression test for a bug caught in review before this shipped)."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        tag_a = TagFactory(name="Full Art")
        tag_b = TagFactory(name="Etched")
        for tag in (tag_a, tag_b):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses[tag_a.name] == TagVoteStatus.CONTESTED
        assert card.tag_vote_statuses[tag_b.name] == TagVoteStatus.CONTESTED
        # this voter already answered tag_a, but not tag_b
        CardTagVoteFactory(card=card, tag=tag_a, polarity=VotePolarity.APPLY, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "tag"
        assert item.card.identifier == card.identifier
        assert item.tagName == tag_b.name


class TestGetRemainingEstimate:
    def test_is_non_negative(self, db):
        counts = get_remaining_estimate()
        assert counts.total >= 0
        assert counts.confirmable >= 0
        assert counts.contested >= 0
        assert counts.fresh >= 0

    def test_total_counts_a_card_unresolved_in_both_printing_and_artist_only_once(self, db):
        """Regression test for the bug this shape replaced: the old implementation summed
        printing.count() + artist.count() + len(tag_pairs), so a single fresh card - UNRESOLVED
        on both printing and artist by default - added 2 to the total instead of 1. `total` is
        now a distinct-card union, so it must add exactly 1."""
        before = get_remaining_estimate().total
        # CardFactory() defaults both printing_tag_status and artist_vote_status to UNRESOLVED
        CardFactory()
        after = get_remaining_estimate().total
        assert after == before + 1

    def test_total_counts_fresh_confirmable_and_contested_cards_but_not_resolved_ones(self, db):
        before = get_remaining_estimate().total

        # confirmable: unresolved printing with an AI-sourced vote, no human vote yet
        confirmable_card, _ = make_ai_suggested_card(anonymous_id="ai-bot")
        # contested: conflicting human printing votes
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        # fresh: no votes at all
        CardFactory()
        # resolved: must not be counted
        CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)

        after = get_remaining_estimate().total
        assert after == before + 3

    def test_confirmable_counts_cards_with_an_unconfirmed_ai_suggestion(self, db):
        before = get_remaining_estimate().confirmable
        make_ai_suggested_card(anonymous_id="ai-bot")
        after = get_remaining_estimate().confirmable
        assert after == before + 1

    def test_confirmable_excludes_cards_with_a_human_vote_already(self, db):
        card, printing = make_ai_suggested_card(anonymous_id="ai-bot")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        # human vote moves it out of "confirmable" (no longer AI-only), and since it's not
        # conflicting with the AI vote, it's not contested either - not asserted here, just
        # confirming it leaves the confirmable bucket
        assert get_remaining_estimate().confirmable == 0

    def test_contested_counts_conflicting_printing_votes(self, db):
        before = get_remaining_estimate().contested
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        after = get_remaining_estimate().contested
        assert after == before + 1

    def test_contested_counts_conflicting_artist_votes(self, db):
        before = get_remaining_estimate().contested
        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        resolve_and_persist_artist(card)
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED
        after = get_remaining_estimate().contested
        assert after == before + 1

    def test_fresh_counts_totally_untouched_cards(self, db):
        before = get_remaining_estimate().fresh
        # unresolved on both printing and artist, but `fresh` (like `total`) is a distinct-card
        # count, so this one card only adds 1 even though it matches both axes' OR clauses
        CardFactory()
        after = get_remaining_estimate().fresh
        assert after == before + 1

    def test_fresh_excludes_contested_printing_cards(self, db):
        before = get_remaining_estimate().fresh
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        after = get_remaining_estimate().fresh
        assert after == before

    def test_pending_approval_pairs_are_not_counted(self, db):
        # this feed's "remaining" counts are ordinary-tagging advisory copy only - pending
        # moderation reports have their own badge on the dedicated Moderation tab instead
        # (see this module's docstring)
        before = get_remaining_estimate()
        make_pending_pair()
        after = get_remaining_estimate()
        assert after.total == before.total
        assert after.confirmable == before.confirmable
        assert after.contested == before.contested
        assert after.fresh == before.fresh


class TestGetQuestionFeedView:
    def test_missing_anonymous_id_is_a_bad_request(self, client, django_settings):
        response = client.get(reverse(views.get_question_feed))
        assert response.status_code == 400

    def test_returns_null_item_when_caught_up(self, client, django_settings):
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.status_code == 200
        assert response.json()["item"] is None
        assert response.json()["remainingEstimate"] == {
            "total": 0,
            "confirmable": 0,
            "contested": 0,
            "fresh": 0,
        }

    def test_returns_the_next_item(self, client, django_settings):
        card, _ = make_ai_suggested_card()
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.status_code == 200
        assert response.json()["item"]["card"]["identifier"] == card.identifier

    def test_pending_approval_pairs_never_surface_here_even_for_a_moderator_session(
        self, client, django_settings, moderator_user
    ):
        make_pending_pair()

        client.force_login(moderator_user)
        response = client.get(reverse(views.get_question_feed), {"anonymousId": "anon-1"})
        assert response.json()["item"] is None


def make_one_vote_from_resolving_card() -> tuple:
    """
    Two machine (OCR) votes for the same printing - summed weight 1.0 - is the 2026-07-24 data
    brief's "ONE more human vote resolves it" shape (45,154 of the 46,310-card LIKELY-RESOLVE
    SUPPLY): a hypothetical human vote (weight 1.0) totals 2.0, clearing
    `PRINTING_TAG_MIN_VOTES=2` outright. `artist_vote_status=RESOLVED` isolates this fixture to
    the printing axis only - otherwise a fresh card's default UNRESOLVED artist status would
    make it independently servable as a *different* (artist) question type via tier 4, which
    would falsely look like this same printing question resurfacing to tests that assert
    exclusion/non-recurrence (same isolation `make_pending_pair` above already relies on).
    """
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="bot-1")
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="bot-2")
    return card, printing


def make_two_votes_from_resolving_card() -> tuple:
    """
    A single machine (OCR) vote - weight 0.5 - is the data brief's "TWO more human votes
    resolve it" shape (39,968 of the near-threshold population): a hypothetical human vote
    (weight 1.0) only totals 1.5, still short of `PRINTING_TAG_MIN_VOTES=2`. See
    `make_one_vote_from_resolving_card` above for why `artist_vote_status=RESOLVED`.
    """
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="bot-1")
    return card, printing


def seed_served_log(anonymous_id: str, likely_resolve_count: int, remainder_count: int) -> None:
    for _ in range(likely_resolve_count):
        QuestionFeedServedLog.objects.create(
            anonymous_id=anonymous_id,
            pool=QuestionFeedServedPool.LIKELY_RESOLVE,
            question_type="confirm_suggestion",
            origin_reason="printing_one_vote_from_resolving",
        )
    for _ in range(remainder_count):
        QuestionFeedServedLog.objects.create(
            anonymous_id=anonymous_id,
            pool=QuestionFeedServedPool.REMAINDER,
            question_type="identify_printing",
            origin_reason="tier_4_fresh_printing",
        )


class TestIsLikelyResolvePrinting:
    """Serve-time LIKELY-RESOLVE classification (question_feed.is_likely_resolve_printing) -
    matches the real resolver on constructed 1-away/2-away fixtures, per the data brief's
    bimodal arithmetic (a printing pair is always exactly 1-away or 2-away, never further -
    PRINTING_TAG_MACHINE_WEIGHT is a constant 0.5/vote)."""

    def test_no_votes_at_all_is_not_likely_resolve(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        assert is_likely_resolve_printing(card) is False

    def test_one_machine_vote_two_away_is_not_likely_resolve(self, db):
        card, printing = make_two_votes_from_resolving_card()

        assert is_likely_resolve_printing(card) is False

        # round-trip against the real resolver: adding the actual hypothetical vote does NOT
        # resolve this card, confirming the classification agrees with resolve_printing itself
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

    def test_two_machine_votes_one_away_is_likely_resolve(self, db):
        card, printing = make_one_vote_from_resolving_card()

        assert is_likely_resolve_printing(card) is True

        # round-trip: adding the actual hypothetical vote DOES resolve this card
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

    def test_multi_candidate_leading_group_one_away_is_likely_resolve(self, db):
        # near-threshold multi-candidate shape (1,156 of the 46,310-card supply): two machine
        # votes for the leading printing (weight 1.0) plus one machine vote for a losing
        # candidate (weight 0.5) - the leading group is still exactly one human vote from
        # clearing quorum and share
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        leading_printing = CanonicalCardFactory()
        losing_printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=leading_printing, source=VoteSource.OCR, anonymous_id="bot-1")
        CardPrintingTagFactory(card=card, printing=leading_printing, source=VoteSource.OCR, anonymous_id="bot-2")
        CardPrintingTagFactory(card=card, printing=losing_printing, source=VoteSource.OCR, anonymous_id="bot-3")

        assert is_likely_resolve_printing(card) is True


class TestMixComposition:
    """Serve-mix policy (>=QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO from the likely-resolve pool
    when it has supply, per the 2026-07-24 data brief) - ratio gating, graceful degradation,
    per-voter exclusion, and the served-mix log this policy's soundness note requires."""

    def test_fresh_session_tries_likely_resolve_first_when_supply_exists(self, db):
        card, _ = make_one_vote_from_resolving_card()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.pool == QuestionFeedServedPool.LIKELY_RESOLVE
        assert log.origin_reason == "printing_one_vote_from_resolving"

    def test_ratio_below_target_prefers_likely_resolve_even_when_remainder_supply_exists(self, db):
        seed_served_log("anon-1", likely_resolve_count=20, remainder_count=80)  # ratio = 0.2
        likely_resolve_card, _ = make_one_vote_from_resolving_card()
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)  # remainder-only distractor

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == likely_resolve_card.identifier
        newest_log = QuestionFeedServedLog.objects.filter(anonymous_id="anon-1").latest("served_at")
        assert newest_log.pool == QuestionFeedServedPool.LIKELY_RESOLVE

    def test_ratio_at_target_serves_remainder_even_when_likely_resolve_supply_exists(self, db):
        # already at 60% likely-resolve, above the 51% floor - the greedy per-serve policy must
        # not keep piling more likely-resolve on top of an already-satisfied ratio, i.e. this
        # item must be reached via the remainder chain (tiers 1/2/4), never via the dedicated
        # likely-resolve branch - even though tier 4's own pre-existing "-vote_count" heuristic
        # can legitimately land on the SAME underlying card the likely-resolve pool would also
        # have picked (that card really is closest to resolving by both measures at once) - only
        # `pool` on the logged row, not card identity, is the thing this policy actually decides
        make_one_vote_from_resolving_card()  # likely-resolve supply exists...
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)  # ...so does plain remainder
        seed_served_log("anon-1", likely_resolve_count=60, remainder_count=40)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        newest_log = QuestionFeedServedLog.objects.filter(anonymous_id="anon-1").latest("served_at")
        assert newest_log.pool == QuestionFeedServedPool.REMAINDER

    def test_degrades_gracefully_to_remainder_with_no_supply_and_no_hang(self, db):
        # ratio under target, but nothing in the catalog qualifies as likely-resolve - must
        # fall straight through to the remainder tiers, not raise or loop
        fresh_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == fresh_card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.pool == QuestionFeedServedPool.REMAINDER

    def test_ratio_drops_honestly_once_the_likely_resolve_pool_is_exhausted(self, db):
        # this voter has already voted on the only likely-resolve card (excluded from the pool
        # for them specifically) - the mix ratio is free to fall below target rather than the
        # feed stalling/erroring to try to protect it
        seed_served_log("anon-1", likely_resolve_count=10, remainder_count=0)  # ratio = 1.0 so far
        exhausted_card, printing = make_one_vote_from_resolving_card()
        CardPrintingTagFactory(card=exhausted_card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")
        fresh_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == fresh_card.identifier
        newest_log = QuestionFeedServedLog.objects.filter(anonymous_id="anon-1").latest("served_at")
        assert newest_log.pool == QuestionFeedServedPool.REMAINDER

    def test_returns_none_with_no_log_row_when_nothing_is_servable_at_all(self, db):
        assert get_next_question_feed_item("anon-1") is None
        assert not QuestionFeedServedLog.objects.filter(anonymous_id="anon-1").exists()

    def test_likely_resolve_pool_excludes_cards_this_voter_already_voted_on(self, db):
        card, printing = make_one_vote_from_resolving_card()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        assert item is None or item.card.identifier != card.identifier

    def test_a_second_voters_own_exclusion_does_not_affect_a_first_voter(self, db):
        card, printing = make_one_vote_from_resolving_card()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")

        item_for_second_voter = get_next_question_feed_item("anon-2")

        assert item_for_second_voter is not None
        assert item_for_second_voter.card.identifier == card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-2")
        assert log.pool == QuestionFeedServedPool.LIKELY_RESOLVE

    def test_logs_a_row_for_a_remainder_served_item_too(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.pool == QuestionFeedServedPool.REMAINDER
        assert log.question_type == item.type.value

    def test_tier_4_prioritizes_quick_negative_to_review_origin_over_no_scan_log_at_all(self, db):
        no_origin_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        quick_negative_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardScanLog.objects.create(
            card=quick_negative_card,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
        )

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == quick_negative_card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.origin_reason == "tier_4_quick_negative_to_review"
        assert no_origin_card.identifier != quick_negative_card.identifier

    def test_tier_4_does_not_treat_ambiguous_origin_as_quick_negative(self, db):
        # "ambiguous" is deliberately excluded from QUICK_NEGATIVE_SKIP_REASONS (blocked on the
        # survivor_pks gap per the data brief - see question_feed.py's own module docstring) -
        # whichever card is served, it must never be logged as the quick-negative reason
        ambiguous_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardScanLog.objects.create(card=ambiguous_card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.origin_reason != "tier_4_quick_negative_to_review"
