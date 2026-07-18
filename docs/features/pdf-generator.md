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

**Shipped and tested**: the measurement/plan/extension math end-to-end, real per-card wiring in the standard (non-SCM) render path, `PDFProps.bleedPriors`/`bleedOverrides` (both optional maps keyed by card identifier, safely defaulting to `"unresolved"`/`"auto"` when absent).

**Explicitly not yet built** (next concrete steps, not silently dropped):
1. The main-thread batch resolution of `bleedPriors` from `APIGetTagConsensus` (per the approved spec's fallback prior) — `PDFGenerator.tsx` doesn't populate this map yet, so every ambiguous side currently falls through to the safe default (`"unresolved"` → extend the full target) rather than a real per-card machine-vote lean. This needs its own concurrency-bounded batch fetch (one card's tag consensus can fail without failing the whole export) and hasn't been built or tested yet - building it without that care would risk exactly the kind of half-tested network code this proposal's own memory-discipline section was written to guard against.
2. The manual override UI (Auto / Force bleed / Force trimmed per card) and its persistence in project state - `resolveBleedPlan` already fully supports all three modes (tested), but nothing in the UI sets `bleedOverrides` yet.
3. The WYSIWYG preview badge ("bleed will be generated") in `PagePreview.tsx` - the preview still shows the pre-Proposal-B cheap CSS approximation only.

`PDFCardImage`'s effective-dpi derivation (`imageDPI` when it's set and lower than `cardDocument.dpi`, else `cardDocument.dpi`) handles the case where a lower `imageDPI` setting makes the Worker serve a downscaled image - measurement always converts px→mm against the resolution of what was actually decoded, not assumed.

**A real crash caught only by running `tests/PDFGenerator.spec.ts`, not by `tsc`/`jest`**: the first version skipped the old proportional rescale by setting `transform: "none"` when normalized. `@react-pdf/renderer`'s own stylesheet parser (`@react-pdf/stylesheet`) has a bug where any single-token transform value throws deep inside its internals (see `docs/lessons.md`'s entry for the exact mechanism) - and their custom reconciler doesn't propagate that as a rejection anywhere, so `pdf(...).toBlob()` just hangs forever with zero console/page error. All 3 download-path Playwright tests hung at their timeout; a stashed pre-Proposal-B baseline confirmed they pass cleanly with no other changes. Fixed by using `transform: undefined` (omitting the key) instead of `"none"` - all 4 tests pass afterward, matching baseline timing.

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
- `frontend/tests/PDFGenerator.spec.ts` — mocked-CDN Playwright coverage for
  bug 4 (preview warning, confirm-gated download/cancel, and a real-image
  success-path regression check)

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
