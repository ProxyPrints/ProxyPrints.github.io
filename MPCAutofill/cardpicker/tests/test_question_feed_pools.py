"""
Tests for `cardpicker.question_feed_pools` (issue #727) - the materialised, shared, per-lane
candidate pools backing `question_feed.get_next_question_feed_item`'s fast path. Uses the real
`settings.CACHES["shared"]` (`DatabaseCache`, provisioned by migration `0092_shared_cache_table`,
already present in the test database) rather than overriding `CACHES`, same convention
`test_catalog_stats.py`'s `TestWarmCatalogStatsCache` class uses for its own happy-path tests -
only `TestSharedCacheNotConfigured` below overrides it, to cover the pre-#538/#543 state.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from django.core.cache import caches
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
)
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardScanLog,
    IllustrationVoteStatus,
    PrintingTagStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.question_feed import _question_information_gain_score
from cardpicker.question_feed_pools import (
    KIND_ARTIST,
    KIND_ILLUSTRATION,
    KIND_PRINTING,
    KIND_TAG,
    LANE_COLD,
    LANE_CONFIRM,
    LANE_CONTESTED,
    LANE_RESOLUTION_IMMINENT,
    SHARED_CACHE_ALIAS,
    PoolEntry,
    _cache_key,
    _get_cached_pool,
    _live_information_gain_score,
    _pool_sample_chunk_size,
    _precomputed_information_gain_score,
    _sample_across_pk_strata,
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
    CanonicalPrintingMetadataFactory,
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


_COMPLETE_EVIDENCE_TYPES = ("border", "artist", "symbol")


def make_ai_suggested_card(
    anonymous_id: str = "ai-bot", evidence_types_used: tuple = _COMPLETE_EVIDENCE_TYPES
) -> tuple:
    """See `test_question_feed.py`'s own helper of the same name: `evidence_types_used` (issue
    #766's evidence gate on `confirm_suggestion`) lives on the suggestion vote itself, not on a
    `CardScanLog` row - a MATCH never writes one (issue #797)."""
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


def make_contested_tag(tag_name: str = "Full Art") -> tuple:
    card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
    tag = TagFactory(name=tag_name)
    CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, anonymous_id="crowd-1")
    CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, anonymous_id="crowd-2")
    resolve_and_persist_tag_votes(card)
    card.refresh_from_db()
    return card, tag


def without_scores(pool_entries) -> list:
    """`PoolEntry`s with the warm-time `score` field stripped - builder-membership assertions
    check the candidate identity (`kind`/`card_id`/`tag_name`/`reason`), never the precomputed
    score itself, so building the expected entry without a score must still match."""
    return [PoolEntry(kind=e.kind, card_id=e.card_id, tag_name=e.tag_name, reason=e.reason) for e in pool_entries]


class TestBuildPoolResolutionImminent:
    def test_includes_a_card_one_vote_from_resolving(self, db):
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_RESOLUTION_IMMINENT))
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in without_scores(entries)

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
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in without_scores(entries)

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
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk) in without_scores(entries)

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
        assert PoolEntry(kind=KIND_ARTIST, card_id=card.pk) in without_scores(entries)

    def test_includes_a_contested_tag_pair(self, db):
        card, tag = make_contested_tag()
        warm_pool_cache(LANE_CONTESTED)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_CONTESTED))
        assert PoolEntry(kind=KIND_TAG, card_id=card.pk, tag_name=tag.name) in without_scores(entries)

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
        assert PoolEntry(kind=KIND_PRINTING, card_id=card.pk, reason="tier_4_fresh_printing") in without_scores(entries)

    def test_includes_a_quick_negative_card_with_the_quick_negative_reason(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason=JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON
        )
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(
            kind=KIND_PRINTING, card_id=card.pk, reason="tier_4_quick_negative_to_review"
        ) in without_scores(entries)

    def test_excludes_a_contested_printing_card(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert all(entry.card_id != card.pk for entry in entries if entry.kind == KIND_PRINTING)

    def test_includes_an_illustration_candidate(self, db):
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory(name="Brainstorm")
        illustration_id = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_ILLUSTRATION, card_id=card.pk, reason="tier_4_fresh_illustration") in without_scores(
            entries
        )

    def test_excludes_a_card_with_no_illustration_data_at_all(self, db):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert all(entry.card_id != card.pk for entry in entries if entry.kind == KIND_ILLUSTRATION)

    def test_includes_a_fresh_artist_card(self, db):
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.RESOLVED, artist_vote_status=ArtistVoteStatus.UNRESOLVED
        )
        warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        assert PoolEntry(kind=KIND_ARTIST, card_id=card.pk) in without_scores(entries)

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
        assert PoolEntry(kind=KIND_TAG, card_id=card.pk, tag_name=tag.name) in without_scores(entries)


