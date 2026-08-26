import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.urls import reverse

from cardpicker import views
from cardpicker.artist_consensus import (
    get_contested_artist_card_ids,
    resolve_and_persist_artist,
)
from cardpicker.illustration_vote import cast_illustration_vote
from cardpicker.local_calculate_verdicts import (
    FALLBACK_NO_EVIDENCE_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardPrintingTag,
    CardQuestionAbstention,
    CardScanLog,
    HiddenCard,
    IllustrationVoteStatus,
    PrintingTagStatus,
    QuestionFeedServedLog,
    QuestionFeedServedPool,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.printing_consensus import (
    get_contested_card_ids,
    resolve_and_persist_printing,
)
from cardpicker.question_feed import (
    _artist_item,
    _border_item,
    _confirm_suggestion_item,
    _evidence_justifies_confirmation,
    _identify_printing_item,
    _illustration_item,
    _likely_resolve_item,
    _likely_resolve_narrowing_ratio,
    _likely_resolve_printing_card,
    _log_served,
    _scryfall_illustration_url,
    _tag_review_card_ids_by_status,
    _tier_1_confirm_suggestion,
    _tier_2_contested,
    _tier_4_fresh,
    _voter_answered_border_card_ids,
    _voter_answered_printing_card_ids,
    _voter_cannot_tell_card_ids,
    get_next_question_feed_item,
    get_remaining_estimate,
    is_likely_resolve_printing,
    warm_feed_supply_cache,
)
from cardpicker.question_feed_pools import (
    LANE_COLD,
    LANE_CONFIRM,
    LANE_CONTESTED,
    LANE_RESOLUTION_IMMINENT,
    LANES,
    SHARED_CACHE_ALIAS,
    _cache_key,
    warm_pool_cache,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardIllustrationRejectionFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    ImageEvidenceFactory,
    TagFactory,
)
from cardpicker.vote_consensus import contested_queryset


def _warm_all_lanes() -> None:
    """Warms every pool lane fresh from the DB state at the point this is called - the
    test-suite analogue of a warm cycle having just run right before a request, since pools are
    the sole serving mechanism (issue #762) and no longer build themselves inline on a cache
    miss. Must be called AFTER a test's fixtures are arranged (not via an autouse fixture, which
    would run before the test body and warm an empty pool) and, for a class asserting on
    `get_contested_card_ids`/`get_contested_artist_card_ids` call counts, before any `patch(...)`
    of those names - see `TestContestedIdsMemoizedPerRequest` below."""
    for lane in LANES:
        warm_pool_cache(lane)


def make_shared_illustration_group(name: str = "Brainstorm") -> tuple:
    """Two live printing candidates for a fresh `card`, sharing one `illustration_id` - the N>1
    shared-illustration-group premise `cast_illustration_vote` (illustration_vote.py) requires to
    take its no-CardPrintingTag-write branch. Mirrors test_illustration_vote.py's own
    `_printing_with_illustration` helper."""
    card = CardFactory(name=name, printing_tag_status=PrintingTagStatus.UNRESOLVED)
    illustration_id = uuid.uuid4()
    artist = CanonicalArtistFactory(name="Shared Artist")
    for _ in range(2):
        printing = CanonicalCardFactory(name=name, artist=artist)
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
    return card, illustration_id


_COMPLETE_EVIDENCE_TYPES = ("border", "artist", "collector_line")


def make_ai_suggested_card(
    anonymous_id: str = "ai-bot", evidence_types_used: tuple = _COMPLETE_EVIDENCE_TYPES
) -> tuple:
    """A card carrying a machine printing suggestion (issue #766: `confirm_suggestion` is now
    gated on `evidence_types_used` - see `_evidence_justifies_confirmation` - so this fixture
    attaches `evidence_types_used` directly to the suggestion vote, complete by default so every
    existing confirm_suggestion-shaped test stays a confirm_suggestion-shaped test). Pass
    `evidence_types_used=()`/a partial tuple/`None` for a test exercising the gate itself. Issue
    #797: the field lives on the `CardPrintingTag` vote the gate reads, not on a `CardScanLog`
    row - a MATCH outcome never writes one (see that issue and `_evidence_justifies_confirmation`
    for why)."""
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(
        card=card,
        printing=printing,
        source=VoteSource.DEDUCTION,
        anonymous_id=anonymous_id,
        evidence_types_used=list(evidence_types_used) if evidence_types_used is not None else None,
    )
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
        _warm_all_lanes()

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
        _warm_all_lanes()

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
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == contested_card.identifier

    def test_tier_4_fresh_unresolved_printing_when_nothing_higher_priority_exists(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CanonicalCardFactory(name=card.name)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == card.identifier

    def test_zero_candidate_card_is_never_served_identify_printing(self, db):
        """docs/features/wtc-question-model.md §5 rule 5 ("never ask for a claim the user has
        not been shown the evidence to make"): a card with no ranked printing candidates at all
        has nothing in its identify_printing grid to pick from, so it must never be served that
        question. `artist_vote_status=RESOLVED` isolates this card from every other question
        type this feed could ask about it - with no matching `CanonicalCard` (so
        `get_ranked_printing_candidates` is `[]`) and nothing else answerable, the feed must
        return `None` rather than the dead question the pre-fix code served. FAILS against
        pre-fix code, which served `identify_printing` with an empty `candidates` list here."""
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        _warm_all_lanes()

        assert get_next_question_feed_item("anon-1") is None

    def test_zero_candidate_card_falls_through_to_its_still_answerable_artist_question(self, db):
        """A card with zero ranked printing candidates is not necessarily unanswerable on every
        axis (task's own requirement): if its artist question is still open, the feed must ask
        that instead of dropping the card entirely."""
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "artist"
        assert item.card.identifier == card.identifier

    def test_tier_4_prioritizes_a_card_one_vote_from_resolving_over_a_totally_fresh_one(self, db):
        # zero votes at all - the common case, 28k+ of these exist at once
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # one machine vote + one *agreeing* human vote (weight 1.5 < PRINTING_TAG_MIN_VOTES=2, so
        # not yet resolved) - excluded from tier 1 (has a human vote) and not contested
        # (agreeing, not conflicting), so it falls through to tier 4 same as a fresh card,
        # but is one vote closer to actually resolving than one with zero votes.
        almost_resolved = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=almost_resolved, printing=printing, source=VoteSource.USER)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == almost_resolved.identifier

    def test_tier_4_artist_when_no_printing_candidates_remain(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )
        _warm_all_lanes()

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
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "tag"
        assert item.card.identifier == card.identifier
        assert item.tagName == tag_b.name

    def test_a_hidden_card_is_excluded_from_this_voters_feed(self, db):
        """Issue #714: a card this voter hid for themselves (`HiddenCard`, written by
        `views.post_report_card` when a report carries `hide=True`) must never come back in
        their own feed items, whichever tier would otherwise have served it."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        HiddenCard.objects.create(card=card, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        # the only candidate is hidden for this voter - nothing else exists, so None
        assert item is None or item.card.identifier != card.identifier

    def test_a_hidden_card_is_still_served_to_other_voters(self, db):
        """The exclusion is per-anonymous_id, not global: hiding a card for yourself never
        hides it for anyone else - same scoping as every other vote/report table here."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        HiddenCard.objects.create(card=card, anonymous_id="anon-1")
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-2")

        assert item is not None
        assert item.card.identifier == card.identifier

    def test_a_hidden_card_is_excluded_even_when_it_is_the_only_contested_candidate(self, db):
        """Tier 2's contested printing half must respect the hidden exclusion too - a card the
        voter hid must not resurface just because it became the highest-priority contested one."""
        hidden_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=hidden_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=hidden_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        HiddenCard.objects.create(card=hidden_card, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        assert item is None or item.card.identifier != hidden_card.identifier


class TestContestedIdsMemoizedPerRequest:
    """`get_contested_card_ids` is expensive (issue #726: 330-400ms on production data per
    call, 520-686ms measured 2026-08-16) and, before this fix, was recomputed once per tier
    that consulted it instead of once per `get_next_question_feed_item` call. `contested_card_ids`
    is now resolved at most once per call and threaded to every lane that needs it.

    `get_contested_artist_card_ids` is deliberately NOT part of the pool-served request path
    any more: the bare call inside the contested lane (a vestige of the pre-pool waterfall)
    was removed, and the contested lane's artist half relies on the per-candidate read-time
    filter `artist_vote_status=ArtistVoteStatus.CONTESTED` in
    `question_feed_pools.draw_contested_entry` - the same "still CONTESTED right now, not just
    as of the last warm" staleness guarantee the printing half's
    `_fetch_unresolved_printing_card` documents. The contested-artist id set is consumed where
    it still matters: by the live `_tier_2_contested` (its artist half filters on it) and by
    the contested-lane pool builder at warm time."""

    def test_get_contested_card_ids_computed_once_when_tier_2_and_tier_4_are_both_consulted(self, db):
        # a plain unresolved card with no votes: tier 2 finds nothing contested and falls
        # through to tier 4, which - before this fix - called get_contested_card_ids() a
        # second time for the same answer within the same request
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        # warmed before the patch context: warming itself calls the real (unpatched, different
        # module-level reference) get_contested_card_ids internally to build the cold pool, and
        # must not count toward the mocked call assertions below
        warm_pool_cache(LANE_COLD)

        with (
            patch("cardpicker.question_feed.get_contested_card_ids", wraps=get_contested_card_ids) as mock_contested,
            patch(
                "cardpicker.question_feed.get_contested_artist_card_ids", wraps=get_contested_artist_card_ids
            ) as mock_contested_artist,
        ):
            item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier
        assert mock_contested.call_count == 1
        assert mock_contested_artist.call_count == 0  # the vestigial bare call was removed

    def test_get_contested_card_ids_not_called_when_tier_1_serves_the_item(self, db):
        # tier 1 (confirm_suggestion) and the likely-resolve pool both resolve before tier 2 is
        # ever reached, so neither contested-ids function should run at all
        make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)

        with patch("cardpicker.question_feed.get_contested_card_ids", wraps=get_contested_card_ids) as mock_contested:
            item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert mock_contested.call_count == 0


class TestGetContestedCardIdsCaching:
    """`get_contested_card_ids`'s short-TTL "shared"-cache wrapper (2026-08-16): the value is a
    pure function of persisted votes and measured at 520-686ms per call against live production
    data, and `views.get_question_feed` resolves it once per feed request - so it is cached on
    the cross-process `"shared"` cache for `_CONTESTED_CARD_IDS_CACHE_TTL` (300s), the TTL being
    the only invalidation mechanism, same convention as the remaining-estimate counts."""

    def test_second_call_within_ttl_hits_the_cache(self, db):
        with patch("cardpicker.printing_consensus.contested_queryset", wraps=contested_queryset) as mock_compute:
            first = get_contested_card_ids()
            second = get_contested_card_ids()
            assert mock_compute.call_count == 1  # the second call was served by the cache
        assert first == second

    def test_clearing_the_cache_forces_a_recompute(self, db):
        with patch("cardpicker.printing_consensus.contested_queryset", wraps=contested_queryset) as mock_compute:
            get_contested_card_ids()
            caches["shared"].clear()
            get_contested_card_ids()
            assert mock_compute.call_count == 2

    def test_a_mutating_caller_never_poisons_the_cached_value(self, db):
        first = get_contested_card_ids()
        first.append(999999999)  # a caller mutating the returned list
        second = get_contested_card_ids()
        assert 999999999 not in second  # the cache serves a fresh copy, unaffected

    def test_force_refresh_skips_the_cache_read_but_still_writes(self, db):
        """2026-08-20 fix: `force_refresh=True` must bypass a still-valid cache entry (the
        normal case `warm_feed_supply_cache` hits on its cadence) and recompute, then WRITE the
        fresh value so a subsequent default call reads it rather than a stale hit."""
        with patch("cardpicker.printing_consensus.contested_queryset", wraps=contested_queryset) as mock_compute:
            get_contested_card_ids()  # seed a valid cache entry
            get_contested_card_ids(force_refresh=True)
            assert mock_compute.call_count == 2  # force_refresh bypassed the still-valid entry
            get_contested_card_ids()
            assert mock_compute.call_count == 2  # the force_refresh call's write landed


class TestPhaseCNotOfficialArtRouting:
    """
    2026-08-04 gate on the phase-C/md5 routing brief (item 2): a card carrying a positive,
    human-backed no-match-reason vote for one of `reason_tags.NOT_OFFICIAL_ART_REASON_TAGS` has
    had its artwork question declared unanswerable by a human, so the feed must stop serving
    artist-shaped questions for it - the printing question is a different matter and stays
    unaffected. `NOT_OFFICIAL_PRINTING_REASON_TAGS` tags carry no such implication.
    """

    @staticmethod
    def _artist_candidate():
        # RESOLVED printing + UNRESOLVED artist isolates this card to tier 4's artist half,
        # mirroring test_tier_4_artist_when_no_printing_candidates_remain above.
        return CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )

    def test_a_not_official_art_vote_excludes_the_card_from_artist_questions(self, db):
        card = self._artist_candidate()
        tag = TagFactory(name="custom-art")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")

        assert get_next_question_feed_item("anon-1") is None

    def test_a_not_official_printing_vote_does_not_exclude_the_card(self, db):
        card = self._artist_candidate()
        tag = TagFactory(name="upscaled")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "artist"
        assert item.card.identifier == card.identifier

    def test_a_negative_not_official_art_vote_does_not_exclude_the_card(self, db):
        card = self._artist_candidate()
        tag = TagFactory(name="external-ip")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-1")
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier

    def test_a_machine_cast_not_official_art_vote_does_not_exclude_the_card(self, db):
        card = self._artist_candidate()
        tag = TagFactory(name="ai-art")
        CardTagVoteFactory(
            card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="ai-bot", source=VoteSource.DEDUCTION
        )
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier


class TestScryfallIllustrationUrl:
    """`_scryfall_illustration_url` (WTC artist question re-frame) surfaces the canonical
    printing's harvested Scryfall art-crop URL on artist-type feed items - see that function's
    own docstring for the precedence it delegates to `Card._get_indexed_printing_metadata`."""

    def test_returns_the_art_crop_url_when_the_canonical_printing_has_one(self, db):
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(
            canonical_card=printing, art_crop_url="https://cards.scryfall.io/art_crop/example.jpg"
        )
        card = CardFactory(canonical_card=printing)

        assert _scryfall_illustration_url(card) == "https://cards.scryfall.io/art_crop/example.jpg"

    def test_returns_none_when_the_canonical_printing_has_an_empty_art_crop_url(self, db):
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, art_crop_url="")
        card = CardFactory(canonical_card=printing)

        assert _scryfall_illustration_url(card) is None

    def test_returns_none_when_there_is_no_canonical_printing_at_all(self, db):
        # no canonical_card, and printing_tag_status defaults to UNRESOLVED so
        # inferred_canonical_card is never consulted either - see
        # Card._get_indexed_printing_metadata's own RESOLVED-gated fallback.
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED)

        assert _scryfall_illustration_url(card) is None

    def test_falls_back_to_inferred_canonical_card_only_once_resolved(self, db):
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(
            canonical_card=printing, art_crop_url="https://cards.scryfall.io/art_crop/inferred.jpg"
        )
        unresolved_card = CardFactory(
            canonical_card=None, inferred_canonical_card=printing, printing_tag_status=PrintingTagStatus.UNRESOLVED
        )
        assert _scryfall_illustration_url(unresolved_card) is None

        resolved_card = CardFactory(
            canonical_card=None, inferred_canonical_card=printing, printing_tag_status=PrintingTagStatus.RESOLVED
        )
        assert _scryfall_illustration_url(resolved_card) == "https://cards.scryfall.io/art_crop/inferred.jpg"

    def test_artist_item_carries_the_field(self, db):
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(
            canonical_card=printing, art_crop_url="https://cards.scryfall.io/art_crop/example.jpg"
        )
        card = CardFactory(canonical_card=printing)

        item = _artist_item(card)

        assert item.scryfallIllustrationUrl == "https://cards.scryfall.io/art_crop/example.jpg"

    def test_artist_item_carries_none_when_there_is_no_art_crop(self, db):
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = _artist_item(card)

        assert item.scryfallIllustrationUrl is None


