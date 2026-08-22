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
   `Tab.Pane`s that mounted it (`PDFGeneratorModal.tsx` — and, before the
   `/print` retirement below, `FinishedMyProject.tsx` and
   `ProjectEditor.tsx`).
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
  `pdfRenderService` → `PDFGenerator.tsx`) drives progress feedback so the wait reads as working,
  not hung. `total` is an approximation (unique card count, not slot count - a duplicate card in
  the deck fetches once per slot, so `completed` can end up slightly ahead of it), intentionally
  not presented as an exact fraction for that reason. See "PDF-generation wait experience" below
  for the current UI this drives (a real `ProgressBar`, not the bare text line this originally
  shipped as).
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

## #301 — croppable bleed, merged bleed boxes, split-the-difference gutters

Owner decisions, 2026-07-21/29, extending Proposal B above: bleed is now a resource the layout
may CROP, not a rigid box that gets a whole card dropped when it doesn't fit. #299 (Proposal B,
above) still produces the resource - `resolveBleedPlan`/`normalizeCardBleed` still measure and
synthesize each card's bleed to exactly the configured target (`bleedEdgeMM`) on every side. #301
decides how much of that carried bleed actually RENDERS, given the page - neither replaces the
other.

**The fit math (`layout.ts`)**: `bleedEdgeMM` is now a per-edge MAXIMUM, not a fixed addend.
`fitAxisWithBleed` (replacing the old `fitCardsInDimension`) fits card COUNT from the bare card
size alone (no bleed at all) - a crowded axis that used to drop a whole card the moment full
bleed didn't fit now keeps every card and shrinks bleed instead. Whatever space is left over
after the bare-card fit is handed out via a water-filling formula: every one of an axis's
`2*count` half-boundaries (both page edges and every shared interior gutter's two facing halves)
draws from the same slack pool equally - "split the difference" at a gutter and "page edge/margin
caps are just another constraint on the same clamp" both fall out of that one formula, not two
code paths. `computeLayout`'s `LayoutSlot` now carries a `bleedMM: {top,bottom,left,right}` -
uniform across every slot on the page (per-AXIS, not truly per-slot - see `LayoutSlot.bleedMM`'s
own comment for why that's correct here, not a simplification), so a card can be full bleed on
one axis (say top/bottom) while cropped on the other (left/right), but never asymmetric left-vs-
right or top-vs-bottom within this grid's regular geometry. Regression-guarded: when there's
enough slack to grant the full target everywhere (the common case), the new formula reduces to
byte-identical output to the pre-#301 rigid fit (`layout.test.ts`'s dedicated regression-guard
describe block proves this against the old formula directly, not just self-consistency).

**Per-edge crop windows (`pdfImage.ts`)**: `computeBleedCropMM`/`computeRenderedBleedMM` are pure
mm-domain geometry - `max(0, carried - available)` per edge for the crop, `min(carried, available)` for what actually renders. `computeBleedCropWindowPx` converts to source-image pixels
at the card's own dpi for a caller that wants a true pixel crop. A card whose plan carries no
bleed at all (a trimmed source, or any card `isBleedNormalizationEligible` rejects) always
computes a 0 crop, never negative - "up to X available," never "X or a dropped card."

**Export (`PDF.tsx`)**: `PDFCardImage` sizes each card's destination box to
`CardSize + renderedBleedMM` (may be less than the configured target on a crowded axis) and,
for a #299-normalized (bleed-normalized) card, crops the oversized synthesized image down to
that box via a CSS technique - the full-target-bleed `<Image>` sits at a negative offset inside
an `overflow: hidden` wrapper sized to the rendered box, rather than a second canvas decode/
crop/re-encode pass (the visible PDF output is pixel-identical either way; this keeps the
crop as pure, unit-tested geometry in `pdfImage.ts` with no new imperative canvas code - see
that module's own boundary-of-thin-imperative-work comment, same shape as `bleedExtension.ts`'s
split). Cut lines (`CutLineCorner`, `PDFCardCutLines`, `PageCutLines`) mark the TRUE card edge -
`bleedMM.<edge>` in from the slot boundary, not a flat offset - so a cut line stays correct even
when its slot is cropped below the configured target. The non-normalized path (thumbnail-tier,
SCM, any source `isBleedNormalizationEligible` rejects) keeps the pre-#301 proportional CSS
rescale (a real per-edge pixel crop isn't available for that path - unchanged limitation, not a
#301 regression), just targeting the new (possibly smaller) rendered box instead of the flat
configured target.

**Preview (`PagePreview.tsx`)**: reads `computeLayout`'s own `slot.widthMM`/`heightMM`/`bleedMM`
directly (previously assumed a flat `CardSize + 2*bleedEdgeMM` for every slot) - same
`computeLayout()` call the exporter uses, so slot sizes and cut-line positions agree with the PDF
by construction, not by parallel maintenance.

**Trailing-edge / bordered-profile warning (`marginProfiles.ts` + `MarginProfileControl.tsx`)**:
`maxBleedForFourColumns`'s FORMULA is unchanged (it already computed exactly the per-edge bleed
`fitAxisWithBleed`'s water-filling converges to at a fixed count of 4 - the same expression,
re-derived) - only what exceeding it MEANS changed. Pre-#301 it meant "the sheet drops from 4
columns to 3"; post-#301 it means "bleed on the affected edge crops to this cap, all 4 columns
stay." `MarginProfileControl`'s warning copy was rewritten from a vague "see the warning above"/
"fewer cards per row" pointer into the owner's mandated disclaimer: bleed is cropped to N mm on
the affected edge, with reduced cutting tolerance there - stated outright, not implied. Still
never a hard clamp on the bleed input itself (unchanged from before this round).

**Superseded**: `MarginProfileControl`'s boolean warning described above no longer exists.
`BleedGrantedReadout.tsx` replaced it with a per-axis granted-vs-requested number, reading
`computeLayout`'s own output directly rather than a separate cap comparison — see
[`user-guide.md`](../user-guide.md#exporting-a-print-ready-pdf) for the current behaviour and
[`proposals/proposal-h-display-layout-spec.md`](../proposals/proposal-h-display-layout-spec.md#b0-granted-vs-requested-bleed-readout)
for the decision record. `maxBleedForFourColumns`'s formula is still what the readout's numbers
converge to; only the disclaimer-copy warning it used to feed is gone.

**Known limitation, not fixed here**: a #299-normalized card is ASSUMED to carry exactly
`bleedEdgeMM` on every side for crop-window purposes (matching `normalizeCardBleed`'s own
contract) - the rare case where a too-small source hit `bleedExtension.ts`'s own
`clampOpposingCrop` shortfall (a real, already-documented "slightly-short bleed margin" trade
there) isn't visible from outside that module without touching it, which is out of this pass's
scope (`bleedNormalize.ts`/`bleedExtension.ts` are #299's contract - see this doc's own Proposal
B section and those files' own header warnings about a past unilateral change to that
resolution order).

**Key files**: `frontend/src/features/pdf/layout.ts` (+ `layout.test.ts`),
`frontend/src/features/pdf/pdfImage.ts` (+ `pdfImage.test.ts`),
`frontend/src/features/pdf/PDF.tsx`, `frontend/src/features/pdf/PagePreview.tsx`,
`frontend/src/features/display/marginProfiles.ts` (+ `marginProfiles.test.ts`),
`frontend/src/features/display/MarginProfileControl.tsx` (+ `.test.tsx`),
`frontend/tests/DisplayPage.spec.ts`'s margin-profile-control test (rewritten for the new
behavior - old title ack'd in `.github/coverage-acks.txt`).

## PDF-generation wait experience (SPEC-cardback-pdfwait.md §D, PKG2)

> **Retired 2026-08-14 with `/print`** — `PDFWaitPanel.tsx` was the PDF tab's own wait UI, and
> the PDF tab (with its host `PDFGenerator.tsx`, `FinishedMyProject.tsx`, `pages/print.tsx`)
> was deleted in the `/print` retirement (see "Printshop ordering guides" below). `/editor`'s own
> PDF export (`DisplayExportPDF.tsx`/`pdfDownload.tsx`) never mounted this panel — it downloads
> straight from a button press, so its export wait is the download manager's own progress, not
> this. The section below is kept as history.

`PDFGenerator.tsx` derives a `waitPhase` (`"idle" | "fetching" | "assembling" | "done"`) from the
existing `isDownloading`/`isSavingToDrive` + `imageFetchProgress` state, rather than tracking it as
independent state - fewer places that can drift out of sync. `imageFetchProgress == null` reads as
`"fetching"` (nothing reported yet, not `"assembling"` - a real bug caught by this round's own
Playwright coverage: treating the brief pre-first-callback window as null-means-assembling flashed
"Assembling PDF…" before any fetch had actually started).

- **2a - progress bar** (`PDFWaitPanel.tsx`'s `PDFProgressBox`, replaces the old bare
  `pdf-image-fetch-progress` text line): a real Bootstrap `ProgressBar`, determinate
  (`now={min(completed/total,1)*100}`, capped at 99% - never a false 100% before the phase
  genuinely ends) while fetching, honest indeterminate (`animated striped`, `aria-busy`) while
  assembling (no progress callback exists for `@react-pdf/renderer`'s own layout/encode phase -
  Annex A-3/`PB1`: swap to determinate if a future render seam exposes one), and a green `done`
  bar once the export genuinely succeeds.
- **2b - embedded "What's That Card?" game** (`PDFWaitPanel.tsx`'s `PDFWaitGameEmbed`): the right
  column (normally the live PDF preview) becomes a chrome frame around `<QuestionFeed>` rendered
  **verbatim** (`next/dynamic({ssr:false})`, imported only once `isDownloading`/`isSavingToDrive`
  flips true - never eagerly bundled while a user is still configuring the PDF, mirroring bug 1's
  own lazy-WASM posture above) plus a persistent build-status ribbon. No forked component, no new
  voting mechanic - the exact `/whatsthat` funnel (`docs/features/printing-tags.md`). Torn down
  (unmounted) the instant generation finishes, replaced by the existing
  `PostExportContributionPrompt` as the embed's own outro (context-aware "one nudge, not two" -
  the standalone bottom-of-settings mount, described below, is suppressed whenever this outro is
  already showing the same prompt in the right column).

## Cardback reminder gate on the classic direct "Generate PDF"/"Save PDF to Google Drive" buttons

> **Historical** — this section describes the gate's original `/print`-side call sites. The
> `/print` page and `PDFGenerator.tsx` were retired 2026-08-14; the gate itself still runs,
> composed inside `usePrePrintSaveGate.startPrintFlow` wrapping `DisplayExportPDF`'s own
> Download/Save-to-Drive buttons (see "Editor-native PDF export" and "Printshop ordering guides"
> below). One call site instead of two now, but the same hook, key, and session semantics.

A user can reach `/print` directly (bookmark, refresh, any entry that skips the editor's Finish
footer/`usePrePrintSaveGate` entirely) - so `PDFGenerator.tsx`'s own Generate/Save-to-Drive click
handlers wrap themselves in `useCardbackReminderGate` (`frontend/src/features/display/ useCardbackReminderGate.tsx`) independently of `PrePrintSaveGate.tsx`'s own composition of the
same hook. Both call sites read the same per-project `sessionStorage` suppression key
(`cardbackReminderSuppression.ts`), so passing through the reminder once (from either entry) is
enough for the rest of that session - see `docs/features/printing-tags.md`'s neighbour,
`SPEC-cardback-pdfwait.md` §C.1, for the gate's own full design.

## Card selection modes and the default

`PDFGenerator.tsx`'s "Card Selection" settings offer four modes
(`CardSelectionMode` in `frontend/src/features/pdf/PDF.tsx`, each backed by a
paginator in `CardSelectionModeToPaginator`):

- **Fronts + Backs** — every card's front and back, front pages interleaved
  with their corresponding back pages (F1, B1, F2, B2, …), so duplex output
  collates correctly.
- **Fronts + Distinct Backs** — every front, plus only the backs that differ
  from the project's shared cardback. The shared cardback is deliberately
  omitted: it is meant to be printed in bulk once (a "Backs Only" export of
  the cardback, or cardback sheets the user already has), not once per card.
- **Fronts Only** / **Backs Only** — one side only.

The default is **Fronts + Backs**. It used to be Fronts + Distinct Backs,
which silently produced a fronts-only file for the ordinary deck whose cards
all share the project cardback — exactly the scenario the pre-print cardback
reminder gate warns about — with no warning that backs were missing. A deck
that relies on a single shared cardback must still export a duplex-printable
file by default; users who want the paper-saving behaviour select Fronts +
Distinct Backs explicitly. The default lives in
`DEFAULT_CARD_SELECTION_MODE` (same file), consumed by `PDFGenerator.tsx`'s
`useState` initialiser and asserted by `pagination.test.ts`.

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
memory-heavy Generate PDF/Save-to-Drive operations moved solely to
`/print`, reached from `/editor`'s Finish footer via a pre-print save gate;
see `docs/proposals/proposal-h-display-layout-spec.md`'s [Finish
Footer](../proposals/proposal-h-display-layout-spec.md#finish-footer-save-before-print)
and [Print-Page
Funnel](../proposals/proposal-h-display-layout-spec.md#print-page-funnel-destination)
decisions). After the `/print` retirement (below), this prompt has **no live
mount at all**: `PDFGenerator.tsx` was its only mount, and that file (with
`FinishedMyProject.tsx`, `pages/print.tsx`, and `PDFGeneratorModal.tsx`) is
deleted; the implementation files
(`postExportContributionPrompt.ts` + `usePostExportContributionPrompt.ts` +
`PostExportContributionPrompt.tsx`) and their test remain in-tree as
unmounted dead code, kept because the `/whatsthat` funnel they promote is
still live. `/editor`'s own PDF export item (see "Editor-native PDF export"
below) reuses `useDownloadPDF` but never mounted this prompt. See
`docs/features/printing-tags.md`'s own entry for the full detail (why
`/whatsthat` and not a new route, the `sessionStorage`-backed
"never repeats within a session" rule) and `docs/features/print-export-page.md`
for the classic "Print!" tab's own (now retired) history.

## Editor-native PDF export (`/editor`'s Export ▾ menu)

`/editor` (`DisplayPage.tsx`) had no PDF export of its own after issue #275
above retired its inline pipeline — its Export ▾ menu (`DisplayExportMenu.tsx`)
offered only XML/Card Images/Decklist, and its own centre sheet (a real
`computeLayout()`-driven `PagePreview`, not a preview of the PDF) had no
export action at all. The only way to get a PDF was navigating to `/print`,
whose `PDFGenerator.tsx` carries an entirely separate settings panel that
never read `/editor`'s own `DisplaySheetSettings`/margin-profile/card-spacing
state — a rail configured for LETTER landscape 4x2 could silently export an
A4 3x3 PDF.

Two pieces close that gap, without forking the render pipeline:

- **`pdfDownload.tsx`** — `useDownloadPDF`/`useSaveToDrivePDF`/
  `ImageFailureConfirmModal`/`ConfirmDespiteFailures`, moved out of
  `PDFGenerator.tsx` verbatim (no logic changes) so `/editor`'s own PDF item
  can reuse the exact download plumbing `/print` uses without statically
  importing `PDFGenerator.tsx` itself — that module pulls in
  `PDFCanvasPreview` (`pdfjs-dist`) and its whole settings panel, which
  `/editor`'s page must not pay for (its sheet already IS the preview).
  `PDFGenerator.tsx` now imports these same functions back from here.
- **`displayPdfProps.ts`** — the one adapter from `/editor`'s live state
  (`DisplaySheetSettings`, the margin-profile/card-spacing redux slices,
  project members/cardback, and `projectSlice.manualOverrides`) to the
  `PDFProps` shape `PDF.tsx` already consumes. `PDF.tsx`'s `PageSize` table
  is portrait-oriented; `/editor`'s sheet is landscape by convention
  (width/height swapped), so the adapter always emits `pageSize: "CUSTOM"`
  with the swapped dimensions computed from the rail's own page-size
  selection via the same `getPageSizeMM` lookup (now factored out into its
  own `pageSize.ts` module so both `PDF.tsx` and this adapter share it,
  rather than one importing the other's page-size table). Every `PDFProps`
  field with no editor equivalent yet (quality/DPI, corner rounding, cut-line
  geometry beyond the rail's single Guides toggle, SCM settings, per-side
  page margins beyond the margin profile, card selection mode) gets an
  explicit named default in this one module — see its own module comment for
  the full list and reasoning, including why the rail's Fronts/Backs toggle
  is deliberately NOT read as a card-selection filter.

`DisplayExportPDF.tsx` (the new fourth `Dropdown.Item` in
`DisplayExportMenu.tsx`) wires the two together: `useDisplayPDFProps` for
props, `useDownloadPDF` to trigger the download, `ImageFailureConfirmModal`
for the same blank-card safeguard bug 4 above added. It mounts no preview of
its own (no `PDFCanvasPreview`, no fast DOM preview) — the sheet the user is
already looking at makes one redundant, and rendering a second one live on
this page would cost it the render budget it has to stay fast. The rail's
"Guides" toggle (`DisplaySheetSettings.showCutLines`), which previously only
drove `PagePreview`'s on-screen lime corner guides, now reaches the exported
file's `drawCardCutLines` through this same adapter, with cut-line
placement/length/thickness/offset defaults matching that on-screen guide
style (`InsideOnly`, `Inside`) so the export looks like the sheet that
produced it.

### Editor export controls (card selection, page range, quality, cut-line style)

`displayPdfProps.ts`'s original defaults covered every `PDFProps` field the
rail had no control for at all. Four of those became real controls in this
pass. **Note, current-code correction**: card selection mode, page range,
image quality, and cut-line appearance all subsequently migrated OUT of
`DisplayExportPDF.tsx`'s own settings step into the right rail proper (card
selection mode/page range into a new "Export" section, image quality/corner
rounding into "Print quality", cut-line appearance next to the Guides
toggle) - see `DisplaySheetExportSettings` in `displayPdfProps.ts` for where
each one lives today. **Further correction**: the per-side page-margin
override also subsequently migrated to the rail (see "Editor export controls,
part 2" section's own correction note below) - only SCM mode/its six
sub-settings and the page-level cut guide toggle remain genuine export-RUN
choices behind the dialog. The bullets below describe this pass's
ORIGINAL shape (kept for history); treat `displayPdfProps.ts`'s own module
comment as the current source of truth for which settings object owns which
field.

- **Card selection mode** — the four `CardSelectionMode` options
  (`PDF.tsx`), each with a one-line explanation, since the names alone
  mislead ("Fronts + Distinct Backs" sounds like it emits backs, and for a
  deck where every card uses the shared project cardback it emits none).
  The starting value reads `DEFAULT_CARD_SELECTION_MODE` (`PDF.tsx`) rather
  than a literal, so a change to that constant moves both `/print` and
  `/editor` together. Now a rail control (the "Export" section), not the
  export dialog's.
- **Page range** — `PDFProps.pageRangeStart`/`pageRangeEnd` (1-indexed,
  inclusive, `undefined` on either bound meaning "no restriction on that
  end"). `PDF.tsx`'s pagination itself is unchanged; a `sliceToPageRange`
  step slices the already-paginated `pages` array afterwards, clamped
  defensively against the real count. That real count is what
  `computePDFPageCount` (`PDF.tsx`, also exported) is for: pagination can
  only run once page size, margins, spacing, bleed, and card selection mode
  are all known, so the rail's own "Export" section calls this against its
  own live sheet state to show "N total" and bound the range inputs against
  a real number, rather than letting a request outlive the actual page
  count (deliberately computed against the margin PROFILE, not
  `DisplaySheetExportSettings.marginOverride` - that override's EFFECT stays
  scoped to the export only, same as before it moved into the rail's own
  state, so this readout reflects the profile's own margins, same as the
  live sheet). Now a rail control, not the export dialog's.
- **Image quality (DPI, JPG quality)** — sliders at the same 100–1500 DPI /
  5–100% ranges `/print`'s own `CardQualitySettings` panel used, so output
  stayed comparable between the two surfaces while both existed. Now a rail
  control (the "Print quality" section) - see `DisplaySheetExportSettings. imageDPI`/`jpgQuality`.
- **Cut-line colour and shape** — shown only when the rail's Guides toggle
  is on (nothing to style when no cut lines are drawn). Now a rail control,
  next to the Guides toggle it depends on - see
  `DisplaySheetExportSettings.cutLineColor` (the shape select was later
  retired outright in favour of a single crosshair-marks toggle, per the
  "Print cut-guide redesign" coverage-ack entry).

### Editor export controls, part 2 (SCM cutting mode, corner rounding, cut-line geometry, page margins, custom page size)

The remaining `displayPdfProps.ts` named defaults from the first pass above became real
controls too, all in `DisplayExportPDF.tsx`'s own settings step at the time — every default they
replaced was removed from the adapter's default block, not left shadowed (the same pattern the
first pass established). **Note, current-code correction**: corner rounding subsequently migrated
to the rail's "Print quality" section alongside image quality (see the note above the first
"Editor export controls" section) - it is `DisplaySheetExportSettings.roundCorners` today, not
`DisplayExportSettings.roundCorners`. **Further correction**: the per-side margin override
subsequently migrated too (see its own bullet below) - only SCM mode and its six sub-settings
remain genuine dialog-only export-RUN choices.

- **Silhouette (SCM) cutting mode** — `DisplayExportSettings.scmMode` plus its six sub-settings
  (`scmPaperSize`, `scmVariant`, `scmRegistration`, `scmDuplex`, `scmOffsetXMM`/`scmOffsetYMM`,
  `scmOffsetAngleDeg`). `PDF.tsx`'s `PDF` component returns straight into `<SCMPDF>` for
  `scmMode: true` and never touches card selection, cut-line geometry, corner rounding, or page
  margins for that render — a genuinely different output format, not a style option on the
  standard grid. The settings step reads this the same way: a switch at the top of the modal
  swaps its ENTIRE body between the standard-grid panel and SCM's own six controls, rather than
  appending SCM's settings to the existing list (where they'd be meaningless whenever SCM is
  off, and the standard controls would be equally meaningless whenever SCM is on). Only image
  quality (DPI/JPG) is genuinely shared — `SCMCard` reads it exactly like the standard grid's own
  card image does — so it's the one group visible in both panels.