class TestPoolSamplesAcrossImportBatches:
    """Covers the pooling defect this module's own `_sample_across_pk_strata` exists to fix: a
    naive `.order_by(<field>)[:limit]` builder returns one import batch, since cards imported
    together share both a close pk range and a `date_created`. Uses the cold lane's artist
    sub-list (a plain DB-filtered `Card.objects.filter(artist_vote_status=...)`, no per-candidate
    Python check) so every qualifying row is deterministically included, making the batch-mix
    guarantees below structural rather than probabilistic."""

    def _make_batch(self, count: int, date_created: datetime) -> list[int]:
        return [
            CardFactory(
                date_created=date_created,
                artist_vote_status=ArtistVoteStatus.UNRESOLVED,
                printing_tag_status=PrintingTagStatus.RESOLVED,
            ).pk
            for _ in range(count)
        ]

    def test_spans_more_than_one_batch_when_the_population_does(self, db):
        """5 batches of 20 cards each, each batch confined to its own pk range and
        `date_created`. With `QUESTION_FEED_POOL_SIZE=30`, filling the pool needs at least 5 of
        the module's 10 pk-space windows (`_pool_sample_chunk_size(30)` caps each window's yield
        at 6); since a 20-card batch spans only 2 of those windows, touching 5 windows forces at
        least 3 distinct batches to contribute - guaranteed by the numbers, not by luck."""
        batches = [self._make_batch(20, datetime(2023, 1, 1) + timedelta(days=day)) for day in range(5)]
        with override_settings(QUESTION_FEED_POOL_SIZE=30):
            warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        pooled_pks = {entry.card_id for entry in entries if entry.kind == KIND_ARTIST}
        touched_batches = sum(1 for batch in batches if pooled_pks & set(batch))
        assert touched_batches > 1

    def test_successive_warms_of_an_unchanged_population_are_not_identical(self, db):
        """Same population and pool size as above, unchanged across 5 independent warms.
        `_POOL_SAMPLE_STRATA=10` gives `C(10, 5) = 252` distinct 5-window combinations for this
        draw, so 5 independent warms landing on the exact same combination every time is
        vanishingly unlikely - this only reproduces the pre-fix "always the same 500" symptom if
        the window shuffle has stopped varying."""
        for day in range(5):
            self._make_batch(20, datetime(2023, 1, 1) + timedelta(days=day))
        snapshots = set()
        with override_settings(QUESTION_FEED_POOL_SIZE=30):
            for _ in range(5):
                warm_pool_cache(LANE_COLD)
                entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
                snapshots.add(frozenset(entry.card_id for entry in entries if entry.kind == KIND_ARTIST))
        assert len(snapshots) > 1


class TestPoolSamplingPreservesQualifyingSet:
    def test_sampling_never_pools_a_non_qualifying_card(self, db):
        """Cards that DO and DON'T qualify interleaved by pk (alternating), across several
        `date_created` values - so every pk-space window the sampler visits contains a mix, and
        a boundary bug in window filtering would leak a non-qualifying card into the pool."""
        qualifying_pks: set[int] = set()
        for day in range(4):
            date_created = datetime(2023, 1, 1) + timedelta(days=day)
            for _ in range(15):
                qualifying_pks.add(
                    CardFactory(
                        date_created=date_created,
                        artist_vote_status=ArtistVoteStatus.UNRESOLVED,
                        printing_tag_status=PrintingTagStatus.RESOLVED,
                    ).pk
                )
                CardFactory(
                    date_created=date_created,
                    artist_vote_status=ArtistVoteStatus.RESOLVED,
                    printing_tag_status=PrintingTagStatus.RESOLVED,
                )
        with override_settings(QUESTION_FEED_POOL_SIZE=30):
            warm_pool_cache(LANE_COLD)
        entries = caches[SHARED_CACHE_ALIAS].get(_cache_key(LANE_COLD))
        pooled_pks = {entry.card_id for entry in entries if entry.kind == KIND_ARTIST}
        assert pooled_pks <= qualifying_pks
        assert len(pooled_pks) == 30