class TestBorderItem:
    """`_border_item` - the per-element border question (wtc-question-model.md §7): asks
    which of the four border colours (Black / White / Silver / Borderless, the exclusive
    BORDER_COLOR_GROUP axis) a card has. Self-contained builder: not wired into the
    selection/waterfall (PR #775 owns that), casts through the existing tag-vote path.
    """

    def test_border_item_is_type_border(self, db):
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = _border_item(card)

        assert item.type.value == "border"
        assert item.card.name == card.name

    def test_border_item_carries_tag_confidence_for_the_seeded_border_chips(self, db):
        # Seed the four border-axis tags the way production's seed_attribute_tags does - the
        # payload must carry each one's net polarity so the frontend chips get a fill overlay,
        # reading 0.0 (neutral) for unvoted chips rather than being absent.
        for tag_name in ("Black Border", "White Border", "Silver Border", "Borderless"):
            TagFactory(name=tag_name)
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED)

        item = _border_item(card)

        assert item.tagConfidence == {
            "Black Border": 0.0,
            "White Border": 0.0,
            "Silver Border": 0.0,
            "Borderless": 0.0,
        }


class TestLogServedMeasuredBleed:
    """`_log_served` attaches the served card's own measured bleed (Card.measured_bleed_mm())
    onto `item.card.measuredBleedMm` - see that function's own docstring for why this is
    resolved here rather than inside each item builder."""

    def test_attaches_measured_bleed_when_current_evidence_has_it(self, db):
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED, content_phash=123)
        ImageEvidenceFactory(card=card, content_hash=123, bleed_diff_mm=0.675)
        item = _border_item(card)

        served = _log_served("anon", item, QuestionFeedServedPool.REMAINDER, "test")

        assert served.card.measuredBleedMm == 2.5  # BLEED_MARGIN_MM (3.175) - 0.675

    def test_leaves_measured_bleed_null_when_no_current_evidence(self, db):
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED, content_phash=456)
        item = _border_item(card)

        served = _log_served("anon", item, QuestionFeedServedPool.REMAINDER, "test")

        assert served.card.measuredBleedMm is None

    def test_leaves_measured_bleed_null_when_evidence_is_stale(self, db):
        # content_hash disagrees with the card's own current content_phash - current_evidence_
        # queryset excludes it, the same staleness rule every other bleed reader honours.
        card = CardFactory(canonical_card=None, printing_tag_status=PrintingTagStatus.UNRESOLVED, content_phash=789)
        ImageEvidenceFactory(card=card, content_hash=999, bleed_diff_mm=0.675)
        item = _border_item(card)

        served = _log_served("anon", item, QuestionFeedServedPool.REMAINDER, "test")

        assert served.card.measuredBleedMm is None


def _remaining_estimate(*args, **kwargs):
    """`get_remaining_estimate()` with the shared cache cleared first.

    The tests in `TestGetRemainingEstimate` assert exact count deltas around DB mutations, but
    production may legitimately serve a <=300s-stale advisory count (the TTL is the invalidation
    policy - see the function's docstring). Clearing the cache before each call makes the
    assertions see a fresh compute, which is what they are actually testing.
    """
    caches["shared"].clear()
    return get_remaining_estimate(*args, **kwargs)


class TestGetRemainingEstimate:
    def test_is_non_negative(self, db):
        counts = _remaining_estimate()
        assert counts.total >= 0
        assert counts.confirmable >= 0
        assert counts.contested >= 0
        assert counts.fresh >= 0

    def test_total_counts_a_card_unresolved_in_both_printing_and_artist_only_once(self, db):
        """Regression test for the bug this shape replaced: the old implementation summed
        printing.count() + artist.count() + len(tag_pairs), so a single fresh card - UNRESOLVED
        on both printing and artist by default - added 2 to the total instead of 1. `total` is
        now a distinct-card union, so it must add exactly 1."""
        before = _remaining_estimate().total
        # CardFactory() defaults both printing_tag_status and artist_vote_status to UNRESOLVED
        CardFactory()
        after = _remaining_estimate().total
        assert after == before + 1

    def test_total_counts_fresh_confirmable_and_contested_cards_but_not_resolved_ones(self, db):
        before = _remaining_estimate().total

        # confirmable: unresolved printing with a machine-sourced vote, no human vote yet
        confirmable_card, _ = make_ai_suggested_card(anonymous_id="ai-bot")
        # contested: conflicting human printing votes
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        # fresh: no votes at all
        CardFactory()
        # resolved: must not be counted
        CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)

        after = _remaining_estimate().total
        assert after == before + 3

    def test_confirmable_counts_cards_with_an_unconfirmed_ai_suggestion(self, db):
        before = _remaining_estimate().confirmable
        make_ai_suggested_card(anonymous_id="ai-bot")
        after = _remaining_estimate().confirmable
        assert after == before + 1

    def test_confirmable_excludes_cards_with_a_human_vote_already(self, db):
        card, printing = make_ai_suggested_card(anonymous_id="ai-bot")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        # human vote moves it out of "confirmable" (no longer machine-only), and since it's not
        # conflicting with the machine vote, it's not contested either - not asserted here, just
        # confirming it leaves the confirmable bucket
        assert _remaining_estimate().confirmable == 0

    def test_contested_counts_conflicting_printing_votes(self, db):
        before = _remaining_estimate().contested
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        after = _remaining_estimate().contested
        assert after == before + 1

    def test_contested_counts_conflicting_artist_votes(self, db):
        before = _remaining_estimate().contested
        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        resolve_and_persist_artist(card)
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED
        after = _remaining_estimate().contested
        assert after == before + 1

    def test_fresh_counts_totally_untouched_cards(self, db):
        before = _remaining_estimate().fresh
        # unresolved on both printing and artist, but `fresh` (like `total`) is a distinct-card
        # count, so this one card only adds 1 even though it matches both axes' OR clauses
        CardFactory()
        after = _remaining_estimate().fresh
        assert after == before + 1

    def test_fresh_excludes_contested_printing_cards(self, db):
        before = _remaining_estimate().fresh
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        after = _remaining_estimate().fresh
        assert after == before

    def test_pending_approval_pairs_are_not_counted(self, db):
        # this feed's "remaining" counts are ordinary-tagging advisory copy only - pending
        # moderation reports have their own badge on the dedicated Moderation tab instead
        # (see this module's docstring)
        before = _remaining_estimate()
        make_pending_pair()
        after = _remaining_estimate()
        assert after.total == before.total
        assert after.confirmable == before.confirmable
        assert after.contested == before.contested
        assert after.fresh == before.fresh


