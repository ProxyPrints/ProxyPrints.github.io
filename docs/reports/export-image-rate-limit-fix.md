# Mass export-image failure — diagnosis and fix

**Incident**: owner-reported PDF export ("104 card images couldn't be loaded
and will be blank") on a large real-deck export — the first big
full-resolution export attempted through the pipeline since the image-CDN
Worker's shared rate limiter went live. Branch:
`claude/export-image-rate-limit-fix`.

## Diagnosis

Owner's hypothesis: the export path performs its own image fetches without
pacing to the image-CDN Worker's shared 3 req/s rate limiter and without
retry-on-429, so mass per-card failures on large exports are the expected
result.

**Confirmed.** Three findings:

1. **Server-side, the Worker already retries.** `image-cdn/src/utils.ts`'s
   `fetchWithRateLimit` (used by the full-resolution tier in
   `image-cdn/src/handler/image.ts`) loops up to `MAX_RATE_LIMIT_RETRIES = 5`
   times acquiring a slot from a Cloudflare rate limiter binding configured
   as `{ limit: 30, period: 10 }` — 3 req/sec, shared globally across live PDF
   export, live bulk download, and the backend's own backfill pilot (see
   `docs/features/image-cdn.md`). If all 5 retries exhaust, it throws, and
   nothing in `index.ts`'s top-level `fetch` handler catches it — the client
   just sees a failed request.

