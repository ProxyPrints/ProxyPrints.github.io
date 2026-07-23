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
  a reversible "Hide" control. **Only the editor/self-import surface is
  wired up in this pass** — `SharedDeckViewer.tsx` and any other read-only
  viewer were not touched, so they simply don't synthesize orphan
  CardDocuments at all yet (safe-by-omission: deny-by-default is the
  correct posture there, just not yet built as an explicit opt-in flow).
  Building that opt-in UI is future work, not a regression.
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
  listener's orphan-candidate skip.
- `frontend/src/features/card/Card.tsx` — `OrphanBadge`, the
  bucket-validity-aware `onError` fix, click-to-detail suppression.
- `frontend/src/features/card/DeckbuilderConfirmAffordance.tsx` — the
  consensus-surface gate.
- `frontend/src/features/pdf/pdfImage.ts` — `getOrphanPDFImageURL`, the
  full-resolution PDF-export path.
- `frontend/src/common/types.ts` — the `isOrphan?: boolean` marker on the
  frontend's own `Card`/`CardDocument` type (never present in the
  quicktype-generated `schema_types.ts`).
- Tests: `orphanCard.test.ts`, `processing.test.ts` (bracket-token cases),
  `listenerMiddleware.test.ts`, `ImportXML.test.ts` (front + the b:null
  back-face case), `downloadXML.test.ts` (round-trip), `Card.test.tsx`
  (badge/click-suppression/error-degrade), and the Playwright
  `tests/OrphanRendering.spec.ts` (both reported symptoms, end to end,
  with screenshots).
