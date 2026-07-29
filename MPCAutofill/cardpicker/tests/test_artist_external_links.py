"""
Tests for cardpicker.artist_external_links (the MTGAC daily-cached bulk consumer, M1 - see that
module's own docstring) and cardpicker.views.get_artist_external_links.

Normaliser tests use synthetic fixtures from cardpicker.tests.mtgac_synthetic_fixtures - see that
module's own docstring for why (no real MTGAC data is committed to this repo). They cover the
hazards catalogued in that module's/the feature's own docs: boolean-string-shaped values, email
addresses in link fields, scheme-less URLs, whitespace, bare non-URL text, the fixed allowlist
priority order and 5-cap, affiliate parameter preservation, and the signature-service flag.

Endpoint tests need `db` (CanonicalArtist lookups) and therefore the Postgres testcontainer this
project's conftest.py spins up - may be blocked by port conflicts on a shared box; the normaliser/
cache/command tests below do not need `db` at all and should always be runnable.

Cache setup: this feature reads/writes the NAMED `"shared"` cache alias (`SHARED_CACHE_ALIAS`),
deliberately not Django's `default` (see cardpicker.artist_external_links's own module docstring
for why). `_shared_cache_configured` (autouse) provisions a real `"shared"` LocMemCache alias for
every test in this file by default - the state this feature actually runs under once issue #538's
infrastructure PR lands. `TestSharedCacheNotConfigured` overrides this per-test with its own
`override_settings(CACHES=...)` that omits `"shared"` entirely, to cover the pre-#538 state.

Opt-in setup: `settings.MTGAC_BULK_URL` defaults to empty in `MPCAutofill/settings.py` (owner
requirement, 2026-07-29 - see `cardpicker.artist_external_links`'s own "Opt-in, per instance"
docstring section) - empty means the whole integration is off. `_bulk_url_configured` (autouse)
sets it to a dummy configured value for every test in this file by default, so the pre-existing
fetch/cache/command/endpoint tests below keep exercising the CONFIGURED state they were written
for. `TestBulkUrlNotConfigured` and `TestWarmArtistExternalLinksCommandNotConfigured` override it
back to empty per-test to cover the opt-out state instead.
"""

from unittest.mock import patch

import pytest

from django.core.cache import caches
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.urls import reverse

from cardpicker.artist_external_links import (
    CACHE_KEY,
    SHARED_CACHE_ALIAS,
    bulk_url_configured,
    compute_artist_external_links_blob,
    fetch_bulk_export,
    get_cached_artist_external_links,
    normalise_artist_record,
    not_found_record,
    warm_artist_external_links_cache,
)
from cardpicker.tests.factories import CanonicalArtistFactory
from cardpicker.tests.mtgac_synthetic_fixtures import (
    BARE_TEXT_RECORD,
    BOOLEAN_FLAG_RECORD,
    CLEAN_RECORD,
    EMAIL_IN_TWITTER_RECORD,
    EMAIL_IN_WEBSITE_RECORD,
    FULL_ALLOWLIST_RECORD,
    HANDLE_URL_RECORD,
    INSTAGRAM_ONLY_RECORD,
    MISSING_NAME_RECORD,
    SCHEME_LESS_RECORD,
    WHITESPACE_RECORD,
    raw_record,
)

# A real "shared" cache alias, distinct from "default" - matches the post-#538 shape this feature
# is designed for. Tests that need the "shared" alias to be ABSENT (the pre-#538 degradation
# path) override CACHES themselves with a dict that omits "shared" entirely - see
# TestSharedCacheNotConfigured below.
_TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "shared": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-artist-external-links-shared",
    },
}


@pytest.fixture(autouse=True)
def _shared_cache_configured():
    with override_settings(CACHES=_TEST_CACHES):
        caches["default"].clear()
        caches[SHARED_CACHE_ALIAS].clear()
        yield
        caches["default"].clear()
        caches[SHARED_CACHE_ALIAS].clear()


# A dummy, deliberately non-real URL - opting these tests into the CONFIGURED state without ever
# risking a real request landing on MTGAC's actual endpoint (every outbound call in this file is
# mocked/patched regardless, but this is a second line of defence).
_TEST_BULK_URL = "https://mtgac-bulk.example.invalid/api/public/artists"


