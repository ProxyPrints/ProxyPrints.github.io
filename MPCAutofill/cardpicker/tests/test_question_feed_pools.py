"""
Tests for `cardpicker.question_feed_pools` (issue #727) - the materialised, shared, per-lane
candidate pools backing `question_feed.get_next_question_feed_item`'s fast path. Uses the real
`settings.CACHES["shared"]` (`DatabaseCache`, provisioned by migration `0092_shared_cache_table`,
already present in the test database) rather than overriding `CACHES`, same convention
`test_catalog_stats.py`'s `TestWarmCatalogStatsCache` class uses for its own happy-path tests -
only `TestSharedCacheNotConfigured` below overrides it, to cover the pre-#538/#543 state.
"""

from unittest.mock import patch

import pytest

from django.core.cache import caches
from django.core.management import CommandError, call_command
from django.test import override_settings

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardScanLog,
    PrintingTagStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.question_feed_pools import (
    KIND_ARTIST,
    KIND_PRINTING,
    KIND_TAG,
    LANE_COLD,
    LANE_CONFIRM,
    LANE_CONTESTED,
    LANE_RESOLUTION_IMMINENT,
    SHARED_CACHE_ALIAS,
    PoolEntry,
    _cache_key,
    draw_cold_entry,
    draw_confirm_card,
    draw_contested_entry,
    draw_resolution_imminent_card,
    warm_pool_cache,
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


def make_one_vote_from_resolving_card() -> tuple:
    """Same shape as `test_question_feed.py`'s own helper of the same name: two machine (OCR)
    votes for the same printing - a hypothetical human vote clears `PRINTING_TAG_MIN_VOTES=2`
    outright, so this card is `is_likely_resolve_printing`."""
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="bot-1")
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="bot-2")
    return card, printing


def make_ai_suggested_card(anonymous_id: str = "ai-bot") -> tuple:
    card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
    printing = CanonicalCardFactory()
    CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id=anonymous_id)
    return card, printing


def make_contested_tag(tag_name: str = "Full Art") -> tuple:
    card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
    tag = TagFactory(name=tag_name)
    CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
    CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
    resolve_and_persist_tag_votes(card)
    card.refresh_from_db()
    return card, tag


class TestBuildPoolResolutionImminent:
    def test_includes_a_card_one_vote_from_resolving(self, db):
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_RESOLUTION_IMMINENT))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in entries

    def test_excludes_a_card_with_no_votes_at_all(self, db):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_RESOLUTION_IMMINENT))
        assert entries == []

    def test_is_not_scoped_to_any_particular_voter(self, db):
        """Pools are shared - building the pool does not take an anonymous_id, and two
        different voters draw from the exact same materialised entries."""
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)

        first = draw_resolution_imminent_card(answered_card_ids=set())
        second = draw_resolution_imminent_card(answered_card_ids=set())

        assert first is not None and first.pk == card.pk
        assert second is not None and second.pk == card.pk


class TestBuildPoolConfirm:
    def test_includes_a_machine_only_suggestion(self, db):
        card, _ = make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONFIRM))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in entries

    def test_excludes_a_card_with_a_human_vote_already(self, db):
        card, printing = make_ai_suggested_card()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        warm_pool_cache(LANE_CONFIRM)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONFIRM))
        assert entries == []


class TestBuildPoolContested:
    def test_includes_a_contested_printing_card(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        warm_pool_cache(LANE_CONTESTED)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in entries

    def test_includes_a_contested_artist_card(self, db):
        from cardpicker.artist_consensus import resolve_and_persist_artist

        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        resolve_and_persist_artist(card)
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED

        warm_pool_cache(LANE_CONTESTED)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED))
        assert PoolEntry(kind=KIND_ARTIST, card_id=card.pk) in entries

    def test_includes_a_contested_tag_pair(self, db):
        card, tag = make_contested_tag()
        warm_pool_cache(LANE_CONTESTED)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED))
        assert PoolEntry(kind=KIND_TAG, card_id=card.pk, tag_name=tag.name) in entries

    def test_excludes_a_plain_fresh_card(self, db):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        warm_pool_cache(LANE_CONTESTED)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED))
        assert entries == []