- **Corner rounding** — `DisplayExportSettings.roundCorners` at the time (now
  `DisplaySheetExportSettings.roundCorners`, see the correction note above), a single
  Round/Square switch next to the cut-line group below (standard-grid panel only; SCM's own
  template never reads `roundCorners`).
- **Cut-line geometry** — `cutLinePlacement`/`cutLineLengthMM`/`cutLineThicknessMM`/
  `cutLineOffsetMM` extend the existing colour/shape group from the first pass above (same
  `Form.Group`, same `showCutLines`-gated visibility) rather than starting a second one.
- **Per-side page margins** — the rail's margin PROFILE (`marginProfileSlice`, three named
  presets) still drives both the live sheet and, by default, the export, unchanged. The four
  independent per-side values a real print run sometimes needs are a genuinely finer model than
  a 3-option preset, so they're an opt-in ADVANCED OVERRIDE scoped to a single export run,
  `undefined` by default. Turning the override on seeds it from the current profile's own values
  (so the numbers a user first sees are never a jarring unrelated default), and the four fields
  become editable from there; turning it off restores `undefined` — back to reading the profile
  exactly as before this field existed. The profile itself, the live sheet, and every other
  export are never touched by the override. **Further correction**: subsequently migrated to
  `DisplaySheetExportSettings.marginOverride` (not `DisplayExportSettings.marginOverride`) and
  the rail's own Page Setup section, grouped directly under the margin-profile control it
  overrides rather than the export dialog - the same rail-migration reasoning the other controls
  in this section already got, applied to a manual override of a rail-owned decision rather than
  an unrelated one-off export-run choice like SCM mode.
