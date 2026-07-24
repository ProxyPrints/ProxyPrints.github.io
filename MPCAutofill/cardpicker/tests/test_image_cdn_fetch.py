"""
`fetch_card_image`'s lockout carve-out (Stage B red-team correction, 2026-07-19,
docs/features/catalog-completion-plan.md's "Harvest-calculate pipeline" section): a
GoogleFetchLockoutError (403 hard stop) must survive the function's broad
`except Exception: return None` around ordinary fetch failures, or a long-running harvest would
silently keep hammering a destination that has already locked it out.
"""

import pytest

import cardpicker.image_cdn_fetch as module
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.tests.factories import CardFactory


class TestFetchCardImageLockoutCarveOut:
    def test_lockout_error_propagates_not_swallowed(self, db, monkeypatch):
        card = CardFactory()

        def _raise_lockout(config, url, **kwargs):
            raise GoogleFetchLockoutError("locked out")

        monkeypatch.setattr(module, "rate_limited_get", _raise_lockout)

        with pytest.raises(GoogleFetchLockoutError):
            module.fetch_card_image(card)

    def test_ordinary_exception_still_returns_none(self, db, monkeypatch):
        card = CardFactory()

        def _raise_ordinary(config, url, **kwargs):
            raise ConnectionError("transient network blip")

        monkeypatch.setattr(module, "rate_limited_get", _raise_ordinary)

        assert module.fetch_card_image(card) is None
