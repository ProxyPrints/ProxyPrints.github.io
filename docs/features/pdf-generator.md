# PDF generator

Upstream PR #367 (DriveThruCards PDF export). Four real bugs were found
and fixed here — the first three verified deployed and working end-to-end
(Playwright, real headed Chromium + Firefox, real backend + image-cdn); the
fourth (silent blank-card data loss) shipped 2026-07-17, verified via a
mocked-CDN Playwright suite in a sandbox with no live-backend access — see
its own entry below for what that leaves unverified.

## Bugs found and fixed

1. **Phantom PDF download on opening the editor**, before ever touching the
   PDF tab. `@react-pdf/renderer` eagerly instantiates a Yoga WASM binary at
   _import_ time, not render time, and `PDFGenerator` was statically
   imported. Fixed via `next/dynamic({ssr: false})` + `mountOnEnter` on the
   `Tab.Pane`s that mount it (`PDFGeneratorModal.tsx`,
   `FinishedMyProject.tsx`, `ProjectEditor.tsx`).
2. **Live preview auto-downloading in Firefox / eating too much space in
   Chrome**. The native `<iframe>`/`<object>` embed either triggers
   Firefox's "download instead of render" behavior for blob PDFs, or (once
   switched to `<object>`) pulls in the browser's own PDF viewer chrome
   (toolbar, thumbnail sidebar) that isn't controllable. Replaced entirely
   with a pdf.js canvas renderer (`PDFCanvasPreview.tsx`) — zero chrome,
   works identically in every browser. `pdfjs-dist`'s worker script can't be
   resolved by Next's webpack via the normal `import.meta.url` pattern, so
   it's copied into `public/` as a static asset by a postinstall script
   (`frontend/scripts/copy-pdf-worker.js`) — gitignored, regenerated on
   every `npm install`, always matches the installed `pdfjs-dist` version.
3. **PDF card images never rendered at all** (both preview and the actual
   download — only cut lines showed), because `pdfImage.ts` routed
   thumbnail-quality previews through `getBucketImageURL`, and no image CDN
   was configured for this fork at all. See [[image-cdn.md]].
4. **Silent blank-card data loss on a failed image fetch, both in the live
   preview and the actual download** (frontend-polish package item 1/5,
   2026-07-17). `@react-pdf/renderer`'s `<Image>` fetches its `src` URL
   internally and silently skips a card it can't fetch rather than failing
   the render — a real production risk, since a user could send a
   print-ready file to MakePlayingCards/PringlePrints/NotMPC with blank
   cards and only find out after physical printing.

   Fixed by having `pdfImage.ts` fetch the image itself instead of handing
   `<Image>` a bare remote URL to fetch blind (`fetchAsObjectURL`: a GET
   request, an `ok` check, then a `blob:` object URL — the same pattern the
   `LocalFile` source type already used). A genuine failure now rejects
   instead of resolving to a URL that might fail silently later.
   `PDFCardImage` and `SCMCard` catch that rejection and call
   `reportImageFailure`, a callback threaded through `PDFProps` and
   `SCMPDFProps` that `pdf.worker.ts` supplies per render call (not
   something any caller of the public render hooks passes in itself).
   `renderPDF`/`renderPDFInWorker` now return that render's failures
   alongside the blob, as `RenderPDFResult.failures`.

   The live preview in `PDFGenerator.tsx` shows a warning `Alert` naming
   the failed cards (test id `pdf-preview-image-failures`) whenever any
   failures came back, and a separate danger `Alert` (test id
   `pdf-preview-error`) when the render itself throws — that's
   `useRenderPDF`'s pre-existing `error` value, which used to be computed
   and then never actually rendered anywhere. The download and
   Save-to-Drive paths (`downloadPDF`/`saveToDrivePDF`) block behind a
   `window.confirm` naming the failed cards before calling
   `downloadFile`/uploading, the same pattern already used for the
   irreversible-action confirms in `DrivesPanel.tsx`. Cancelling that
   confirm dispatches a "Download Cancelled"/"Save Cancelled" toast and
   returns without writing anything.

## Thumbnail + full-resolution image fetching (bucket → worker fallback)

