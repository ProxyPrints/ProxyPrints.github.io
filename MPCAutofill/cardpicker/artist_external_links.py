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

**MTGAC's own disclosed rate limits (as of 2026-07-29, from their reply granting permission for
this integration to be open-source - they offered to adjust these if needed): 60 requests/15min
for their single-artist lookup endpoint (`.../api/public/artist/<name>` - not called anywhere in
this module, see the architecture note above for why), 12 requests/hour for the bulk list
endpoint `fetch_bulk_export` below actually calls.** See that function's own docstring for the
headroom math and the no-retry design that keeps a failure from ever threatening this ceiling.

**Storage: Django cache ONLY.** No model, no migration - deliberate, not an oversight. This
architecture decision predates MTGAC's 2026-07-29 confirmation that they're comfortable with
this integration being open-source and that they've granted permission to distribute their data
(owner email correspondence) - there is no outstanding licensing question blocking a permanent
copy. The cache-only design stands anyway: a daily refresh needs no schema/migration, and MTGAC
remains the source of truth for this upstream-mastered data (freshness, not licence status, is
now the standing rationale). Follows
the `funnel-counts-v1` pattern already established in `views.py` (`get_funnel_counts`), with one
structural difference: funnel-counts computes AND caches inline, in the same request that serves
it; this feature's cache is instead populated by a SEPARATE management-command invocation.