@pytest.fixture(autouse=True)
def _bulk_url_configured(settings):
    """
    `settings.MTGAC_BULK_URL` defaults to empty (owner requirement - see
    cardpicker.artist_external_links's "Opt-in, per instance" docstring section), which would make
    every pre-existing fetch/cache/command/endpoint test below fail immediately with the new
    "not configured" guard. This autouse fixture opts every test in this file into the CONFIGURED
    state by default; tests that specifically cover the opt-out state set it back to "" themselves
    (pytest-django's `settings` fixture restores the real value after each test either way).
    """
    settings.MTGAC_BULK_URL = _TEST_BULK_URL


def _link_types(record: dict) -> list[str]:
    return [link["type"] for link in record["links"]]


def _link_url(record: dict, link_type: str) -> str:
    return next(link["url"] for link in record["links"] if link["type"] == link_type)


class TestNormaliseArtistRecordHappyPath:
    def test_found_is_true(self):
        assert normalise_artist_record(CLEAN_RECORD)["found"] is True

    def test_page_url_and_location_are_carried_through(self):
        result = normalise_artist_record(CLEAN_RECORD)
        assert result["pageUrl"] == CLEAN_RECORD["pageUrl"]
        assert result["location"] == CLEAN_RECORD["location"]

    def test_website_link_is_surfaced(self):
        result = normalise_artist_record(CLEAN_RECORD)
        assert _link_url(result, "website") == CLEAN_RECORD["website"]


class TestNormaliseArtistRecordBooleanFlagHazard:
    """`markssignatureservice` is a flag ("true"/"false"), not a link; `mountainmage` uses the
    literal string "false" to mean "not offered" - neither should ever become an href."""

    def test_markssignatureservice_never_appears_as_a_link(self):
        result = normalise_artist_record(CLEAN_RECORD)
        assert "markssignatureservice" not in _link_types(result)

    def test_markssignatureservice_true_surfaces_as_a_boolean_flag(self):
        assert normalise_artist_record(CLEAN_RECORD)["hasSignatureService"] is True

    def test_markssignatureservice_false_surfaces_as_a_boolean_flag(self):
        assert normalise_artist_record(BOOLEAN_FLAG_RECORD)["hasSignatureService"] is False

    def test_markssignatureservice_missing_defaults_to_false(self):
        result = normalise_artist_record(raw_record("No Flag", website="https://example.invalid/"))
        assert result["hasSignatureService"] is False

    def test_mountainmage_url_form_is_kept(self):
        result = normalise_artist_record(CLEAN_RECORD)
        assert _link_url(result, "mountainmage") == CLEAN_RECORD["links"]["mountainmage"]

    def test_mountainmage_literal_false_is_dropped_not_rendered_as_href_false(self):
        result = normalise_artist_record(BOOLEAN_FLAG_RECORD)
        assert "mountainmage" not in _link_types(result)


class TestNormaliseArtistRecordEmailHazard:
    """Email addresses filed in a link field are dropped unconditionally - mandatory, no
    exceptions, per owner ruling."""

    def test_email_in_website_drops_that_slot_entirely(self):
        result = normalise_artist_record(EMAIL_IN_WEBSITE_RECORD)
        assert "website" not in _link_types(result)

    def test_email_in_website_does_not_block_other_allowlisted_fields(self):
        result = normalise_artist_record(EMAIL_IN_WEBSITE_RECORD)
        assert "artstation" in _link_types(result)

    def test_email_in_twitter_is_never_surfaced(self):
        # twitter isn't in the allowlist at all, so this is a belt-and-suspenders check at the
        # cleaning-function level, not just "excluded field never appears".
        from cardpicker.artist_external_links import _clean_url_value

        assert _clean_url_value(EMAIL_IN_TWITTER_RECORD["links"]["twitter"]) is None

    def test_record_with_email_in_twitter_still_surfaces_its_clean_website(self):
        result = normalise_artist_record(EMAIL_IN_TWITTER_RECORD)
        assert _link_url(result, "website") == EMAIL_IN_TWITTER_RECORD["website"]


