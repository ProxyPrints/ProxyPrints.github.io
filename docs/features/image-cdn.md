# Image CDN

Our own Cloudflare Worker serving card thumbnails, replacing what would
otherwise be direct Google Drive image URLs.

## What it does / how it works

- Cloudflare Worker at a `*.workers.dev` subdomain, with a custom-domain
  route added later (see below). R2 bucket `thumbnails` backs the
  small/large size tiers.
- Wired into the frontend via `NEXT_PUBLIC_IMAGE_WORKER_URL` in
  `deploy-frontend.yml`.
- Also implements upstream's bucket+worker split: a Cloudflare R2 custom
  domain (no compute, serves the `thumbnails` bucket's objects directly)
  on the same account as the Worker, with a wildcard CORS policy on the
  bucket (the Worker sets its own CORS header in code; direct R2 access
  needed its own policy, set via the bucket's Settings → CORS Policy).
  `NEXT_PUBLIC_IMAGE_BUCKET_URL` points at this domain. `Card.tsx` and
  `common/image.ts` already implemented the bucket-first/worker-fallback
  logic upstream-identically — it was simply dormant until the bucket URL
  was set, no code changes needed there.
- `pdfImage.ts` (PDF tab image loading) previously routed **all** quality
  tiers through the worker only, with no bucket fallback at all for
  small/large thumbnails (unlike upstream, which has the bucket leg but no
  worker fallback on a miss). Now tries the bucket first via a HEAD request
  (no `<img onError>` equivalent exists in `@react-pdf/renderer`'s `<Image>`
  component) and falls back to the worker on a miss, for small/large tiers
  only — full-resolution still always goes through the worker, matching
  upstream (`getBucketImageURL` throws for `"full"`).
- **Full-tier requests bypass R2 caching entirely** (only small/large are
  cached - see `R2Service`) and go through `fetchWithRateLimit(env. IMAGE_FULL_TIER_RATE_LIMITER, ...)` to Google's `lh4` endpoint instead -
  `simple = { limit: 30, period: 10 }` (3 req/sec), shared globally across
  live PDF export, live bulk download, AND the local pilot/backfill's own
  fetches (`cardpicker.image_cdn_fetch.get_worker_image_url` builds this
  same full-tier URL - confirmed via code, every pilot candidate fetch is
  one Worker invocation, none go direct to Google). This limiter exists to
  protect Google's endpoint from abuse (an earlier unattended backfill
  script hammered it directly) and stays exactly where it is regardless of
  Cloudflare account billing tier - it's a politeness/fairness control, not
  a cost control.
- **Separately, the account was on Cloudflare Workers' free tier (100,000
  invocations/day) until 2026-07-16**, when the pilot's own full-tier
  fetches (one Worker invocation per candidate, per the point above) were
  found to be consuming meaningful daily quota alongside live traffic -
  upgraded to Workers Paid ($5/month, 10M requests/month included) the
  same day, removing the daily cap. The 218k-card `content_phash` backfill
  (docs/features/catalog-completion-plan.md's Part 2) needed this: at full
  tier its request count alone exceeds the old 100k/day cap, independent
  of the rate limiter's own pacing.

## Key files

- `image-cdn/src/index.ts` (Worker), `image-cdn/wrangler.toml`
- `frontend/src/common/image.ts`, `frontend/src/components/Card.tsx`
- `frontend/src/features/pdf/pdfImage.ts`

## Status / verification

- Verified end-to-end: fetched a real cached thumbnail through both the
  worker and the bucket domain directly, confirmed byte-identical content
  (md5sum match) and that the bucket's CORS header only appears on
  requests carrying an `Origin` header (a bare curl without one won't show
  it — not a broken policy).
- Fixed a real CORS bug: small/large GET responses had no
  `Access-Control-Allow-Origin` header at all, only the OPTIONS preflight
  did. Confirmed this also affects chilli-axe's live CDN, not fork-specific
  — upstreamed as PR #465 (currently open; see [[../infrastructure.md]]).
- The Worker was originally reachable only at its bare `*.workers.dev`
  subdomain — bare Workers subdomains get generically flagged by some
  ad-block/privacy lists (heavily abused for ad-tech on Cloudflare's shared
  free subdomain). Fixed by adding a `[[routes]]` entry with
  `custom_domain = true` to `wrangler.toml` and pointing
  `NEXT_PUBLIC_IMAGE_WORKER_URL` at the custom domain. The R2 bucket domain
  and the Worker's custom domain are deliberately separate domains.
- `IMAGE_CDN_GOOGLE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN` repo secrets are
  placeholders — they only gate the scheduled thumbnail-refresh
  cache-invalidation cron, not the request-serving path, so image serving
  works fine without real values; only the daily refresh job no-ops.

## Known gaps

- Every deploy's "Publish image CDN" job in `cloudflare-workers-ci.yml`
  shows as failed, because wrangler can't attach the Workflows cron
  trigger for the thumbnail-refresh job (a Cloudflare API error). The
  actual worker script deploy succeeds regardless — check the job log for
  "Uploaded image-cdn"/"Deployed image-cdn triggers" before assuming a
  real failure. Non-blocking, not something to chase.
- Whether `wrangler deploy` can auto-provision a custom domain depends on
  the API token having zone-level DNS edit rights — since the bucket
  domain needed a manual dashboard step, the token may be account-scoped
  only, in which case the Worker's custom domain needs the same manual
  Custom Domain setup (Workers & Pages → image-cdn → Settings → Domains &
  Routes) rather than happening automatically on deploy.