See [[image-cdn.md]]'s "What it does" section for the R2 bucket/Worker
split. `pdfImage.ts` tries the R2 bucket first for small/large tiers,
falling back to the Worker on a miss; full-resolution always goes through
the Worker, matching upstream. As of the bug-4 fix above, **both legs are a
real `GET` + `response.ok` check** (not a `HEAD` probe) — the fetched body
becomes a `blob:` object URL handed to `<Image>`, so a fetch failure on
either domain is something calling code can actually observe and report,
rather than being resolved into an unvalidated URL for `<Image>` to fail on
silently later. This also means the "cheap check without a body" rationale
a `HEAD` request had is gone — the body was going to be fetched by `<Image>`
anyway on a hit, so fetching it once ourselves is a real efficiency win, not
just a correctness one.

## Full-resolution fetches are paced + retrying (mass export-image-failure incident)

A large real export (~104 cards) failed almost every full-resolution image fetch, all reporting
as blank in the confirm dialog. Root cause: the image-CDN Worker's full-resolution tier shares
ONE global 3-req/s rate limiter across every caller (see [[image-cdn.md]]'s "What it does"
section), enforced server-side with its own internal retry/backoff - but nothing on the CLIENT
paced how many concurrent full-resolution fetches it fired at once.
`@react-pdf/renderer`'s own internal scheduler resolves every card's `<Image src={async () => ...}>` callback with its own concurrency, entirely outside this codebase's control - a large
export could trigger dozens of simultaneous fetches, each independently exhausting its own
server-side retry budget under that contention and coming back as a permanent per-card failure.