class TestNormaliseArtistRecordSchemeCheckedBeforeEmailHeuristic:
    """
    Regression coverage for a real bug: `_EMAIL_RE` (`^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$`) matches
    any single-`@` string whose right-hand side contains a dot - not just emails. A scheme-ful
    handle-style URL (YouTube/TikTok/Bluesky @handles, e.g.
    `https://www.example.com/@some.handle` - a real value of exactly this shape was confirmed in
    the export during this fix's own investigation, not reproduced here per this project's
    synthetic-fixtures policy) satisfies that same shape and was silently dropped as if it were
    an email when the email test ran before the scheme check. The fix reorders
    `_clean_url_value` to check for a URL scheme FIRST - a scheme-ful value is a URL by
    construction and is never email-tested - and applies the email heuristic ONLY to genuinely
    scheme-less input, which is the actual failure mode it defends against.
    """

    def test_scheme_ful_handle_style_url_survives_normalisation(self):
        from cardpicker.artist_external_links import _clean_url_value

        assert _clean_url_value("https://www.example.com/@some.handle") == "https://www.example.com/@some.handle"

    def test_record_with_a_handle_style_website_surfaces_it_as_a_link(self):
        result = normalise_artist_record(HANDLE_URL_RECORD)
        assert _link_url(result, "website") == HANDLE_URL_RECORD["website"]

    def test_bare_scheme_less_email_is_still_dropped(self):
        # The actual failure mode the email heuristic exists for must still be caught.
        from cardpicker.artist_external_links import _clean_url_value

        assert _clean_url_value("someone@example.invalid") is None


class TestNormaliseArtistRecordSchemeLessUrls:
    def test_scheme_less_website_gets_https_prefix(self):
        result = normalise_artist_record(SCHEME_LESS_RECORD)
        assert _link_url(result, "website") == "https://ezrafenwick.example"

    def test_scheme_less_artstation_gets_https_prefix(self):
        result = normalise_artist_record(SCHEME_LESS_RECORD)
        assert _link_url(result, "artstation") == "https://artstation.example/ezrafenwick"


class TestNormaliseArtistRecordWhitespace:
    def test_leading_and_trailing_whitespace_and_newline_are_stripped(self):
        result = normalise_artist_record(WHITESPACE_RECORD)
        assert _link_url(result, "inprnt") == "https://www.inprnt.example/gallery/fiora"


class TestNormaliseArtistRecordBareText:
    def test_bare_non_url_text_is_dropped(self):
        result = normalise_artist_record(BARE_TEXT_RECORD)
        assert "artstation" not in _link_types(result)

    def test_bare_non_url_text_does_not_block_other_fields(self):
        result = normalise_artist_record(BARE_TEXT_RECORD)
        assert "website" in _link_types(result)


class TestNormaliseArtistRecordAllowlistAndPriority:
    def test_only_allowlisted_field_types_are_ever_present(self):
        result = normalise_artist_record(CLEAN_RECORD)
        assert set(_link_types(result)) <= {
            "website",
            "artstation",
            "inprnt",
            "mountainmage",
            "omalink",
            "instagram",
        }

    def test_pure_socials_are_never_surfaced(self):
        # `instagram` is deliberately NOT in this list (owner ruling, added after the initial
        # allowlist) - it's allowlisted now, just last-priority; see
        # TestNormaliseArtistRecordInstagramLastResort below for its own coverage. CLEAN_RECORD
        # separately demonstrates instagram getting capped out by 5 higher-priority commerce
        # links present in the same fixture (test_only_allowlisted_field_types_are_ever_present
        # plus test_capped_at_five_links below cover that combination).
        result = normalise_artist_record(CLEAN_RECORD)
        for excluded in ("twitter", "facebook", "youtube", "bluesky"):
            assert excluded not in _link_types(result)

    def test_patreon_is_never_surfaced(self):
        # patreon is a support channel, not a purchase/browse/signing link - excluded by owner
        # ruling even though it's a perfectly well-formed URL in the fixture.
        result = normalise_artist_record(CLEAN_RECORD)
        assert "patreon" not in _link_types(result)

    def test_priority_order_is_fixed_regardless_of_input_key_order(self):
        # FULL_ALLOWLIST_RECORD has all 6 allowlisted fields populated (5 commerce + instagram) -
        # this also proves instagram is LAST priority and gets capped out below.
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert _link_types(result) == ["website", "artstation", "inprnt", "mountainmage", "omalink"]

    def test_capped_at_five_links(self):
        # Six real allowlisted candidates present (the first time this combination is even
        # possible, now that instagram joined the allowlist) - the cap must still hold at 5.
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert len(result["links"]) == 5

    def test_affiliate_query_parameter_is_preserved_verbatim(self):
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert _link_url(result, "omalink") == FULL_ALLOWLIST_RECORD["links"]["omalink"]
        assert "rfsn=" in _link_url(result, "omalink")