class TestPoolSampleCostBounded:
    def test_query_count_does_not_scale_with_population_size(self, db):
        """`_sample_across_pk_strata`'s own query count - `_POOL_SAMPLE_STRATA` pk-space windows
        plus one bounds lookup - must stay identical whether the qualifying population is 15 rows
        or 315, since it's sized off `_POOL_SAMPLE_STRATA`/`chunk_size`, never off how many rows
        actually match. Starts at 15 (not fewer) so the pk range already meets
        `_POOL_SAMPLE_STRATA`'s own window count on the small side too - a population smaller
        than `_POOL_SAMPLE_STRATA` legitimately uses fewer, wider windows to avoid querying empty
        ones, which is a different (and already covered) property from cost staying flat once
        that clamp is no longer in play."""
        for _ in range(15):
            CardFactory(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        queryset = Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED).values_list("pk", flat=True)
        chunk_size = _pool_sample_chunk_size(30)
        with CaptureQueriesContext(connection) as small_population:
            list(_sample_across_pk_strata(queryset, chunk_size=chunk_size))

        for _ in range(300):
            CardFactory(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        with CaptureQueriesContext(connection) as large_population:
            list(_sample_across_pk_strata(queryset, chunk_size=chunk_size))

        assert len(large_population.captured_queries) == len(small_population.captured_queries)


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


class TestNoInlineBuildOnCacheMiss:
    """A cache miss (never warmed, evicted, or the `"shared"` backend unavailable) must mean
    "no supply for this request", never trigger a live pool build - the exact Parallel Seq Scan
    (issue #726/#727) pooling exists to move off the request path."""

    def test_get_cached_pool_returns_none_without_calling_any_builder(self, db):
        make_one_vote_from_resolving_card()  # real data a builder WOULD find, if ever called
        with patch("cardpicker.question_feed_pools._build_pool_resolution_imminent") as mock_build:
            assert _get_cached_pool(LANE_RESOLUTION_IMMINENT) is None
            mock_build.assert_not_called()

    def test_draw_confirm_card_never_builds_inline_on_a_cold_cache(self, db):
        make_ai_suggested_card()  # a real confirm-lane candidate, never warmed
        with patch("cardpicker.question_feed_pools._build_pool_confirm") as mock_build:
            assert draw_confirm_card(answered_card_ids=set()) is None
            mock_build.assert_not_called()


class TestScoresPrecomputedAtWarmTime:
    """A draw must perform no vote-query scoring on the request path - scoring is paid once per
    pooled entry at WARM time (`PoolEntry.score`). Before the 2026-08-16 change, every draw
    scored its window live (`_question_information_gain_score` costs several vote queries per
    candidate - measured 288-791 queries / 9.1-9.6s per draw against live production data), the
    exact per-request cost pooling exists to avoid paying."""

    def test_draw_of_a_warm_pool_performs_no_scoring(self, db):
        from cardpicker.question_feed import _CANDIDATE_SCORING_WINDOW

        for _ in range(_CANDIDATE_SCORING_WINDOW + 20):
            CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED)
        warm_pool_cache(LANE_COLD)  # scoring is paid here, once per pooled entry

        with patch(
            "cardpicker.question_feed._question_information_gain_score", wraps=_question_information_gain_score
        ) as mock_score:
            drawn = draw_cold_entry("anon-1", set(), set(), contested_card_ids=[])

        assert mock_score.call_count == 0  # the draw sorts by precomputed scores only
        assert drawn is not None

    def test_precomputed_score_matches_the_live_score_for_the_same_state(self, db):
        """The request-path fallback (`_live_information_gain_score`, serving a v1 pool that
        warms out during this change's deploy) must compute exactly what the warm-time
        precompute stored, and the precompute must route identically whether the builder already
        held the `Card` or had to fetch it - both wrap `_question_information_gain_score` with
        the same `(kind, card, tag_name)` call, differing only in whether the routing happened
        at build time or at draw time."""
        card, _ = make_one_vote_from_resolving_card()  # real votes, so the score is non-degenerate
        expected = _question_information_gain_score(KIND_PRINTING, card, None)
        assert _precomputed_information_gain_score(KIND_PRINTING, card.pk, card=card) == expected
        assert _precomputed_information_gain_score(KIND_PRINTING, card.pk) == expected  # fetch path
        assert _live_information_gain_score(PoolEntry(kind=KIND_PRINTING, card_id=card.pk)) == expected


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

    def test_excludes_a_card_this_voter_hid_for_themselves(self, db):
        """Issue #714: the draw-time analogue of `_tier_4_fresh`/tier 1's hidden-card
        exclusion - a hidden card is skipped even though it is still pooled."""
        card, _ = make_one_vote_from_resolving_card()
        warm_pool_cache(LANE_RESOLUTION_IMMINENT)

        assert draw_resolution_imminent_card(answered_card_ids=set(), hidden_card_ids={card.pk}) is None
        # no hidden exclusion = still served, for this voter or any other
        assert draw_resolution_imminent_card(answered_card_ids=set()) is not None


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

    def test_excludes_a_card_this_voter_hid_for_themselves(self, db):
        card, _ = make_ai_suggested_card()
        warm_pool_cache(LANE_CONFIRM)

        assert draw_confirm_card(answered_card_ids=set(), hidden_card_ids={card.pk}) is None


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

    def test_an_artist_resolved_since_the_warm_is_excluded_at_read_time(self, db):
        """The artist-half analogue of the printing-half staleness checks above: resolution
        happens after the pool warmed, so the draw's per-candidate read-time filter
        (`Card.objects.filter(pk=..., artist_vote_status=ArtistVoteStatus.CONTESTED)`) must catch
        it - the same guarantee the pre-pool bare `get_contested_artist_card_ids()` call
        (removed 2026-08-16) used to provide at request-start."""
        from cardpicker.artist_consensus import resolve_and_persist_artist

        card = CardFactory(printing_tag_status=PrintingTagStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=CanonicalArtistFactory(), source=VoteSource.USER)
        resolve_and_persist_artist(card)
        card.refresh_from_db()
        assert card.artist_vote_status == ArtistVoteStatus.CONTESTED
        warm_pool_cache(LANE_CONTESTED)

        card.artist_vote_status = ArtistVoteStatus.RESOLVED
        card.save()

        assert draw_contested_entry(set(), set(), {}, set()) is None

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

    def test_a_hidden_card_is_excluded_from_the_printing_half(self, db):
        """Issue #714: the card-level hidden exclusion applies across every contested kind -
        the printing half is the common case, the artist/tag halves share the same entry-level
        skip (asserted via the cold lane's equivalent test below)."""
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        warm_pool_cache(LANE_CONTESTED)

        assert draw_contested_entry(set(), set(), {}, set(), hidden_card_ids={card.pk}) is None

    def test_returns_none_on_a_cache_miss(self, db):
        assert draw_contested_entry(set(), set(), {}, set()) is None