class TestGetRemainingEstimateCaching:
    """The 300s shared-cache wrapper (see `get_remaining_estimate`'s docstring): the four counts
    are advisory header copy, so the TTL is the invalidation policy and there are deliberately no
    invalidation hooks. These tests assert the cache is actually hit on a second call within the
    TTL, and that the key is derived from the function's effective inputs - a pre-resolved
    contested set must never read a cached value computed against a different set."""

    def test_second_call_within_ttl_hits_the_cache(self, db):
        """The measured ~7.45s of the uncached feed (2026-08-06 deploy wave) is 2 id-set scans
        plus 4 `.distinct().count()` buckets; a cache hit skips all of it. Two calls with
        `contested_card_ids=None` share the single stable key, so the contested set must be
        resolved exactly once: the first call computes and stores, the second returns the stored
        value without touching the data-access functions at all."""
        with patch("cardpicker.question_feed.get_contested_card_ids", return_value=[1, 2, 3]) as resolve:
            first = get_remaining_estimate()
            second = get_remaining_estimate()
            assert resolve.call_count == 1  # the second call was served by the cache
        assert first == second

    def test_a_pre_resolved_set_keys_the_cache_by_its_content(self, db):
        """The view path (issue #713 part 2) passes a contested set resolved earlier in the
        request; the key must incorporate that set's content so two requests that resolved
        different sets never share a cached value. Same set twice -> second call hits; a
        different set -> miss, recomputed."""
        with patch(
            "cardpicker.question_feed._tag_review_card_ids_by_status",
            side_effect=[(set(), set()), (set(), set()), (set(), set())],
        ) as tag_review:
            get_remaining_estimate([1, 2, 3])
            get_remaining_estimate([1, 2, 3])
            assert tag_review.call_count == 1  # same set: second call hit the cache

            get_remaining_estimate([4, 5, 6])
            assert tag_review.call_count == 2  # different set: different cache entry, recomputed

    def test_clearing_the_cache_forces_a_recompute(self, db):
        """The TTL is the only invalidation mechanism - there are no invalidation hooks - so a
        value evicted (or never stored) must be recomputed on the next call."""
        with patch("cardpicker.question_feed.get_contested_card_ids", return_value=[1, 2, 3]) as resolve:
            get_remaining_estimate()
            caches["shared"].clear()
            get_remaining_estimate()
            assert resolve.call_count == 2

    def test_force_refresh_skips_the_cache_read_but_still_writes(self, db):
        """2026-08-20 fix: `force_refresh=True` must bypass a still-valid cache entry (the
        normal case `warm_feed_supply_cache` hits on its cadence) and recompute, then WRITE the
        fresh value so a subsequent default call reads it rather than a stale hit."""
        with patch("cardpicker.question_feed.get_contested_card_ids", return_value=[1, 2, 3]) as resolve:
            get_remaining_estimate()  # seed a valid cache entry
            get_remaining_estimate(force_refresh=True)
            assert resolve.call_count == 2  # force_refresh bypassed the still-valid entry
            get_remaining_estimate()
            assert resolve.call_count == 2  # the force_refresh call's write landed


class TestWarmFeedSupplyCache:
    """`warm_feed_supply_cache` - the scheduled warm behind `warm_question_feed_remaining_
    estimate` - must leave both 300s-TTL caches (`get_contested_card_ids`'s own,
    `get_remaining_estimate`'s own) populated with the SAME values a live `views.
    get_question_feed` request would then read, not merely "some" cached value."""

    def test_populates_both_caches_a_live_request_reads(self, db):
        caches["shared"].clear()
        warm_feed_supply_cache()

        with patch("cardpicker.question_feed.get_contested_card_ids") as resolve:
            # A live request's own call to get_contested_card_ids must be served by the warm
            # above's cache entry, not recomputed.
            from cardpicker.printing_consensus import (
                get_contested_card_ids as real_get_contested_card_ids,
            )

            resolve.side_effect = AssertionError("should not be called - the warm already cached this")
            contested = real_get_contested_card_ids()
        assert contested == []

        with patch("cardpicker.question_feed._tag_review_card_ids_by_status") as tag_review:
            tag_review.side_effect = AssertionError("should not be called - the warm already cached this")
            counts = get_remaining_estimate(contested)
        assert counts.total == 0

    def test_returns_the_same_counts_it_cached(self, db):
        caches["shared"].clear()
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        returned = warm_feed_supply_cache()
        cached = get_remaining_estimate()
        assert returned == cached
        assert returned.total >= 1

    def test_warm_recomputes_and_overwrites_a_still_valid_contested_ids_entry(self, db):
        # 2026-08-20 production fix: the normal case on a warm cadence shorter than the 300s
        # TTL is that the entry is STILL VALID when the warm runs. Asserts the underlying
        # compute actually ran, not merely that the return value looks right.
        get_contested_card_ids()
        with patch("cardpicker.printing_consensus.contested_queryset", wraps=contested_queryset) as mock_compute:
            warm_feed_supply_cache()
            assert mock_compute.call_count == 1

    def test_warm_recomputes_and_overwrites_a_still_valid_remaining_estimate_entry(self, db):
        contested = get_contested_card_ids()
        get_remaining_estimate(contested)
        with patch(
            "cardpicker.question_feed._tag_review_card_ids_by_status", wraps=_tag_review_card_ids_by_status
        ) as tag_review:
            warm_feed_supply_cache()
            assert tag_review.call_count == 1

    def test_warm_resets_the_ttl_by_writing_both_keys_even_when_entries_are_still_valid(self, db):
        contested = get_contested_card_ids()
        get_remaining_estimate(contested)
        with patch.object(caches["shared"], "set", wraps=caches["shared"].set) as mock_set:
            warm_feed_supply_cache()
            assert mock_set.call_count == 2

    def test_a_normal_request_after_a_warm_still_reads_through_without_recomputing(self, db):
        warm_feed_supply_cache()
        with patch("cardpicker.printing_consensus.contested_queryset", wraps=contested_queryset) as mock_compute:
            get_contested_card_ids()
            assert mock_compute.call_count == 0


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
        _warm_all_lanes()
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
        _warm_all_lanes()

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
        _warm_all_lanes()

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
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        newest_log = QuestionFeedServedLog.objects.filter(anonymous_id="anon-1").latest("served_at")
        assert newest_log.pool == QuestionFeedServedPool.REMAINDER

    def test_degrades_gracefully_to_remainder_with_no_supply_and_no_hang(self, db):
        # ratio under target, but nothing in the catalog qualifies as likely-resolve - must
        # fall straight through to the remainder tiers, not raise or loop
        fresh_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _warm_all_lanes()

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
        _warm_all_lanes()

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
        _warm_all_lanes()

        item_for_second_voter = get_next_question_feed_item("anon-2")

        assert item_for_second_voter is not None
        assert item_for_second_voter.card.identifier == card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-2")
        assert log.pool == QuestionFeedServedPool.LIKELY_RESOLVE

    def test_logs_a_row_for_a_remainder_served_item_too(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.pool == QuestionFeedServedPool.REMAINDER
        assert log.question_type == item.type.value

    def test_tier_4_prioritizes_quick_negative_to_review_origin_over_no_scan_log_at_all(self, db):
        no_origin_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        quick_negative_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CanonicalCardFactory(name=no_origin_card.name)
        CanonicalCardFactory(name=quick_negative_card.name)
        CardScanLog.objects.create(
            card=quick_negative_card,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
        )
        _warm_all_lanes()

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
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        log = QuestionFeedServedLog.objects.get(anonymous_id="anon-1")
        assert log.origin_reason != "tier_4_quick_negative_to_review"


class TestEvidenceJustifiesConfirmation:
    """Direct unit coverage of `_evidence_justifies_confirmation` itself (issue #797), below the
    full `get_next_question_feed_item` integration tests in `TestEvidenceGatedConfirmation`."""

    def test_a_vote_with_all_three_required_evidence_types_clears_the_gate(self, db):
        vote = CardPrintingTagFactory(
            source=VoteSource.OCR,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            evidence_types_used=["border", "artist", "collector_line"],
        )

        assert _evidence_justifies_confirmation(vote) is True

    def test_a_vote_additionally_carrying_symbol_still_clears_the_gate(self, db):
        # symbol is optional corroboration, never a precondition (see
        # `_REQUIRED_EVIDENCE_TYPES`'s own comment) - a vote that happens to carry it alongside
        # the three required types must still pass, not be penalised for the extra evidence
        vote = CardPrintingTagFactory(
            source=VoteSource.OCR,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            evidence_types_used=["border", "artist", "collector_line", "symbol"],
        )

        assert _evidence_justifies_confirmation(vote) is True

    def test_a_vote_missing_collector_line_does_not_clear_the_gate(self, db):
        # border + artist + symbol - the pre-2026-08-21 gate's own requirement - now fails,
        # since collector_line is required and symbol alone is not a substitute for it
        vote = CardPrintingTagFactory(
            source=VoteSource.OCR,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            evidence_types_used=["border", "artist", "symbol"],
        )

        assert _evidence_justifies_confirmation(vote) is False

    def test_a_vote_with_partial_evidence_does_not_clear_the_gate(self, db):
        vote = CardPrintingTagFactory(
            source=VoteSource.OCR,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            evidence_types_used=["border", "artist"],
        )

        assert _evidence_justifies_confirmation(vote) is False

    def test_a_vote_with_null_evidence_does_not_clear_the_gate(self, db):
        vote = CardPrintingTagFactory(source=VoteSource.OCR, evidence_types_used=None)

        assert _evidence_justifies_confirmation(vote) is False


class TestEvidenceGatedConfirmation:
    """Evidence-gated printing-confirmation policy (2026-08-11, issue #766, tightened to read the
    vote itself by issue #797; see this module's own docstring's "Evidence-gated printing-
    confirmation policy" section): `confirm_suggestion` is offered only when the suggestion
    vote's own recorded `evidence_types_used` covers every type the fallback calculator can
    record; any other vote - partial evidence, or none at all - falls through to `identify_
    printing` via the existing contested/cold machinery instead, and the remainder waterfall
    itself is a fixed confirm -> contested -> cold order with no session-dependent rotation."""

    def test_a_card_with_complete_evidence_is_offered_as_confirm_suggestion(self, db):
        card, printing = make_ai_suggested_card()  # complete evidence by default
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier

    def test_a_card_with_symbol_recorded_too_is_still_offered_as_confirm_suggestion(self, db):
        # symbol is optional corroboration (see `_REQUIRED_EVIDENCE_TYPES`'s own comment) - the
        # gate must still fire via subset containment, not equality, so a vote carrying symbol
        # alongside the three required types is not penalised for the extra evidence
        card, printing = make_ai_suggested_card(evidence_types_used=("border", "artist", "collector_line", "symbol"))
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier

    def test_a_card_missing_one_evidence_type_is_not_offered_as_confirm_suggestion(self, db):
        # two of three required evidence types recorded (missing "collector_line") - the ratified
        # doc's own ruling (§10 ruling 3) that three-of-four earns no special tier applies here
        # too: anything less than complete required evidence routes to identify_printing, no
        # partial-credit tier
        incomplete_card, _ = make_ai_suggested_card(evidence_types_used=("border", "artist"))
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == incomplete_card.identifier

    def test_a_card_with_no_recorded_evidence_at_all_is_not_offered_as_confirm_suggestion(self, db):
        # the pre-#797 universal case: a machine printing suggestion whose vote's own
        # evidence_types_used is null - every vote cast before this field existed, and every
        # join-key/deductive-backfill vote, since only the fallback calculator populates it
        no_evidence_card, _ = make_ai_suggested_card(evidence_types_used=None)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == no_evidence_card.identifier

    def test_the_remainder_waterfall_tries_confirm_before_contested_regardless_of_session_history(self, db):
        # session history used to change which lane went first (the deleted rotation); it must
        # not any more - a genuinely evidence-complete confirm candidate still wins first even
        # against a session logged as heavily confirm-served already
        for _ in range(10):
            QuestionFeedServedLog.objects.create(
                anonymous_id="anon-1",
                pool=QuestionFeedServedPool.REMAINDER,
                question_type="confirm_suggestion",
                origin_reason="tier_1_confirm_suggestion",
            )
        confirm_card, _ = make_ai_suggested_card()
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.OCR)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.OCR)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == confirm_card.identifier

    def test_a_starved_confirm_lane_falls_through_to_contested_without_hanging(self, db):
        # no card anywhere clears the evidence gate - the common case today - so the confirm
        # lane's pool is genuinely empty; the request must still reach contested rather than
        # stalling on the empty first lane
        make_ai_suggested_card(evidence_types_used=None)  # confirm-shaped but ungated
        contested_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=contested_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == contested_card.identifier