**Cache backend: a NAMED shared cache (`caches["shared"]`), deliberately NOT `default` (issue
#538).** This module reads and writes `caches["shared"]`, never Django's `default` cache. That's
not an arbitrary choice: `default` stays `LocMemCache` (per-process, in-memory) on purpose,
because two OTHER things in this codebase already depend on that:

- `django-ratelimit` (`views.py`'s `@ratelimit` decorators, including
  `get_artist_external_links`'s own) runs against `default` with no `RATELIMIT_*` override in
  `settings.py` - repointing `default` at a database-backed cache would turn every rate-limited
  request into a DB read plus write, adding load through the exact mechanism meant to shed it.
- `cardpicker.review_clusters` caches a `list[ReviewCluster]` built over a ~135k-row queue on
  `default` - a `DatabaseCache` there means a pickle round-trip through Postgres on every read.

Neither is broken today (gunicorn runs a single worker - `docker/django/Dockerfile`'s `CMD` has
no `--workers` flag - so the SAME process both writes and later reads its own `default` cache),
so neither should move. THIS feature is the one with the actual cross-process gap: a
cron-invoked `warm_artist_external_links` runs as a separate `manage.py` process, a different OS
process from the running web server, so writes to a per-process cache are never visible to the
process serving `2/artistExternalLinks/` requests - independent of worker count. A second,
NAMED cache (`caches["shared"]`, backed by something actually shared across processes -
`DatabaseCache` on Postgres is the leading candidate) is the fix, tracked as issue #538 and
landing in a SEPARATE infrastructure PR. **Do not "simplify" this later by moving `default` and
`review_clusters`/rate-limiting onto the same shared backend** - re-read the two bullets above
first if that ever looks tempting.

**Graceful degradation when `"shared"` isn't configured yet - merge order with #538 doesn't
matter.** `caches["shared"]` raises `InvalidCacheBackendError` if no such alias exists in
`CACHES`. The read path (`get_cached_artist_external_links`) catches this and treats it EXACTLY
as a cache miss - `not_found_record()`, the frontend degrades to today's existing behaviour,
never a 500 because an optional infrastructure piece isn't wired up yet. The write path
(`warm_artist_external_links_cache`, called from the cron) does the opposite on purpose: it lets
this surface as a loud, actionable failure (see that function's own docstring) - a cron run that
silently writes nowhere and reports success is exactly the original bug this feature shipped
with, and swallowing it a second way here would reintroduce it. Because of this split, THIS PR
and the #538 infrastructure PR can land and be deployed in EITHER order with no broken
intermediate state: before #538, the endpoint just serves not-found (identical to today); after
it, `warm_artist_external_links` starts working and the endpoint starts serving real data with
no code change on either side.

**The normaliser (`normalise_artist_record`) is the core of this module.** The upstream data is
dirty in specific, measured ways (all confirmed against the real bulk export, 2,389 records):

- Values that are not URLs at all: `markssignatureservice` is the literal string `"true"`/
  `"false"` on 2,387 of 2,389 records (a flag, not a link - only 2 are URL-shaped). `mountainmage`
  is a URL on 379 records and the literal string `"false"` on 307 (meaning "not offered").
  Rendering either as an href would produce `href="true"`/`href="false"`.
- Email addresses filed in a link field - real personal addresses belonging to real artists,
  seen in both `twitter` and `website` on multiple records (not reproduced here or in this
  project's committed test fixtures, regardless of MTGAC's own permission to distribute their
  data more broadly - see `cardpicker.tests.mtgac_synthetic_fixtures`'s own docstring: MTGAC can
  license their compilation, but cannot consent on an individual artist's behalf to that
  artist's personal email being republished). Dropped unconditionally at runtime, here and
  everywhere: publishing an artist's personal contact address on our site because it was filed
  in the wrong upstream field is not acceptable, no exceptions.
- Scheme-less URLs (a bare `example.com/someartist`-shaped value with no `https://` prefix,
  confirmed on multiple fields in the real export) - `https://` is prefixed.
- Leading/trailing whitespace (including an embedded newline seen on one real `inprnt` value).
- Bare non-URL text - e.g. `artstation` holding the artist's own display name, typo'd into the
  wrong field upstream, confirmed on at least one real record.

**Commerce-only allowlist (owner ruling), PLUS `instagram` as a deliberate last-resort (owner
ruling, added after the initial allowlist).** Only links that let a user purchase or browse art,
or get prints signed, are ever surfaced - see `_LINK_PRIORITY` below for the fixed order (never
re-sorted per-artist, so the rendered row doesn't reorder between artists) and `_EXCLUDED_FIELDS`
for what's deliberately left out (`twitter`/`facebook`/`youtube`/`bluesky`, plus `patreon` - a
support channel, not a purchase/browse/signing one).

`instagram` is NOT a purchase/browse/signing surface either, but it's allowlisted anyway, LAST,
as a deliberate exception: measured against the real 2,389-record export, 812 artists have zero
links under the pure commerce-only allowlist, and `instagram` appears on 1,428 artists overall
(60%) but only on 157 of those specific 812 zero-link artists (it correlates heavily with artists
who already have a `website`/`artstation`) - moving the empty-applet case from 812 down to 655.
Being LAST in priority means it never crowds out a real commerce link for an artist who has one
(the 5-cap still favours `website`/`artstation`/`inprnt`/`mountainmage`/`omalink` first), while
still giving an artist with nothing else a single link instead of an empty applet. The other
socials were measured and rejected for the same 812-zero-link rescue: `twitter` (105), `facebook`
(82), `bluesky` (11), `youtube` (10) - not worth the added clutter for that little rescue value.
`markssignatureservice` is surfaced separately as a boolean flag, never as a link. These five
purchase/browse/signing fields plus `instagram` plus the five rejected socials plus
`markssignatureservice` are the complete link vocabulary present in the export - there is nothing
else to consider.

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

**Opt-in, per instance (`settings.MTGAC_BULK_URL`, owner requirement 2026-07-29).** This is
self-hostable software. MTGAC granted bulk-endpoint access, and disclosed the rate limits above,
to THIS project specifically, as a favour - not to every fork or self-hosted instance that
happens to deploy this code. `settings.MTGAC_BULK_URL` therefore defaults to EMPTY (see
`MPCAutofill/settings.py`'s own comment), and empty means "not configured", which means the
integration is OFF: `bulk_url_configured()` below is `False`, `warm_artist_external_links_cache`
refuses to run (see its own docstring), and the `warm_artist_external_links` management command
no-ops cleanly - a quiet, expected, exit-0 state on every instance that hasn't deliberately
opted in, not an error. One knob, not two - there is no separate enable flag, only this URL. The
weekly `django_q.Schedule` row (`cardpicker.migrations.0093_warm_artist_external_links_weekly_
schedule`) is still created UNCONDITIONALLY on every instance - see that migration's own
docstring for why gating row creation on env at migration time doesn't work - so this runtime
check is what actually makes an unconfigured instance harmless, not the absence of the schedule.
The URL itself is NOT a secret (public, unauthenticated, already shared openly by MTGAC) - see
`docs/features/artist-support-links.md` for the value and, importantly, for why an operator who
enables this on their own instance should contact MTGAC directly rather than assume this
project's permission extends to them.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from django.conf import settings
from django.core.cache import InvalidCacheBackendError, caches

logger = logging.getLogger(__name__)

# The named cache alias this feature reads/writes - deliberately NOT Django's `default` cache.
# See module docstring's "Cache backend: a NAMED shared cache" section for why.
SHARED_CACHE_ALIAS = "shared"

# Versioned so a future shape change can be rolled out without a stale-shaped blob confusing a
# freshly-deployed reader - same idiom as views.py's "funnel-counts-v1".
CACHE_KEY = "artist-external-links-v1"

# No TTL: this cache is refreshed by a daily warm run, not by request-triggered recomputation
# (this feature is deliberately cache-ONLY on the read path - see get_cached_artist_external_
# links below). An expiring TTL here would mean a missed cron run silently blanks every artist's
# links back to "not found" instead of quietly serving yesterday's still-good data - worse than
# staleness. Freshness is the warm command's job, not the cache's.
CACHE_TIMEOUT = None

# Fixed priority order (owner ruling): the first five are commerce fields (purchase/browse/
# signing); `instagram` is appended LAST as a deliberate exception - see module docstring's
# allowlist section for the exact rescue numbers (812 -> 655 zero-link artists) and why LAST
# matters (never crowds out a real commerce link; still rescues an artist with nothing else).
# `website` is a TOP-LEVEL field on the raw record, everything else lives under `links`. This
# list's ORDER is the rendered order - never re-sorted per-artist, so the row doesn't visually
# reorder between artists that happen to have different subsets of these present. DO NOT move
# `instagram` earlier without re-reading the ruling this comment points to.
_LINK_PRIORITY: list[str] = ["website", "artstation", "inprnt", "mountainmage", "omalink", "instagram"]

_MAX_LINKS = 5

# Deliberately excluded from the allowlist (owner ruling), named here so a future editor doesn't
# "helpfully" add them back without re-reading the ruling: these carry no purchase/browse/signing
# value (or, for `patreon`, are a support channel rather than a place to buy/browse/sign art), and
# were individually measured and rejected as zero-link-artist rescues too small to justify the
# added clutter (see module docstring: twitter 105, facebook 82, bluesky 11, youtube 10 - all
# smaller than instagram's 157, which WAS allowlisted for exactly that reason).
_EXCLUDED_FIELDS = frozenset({"twitter", "facebook", "youtube", "bluesky", "patreon"})

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

    # A value that already declares a URL scheme is a URL BY CONSTRUCTION - the email heuristic
    # a few lines down is only ever applied to scheme-LESS input, checked here (scheme first) not
    # after. Getting this order backwards is a real bug this project shipped and caught by
    # running the normaliser against the actual export: a scheme-ful handle-style URL - e.g.
    # `https://www.example.com/@some.handle` (YouTube/TikTok/Bluesky-style @handles are common
    # and will recur; a real handle of exactly this shape was confirmed in the export during
    # this fix's own investigation, not reproduced here - see
    # `cardpicker.tests.mtgac_synthetic_fixtures`'s own docstring for why) - has an "@" and, past
    # it, a segment containing a "." (`handle`), which is everything `_EMAIL_RE` checks for;
    # email-testing it BEFORE the scheme check silently drops a perfectly good URL as if it were
    # an email address. Not live today only by luck of the allowlist (no allowlisted field
    # currently carries handle-shaped URLs), so this fix is preventative, not an incident.
    has_scheme = bool(_SCHEME_RE.match(value))
    if not has_scheme:
        # Only reached for scheme-less input - which is the actual failure mode this check
        # defends against (a bare `someone@example.com` typed into a link field). Checked before
        # the scheme-less prefixing below so a bare email never accidentally gets turned into a
        # bogus `https://` URL first.
        if _EMAIL_RE.match(value):
            return None
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
        ("instagram", links_raw.get("instagram")),
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


def bulk_url_configured() -> bool:
    """
    Whether this instance has opted into the MTGAC integration - see module docstring's "Opt-in,
    per instance" section. `settings.MTGAC_BULK_URL` defaults to empty, and empty means "not
    configured": that's deliberate, this project's bulk-endpoint access is granted to it
    specifically, not to every self-hosted fork of this code. Read at call time (not cached at
    import time) so `override_settings`/env changes are picked up immediately, same as every
    other settings read in this module.
    """
    return bool(settings.MTGAC_BULK_URL)


def fetch_bulk_export(timeout: float = 30.0) -> list[dict[str, Any]]:
    """
    The ONE outbound call this feature ever makes on a given day - see module docstring for why
    this is a bulk fetch, never a per-request proxy. Makes exactly ONE `requests.get` call, full
    stop - no retry loop, no backoff-and-retry, by design (see below), so a single call to this
    function costs at most 1 of MTGAC's disclosed 12-requests/hour bulk-endpoint budget.

    Headroom: `warm_artist_external_links` runs weekly (`cardpicker.migrations.0093_warm_artist_
    external_links_weekly_schedule`), so one successful call/week against a 12/hour (2,016/week)
    allowance is roughly 1/2,016th of the budget - steady state is nowhere near the ceiling and
    isn't the risk.

    **The real exposure is a failure loop, not steady state** - hammering a partner's
    infrastructure immediately after they granted this project access would be a genuinely bad
    outcome. This function therefore has NO retry logic at all, deliberately: on any
    transport/shape failure it raises immediately and returns control to the caller
    (`warm_artist_external_links_cache`, which is itself responsible for not letting that failure
    touch the existing cache - see its own docstring). One failed cron run costs exactly 1 request
    against the budget and is simply not retried until the next scheduled run (tomorrow, or next
    week) - a cron that fails and stays failed until its next scheduled invocation is the desired
    behaviour here, not a bug to paper over. **Do not add retry/backoff logic to this function**
    without re-reading this docstring; if MTGAC's limits ever need more headroom than a single
    daily/weekly call provides, that's a conversation with MTGAC (who have already offered to
    adjust their numbers), not a reason to retry silently against a rate limit from our side.

    Reads `settings.MTGAC_BULK_URL` at call time - see module docstring's "Opt-in, per instance"
    section. Callers that might run on an unconfigured instance should check `bulk_url_configured()`
    themselves rather than rely on this raising cleanly; an empty URL fails inside `requests` with
    a generic, unhelpful error, not one that names the actual problem.
    """
    response = requests.get(settings.MTGAC_BULK_URL, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list from MTGAC's bulk endpoint, got {type(data).__name__}.")
    return data


def _shared_cache_for_read() -> Optional[Any]:
    """
    Returns the named `"shared"` cache backend for the READ path, or `None` if it isn't
    configured (`InvalidCacheBackendError`) - see module docstring's "Graceful degradation"
    section. A missing `"shared"` alias here is treated EXACTLY like a cache miss by the caller,
    never an exception that could 500 the endpoint.
    """
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError:
        return None


def _shared_cache_for_write() -> Any:
    """
    Returns the named `"shared"` cache backend for the WRITE path (the warm command), or raises
    `RuntimeError` with an actionable message if it isn't configured - deliberately NOT swallowed
    the way the read path swallows it. See module docstring's "Graceful degradation" section: a
    warm run that appears to succeed while silently writing nowhere is exactly the original bug
    this feature shipped with, so this surfaces loudly instead of repeating it.
    """
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError as e:
        raise RuntimeError(
            f"The {SHARED_CACHE_ALIAS!r} cache backend is not configured in CACHES "
            "(MPCAutofill/settings.py) - issue #538 tracks the infrastructure PR that adds it. "
            "warm_artist_external_links cannot write anywhere without it, so refusing to run "
            "rather than silently succeeding while writing nowhere."
        ) from e


def warm_artist_external_links_cache() -> dict[str, dict[str, Any]]:
    """
    Fetch + normalise + write the cache blob in one call - the body of the
    `warm_artist_external_links` management command. Calls `fetch_bulk_export` AT MOST ONCE per
    invocation - there is no retry path anywhere in this function, so one call to this function
    costs at most 1 request against MTGAC's disclosed 12/hour bulk-endpoint budget (see
    `fetch_bulk_export`'s own docstring for the full rate-limit/no-retry rationale).

    Checks `bulk_url_configured()` and resolves the `"shared"` cache backend BEFORE making any
    outbound call (`_shared_cache_for_write` raises immediately if it isn't configured) - a
    misconfigured/not-opted-in environment therefore never wastes any of MTGAC's rate-limit
    budget on a fetch whose result couldn't be written down anyway (or shouldn't have been made
    at all).

    Raises `RuntimeError` immediately, before any I/O, if `bulk_url_configured()` is `False` -
    see module docstring's "Opt-in, per instance" section. `warm_artist_external_links` (the
    management command) checks this itself first and no-ops quietly instead of ever reaching
    this function on an unconfigured instance; this function's own check is defense in depth for
    any other caller.

    Raises `ValueError` (fetch/shape errors propagate from `fetch_bulk_export` as-is) on ANY
    fetch/shape failure, WITHOUT writing to the cache first - a refresh that can't complete
    cleanly must leave the previous good blob in place, never overwrite it with an empty or
    partial one, and is never itself retried within this call - the next attempt is the next
    scheduled cron run. Returns the blob it wrote, so the calling command can report a real
    summary (artist count, link count, etc.) without a second cache read.
    """
    if not bulk_url_configured():
        raise RuntimeError(
            "MTGAC_BULK_URL is not configured - this instance has not opted into the MTGAC "
            "integration (see docs/features/artist-support-links.md's opt-in section). Refusing "
            "to run rather than making a request with no configured URL."
        )

    shared_cache = _shared_cache_for_write()

    records = fetch_bulk_export()
    if not records:
        raise ValueError("MTGAC bulk export returned zero records - refusing to overwrite the existing cache.")

    blob = compute_artist_external_links_blob(records)
    if not blob:
        raise ValueError("Normalised MTGAC blob is empty - refusing to overwrite the existing cache.")

    shared_cache.set(CACHE_KEY, blob, timeout=CACHE_TIMEOUT)
    return blob


def get_cached_artist_external_links(artist_name: str) -> dict[str, Any]:
    """
    Cache-only read - NEVER calls upstream, regardless of hit or miss. Returns
    `not_found_record()` when: the `"shared"` cache backend isn't configured yet (see module
    docstring's "Graceful degradation" section - this is the common case until issue #538 lands),
    the cache hasn't been warmed yet even though it IS configured (blob missing), or this
    specific artist simply isn't in MTGAC's directory (name absent from the blob). All three look
    identical to the caller, by design.

    Deliberately does NOT check `CanonicalArtist` - that restriction (the requested name must be
    one this project actually indexes, so this endpoint can't be used to enumerate MTGAC's whole
    directory) is the CALLER's job (`views.get_artist_external_links`), not this cache-reading
    primitive's - keeps this function reusable/testable independent of that policy.
    """
    shared_cache = _shared_cache_for_read()
    if shared_cache is None:
        return not_found_record()
    blob = shared_cache.get(CACHE_KEY)
    if not blob:
        return not_found_record()
    return blob.get(artist_name) or not_found_record()
