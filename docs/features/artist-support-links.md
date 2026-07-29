# Artist Support Links

## What this is

A small, deliberately narrow link-out feature: wherever a card's artist is
confirmed/known, show a link to that artist's page on [MTG Artist
Connection](https://www.mtgartistconnection.com) (MTGAC) - a
community-maintained directory of Magic: the Gathering artists, not
affiliated with this project or its operator.

**Status: both M1 and M2 are built.** A partnership with MTGAC's operator
was agreed after this doc's original v1 design (below) was written. They
offered site credits (accepted, see Credits), an embed (**declined** -
this project's no-third-party-embeds posture), and a data endpoint
(accepted). MTGAC has since supplied public bulk/single-artist endpoints;
the backend consumer for that data (M1: daily-cached fetch + normalise +
cache, one new read endpoint) is built - see "M1: the verified backend
integration" below - and the frontend applet that actually consumes it
(M2: `ArtistSupportLink.tsx`, RTK Query, commerce-link buttons, the
Mark's Signature Service badge, the MTGAC credit line) is built too - see
"M2: the frontend applet" below. The original v1 design (immediately
below) is now the FALLBACK behaviour, not the only behaviour: every
surface still degrades to it gracefully whenever the backend has no data
for an artist (cold cache, artist not yet indexed, or no remote backend
configured at all).

## v1 design: zero-crawl, deterministic link-out only (now the fallback)

The core constraint, decided up front: **v1 does no verification of any
kind**. No per-artist database, no crawling MTG Artist Connection to build
a mapping, no existence check before rendering a link. The href is built
directly from the artist's display name string alone, via
`buildArtistSupportURL` (`frontend/src/components/ArtistSupportLink.tsx`):

```
https://www.mtgartistconnection.com/artist/<encodeURIComponent(artistName)>
```

e.g. `"Harold McNeill"` -> `.../artist/Harold%20McNeill`.

**Why no existence check, specifically**: MTG Artist Connection is a
client-rendered SPA where every route - including one for an artist it
doesn't actually have a page for - returns HTTP `200`. A status-code-based
"does this resolve to something real?" check is therefore not just
skipped for convenience, it's structurally meaningless against this site;
confirmed during this feature's own recon, don't re-attempt it. An artist
who isn't in their directory lands on MTG Artist Connection's own graceful
"No artist found" in-app page - accepted v1 behaviour, not treated as a
broken link from this project's side.

**This "no existence check" gap turns out to be real, not just
theoretical** - see the 8.2% slug-divergence finding in the M1 section
below, discovered once MTGAC's own authoritative data became available to
compare against.

## Component

`frontend/src/components/ArtistSupportLink.tsx` exports:

- `buildArtistSupportURL(artistName: string): string` - the pure URL
  builder above, unit-tested directly (`ArtistSupportLink.test.tsx`) for
  the encoding behaviour (spaces -> `%20`, `&` -> `%26`, etc.) since that's
  the one thing this feature can silently get wrong with no visual symptom.
  Still used as the fallback construction whenever the backend has no data
  for an artist - see "M2: the frontend applet" below.
- `ArtistSupportLink({ artistName, className? })` - the M2 applet (was: a
  plain `<a>` wrapping caller-supplied `children`; **`children` is gone**,
  the applet now owns its own content/labels entirely). Fetches
  `2/artistExternalLinks/` via RTK Query (`useGetArtistExternalLinksQuery`,
  `store/api.ts`) and renders, in this order: a primary page-link button
  (MTGAC's `pageUrl` when available, `buildArtistSupportURL` otherwise -
  ALWAYS present), any commerce-link buttons (0-5, fixed priority order),
  the Mark's Signature Service badge (when true), and the MTG Artist
  Connection credit line (ALWAYS present). See "M2: the frontend applet"
  below for the full design.

**Gating is the caller's job, not the component's**: `ArtistSupportLink`
takes an `artistName: string` (not optional/nullable) - it has no opinion
on when an artist is "confirmed enough" to render. Every caller below only
renders it once the artist is confirmed/known via the same precedence
chain the backend's `Card.serialise` exposes (i.e. `canonicalArtist` is
non-null) or a vote the user just cast themselves - never for a vote-
pending or unknown artist, since there'd be no name to build a URL from.
M2 didn't widen this gate at all, only what gets rendered once it's open.

## Surfaces (three, as of the Proposal H pane migration)

1. **Card Detail Modal** (`CardDetailedViewModal.tsx`'s attribute table,
   the `"Canonical Aritst"` row - yes, that's a pre-existing typo in the
   row label, left as-is since fixing it is out of scope for this change).
   `cardDocument.canonicalArtist != null` renders
   `<ArtistSupportLink artistName={...} />` in place of the plain name
   text; `null` still renders `"Unknown"` as before, unchanged.
2. **`/whatsthat`'s post-answer moment** (`QuestionFeed.tsx`'s `"artist"`
   item type). `ArtistVotePicker` gained an optional `onArtistConfirmed?: (artistName: string) => void` prop, called from inside its own
   `submit()`'s success handler only when a real named artist was voted
   for (`!isUnknown && artistName != null` - "Unknown artist" never
   calls it, there's nothing to link). `QuestionFeed.tsx` wires this to
   local state (`confirmedArtistName`, reset every new item alongside the
   rest of the per-question state - see the fetch effect's own comment on
   why that reset has to be unconditional, not dependency-array-keyed) and
   renders a plain `"Art by <Name> - support them"` text line followed by
   the applet, once set. `ArtistVotePicker`'s _other_ caller
   (`AttributeVotingPanel`, the Card Detail Modal's own voting surface)
   doesn't pass this prop, so its behaviour is unchanged - the confirm
   banner is specific to the `/whatsthat` funnel's own post-answer moment,
   not a general property of casting an artist vote anywhere.
3. **Proposal H's `/display` rail Artist section**
   (`frontend/src/features/display/ArtistSection.tsx`, left-panel
   unification, issue #164) - the follow-on this doc originally
   anticipated. Same precedence chain/gating as surface 1:
   `cardDocument.canonicalArtist != null` renders a plain `"Art by <Name>"` credit line followed by the applet; `null` renders plain
   `"Unknown"` text, never an applet with nothing to point at. Reads the
   rail's currently-selected slot's own `CardDocument` (already resident in
   `cardDocumentsByIdentifier`) for the artist name - the applet's own data
   fetch is separate (keyed by that name), not piggybacked on this read.

**Not built** (explicitly out of scope, noted so a future session doesn't
have to re-derive why): the confidently-known-artist collapsed display
inside `ArtistVotePicker` itself (the `"<name> wrong?"` span, shared by
both its callers) does not get an applet - only the three surfaces above.

## M1: the verified backend integration

**Architecture: a DAILY-CACHED BULK CONSUMER, not a per-request proxy.**
`MPCAutofill/cardpicker/artist_external_links.py` makes ONE outbound call
per day (via `warm_artist_external_links_cache`) against MTGAC's bulk
export (`.../api/public/artists`), normalises it, and writes the result to
Django's cache. Nothing on the request-serving path ever calls upstream - a
per-request proxy would be functionally closer to the embed MTGAC already
offered and this project already declined, and would turn this site into
an enumerable mirror of their directory.

**Storage: Django cache ONLY - no model, no migration.** Deliberate, not an
oversight. MTGAC has confirmed they're comfortable with this integration
being open-source AND granted permission to distribute their data (see
"Licence status" below) - there is no licensing barrier to a permanent
copy. The cache-only design stands anyway: a daily refresh needs no
schema/migration, and MTGAC remains the source of truth for this
upstream-mastered data. Follows the existing `funnel-counts-v1` pattern in
`views.py`. Test fixtures stay synthetic regardless of the licence
question - see "Licence status" below for why (it isn't a licensing
reason) and `cardpicker.tests.mtgac_synthetic_fixtures`'s own docstring.

**The normaliser is the core of this addition**, because the upstream data
is dirty in specific, measured ways (confirmed against a 2,389-record
sample of the real export):

- Several fields are booleans dressed as links (a literal `"true"`/
  `"false"` string) rather than URLs - rendering one as an href would
  produce `href="true"`. One field in particular uses the real export's
  literal `"false"` to mean "not offered" on the large majority of records
  it appears on, and a real URL on the rest.
- Some records carry a personal email address in a link field (`twitter`
  and `website` both observed). **Dropped unconditionally** - publishing an
  artist's personal contact address because it was filed in the wrong
  upstream field is not acceptable, no exceptions.
- Scheme-less URLs (`example.com/artist`, no `https://`) are prefixed.
- Leading/trailing whitespace (including an embedded newline on one real
  value) is stripped.
- Bare non-URL text (an artist's own name, typo'd into the wrong field) is
  dropped.

**Commerce-only allowlist (owner ruling), plus `instagram` as a deliberate
last-resort exception**, fixed priority order so the rendered row never
reorders between artists: the artist's own `website` (top-level field),
`artstation`, `inprnt`, `mountainmage` (URL form only), `omalink`,
`instagram` - capped at 5. `twitter`/`facebook`/`youtube`/`bluesky` and
`patreon` (a support channel, not a purchase/browse/signing link) are
excluded entirely.

`instagram` is LAST, deliberately, because of what it does and doesn't
change: measured against the real 2,389-record export, 812 artists have
zero links under the pure commerce-only allowlist; `instagram` appears on
1,428 artists overall but only on 157 of those 812 (it correlates with
already having a `website`/`artstation`), moving the empty-applet case
from 812 down to 655. Being last means it never crowds out a real
commerce link for an artist who has one - the 5-cap still fills from
`website` onward first. The other socials were measured and rejected as
rescues too small to justify the clutter: `twitter` (105), `facebook`
(82), `bluesky` (11), `youtube` (10).

`markssignatureservice` is surfaced separately as a **boolean flag**, never
as a link.

**Affiliate referral parameters are kept intact, deliberately** - a
meaningful fraction of `omalink` values carry MTGAC's own `rfsn=`
parameter, retained as a good-faith gesture per owner ruling rather than
stripped.

**`pageUrl` is always carried through - and this is the concrete
justification for this whole integration**, not a nice-to-have: comparing
MTGAC's real artist-page slugs against the deterministic URL v1's
`buildArtistSupportURL` constructs found that **8.2% of them disagree**
(accents folded, periods dropped, case normalised, or names truncated).
Those 8.2% currently land on MTGAC's own "no artist found" page under v1.
Surfacing MTGAC's own authoritative `pageUrl` (once M2 wires the frontend
up to actually use it) fixes a real broken-link rate, not a hypothetical
one.

### Endpoint

`GET 2/artistExternalLinks/?name=<artist name>` (`views.get_artist_external_links`) -
cache-only, one artist per request, GET-only, rate-limited
(`ARTIST_EXTERNAL_LINKS_RATE`, default `60/m`, per-IP). Returns the
not-found shape (`found: false`, no links) in two cases: the cache hasn't
been warmed (yet, or at all), or the requested name doesn't match any
`CanonicalArtist` this project actually indexes - the latter is
deliberate, so this endpoint can never be used as a free-text lookup
against the raw cached MTGAC blob (i.e. an enumerable mirror of their
directory). No bulk/list shape exists or is planned - one artist per
request, always.

### Warming the cache

`python manage.py warm_artist_external_links` fetches the full bulk
export, normalises it, and overwrites the cache blob (keyed by artist
name) in one call. Idempotent - safe to re-run any number of times. On any
fetch/shape failure it changes nothing and exits non-zero (`CommandError`)
rather than risk poisoning the cache with an empty or partial result -
today's or yesterday's good data stays in place until a fetch actually
succeeds.

**MTGAC's disclosed rate limits (as of 2026-07-29, from their reply
granting permission for this integration to be open-source - they offered
to adjust these numbers if needed):**

| Endpoint                                           | Limit             | Used by this integration?                                                             |
| -------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------- |
| Single-artist lookup (`/api/public/artist/<name>`) | 60 requests/15min | No - this is a bulk consumer, never a per-request proxy (see architecture note above) |
| Bulk list (`/api/public/artists`)                  | 12 requests/hour  | Yes - the one call `fetch_bulk_export` makes                                          |

A daily-or-weekly cron makes this a non-issue at steady state (1 call/day
against 12/hour = 288/day is roughly 1/288th of the budget). **The real
exposure is a failure loop, not steady state**: `fetch_bulk_export` and
`warm_artist_external_links_cache` contain NO retry logic at all,
deliberately - see `fetch_bulk_export`'s own docstring. A failed run
costs exactly one request and is not retried until the next scheduled
cron invocation; do not add retry/backoff without re-reading that
docstring first.

**OPEN ITEMS (owner decisions, neither resolved by this change):**

1. **A daily cron must be scheduled** to run
   `warm_artist_external_links` - nothing runs it automatically yet.
2. **A shared cache backend is a tracked prerequisite, not something this
   PR fixes - but merge order no longer matters (see below).** This
   feature reads and writes a NAMED cache, `caches["shared"]`, deliberately
   NOT Django's `default` cache
   (`cardpicker.artist_external_links.SHARED_CACHE_ALIAS`). That's not
   incidental: `default` stays `LocMemCache` on purpose, because two other
   things already depend on that exact property -
   `django-ratelimit` (no `RATELIMIT_*` override in `settings.py`) runs
   against `default`, and `cardpicker.review_clusters` caches a
   `list[ReviewCluster]` built over a ~135k-row queue on `default` too -
   repointing `default` at a database-backed cache would turn every
   rate-limited request into a DB read/write and every review-cluster
   fetch into a pickle round-trip through Postgres, adding load through
   the exact mechanisms meant to shed it. Neither is broken today
   (gunicorn runs a single worker - `docker/django/Dockerfile`'s `CMD` has
   no `--workers` flag - so the SAME process both writes and reads its own
   `default` cache), so neither should move onto a shared backend.
   `warm_artist_external_links` has the actual cross-process gap instead:
   it runs as a separate `manage.py` invocation (a cron entry), a
   different OS process from the running web server, so its writes to a
   per-process cache are never visible to the process serving
   `2/artistExternalLinks/` requests - independent of worker count. The
   fix is a SECOND, named cache alias (`caches["shared"]`, backed by
   something actually shared across processes - `DatabaseCache` on the
   Postgres already present is the leading candidate), tracked as
   **issue #538** and landing in a **separate infrastructure PR**.
   **Graceful degradation means merge/deploy order between that PR and
   this one doesn't matter**: `caches["shared"]` raises
   `InvalidCacheBackendError` when the alias doesn't exist yet: the read
   endpoint catches this and returns its ordinary not-found response
   (identical to today's behaviour, never a 500), while the warm command
   deliberately does NOT catch it - it exits non-zero with a clear message
   instead, because a cron run that silently writes nowhere while
   reporting success is exactly the bug this feature originally shipped
   with. Once `"shared"` is configured, both sides start working with no
   further code change on either side.

### Licence status

**Resolved, both halves.** MTGAC's operator confirmed by email (owner
correspondence, 2026-07-29) that they're comfortable with this
INTEGRATION - the code in this repo that fetches, normalises, and serves
their data - being open-source, AND that they've granted permission to
distribute their DATA (that's the entire reason they stood the bulk
endpoint up for this project in the first place). There is no licensing
barrier to this integration or to its data.

What's still genuinely open with MTGAC, separately, and unrelated to
licensing: name aliases/variants, and a per-record last-updated/export-
version field.

**Test fixtures stay synthetic anyway - not a licensing precaution, a
personal-data one.** The real export contains personal email addresses
belonging to real artists, mis-filed into `twitter`/`website` link fields
(dropped at runtime by the normaliser - see the M1 section above). MTGAC
can license their own compilation; they cannot consent, on an individual
artist's behalf, to that artist's personal email address being
republished, permanently and searchably, in a public repository - that's
third-party personal data, outside anything MTGAC is in a position to
license away. See `cardpicker.tests.mtgac_synthetic_fixtures`'s own
docstring for the full reasoning (including the independent engineering
case for synthetic fixtures - stable, minimal, each hazard exercised
deliberately).

## M2: the frontend applet

**Fetch via RTK Query, never an ad-hoc `fetch`.** `useGetArtistExternalLinksQuery`
(`store/api.ts`) wraps the raw generated hook the same way every other
backend-specific query in this codebase does - `skip`ped entirely when no
remote backend is configured, so a demo/local-only session makes zero
network calls and falls straight back to the deterministic URL, silently.
`found: false` is a normal, expected response (cold cache, or an artist
this project doesn't index in `CanonicalArtist` yet), never surfaced as an
error - the applet treats it exactly like "no data yet."

**Design target: zero and one commerce links, not four or five.** The
same 2,389-artist measurement M1's allowlist is built on: 812 artists have
zero commerce links, 818 have exactly one, only 13 have all five
(`instagram`'s last-resort allowlisting - see M1's allowlist section above

- rescues 157 of those 812 down to 655; roughly 598 have nothing but the
  MTGAC page link regardless of what's allowlisted). The applet is built for
  that distribution: the MTGAC page-link button and the MTG Artist
  Connection credit line are ALWAYS rendered (an obligation, not decoration
- MTGAC accepted site credits as part of the partnership), and commerce
  buttons/the signature badge are purely additive on top. **The applet never
  renders as an empty box** - even an artist with nothing else still shows
  the page-link button and the credit.

**No layout shift while loading.** The loading state and the "found:
false"/zero-commerce-link state render identically (page-link button +
credit only) - for roughly a third of all artists that's not a shift at
all, since the loaded state IS the base shape; for the rest, commerce
buttons/the badge appear additively below a base that was already there,
never a spinner collapsing into a differently-shaped final layout.

**`pageUrl` is preferred over the constructed URL whenever the backend has
it** - this is the actual point of the applet, not a nice-to-have: see
M1's own 8.2% slug-divergence finding above. A cold cache, a not-yet-
loaded request, an unconfigured remote backend, and an artist absent from
`CanonicalArtist` all fall back to the identical deterministic
construction, indistinguishably.

**Buttons stretch to fill the applet** (owner instruction) - every
rendered button/link is full-width within whatever container the caller
gives it (Bootstrap `w-100`/`d-grid`), so the applet reads consistently
whether that container is the Card Detail Modal's narrow table cell or the
`/display` rail's full-width panel.

**Link labels**: `website` → "Website", `artstation` → "ArtStation",
`inprnt` → "INPRNT", `mountainmage` → "Mountain Mage Signatures",
`omalink` → "Original Magic Art", `instagram` → "Instagram" - rendered in
the backend's own fixed priority order, never re-sorted client-side.

## Credits

`frontend/src/pages/about.tsx` credits MTG Artist Connection by name,
right after the existing contributors section, explaining the link-out-
only nature of the integration (traffic flows _to_ their directory, not
the other way) and inviting the actual site operator to reach out for a
richer, blessed integration later.

## Tests

- `ArtistSupportLink.test.tsx` (Jest/RTL, M2) - the URL-encoding behaviour
  of `buildArtistSupportURL` directly; the applet's own behaviour end to
  end against the RTK Query hook (MSW-mocked, `src/mocks/handlers.ts`'s
  synthetic `artistExternalLinks*` handlers - see their own module comment
  for why they're synthetic): never an empty box before data arrives or
  with no remote backend configured, cache-miss/not-found falls back to
  the deterministic URL, `pageUrl` is preferred over the constructed URL
  when they genuinely disagree, zero/one/five-commerce-link rendering, the
  fixed priority order and 5-cap (including the `instagram` last-resort
  rescue scenario), the Mark's Signature Service badge renders as a badge
  never a link, the MTGAC credit line is always present, and every
  rendered link carries the external-link etiquette attributes.
- `tests/ArtistSupportLink.spec.ts` (Playwright) - surface 1: a known
  canonical artist renders the link with the correct href/attributes (MSW
  default not-found response, so this exercises the fallback URL); no
  canonical artist renders plain `"Unknown"` text with no link at all.
- `tests/QuestionFeed.spec.ts` (formerly `QuestionFeedArtistAndTag.spec.ts`,
  Playwright) - surface 2: the
  post-answer banner appears (with the correct href) after voting for a
  named artist; voting "Unknown artist" never shows it.
- `tests/DisplayPage.spec.ts` (Playwright) - surface 3: the rail's Artist
  section shows the applet (page-link button naming the artist, own MTGAC
  credit line) for a slot with a known canonical artist (Print Options and
  Slot Actions' own new-section coverage lives in the same file, alongside
  this).
- `MPCAutofill/cardpicker/tests/test_artist_external_links.py` (M1,
  backend) - the normaliser against every hazard above (using synthetic
  fixtures - see `mtgac_synthetic_fixtures.py`'s docstring for why),
  cache-hit/cache-miss/not-indexed-artist endpoint behaviour (asserting no
  outbound call ever happens on the request path), the warm
  command/function's idempotency and cache-preservation-on-failure
  behaviour, and the `caches["shared"]`-not-configured graceful-degradation
  suite.