- **Custom page dimensions** — the rail's own paper-size `Form.Select` (`DisplayPage.tsx`'s Page
  Setup section) gains a `Custom` option (`PageSize.CUSTOM`, already supported by `PDFProps`/
  `getPageSizeMM` — the gap was only the rail's own option list), with two mm inputs (portrait
  convention, same as every other table entry) that appear once selected. Chosen as a rail
  control rather than an export-only one because page size already IS a rail-owned, shared field
  — the live sheet and the export have read the exact same `pageSize` since the first "Editor
  export controls" pass, and Custom is a straightforward additional value on that same field, not
  a different model requiring a coexistence decision (unlike the page-margin override above).
  Picking `Custom` seeds both mm fields together, in the same state update, from whatever paper
  size was selected immediately before — never a transient undefined pair.

### Page cut guide lines, Google Drive save, and retiring the Finish footer's own print route

A rescue-inventory pass against `/print`'s `PDFGenerator.tsx` found two capabilities still missing
from the editor after the passes above: the page-level cut guide toggle, and Save PDF to Google
Drive. Both are now real controls on `/editor`, and with Drive save no longer print-page-only, the
Finish footer's separate "Print / Export →" button — the last thing routing the editor anywhere to
export — was retired in the same pass.

- **Page cut guide lines** — `DisplayExportSettings.drawPageCutLines`, a switch in
  `DisplayExportPDF.tsx`'s settings step alongside the existing cut-line group, mapped straight
  through the adapter to `PDFProps.drawPageCutLines` (previously a hardcoded `false` in
  `displayPdfProps.ts`'s own default block — removed from that block entirely, not left shadowed,
  the same pattern the two "Editor export controls" passes above established). This is a genuinely
  different guide from `sheetSettings.showCutLines`/`drawCardCutLines`: that toggle marks each
  card's own trim boundary, while page cut lines mark guides across the whole sheet for a
  guillotine cutting a printed stack — the two are independent, and the settings step's own switch
  is never gated on the card cut-line toggle. Defaults to `true`, matching `/print`'s own
  `PDFGenerator.tsx` default, so a workflow that depended on page guides keeps them on the editor.