class TestEvidenceGateReadsTheVoteNotTheScanLog:
    """Issue #797: `_evidence_justifies_confirmation` reads `evidence_types_used` off the
    `CardPrintingTag` vote being confirmed, never off `CardScanLog` - a MATCH (the only outcome
    that can ever reach this gate) never writes a scan-log row at all
    (`local_calculate_verdicts.run_fallback_calculator`). These tests pin the single-source-of-
    truth property: an unrelated `CardScanLog` row on the same card, however it's shaped, must
    never move this gate's outcome in either direction."""

    def test_an_unrelated_scan_log_row_does_not_help_a_vote_with_no_evidence_clear_the_gate(self, db):
        # a card whose vote carries no evidence, but which also carries a fully-populated
        # fallback-writer scan-log row (e.g. left behind by an earlier skip on the same card,
        # later superseded by a match under a fresh run) - the gate must still fail, since it
        # never looks at CardScanLog at all; a reader that silently fell back to it would let a
        # stale, unrelated row stand in for the vote's own record
        card, _ = make_ai_suggested_card(evidence_types_used=None)
        CardScanLog.objects.create(
            card=card,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            skip_reason="ambiguous",
            evidence_types_used=list(_COMPLETE_EVIDENCE_TYPES),
        )
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "identify_printing"
        assert item.card.identifier == card.identifier

    def test_an_unrelated_scan_log_row_does_not_break_a_vote_that_already_clears_the_gate(self, db):
        # the inverse: a card whose vote already carries complete evidence must keep clearing the
        # gate regardless of whatever else CardScanLog holds for the same card - a join-key skip
        # row (a different writer entirely) and an empty fallback no-evidence row are both present
        card, _ = make_ai_suggested_card()  # complete evidence, on the vote
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, skip_reason=FALLBACK_NO_EVIDENCE_SKIP_REASON
        )
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier


class TestIllustrationVoteAnsweredExclusion:
    """Issue #713: `cast_illustration_vote` writes `CardPrintingTag` only when the shared-
    illustration group resolves to exactly one live printing - at N>1 (the premise of the
    cluster UI that triggers this path) it writes only `CardIllustrationVote`, which the
    printing exclusion below must also read or the voter is re-served the very card they just
    answered."""

    def test_voter_answered_printing_card_ids_includes_n_gt_1_illustration_votes(self, db):
        card, illustration_id = make_shared_illustration_group()

        outcome = cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert outcome.printing_vote_cast is False
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="voter-1").count() == 0
        assert card.pk in _voter_answered_printing_card_ids("voter-1")

    def test_a_voter_who_answers_an_n_gt_1_illustration_group_is_not_re_served_that_card(self, db):
        card, illustration_id = make_shared_illustration_group()
        _warm_all_lanes()

        first_item = get_next_question_feed_item("voter-1")
        assert first_item is not None
        assert first_item.card.identifier == card.identifier

        cast_illustration_vote(
            card=card,
            anonymous_id="voter-1",
            illustration_id=illustration_id,
            is_unknown=False,
            user=None,
            vote_surface="question-feed",
        )

        assert get_next_question_feed_item("voter-1") is None


