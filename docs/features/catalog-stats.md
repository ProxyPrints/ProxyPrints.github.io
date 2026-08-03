# Catalog Stats

## What this is

The backend for Proposal F's public `/stats` transparency page
(`docs/proposals/proposal-f-public-stats-page.md`) - a periodic, cached
aggregate of catalog/moderation state, served from `GET 1/catalogStats/`.
Issue #233's owner ruling (2026-07-29) lifted the proposal's HOLD; this is
**backend pass 1** - the aggregate generator, the warm command, its hourly
schedule, and the cache-only endpoint.

**Frontend status (2026-07-29, branch `feat/stats-page-frontend`): built.**
The `/stats` page (`frontend/src/pages/stats.tsx`, panels under
`frontend/src/features/stats/`) consumes this endpoint and renders all five
shipped panels, transformed from the old `/contributions` page (which now
redirects to `/stats` - see `frontend/src/pages/contributions.tsx`'s own
comment) and restored to the top nav. It renders a "not computed yet" state
on a cache miss (`generatedAt: null`) rather than presenting the zeroed
skeleton as real data - see `pages/stats.tsx`'s own module comment. A
homepage call-to-action graph (`features/stats/ParticipationGraph.tsx`)
draws on this endpoint's `participation` panel only.

**Status: five of Proposal F's seven charts, plus the call-to-action
panel.** Charts 2, 4, 6, 7 ship this pass; charts 1 (catalog resolution
progress) and 5 (hash coverage) are deliberately deferred - see "Deferred
charts" below.

## Architecture: compute / warm / cache-only-read

Follows `cardpicker.artist_external_links`'s pattern exactly (see that
module's own docstring for the fully-worked-out rationale this reuses
rather than re-derives):

- `cardpicker/catalog_stats.py` - pure aggregation functions
  (`compute_contributions_over_time`, `compute_skip_breakdown`,
  `compute_run_history`, `compute_catalog_composition`,
  `compute_participation`), plus `compute_catalog_stats()` (all five, one
  call), `warm_catalog_stats_cache()` (compute + write), and
  `get_cached_catalog_stats()` (cache-only read, never computes).
- `management/commands/warm_catalog_stats.py` - the command an hourly
  django-q2 schedule invokes. Idempotent; on any failure leaves the
  existing cache untouched and exits non-zero.
- `migrations/0094_warm_catalog_stats_hourly_schedule.py` - hand-written,
  creates the `django_q.Schedule` row (`get_or_create`, `next_run` pinned
  to the next top-of-the-hour UTC at apply-time), same idiom as
  `0093_warm_artist_external_links_weekly_schedule.py`.
- `views.get_catalog_stats` (`GET 1/catalogStats/`) - cache-only, never
  computes on request. A cache miss returns the zeroed skeleton, never a 500.