- **Save PDF to Google Drive** — `DisplayExportPDF.tsx`'s Modal footer now offers a "Save PDF to
  Google Drive" button beside Download PDF, reusing `pdfDownload.tsx`'s `useSaveToDrivePDF`
  unchanged (no forked upload logic) and gated behind the same `isGoogleDriveAppConfigured()`
  check `PDFGenerator.tsx`'s own Drive button uses — absent when Drive isn't configured, rather
  than present-but-broken.
- **Finish footer collapse** — `FinishFooter.tsx`'s separate `Print / Export →` button (the last
  in-app route to `/print`) is gone; `Save Deck` is now the footer's sole primary button, and PDF
  export lives solely in the Export ▾ dropdown's existing "PDF" item. The two behaviours that
  button used to gate before navigating away — `usePrePrintSaveGate`'s draft-flush and
  save-before-export prompt, and its composed `useCardbackReminderGate` — still run, just wrapped
  around `DisplayExportPDF`'s own Download/Save-to-Drive clicks instead of a navigation:
  `usePrePrintSaveGate.startPrintFlow` now takes the actual export action as a `proceed` parameter
  rather than hardcoding a `router.push("/print")`, and that gate function (`runExportGate`) is
  threaded down from `DisplayPage.tsx`'s one shared `usePrePrintSaveGate` instance through
  `FinishFooter`/`DisplayExportMenu` to `DisplayExportPDF`'s two buttons. With that, `/print` had
  no in-app entry point left, and the page itself — `pages/print.tsx`, `PDFGenerator.tsx`,
  `FinishedMyProject.tsx`, `Export.tsx`, `ExportPDF.tsx`, `PDFCanvasPreview.tsx`,
  `PDFWaitPanel.tsx`, and `PDFGeneratorModal.tsx` — was deleted in the same retirement that moved
  the printshop ordering guides into the Export menu (see "Printshop ordering guides" below).