class TestNormaliseArtistRecordInstagramLastResort:
    """
    `instagram` is a deliberate LAST-priority exception to the commerce-only allowlist (owner
    ruling, added after the initial allowlist): not a purchase/browse/signing surface itself, but
    allowlisted anyway because it rescues 157 of the 812 artists who would otherwise have zero
    links at all, while never crowding out a real commerce link for an artist who has one (being
    last in priority means the 5-cap always favours the 5 commerce fields first).
    """

    def test_artist_whose_only_link_is_instagram_surfaces_it(self):
        # The exact 157-artist scenario this exception exists for.
        result = normalise_artist_record(INSTAGRAM_ONLY_RECORD)
        assert _link_types(result) == ["instagram"]
        assert _link_url(result, "instagram") == INSTAGRAM_ONLY_RECORD["links"]["instagram"]

    def test_instagram_is_included_when_it_fits_within_the_cap(self):
        record = raw_record(
            "Wren Fairholt",
            website="https://wrenfairholt.example/",
            links={"instagram": "https://www.instagram.example/wrenfairholt/"},
        )
        result = normalise_artist_record(record)
        assert _link_types(result) == ["website", "instagram"]

    def test_instagram_never_crowds_out_a_higher_priority_commerce_link(self):
        # Six real candidates (FULL_ALLOWLIST_RECORD) - instagram is dropped, every commerce
        # field survives. Same fixture/assertion as TestNormaliseArtistRecordAllowlistAndPriority's
        # own priority-order test, restated here under this exception's own dedicated class for
        # discoverability.
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert "instagram" not in _link_types(result)
        assert len(result["links"]) == 5


class TestComputeArtistExternalLinksBlob:
    def test_blob_is_keyed_by_artist_name(self):
        blob = compute_artist_external_links_blob([CLEAN_RECORD, BOOLEAN_FLAG_RECORD])
        assert set(blob.keys()) == {CLEAN_RECORD["name"], BOOLEAN_FLAG_RECORD["name"]}

    def test_records_with_missing_or_blank_name_are_skipped(self):
        blob = compute_artist_external_links_blob([CLEAN_RECORD, MISSING_NAME_RECORD])
        assert len(blob) == 1
        assert CLEAN_RECORD["name"] in blob


class TestNotFoundRecord:
    def test_shape(self):
        assert not_found_record() == {
            "found": False,
            "pageUrl": None,
            "location": None,
            "links": [],
            "hasSignatureService": False,
        }


class TestGetCachedArtistExternalLinks:
    def test_returns_not_found_when_cache_is_entirely_empty(self):
        assert get_cached_artist_external_links("Aurelia Thistledown") == not_found_record()

    def test_returns_not_found_when_artist_absent_from_populated_blob(self):
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))
        assert get_cached_artist_external_links("Someone Else Entirely") == not_found_record()

    def test_returns_normalised_record_on_hit(self):
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))
        result = get_cached_artist_external_links(CLEAN_RECORD["name"])
        assert result["found"] is True
        assert result["pageUrl"] == CLEAN_RECORD["pageUrl"]