**Fix** (`pdfImage.ts`'s `fetchFullResolutionImageAsBlob`, used by both `getPDFImageURL`'s and
`getPDFImageBlob`'s full-resolution branches - the risk applies to any full-resolution export,
not just Proposal B's bleed-normalized cards):

- A shared `Semaphore` (`common/semaphore.ts`, new - a plain acquire/release concurrency gate for
  gating an unbounded stream of ad-hoc calls from a scheduler this codebase doesn't control,
  distinct from `concurrencyLimit.ts`'s `mapWithConcurrencyLimit`, which needs a known, finite
  item list) caps client-side full-resolution fetches to `FULL_RESOLUTION_FETCH_CONCURRENCY = 3`,
  matching the server's own limit.
- Retries a 429 or 5xx (transient) up to `FULL_RESOLUTION_FETCH_MAX_RETRIES = 3` times with
  exponential backoff + jitter - a non-retryable 4xx (a real dead link) still fails on the first
  attempt, so a genuinely broken image doesn't burn retry budget that delays every other card
  queued behind the concurrency gate.
- **Live progress**: a large export paced to 3 req/s can now take several minutes (honestly
  reported, not hidden) - `PDFProps.reportImageProgress` (mirroring the existing
  `reportImageFailure` pattern, threaded through `pdf.worker.ts` → comlink's `onImageProgress` →
  `pdfRenderService` → `PDFGenerator.tsx`) drives a "Fetching images: N/M" indicator so the wait
  reads as working, not hung. `total` is an approximation (unique card count, not slot count - a
  duplicate card in the deck fetches once per slot, so `completed` can end up slightly ahead of
  it), intentionally not presented as an exact fraction for that reason.
- **In-app confirm modal, not `window.confirm()`**: the incident's own screenshot showed
  Firefox's "allow notifications?" anti-spam chrome sitting next to the native confirm dialog -
  a browser can silently start auto-suppressing FUTURE `window.confirm()` calls on an origin once
  enough of them fire near other browser-level prompts, which would turn this safeguard off with
  no visible warning. `ImageFailureConfirmModal` (a real React-rendered Bootstrap `Modal`,
  `PDFGenerator.tsx`) can't be affected by that heuristic at all.

## "HEAD request fails" console noise — historical, no longer applies

A cross-session report once flagged failed `HEAD` requests to
`img.proxyprints.ca/<id>-small-google_drive` when opening the PDF tab live,
traced to an R2 custom-domain quirk (`net::ERR_FAILED` on a HEAD-on-missing-
object, not a clean 404) that the existing bucket→worker fallback already
absorbed harmlessly. The bug-4 fix above replaced the `HEAD` check with a
real `GET`, so this specific console-noise pattern no longer occurs — kept
here as a historical note in case an old bug report referencing it resurfaces.

## Proposal B — export-time per-side bleed normalization

Full spec + approval record: `docs/proposals/proposal-b-bleed-normalization.md`. Core algorithm (`bleedNormalize.ts`: probe-median measurement per side, IQR ambiguity, fallback + manual-override plan resolution) and canvas synthesis (`bleedExtension.ts`: pure crop/extend geometry + `normalizeCardBleed`'s decode→measure→plan→draw→encode→release pipeline) are built and unit tested (12 tests across the two modules, plus 4 new `pdfImage.test.ts` tests for the `getPDFImageBlob` split). Wired into `PDF.tsx`'s `PDFCardImage`: full-resolution Google Drive/local-file images run through normalization instead of the old uniform proportional rescale; SCM mode and the thumbnail tiers are untouched (out of scope per the proposal doc).

**Shipped and tested**: the measurement/plan/extension math end-to-end, real per-card wiring in the standard (non-SCM) render path, `PDFProps.bleedPriors`/`bleedOverrides` (both optional maps keyed by card identifier, safely defaulting to `"unresolved"`/`"auto"` when absent), the main-thread batch resolution of `bleedPriors` from `APIGetTagConsensus` (bounded concurrency, per-card failure tolerance — `frontend/src/common/concurrencyLimit.ts` + `bleedPriorResolution.ts`), the manual-override UI (Auto/Force bleed/Force trimmed per card, `PDFGenerator.tsx`'s "Bleed Overrides" panel) with its `projectSlice`/localStorage persistence, and the hedged WYSIWYG preview badge ("bleed will be generated", `PagePreview.tsx` + `willLikelyGenerateBleed`). **Proposal B is complete end to end** — see `docs/proposals/proposal-b-bleed-normalization.md`'s "Shipped vs. not yet built" for the full per-PR breakdown.

**Not yet built** (both intentionally out of scope, not silently dropped): the merge-time server-side calibration pass for the four named measurement constants, and the XML round-trip field for a persisted override (flagged per the owner's own instruction, not built).

`PDF.tsx`'s per-card eligibility check (`isBleedNormalizationEligible` - full-resolution Google Drive/local-file images only) is now exported and shared, rather than re-derived: `PDFGenerator.tsx`'s `BleedOverrideSettings` panel and the display page's rail Print Options section (`frontend/src/features/display/PrintOptionsSection.tsx` - Proposal H pane migration, left-panel unification, issue #164) both call the same function, so the two surfaces' eligibility rule can't silently drift apart.

`PDFCardImage`'s effective-dpi derivation (`imageDPI` when it's set and lower than `cardDocument.dpi`, else `cardDocument.dpi`) handles the case where a lower `imageDPI` setting makes the Worker serve a downscaled image - measurement always converts px→mm against the resolution of what was actually decoded, not assumed.

**A real crash caught only by running `tests/PDFGenerator.spec.ts`, not by `tsc`/`jest`**: the first version skipped the old proportional rescale by setting `transform: "none"` when normalized. `@react-pdf/renderer`'s own stylesheet parser (`@react-pdf/stylesheet`) has a bug where any single-token transform value throws deep inside its internals (see `docs/lessons.md`'s entry for the exact mechanism) - and their custom reconciler doesn't propagate that as a rejection anywhere, so `pdf(...).toBlob()` just hangs forever with zero console/page error. All 3 download-path Playwright tests hung at their timeout; a stashed pre-Proposal-B baseline confirmed they pass cleanly with no other changes. Fixed by using `transform: undefined` (omitting the key) instead of `"none"` - all 4 tests pass afterward, matching baseline timing.

## Post-export contribution prompt (issue #166)

`useDownloadPDF`/`useSaveToDrivePDF` (this file) are the shared success
signal both real export surfaces key off: `PDFGenerator.tsx` itself now
awaits its own `downloadPDF`/`saveToDrive` button handlers and, on a
genuine success, calls `usePostExportContributionPrompt`'s
`notifyExportSucceeded()` to show a dismissible, once-per-session prompt
linking to `/whatsthat` (`frontend/src/features/export/ postExportContributionPrompt.ts` + `usePostExportContributionPrompt.ts` +
`PostExportContributionPrompt.tsx`). Two different success-detection paths,
because the two hooks return differently:

- **Download path**: `useDownloadPDF`'s returned promise resolves `void` —
  its own `useDoFileDownload` wrapper (`download.ts`) swallows the inner
  success boolean to drive the download-manager UI instead. Success is read
  back out of the same `fileDownloads` redux slice that UI already
  populates (`wasLatestCardsPdfDownloadSuccessful`, keyed off the most
  recently COMPLETED `"cards.pdf"` entry by `completedTimestamp` — every
  click enqueues a fresh entry, so this can't pick up a stale success from
  an earlier export).
- **Save-to-Drive path**: `useSaveToDrivePDF` has no such wrapper —
  `.finally()` passes its `.then()`'s resolved boolean straight through, so
  `await saveToDrive()` already gives the real success/cancelled value
  directly.

This used to also be mounted from `DisplayPage.tsx`'s own inline export
(Proposal H, item 2) — issue #275 retired that pipeline entirely (the
memory-heavy Generate PDF/Save-to-Drive operations now live solely here,
reached from `/display`'s Finish footer via a pre-print save gate; see
`docs/proposals/proposal-h-display-layout-spec.md`'s [Finish
Footer](../proposals/proposal-h-display-layout-spec.md#finish-footer-save-before-print)
and [Print-Page
Funnel](../proposals/proposal-h-display-layout-spec.md#print-page-funnel-destination)
decisions). The later Proposal H route swap (2026-07-23, issues #231/#272)
fully unrouted the classic grid `ProjectEditor.tsx` as well (component kept
in-tree, deletion is a separate later decision) — this component's only
LIVE mounts today are `FinishedMyProject.tsx`'s PDF tab (reached solely via
the standalone `/print` route, `pages/print.tsx`) and `PDFGeneratorModal.tsx`
(mounted globally via `Modals.tsx`, route-independent); one implementation
either way, not a forked second copy. See `docs/features/printing-tags.md`'s
own entry for the full detail (why `/whatsthat` and not a new route, the
`sessionStorage`-backed "never repeats within a session" rule) and
`docs/features/print-export-page.md` for the classic "Print!" tab's own
(now unrouted) history.

## Key files

- `frontend/src/features/pdf/PDFGenerator.tsx`,
  `frontend/src/features/pdf/pdfImage.ts` (+ `pdfImage.test.ts`)
- `frontend/src/features/pdf/PDF.tsx`, `frontend/src/features/pdf/scm/SCMPDF.tsx`
  (both thread `reportImageFailure` down to their per-card `<Image>`)
- `frontend/src/features/pdf/pdf.worker.ts` (owns the per-render
  `failures` array — see bug 4), `pdfRenderService.ts`, `useRenderPDF.ts`
- `frontend/src/features/pdf/PDFCanvasPreview.tsx`
- `frontend/scripts/copy-pdf-worker.js`
- `frontend/src/features/pdf/PDFGeneratorModal.tsx`,
  `frontend/src/features/export/FinishedMyProject.tsx`,
  `frontend/src/components/ProjectEditor.tsx`
- `frontend/src/features/export/postExportContributionPrompt.ts` (+
  `postExportContributionPrompt.test.ts`),
  `frontend/src/features/export/usePostExportContributionPrompt.ts`,
  `frontend/src/features/export/PostExportContributionPrompt.tsx` — issue
  #166's post-export contribution prompt
- `frontend/tests/PDFGenerator.spec.ts` — mocked-CDN Playwright coverage for
  bug 4 (preview warning, confirm-gated download/cancel, and a real-image
  success-path regression check)
- `frontend/tests/PostExportContributionPrompt.spec.ts` — issue #166
  coverage against this component's one remaining live mount, `/print`'s
  PDF tab (re-homed there from the classic "Print!" tab in the 2026-07-24
  parked-spec port wave, issue #272 — the second, `/display`-inline-export
  surface this file used to also cover was already retired by issue #275,
  above)

## Status

All four bugs verified fixed. The first three are deployed and confirmed
live; bug 4 is verified only in a mocked sandbox (see its merge-time
checklist item in the frontend-polish PR) pending a live-backend check.
Upstream PR #463 (lazy WASM load fix) is open; #464 (canvas preview) and
#466 (thumbnail routing) were closed after the maintainer said the existing
upstream behavior is deliberate design for their codebase, not a bug — see
[[../infrastructure.md]] for PR status details. Don't "fix" this fork's PDF
tab implementation to match upstream's on those two points; both are
correct for their own codebase.

See also [[google-drive-connect.md]] for the separate "Save PDF directly to
Google Drive" upload feature on this same tab.