class TestGetNextQuestionFeedItemUsesPools:
    """`get_next_question_feed_item` tries a materialised pool (issue #727) for each of its four
    lanes and pools are the SOLE serving mechanism on this request path (issue #762 correction -
    an earlier version of this module built a lane's pool INLINE on a cache miss, reintroducing
    the exact Parallel Seq Scan pooling exists to move off the request path; see
    `question_feed_pools._get_cached_pool`'s own docstring). A pool draw returning `None` -
    never warmed, evicted, this voter's exclusion exhausting every entry, or the `"shared"`
    backend not configured - means that lane has no supply for THIS request; there is no live
    per-tier fallback to reach for any more. These tests warm a pool first and prove the SERVED
    item matches it and that the item-level (never full-scan) tier function is called at most
    once for construction; the cold/exhausted/unconfigured cases below prove the request
    degrades to "no supply for this lane" rather than paying for an inline build."""

    def test_serves_the_same_item_from_a_warmed_resolution_imminent_pool(self, db):
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)

        with patch(
            "cardpicker.question_feed._likely_resolve_printing_card", wraps=_likely_resolve_printing_card
        ) as mock_live:
            item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == card.identifier
        mock_live.assert_not_called()

    def test_serves_the_same_item_from_a_warmed_confirm_pool(self, db):
        card, printing = make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)

        with patch("cardpicker.question_feed._tier_1_confirm_suggestion") as mock_live:
            item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.type.value == "confirm_suggestion"
        assert item.card.identifier == card.identifier
        mock_live.assert_not_called()

    def test_a_cold_pool_never_builds_inline_and_serves_nothing(self, db):
        """No `warm_pool_cache` call at all: every lane is a genuine cache miss. Data that would
        be servable if any lane had ever been warmed must still yield nothing - a cold cache is
        "no supply", never a signal to build the pool live on this request."""
        make_ai_suggested_card()  # would be a valid confirm-lane candidate, but nothing warmed it

        item = get_next_question_feed_item("anon-1")

        assert item is None

    def test_exhausting_this_voters_pool_entries_serves_nothing_else(self, db):
        card, printing = make_ai_suggested_card(anonymous_id="ai-bot")
        card.artist_vote_status = ArtistVoteStatus.RESOLVED
        card.save()
        warm_pool_cache(LANE_CONFIRM)
        # this voter already answered the only pooled candidate - the draw must exhaust and,
        # with no other data anywhere, the request has nothing left to serve
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="anon-1")

        item = get_next_question_feed_item("anon-1")

        assert item is None

    def test_a_resolved_card_falls_through_past_a_stale_pool_entry_to_a_freshly_warmed_lane(self, db):
        """Staleness: a card served by the confirm lane resolves between the pool's warm and
        this request. The pool draw must reject it (still `UNRESOLVED`-only), and the request
        must still get served from whatever else genuinely qualifies today - which itself must
        have been warmed, since a stale entry falling through no longer reaches a live scan."""
        stale_card, printing = make_ai_suggested_card(anonymous_id="ai-bot")
        warm_pool_cache(LANE_CONFIRM)
        stale_card.printing_tag_status = PrintingTagStatus.RESOLVED
        stale_card.artist_vote_status = ArtistVoteStatus.RESOLVED
        stale_card.save()
        fresh_card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _warm_all_lanes()

        item = get_next_question_feed_item("anon-1")

        assert item is not None
        assert item.card.identifier == fresh_card.identifier

    def test_shared_cache_not_configured_serves_nothing_rather_than_scanning_live(self, db):
        from django.test import override_settings

        make_ai_suggested_card()  # would be a valid confirm-lane candidate under a configured cache
        caches_without_shared = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        with override_settings(CACHES=caches_without_shared):
            item = get_next_question_feed_item("anon-1")

        assert item is None


class TestConfirmSuggestionSkipsEliminatedSuggestions:
    """ "Not this art" closes the loop at the ONE consumer this PR wires: a suggestion whose
    artwork the group has already reached elimination consensus on must not be re-served as a
    NEW confirm_suggestion question.

    Every vote here carries complete `evidence_types_used` (the `_evidence_justifies_
    confirmation` gate from #775, reading the vote directly per #797, passes), so a `None`
    result is attributable to elimination consensus, not to the gate - the gate failing would
    produce the same `None` for an unrelated reason and prove nothing about this feature."""

    def test_the_only_ai_vote_being_eliminated_yields_no_item(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        illustration_id = uuid.uuid4()
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            source=VoteSource.DEDUCTION,
            anonymous_id="ai-bot",
            evidence_types_used=list(_COMPLETE_EVIDENCE_TYPES),
        )
        for anonymous_id in ("voter-1", "voter-2"):
            CardIllustrationRejectionFactory(
                card=card, illustration_id=illustration_id, source=VoteSource.USER, anonymous_id=anonymous_id
            )

        assert _confirm_suggestion_item(card) is None

    def test_a_non_eliminated_suggestion_is_unaffected(self, db):
        card, printing = make_ai_suggested_card()

        item = _confirm_suggestion_item(card)

        assert item is not None
        assert item.suggestedPrinting.identifier == str(printing.identifier)

    def test_falls_through_to_a_second_ai_vote_once_the_first_is_eliminated(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        eliminated_illustration = uuid.uuid4()
        eliminated_printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=eliminated_printing, illustration_id=eliminated_illustration)
        CardPrintingTagFactory(
            card=card,
            printing=eliminated_printing,
            source=VoteSource.DEDUCTION,
            anonymous_id="calc-a-v1",
            evidence_types_used=list(_COMPLETE_EVIDENCE_TYPES),
        )
        for anonymous_id in ("voter-1", "voter-2"):
            CardIllustrationRejectionFactory(
                card=card, illustration_id=eliminated_illustration, source=VoteSource.USER, anonymous_id=anonymous_id
            )

        survivor_printing = CanonicalCardFactory()
        CardPrintingTagFactory(
            card=card,
            printing=survivor_printing,
            source=VoteSource.OCR,
            anonymous_id="calc-b-v1",
            evidence_types_used=list(_COMPLETE_EVIDENCE_TYPES),
        )

        item = _confirm_suggestion_item(card)

        assert item is not None
        assert item.suggestedPrinting.identifier == str(survivor_printing.identifier)


def _printing_with_border(name: str, border_color: str, illustration_id=None) -> None:
    """A live `CanonicalCard` candidate matching `name`, carrying `border_color` (and
    optionally `illustration_id`) on its metadata sidecar - the fixture `_likely_resolve_item`
    routing tests below use to control what `get_ranked_printing_candidates` returns."""
    printing = CanonicalCardFactory(name=name)
    CanonicalPrintingMetadataFactory(
        canonical_card=printing, border_color=border_color, illustration_id=illustration_id
    )


class TestIllustrationItem:
    """`_illustration_item` (wtc-question-model.md §7.2): asks which artwork a card depicts,
    deduplicating candidates that share an `illustration_id`. Returns `None` unless the
    deduplicated set is a genuine multi-way choice (at least two distinct illustrations) - a
    zero- or one-candidate result is not a choice for the grid UI to render."""

    def test_no_ranked_candidates_declines(self, db):
        """FAILS against pre-fix code, which built and returned a `QuestionFeedItem` with
        `illustrationCandidates=[]` here instead of declining."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        assert _illustration_item(card) is None

    def test_single_illustration_after_dedupe_declines(self, db):
        """FAILS against pre-fix code, which served this exact one-candidate-after-dedupe shape
        as a real illustration question."""
        card, _illustration_id = make_shared_illustration_group("Brainstorm")

        assert _illustration_item(card) is None

    def test_illustration_item_keeps_distinct_illustrations_separate(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _printing_with_border("Brainstorm", "black", illustration_id=uuid.uuid4())
        _printing_with_border("Brainstorm", "black", illustration_id=uuid.uuid4())

        item = _illustration_item(card)

        assert item is not None
        assert item.type.value == "illustration"
        assert item.card.name == card.name
        assert len(item.illustrationCandidates) == 2


class TestConfirmSuggestionMissingIllustrationTableDegrades:
    """The `eliminated_illustration_ids` read inside `_confirm_suggestion_item` is wrapped in a
    broad `except Exception` (see that function's own comment) so an absent
    `CardIllustrationRejection` table (a pre-migration environment) degrades to "nothing
    eliminated" instead of a 500."""

    def test_a_db_error_reading_elimination_consensus_degrades_rather_than_raising(self, db):
        card, printing = make_ai_suggested_card()
        # simulate the illustration_id branch being reached at all - a suggestion with no
        # illustration_id never calls `eliminated_illustration_ids` in the first place, so the
        # printing here must carry one for this test to actually exercise the guard.
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())

        with patch(
            "cardpicker.question_feed.eliminated_illustration_ids",
            side_effect=Exception('relation "cardpicker_cardillustrationrejection" does not exist'),
        ):
            item = _confirm_suggestion_item(card)

        assert item is not None
        assert item.suggestedPrinting.identifier == str(printing.identifier)