# CACHES with no "shared" alias at all - simulates every environment before issue #538's
# infrastructure PR lands, regardless of what the real settings.py currently has (deliberately
# NOT relying on "the real settings.py just happens to lack `shared` today", which would silently
# start testing the wrong thing the moment that PR merges).
_CACHES_WITHOUT_SHARED = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class TestSharedCacheNotConfigured:
    """
    Covers the pre-#538 state: the named `"shared"` cache alias doesn't exist in `CACHES` at
    all. `caches["shared"]` raises `InvalidCacheBackendError` in this state - the read path must
    swallow it and degrade to an ordinary not-found response (never a 500), while the warm
    command must NOT swallow it (a cron run that silently writes nowhere while reporting success
    is exactly the bug this feature originally shipped with).
    """

    def test_read_path_returns_not_found_without_raising(self):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            result = get_cached_artist_external_links(CLEAN_RECORD["name"])
        assert result == not_found_record()

    def test_read_path_makes_no_outbound_call_either(self):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with patch("cardpicker.artist_external_links.requests.get") as mock_get:
                get_cached_artist_external_links(CLEAN_RECORD["name"])
                mock_get.assert_not_called()

    def test_endpoint_returns_not_found_shape_not_a_500(self, client, django_settings):
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            response = client.get(reverse("get_artist_external_links"), {"name": artist.name})
        assert response.status_code == 200
        assert response.json() == {
            "found": False,
            "pageUrl": None,
            "location": None,
            "links": [],
            "hasSignatureService": False,
        }

    def test_warm_function_raises_a_clear_runtime_error_before_any_outbound_call(self):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with patch("cardpicker.artist_external_links.requests.get") as mock_get:
                with pytest.raises(RuntimeError, match="shared.*not configured"):
                    warm_artist_external_links_cache()
                # resolved BEFORE fetching, so a misconfigured environment never wastes any of
                # MTGAC's rate-limit budget on a fetch it couldn't have written down anyway.
                mock_get.assert_not_called()

    def test_warm_command_exits_non_zero_with_a_comprehensible_message(self):
        with override_settings(CACHES=_CACHES_WITHOUT_SHARED):
            with pytest.raises(CommandError, match="shared.*not configured"):
                call_command("warm_artist_external_links")


class TestBulkUrlConfigured:
    """
    `bulk_url_configured()` is the single knob gating the whole MTGAC integration - see
    `cardpicker.artist_external_links`'s "Opt-in, per instance" docstring section. One knob, not
    two: there is no separate enable flag, only whether `MTGAC_BULK_URL` is set.
    """

    def test_false_when_unset(self, settings):
        settings.MTGAC_BULK_URL = ""
        assert bulk_url_configured() is False

    def test_true_when_set(self, settings):
        settings.MTGAC_BULK_URL = _TEST_BULK_URL
        assert bulk_url_configured() is True

    def test_reflects_settings_changes_immediately(self, settings):
        # Read at call time, not cached at import time - an operator flipping the env var (or a
        # test using override_settings/the `settings` fixture) must see the new state right away.
        settings.MTGAC_BULK_URL = ""
        assert bulk_url_configured() is False
        settings.MTGAC_BULK_URL = _TEST_BULK_URL
        assert bulk_url_configured() is True


