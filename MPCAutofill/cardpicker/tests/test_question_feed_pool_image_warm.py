"""
Tests for `question_feed_pools.warm_pool_images`/`_warm_entry_images` - the pool-image-warming
step (see `question_feed_pools.py`'s own comment block above those functions for the full
reasoning). Mirrors `test_image_cdn_fetch.py`'s own `monkeypatch.setattr(module, "rate_limited_get",
...)` convention rather than mocking `requests` directly, so these tests never touch the network.
"""


import cardpicker.question_feed_pools as module
from cardpicker.harvest_fetch_limiter import (
    DestinationThrottledError,
    GoogleFetchLockoutError,
)
from cardpicker.models import PrintingTagStatus
from cardpicker.question_feed_pools import (
    KIND_ARTIST,
    KIND_PRINTING,
    KIND_TAG,
    LANE_COLD,
    PoolEntry,
    warm_pool_cache,
    warm_pool_images,
)
from cardpicker.tests.factories import CardFactory


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class TestWarmEntryImages:
    def test_warms_every_distinct_card_once(self, db, monkeypatch):
        card_a = CardFactory()
        card_b = CardFactory()
        calls = []

        def _fake_get(config, url, **kwargs):
            calls.append(url)
            return _FakeResponse(200)

        monkeypatch.setattr(module, "rate_limited_get", _fake_get)

        entries = [
            PoolEntry(kind=KIND_PRINTING, card_id=card_a.pk),
            # Same card under a second kind - must be deduplicated, not fetched twice.
            PoolEntry(kind=KIND_ARTIST, card_id=card_a.pk),
            PoolEntry(kind=KIND_TAG, card_id=card_b.pk, tag_name="Full Art"),
        ]

        warmed = module._warm_entry_images(entries)

        assert warmed == 2
        assert len(calls) == 2
        assert all("/images/google_drive/small/" in url for url in calls)

    def test_empty_entries_makes_no_calls(self, db, monkeypatch):
        def _fail_if_called(config, url, **kwargs):
            raise AssertionError("should not be called for an empty entry list")

        monkeypatch.setattr(module, "rate_limited_get", _fail_if_called)
        assert module._warm_entry_images([]) == 0

    def test_lockout_aborts_the_rest_of_the_batch(self, db, monkeypatch):
        card_a = CardFactory()
        card_b = CardFactory()
        calls = []

        def _fake_get(config, url, **kwargs):
            calls.append(url)
            raise GoogleFetchLockoutError("locked out")

        monkeypatch.setattr(module, "rate_limited_get", _fake_get)

        warmed = module._warm_entry_images(
            [PoolEntry(kind=KIND_PRINTING, card_id=card_a.pk), PoolEntry(kind=KIND_PRINTING, card_id=card_b.pk)]
        )

        assert warmed == 0
        # Locked out on the first call - the second card must never be attempted.
        assert len(calls) == 1

    def test_throttled_card_is_skipped_not_fatal(self, db, monkeypatch):
        card_a = CardFactory()
        card_b = CardFactory()
        calls = []

        def _fake_get(config, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise DestinationThrottledError("throttled")
            return _FakeResponse(200)

        monkeypatch.setattr(module, "rate_limited_get", _fake_get)

        warmed = module._warm_entry_images(
            [PoolEntry(kind=KIND_PRINTING, card_id=card_a.pk), PoolEntry(kind=KIND_PRINTING, card_id=card_b.pk)]
        )

        assert warmed == 1
        assert len(calls) == 2

    def test_ordinary_exception_is_skipped_not_fatal(self, db, monkeypatch):
        card_a = CardFactory()
        card_b = CardFactory()
        calls = []

        def _fake_get(config, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise ConnectionError("transient network blip")
            return _FakeResponse(200)

        monkeypatch.setattr(module, "rate_limited_get", _fake_get)

        warmed = module._warm_entry_images(
            [PoolEntry(kind=KIND_PRINTING, card_id=card_a.pk), PoolEntry(kind=KIND_PRINTING, card_id=card_b.pk)]
        )

        assert warmed == 1
        assert len(calls) == 2

    def test_error_response_status_does_not_count_as_warmed(self, db, monkeypatch):
        card = CardFactory()
        monkeypatch.setattr(module, "rate_limited_get", lambda config, url, **kwargs: _FakeResponse(500))
        assert module._warm_entry_images([PoolEntry(kind=KIND_PRINTING, card_id=card.pk)]) == 0


class TestWarmPoolImages:
    def test_reads_back_the_just_warmed_pool(self, db, monkeypatch):
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        calls = []
        monkeypatch.setattr(
            module, "rate_limited_get", lambda config, url, **kwargs: calls.append(url) or _FakeResponse(200)
        )

        warm_pool_cache(LANE_COLD)
        warmed = warm_pool_images(LANE_COLD)

        assert warmed == len(calls)
        assert warmed >= 1

    def test_never_warmed_lane_is_a_noop(self, db, monkeypatch):
        def _fail_if_called(config, url, **kwargs):
            raise AssertionError("should not be called - lane was never warmed")

        monkeypatch.setattr(module, "rate_limited_get", _fail_if_called)
        assert warm_pool_images(LANE_COLD) == 0