class TestBuildPoolCold:
    def test_includes_a_totally_fresh_card_with_the_fresh_reason(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk, reason="tier_4_fresh_printing") in entries

    def test_includes_a_quick_negative_card_with_the_quick_negative_reason(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        )
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk, reason="tier_4_quick_negative_to_review") in entries

    def test_excludes_a_contested_printing_card(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert all(entry.card_id != card.pk for entry in entries if entry.kind == KIND_PRINTING)

    def test_includes_a_fresh_artist_card(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_ARTIST, card_id=card.pk) in entries

    def test_includes_an_unresolved_tag_pair(self, db):
        card = CardFactory(
            tags=[], printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        tag = TagFactory(name="Etched")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_TAG, card_id=card.pk, tag_name=tag.name) in entries


class TestPoolSizeCap:
    def test_pool_is_capped_at_the_configured_size(self, db):
        # artist_vote_status=RESOLVED isolates these to the printing sub-list only - a fresh
        # CardFactory() defaults artist_vote_status to UNRESOLVED too, which would otherwise
        # also pool each card a second time via the cold lane's artist half.
        for _ in range(5):
            CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        with override_settings(QUESTION_FEED_POOL_SIZE=2):
            count = warm_pool_cache(LANE_COLD)
        assert count == 2
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert len([e for e in entries if e.kind == KIND_PRINTING]) == 2


class TestWarmPoolCacheValidation:
    def test_unknown_lane_raises_value_error(self, db):
        with pytest.raises(ValueError, match="Unknown question-feed pool lane"):
            warm_pool_cache("not-a-real-lane")

    def test_idempotent_on_repeat_runs(self, db):
        make_one_vote_from_resolving_card()
        first = warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        second = warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        assert first == second == 1


class TestDrawResolutionImminentCard:
    def test_excludes_a_card_this_voter_already_answered(self, db):
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        assert draw_resolution_imminent_card(answered_card_ids={card.pk}) is None

    def test_a_second_voters_own_exclusion_does_not_affect_a_first_voter(self, db):
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        assert draw_resolution_imminent_card(answered_card_ids={999999999}) is not None

    def test_returns_none_on_a_cache_miss(self, db):
        # never warmed - a fresh environment, or this lane hasn't fired its first schedule yet
        assert draw_resolution_imminent_card(answered_card_ids=set()) is None

    def test_a_resolved_card_is_excluded_at_read_time_even_though_still_pooled(self, db):
        """Staleness: the card resolved after the pool warmed - the read-time single-row check
        must catch this, not just serve whatever was cached."""
        card, printing = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        card.printing_tag_status = PrintingTagStatus.RESOLVED
        card.save()

        assert draw_resolution_imminent_card(answered_card_ids=set()) is None


class TestDrawConfirmCard:
    def test_returns_the_pooled_card(self, db):
        card, _ = make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)
        drawn = draw_confirm_card(answered_card_ids=set())
        assert drawn is not None
        assert drawn.pk == card.pk

    def test_excludes_a_card_this_voter_already_answered(self, db):
        card, _ = make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)
        assert draw_confirm_card(answered_card_ids={card.pk}) is None