class TestLikelyResolveRouting:
    """`_likely_resolve_item`'s pool-dependent routing rule (docs/features/
    wtc-question-model.md): for the LIKELY-RESOLVE pool, serve the most discriminating question
    for THIS card - border first if it narrows the candidate set, illustration next, otherwise
    the pre-existing confirm/identify fallback."""

    def test_candidates_split_on_border_and_unrecorded_serves_border(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _printing_with_border("Brainstorm", "black")
        _printing_with_border("Brainstorm", "white")

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "border"

    def test_border_already_recorded_skips_border_even_when_candidates_split(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        card.tag_vote_statuses = {"Black Border": TagVoteStatus.RESOLVED_APPLY}
        card.save(update_fields=["tag_vote_statuses"])
        _printing_with_border("Brainstorm", "black")
        _printing_with_border("Brainstorm", "white")

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value != "border"

    def test_candidates_do_not_split_on_border_falls_through_to_illustration(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _printing_with_border("Brainstorm", "black", illustration_id=uuid.uuid4())
        _printing_with_border("Brainstorm", "black", illustration_id=uuid.uuid4())

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "illustration"

    def test_a_single_illustration_after_dedupe_falls_through_to_identify_printing(self, db):
        """FAILS against pre-fix code: two printings sharing ONE illustration_id dedupe to a
        single candidate, which `_illustration_item` used to serve as a real choice anyway."""
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        illustration_id = uuid.uuid4()
        _printing_with_border("Brainstorm", "black", illustration_id=illustration_id)
        _printing_with_border("Brainstorm", "black", illustration_id=illustration_id)

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "identify_printing"

    def test_illustration_already_resolved_falls_through_to_identify_printing(self, db):
        card = CardFactory(
            name="Brainstorm",
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            illustration_vote_status=IllustrationVoteStatus.RESOLVED,
        )
        illustration_id = uuid.uuid4()
        _printing_with_border("Brainstorm", "black", illustration_id=illustration_id)
        _printing_with_border("Brainstorm", "black", illustration_id=illustration_id)

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "identify_printing"

    def test_no_illustration_data_at_all_falls_through_to_identify_printing(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _printing_with_border("Brainstorm", "black")
        _printing_with_border("Brainstorm", "black")

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "identify_printing"

    def test_border_split_wins_over_an_unresolved_illustration(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        illustration_id = uuid.uuid4()
        _printing_with_border("Brainstorm", "black", illustration_id=illustration_id)
        _printing_with_border("Brainstorm", "white", illustration_id=illustration_id)

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "border"

    def test_a_machine_suggestion_is_still_confirmable_once_border_and_illustration_are_settled(self, db):
        card, printing = make_ai_suggested_card()
        card.illustration_vote_status = IllustrationVoteStatus.RESOLVED
        card.save(update_fields=["illustration_vote_status"])

        item = _likely_resolve_item(card, anonymous_id="anon-1")

        assert item.type.value == "confirm_suggestion"


class TestBorderPerVoterExclusion:
    """A voter's own answer to the border question must remove that card from their own future
    feed without affecting any other voter - `_voter_answered_border_card_ids` is the exclusion
    set `_likely_resolve_item` checks alongside the pre-existing catalogue-wide
    `_card_border_unrecorded` consensus gate."""

    def _split_card(self, name: str = "Brainstorm"):
        card = CardFactory(name=name, printing_tag_status=PrintingTagStatus.UNRESOLVED)
        _printing_with_border(name, "black")
        _printing_with_border(name, "white")
        return card

    def test_voter_who_voted_a_border_colour_is_not_served_border_again(self, db):
        card = self._split_card()
        CardTagVoteFactory(card=card, tag=TagFactory(name="Black Border"), anonymous_id="voter-1")

        item = _likely_resolve_item(card, anonymous_id="voter-1")

        assert item.type.value != "border"

    def test_a_different_voter_is_still_served_border(self, db):
        """Proves the exclusion is per-voter: a global exclusion would fail this too."""
        card = self._split_card()
        CardTagVoteFactory(card=card, tag=TagFactory(name="Black Border"), anonymous_id="voter-1")

        item = _likely_resolve_item(card, anonymous_id="voter-2")

        assert item.type.value == "border"

    def test_cannot_tell_abstention_excludes_the_voter_from_border(self, db):
        card = self._split_card()
        CardQuestionAbstention.objects.create(
            card=card, anonymous_id="voter-1", question_type="border", reason="cannot-tell"
        )

        item = _likely_resolve_item(card, anonymous_id="voter-1")

        assert item.type.value != "border"

    def test_cannot_tell_abstention_does_not_exclude_a_different_voter(self, db):
        card = self._split_card()
        CardQuestionAbstention.objects.create(
            card=card, anonymous_id="voter-1", question_type="border", reason="cannot-tell"
        )

        item = _likely_resolve_item(card, anonymous_id="voter-2")

        assert item.type.value == "border"

    def test_plain_skip_abstention_does_not_exclude_border(self, db):
        card = self._split_card()
        CardQuestionAbstention.objects.create(card=card, anonymous_id="voter-1", question_type="border", reason=None)

        item = _likely_resolve_item(card, anonymous_id="voter-1")

        assert item.type.value == "border"

    def test_voter_answered_border_card_ids_reads_any_of_the_four_colour_tags(self, db):
        card = self._split_card()
        CardTagVoteFactory(card=card, tag=TagFactory(name="Borderless"), anonymous_id="voter-1")

        assert card.pk in _voter_answered_border_card_ids("voter-1")
        assert card.pk not in _voter_answered_border_card_ids("voter-2")

    def test_voter_cannot_tell_card_ids_ignores_other_question_types(self, db):
        card = self._split_card()
        CardQuestionAbstention.objects.create(
            card=card, anonymous_id="voter-1", question_type="identify_printing", reason="cannot-tell"
        )

        assert card.pk not in _voter_cannot_tell_card_ids("voter-1", "border")
        assert card.pk in _voter_cannot_tell_card_ids("voter-1", "identify_printing")


def _make_border_split_likely_resolve_card(name: str = "Brainstorm"):
    """A card that is BOTH `is_likely_resolve_printing` (two agreeing OCR votes on one
    printing) AND has candidates that split on border colour with border unrecorded - the
    production shape (measured 2026-08-21: no card in the catalogue carries a RESOLVED_APPLY
    border-colour tag) that makes `_likely_resolve_item`'s border branch fire for every
    likely-resolve card whose candidates split on border, uncapped."""
    card = CardFactory(
        name=name, printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
    )
    black_printing = CanonicalCardFactory(name=name)
    CanonicalPrintingMetadataFactory(canonical_card=black_printing, border_color="black")
    CanonicalPrintingMetadataFactory(canonical_card=CanonicalCardFactory(name=name), border_color="white")
    CardPrintingTagFactory(card=card, printing=black_printing, source=VoteSource.OCR, anonymous_id="bot-1")
    CardPrintingTagFactory(card=card, printing=black_printing, source=VoteSource.OCR, anonymous_id="bot-2")
    return card


class TestLikelyResolveNarrowingCap:
    """`QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO`: caps how much of a session's own
    LIKELY-RESOLVE-pool servings may be a narrowing question (border/illustration) rather than
    a printing question (confirm_suggestion/identify_printing) - the pool whose entire purpose
    is serving a printing question one more vote would resolve. No card in the catalogue
    carries a RESOLVED_APPLY border-colour tag (measured 2026-08-21), so `_card_border_
    unrecorded` is true for every card and, uncapped, `_likely_resolve_item` serves `border`
    for every likely-resolve card whose candidates split on border - see
    `test_uncapped_routing_serves_zero_printing_questions_over_a_session` below, which
    reproduces that with `allow_narrowing` forced `True` the way the pre-fix code always ran."""

    def test_narrowing_ratio_is_zero_with_no_served_log_yet(self, db):
        assert _likely_resolve_narrowing_ratio("anon-1") == 0.0

    def test_narrowing_ratio_counts_only_likely_resolve_pool_rows(self, db):
        for _ in range(3):
            QuestionFeedServedLog.objects.create(
                anonymous_id="anon-1",
                pool=QuestionFeedServedPool.LIKELY_RESOLVE,
                question_type="border",
                origin_reason="printing_one_vote_from_resolving",
            )
        for _ in range(2):
            QuestionFeedServedLog.objects.create(
                anonymous_id="anon-1",
                pool=QuestionFeedServedPool.LIKELY_RESOLVE,
                question_type="identify_printing",
                origin_reason="printing_one_vote_from_resolving",
            )
        # a REMAINDER-pool row must not shift this ratio either way
        QuestionFeedServedLog.objects.create(
            anonymous_id="anon-1",
            pool=QuestionFeedServedPool.REMAINDER,
            question_type="border",
            origin_reason="tier_4_fresh_printing",
        )

        assert _likely_resolve_narrowing_ratio("anon-1") == 3 / 5

    def test_allow_narrowing_false_forces_a_printing_question_despite_a_border_split(self, db):
        card = _make_border_split_likely_resolve_card()

        item = _likely_resolve_item(card, allow_narrowing=False, anonymous_id="anon-1")

        assert item.type.value in ("confirm_suggestion", "identify_printing")

    def test_uncapped_routing_serves_zero_printing_questions_over_a_session(self, db):
        """Fails against the pre-fix code (no `allow_narrowing` gate existed - this always ran
        as if it were `True`): with the production shape (border split, border unrecorded) every
        one of 20 likely-resolve servings comes back `border`, never a printing question."""
        card = _make_border_split_likely_resolve_card()

        served_types = [
            _likely_resolve_item(card, allow_narrowing=True, anonymous_id="anon-1").type.value for _ in range(20)
        ]

        assert served_types == ["border"] * 20
        assert not any(t in ("confirm_suggestion", "identify_printing") for t in served_types)

    def test_capped_session_reaches_printing_questions_and_keeps_narrowing_present(self, db):
        """The fixed pipeline, end to end: `get_next_question_feed_item` over a 20-request
        session, with `_served_mix_ratio` forced to 0.0 so every request actually reaches the
        likely-resolve branch (isolating this test to the within-pool routing this change fixes,
        not the separate, already-covered `TestMixComposition` pool-selection ratio)."""
        _make_border_split_likely_resolve_card()
        _warm_all_lanes()

        with patch("cardpicker.question_feed._served_mix_ratio", return_value=0.0):
            served_types = [get_next_question_feed_item("anon-session").type.value for _ in range(20)]

        printing_types = {"confirm_suggestion", "identify_printing"}
        narrowing_types = {"border", "illustration"}
        printing_count = sum(1 for t in served_types if t in printing_types)
        narrowing_count = sum(1 for t in served_types if t in narrowing_types)

        assert printing_count > 0, f"expected non-zero printing questions, got {served_types}"
        assert narrowing_count > 0, f"expected narrowing questions to still appear, got {served_types}"
        # the cap bounds the LONG-RUN share at QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO
        # (0.5 by default); at N=20 the running ratio can overshoot by at most one serving's
        # worth before the next request's check reins it back in.
        assert narrowing_count / len(served_types) <= settings.QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO + 0.05


class TestTier4FreshServesIllustration:
    """The REMAINDER lane's own illustration-before-printing precedence
    (`_tier_4_fresh`/`_build_pool_cold`): a card whose illustration identity is unresolved and
    resolves to a genuine multi-way choice of artwork (`_illustration_item`) is answerable via
    the cheaper illustration question, ahead of `identify_printing`."""

    def test_a_remainder_card_with_two_illustrations_is_served_illustration(self, db):
        # `_tier_4_fresh`'s illustration filter reads `card.printing_tags` (an actual cast
        # vote), not `get_ranked_printing_candidates`' name-matched search results - unlike
        # `_likely_resolve_item`'s gate, so this fixture needs a real `CardPrintingTag` row. A
        # second, distinct-illustration printing of the same name is what makes the ranked
        # candidate set `_illustration_item` actually renders from a genuine multi-way choice.
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory(name="Brainstorm")
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        _printing_with_border("Brainstorm", "black", illustration_id=uuid.uuid4())

        result = _tier_4_fresh("anon-1")

        assert result is not None
        item, reason = result
        assert item.type.value == "illustration"
        assert reason == "tier_4_fresh_illustration"

    def test_a_remainder_card_with_a_single_illustration_falls_through_to_printing(self, db):
        """FAILS against pre-fix code: the coarse admission filter
        (`illustration_id__isnull=False` on SOME cast printing tag) admits this card, but the
        name-similarity search `_illustration_item` actually builds its answers from resolves to
        exactly one candidate here - a confirm wearing a chooser's clothes, not a real choice."""
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        illustration_id = uuid.uuid4()
        printing = CanonicalCardFactory(name="Brainstorm")
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")

        result = _tier_4_fresh("anon-1")

        assert result is not None
        item, reason = result
        assert item.type.value != "illustration"

    def test_a_remainder_card_with_no_illustration_data_falls_through_to_printing(self, db):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        result = _tier_4_fresh("anon-1")

        assert result is not None
        item, reason = result
        assert item.type.value != "illustration"


class TestIdentifyPrintingCandidateGate:
    """docs/features/wtc-question-model.md §5 rule 5: an `identify_printing` question with an
    empty candidate grid asks the voter to pick a printing from a set with no options. Reproduces
    the reported Urza's Saga defect (measured live 2026-08-22: ~10% of UNRESOLVED cards carry
    zero ranked printing candidates and were served this question anyway) directly against
    `_identify_printing_item`, the one function every serving path (live tiers and pools alike)
    builds this question through."""

    def test_declines_for_a_card_with_no_ranked_printing_candidates(self, db):
        """FAILS against pre-fix code, which built and returned a `QuestionFeedItem` with
        `candidates=[]` here instead of declining."""
        card = CardFactory()  # no matching CanonicalCard - get_ranked_printing_candidates() is []

        assert _identify_printing_item(card) is None

    def test_still_serves_a_card_with_a_ranked_printing_candidate(self, db):
        """The gate declines only an empty grid - a card with something to show is unaffected,
        proving this isn't a blanket disable of `identify_printing`."""
        card = CardFactory(name="Brainstorm")
        CanonicalCardFactory(name="Brainstorm")

        item = _identify_printing_item(card)

        assert item is not None
        assert item.type.value == "identify_printing"
        assert len(item.candidates) > 0

    def test_tier_2_contested_printing_skips_a_zero_candidate_card_for_a_servable_one(self, db):
        """Two contested printing cards in the same window - one with no ranked candidates, one
        with real candidates. The dead one must never win the tier; the servable one must.
        `dead_card`'s name is deliberately disjoint from every `CanonicalCardFactory` default
        name ("Canonical Card N", which contains the substring "card" every OTHER default
        `CardFactory` name also normalises to) - both cards' own default names would otherwise
        coincidentally cross-match on that shared word and defeat the fixture."""
        dead_card = CardFactory(name="Zzyzx Qwerty Unmatched", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=dead_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=dead_card, printing=CanonicalCardFactory(), source=VoteSource.USER)

        servable_card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CanonicalCardFactory(name="Brainstorm")
        CardPrintingTagFactory(card=servable_card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=servable_card, printing=CanonicalCardFactory(), source=VoteSource.USER)

        result = _tier_2_contested("anon-1")

        assert result is not None
        item, reason = result
        assert item.type.value == "identify_printing"
        assert item.card.identifier == servable_card.identifier

    def test_zero_candidate_kind_printing_cards_never_enter_the_contested_or_cold_pools(self, db):
        """Warm-time gate (`_build_pool_contested`/`_build_pool_cold`): a zero-candidate card
        must never be materialised into a `KIND_PRINTING` pool entry in the first place, since
        the pooled request path never re-derives item content before serving it."""
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        _warm_all_lanes()

        contested_entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED)) or []
        cold_entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD)) or []

        assert not any(entry.kind == "printing" for entry in contested_entries)
        assert not any(entry.kind == "printing" for entry in cold_entries)

    def test_confirm_suggestion_never_needs_the_ranked_candidate_list(self, db):
        """Considered per the task's own requirement: unlike identify_printing,
        confirm_suggestion's `suggestedPrinting` comes straight off the existing machine vote
        (`ai_vote.printing`), never off `get_ranked_printing_candidates` - so a card with zero
        ranked candidates can still be served a confirm_suggestion with something to act on.
        `card`'s and `printing`'s names are deliberately disjoint nonsense words (see
        `test_tier_2_contested_printing_skips_a_zero_candidate_card_for_a_servable_one`'s own
        comment for why an ordinary default-named fixture would coincidentally cross-match)."""
        card = CardFactory(name="Zzyzx Qwerty Unmatched", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory(name="Wholly Disjoint Printing")
        CardPrintingTagFactory(
            card=card,
            printing=printing,
            source=VoteSource.DEDUCTION,
            anonymous_id="ai-bot",
            evidence_types_used=list(_COMPLETE_EVIDENCE_TYPES),
        )

        item = _confirm_suggestion_item(card)

        assert item is not None
        assert item.suggestedPrinting.identifier == str(printing.identifier)
        assert item.candidates == []