class TestFetchBulkExport:
    """
    MTGAC's own disclosed limit on this endpoint is 12 requests/hour (2026-07-29). The tests
    below assert the no-retry guarantee directly at the `requests.get` boundary so a future
    "helpful" retry loop added to this function would fail these tests immediately, not just
    the docstring's own warning.
    """

    def test_calls_the_url_from_settings(self, settings):
        settings.MTGAC_BULK_URL = _TEST_BULK_URL
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.json.return_value = [CLEAN_RECORD]
            mock_get.return_value.raise_for_status.return_value = None
            fetch_bulk_export()
            assert mock_get.call_args.args[0] == _TEST_BULK_URL

    def test_raises_on_non_list_json(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"not": "a list"}
            mock_get.return_value.raise_for_status.return_value = None
            with pytest.raises(ValueError):
                fetch_bulk_export()

    def test_propagates_http_errors(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = OSError("boom")
            with pytest.raises(OSError):
                fetch_bulk_export()

    def test_successful_fetch_makes_exactly_one_outbound_call(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.json.return_value = [CLEAN_RECORD]
            mock_get.return_value.raise_for_status.return_value = None
            fetch_bulk_export()
            mock_get.assert_called_once()

    def test_failed_fetch_makes_exactly_one_outbound_call_and_does_not_retry(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = OSError("network down")
            with pytest.raises(OSError):
                fetch_bulk_export()
            mock_get.assert_called_once()


class TestWarmArtistExternalLinksCache:
    def test_writes_normalised_blob_to_cache(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            warm_artist_external_links_cache()
        cached = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)
        assert cached is not None
        assert CLEAN_RECORD["name"] in cached

    def test_idempotent_on_repeat_runs(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            first = warm_artist_external_links_cache()
            second = warm_artist_external_links_cache()
        assert first == second
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == second

    def test_empty_export_raises_and_leaves_prior_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            warm_artist_external_links_cache()
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[]):
            with pytest.raises(ValueError):
                warm_artist_external_links_cache()

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache

    def test_fetch_failure_raises_and_leaves_prior_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            warm_artist_external_links_cache()
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", side_effect=OSError("network down")):
            with pytest.raises(OSError):
                warm_artist_external_links_cache()

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache

    def test_successful_run_makes_exactly_one_outbound_call(self):
        # Patched at requests.get, not fetch_bulk_export, so this exercises the REAL
        # fetch_bulk_export end-to-end - MTGAC's disclosed bulk-endpoint limit is 12/hour, and
        # this is the guarantee that a single warm run never costs more than 1 against it.
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.json.return_value = [CLEAN_RECORD]
            mock_get.return_value.raise_for_status.return_value = None
            warm_artist_external_links_cache()
            mock_get.assert_called_once()

    def test_failed_run_makes_exactly_one_outbound_call_and_does_not_retry(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = OSError("network down")
            with pytest.raises(OSError):
                warm_artist_external_links_cache()
            mock_get.assert_called_once()


class TestWarmArtistExternalLinksCacheNotConfigured:
    """
    `warm_artist_external_links_cache`'s own opt-in guard (defense in depth - the management
    command checks `bulk_url_configured()` itself first and normally never reaches this function
    at all on an unconfigured instance, see `TestWarmArtistExternalLinksCommandNotConfigured`).
    """

    def test_raises_runtime_error_before_any_outbound_call(self, settings):
        settings.MTGAC_BULK_URL = ""
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            with pytest.raises(RuntimeError, match="not configured"):
                warm_artist_external_links_cache()
            mock_get.assert_not_called()

    def test_does_not_touch_the_shared_cache_backend_at_all(self, settings):
        # Checked even before resolving the shared cache backend, so an unconfigured instance
        # can't fail this a different, more confusing way (e.g. issue #538's error) instead.
        settings.MTGAC_BULK_URL = ""
        with patch("cardpicker.artist_external_links._shared_cache_for_write") as mock_shared:
            with pytest.raises(RuntimeError, match="not configured"):
                warm_artist_external_links_cache()
            mock_shared.assert_not_called()


class TestWarmArtistExternalLinksCommand:
    def test_success_prints_a_summary(self, capsys):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
        output = capsys.readouterr().out
        assert "1 artists" in output

    def test_failure_exits_non_zero_and_leaves_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
        good_cache = caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", side_effect=OSError("network down")):
            with pytest.raises(CommandError):
                call_command("warm_artist_external_links")

        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) == good_cache

    def test_re_running_after_success_is_safe(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
            call_command("warm_artist_external_links")
        assert CLEAN_RECORD["name"] in caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)

    def test_one_command_invocation_makes_exactly_one_outbound_call_on_success(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.json.return_value = [CLEAN_RECORD]
            mock_get.return_value.raise_for_status.return_value = None
            call_command("warm_artist_external_links")
            mock_get.assert_called_once()

    def test_one_command_invocation_makes_exactly_one_outbound_call_on_failure_no_retry(self):
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = OSError("network down")
            with pytest.raises(CommandError):
                call_command("warm_artist_external_links")
            mock_get.assert_called_once()


class TestWarmArtistExternalLinksCommandNotConfigured:
    """
    THE safety story for a fresh/non-opted-in instance running this command on the weekly
    schedule (migration 0093) forever: it must no-op cleanly, not fail. See the command's own
    module docstring and `cardpicker.artist_external_links`'s "Opt-in, per instance" section.
    """

    def test_exits_zero_no_exception(self, settings):
        settings.MTGAC_BULK_URL = ""
        # `call_command` re-raises on non-zero/`CommandError` - this simply must not raise.
        call_command("warm_artist_external_links")

    def test_prints_a_clear_skip_message(self, settings, capsys):
        settings.MTGAC_BULK_URL = ""
        call_command("warm_artist_external_links")
        output = capsys.readouterr().out
        assert "not configured" in output
        assert "skipping" in output

    def test_makes_no_outbound_call(self, settings):
        settings.MTGAC_BULK_URL = ""
        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            call_command("warm_artist_external_links")
            mock_get.assert_not_called()

    def test_does_not_touch_the_cache(self, settings):
        settings.MTGAC_BULK_URL = ""
        call_command("warm_artist_external_links")
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) is None

    def test_configured_instance_behaviour_is_unchanged(self, settings, capsys):
        # Negative control: flipping MTGAC_BULK_URL back on must restore the pre-existing
        # success-path behaviour exactly (TestWarmArtistExternalLinksCommand's own coverage),
        # proving the opt-in check doesn't leak into the configured path.
        settings.MTGAC_BULK_URL = _TEST_BULK_URL
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
        output = capsys.readouterr().out
        assert "1 artists" in output
        assert CLEAN_RECORD["name"] in caches[SHARED_CACHE_ALIAS].get(CACHE_KEY)


class TestGetArtistExternalLinksView:
    def test_cache_hit_for_an_indexed_artist_returns_normalised_links(self, client, django_settings):
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))

        response = client.get(reverse("get_artist_external_links"), {"name": artist.name})

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["pageUrl"] == CLEAN_RECORD["pageUrl"]
        assert data["hasSignatureService"] is True

    def test_cache_miss_returns_not_found_and_makes_no_outbound_call(self, client, django_settings):
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) is None

        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            response = client.get(reverse("get_artist_external_links"), {"name": artist.name})
            mock_get.assert_not_called()

        assert response.status_code == 200
        data = response.json()
        assert data == {"found": False, "pageUrl": None, "location": None, "links": [], "hasSignatureService": False}

    def test_artist_absent_from_canonical_artist_returns_not_found_even_if_cached(self, client, django_settings):
        # cache has real data for this name, but no CanonicalArtist row exists for it - this
        # endpoint must not be usable as a free-text lookup against the raw cached blob.
        caches[SHARED_CACHE_ALIAS].set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))

        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            response = client.get(reverse("get_artist_external_links"), {"name": CLEAN_RECORD["name"]})
            mock_get.assert_not_called()

        assert response.status_code == 200
        assert response.json()["found"] is False

    def test_missing_name_query_param_is_a_bad_request(self, client, django_settings):
        response = client.get(reverse("get_artist_external_links"))
        assert response.status_code == 400

    def test_post_is_rejected(self, client, django_settings):
        response = client.post(reverse("get_artist_external_links"))
        assert response.status_code == 400

    def test_rate_limited_after_exceeding_the_configured_rate(self, client, django_settings, settings):
        settings.ARTIST_EXTERNAL_LINKS_RATE = "1/m"
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])

        first = client.get(reverse("get_artist_external_links"), {"name": artist.name})
        second = client.get(reverse("get_artist_external_links"), {"name": artist.name})

        assert first.status_code == 200
        assert second.status_code == 429


