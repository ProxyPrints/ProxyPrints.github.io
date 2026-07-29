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
"""

from unittest.mock import patch

import pytest

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.urls import reverse

from cardpicker.artist_external_links import (
    CACHE_KEY,
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
    MISSING_NAME_RECORD,
    SCHEME_LESS_RECORD,
    WHITESPACE_RECORD,
    raw_record,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


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
        assert set(_link_types(result)) <= {"website", "artstation", "inprnt", "mountainmage", "omalink"}

    def test_pure_socials_are_never_surfaced(self):
        result = normalise_artist_record(CLEAN_RECORD)
        for excluded in ("instagram", "twitter", "facebook", "youtube", "bluesky"):
            assert excluded not in _link_types(result)

    def test_patreon_is_never_surfaced(self):
        # patreon is a support channel, not a purchase/browse/signing link - excluded by owner
        # ruling even though it's a perfectly well-formed URL in the fixture.
        result = normalise_artist_record(CLEAN_RECORD)
        assert "patreon" not in _link_types(result)

    def test_priority_order_is_fixed_regardless_of_input_key_order(self):
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert _link_types(result) == ["website", "artstation", "inprnt", "mountainmage", "omalink"]

    def test_capped_at_five_links(self):
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert len(result["links"]) == 5

    def test_affiliate_query_parameter_is_preserved_verbatim(self):
        result = normalise_artist_record(FULL_ALLOWLIST_RECORD)
        assert _link_url(result, "omalink") == FULL_ALLOWLIST_RECORD["links"]["omalink"]
        assert "rfsn=" in _link_url(result, "omalink")


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
        cache.set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))
        assert get_cached_artist_external_links("Someone Else Entirely") == not_found_record()

    def test_returns_normalised_record_on_hit(self):
        cache.set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))
        result = get_cached_artist_external_links(CLEAN_RECORD["name"])
        assert result["found"] is True
        assert result["pageUrl"] == CLEAN_RECORD["pageUrl"]


class TestFetchBulkExport:
    """
    MTGAC's own disclosed limit on this endpoint is 12 requests/hour (2026-07-29). The tests
    below assert the no-retry guarantee directly at the `requests.get` boundary so a future
    "helpful" retry loop added to this function would fail these tests immediately, not just
    the docstring's own warning.
    """

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
        cached = cache.get(CACHE_KEY)
        assert cached is not None
        assert CLEAN_RECORD["name"] in cached

    def test_idempotent_on_repeat_runs(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            first = warm_artist_external_links_cache()
            second = warm_artist_external_links_cache()
        assert first == second
        assert cache.get(CACHE_KEY) == second

    def test_empty_export_raises_and_leaves_prior_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            warm_artist_external_links_cache()
        good_cache = cache.get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[]):
            with pytest.raises(ValueError):
                warm_artist_external_links_cache()

        assert cache.get(CACHE_KEY) == good_cache

    def test_fetch_failure_raises_and_leaves_prior_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            warm_artist_external_links_cache()
        good_cache = cache.get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", side_effect=OSError("network down")):
            with pytest.raises(OSError):
                warm_artist_external_links_cache()

        assert cache.get(CACHE_KEY) == good_cache

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


class TestWarmArtistExternalLinksCommand:
    def test_success_prints_a_summary(self, capsys):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
        output = capsys.readouterr().out
        assert "1 artists" in output

    def test_failure_exits_non_zero_and_leaves_cache_untouched(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
        good_cache = cache.get(CACHE_KEY)

        with patch("cardpicker.artist_external_links.fetch_bulk_export", side_effect=OSError("network down")):
            with pytest.raises(CommandError):
                call_command("warm_artist_external_links")

        assert cache.get(CACHE_KEY) == good_cache

    def test_re_running_after_success_is_safe(self):
        with patch("cardpicker.artist_external_links.fetch_bulk_export", return_value=[CLEAN_RECORD]):
            call_command("warm_artist_external_links")
            call_command("warm_artist_external_links")
        assert CLEAN_RECORD["name"] in cache.get(CACHE_KEY)

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


class TestGetArtistExternalLinksView:
    def test_cache_hit_for_an_indexed_artist_returns_normalised_links(self, client, django_settings):
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        cache.set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))

        response = client.get(reverse("get_artist_external_links"), {"name": artist.name})

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["pageUrl"] == CLEAN_RECORD["pageUrl"]
        assert data["hasSignatureService"] is True

    def test_cache_miss_returns_not_found_and_makes_no_outbound_call(self, client, django_settings):
        artist = CanonicalArtistFactory(name=CLEAN_RECORD["name"])
        assert cache.get(CACHE_KEY) is None

        with patch("cardpicker.artist_external_links.requests.get") as mock_get:
            response = client.get(reverse("get_artist_external_links"), {"name": artist.name})
            mock_get.assert_not_called()

        assert response.status_code == 200
        data = response.json()
        assert data == {"found": False, "pageUrl": None, "location": None, "links": [], "hasSignatureService": False}

    def test_artist_absent_from_canonical_artist_returns_not_found_even_if_cached(self, client, django_settings):
        # cache has real data for this name, but no CanonicalArtist row exists for it - this
        # endpoint must not be usable as a free-text lookup against the raw cached blob.
        cache.set(CACHE_KEY, compute_artist_external_links_blob([CLEAN_RECORD]))

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