2. **Client-side, there was no pacing at all.** `pdfImage.ts`'s
   `fetchAsBlob` (a single `fetch`, no retry, throw on non-`ok`) was called
   directly by both `getPDFImageURL`'s full-resolution branch and the newer
   `getPDFImageBlob`, with zero coordination between concurrent card fetches.
   `@react-pdf/renderer` resolves every card's `<Image src={async () =>
   ...}>` callback using its own internal scheduler, which this codebase
   doesn't control — on a large export, dozens of full-resolution fetches
   fire near-simultaneously, each independently fighting for the shared 3/s
   slot with only the server's fixed 5-retry budget to save it. Under that
   contention most exhaust retries and fail.

3. **Not a Proposal-B regression.** Diffed against `dfa1eb0^` (pre-Proposal-B):
   `getPDFImageURL`'s full-resolution branch already existed with identical
   fetch mechanics (`fetchAsBlob`, no retry, no pacing) before Proposal B.
   The new `getPDFImageBlob` fetches the same one-request-per-card-slot
   volume as the old path — it didn't add fetch volume or change fetch
   mechanics. The incident is best explained as the first large-scale
   full-resolution export attempted since the rate limiter's introduction,
   not something Proposal B caused.

**Not independently verified**: the owner's "~15 known-dead-link ids should
fail, ~89 others should not" split. This sandboxed session has no live
backend/CDN access, so there was no way to replay the actual export and
confirm the post-fix failure count lands at ~15. Recommend the owner re-run
the same export post-deploy and compare the failure count/names against
that list.

## Fix

### 1. Client-side pacing + retry (`frontend/src/features/pdf/pdfImage.ts`)

- New `frontend/src/common/semaphore.ts`: a plain counting semaphore
  (`acquire()`/`release()`), deliberately distinct from the existing
  `concurrencyLimit.ts`'s `mapWithConcurrencyLimit` — that helper needs a
  known, finite item list processed in one call, whereas react-pdf's
  scheduler produces an unbounded stream of ad-hoc calls arriving over time
  that this codebase doesn't control. 4 tests (concurrency ceiling under
  real contention, FIFO ordering, blocking/release behaviour).
- `pdfImage.ts` gets a module-level `fullResolutionFetchSemaphore =
  new Semaphore(FULL_RESOLUTION_FETCH_CONCURRENCY = 3)` — matched to the
  Worker's own 3 req/s ceiling — and a new
  `fetchFullResolutionImageAsBlob(url)` that:
  - acquires a semaphore slot before fetching, releases it in `finally`
    regardless of outcome;
  - retries up to `FULL_RESOLUTION_FETCH_MAX_RETRIES = 3` times with
    backoff (`2 ** attempt * 250 + jitter` ms) on `429`, `5xx`, or a
    network-level fetch rejection;
  - fails **immediately**, no retry, on a non-retryable 4xx (e.g. a real
    404 dead link) — so a permanently-dead card doesn't burn its retry
    budget delaying the other cards queued behind the concurrency gate.
- Both `getPDFImageURL`'s full-resolution branch and `getPDFImageBlob`'s
  `SourceType.GoogleDrive` branch now call this instead of the old
  `fetchAsBlob`. `fetchAsBlob` itself is untouched and still used by
  `getThumbnailURL` — thumbnails aren't rate-limited server-side, so they
  don't need this.
- 6 new tests cover the retry/backoff/give-up/concurrency behaviour with
  `jest.useFakeTimers()`.

### 2. Live "fetching images: N/M" progress

Mirrors the existing `reportImageFailure` plumbing exactly, end to end:

- `PDF.tsx` / `SCMPDF.tsx`: new optional `reportImageProgress` prop, called
  once per resolved image slot (success or failure) from a `finally` block
  alongside the existing failure-reporting `catch`.
- `pdf.worker.ts`: `renderPDF` tracks `completed`/`total` (total = unique
  card-document count — an approximation that undercounts decks with
  duplicate-card slots, since each slot resolves independently; documented
  as such, the UI doesn't present it as an exact fraction) and forwards
  progress through a new `onImageProgress` comlink export, alongside the
  pre-existing but dead `onProgress`/`log` hook (grepped — nothing calls it;
  left untouched, out of scope).
- `pdfRenderService.ts`: new `onImageProgress(cb)` wrapper. **Must** wrap
  `cb` in `Comlink.proxy(cb)` — see the real bug found below.
- `PDFGenerator.tsx`: registers the callback right before
  `renderPDF`/`renderPDFInWorker`, renders `Fetching images: {completed} of
  ~{total}` (`data-testid="pdf-image-fetch-progress"`) while downloading or
  saving to Drive, clears on completion.

Wall-clock honesty: at 3 req/s, a 500-card export is ~3+ minutes of pure
image fetching. The progress text exists specifically so that reads as
"working," not "hung."

### 3. In-app confirm modal replaces `window.confirm()`

The owner's screenshot showed Firefox's "allow notifications" anti-spam
chrome next to the native confirm dialog — repeated native `confirm()`
calls in a short window can get silently auto-suppressed by the browser,
which would turn the failure safeguard off with no visible indication.

- New `ImageFailureConfirmModal` in `PDFGenerator.tsx`: a real
  React-Bootstrap `Modal` (`data-testid="image-failure-confirm-modal"`,
  `-cancel`, `-continue`) listing up to 10 failed card names ("…and N
  more"), asking "Continue anyway?"
- `downloadPDF`/`saveToDrivePDF` (plain async functions outside the
  component tree) bridge to it via a `ConfirmDespiteFailures = (failures) =>
  Promise<boolean>` type and a `pendingFailureConfirm` state holding
  `{ failures, resolve }`, resolved when the user clicks Cancel/Continue.
- Only cards that fail **after** the client-side retries in fix #1 reach
  this dialog at all — transient 429/5xx blips are now absorbed before the
  user ever sees them.

## Real bug found along the way

Wiring `onImageProgress` through comlink without `Comlink.proxy(cb)`
throws `DataCloneError: ... could not be cloned` — but only the instant the
callback actually fires (inside comlink's internal promise chain), not at
compile time or call time. This disguised itself as three unrelated-looking
Playwright failures (a `.click()` timeout intercepted by
`<nextjs-portal>`, a `waitForEvent('download')` timeout, and progress text
never appearing) until the saved `error-context.md` page snapshot for one
failing test was inspected directly and showed a Next.js dev-mode
"Unhandled Runtime Error" overlay sitting **on top of** — not instead of —
the correctly-rendered modal underneath. Playwright's `toBeVisible()` on
the modal locator was a false positive: the modal genuinely was
CSS-visible under the overlay. Fixed with a one-line `Comlink.proxy(cb)`
wrap in `pdfRenderService.ts`. Logged to `docs/lessons.md` as a general
diagnostic technique: check for an "Unhandled Runtime Error" dialog node in
a failing test's `error-context.md` before assuming a pointer-interception
failure is a CSS/layout problem.

## Verification

- `npx tsc --noEmit` — clean.
- `npx jest --runInBand` — 303/303 passing (18 in `pdfImage.test.ts`, 4 in
  the new `semaphore.test.ts`).
- `npx eslint` on all touched files — 0 errors, 2 pre-existing
  `jsx-a11y/alt-text` warnings on `PDF.tsx`/`SCMPDF.tsx` (confirmed
  pre-existing via `git stash` comparison, unrelated to this change).
- `npx playwright test tests/PDFGenerator.spec.ts --workers=1` — 5/5
  passing, including a new progress-UI test using an artificially delayed
  mock handler to reliably observe the "Fetching images:" text before it
  clears.

## Open items

1. Could not verify against the owner's specific "~15 known-dead-link ids
   vs. ~89 that should now succeed" split — no live backend/CDN access in
   this sandboxed session. Recommend re-running the same large export
   post-deploy and comparing the failure list/count against that
   expectation.
2. `pdf.worker.ts`'s progress `total` undercounts decks with duplicate-card
   slots (counts unique card documents, not slots) — noted in code comments
   as an approximation, not exact-fraction UI. Not fixed here; would need a
   slot count passed in separately if exactness is wanted later.
