# Foreign-order resilience (issue #324)

Owner-ratified direction, 2026-07-22, promoted to high priority 2026-07-23
after two live symptoms: a text-import `[mpc:<id>]` token not registering at
all, and an XML-imported unindexed back face landing in the Invalid Cards
modal as `Back | b:null | <id>`. **Phase 1 (orphan rendering) shipped
2026-07-23** — this doc covers what shipped, what was adapted from the
original spec, and what's still deferred to Phase 2.

## The problem

The editor previously rendered only what the catalog already knows: a
project-member `selectedImage` that doesn't appear in the catalog's own
search results for its query got silently deselected (or, if search results
existed at all for the query, recorded as an "Invalid Card" and replaced
with the first real match) — regardless of whether that identifier was
genuinely garbage or a real, fetchable Google Drive file ID from an order
built against another mpc-autofill-lineage catalog.

## What "orphan" means here

An **orphan** is a `CardDocument` synthesized entirely client-side
(`frontend/src/common/orphanCard.ts`) for a project-member identifier the
catalog has never indexed. It carries `isOrphan: true` and deliberately
never sets `sourceType` — every consumer that must not route it through our
own image-CDN Worker/R2 bucket (`common/image.ts`'s `getBucketImageURL`/
`getWorkerImageURL` both gate on `sourceType === SourceType.GoogleDrive`) or
offer it tag/consensus surfaces checks `isOrphan` (or, for the CDN-routing
case, gets that behaviour for free just by `sourceType` being absent).

## How an identifier becomes an orphan

1. **Text import**: a `[mpc:<id>]` token anywhere after the query text (e.g.
   `1x Kharn [mpc:1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn]`) is parsed by
   `processing.ts`'s `extractDriveIdBracketToken`/`unpackLine` — an
   _addition_ to the pre-existing `query@id` (`SelectedImageSeparator`)
   syntax, not a replacement. Both forms end up in the same
   `ProjectMember.selectedImage` field, so everything below applies
   identically regardless of which syntax supplied it.
2. **XML import**: `ImportXML.tsx`'s `parseXmlImport` already read a
   `<card>`'s raw `<id>` text verbatim before this feature — the parser
   itself needed no change. The reported `b:null` case is
   `parseXmlImport`'s own pre-existing fallback: a front slot with no
   matching `<backs>` entry gets `{ query: { query: null, cardType: Cardback }, selectedImage: <the order's own root-level <cardback> text> }`
   — an entirely legitimate, name-less orphan.
3. Either way, `cardDocumentsSlice.ts`'s `fetchCardDocuments` thunk now
   fetches against the **union** of the pre-existing search-derived
   identifier set (`selectUniqueCardIdentifiers`) and every raw
   `selectedImage` a project member actually references
   (`selectProjectMemberIdentifiers`) — the search-derived set alone would
   never even attempt to resolve an orphan, since by definition it never
   appears in any search result. Anything still unresolved after both the
   local (client-search) and remote (`/2/cards/`) lookups, that also passes
   `orphanCard.ts`'s `isLikelyDriveFileId` allowlist
   (`^[A-Za-z0-9_-]{10,200}$`, the owner's 2026-07-22 security-review
   ruling), gets synthesized into a `CardDocument` and merged into
   `cardDocuments.cardDocuments` — same map real catalog cards live in, so
   every existing selector/consumer (`selectCardDocumentByIdentifier`,
   `Card.tsx`, `downloadXML.ts`, `pdfImage.ts`, …) picks it up automatically.

## The listener fix (the actual root cause)

