# PDF generator

Upstream PR #367 (DriveThruCards PDF export). Three real bugs were found
and fixed here, verified deployed and working end-to-end (Playwright, real
headed Chromium + Firefox, real backend + image-cdn).

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

## Thumbnail routing (bucket → worker fallback)

See [[image-cdn.md]]'s "What it does" section — `pdfImage.ts` tries the R2
bucket first via HEAD request for small/large tiers, falls back to the
Worker on a miss. Full-resolution always goes through the Worker, matching
upstream.

## "HEAD request fails" console noise — investigated, not a bug

A cross-session report flagged failed `HEAD` requests to
`img.proxyprints.ca/<id>-small-google_drive` when opening the PDF tab live.
Reproduced directly (headed Chromium Playwright, live site): confirmed
real, but it's `getThumbnailURL` in `pdfImage.ts` working exactly as
designed — a `HEAD` on a cache-miss key fails at the network level
(`net::ERR_FAILED`, not a clean 404 — an R2 custom-domain quirk where
HEAD-on-missing-object doesn't return a normal HTTP response), which the
existing `try { ... } catch { /* fall through to worker */ }` already
absorbs. The very next request is a successful `GET` to the Worker (200),
and the card renders correctly. Cosmetic console noise only — don't spend
time "fixing" it.

## Key files

- `frontend/src/features/pdf/PDFGenerator.tsx`,
  `frontend/src/features/pdf/pdfImage.ts`
- `frontend/src/features/pdf/PDFCanvasPreview.tsx`
- `frontend/scripts/copy-pdf-worker.js`
- `frontend/src/components/PDFGeneratorModal.tsx`,
  `FinishedMyProject.tsx`, `ProjectEditor.tsx`

## Status

All three original bugs verified fixed and deployed. Upstream PR #463 (lazy
WASM load fix) is open; #464 (canvas preview) and #466 (thumbnail routing)
were closed after the maintainer said the existing upstream behavior is
deliberate design for their codebase, not a bug — see
[[../infrastructure.md]] for PR status details. Don't "fix" this fork's PDF
tab implementation to match upstream's on those two points; both are
correct for their own codebase.

See also [[google-drive-connect.md]] for the separate "Save PDF directly to
Google Drive" upload feature on this same tab.
