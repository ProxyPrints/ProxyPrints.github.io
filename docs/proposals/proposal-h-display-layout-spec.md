# /display responsive layout spec — issues #266 / #267 / #268

Design target for the unified display page (`frontend/src/features/display/DisplayPage.tsx`,
route `frontend/src/pages/display.tsx`). Companion mockup: `display-mockup.html` (same
directory; open standalone via file://, use its top demo strip to force any breakpoint's
view at any window width). All primitives are react-bootstrap 2.10.10 / Bootstrap 5.3.8
(confirmed installed, including responsive-Offcanvas). No new dependencies.

Issue mapping (explicit):

- **#266** (mobile fit-to-width sheet + bottom-sheet drawer, tablet off-canvas) = §2
  (sheet scaling), §4 (rail placement per breakpoint), §6 rows R1–R6.
- **#267** (settings banner / deck input evolves into top search bar) = §3 (action
  bar + search-bar states) and §4.2 (the settings surface — owner decision D2 below
  moved it from a top banner into the RIGHT rail; on phone/tablet it remains
  reachable from a top-bar gear control, preserving the issue's intent), §6 rows
  T1–T5, I1.
- **#268** (landing cohesion with saved decks) = §5, §6 rows S1–S3.
- Owner decisions D4–D6 (grid/margins/bleed defaults, §6 row M1) and D8 (color
  calibration, rows C1–C2) are NEW scope beyond these three issues — file as their
  own issues at implementation time.

## 0. Owner decisions log (2026-07-21 review round)

- **D1 — Landscape is the default PDF orientation at ALL breakpoints.** Even though
  portrait renders larger on phones, landscape stays the default; the fit-to-width
  rule (§2) therefore letterboxes the landscape page on phones (full page visible,
  smaller cards) rather than switching orientation per device. Mechanics verified:
  `computeLayout()` (`frontend/src/features/pdf/layout.ts`) with `DisplayPage.tsx`'s
  existing portrait-swap; cards are never rotated by the layout engine. (At the OLD
  defaults — 5mm margins, 3.048mm bleed — Letter landscape gave only 3×2; D4–D6
  below change those defaults.)
- **D2 — Three regions, split roles** (owner framing, verbatim: "rail on left,
  center where our PDF preview is, then the right rail where settings are. might be
  3 rails not 2 depending how you think about it"; earlier: "the left rail to be
  the old card details page and the old art selector page merged… united on mobile
  and desktop. the right rail should be editing settings and preparing print.
  repurposing existing elements as often as possible"). LEFT rail = card surface
  (§4.1); CENTER = the sheet region (the PDF preview, §2); RIGHT rail =
  project/print surface (§4.2). This supersedes the earlier top-settings-banner
  layout for #267 item 1; the "banner near the top" ask survives as the gear
  control in the top action bar opening the right rail below desktop width.
- **D3 — Left-rail de-clutter hierarchy** (verbatim: "information not related to art
  selection or supporting the artist should be hidden or near the bottom of the new
  unified details page. it was previously cluttered and used a lot of space").
  TOP/always-visible = art selection + artist support; everything else the old
  details modal showed is demoted to collapsed-by-default sections near the bottom —
  collapsed, not deleted, since moderation/tagging surfaces must stay reachable.
  Full promoted/demoted assignment in §4.1.
- **D4 — 4×2 landscape grid (8/page)** (verbatim: "4×2 will fit certainly. might
  have an upperbound on the amount of bleed available but it will fit"). Correct:
  the column axis binds via `fitCardsInDimension`'s strict
  `4·(63+2b) + 0.1 < 279.4 − (marginL+marginR)`; the row axis never binds
  (b ≤ 8.45mm even at 3mm margins). The bleed upper bound depends on the D5 margin
  profile — table under D6 below.
- **D5 — Near-zero default margins, calibrated to the Epson ET-8500** (verbatim:
  "our PDFs should have close to no margins. (calibrate based on an Epson ET-8500
  rear/top feeder forced margins, should be a lead/right edge only thing)").
  Researched from Epson's own ET-8500/ET-8550 User's Guide (CPD-59879), "Printable
  Area Specifications"
  (files.support.epson.com/docid/cpd5/cpd59879/…/spex_printable_area_et8500_8550.html):
  bordered printing minimum margins **3mm (0.12in) on all four edges**; **rear
  paper feed slot adds a 20mm (0.8in) unprintable zone at the trailing (bottom)
  edge**; **borderless (0mm) is supported up to Letter/Legal** (spec sheet
  CPD-59931R2). The owner's "lead/right edge only" intuition maps to reality:
  Letter feeds portrait (215.9mm leading edge), so in the landscape layout the
  20mm trailing zone lands on one landscape SIDE edge — margins in landscape view
  become 3mm lead-side + 20mm trail-side + 3mm top/bottom when using the rear
  straight-pass. New defaults replace the current hardcoded 5mm-all-sides
  (`DisplayPage.tsx`'s `margins` useMemo — NOT `layout.ts`, which takes margins as
  arguments and has no defaults of its own). Margins are currently NOT
  user-editable anywhere on /display (the classic PDF tab's
  `SpacingAndMarginsSettings` is; this page hardcodes them) — the right rail's
  Page Setup section gains a margin-profile control (Borderless / Bordered 3mm /
  Rear-feed +20mm trail), which is also where user override lives.
- **D6 — Default bleed = MPC standard 3.175mm (1/8in)**, replacing 3.048mm.
  Verified in-repo: `STANDARD_BLEED_MARGIN_MM = 3.175` in
  `frontend/src/features/pdf/bleedNormalize.ts` (line 145; its comments cite the
  1/8in-at-63×88mm-trim convention and the backend's ~97.5% bleed-prevalence
  finding across DB images), vs `constants.ts`'s `BleedEdgeMM = 3.048`
  (0.12in — an Epson-margin-shaped constant, inherited from upstream).
  **Fit check, 4×2 Letter landscape at exactly b=3.175**: needs
  4·69.35 + 0.1 = **277.5mm** of printable width. Results per D5 profile:

  | Margin profile (landscape L/R)     | Printable width | 4×2 at b=3.175?                     | Max bleed for 4×2 |
  | ---------------------------------- | --------------- | ----------------------------------- | ----------------- |
  | Borderless (0 / 0)                 | 279.4mm         | **YES** (1.9mm slack, ≤0.95mm/side) | 3.412mm           |
  | Bordered minimum (3 / 3)           | 273.4mm         | no                                  | 2.662mm           |
  | Rear feed slot (3 lead / 20 trail) | 256.4mm         | no (fits at b ≤ 0.537)              | 0.537mm           |
  | (old default, 5 / 5)               | 269.4mm         | no                                  | 2.162mm           |

  So the binding constraint: **full MPC bleed + 4×2 requires borderless mode**
  (which the ET-8500 supports for Letter); any bordered profile caps bleed below
  3.175 — most severely the rear straight-pass (0.54mm). Default = borderless +
  3.175mm bleed; the Page Setup margin-profile control (D5) surfaces the trade-off.

- **D7 — Screen-only sheet presentation**: minimal wasted space between pages,
  slightly rounded page corners, pages drawn as OUTLINE ONLY (a subtle border
  frame around the card grid, no solid white page fill). Applies to the /display
  render only — the real PDF is untouched. Kills the letterbox-white look D1 would
  otherwise produce on phones.
- **D8 — Deck-wide color calibration in the PDF output** (relayed as the round's
  final addition; rationale recorded as relayed: "the ET-8500's Linux driver only
  exposes brightness/saturation/contrast, so color-cast calibration must live in
  our PDF output itself" — owner wrote "CY…etc." for the channel controls).
  Per-channel color shifts (cyan/magenta/yellow) plus brightness/saturation/
  contrast sliders, applied to EVERY card at PDF image-render time and previewed
  on the center sheet. Location: a "Color Calibration" collapsed `AutofillCollapse`
  group in the right rail's settings region (§4.2), sliders + a Reset button.
  Preview behavior: a CSS `filter` approximation on the on-screen sheet cards is
  acceptable — `brightness()`/`saturate()`/`contrast()` map 1:1, but **CSS filters
  cannot express pure per-channel CMY math** (only hue-rotate/sepia composites
  approximate it), so the preview is explicitly approximate; the exact transform
  runs as a canvas color-matrix in the PDF image pipeline
  (`frontend/src/features/pdf/pdfImage.ts` / `pdf.worker.ts`, where card bitmaps
  are already decoded for render). Persistence: per saved deck, following the
  existing `finishSettingsSlice` precedent (`deckPayload.ts` already serializes
  finish settings into the deck payload and `MyDecksPage`'s `performLoad`
  dispatches `loadFinishSettings` — a `colorCalibrationSlice` rides the same
  path). Outside issues #266–268's scope — file as its own issue at
  implementation time.

Breakpoint tiers (Bootstrap stock boundaries — four tiers now, because two inline
rails don't fit below xl):

| Tier    | Width        | Bootstrap | Left rail (card)        | Right rail (print/settings) |
| ------- | ------------ | --------- | ----------------------- | --------------------------- |
| Phone   | `<768px`     | xs+sm     | Bottom sheet (card tap) | End drawer (gear)           |
| Tablet  | `768–991px`  | md        | Start drawer (card tap) | End drawer (gear)           |
| Laptop  | `992–1199px` | lg        | Inline left, sticky     | End drawer (gear)           |
| Desktop | `≥1200px`    | xl        | Inline left, sticky     | Inline right, sticky        |

Context facts the design is built on (verified in code, 2026-07-21):

- The page lives inside `ProjectContainer` (`frontend/src/features/ui/Layout.tsx`):
  `position: fixed` scroll container, `overflow-x: hidden`, content capped at
  `ContentMaxWidth` = 1200px. That `overflow-x: hidden` + the fixed
  `SHEET_MAX_WIDTH_PX = 960` render width is exactly the owner's mobile symptom
  (only the middle cards visible, no sideways scroll). Sticky offsets are relative
  to this container (`top: 0`), so the wrong `NavbarHeight` constant (issue #250) is
  never involved.
- `PagePreview.tsx` scales to any width (`scale = maxWidthPx / (pageWidthMM * CSS_PX_PER_MM)`) — fit-to-width needs zero `PagePreview` changes.
- One rendered instance per rail (hard precedent, `DisplayPage.tsx` module comment:
  no `d-none` duplicate renders — testids/screen readers). `Offcanvas responsive={bp}` renders one node: inline static at ≥bp, drawer below.
- react-bootstrap's Offcanvas dialog renders through a portal, so its
  `z-index: 1045` escapes ancestor stacking contexts. The mockup (hand-rolled CSS)
  demonstrated the trap that portal avoids: a `position: relative; z-index: 0`
  parent traps a non-portaled drawer under the sticky action bar. Rule stands:
  scope the relative/z-0 pair (docs/lessons.md sticky fix) to tiers where the rail
  is inline.

## 1. Region inventory (all breakpoints)

| Element                                      | Desktop ≥1200      | Laptop 992–1199    | Tablet 768–991     | Phone <768             |
| -------------------------------------------- | ------------------ | ------------------ | ------------------ | ---------------------- |
| Sheet indicator ("Sheet N of M")             | Action bar         | Action bar         | Action bar         | Action bar             |
| `SavedDeckPanel` (deck name + Save)          | Action bar         | Action bar         | Action bar         | Action bar (truncated) |
| Add-cards search bar (#267, populated state) | Action bar, grows  | Action bar, grows  | Action bar, grows  | Full-width 2nd row     |
| Gear ("Print & Settings") button             | hidden             | Action bar (right) | Action bar (right) | Action bar (right)     |
| LEFT rail — card surface (§4.1)              | Inline left 380px  | Inline left 380px  | Start drawer 380px | Bottom sheet 72vh      |
| Sheet stack (landscape, fit-to-width)        | Center, fills      | Center, fills      | Full width         | Full width, letterbox  |
| RIGHT rail — settings + prepare print (§4.2) | Inline right 300px | End drawer 320px   | End drawer 320px   | End drawer (near-full) |
| Export progress bar                          | Right-rail footer  | Right-rail footer  | Right-rail footer  | Right-rail footer      |
| Landing (empty project)                      | §5                 | §5                 | §5                 | §5                     |

The old single toolbar's settings controls (Fronts/Backs, paper, bleed, guides,
`SearchSettings`, `CardbackToolbarButton`) and the export cluster
(`DisplayExportMenu`, Save-to-Drive, Generate PDF) ALL move into the right rail —
the action bar keeps only identity + add-cards + the gear.

## 2. Center region: sheet scaling + presentation (#266 item 1; D1, D4–D7)

**Rule: rendered sheet width = `min(960, sheetRegionClientWidth)` px, always; the
page is landscape (D1), so on phones this letterboxes** — a 390px viewport shows the
full 279.4×215.9mm Letter page at ~366px wide / ~283px tall. No horizontal overflow
at any width; pinch-zoom deferred (issue text: optional later). Each page renders
4×2 (D4, at the D5/D6 borderless + 3.175mm defaults).

Implementation:

- `DisplayPage.tsx`: `ResizeObserver` on the sheet-region div →
  `sheetRenderWidthPx = Math.min(SHEET_MAX_WIDTH_PX, containerWidth)`, quantized
  (~8px) to avoid re-render jitter; passed as `PagePreview.maxWidthPx`.
- `sheetPixelHeightPx` (the `RenderIfVisible` `defaultHeight`/`visibleOffset`
  estimate) derives from the same measured width — virtualization placeholders stay
  exact.
- Landscape mechanics already exist: `DisplayPage.tsx` swaps
  `getPageSizeMM`'s portrait width/height (its own "Landscape:" comment) — no change.
- Defaults change (D5/D6): `DisplayPage.tsx`'s `margins` useMemo 5mm-all →
  borderless profile (0mm, with the Page Setup margin-profile control per D5), and
  `DEFAULT_SHEET_SETTINGS.bleedEdgeMM` → `STANDARD_BLEED_MARGIN_MM` (3.175,
  imported from `bleedNormalize.ts` rather than a new literal). `layout.ts`
  untouched — it takes margins/bleed as arguments.
- Screen presentation (D7): `PagePreview.tsx` gains a screen-presentation variant
  (prop or wrapper class): no solid page fill, subtle outline frame, slightly
  rounded corners; `DisplayPage`'s inter-sheet spacing tightens (the current
  `mb-4` + bordered wrapper shrinks to minimal gap). PDF output untouched. (This
  retires the earlier "PagePreview: no change" claim — the change is presentation-
  only, its mm-accurate `transform: scale()` layout machinery is untouched.)

## 3. Action bar (#267)

One sticky band (md+; static on phone — docs/lessons.md's no-sticky-below-md lesson):
sheet indicator · `SavedDeckPanel` · add-cards search bar · gear. `d-flex flex-wrap align-items-center gap-2`, `bg-body`, `z-index` at Bootstrap's sticky tier (1020 —
under the 1045 offcanvas). Export buttons are NOT here (D2 moved them to the right
rail's footer).

Search-bar states (#267 item 2 + proposal H open decision 8):

- **Empty project**: no bar — the landing renders instead (§5); its `ImportText`
  textarea is the "centered landing input".
- **Populated**: compact single-line input — a `variant?: "block" | "inline"` prop
  added to the shared `ImportText`
  (`frontend/src/features/import/ImportText.tsx`; default `"block"` keeps the
  editor's `AddCardsPanel` byte-for-byte). Enter runs the same
  `convertLinesIntoSlotProjectMembers`/`addMembers` pipeline. Beside it, the
  editor's existing `Import.tsx` dropdown (`*Button` modal variants) — closing the
  add-cards-to-non-empty-project parity gap with zero new UI.

## 4. The two rails (D2)

Both rails follow the same primitive pattern: ONE node each, `Offcanvas responsive={bp}` — left rail `responsive="lg"` (inline ≥992), right rail
`responsive="xl"` (inline ≥1200) — with `placement` driven by a `matchMedia` hook
(left: `"bottom"` on phone, `"start"` on tablet; right: `"end"` below xl). Inline
styling (width / sticky / own `overflow-y: auto` / border) attaches via a wrapper
class scoped to the inline tiers. Opening either drawer closes the other (only one
overlay at a time). Sticky top offset = action-bar height via CSS var, not a
constant (issue #250 lesson).

### 4.1 LEFT rail — card surface (merged details + art selector, united all widths)

Merged sources (all existing, repurposed — never forked):

- The **art selector**: `SelectVersionResults.tsx` + `GridSelectorFilters.tsx` +
  `useGridSelectorSearch.ts` (the GridSelector family) — already mounted inline in
  today's rail as `ChooseImageSection` (`DisplayPage.tsx`).
- The **old card-details page**: `CardDetailedViewModal.tsx`
  (`frontend/src/features/cardDetailedView/`) — the /editor click-a-card modal:
  hi-res preview, `AutofillTable` metadata (source, DPI, size, date, language),
  `ClickToCopy` identifier, `SetIcon`, `ArtistSupportLink`,
  `AttributeVotingPanel`, `PrintingTagPicker`, `AddCardToFavorites`,
  `AddCardToProjectForm`, `ReportCardPanel`, download-image button. Its body gets
  extracted into a `CardDetailedViewBody` component so the modal (editor,
  unchanged) and this rail (new caller) both mount it — repurpose, not fork.

Content hierarchy (D3 — de-clutter mandate; the old details page "was previously
cluttered and used a lot of space"):

**PROMOTED — top, always visible, no disclosure:**

1. Status header (exists today): slot + face, card name,
   `RequestedPrintingBadge`, `DeckbuilderConfirmAffordance`.
2. **Select Version** — the art selection surface, open by default
   (`SelectVersionResults` + filters), directly under the header.
3. **Artist support** — artist name + `ArtistSupportLink`
   (`frontend/src/components/ArtistSupportLink.tsx`), promoted to an always-visible
   line (today's collapsed `ArtistSection.tsx` is absorbed by this line and
   retired as a separate accordion section).

**DEMOTED — near the bottom, collapsed-by-default `AutofillCollapse` sections
(collapsed, not deleted — moderation/tagging must stay reachable):**

4. Card Details — the extracted `CardDetailedViewBody` metadata block:
   `AutofillTable` rows (source, DPI/size, date, language), `ClickToCopy`
   identifier, `SetIcon`, download-image (`useDoImageDownload`),
   `AddCardToFavorites`. (`AddCardToProjectForm` is dropped from this rail's mount
   — the slot is already in the project; the modal keeps it.)
5. Attributes — `AttributesSection.tsx` (tap/vote via the shared `useTagVoting`
   path of `AttributeVotingPanel`).
6. Printing Tags — `PrintingTagPicker` (+ printing-consensus display), previously
   inside the modal body.
7. Print Options — `PrintOptionsSection.tsx` (per-card bleed override).
8. Slot Actions — `SlotActionsSection.tsx`.
9. Report — `ReportCardPanel`, bottom-most.

Per-breakpoint (identical composition everywhere — "united on mobile and desktop"):
inline sticky 380px column at ≥992; `placement="start"` drawer on tablet (card side
= left, matching its inline home; a "Card details" edge handle keeps it
discoverable with nothing selected); `placement="bottom"` 72vh sheet on phone
(rounded top + drag handle; CSS override of Bootstrap's ~33vh default). Opens on
slot tap below lg (fixes "tapping a card shows nothing"); closing does not clear
`selectedSlotRef`. The `key`-remount-per-slot on `<Rail>` stays exactly as-is.

### 4.2 RIGHT rail — editing settings + preparing print

All existing components, relocated (sources named):

- **Page Setup** section (open): paper `Form.Select`, bleed `Form.Control`
  (default 3.175 per D6), guides `Form.Check` — today's `DisplayPage.tsx` toolbar
  controls (the page-local subset of `PDFGenerator.tsx`'s
  `PageSizeSettings`/`EdgeSettings`/`CutLinesSettings`) — plus the NEW D5
  margin-profile `Form.Select` (Borderless / Bordered 3mm / Rear-feed +20mm
  trail), the only genuinely new control in this section.
- **Color Calibration** section (collapsed, D8): C/M/Y shift +
  brightness/saturation/contrast sliders + Reset — new UI over a new
  `colorCalibrationSlice`; preview via CSS filter approximation, exact canvas
  color-matrix at PDF render (see D8 for the honesty note on the approximation).
- **View** section: Fronts/Backs toggle (`toggleFaces`/`selectFrontsVisible`).
- **Cardback** section: `CardbackToolbarButton` (`CommonCardback.tsx`), modal
  unchanged.
- **Search Settings** section: `SearchSettings.tsx` trigger, modal unchanged.
- **Prepare Print footer** — pinned, always visible at the rail's bottom (flex
  column: body scrolls, footer doesn't): `DisplayExportMenu`, Save-to-Drive,
  Generate PDF (`useDownloadPDF`/`useSaveToDrivePDF`, unchanged), plus the export
  `ProgressBar` relocating here from the page top.

Section chrome is `AutofillCollapse` (same component the left rail and classic PDF
panel already use). Per-breakpoint: inline sticky 300px right column at ≥1200;
`placement="end"` drawer opened by the action-bar gear below. Laptop (992–1199)
deliberately keeps the right rail as a drawer — 380 + 300 + a legible sheet does
not fit under 1200px.

## 5. Landing state: import + saved decks (#268)

Unchanged from the prior draft. When `isProjectEmpty`, `DeckInputLanding` becomes a
three-surface composition: a saved-decks panel (new
`SavedDecksLandingPanel.tsx` composing `useGetSavedDecksQuery` + an exported
`DeckRow` (currently private in `MyDecksPage.tsx`, gains an `openLabel` prop) + a
new `useLoadSavedDeck({ navigateTo? })` hook extracted from `MyDecksPage`'s
`performLoad`/`openInEditor`/`LoadSafetyModal`/`UnlockModal` orchestration —
`MyDecksPage` passes `navigateTo: "/editor"`, the landing omits it and re-renders
in place), beside today's `ImportText` paste column and URL/XML/CSV `Accordion`.
Grid: `Col lg={4}` decks / `Col lg={8}` import at ≥992; stacked below, saved decks
first on phone. Renders nothing for anonymous/zero-deck sessions.

## 6. Concrete change inventory (per file)

Rails + scaling (#266, D1–D3):

- **R1** `DisplayPage.tsx` — sheet-region `ResizeObserver` → `sheetRenderWidthPx`
  feeding `PagePreview.maxWidthPx` + `sheetPixelHeightPx` (§2).
- **R2** `DisplayPage.tsx` — left rail: replace `RailWrapper` with
  `Offcanvas responsive="lg"`, `placement` from `useViewportTier()` (`matchMedia`),
  `leftOpen` state, slot tap opens below lg; scope the body wrapper's
  `position: relative; z-index: 0` to inline tiers only (portal note, §context).
- **R3** `DisplayPage.tsx` + `frontend/src/features/cardDetailedView/CardDetailedViewModal.tsx`
  — extract `CardDetailedViewBody`; recompose the rail per §4.1's promoted/demoted
  order; retire `ArtistSection` as a section (absorbed into the promoted artist
  line); add Printing Tags + Report demoted sections.
- **R4** `DisplayPage.tsx` — right rail: new node (`Offcanvas responsive="xl"`,
  `placement="end"`), sections per §4.2, pinned Prepare Print footer; gear button
  in the action bar; export progress bar moves into the footer region.
- **R5** page CSS — bottom-sheet override (72vh, rounded top, drag handle), tablet
  "Card details" start-edge handle, inline-tier wrapper classes (380px/300px,
  sticky, own scroll).
- **R6** `frontend/tests/DisplayPage.spec.ts` (+ scroll bench guard) — viewport
  cases: 390px letterboxed full sheet visible; card tap opens bottom sheet; gear
  opens end drawer; 1100px left rail inline + right drawer; 1280px both inline;
  unique testids (one instance per rail).
- **R7** `frontend/src/features/pdf/PagePreview.tsx` — D7 screen-presentation
  variant (no page fill, outline frame, rounded corners; prop or wrapper class,
  PDF untouched) + `DisplayPage.tsx` inter-sheet spacing tightened.

Print defaults + calibration (D4–D6, D8):

- **M1** `DisplayPage.tsx` — margins memo → D5 borderless default +
  margin-profile state feeding both `computeLayout` and `exportPdfProps`'
  `pageMargin*MM`; bleed default → `STANDARD_BLEED_MARGIN_MM` import (D6); the
  Page Setup profile control clamps the bleed input's max per profile (D6 table).
- **C1** new `colorCalibrationSlice` + the right rail's Color Calibration section
  (D8); persistence into the saved-deck payload following the
  `finishSettingsSlice` precedent in `deckPayload.ts`/`MyDecksPage.performLoad`.
- **C2** `frontend/src/features/pdf/pdfImage.ts` / `pdf.worker.ts` — canvas
  color-matrix application of the calibration at image-render; CSS `filter`
  approximation applied to `PagePreview` slot images for live preview.

Action bar / search (#267):

- **T1** `DisplayPage.tsx` — toolbar reduced to the §3 action bar (settings +
  export controls move to R4).
- **T2** `DisplayPage.tsx` — sticky-at-md+ wrapper for the action bar.
- **T3** `frontend/src/features/import/ImportText.tsx` — `variant` prop (shared
  family, default unchanged).
- **T4** `DisplayPage.tsx` — mount inline `ImportText` + existing `Import.tsx`
  dropdown when `!isProjectEmpty`.
- **T5** phone condensation (truncated deck name; full-width search row).
- **I1** tests — banner-gear/right-drawer + inline-add cases.

Landing (#268):

- **S1** `MyDecksPage.tsx` — export `DeckRow` (+ `openLabel`); extract
  `useLoadSavedDeck` (new `useLoadSavedDeck.ts`).
- **S2** new `SavedDecksLandingPanel.tsx` (§5).
- **S3** `DisplayPage.tsx` `DeckInputLanding` — §5 grid, mounting S2.

## 7. Conflicts / tensions found (honest)

1. **D6's full MPC bleed vs. D5's hardware margin profiles**: 4×2 at exactly
   3.175mm bleed fits ONLY borderless (D6 table) — every bordered ET-8500 profile
   caps bleed below the MPC standard, the rear straight-pass (the owner's named
   calibration target) most severely at 0.537mm. The spec defaults to borderless
   to honor both D4 and D6 simultaneously, but a user who switches to the
   rear-feed profile must accept near-zero bleed or 3 columns — the Page Setup
   control has to make that trade-off visible, not silent. (Also note: Epson's
   borderless mode is designed to overspray/scale slightly — dimensional accuracy
   of 63×88 cards under borderless needs a print-test before D5/D6 defaults are
   called done.)
2. **D2 vs. #267's literal "banner near the top"**: settings are now a right rail,
   not a top banner. Treated as the owner refining their own ask (D2 is newer and
   verbatim); the gear in the top bar preserves "settings reachable from the top"
   on small screens. The implementing PR should note this on issue #267.
3. **`ContentMaxWidth` 1200px cap** (`Layout.tsx`): two inline rails (380+300)
   leave only ~520px of sheet inside the cap — cramped. The spec handles it by
   gating the inline right rail to ≥1200 and keeping it a drawer at laptop, but if
   /display may widen its container (a `ProjectContainer` prop), desktop gains
   real sheet width. Owner decision; spec default keeps the cap.
4. **Proposal H §3's "no fixed positioning below md" vs. bottom sheet**:
   consciously overridden by #266's owner-driven bottom-sheet ask; Bootstrap's own
   Offcanvas (portaled, z-1045) is the app's existing phone pattern (Navbar's
   BackendConfig/DownloadManager). The hand-rolled mockup surfaced the stacking
   trap the portal avoids — recorded in §context and R2.
5. **`CardDetailedViewBody` extraction is the largest repurpose refactor**:
   `CardDetailedViewModal.tsx` (244 lines) interleaves modal chrome with body
   content; the extraction must keep the editor modal pixel-identical while
   letting the rail mount body regions in D3's promoted/demoted order — the body
   component needs region-level composability (e.g. exported sub-blocks or a
   `sections` prop), not just one blob, or the rail can't reorder without forking.
6. **`bootstrap` floor**: `package.json` declares `^5.2.3` but the design needs the
   resolved 5.3.x CSS (responsive offcanvas classes) — pin `^5.3.0` in the
   implementing PR.
7. **Two overlays, one screen**: left (card) and right (settings) drawers must
   never stack — the spec mandates opening one closes the other below their inline
   tiers; `DisplayPage` owns both `show` states so this is a local invariant.

## 8. Mockup notes

`display-mockup.html`: self-contained (no CDN, vanilla JS only), works standalone
via file://. The fixed top demo strip (wraps on narrow screens, never clipped)
forces Desktop (both rails inline) / Tablet / Phone layouts at any window width —
the breakpoint CSS is a single set of JS-injected chunks used both inside media
queries (Auto) and bare (forced), so forced views can't drift from responsive
behavior. **Phone-reviewable**: forced Desktop/Tablet frames render as a
transform-scaled zoomed-out preview (`scale = viewportWidth / frameWidth`,
negative margin-bottom removes the reserved blank space), and because any CSS
transform makes the frame the containing block for fixed descendants, the drawers
anchor to — and scale with — the frame, so the full desktop composition including
the right rail is visible on a ~390px phone. "State" button flips populated ↔
empty (landing). Landscape Letter 4×2 borderless sheets (D4–D6), outline-only
presentation (D7), Color Calibration group in the right rail (D8), left-rail
content ordered per D3.