class TestGetArtistExternalLinksViewOnAnUnconfiguredInstance:
    """
    THE whole safety story for a fresh/non-opted-in instance (owner requirement, 2026-07-29): with
    `MTGAC_BULK_URL` unset, the cache is simply never warmed (the weekly command no-ops, see
    `TestWarmArtistExternalLinksCommandNotConfigured`), so this read endpoint - which never calls
    upstream on its own, configured or not - must degrade to its ordinary not-found response
    exactly like any other cold cache, never raise, and the frontend's existing fallback to
    `buildArtistSupportURL` (`ArtistSupportLink.tsx`) takes over unchanged.
    """

    def test_returns_not_found_shape_not_an_error(self, client, django_settings, settings):
        settings.MTGAC_BULK_URL = ""
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        assert caches[SHARED_CACHE_ALIAS].get(CACHE_KEY) is None  # never warmed

        response = client.get(reverse("get_artist_external_links"), {"name": artist.name})

        assert response.status_code == 200
        assert response.json() == {
            "found": False,
            "pageUrl": None,
            "location": None,
            "links": [],
            "hasSignatureService": False,
        }

    def test_makes_no_outbound_call(self, client, django_settings, settings):
        settings.MTGAC_BULK_URL = ""
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])

        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            client.get(reverse("get_artist_external_links"), {"name": artist.name})
            mock_get.assert_not_called()