### Bleed-normalization signal on the editor sheet

`willLikelyGenerateBleed` (`bleedNormalize.ts`) — the cheap, preview-only
hedge for whether export is expected to synthesize bleed for a given card —
used to be reachable only from `PDFGenerator.tsx`'s own fast preview
(`fastPreviewSlots`), so `/editor`'s sheet never showed the badge
`PagePreview`'s `willGenerateBleed` slot flag already supports rendering.
`DisplayPage.tsx` now resolves the same signal for its own sheet: bleed
priors for every eligible card (`isBleedNormalizationEligible`, `PDF.tsx` —
full-resolution Google Drive/local-file sources only, since this page always
exports at full resolution) are fetched via `resolveBleedPriors`
(`bleedPriorResolution.ts`) and debounced the same way the fast preview
debounces its own identifier list, then combined with
`projectSlice.manualOverrides` using the same "only render once there's a
real signal to hedge on" gate the fast preview uses, so the badge never
flickers wrong-then-right while a prior fetch is still in flight. This was a
prerequisite for retiring `/print`: with that page deleted, `PDFGenerator.tsx`'s
own copy of this wiring went with it, and the editor sheet is the only place
left that shows it.

## Printshop ordering guides (the retired `/print` "Print!" tab)

The three printshop ordering instructions that used to live on `/print`'s "Print!" tab
(`FinishedMyProject.tsx`) — PringlePrints, MakePlayingCards, and NotMPC — now live in
`frontend/src/features/export/DisplayExportPrintshops.tsx`, opened from `/editor`'s Export ▾
menu as a "Printshops" item (`data-testid="export-printshops-button"`) that shows a modal with
one tab per printshop, each titled with its flag (`@/components/flags.tsx` — the same vendored
static SVGs the old tab bar used; deliberately not unicode emoji flags, which Windows browsers
render as plain letter pairs, see `print-export-page.md`'s retirement note for the full history).

The instructions are ported verbatim from the retired tab, including the "steps current as of
July 2026 — confirm before ordering" caveats and the TODO comments flagging the NotMPC and
PringlePrints flows as site-read-derived rather than manually walked through. Two step-1
rewrites for the new home: the MakePlayingCards tab's first step now points at the Export menu's
own XML item (the old in-tab "Download Project as XML" button is gone — the Export menu's XML
item is the same `useDownloadXML`-driven download), and the PringlePrints tab's first step now
points at the Export menu's own PDF item instead of the old "PDF" tab. The MakePlayingCards tab
keeps the desktop-tool download buttons, `MobileStatus`, and `Coffee` tip jar.

The modal opens with a home-printing guidance `Alert` (this is the export affordance's single
placement for it, deliberately not duplicated on the PDF item): print at 100% / Actual Size
rather than "Fit to Page", and use borderless printing with Expansion at its minimum — a scaling
driver enlarges the whole sheet, which no page-layout setting can compensate for.

## Key files

- `frontend/src/features/pdf/pdfImage.ts` (+ `pdfImage.test.ts`)
- `frontend/src/features/pdf/PDF.tsx`, `frontend/src/features/pdf/scm/SCMPDF.tsx`
  (both thread `reportImageFailure` down to their per-card `<Image>`)
- `frontend/src/features/pdf/pdf.worker.ts` (owns the per-render
  `failures` array — see bug 4), `pdfRenderService.ts`, `useRenderPDF.ts`
- `frontend/scripts/copy-pdf-worker.js`
- `frontend/src/components/ProjectEditor.tsx` (kept in-tree, unrouted since
  the Proposal H switchover — its "Print!" tab and Export/FinishedMyProject
  mounts were removed with the `/print` retirement)
- `frontend/src/features/export/postExportContributionPrompt.ts` (+
  `postExportContributionPrompt.test.ts`),
  `frontend/src/features/export/usePostExportContributionPrompt.ts`,
  `frontend/src/features/export/PostExportContributionPrompt.tsx` — issue
  #166's post-export contribution prompt (kept in-tree, unmounted dead code
  since the `/print` retirement — see its section above)