class TestDrawColdEntry:
    def test_returns_an_illustration_entry_ahead_of_printing(self, db):
        """KIND_ILLUSTRATION leads `_iter_by_kind_precedence` - a card with illustration data
        available is served that instead of `identify_printing`, even though both entries are
        pooled for the same card."""
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory(name="Brainstorm")
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        warm_pool_cache(LANE_COLD)

        drawn = draw_cold_entry("anon-1", set(), set(), contested_card_ids=[])

        assert drawn is not None
        kind, drawn_card, tag_name, reason = drawn
        assert kind == KIND_ILLUSTRATION
        assert drawn_card.pk == card.pk
        assert reason == "tier_4_fresh_illustration"

    def test_an_illustration_entry_resolved_since_the_warm_falls_through_to_printing(self, db):
        # `card` is pooled under BOTH KIND_ILLUSTRATION and KIND_PRINTING (it is also a plain
        # unresolved printing card) - once its illustration resolves mid-warm-cycle, the stale
        # illustration entry is skipped at read time and the waterfall falls through to the
        # still-valid printing entry for the same card, not to `None`.
        card = CardFactory(name="Brainstorm", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        printing = CanonicalCardFactory(name="Brainstorm")
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ai-bot")
        warm_pool_cache(LANE_COLD)  # pooled while still unresolved
        card.illustration_vote_status = IllustrationVoteStatus.RESOLVED
        card.save(update_fields=["illustration_vote_status"])

        drawn = draw_cold_entry("anon-1", set(), set(), contested_card_ids=[])

        assert drawn is not None
        kind, drawn_card, tag_name, reason = drawn
        assert kind == KIND_PRINTING
        assert drawn_card.pk == card.pk

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

    def test_a_hidden_card_is_excluded(self, db):
        """Issue #714: the cold lane's card-level hidden exclusion, keyed on the same
        entry-level skip as the contested lane."""
        card = CardFactory(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, artist_vote_status=ArtistVoteStatus.RESOLVED
        )
        warm_pool_cache(LANE_COLD)

        assert draw_cold_entry("anon-1", set(), set(), contested_card_ids=[], hidden_card_ids={card.pk}) is None
        # no hidden exclusion = still served
        assert draw_cold_entry("anon-1", set(), set(), contested_card_ids=[]) is not None

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
