import re

import pytest
import requests

from django.core.cache import cache
from django.urls import reverse

from cardpicker.views import (
    MTGAC_API_BASE_URL,
    MTGAC_SOURCE_NAME,
    _mtgac_cache_key,
    _mtgac_artist_api_url,
)

ARTIST_NAME = "Aaron Miller"
UNKNOWN_ARTIST_NAME = "Not A Real Artist"
ARTIST_URL_PATTERN = re.compile(r"/api/public/artist/")

MTGAC_ARTIST_PAYLOAD = {
    "name": "Aaron Miller",
    "pageUrl": "https://www.mtgartistconnection.com/artist/Aaron%20Miller",
    "location": "Illinois, US",
    "website": "https://www.aaronbmiller.com/",
    "links": {
        "facebook": "https://www.facebook.com/aaronbmiller",
        "instagram": "https://www.instagram.com/aaronmiller/",
        "patreon": "https://www.patreon.com/aaronmiller",
        "markssignatureservice": "true",
        "mountainmage": "false",
    },
}

EMPTY_PAYLOAD = {
    "links": [],
    "source": MTGAC_SOURCE_NAME,
    "sourceUrl": _mtgac_artist_api_url(UNKNOWN_ARTIST_NAME),
}


@pytest.fixture(autouse=True)
def _clear_artist_links_cache():
    keys = [_mtgac_cache_key(ARTIST_NAME), _mtgac_cache_key(UNKNOWN_ARTIST_NAME)]
    cache.delete_many(keys)
    yield
    cache.delete_many(keys)


def _get_links(client, name=ARTIST_NAME):
    return client.get(reverse("get_artist_external_links"), {"artist_name": name})


class TestArtistExternalLinksSuccess:
    def test_maps_upstream_payload_to_links(self, client, requests_mock):
        # Given MTGAC knows the artist
        requests_mock.get(ARTIST_URL_PATTERN, json=MTGAC_ARTIST_PAYLOAD)

        # When the proxy is queried
        response = _get_links(client)

        # Then the upstream payload is mapped onto the frontend's link shape
        assert response.status_code == 200
        data = response.json()
        assert data["source"] == MTGAC_SOURCE_NAME
        assert data["sourceUrl"] == f"{MTGAC_API_BASE_URL}/api/public/artist/Aaron%20Miller"

        by_label = {link["label"]: link for link in data["links"]}
        for link in data["links"]:
            assert set(link.keys()) == {"label", "url"}
        assert by_label["Website"] == {"label": "Website", "url": "https://www.aaronbmiller.com/"}
        assert by_label["Facebook"] == {"label": "Facebook", "url": "https://www.facebook.com/aaronbmiller"}
        assert by_label["Patreon"] == {"label": "Patreon", "url": "https://www.patreon.com/aaronmiller"}
        assert by_label[MTGAC_SOURCE_NAME]["url"] == (
            "https://www.mtgartistconnection.com/artist/Aaron%20Miller"
        )
        # "true"/"false" marker values are not URLs and must not surface as links
        assert "Mark's Signature Service" not in by_label
        assert "Mountain Mage" not in by_label

    def test_result_is_cached(self, client, requests_mock):
        # Given MTGAC knows the artist
        matcher = requests_mock.get(ARTIST_URL_PATTERN, json=MTGAC_ARTIST_PAYLOAD)

        # When the proxy is queried twice
        first = _get_links(client)
        second = _get_links(client)

        # Then the second response is served from cache without another upstream call
        assert first.json() == second.json()
        assert matcher.call_count == 1
        assert cache.get(_mtgac_cache_key(ARTIST_NAME)) is not None

    def test_name_is_url_decoded_and_forwarded_quoted(self, client, requests_mock):
        # Given MTGAC knows the artist
        matcher = requests_mock.get(ARTIST_URL_PATTERN, json=MTGAC_ARTIST_PAYLOAD)

        # When the proxy is queried with a name containing a space
        response = _get_links(client)

        # Then the upstream request path contains the percent-quoted artist name
        assert response.status_code == 200
        assert matcher.call_count == 1
        assert matcher.last_request.path == "/api/public/artist/Aaron%20Miller"


class TestArtistExternalLinksGracefulDegradation:
    def test_unknown_artist_returns_empty_links_and_caches(self, client, requests_mock):
        # Given MTGAC does not list the artist
        matcher = requests_mock.get(ARTIST_URL_PATTERN, status_code=404, json={"error": "Artist not found"})

        # When the proxy is queried twice
        first = _get_links(client, name=UNKNOWN_ARTIST_NAME)
        second = _get_links(client, name=UNKNOWN_ARTIST_NAME)

        # Then a graceful empty payload is returned, and the definitive 404 is cached
        assert first.status_code == 200
        assert first.json() == EMPTY_PAYLOAD
        assert second.json() == EMPTY_PAYLOAD
        assert matcher.call_count == 1
        assert cache.get(_mtgac_cache_key(UNKNOWN_ARTIST_NAME)) is not None

    def test_upstream_unreachable_returns_empty_links_without_caching(self, client, requests_mock):
        # Given MTGAC cannot be reached
        requests_mock.get(ARTIST_URL_PATTERN, exc=requests.ConnectionError)

        # When the proxy is queried
        response = _get_links(client)

        # Then it degrades gracefully, and the transient failure is NOT cached
        assert response.status_code == 200
        assert response.json() == {
            "links": [],
            "source": MTGAC_SOURCE_NAME,
            "sourceUrl": _mtgac_artist_api_url(ARTIST_NAME),
        }
        assert cache.get(_mtgac_cache_key(ARTIST_NAME)) is None

    def test_upstream_500_returns_empty_links_without_caching(self, client, requests_mock):
        # Given MTGAC is erroring
        requests_mock.get(ARTIST_URL_PATTERN, status_code=500, text="boom")

        # When the proxy is queried
        response = _get_links(client)

        # Then it degrades gracefully, and the transient failure is NOT cached
        assert response.status_code == 200
        assert response.json() == {
            "links": [],
            "source": MTGAC_SOURCE_NAME,
            "sourceUrl": _mtgac_artist_api_url(ARTIST_NAME),
        }
        assert cache.get(_mtgac_cache_key(ARTIST_NAME)) is None


class TestArtistExternalLinksValidation:
    def test_missing_artist_name_returns_400(self, client):
        response = client.get(reverse("get_artist_external_links"))
        assert response.status_code == 400

    def test_blank_artist_name_returns_400(self, client):
        response = client.get(reverse("get_artist_external_links"), {"artist_name": "  "})
        assert response.status_code == 400

    def test_post_returns_400(self, client):
        response = client.post(reverse("get_artist_external_links"), {"artist_name": ARTIST_NAME})
        assert response.status_code == 400