**Cache: `caches["shared"]` (`DatabaseCache`, PR #543/#538) - never
`caches["default"]`.** Same cross-process gap as the MTGAC integration:
`warm_catalog_stats` runs as a separate `manage.py` process from the web
server, so a `default`-cached (per-process `LocMemCache`) blob would never
be visible to the process serving `1/catalogStats/`. `default` stays
`LocMemCache` on purpose (django-ratelimit + `cardpicker.review_clusters`
depend on that). Graceful degradation: if `"shared"` isn't configured yet,
the read path returns the zeroed skeleton (never a 500); the warm command
raises loudly instead (a warm run that silently writes nowhere while
reporting success is exactly the bug issue #538 exists to prevent).

**Cache key**: `catalog-stats-v1`, no TTL (refreshed by the hourly warm
run, not by expiry - see `cardpicker.catalog_stats`'s own module
docstring for why an expiring TTL would be worse than staleness here).

**Schedule: hourly, unconditional.** Unlike the MTGAC integration, this
reads only the project's own database - no third-party rate limit, no
opt-in gate. All five aggregates move slowly by nature (vote counts,
skip-log rows, and pilot-run ledger rows accumulate at most a few dozen
new rows an hour even during an active tagging push), so hourly is
generous headroom, not a tuned-to-the-edge number.

## HUMAN_SOURCES - a stats-page-specific human/machine split

`cardpicker.catalog_stats.HUMAN_SOURCES = [VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED]` - deliberately **not**
`vote_consensus._MACHINE_DERIVED_SOURCES` (which also includes
`FEDERATED` as machine-derived). Issue #233's owner ruling: "the snapshot
groups USER/ADMIN/FEDERATED as human and DEDUCTION/OCR/IMPLICIT as
machine ... the consensus set answers 'can this vote resolve a card
unattended', while a public stats page answers 'who is doing the tagging
work'." Every "human vote"/"human voter" count in this module filters on
`HUMAN_SOURCES`, never on `vote_consensus.is_human_backed_source`.

`VoteSource.IMPLICIT` (the passive filter-chip signal,
`post_cast_implicit_vote`) is excluded from `HUMAN_SOURCES` even though it
DOES write `vote_surface` (`IMPLICIT_VOTE_SURFACE = "display-editor-filter"`) - it's a tiny-weight by-product of a card
selection, "never human-backed" per `VoteSource.IMPLICIT`'s own docstring,
not tagging work a person chose to do. `compute_contributions_over_time`
filters on both `vote_surface__isnull=False` (excludes DEDUCTION/OCR,
which never set `vote_surface` at all) **and** `source__in=HUMAN_SOURCES`
(excludes IMPLICIT specifically) - relying on the `vote_surface` filter
alone would let implicit votes leak into a chart titled "human
confirmations".

## The five shipped panels

| Panel                   | Proposal F chart | Data source                                                                        | Notes                                                                                                                  |
| ----------------------- | ---------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `contributionsOverTime` | 2                | `CardPrintingTag`/`CardArtistVote`/`CardTagVote`, weekly `vote_surface` buckets    | Human-only by two independent filters (`vote_surface` non-null/non-blank AND `source in HUMAN_SOURCES`) - see above    |
| `skipBreakdown`         | 4                | `CardScanLog.skip_reason`, grouped by reason and by reason+`anonymous_id` (engine) | Plain `GROUP BY`, no assumption about how many distinct reasons exist - see `reference/skip-reasons.md` for the roster |
| `runHistory`            | 6                | `PilotRunLedger` - status/duration/`votes_written`, most recent 50                 | See "The already-voted caveat" below                                                                                   |
| `catalogComposition`    | 7                | `cardpicker.models.summarise_contributions()`, reused verbatim                     | The cheapest panel - moves an existing live query (`GET 2/contributions/`) onto this cache instead of adding one       |
| `participation`         | (call to action) | `question_feed.get_remaining_estimate()` + human vote counts + md5-group figures   | Raw counts only - see "No percent-complete field" below; card-denominated counts in "Cards vs. votes" below            |

## The already-voted caveat (`runHistory`)

Several `PilotRunLedger.counters` keys - `stage_d_join_key_already_voted`,
`stage_d_fallback_already_voted`, `stage_d_illustration_already_voted` -
are structurally `0` on every row written since 2026-07-28:
`cardpicker.vote_write`'s purge-then-write primitive purges by calculator
family (which includes the caller's own current `anonymous_id`) **before**
the already-voted split ever runs, so the split counts against a table it
just emptied. `compute_run_history` never surfaces any `counters` key at
all, specifically to avoid shipping one of these.

`votes_written` (the field this panel DOES surface) is a different, TOP-LEVEL
column and is **not** affected by that bug - verified by tracing every
call site that sets it: each one derives it from a `result.votes_written`/
`len(new_votes)` value computed by the SPLIT step, which
`cardpicker.vote_write`'s own docstring establishes runs BEFORE the purge.
It is `None` for `command="stage_e_streaming_dispatch"` rows specifically -
a separate, unrelated gap (that dispatcher's own ledger update writes only
`counters` keys, never the top-level `votes_written` column) - and this
panel passes that `None` through rather than backfilling it.

## No percent-complete field (`participation`)

Measured 2026-07-29: total human votes across all three vote tables is
237 (`CardPrintingTag` 125 + `CardArtistVote` 6 + `CardTagVote` 106)
against a `total` (from `get_remaining_estimate()`) of 230,770 - roughly
0.1%. `compute_participation` deliberately emits **only raw counts** -
`confirmable`/`contested`/`fresh`/`total`, `humanVotes` (by table and
summed), `distinctHumanVoters`, `distinctCardsWithHumanVotes`,
`distinctCardsRoutedToReview`, `distinctCardsRoutedToReviewWithHumanVotes`,
and the md5-group figures
(`groupsWithMultipleCards`/`cardsInMultiCardGroups`/`largestGroupSize`) -
never a single computed ratio. A meter pinned to 0.1% reads as "this
project failed" rather than "this project needs you" - the page decides
how to frame the numbers; the backend never pre-computes that choice away.

## Cards vs. votes (`distinctCardsWithHumanVotes`, `distinctCardsRoutedToReview`, `distinctCardsRoutedToReviewWithHumanVotes`)

Added 2026-07-29 so a front-page consumer can render a cards-over-cards
participation ratio instead of votes-over-cards. Before this trio of
fields, the only human-activity numerator available was `humanVotes.total`
(a vote count) against a `total`/`confirmable` denominator that is
card-counted - dividing the two over-counts participation, since one card
can carry several independent human votes (a printing tag, an artist
vote, and a descriptor tag are three separate votes on the same card).
`frontend/src/features/stats/ParticipationGraph.tsx`'s own module
docstring documents this exact `humanVotes.total / total` ratio as the
approximation it originally shipped with (measured 2026-07-29, ≈0.1%,
worse once machine votes grow) - these fields make an exact cards/cards
ratio possible without that pitfall.

**Consumer swap shipped (2026-07-29, this task):** the homepage graph's
gate and drawn series (`frontend/src/features/stats/humanProgressReveal.ts`'s
`humanProgressRatioPercent`) now compute
`distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview`
instead of `humanVotes.total / total` - the old votes-over-cards path (and
its units-mismatch caveat) is deleted, not kept as a fallback. See "The
gated human-progress series" below for the full consumer-side writeup,
including the live-API-skew guard this swap requires.

- **`distinctCardsWithHumanVotes`** - distinct `card_id` across
  `CardPrintingTag`/`CardArtistVote`/`CardTagVote`, filtered to
  `HUMAN_SOURCES` (this module's own USER/ADMIN/FEDERATED split, see
  above) and unioned across the three tables in Python, the same
  `distinct_voters`-style set-union `compute_participation` already uses
  for `distinctHumanVoters` - a card voted on in two tables counts once.
  This is cheap **only because the `HUMAN_SOURCES` filter keeps the row
  set tiny** (low hundreds today, per the 237-vote figure above); it is
  not a pattern to copy for an unfiltered count. Answers "total human
  reach across the catalog, routed or not."
- **`distinctCardsRoutedToReview`** - distinct `card_id` in `CardScanLog`
  filtered to the slow-path agent
  (`local_calculate_verdicts.SLOW_PATH_ANONYMOUS_ID`) and
  `skip_reason=SLOW_PATH_TO_REVIEW_SKIP_REASON` - the same filter shape
  `review_clusters._review_queue_card_ids()` already uses. **This must be
  a distinct-card count, computed with
  `.values("card_id").distinct().count()`, never a plain `.count()`.**
  `CardScanLog` is an append-only audit trail (see that model's own
  docstring): a card can accumulate more than one row for the same
  `(card, anonymous_id)` pair over time, since multiple runs can each
  abstain on the same card independently - a raw row count would report
  rows, not cards, and silently overstate this figure. Unlike the human
  vote tables, `CardScanLog` is a genuinely large table (order 10^5 rows),
  so this is computed as one `.distinct().count()` query rather than a
  Python-side set union. `CardScanLog`'s only declared index is on
  `(card, anonymous_id)` (see that model's `Meta.indexes`) - this filter
  is on `anonymous_id` + `skip_reason` without `card` in the predicate, so
  that index's leading column doesn't help it; no index in this codebase
  currently supports this exact filter (open item, not addressed by this
  change - see the introducing PR's report).
  **This count is not, on its own, a progress measure: it only ever
  grows.** Nothing clears a card's routing marker when it later gets a
  human vote - `CardScanLog` is append-only - so `distinctCardsRoutedToReview`
  rises monotonically as the sweep runs, even while people are actively
  contributing. Treat it strictly as a denominator, paired with
  `distinctCardsRoutedToReviewWithHumanVotes` below, never charted alone
  as "how much is done."
- **`distinctCardsRoutedToReviewWithHumanVotes`** - the INTERSECTION of
  the two sets above: cards that are both routed to review AND carry a
  human vote. **This is the pair that forms a valid progress ratio** -
  `distinctCardsWithHumanVotes` is deliberately NOT a subset of
  `distinctCardsRoutedToReview` (a person can vote on a card the machine
  never routed to review at all), so `distinctCardsWithHumanVotes / distinctCardsRoutedToReview` is not a coherent ratio. `distinctCards RoutedToReviewWithHumanVotes / distinctCardsRoutedToReview` is, by
  construction, a proper subset over its own superset, and rises as
  people work the review queue. Computed by reusing the same
  `distinctCardsWithHumanVotes` card-id set built once above and
  filtering the `CardScanLog` routed queryset down to
  `card_id__in=<that tiny set>` - cheap because that IN-list is small and
  the model's own `(card, anonymous_id)` index serves it, rather than
  pulling every routed card id into Python to intersect there or
  re-querying the three vote tables a second time.

## Deferred charts (1 and 5)

Not built this pass, and not merely unbuilt - both would render as a
single, uninformative bar at today's measured values:

- **Chart 1 (catalog resolution progress)**: resolved printings sit at 3
  of ~230,770 cards (2026-07-29) - would render essentially empty.
- **Chart 5 (backfill/hash coverage)**: `content_phash` coverage sits at
  ~218k of ~230,770 (≈95%) - would render essentially full.

Both are the OPPOSITE failure mode from `participation`'s own "don't
understate progress" concern - shipping either now would be misleading in
the other direction. A future pass revisits both once the underlying
numbers move enough to be worth a chart.

## The gated human-progress series (2026-07-29 owner ruling)

The owner's original idea for the homepage graph was a literal progress bar

- `humanVotes.total` filling up toward `total`. `ParticipationGraph.tsx`'s
  own module comment explains why that reads as a dead 0.74px stripe at
  today's real ~0.1% ratio. Rather than drop the idea, it now ships **gated**:
  the bar joins the homepage graph once the ratio would actually be legible,
  implemented in `frontend/src/features/stats/humanProgressReveal.ts`.

- **`HUMAN_VOTE_REVEAL_PERCENT`** (default `10`, i.e. 10%) - the threshold,
  as a real percentage. Adjustable in one line in that file, or overridable
  at build time (no source edit) via the `NEXT_PUBLIC_HUMAN_VOTE_REVEAL_PERCENT`
  environment variable - useful for a self-hoster running a much smaller (or
  larger) catalog than production's ~230k cards, where 10% of THEIR catalog
  is reached at a very different absolute vote count.
- **`HUMAN_VOTE_REVEAL_HYSTERESIS_PP`** (`1`, in percentage points) - one-way
  hysteresis around that threshold: the series reveals at
  `>= HUMAN_VOTE_REVEAL_PERCENT`, but once revealed, only hides again once
  the ratio drops below `HUMAN_VOTE_REVEAL_PERCENT - HUMAN_VOTE_REVEAL_HYSTERESIS_PP`. This prevents the homepage layout from
  flipping on every load if the ratio sits right on the boundary.
- **Single accessor, single computation**: `humanProgressRatioPercent()` is
  the one place the ratio is computed; both the reveal gate and the drawn
  bar's fill width read the SAME value, computed once per render in
  `ParticipationGraph.tsx`. Gating on one number and drawing another would
  let the series unlock while still rendering as a hairline - the exact
  failure this feature exists to prevent.
- **Card-denominated ratio (2026-07-29 consumer swap)**:
  `humanProgressRatioPercent()` computes
  `distinctCardsRoutedToReviewWithHumanVotes / distinctCardsRoutedToReview`
  - cards over cards, with the numerator a proper subset of the
    denominator by construction (see "Cards vs. votes" above and that
    field's own backend test). This REPLACES the original
    `humanVotes.total / total` votes-over-cards approximation entirely - the
    old path (and its units-mismatch caveat, which no longer applies) is
    deleted, not kept as a fallback.
- **Live-API-skew guard**: `humanProgressRatioPercent()` returns `null`
  (never `NaN`) whenever the three card-denominated fields aren't all
  present, finite numbers on the given object - the guaranteed state of
  every `1/catalogStats/` response until the production API is deployed
  past PR #566 (`store/api.ts`'s `getCatalogStats` trusts the fetch
  response's shape directly, with no runtime validation, so a real
  response missing these fields reaches this function exactly as typed).
  `shouldRevealHumanProgress` treats `null` as unconditionally
  below-threshold - `ParticipationGraph.tsx` renders its below-threshold
  design, unchanged, with no placeholder/NaN/thrown error. Covered by
  `humanProgressReveal.test.ts`'s "live-skew guard" describe block and
  `ParticipationGraph.test.tsx`'s matching describe block (constructs a
  `Participation` object with the three fields deleted).
- **Below the threshold, nothing changes**: no placeholder, no "0%
  complete" hint, no teaser - the series simply does not exist, and the
  graph is byte-for-byte the design described above. **At or above it**,
  the series joins on the graph's existing single axis (never a second
  y-scale), using the human series' established colour
  (`var(--bs-primary)`, the same token `VoterDotMatrix`'s dots and the
  page's CTA buttons already use). Neither state ever renders a percentage,
  or `participation.total` itself, as literal text - the ratio only ever
  drives the bar's width.
- **The headline flips too (2026-07-29 consumer-swap directive, item 2)**:
  below threshold, the headline/copy is the `confirmable`-count call to
  action, unchanged from today. At/above threshold, the headline switches
  to a "cards the machine routed to people" framing - distinct copy, not
  the below-threshold sentences with a bar bolted on. The flip is driven
  by the same hysteresis-gated `humanProgressRevealed` boolean as the bar
  itself, which means it is NOT a one-way latch: since
  `distinctCardsRoutedToReview` only ever grows, the ratio can retreat
  below the hysteresis floor even while people are actively voting
  (denominator outrunning numerator), and the headline would revert on
  the next load. Known, accepted limitation this pass - tracked as
  orchestration issue #22.
- **A count that only ever rises (item 3)**: because
  `distinctCardsRoutedToReview` (the ratio's denominator) grows on its
  own, the ratio - and the bar's width - can fall even on a day people are
  actively contributing. `ParticipationGraph.tsx`'s `ReviewedCardCount`
  renders `distinctCardsRoutedToReviewWithHumanVotes` (the ratio's
  numerator) as a plain count beside the bar specifically because that
  number never decreases - see that component's own comment for why it
  is not "redundant with the bar."
- **The in-session "you contributed" dot (item 4)**: the dot-matrix's
  dashed "you would be the Nth" mark becomes a filled, green,
  "you're one of them" dot plus a short thank-you once THIS browser tab
  has cast a vote this session. Driven entirely by in-session Redux state
  (`frontend/src/features/stats/sessionContributionSlice.ts`, dispatched
  from `QuestionFeed.tsx`'s existing `bumpSessionCount` on every
  successful vote) - deliberately NOT `localStorage` and NOT a new
  "has this anonymous_id voted" endpoint (see that slice's own module
  comment for why both were rejected). Colour is `var(--bs-success)` -
  `colors.ts`'s existing status-good token, not a new hue - paired with
  changed accessible-name/title text and a visible thank-you paragraph,
  so the state never depends on colour alone.
- A separate, always-present addition (not gated by this threshold): a
  "Start with one card" button immediately after the dot-matrix's hollow
  "you could be next" mark, linking to `/whatsthat`, gated on
  `remoteBackendConfigured` (same condition `Navbar.tsx` uses for its own
  What's That Card? link).

## Endpoint

`GET 1/catalogStats/` (`views.get_catalog_stats`) - no parameters, always
the same shape (`CatalogStatsResponse`, `cardpicker/schema_types.py`).
Cache-only: **never computes on request**, on a hit or a miss - Proposal
F's own explicit constraint ("zero live aggregate queries from public
traffic"). A miss (cold cache, or `"shared"` not configured) returns
`zeroed_catalog_stats()` - every field at its zero/empty value,
`generatedAt: null` - so the page always has something to render and the
endpoint never 500s because an optional piece of infrastructure isn't
wired up yet.

## Warming the cache

`python manage.py warm_catalog_stats` recomputes all five panels and
overwrites the cache blob in one call. Idempotent - safe to re-run any
number of times, each run a full recomputation from the live database
(never a merge/diff against the previous blob). On any failure it changes
nothing and exits non-zero (`CommandError`) - the previous cache entry
(an earlier run's good blob, or nothing at all on a first run) is left
untouched, since `compute_catalog_stats()` is a pure read and only its
return value is ever written.

## Schema

`schemas/schemas/endpoints/CatalogStatsResponse.json` is the JSON schema
source, for documentation and any future safe regeneration - **not run
through `npm run build`** for this addition, since that generator is
destructive to the two hand-added implicit-vote request types already in
`schema_types.py`/`schema_types.ts` (issue #332, four PRs have hit this).
`CatalogStatsResponse` and its nested types
(`ContributionsOverTime`/`SkipBreakdown`/`RunHistory`/
`CatalogComposition`/`Participation` and their children) were
hand-integrated into both generated files instead, matching quicktype's
own generated style (same provenance as `ArtistExternalLinksResponse`).

## Tests

`MPCAutofill/cardpicker/tests/test_catalog_stats.py` - each aggregation
against fixtures with known values (including the `HUMAN_SOURCES`/
`VoteSource.IMPLICIT` exclusion, the md5-group edge cases, and the
`votes_written`/duration edge cases in `runHistory`); the cache-only
endpoint guarantee (cache hit returns the blob, a cache miss makes no
aggregate query - asserted by patching `compute_catalog_stats` to raise
if called); the `"shared"`-not-configured graceful-degradation suite
(mirrors `test_artist_external_links.py`'s own); the warm command's
idempotency and cache-preservation-on-failure behaviour; and the
migration (schedule row created once, `HOURLY`, reverses/reapplies
cleanly).

**Frontend** (branch `feat/stats-page-frontend`, 2026-07-29):
`frontend/src/features/stats/StatsPage.test.tsx` (no-backend/cache-miss/
populated state machine - deliberately NOT under `src/pages/`, since
Next.js compiles every file there into the client bundle and this test
imports the msw node server; see that file's own header comment and
`pages/stats.tsx`'s `CatalogStatsBody` export comment),
`frontend/src/features/stats/RunHistoryPanel.test.tsx` (null
`votesWritten`/`durationSeconds` render as "—", never "0"), and
`frontend/src/features/stats/ParticipationGraph.test.tsx` (the homepage
graph reads correctly under both today's real vote ratio and the
post-machine-sweep ratio, with no percentage ever computed against
`total` - see that file's own module comment; also covers the "Start with
one card" CTA gating, the gated human-progress series and its
routed-to-review headline flip, the always-rising
`distinctCardsRoutedToReviewWithHumanVotes` count, the live-skew guard
(the three card-denominated fields deleted entirely), and the in-session
green-dot/thank-you mechanic), and
`frontend/src/features/stats/humanProgressReveal.test.ts` (the reveal
threshold's own hysteresis band and the card-denominated accessor's
live-skew `null` guard, both pure-function level - see "The gated
human-progress series" above). Playwright: `frontend/tests/Stats.spec.ts`
and `frontend/tests/ParticipationGraph.spec.ts`.

## Sweep gate (`warm_catalog_stats`, retired as default 2026-08-03)

**2026-07-29 ruling → retired 2026-08-03. The gate is now OFF by default; the
command computes all five panels on every hourly run, sweep or no sweep.**

### Why it was retired

The original ruling (2026-07-29) gated the warm run while any
`PilotRunLedger` row with `status=RUNNING` was present within the
staleness bound, on the premise that a heavy batch sweep contended for
the same database. That premise no longer holds under the streaming
micro-batch sweep design (Stage E), where a `RUNNING` row is perpetually
present — the gate was freezing the stats page indefinitely.

**The owner's 2026-08-03 ruling reverses the gate with three-part
rationale, verified against the live system:**

1. **MVCC safety.** The five aggregations are plain `SELECT` queries —
   they never block on or are blocked by the streaming sweep's tiny
   micro-batch `INSERT`s (25 cards, max 3 concurrent).

2. **Sweep artifacts already filtered.** The `runHistory` panel filters
   rows with `anonymous_id=SLOW_PATH_ANONYMOUS_ID, skip_reason=SLOW_PATH_TO_REVIEW_SKIP_REASON`
   (`catalog_stats.py` lines ~391–396), and the vote panels
   (`participation`, `contributionsOverTime`) count only human sources
   (`HUMAN_SOURCES = USER/ADMIN/FEDERATED`), so mid-sweep numbers are
   stable and correct regardless of whether a sweep is in flight.

3. **~9s measured compute.** Full compute of all five panels was measured
   at ~9s (last ungated run 2026-08-02T16:00:22Z → 16:00:31Z), trivial
   load once an hour.

The staleness bound (`WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS`,
default 12h) and the `_find_blocking_sweep` helper are preserved unchanged
as a crashed-sweep guard in the opt-in path below.

### How the gate works now (opt-in)

- **Default (gate off):** The command computes all five panels on every
  hourly run. `_find_blocking_sweep` is never consulted. The stdout log
  prints `"Sweep gate: disabled (default) — computing all five panels."`
  so operators can see which mode ran.

- **Opt-in (gate on):** Set `WARM_CATALOG_STATS_SWEEP_GATE_ENABLED=true`
  in the environment. This restores the exact 2026-07-29 behaviour: a
  `RUNNING` row within the staleness bound skips the entire run (exit 0,
  cache untouched, same warning text naming the blocking run by its
  `run_id`/`started_at`/running-time). A `RUNNING` row older than the
  staleness bound is ignored (crashed-sweep guard).

Both settings remain settings-driven (`WARM_CATALOG_STATS_SWEEP_GATE_ ENABLED`, `WARM_CATALOG_STATS_SWEEP_STALE_AFTER_HOURS` in
`MPCAutofill/MPCAutofill/settings.py`), tunable without a migration or a
code change.

**Index**: `CardScanLog(anonymous_id, skip_reason)` (migration `0096`) -
added because `compute_skip_breakdown`'s per-engine panel (and any future
query shaped the same way) filters/groups `CardScanLog` on those two
columns with no `card` in the predicate, which the model's pre-existing
`(card, anonymous_id)` index cannot serve (leading-column mismatch). See
migration `0096`'s own docstring for the full reasoning, including why
`anonymous_id` leads the composite index.

## Deployment: nginx must route /1/ to django (PR #668)

`docker/nginx/nginx.conf` must include a `location /1/` proxy block
forwarding to `http://django-api`, without which every /1/ request
returns a 404 at nginx. The stats page (`GET 1/catalogStats/`) renders
"The stats cache hasn't been computed yet" and the homepage participation
graph (`GET 1/funnelCounts/`) shows an error. The block was added in
PR #668; see [[../infrastructure.md]] for the full nginx setup.
