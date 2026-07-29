"""
MTG Artist Connection (MTGAC) external-link consumer, M1 (backend only - see
docs/features/artist-support-links.md).

**Architecture: a DAILY-CACHED BULK CONSUMER, not a per-request proxy.** MTGAC offered this
project an embed (declined - no-third-party-embeds posture) and a data endpoint (accepted). This
module makes ONE outbound call per day (via `warm_artist_external_links_cache`, run from the
`warm_artist_external_links` management command on a cron - see that command's docstring) against
MTGAC's bulk export, normalises it once, and writes the result to Django's cache. Nothing in the
request-serving path (`get_cached_artist_external_links`, and `views.get_artist_external_links`
which wraps it) ever calls upstream - a per-request proxy would be functionally closer to the
embed MTGAC's operator already offered and this project already declined, and would turn this
site into an enumerable mirror of their directory.

**Storage: Django cache ONLY.** No model, no migration - deliberate, not an oversight. This is
third-party data whose licence terms are still an open question (tracked separately), so a
refreshable cache is the right posture rather than a permanent copy in our own database. Follows
the `funnel-counts-v1` pattern already established in `views.py` (`get_funnel_counts`), with one
structural difference: funnel-counts computes AND caches inline, in the same request that serves
it; this feature's cache is instead populated by a SEPARATE management-command invocation.

**Shared cache-backend prerequisite (issue #538, not this module's to fix).** This module uses
the standard Django cache framework, same as `get_funnel_counts` and `cardpicker.review_clusters`
- both of which work correctly today under this project's default `LocMemCache`, because gunicorn
runs a single worker (`docker/django/Dockerfile`'s `CMD` has no `--workers` flag) and the SAME
process both writes and later reads its own cache. This feature is different in one specific way,
independent of worker count: `warm_artist_external_links` runs as a separate `manage.py`
invocation (a cron entry) - a DIFFERENT OS process from the running web server regardless of
worker count - so its cache writes are never visible to the process serving
`2/artistExternalLinks/` requests. Until a shared backend is configured, this endpoint returns
its not-found fallback on every request (safe degradation - the frontend falls back to today's
existing behaviour) while the cron itself reports success every run. Tracked as issue #538
(filed generically, since the unbuilt vote-stats design would have the same cross-process shape);
the likely fix is a shared backend (`django.core.cache.backends.db.DatabaseCache` on the Postgres
already present) landing in a SEPARATE infrastructure PR - this module's `cache.get`/`cache.set`
calls need no further edit once that lands, since they already use the standard API. See
`docs/features/artist-support-links.md`'s "Warming the cache" section for the full writeup.

**The normaliser (`normalise_artist_record`) is the core of this module.** The upstream data is
dirty in specific, measured ways (all confirmed against the real bulk export, 2,389 records):

- Values that are not URLs at all: `markssignatureservice` is the literal string `"true"`/
  `"false"` on 2,387 of 2,389 records (a flag, not a link - only 2 are URL-shaped). `mountainmage`
  is a URL on 379 records and the literal string `"false"` on 307 (meaning "not offered").
  Rendering either as an href would produce `href="true"`/`href="false"`.
- Email addresses filed in a link field - real personal addresses seen in both `twitter` and
  `website` on multiple records (not reproduced here or in this project's committed test
  fixtures - see `cardpicker.tests.mtgac_synthetic_fixtures`'s own docstring for why: MTGAC's
  export carries no redistribution licence, so no value copied verbatim from it is ever
  committed to this public repo, content values included). Dropped unconditionally: publishing
  an artist's personal contact address on our site because it was filed in the wrong upstream
  field is not acceptable, no exceptions.
- Scheme-less URLs (a bare `example.com/someartist`-shaped value with no `https://` prefix,
  confirmed on multiple fields in the real export) - `https://` is prefixed.
- Leading/trailing whitespace (including an embedded newline seen on one real `inprnt` value).
- Bare non-URL text - e.g. `artstation` holding the artist's own display name, typo'd into the
  wrong field upstream, confirmed on at least one real record.

**Commerce-only allowlist (owner ruling).** Only links that let a user purchase or browse art, or
get prints signed, are ever surfaced - see `_LINK_PRIORITY` below for the fixed order (never
re-sorted per-artist, so the rendered row doesn't reorder between artists) and `_EXCLUDED_FIELDS`
for what's deliberately left out (the pure socials, plus `patreon` - a support channel, not a
purchase/browse/signing one). `markssignatureservice` is surfaced separately as a boolean flag,
never as a link.

**Affiliate referral parameters are kept intact, deliberately.** 167 of 2,389 `omalink` values
carry MTGAC's own `rfsn=` affiliate parameter - retained as a good-faith gesture per owner
ruling. Nothing in this module strips or rewrites query strings.

**`pageUrl` is always carried through, and this matters more than it looks.** 197 of 2,389
(8.2%) of MTGAC's real artist-page slugs disagree with the deterministic URL this project
currently builds client-side via `buildArtistSupportURL`
(`frontend/src/components/ArtistSupportLink.tsx`) - accents folded, periods dropped, case
normalised, or names truncated (see that component's docstring / the feature doc for concrete
examples). Those 197 currently land on MTGAC's own "no artist found" page. Surfacing MTGAC's own
authoritative `pageUrl` (once M2 wires the frontend up to consume it) fixes a real 8.2% broken-
link rate - this is the concrete justification for the M2 follow-up, not a hypothetical one.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from django.core.cache import cache

logger = logging.getLogger(__name__)

MTGAC_BULK_URL = "https://mtgartistconnectionwebservice-production.up.railway.app/api/public/artists"

# Versioned so a future shape change can be rolled out without a stale-shaped blob confusing a
# freshly-deployed reader - same idiom as views.py's "funnel-counts-v1".
CACHE_KEY = "artist-external-links-v1"

# No TTL: this cache is refreshed by a daily warm run, not by request-triggered recomputation
# (this feature is deliberately cache-ONLY on the read path - see get_cached_artist_external_
# links below). An expiring TTL here would mean a missed cron run silently blanks every artist's
# links back to "not found" instead of quietly serving yesterday's still-good data - worse than
# staleness. Freshness is the warm command's job, not the cache's.
CACHE_TIMEOUT = None

# Fixed priority order (owner ruling): only links that let a user purchase or browse art, or get
# prints signed. `website` is a TOP-LEVEL field on the raw record, everything else lives under
# `links`. This list's ORDER is the rendered order - never re-sorted per-artist, so the row
# doesn't visually reorder between artists that happen to have different subsets of these present.
_LINK_PRIORITY: list[str] = ["website", "artstation", "inprnt", "mountainmage", "omalink"]

_MAX_LINKS = 5

# Deliberately excluded from the allowlist (owner ruling), named here so a future editor doesn't
# "helpfully" add them back without re-reading the ruling: the pure socials carry no purchase/
# browse/signing value, and `patreon` is a support channel, not a place to buy/browse/sign art.
_EXCLUDED_FIELDS = frozenset({"instagram", "twitter", "facebook", "youtube", "bluesky", "patreon"})

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def _clean_url_value(raw: Any) -> Optional[str]:
    """
    Normalise one raw upstream field value into either a safe, renderable URL string or `None`
    (meaning: don't surface this at all). See this module's own docstring for the full catalogue
    of hazards this guards against - every branch below exists because of a real record in
    MTGAC's export, not a hypothetical.
    """
    if not isinstance(raw, str):
        return None

    value = raw.strip()
    if not value:
        return None

    # Boolean-flag-shaped values (`markssignatureservice`'s normal shape, and `mountainmage`'s
    # "not offered" sentinel) are not links - rendering them as an href would produce
    # `href="true"`/`href="false"`.
    if value.lower() in ("true", "false"):
        return None

    # Email addresses filed in a link field are dropped unconditionally, no exceptions - see
    # module docstring. Checked before the scheme-less prefixing below so an email never
    # accidentally gets turned into a "mailto"-shaped or bogus `https://` URL first.
    if _EMAIL_RE.match(value):
        return None

    if not _SCHEME_RE.match(value):
        value = f"https://{value}"

    parsed = urlparse(value)
    if not parsed.netloc or "." not in parsed.netloc:
        # Bare non-URL text (e.g. an artist's own name typo'd into the wrong field) has no
        # domain once scheme-prefixed, so it's not renderable as a link either.
        return None

    return value


def normalise_artist_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise one raw MTGAC bulk-export record into this project's internal shape. Pure function,
    no I/O - takes one record from `fetch_bulk_export`'s list, returns the dict that
    `compute_artist_external_links_blob` stores (keyed by artist name) in the cache blob.
    """
    links_raw = record.get("links") or {}

    signature_flag_raw = links_raw.get("markssignatureservice")
    has_signature_service = isinstance(signature_flag_raw, str) and signature_flag_raw.strip().lower() == "true"

    candidates: list[tuple[str, Any]] = [
        ("website", record.get("website")),
        ("artstation", links_raw.get("artstation")),
        ("inprnt", links_raw.get("inprnt")),
        ("mountainmage", links_raw.get("mountainmage")),
        ("omalink", links_raw.get("omalink")),
    ]
    assert [field for field, _ in candidates] == _LINK_PRIORITY

    links: list[dict[str, str]] = []
    for field_name, raw_value in candidates:
        cleaned = _clean_url_value(raw_value)
        if cleaned is not None:
            links.append({"type": field_name, "url": cleaned})
    links = links[:_MAX_LINKS]

    return {
        "found": True,
        "pageUrl": record.get("pageUrl"),
        "location": record.get("location"),
        "links": links,
        "hasSignatureService": has_signature_service,
    }


def not_found_record() -> dict[str, Any]:
    """The shape returned for a cache miss (blob not warmed yet, or this artist isn't in it)."""
    return {"found": False, "pageUrl": None, "location": None, "links": [], "hasSignatureService": False}


def compute_artist_external_links_blob(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalise a full bulk export (list of raw records) into the cache blob shape: a dict
    mapping artist name -> normalised record (see `normalise_artist_record`)."""
    blob: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        blob[name] = normalise_artist_record(record)
    return blob


def fetch_bulk_export(timeout: float = 30.0) -> list[dict[str, Any]]:
    """
    The ONE outbound call this feature ever makes on a given day - see module docstring for why
    this is a bulk fetch, never a per-request proxy. Raises on any transport/shape failure; the
    caller (`warm_artist_external_links_cache`) is responsible for not letting a failure here
    touch the existing cache.
    """
    response = requests.get(MTGAC_BULK_URL, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list from MTGAC's bulk endpoint, got {type(data).__name__}.")
    return data


def warm_artist_external_links_cache() -> dict[str, dict[str, Any]]:
    """
    Fetch + normalise + write the cache blob in one call - the body of the
    `warm_artist_external_links` management command. Raises `ValueError` (fetch/shape errors
    propagate from `fetch_bulk_export` as-is) on ANY failure, WITHOUT writing to the cache first -
    a refresh that can't complete cleanly must leave the previous good blob in place, never
    overwrite it with an empty or partial one. Returns the blob it wrote, so the calling command
    can report a real summary (artist count, link count, etc.) without a second cache read.
    """
    records = fetch_bulk_export()
    if not records:
        raise ValueError("MTGAC bulk export returned zero records - refusing to overwrite the existing cache.")

    blob = compute_artist_external_links_blob(records)
    if not blob:
        raise ValueError("Normalised MTGAC blob is empty - refusing to overwrite the existing cache.")

    cache.set(CACHE_KEY, blob, timeout=CACHE_TIMEOUT)
    return blob


def get_cached_artist_external_links(artist_name: str) -> dict[str, Any]:
    """
    Cache-only read - NEVER calls upstream, regardless of hit or miss. Returns
    `not_found_record()` both when the cache hasn't been warmed yet at all (blob missing) and
    when this specific artist simply isn't in MTGAC's directory (name absent from the blob).

    Deliberately does NOT check `CanonicalArtist` - that restriction (the requested name must be
    one this project actually indexes, so this endpoint can't be used to enumerate MTGAC's whole
    directory) is the CALLER's job (`views.get_artist_external_links`), not this cache-reading
    primitive's - keeps this function reusable/testable independent of that policy.
    """
    blob = cache.get(CACHE_KEY)
    if not blob:
        return not_found_record()
    return blob.get(artist_name) or not_found_record()