`listenerMiddleware.ts`'s pre-existing invalid-identifier listener
(triggered on `fetchSearchResults.fulfilled`/`fetchCardbacks.fulfilled`)
unconditionally cleared any `selectedImage` absent from the catalog's
search results for its query — this is what silently dropped both reported
symptoms, independent of anything in the parsers. It now also triggers on
`fetchCardDocuments.fulfilled` (needed because `cardDocuments.cardDocuments`
isn't settled yet on the earlier two triggers) and skips the
clear/Invalid-Cards path when the identifier is either already resolved to
an orphan (`selectCardDocumentByIdentifier(...).isOrphan === true`) or not
yet resolved either way but still looks like a real Drive file ID
(`isLikelyDriveFileId`) — erring towards "wait and see" rather than
prematurely clearing. A genuinely-known-but-currently-filtered/removed
catalog card (defined in `cardDocuments`, `isOrphan` false/undefined) still
falls through to the pre-existing Invalid Cards flow unchanged — this is a
regression-guarded addition, not a loosening of that existing behaviour
(see `listenerMiddleware.test.ts`'s explicit regression-guard case).

## Rendering

- **Image source**: direct from Google
  (`https://lh4.googleusercontent.com/d/<id>`), never through the image-CDN
  Worker/R2 bucket — that cache stays catalog-only (issue's own Phase 1
  bullet). Two size tiers mirror the Worker's own `=h<px>` URL shape exactly
  (`image-cdn/src/service/GoogleDriveService.ts`'s `getLH4Params`/
  `image-cdn/src/types.ts`'s `ImageSizes`): 400px height for the editor
  grid/preview tile, 800px for the (currently unused) "large" tier, and no
  size suffix at all — the original file — for PDF export
  (`pdfImage.ts`'s `getOrphanPDFImageURL`/`getPDFImageBlob`, only ever
  invoked on an actual export action, never speculatively).
- **`referrerpolicy="no-referrer"`** on every orphan `<img>` (owner
  ruling — the fetch itself remaining a signal to the file's owner is an
  accepted residual on this, an author-only, surface).
- **Visually distinct treatment**: a small corner badge
  (`Card.tsx`'s `OrphanBadge`) showing the synthesized document's own
  `sourceName` ("Your file" on the editor/author surface this Phase 1 pass
  covers). **Real-browser-only bug caught during Playwright verification,
  not by Jest**: Bootstrap's `.ratio > *` rule stretches every direct child
  of the aspect-ratio card wrapper to `width:100%; height:100%; top:0; left:0` — the badge needs `width: auto; height: auto;` to opt back out,
  the same defensive pattern the pre-existing `CardIcon`/`MatchIndicatorIcon`
  corner icons already use. jsdom (Jest) never computes layout, so this
  class of bug is invisible to unit tests; a real Playwright screenshot
  caught it as a badge stretched to cover the entire card.
- **No tags/consensus surfaces**: `DeckbuilderConfirmAffordance.tsx` gates
  off for `card?.isOrphan === true`; `Card.tsx` suppresses
  click-to-open-detailed-view for orphans (`canShowDetailedView`) since that
  modal's own surfaces (printing tags, reporting) don't apply to a card the
  catalog has never indexed.
- **"Image unavailable" degrade, not a stuck spinner, on a genuine fetch
  failure**: `useImageSrc`'s `onError` handler was fixed to check whether a
  bucket URL is actually configured (`imageBucketURLValid`) before deciding
  whether to retry via the fallback tier or go straight to `errored` — an
  orphan (no bucket at all) was already loading its one-and-only URL from
  the very first render, just still internally labelled
  `"loading-from-bucket"` (this hook's fixed initial state); without the
  fix, a single failure would relabel to `"loading-from-fallback"` and
  re-render with the _same_ src string, which browsers don't re-fetch,
  leaving the spinner stuck forever. This also fixes the identical latent
  issue for any non-Google-Drive card with no bucket configured (e.g. AWS S3
  sources, or local dev with `NEXT_PUBLIC_IMAGE_BUCKET_URL` unset) — not
  orphan-specific, just the same code path.

## Rendering surfaces & acceptance (2026-07-23 owner review round)

- **Acceptance surface**: the classic `/editor` page is a legacy route held
  behind the route-swap PR #389 — owner ruling, this review round: the
  UNIFIED `/display` page (nav "Editor") is the only acceptance surface for
  frontend rendering work. `OrphanRendering.spec.ts`'s Playwright cases
  (originally verified against `/editor`) were moved to run against
  `/display` instead, screenshotting `test-results/orphan-text-import-desktop.png`/
  `orphan-xml-import-desktop.png`/`orphan-xml-import-backs-desktop.png`/
  `orphan-text-import-narrow-390.png`.
- **The `/display` sheet needed no code change to render the image itself**:
  `PagePreview.tsx` (the unified page's own sheet-cell renderer, a DIFFERENT
  component from `Card.tsx`) reads `cardDocument.mediumThumbnailUrl`/
  `isOrphan` straight off the same shared `cardDocuments` store slice — since
  `synthesizeOrphanCardDocument` already sets both, an orphan's image renders
  correctly there for free, for both fronts (text import) and backs (the XML
  `b:null` case, once the page's own Fronts/Backs toggle is switched — the
  "cardback corner" from the owner's report; see the next bullet for the
  surface that PagePreview.tsx is NOT).
- **Badge gap CLOSED (2026-07-23 follow-up)**: `PagePreview.tsx` previously
  had no `OrphanBadge` equivalent (`Card.tsx`'s corner label) — a
  page-scoped visual gap that also left a parity Playwright test
  (`ImportXML.spec.ts`'s orphan-cardback case, `parity-wave1` branch) red
  with nothing to assert against. Closed by adding a `orphanLabel?: string`
  prop to `PagePreviewSlotContent` (`PagePreview.tsx`) — `undefined` renders
  no badge (every non-orphan slot, and any slot with no resolved `imageUrl`
  yet); set, it renders a `data-testid="orphan-badge"` pill in the slot's
  top-right corner (same background/text-transform/weight as Card.tsx's
  `OrphanBadge`, reimplemented in this component's own mm-unit idiom rather
  than px, since every other PagePreview overlay is sized in mm so it stays
  legible after the outer `transform: scale()` — a raw px badge would nearly
  vanish on a heavily letterboxed phone sheet, the same reasoning already
  written up for this component's screen-only border/radius above). Top-right
  rather than Card.tsx's top-left, clear of the existing bleed badge's
  top-left corner (the two never co-occur in practice — an orphan has no
  `sourceType`, so PDF.tsx's bleed-normalization eligibility check never
  fires for one — but kept visually separable regardless). Wired from both
  callers that already resolve a `CardDocument`: `DisplayPage.tsx` (the
  `/display` sheet, `cardDocument.sourceName` when `cardDocument.isOrphan`)
  and `PDFGenerator.tsx`'s fast preview (`doc.sourceName` when
  `doc.isOrphan`, free since `doc` was already resolved for the bleed
  badge). Same testid as Card.tsx's own badge, by design, so a spec can
  target either surface uniformly. Coverage: `PagePreview.test.tsx`'s new
  "orphan badge" describe block (label shown/omitted/gated on a resolved
  `imageUrl`), and `OrphanRendering.spec.ts`'s badge assertions on both the
  text-import and XML-import (front + "cardback corner" back) cases, plus a
  dedicated 390px-narrow-viewport case.
- **REAL BUG, fixed**: the classic editor's "Common Cardback" panel
  (`CommonCardback.tsx`'s right-panel mount, `/editor` only — `/display` has
  no equivalent persistent tile, only the `CardbackToolbarButton` picker)
  showed "Card not found" after importing an order whose own `<cardback>`
  was an orphan, even though the very same identifier rendered correctly one
  panel over as the imported slot's own per-slot back. Root cause was two
  separate gaps, both now fixed:
  1. `ImportXML.tsx`'s `parseXmlImport` read the file's own root-level
     `<cardback>` into each individual backless front's own per-slot
     fallback, but never fed it back to the caller to also initialise
     `state.project.cardback` (the Common Cardback panel's own selection) —
     so a BRAND NEW project (nothing selected yet) never picked it up at
     all. Fixed by returning the raw `<cardback>` text as `cardback` on
     `ParsedXmlImport`, and having `ImportXML`'s `parseXMLFile` dispatch
     `setSelectedCardback` with it — but ONLY when `state.project.cardback`
     was `null` beforehand (`projectCardback == null`, read from the
     component's own pre-import selector snapshot). That gate is load-
     bearing: an EXISTING non-null project cardback deliberately stays
     untouched by a later import even with "Use XML Cardback" on —
     `ImportXML.spec.ts`'s pre-existing "import an XML and use its
     cardback"/"...use the project cardback" tests assert exactly this, and
     the fix must not (and does not) regress them.
  2. `listenerMiddleware.ts`'s `fetchCardbacks.fulfilled` listener (which
     deselects `state.project.cardback` the moment it's absent from the
     catalog's own indexed cardbacks list) had no orphan-candidate carve-out
     at all, unlike its sibling per-slot invalid-identifier listener above —
     so even after fix 1 initialised an orphan cardback, this listener would
     immediately clear it right back out. Given the same `isOrphan`/
     `isLikelyDriveFileId` carve-out as the per-slot listener, now also
     re-triggered on `fetchCardDocuments.fulfilled` for the same
     not-yet-resolved ordering reason.
  - Coverage: `listenerMiddleware.test.ts`'s new "project cardback listener"
    describe block (both the orphan carve-out and its own regression
    guards), `ImportXML.test.ts`'s new `cardback` field cases, and
    `ImportXML.spec.ts`'s new "brand new project" Playwright case
    (`common-cardback`'s `orphan-badge` visible, no "Card Not Found" text).

## Round-trip (export/re-import)

`downloadXML.ts`'s `createCardElement` already returned `null` (silently
dropping the slot) for any identifier absent from `cardDocuments` — since
orphans are now present there, this is unaffected and Just Works. The
synthesized orphan's `searchq` field (which `<query>` re-export reads)
deliberately carries the _sanitized real stand-in query text_, never the
`"Unindexed card"` display fallback — the fallback name would otherwise
corrupt a re-exported file with fabricated text that was never the user's
actual search query. `cardDocumentsSlice.ts`'s `buildStandInQueryByIdentifier`
harvests each identifier's real stand-in name/cardType from the project
member(s) that reference it before synthesis, specifically so this
round-trip stays faithful.

## Replacement suggestions (already-working infra, not new work)

The owner's later scope addition ("orphan slot retains its XML search
query, offers 'find this card in our catalog'") needed **no new code**: an
orphan's `selectedImage` no longer gets forcibly cleared, but its
`SearchQuery` was never touched either — `CardSlot.tsx`'s existing
`searchResultsForQueryOrDefault`/grid-selector/version-picker machinery
already operates independently of whether the currently-selected image is
an orphan, so a real catalog match (if the query happens to find one) is
already offered exactly as it always was for any slot.

## Deviations from the original issue-body spec

- **Resolution-tier param shape**: the owner's own 2026-07-22 follow-up
  comment loosely specified `=w<px>` (width). Implemented instead using the
  image-CDN Worker's own already-tested `=h<px>` (height) convention and
  `lh4.googleusercontent.com` host (not `lh3`) — exact parity with the
  Worker's `GoogleDriveService.getImageURL`/`ImageSizes` rather than
  introducing a second, unverified size-parameter shape for the same
  visual-size discipline the owner asked for.
- **`[mpc:<id>]` text-import syntax**: not present anywhere in the ratified
  issue body or its comments — designed fresh to match the owner's own
  exact reported repro line, as an _additional_ syntax alongside the
  pre-existing `query@id` form (see "How an identifier becomes an orphan"
  above), rather than the issue's proposed identifier-lookup-miss path
  alone (which only covered XML import).

## Explicitly deferred (not shipped in this pass)

- **Phase 2 (source derivation + suggestion)**: the Drive `files.get`
  parents-walk backend endpoint, the "suggest this drive as a source"
  one-tap flow, and its credential-class verification — entirely
  out of scope for Phase 1, per the issue's own phasing.
- **Per-surface consent ruling** (owner's second security-review round):
  self-import/own saved decks allowed by default; shared decks viewed by
  others deny-by-default behind an explicit per-deck recipient opt-in with
  a reversible "Hide" control. **SHIPPED (editor-polish round, item 11,
  2026-07-24)** — `SharedDeckViewer.tsx` now synthesizes orphan awareness
  for a shared-deck recipient (still NOT a full `synthesizeOrphanCardDocument`
  merge into Redux — this component stays local-state-only, per its own
  module comment — just enough to detect a face whose `selectedImage`
  passes `isLikelyDriveFileId` but wasn't resolved by `APIGetCards`, the
  same "unindexed by this catalog" orphan definition Phase 1 already
  uses): a `useConsentToast` prompt keyed `shared-deck-orphans:${shareId}`
  (per-DECK, not per-identifier or global — a second shared deck asks
  independently even in the same session), deny-by-default (decline or
  dismiss both leave every orphan face behind a `🔒 External image hidden` placeholder, and NOTHING is fetched — not even the direct-Google
  URL is built — until the recipient opts in), and a persistent "N
  external images hidden — Review"/"Hide" banner for the reversibility
  the base `useConsentToast` `Promise<boolean>` contract doesn't natively
  offer (the banner's own local `imagesRevealed` boolean is independent
  of the toast's one-shot stored decision — flipping it back and forth
  never re-prompts or touches `sessionStorage`). The revealed image uses
  `getOrphanSmallImageURL` directly (orphanCard.ts) — still never routed
  through the image-CDN Worker/R2 bucket, same posture as the editor's own
  orphan rendering. Test coverage: `SharedDeckViewer.test.tsx` (jest/RTL,
  not Playwright — this is a plain local-state component with no
  `PagePreview` sheet/rail chrome to drive through a page-load E2E flow).
  **Still not built**: any OTHER read-only viewer this catalog might grow
  later inherits nothing automatically — this is `SharedDeckViewer.tsx`
  specifically, not a shared hook/component other future recipient
  surfaces can mount directly (a real gap if a second such surface is
  ever added, flagged here rather than silently assumed-covered).
- **Bleed normalization for orphans**: `PDF.tsx`'s
  `isBleedNormalizationEligible` still gates on `sourceType === GoogleDrive || sourceType === LocalFile`, which an orphan (no
  `sourceType`) never matches — an orphan's PDF embed uses the plain
  scale-transform path, not bleed-measured/corrected geometry. Satisfies
  the acceptance bar ("an exported PDF containing an orphan embeds the
  high-res image") without extending bleed-measurement to a source this
  catalog has no calibration data for.
- **"Download Images" bulk raw-file export** (`ExportImages.tsx`) still
  filters to `sourceType === SourceType.GoogleDrive` only — orphans are
  silently excluded from that surface. Not mentioned in the issue's
  acceptance criteria (which is PDF-export-specific); flagged here as a
  plausible related surface for a future pass, not built.
- **Policy/Terms note** (owner's "non-blocking" queue item: third-party
  image display + takedown path) — not written in this pass.

## Key files

- `frontend/src/common/orphanCard.ts` — the allowlist regex, direct-Google
  URL builder (small/large/full tiers), stand-in-name sanitizer, and
  `synthesizeOrphanCardDocument`/`buildOrphanCardDocuments`.
- `frontend/src/common/processing.ts` — `extractDriveIdBracketToken`,
  wired into `unpackLine`.
- `frontend/src/store/slices/cardDocumentsSlice.ts` — the broadened
  identifier union and orphan synthesis in `fetchCardDocuments`.
- `frontend/src/store/listenerMiddleware.ts` — the invalid-identifier
  listener's orphan-candidate skip, and (2026-07-23 follow-up) the SEPARATE
  `fetchCardbacks.fulfilled` project-cardback listener's own matching
  carve-out.
- `frontend/src/features/card/Card.tsx` — `OrphanBadge`, the
  bucket-validity-aware `onError` fix, click-to-detail suppression.
- `frontend/src/features/card/DeckbuilderConfirmAffordance.tsx` — the
  consensus-surface gate.
- `frontend/src/features/pdf/pdfImage.ts` — `getOrphanPDFImageURL`, the
  full-resolution PDF-export path.
- `frontend/src/features/pdf/PagePreview.tsx` — (2026-07-23 follow-up)
  `PagePreviewSlotContent`'s `orphanLabel` prop and its `orphan-badge`
  render, the `/display` sheet's own port of Card.tsx's `OrphanBadge`.
- `frontend/src/features/display/DisplayPage.tsx` — wires `orphanLabel`
  from `cardDocument.isOrphan`/`sourceName` into each sheet slot's content.
- `frontend/src/features/pdf/PDFGenerator.tsx` — wires the same `orphanLabel`
  into its fast-preview slots (`fastPreviewSlots`), alongside the existing
  bleed badge.
- `frontend/src/common/types.ts` — the `isOrphan?: boolean` marker on the
  frontend's own `Card`/`CardDocument` type (never present in the
  quicktype-generated `schema_types.ts`).
- `frontend/src/features/import/ImportXML.tsx` — (2026-07-23 follow-up)
  `ParsedXmlImport`'s new `cardback` field and `parseXMLFile`'s gated
  `setSelectedCardback` dispatch, fixing the Common Cardback panel bug (see
  "Rendering surfaces & acceptance" above).
- `frontend/src/features/savedDecks/SharedDeckViewer.tsx` — (editor-polish
  round, item 11, 2026-07-24) the shared-deck recipient's own orphan
  detection + consent gate (`isOrphanFace`, the `useConsentToast` mount,
  the `HiddenOrphanBadge`/`ExtBanner` presentation) — see "Per-surface
  consent ruling" above for the full behaviour.
- `frontend/src/features/savedDecks/SharedDeckPage.tsx` — threads the
  route's own `shareId` query param into `SharedDeckViewer`'s `shareId`
  prop (the per-deck consent-key scope).
- Tests: `orphanCard.test.ts`, `processing.test.ts` (bracket-token cases),
  `listenerMiddleware.test.ts` (both the per-slot AND, as of 2026-07-23, the
  project-cardback listener), `ImportXML.test.ts` (front + the b:null
  back-face case, plus the new `cardback` field cases), `downloadXML.test.ts`
  (round-trip), `Card.test.tsx` (badge/click-suppression/error-degrade),
  `ImportXML.spec.ts`'s "brand new project" Playwright case (the Common
  Cardback fix), `PagePreview.test.tsx`'s "orphan badge" describe block
  (2026-07-23 follow-up), and the Playwright `tests/OrphanRendering.spec.ts`
  (both reported symptoms, end to end, on the unified `/display` page as of
  the 2026-07-23 acceptance-surface correction, with screenshots, plus the
  sheet's own `orphan-badge` assertions and a dedicated narrow-viewport case
  added in the same follow-up), and (editor-polish round, item 11)
  `SharedDeckViewer.test.tsx` (jest/RTL — consent prompt, decline-hides,
  accept-reveals, the reversible banner toggle, and the per-deck-id
  independence case).