class TestDrawContestedEntry:
    def test_returns_a_printing_entry(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        warm_pool_cache(LANE_CONTESTED)

        drawn = draw_contested_entry(set(), set(), {}, set())

        assert drawn is not None
        kind, drawn_card, tag_name, reason = drawn
        assert kind == KIND_PRINTING
        assert drawn_card.pk == card.pk
        assert tag_name is None

    def test_a_not_official_art_card_is_excluded_from_the_artist_half(self, db):
        from cardpicker.artist_consensus import resolve_and_persist_artist

        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        resolve_and_persist_artist(card)
        card.refresh_from_db()
        warm_pool_cache(LANE_CONTESTED)

        drawn = draw_contested_entry(set(), set(), {}, not_official_art_card_ids={card.pk})

        assert drawn is None

    def test_a_tag_entry_respects_the_per_tag_exclusion_dict(self, db):
        card, tag = make_contested_tag()
        warm_pool_cache(LANE_CONTESTED)

        # excluded for this specific tag
        assert draw_contested_entry(set(), set(), {tag.name: {card.pk}}, set()) is None
        # not excluded when the exclusion dict names a different tag
        drawn = draw_contested_entry(set(), set(), {"Some Other Tag": {card.pk}}, set())
        assert drawn is not None
        assert drawn[0] == KIND_TAG
        assert drawn[2] == tag.name

    def test_returns_none_on_a_cache_miss(self, db):
        assert draw_contested_entry(set(), set(), {}, set()) is None


class TestDrawColdEntry:
    def test_returns_a_printing_entry_with_its_precomputed_reason(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        )
        warm_pool_cache(LANE_COLD)

        drawn = draw_cold_entry("anon-1", set(), set(), contested_card_ids=[])

        assert drawn is not None
        kind, drawn_card, tag_name, reason = drawn
        assert kind == KIND_PRINTING
        assert drawn_card.pk == card.pk
        assert reason == "tier_4_quick_negative_to_review"

    def test_a_card_that_became_contested_since_the_warm_is_excluded_at_read_time(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        warm_pool_cache(LANE_COLD)  # pooled while still fresh

        drawn = draw_cold_entry("anon-1", set(), set(), contested_card_ids=[card.pk])

        assert drawn is None

    def test_artist_half_uses_an_unwidened_per_voter_check(self, db):
        """`_tier_4_fresh`'s own artist exclusion is deliberately UNWIDENED (own docstring) -
        the pool-backed draw must reproduce that, not the md5-widened convention."""
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), anonymous_id="anon-1")
        warm_pool_cache(LANE_COLD)

        assert draw_cold_entry("anon-1", set(), set(), contested_card_ids=[]) is None
        drawn = draw_cold_entry("anon-2", set(), set(), contested_card_ids=[])
        assert drawn is not None
        assert drawn[1].pk == card.pk

    def test_returns_none_on_a_cache_miss(self, db):
        assert draw_cold_entry("anon-1", set(), set(), contested_card_ids=[]) is None


_CACHES_WITHOUT_SHARED = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class TestSharedCacheNotConfigured:
    """Covers the pre-#538/#543 state - mirrors `test_catalog_stats.py`'s class of the same
    name exactly."""

    def test_draw_functions_return_none_without_raising(self, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            assert draw_resolution_imminent_card(answered_card_ids=set()) is None
            assert draw_confirm_card(answered_card_ids=set()) is None
            assert draw_contested_entry(set(), set(), {}, set()) is None
            assert draw_cold_entry("anon-1", set(), set(), contested_card_ids=[]) is None

    def test_warm_function_raises_a_clear_runtime_error_before_building_anything(self, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with patch("cardpicker.question_feed_pools._build_pool_confirm") as mock_build:
                with pytest.raises(RuntimeError, match="shared.*not configured"):
                    warm_pool_cache(LANE_CONFIRM)
                mock_build.assert_not_called()

    def test_warm_command_exits_non_zero_with_a_comprehensible_message(self, db):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with pytest.raises(CommandError, match="shared.*not configured"):
                call_command("warm_question_feed_pools", "confirm")


class TestWarmQuestionFeedPoolsCommand:
    def test_success_prints_a_summary(self, db, capsys):
        make_ai_suggested_card()
        call_command("warm_question_feed_pools", "confirm")
        output = capsys.readouterr().out
        assert "Question-feed pool warmed" in output
        assert "confirm" in output

    def test_rejects_an_unknown_lane(self, db):
        with pytest.raises(CommandError, match="invalid choice"):
            call_command("warm_question_feed_pools", "not-a-real-lane")