- Editor export rescue (docs' own "Editor-native PDF export" section, below):
  once `Print / Export` stopped navigating anywhere, `/print` lost its last
  in-app entry point (`pages/print.tsx`'s own comment — only a direct/
  bookmarked URL reaches it, always with an empty project), so
  `PDFGenerator.tsx`'s bug-4 (image-fetch failures) and issue #166
  (post-export contribution prompt) Playwright coverage — `PDFGenerator.spec.ts`,
  `PagePreview.spec.ts`, `PostExportContributionPrompt.spec.ts`,
  `PDFWaitExperience.spec.ts` — was dropped rather than ported: none of it
  has a reachable equivalent on `/editor`'s own inline export
  (`DisplayExportPDF.tsx`/`pdfDownload.tsx` never mount `PDFWaitPanel.tsx`,
  the component these files' progress-bar/game-embed assertions targeted).
  See `.github/coverage-acks.txt`'s "Editor export rescue, continued" entry
  for the full reasoning.
- `frontend/src/features/pdf/pdfDownload.tsx`, `frontend/src/features/pdf/pageSize.ts`
  — shared download plumbing and page-size table, factored out of
  `PDFGenerator.tsx`/`PDF.tsx` respectively so `/editor`'s own PDF export
  item can reuse them (see "Editor-native PDF export" above)
- `frontend/src/features/pdf/displayPdfProps.ts` (+ `displayPdfProps.test.ts`),
  `frontend/src/features/export/DisplayExportPDF.tsx`,
  `frontend/src/features/export/DisplayExportMenu.tsx`,
  `frontend/src/features/export/DisplayExportPrintshops.tsx` — `/editor`'s own PDF
  export item, its editor-state-to-`PDFProps` adapter, and the printshop
  ordering guides (see "Printshop ordering guides" above)

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
