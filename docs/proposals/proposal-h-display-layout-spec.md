# /display responsive layout spec — issues #266 / #267 / #268

Design target for the unified display page (`frontend/src/features/display/DisplayPage.tsx`,
route `frontend/src/pages/display.tsx`). Companion mockup: `display-mockup.html` (same
directory; open standalone via file://, use its top demo strip to force any breakpoint's
view at any window width) — synced (this PR) with the committed mockup under
`docs/proposals/mockups/proposal-h/responsive-layout-2026-07-21.html`, which previously
predated this file's ADDENDUM (polish round) and D17/D18/D19 additions. All primitives are
react-bootstrap 2.10.10 / Bootstrap 5.3.8 (confirmed installed, including
responsive-Offcanvas). No new dependencies.

**Implementation status (2026-07-21):** #266 shipped (PR #274 — sheet fit-to-width,
both rails as `Offcanvas` nodes). #267 shipped (PR #283): **D12 v1** (dual-mode
Add/Browse `ToggleButtonGroup` + `CatalogBrowseResults.tsx`, filters-first plain text —
the typed operator grammar is explicitly out of scope, tracked as #276), **D15** (the
existing `Import.tsx` Text/XML/CSV/URL dropdown, mounted verbatim), and **D13's
landing/search-bar feedback half** (`InvalidIdentifiersStatus`, mounted in both the
populated-state action bar and the empty-project landing — the right-rail Status row is
D13's OTHER half, issue #272's own remaining scope, not that PR's). #268 shipped
(PR #293): **#268's own mapped rows (§5, §6 rows S1–S3)**: `DeckRow` (exported, gained an
`openLabel` prop) and a new `useLoadSavedDeck` hook extracted from `MyDecksPage.tsx`
(S1); `SavedDecksLandingPanel.tsx` (S2); `DeckInputLanding`'s `Col lg={4}`/`Col lg={8}`
grid, decks first when stacked, rendering neither column when there's nothing to show
(S3). **R7/D17/D18/D19 shipped (this PR — issue #284):** screen-only sheet presentation
(hairline pinline, no white fill, tightened inter-sheet gap, per-page label lines retired
in favor of one floating "n/M" pill — R7/D17); the asymmetric default inter-card gutter
(`spacing.col=0`/`spacing.row=14.5`, D18); and the right rail's Card Spacing (X/Y +
link/unlink) control that makes that gutter user-editable and persists it per deck (D19).
**D1/D4/D5/D6/M1 shipped (PR #286):** LETTER (not A4) is now the default paper size, matching
the D4–D6 fit math (an audit-driven amendment to issue #286 named this explicitly, since the
original fit tables were computed against Letter throughout); the default bleed edge is now
`STANDARD_BLEED_MARGIN_MM` (3.175mm) rather than the old `BleedEdgeMM` (3.048mm); and the right
rail's Page Setup section gains a new margin-profile `Form.Select` (Borderless 0mm — the
default — / Bordered 3mm / Rear-feed 3mm+20mm trailing edge, `marginProfiles.ts`), persisted
per deck via a new `marginProfileSlice` riding the same `deckPayload.ts` precedent
`cardSpacingSlice` (D19) established. The old hardcoded Bleed-edge input `max` clamp is
removed — a soft warning (never a hard clamp) now surfaces when the current bleed exceeds the
selected profile's D6-table cap for a 4-column sheet, computed dynamically
(`maxBleedForFourColumns`) rather than copying the table's numbers verbatim. At these shipped
defaults, /display's sheet now renders the spec's own 4×2 grid (D4) exactly, not the 4×1 this
doc previously reported as the interim state before D5/D6 landed. Deliberately NOT built here
(this PR, and not by #266/#267/#268/#284 above either): D9–D11/D14/D16 (own future issues, per
§A2's own issue mapping).

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
  trail) and the D19 Card Spacing (X/Y + link/unlink) group — the two genuinely
  new controls in this section.
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
- **M2** (D18) `DisplayPage.tsx:646` — the `spacing` memo default
  `{ row: 0, col: 0 }` → `{ row: 14.5, col: 0 }` (asymmetric inter-card gutter:
  0mm horizontal, 14.5mm vertical). One-line change; the memo already feeds
  `computeLayout`, `PagePreview`'s `spacing` prop, and `exportPdfProps`'
  `cardSpacingRowMM`/`cardSpacingColMM`, so preview and PDF move together.
  `layout.ts` untouched (it takes spacing as an argument). **D19 supersedes the
  "default only" scope of this row:** the memo is no longer a hardcoded constant
  — it becomes state written by the new right-rail Card Spacing (X/Y) control
  (D19 below), seeded from these same D18 defaults (`col`/X = 0, `row`/Y = 14.5)
  and persisted per deck alongside the other print defaults (the
  `finishSettingsSlice`→`deckPayload.ts` precedent D8/D11 already ride). All three
  downstream consumers stay wired to the memo, so the control moves preview + PDF
  in lockstep with no extra plumbing.

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
   leave only ~520px of sheet inside the cap — cramped. RESOLVED (issue #287):
   `ProjectContainer` gained an additive, optional `fullWidth` prop (default
   `false`, every other caller unchanged) and `/display` opts in — at ≥1200px
   viewports with both rails inline, the sheet region now measures its own
   uncapped available width (~720px at the audit's 1400×900 reference, matching
   the naturally-uncapped <1200px laptop tier) instead of the ~520px the cap
   left it.
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

---

# ADDENDUM — polish round (2026-07-21): finish workflow, browse, status, confidence

Scope: the second design round the owner scoped in issue #272's comment
("deck auto-backup + Save-co-equal-with-Print finish footer, and rehoming the
4-tab print page as the funnel destination") plus the placement decisions on
#272 items 2/4/5/7 and the #271 confidence funnel. **D1–D8 are unchanged**;
§1–§8 above stand. This addendum adds decisions D9–D16, extends the change
inventory (§6) with new rows, and extends the issue mapping. Standing
constraints from the base spec still bind: repurpose /editor components (never
fork), compose in display-side containers so shared components stay
upstream-clean, react-bootstrap primitives only, three-region language.

## A0. Owner decisions log (polish round)

- **D9 — Finish footer: Save Deck and Print/Export are CO-EQUAL primaries, and
  persistence always precedes PDF rendering.** HARD OWNER CONSTRAINT (verbatim):
  _"save deck should come before PDF completes because we have to rely on
  clients available mem for the PDF."_ PDF generation is the client's most
  memory-hungry step and can OOM/crash the tab; therefore the working project
  is persisted BEFORE any PDF render begins, and PDF completion is never the
  gate to saving. Three mechanisms, layered:

  1. **Silent local draft auto-backup** (new `useProjectDraftBackup` hook,
     `localStorage`). The working project — decklist identifiers, per-slot
     queries/overrides, and the page/finish/calibration settings — is mirrored
     to `localStorage` on a debounced write after every project mutation. This
     stores **indexes and settings only, never image pixels**, so it satisfies
     the governing premise ("we index, we do not store images") on our own disk
     as strictly as on the wire. It is anonymous-safe (no account, no server,
     no crypto) and is the crash/OOM safety net specifically: if the tab dies
     mid-PDF-render, the draft survives. On next `/display` visit with a
     non-empty draft and an empty project, a one-line "Restore your unsaved
     work?" nudge offers to rehydrate it. Serialization reuses
     `deckPayload.ts`'s `buildDeckPayload` **plaintext** shape (NOT the
     encrypted wire format — it is the user's own browser); a `draftVersion`
     rides the same forward-upgrade path `parseDeckPayload` already uses.
  2. **Promotion nudge** ("draft backed up — name and save it?"). At natural
     moments — post-import (project just went from empty to populated) and
     pre-print (Print/Export pressed) — a non-blocking nudge invites promoting
     the local draft to a real, encrypted, account-bound saved deck. Reuses the
     existing `Toasts` system and the existing mid-session-sign-in nudge
     precedent (saved-decks.md: "a one-time, informational-only toast nudges an
     anonymous user who signs in"). Anonymous users' nudge routes through sign-in
     first (server save is authenticated-only — Discord OAuth — by construction;
     the local draft is the anonymous user's only persistence, and that is fine).
  3. **Pre-print save prompt flow.** Pressing **Print/Export** runs a persist
     step FIRST, before any navigation or render: (a) flush the local draft
     synchronously; (b) if authenticated AND the project is dirty
     (`savedDeckSessionSlice` dirty-check / `lastSavedRevision`), show a
     lightweight "Save before printing?" prompt (Save `SaveDeckModal` / Skip) —
     mirroring the existing `LoadSafetyModal` "always take a safety copy before a
     destructive step" pattern, here applied to the PDF-render step instead of a
     deck-load step; (c) only after persistence resolves does navigation to the
     Print page (D10), and therefore any PDF render, begin. Saving gates PDF;
     PDF never gates saving.

  Footer layout (replaces §4.2's "Prepare Print footer" three-button stack):
  the pinned `rail-foot` holds **two co-equal `btn-primary` buttons of equal
  width side by side — `Save Deck` and `Print / Export →`** — with a secondary
  `Export ▾` (the lightweight `DisplayExportMenu`: XML / decklist / images, none
  of which are memory-heavy) below them. The memory-heavy operations (Generate
  PDF, Save PDF to Google Drive) move OUT of the footer to the Print page (D10),
  so the footer itself can never trigger an OOM. Component sources:
  `SavedDeckPanel.tsx`/`SaveDeckModal.tsx` (Save), `savedDeckSessionSlice`
  (dirty check), `LoadSafetyModal.tsx` (the safety-save precedent),
  `DisplayExportMenu` (lightweight exports). NEW code: `useProjectDraftBackup`
  hook + a `PrePrintSaveGate` composition. This surface needs its OWN issue.

- **D10 — The 4-tab "Print!" page is the funnel DESTINATION, kept intact.**
  `FinishedMyProject.tsx` (the MakePlayingCards / NotMPC / PringlePrints supplier
  tabs + the `PDFGenerator` "PDF" sub-tab) is unchanged. Today it is only
  reachable as the /editor "Print!" tab (`ProjectEditor.tsx`'s `PrintPanel`,
  there is no standalone route). D10 gives it a thin route wrapper —
  **`pages/print.tsx` mounting `PrintPanel`/`FinishedMyProject`** — mirroring the
  established `pages/myDecks.tsx`→`MyDecksPage` and `pages/shared.tsx`→
  `SharedDeckPage` wrapper pattern (compose, don't fork). The Finish footer's
  `Print / Export →` button navigates there via client-side nav, which preserves
  the in-memory project (DisplayPage.tsx already relies on this for the
  /display↔/editor hop). The D9 pre-print persist runs before this navigation.
  **Where the MPC/supplier links live:** they stay in the Print page's own tabs —
  that page IS the print off-ramp (#272 item 3). They are NOT duplicated into the
  /display right rail; the rail funnels to the page, the page owns the supplier
  links and the heavy PDF generation. `PDFGenerator` keeps mounting
  `PostExportContributionPrompt` itself, so the /whatsthat funnel fires on the
  Print page for free (print-export-page.md). The /editor "Print!" tab keeps
  working unchanged — both /display and /editor now funnel to the same
  destination.

  **D10 owner addendum (2026-07-21, relayed):** two changes to the Print page's
  own tabs, folded into this funnel-destination design:

  1. **Tab REORDER + default.** Owner order (verbatim, autocorrect noise
     resolved): _"PDF is default, then MPC, then NotMOC, then Pringle."_ Mapped
     to the page's actual tab names (`FinishedMyProject.tsx`'s
     `FinishedMyProjectExportType` keys / `navBannerItems`, per
     print-export-page.md):

     - `PDF` → **PDF** tab (`"pdf"`)
     - `MPC` → **MakePlayingCards** tab (`"mpc"` — the key is literally `mpc`;
       the tab is titled MakePlayingCards)
     - `NotMOC` → **NotMPC** tab (`"notmpc"` — "NotMOC" is autocorrect for NotMPC)
     - `Pringle` → **PringlePrints** tab (`"pringleprints"`)

     New order: **PDF · MakePlayingCards · NotMPC · PringlePrints**, with **PDF as
     the default/first active tab** (today the array order is PDF / PringlePrints
     / MakePlayingCards / NotMPC and the default active tab is `pringleprints` —
     both change). The mapping is unambiguous, so no open question here.

  2. **PDF tab drops its own preview.** The `PDFGenerator` PDF sub-tab currently
     renders its own live PDF preview; on /display the CENTER sheet region (§2,
     the fit-to-width landscape stack) is now the single preview, so the Print
     page's PDF tab keeps **generation + settings only** and drops the embedded
     preview. This is a change to `PDFGenerator`'s composition when mounted via
     the funnel — express it as a prop on the shared component (e.g.
     `showPreview={false}`) composed from the display-side caller, NOT a fork, so
     the /editor "Print!" tab can keep its own preview if desired. (Since the
     right-rail footer's heavy PDF generation already moves to this tab per D10,
     the preview-less PDF tab is purely the generate/settings surface reached
     after the D9 save gate.)

- **D11 — FinishSettings (foil/finish) → right-rail settings drawer** (owner
  decision, #272 item 4). `features/finishSettings/FinishSettings.tsx` (a
  cardstock `Form.Select` of 5 stocks + a Foil/Non-Foil `Toggle`, auto-disabled
  for non-foil-compatible stocks via `CardstockFoilCompatibility`, backed by
  `finishSettingsSlice`) mounts as a collapsed-by-default **`Finish` section**
  (`AutofillCollapse`) in the right rail's settings region (§4.2), placed after
  **View** and before **Cardback**. No fork — the same component /editor's
  MakePlayingCards finish step mounts. Already persists per saved deck via the
  `finishSettingsSlice`→`deckPayload.ts` precedent (the exact path D8's
  `colorCalibrationSlice` rides), so no new persistence plumbing.

- **D12 — Catalog browse via a DUAL-MODE search bar** (owner decision, #272 item
  5 + #267 — replaces porting `CardGrid` as its own page). The #267 populated-
  state search bar (§3) gains two modes:

  - **Add** (default): Enter runs the existing
    `convertLinesIntoSlotProjectMembers`/`addMembers` pipeline — adds to the deck
    (unchanged from §3).
  - **Browse**: the same input queries the CATALOG and renders results in the
    CENTER region, reusing the GridSelector search machine —
    `useGridSelectorSearch.ts` + `GridSelectorFilters.tsx` +
    `SelectVersionResults.tsx`'s `SelectVersionTile`/`MemoizedEditorCard` tiles
    (the same family already mounted in the left rail's Select Version section).

  **Component-reuse honesty (corrects the base spec's shorthand):** `CardGrid.tsx`
  is NOT the catalog — it renders the _project's own members_ as slots
  (front/back arrays of `MemoizedCardSlot`). So the browse-results grid is built
  from `SelectVersionResults`'s tile + `useGridSelectorSearch`'s
  `sortedFilteredIdentifiers`, using `CardGrid`'s responsive `Row`/`Col`
  layout (`xxl=4 lg=3 md=2 sm=1 xs=1`) only as the visual template — CardGrid
  itself is not forked or re-mounted for browse.

  **Search feature-set scope (honest gap):** the source-filter / DPI / size /
  language / printing-tag / fuzzy-vs-precise settings the owner named already
  exist as `features/searchSettings/` (`SourceSettings`, `FilterSettings` over
  `features/filters/`, `SearchTypeSettings`) and are reused directly. But a
  **Scryfall-style operator/tag query grammar** (`set:2x2 t:instant …`) has **no
  UI today** — the freeform query grammar currently lives only in the import-text
  path (`common/processing.ts`), per-line, not a live search bar. Browse mode's
  operator support is therefore partly net-new: it reuses the existing filter
  settings verbatim and adds an operator-aware query parse over the browse input.
  Flagged as an open question — how much operator grammar is in-scope for v1.

  **Mode UX.** A segmented `ToggleButtonGroup` (two buttons, `Add` / `Browse`)
  sits at the LEFT edge of the search bar as its mode prefix; the active mode
  also drives the input placeholder (`Add cards… e.g. 3x Lightning Bolt` vs
  `Search the catalog… (set:2x2 t:instant …)`). In Browse mode a filter row
  (repurposed `GridSelectorFilters` — source/DPI/size/language/printing-tag
  filters) appears directly under the bar. **Where results render:** the CENTER
  region gains a two-state switch — **`Print sheets` / `Browse results`** — so the
  user always knows what the center is showing; entering Browse mode flips the
  center to the results grid, leaving Print sheets one tap away. **Browse result →
  deck add:** each result tile carries an inline **`+ Add`** affordance reusing
  `AddCardToProjectForm`'s existing add path (the same one the card-detail modal
  exposes) — turning a browse hit into a deck slot without leaving Browse.
  Clearing the query (or tapping `Print sheets`) returns the center to the sheet
  stack. No new page — the machinery is composed into a display-side
  `CatalogBrowseResults` container.

- **D13 — Project status surface** (#272 item 2). Import failures (invalid
  identifiers) and runtime image failures get two coordinated homes, both
  repurposing existing components (`features/status/Status.tsx`,
  `features/invalidIdentifiers/InvalidIdentifiersStatus.tsx` +
  `InvalidIdentifiersModal.tsx`, `invalidIdentifiersSlice`):

  1. **Landing / search-bar feedback**: right after an import (paste or
     Import-dropdown), unresolved identifiers surface inline beside the search
     bar via the existing `InvalidIdentifiersStatus` component (a
     `variant="primary"` Jumbotron with a `variant="warning"` "Review Invalid
     Cards" button that dispatches `showModal("invalidIdentifiers")` → the
     `InvalidIdentifiersModal` slot/face/query/identifier table). It self-hides
     when `selectInvalidIdentifiersCount === 0`, so it costs nothing when clean.
     On the empty-project landing the same component attaches under the paste
     column.
  2. **Right-rail status row**: a persistent **Status row** at the TOP of the
     right rail (above Page Setup) that mounts `Status.tsx` (=
     `InvalidIdentifiersStatus` + `ProjectStatus`) as a compact aggregation —
     when clean it collapses to a single "No issues" line; when
     `selectInvalidIdentifiersCount > 0` (or an image failed) it shows a
     `degraded`-styled "N warnings" summary opening the same modal. This is the
     "something's wrong with your project" surface /display lacks today, reachable
     from the gear below xl.

- **D14 — Printing-confidence funnel in the left-rail PROMOTED identity zone**
  (#271). A compact **confidence element** joins the always-visible identity
  header (§4.1 promoted zone — this is identity information, not demoted
  metadata), directly under the card name + `RequestedPrintingBadge`:

  `[⛨ set symbol] SET · 117 · 92% confident · [✗ not this printing]`

  - **Set symbol**: the existing `SetIcon` (`components/SetIcon.tsx`, a Keyrune
    `ss ss-<code>` glyph) — already mounted in `CardDetailedViewModal`,
    `PrintingTagPicker`, `QuestionFeed`.
  - **Confidence read**: reuses the `resolved`/`suggested` status the printing
    grouping already computes (`selectVersionGrouping.ts` —
    `canonicalCard` present ⇒ human-resolved/high-confidence; only
    `suggestedCanonicalCard` ⇒ machine-suggested/lower-confidence; the
    `suggestedCanonicalCard`/`tagVoteStatuses` plumbing marked shipped in #236).
    A `resolved` printing reads "confirmed"; a `suggested` one shows the
    machine-suggested confidence.
  - **Scryfall image on hover**: an `OverlayTrigger`+`Popover` on the set symbol
    shows the Scryfall image of that printing — **display-serving only, from
    Scryfall's own CDN, nothing stored** (satisfies the governing premise and
    #271's own note).
  - **One-click "incorrect"**: the `✗ not this printing` control casts a REAL
    human vote through the existing consensus path (`useTagVoting` /
    `AttributeVotingPanel`'s submission — no new vote semantics), the human half
    of the Stage D machine-vote funnel (#271), composing with the review queue
    (#262).

  Reconciliation with #271's "don't push to design" note: that hold was against
  the _then-current_ #266–268 mockup round; the owner has now explicitly scoped
  the confidence funnel INTO this polish round (task item 6), so it is designed
  here. The implementation still sequences after the #266–268 layout lands, per
  #271.

- **D15 — Import variety confirmed in the search-bar Import dropdown** (#272 item
  1 + #267). The populated-state search bar's `Import ▾` dropdown carries the
  full set the /editor `AddCardsPanel` already mounts — **URL / XML / CSV**
  (`ImportURL` / `ImportXML` / `ImportCSV` modal variants from `Import.tsx`), with
  paste covered by the inline `ImportText` input itself. This is the §3 T4 row,
  restated as an explicit coverage confirmation: no new importer UI, the CSV/XML/
  URL trio is the existing dropdown reused verbatim. Import failures feed D13's
  status surface.

- **D16 — Cardback swatch strip in the right-rail Cardback section (optional,
  lightweight — KEPT).** #272 item 7 (CommonCardback's swatch gallery chrome,
  which #240's button shipped without). It fits the right rail cleanly: the
  Cardback section (§4.2) becomes a compact **horizontal swatch strip** (the
  project's cardback options as small tappable thumbnails, active one outlined)
  above the existing "Choose cardback…" button that opens the full
  `CommonCardback` modal. It is a thin repurpose of `CommonCardback`'s own
  gallery data, no new modal. **If it crowds the rail at 300px it is acceptable
  to drop it back to the button-only form** — it is genuinely optional and the
  modal already covers the function; the strip is a convenience, not a
  requirement.

- **D17 — Sheet-presentation refinement (SUPERSEDES D7 where they differ).** Owner
  refinement of the screen-only sheet presentation; D7's "outline only, no white
  fill, minimal inter-page space, rounded corners" stands, but its "subtle border
  frame" framing is sharpened and the per-page label is removed:

  1. **Page boundary = a HAIRLINE PINLINE, not a drawn box.** The page fill stays
     fully clear (no white — already so under D7); the boundary is a hairline-weight
     pinline with rounded corners — deliberately subtle, read as a hint of a page
     edge, NOT a visible frame. In the render this is a ~1px, very-low-opacity
     border (mockup: `rgba(235,235,235,.18)`), radius ~7px. `PagePreview.tsx`'s
     screen-presentation variant (R7) carries this exact weight; the PDF output is
     still untouched.
  2. **Inter-page spacing minimized further** ("we waste a lot of space right now").
     The inter-sheet gap tightens to a hairline of its own (mockup: 4px) — pages
     read as a tight continuous stack, not a spaced-out gallery. Tightens R7's
     "inter-sheet spacing" note and §2's `mb-4`→minimal claim to ~4px.
  3. **Kill the per-page "Sheet N of M" header LINE; replace with a compact
     floating indicator.** The per-sheet label line (mockup's `.sheet-label`, and
     the §1/§3 action-bar "Sheet N of M" readout it duplicated) is removed
     entirely. In its place: ONE compact floating **`n/M`** pill (tabular-nums,
     pill-shaped, translucent) that lives INSIDE the center sheet region, `position: sticky` and `align-self: flex-end` so it floats at the top-RIGHT of the
     center column and **updates live as the user scrolls** (driven by the existing
     "Sheet N of M" `IntersectionObserver` DisplayPage.tsx already runs — see §context;
     now it writes the floating pill instead of an action-bar label). **Collision
     safety at every breakpoint:** because the pill is a child of the center flex
     column (a sibling of, never overlapping, the left/right rails), it is
     structurally confined to the center region — it cannot collide with an inline
     rail (desktop/laptop) nor with an off-canvas drawer (tablet/phone, which
     portal above everything anyway). `pointer-events: none` so it never eats a
     scroll/tap. This makes the floating indicator the SINGLE sheet-position
     readout, replacing both the per-sheet lines and the action-bar element in §1's
     region-inventory row "Sheet indicator" (that row's Action-bar home is retired
     in favor of the center-region floating pill at all breakpoints).

- **D18 — Default inter-card spacing on the sheet: HORIZONTAL 0, VERTICAL 14.5.**
  Owner reviewed D17 on desktop ("looks good") and added this asymmetric default
  gutter. Parameter mapping to the real engine (`frontend/src/features/pdf/layout.ts`,
  `computeLayout`): the only spacing knob is `spacing: LayoutSpacing = { row, col }`,
  both in **mm** (the whole module is mm — every argument is `*MM`). `spacing.col`
  is consumed by `fitCardsInDimension` on the **width/column** axis (the gutter
  _between columns_, i.e. the horizontal gap); `spacing.row` on the
  **height/row** axis (the gutter _between rows_, the vertical gap). Therefore:

  - owner **HORIZONTAL 0** → **`spacing.col = 0`** (columns' bleed boxes touch)
  - owner **VERTICAL 14.5** → **`spacing.row = 14.5`** (14.5mm added between rows)

  Real change site: `DisplayPage.tsx:646` `const spacing = useMemo(() => ({ row: 0, col: 0 }), [])` → `({ row: 14.5, col: 0 })`; this single memo already feeds all
  three consumers — `computeLayout` (§2), `PagePreview` (`spacing` prop), and
  `exportPdfProps` (`cardSpacingRowMM`/`cardSpacingColMM`) — so the on-screen sheet
  and the exported PDF stay in lockstep with no extra plumbing. Units are mm and
  unambiguous in-code; no flag raised.

  **Fit re-check, 4×2 Letter landscape** at D5 borderless margins (0/0/0/0) + D6
  bleed 3.175 + `spacing.col=0` + `spacing.row=14.5`, using
  `fitCardsInDimension`'s exact `count·slot + (count−1)·spacing + 0.1` formula:

  - Width axis (slot 63+2·3.175 = 69.35): `4·69.35 + 3·0 + 0.1 = 277.5 < 279.4`
    (5 would need 346.85) ⇒ **4 columns**, container 277.5mm, **slack 1.9mm**.
  - Height axis (slot 88+2·3.175 = 94.35): `2·94.35 + 1·14.5 + 0.1 = 203.3 < 215.9`
    (3 would need 312.15) ⇒ **2 rows**, container 203.3mm, **slack 12.6mm**.

  **Fits.** (Matches the sanity estimate 2·94.35 + 14.5 = 203.2, +0.1 fudge =
  203.3.) **Binding constraint is UNCHANGED — still the width/column axis** (1.9mm
  slack) as under D4/D6; the new 14.5mm row gutter only eats row-axis slack from
  25.1mm down to 12.6mm, and the row axis stays non-binding (it would tolerate
  vertical spacing up to ~27.0mm, or bleed up to ~6.32mm, before losing the 2nd
  row). So D18 costs nothing dimensionally: borderless + full MPC bleed + 4×2
  still holds, and the D6 max-bleed-for-4×2 table (governed by the width axis) is
  untouched.

- **D19 — Card Spacing (mm) control group in the right rail's Page Setup section.**
  Owner-directed; makes the D18 default gutter user-editable. **PROVENANCE NOTE
  (verbatim discipline):** the control's BEHAVIOR is emulated from an owner-provided
  screenshot description of an AGPL-licensed proxy-PDF tool — no source code was
  consulted or is consultable (AGPL); this is the patterns-only posture
  `docs/upstreaming/license-provenance.md` mandates (referencing behavior from a
  public tool is always fine; code reuse is not, and none occurred here). The group:

  - **Two numeric inputs**, unit **mm**: **Horizontal (X)** and **Vertical (Y)**,
    defaults **0 / 14.5** (D18). Axis mapping is D18's, unchanged: **X → `spacing.col`**
    (the gutter between columns, `fitCardsInDimension`'s width axis), **Y →
    `spacing.row`** (the gutter between rows, the height axis).
  - **A LINK/UNLINK toggle between the two inputs.** Linked ⇒ one value drives both
    axes (editing either writes both); unlinked ⇒ independent X and Y. Because the
    D18 defaults are asymmetric (0 ≠ 14.5), the group **opens UNLINKED** — linking
    would collapse to a single value and discard the asymmetric default, so linked
    is an opt-in convenience, not the initial state.
  - **Helper text** conveying the rationale: separate axes ease cutting — a 0
    horizontal gutter butts columns together for strip cutting, while a vertical
    gutter suits die cutters. (Mockup copy: "Separate axes ease cutting — 0
    horizontal butts columns for strip cutting; a vertical gap suits die cutters.")
  - **Wiring (conceptual, per the M2 row):** the two inputs write the
    `DisplayPage.tsx:646` spacing memo — which stops being a hardcoded constant and
    becomes state seeded from the D18 defaults. The memo already feeds `computeLayout`,
    `PagePreview`'s `spacing` prop, and `exportPdfProps`'
    `cardSpacingRowMM`/`cardSpacingColMM` (verified in code at `DisplayPage.tsx`
    lines 720-721, 798, 1145), so the control moves the on-screen sheet and the
    exported PDF in lockstep with no extra plumbing. **Persisted per deck**
    alongside the other print defaults, following the
    `finishSettingsSlice`→`deckPayload.ts`/`MyDecksPage.performLoad` precedent D8's
    `colorCalibrationSlice` and D11's `finishSettings` already ride.
  - **Placement:** inside the existing **Page Setup** `AutofillCollapse` group
    (§4.2), after the Margins control, grouped with the other page-geometry
    controls; respects the collapsed-group pattern (Page Setup is open by default,
    so the control is visible at rest). Reachable on phone/tablet via the same
    gear-opened right-rail drawer as every other Page Setup control — no new
    surface, no new drawer.

  **Implemented as-shipped (this PR, R7+D17+D18+D19):** the right rail doesn't yet
  have `AutofillCollapse` sectioning (that's still the flat, relocated-verbatim
  layout the base spec's own R4 row describes as not-yet-built) — the control is
  placed in the existing flat "Page Setup" block, directly after the Guides toggle,
  as `CardSpacingControl.tsx` (a standalone component so the link/unlink behavior
  has a plain unit-test target). The link/unlink toggle itself is local, session-
  only UI state (always opens unlinked, never persisted); only the numeric X/Y
  values persist per deck.

- **D8-note (not a new decision): color calibration is CMYK, not just CMY.**
  #270 extends D8's per-channel controls from cyan/magenta/yellow to full
  **CMYK (adds black/K)** plus brightness/saturation/contrast. This is an
  implementation-scope note on the existing D8 group, folded in here so the
  mockup's Color Calibration group shows the K channel; no layout change.

## A1. Change inventory (new rows, extending §6)

Finish workflow (D9, D10):

- **F1** new `frontend/src/features/display/useProjectDraftBackup.ts` —
  debounced `localStorage` mirror of the working project (indexes+settings only),
  restore-nudge on next visit; serialization via `deckPayload.ts`'s
  `buildDeckPayload` plaintext shape + a `draftVersion`.
- **F2** `DisplayPage.tsx` right-rail footer — replace the three-button stack
  with the two co-equal `btn-primary` (`Save Deck` = `SavedDeckPanel` Save path;
  `Print / Export →` = D10 nav) + secondary `Export ▾` (`DisplayExportMenu`,
  lightweight only). Move Generate PDF / Save-PDF-to-Drive OUT to the Print page.
- **F3** new `PrePrintSaveGate` (in `DisplayPage.tsx` or a sibling) — the D9(3)
  sequence: flush draft → (auth+dirty) `SaveDeckModal`/Skip → then navigate.
  Reuses `savedDeckSessionSlice` dirty-check + `LoadSafetyModal` precedent.
- **F4** promotion nudge — one `Toasts` entry fired post-import and pre-print,
  reusing the mid-session-sign-in nudge precedent (saved-decks.md).
- **F5** new `frontend/src/pages/print.tsx` — thin route wrapper mounting
  `PrintPanel`/`FinishedMyProject` (mirrors `pages/myDecks.tsx`). `FinishedMyProject.tsx`
  itself UNCHANGED. The export progress bar + Generate-PDF live here now, not the
  rail footer.

Settings relocation (D11, D16, D8-note):

- **F6** `DisplayPage.tsx` right rail — mount `FinishSettings.tsx` as a `Finish`
  `AutofillCollapse` section (after View, before Cardback). No component change.
- **F7** `DisplayPage.tsx` Cardback section — compact swatch strip over
  `CommonCardback`'s gallery data (D16), above the existing Choose-cardback
  button. Optional/droppable.
- **F8** (folds into C1/C2) Color Calibration group gains the K channel (D8-note
  / #270) — one extra slider, no layout change.

Browse + status + confidence (D12, D13, D14, D15):

- **F9** `DisplayPage.tsx` search bar — `ToggleButtonGroup` Add/Browse mode
  prefix; Browse-mode filter row (`GridSelectorFilters`); placeholder swap.
- **F10** new `frontend/src/features/display/CatalogBrowseResults.tsx` —
  center-region results grid composing `useGridSelectorSearch` +
  `SelectVersionResults`'s tile, laid out on `CardGrid`'s responsive Row/Col
  template (not CardGrid itself — that renders project members), each tile with
  an inline `+ Add` (`AddCardToProjectForm` path). Center-region `Print sheets` /
  `Browse results` switch. Operator-grammar parse over the browse input is the
  one net-new piece (see D12 honesty note).
- **F11** `DisplayPage.tsx` — landing/search-bar invalid-identifiers `Alert`
  (repurpose `InvalidIdentifiersStatus`/`InvalidIdentifiersModal`) + a right-rail
  top **Status row** (repurpose `Status.tsx` aggregation). No component fork.
- **F12** `DisplayPage.tsx` left-rail identity header — the D14 confidence
  element: `SetIcon` + resolved/suggested confidence read + Scryfall
  `OverlayTrigger`/`Popover` (CDN-only) + `✗ not this printing` casting a
  `useTagVoting` vote.
- **F13** search-bar `Import ▾` dropdown — confirm URL/XML/CSV via `Import.tsx`
  variants (D15; = §6 T4, restated). No new UI.

Card spacing control (D19) — **SHIPPED** (this PR, alongside R7/D17/D18):

- **F14** `DisplayPage.tsx` right-rail Page Setup section — a **Card Spacing (mm)**
  control group: two `Form.Control type="number"` inputs (Horizontal X / Vertical Y,
  defaults 0 / 14.5) with a LINK/UNLINK toggle (`Button`/`ToggleButton`) between
  them. Converts the `DisplayPage.tsx:646` spacing memo (M2) from a constant to
  state; X writes `spacing.col`, Y writes `spacing.row` (D18 mapping). Linked ⇒ one
  value drives both; opens unlinked (asymmetric defaults). Persist per deck via the
  `finishSettingsSlice`→`deckPayload.ts` precedent (as D8/D11). All three existing
  memo consumers (`computeLayout`, `PagePreview.spacing`, `exportPdfProps`) stay
  wired, so no new plumbing. Placed after the Guides toggle in the flat (not yet
  `AutofillCollapse`-sectioned) Page Setup block; reachable below xl through the
  gear-opened right-rail drawer. Behavior emulated from an owner-supplied
  AGPL-tool screenshot — patterns only, no source consulted (D19 provenance note).
  The only genuinely new control in Page Setup besides D5's margin-profile select
  (D5 itself is not part of this PR).

## A2. Issue mapping (extending the base §"Issue mapping")

- **#267** (search bar) — additionally: D12 dual-mode Add/Browse (F9/F10),
  D15 Import-dropdown variety (F13), D13 search-bar status feedback (F11).
- **#270** (color calibration) — D8-note: extend the D8 group to full CMYK
  (F8). Implementation issue; already filed.
- **#271** (confidence funnel) — D14 (F12). Already filed; design now provided.
- **#272** (parity switchover checklist) — item 2 → D13 status surface (F11);
  item 3 → D10 Print-page rehoming (F5); item 4 → D11 FinishSettings (F6); item
  5 → D12 browse (F9/F10); item 7 → D16 cardback swatch (F7); item 1 → D15
  import variety (F13).
- **NEW issue needed** — **D9 finish footer + deck auto-backup** (F1–F4). The
  owner named this in #272's comment as polish-round scope but it has no issue
  number of its own; it is the one genuinely-new surface here (local-draft
  persistence + co-equal Save/Print + pre-print save gate) and should be filed
  as its own issue at implementation time. D10's `pages/print.tsx` route
  (F5) can ride #272 item 3 or the same new issue.

## A3. Conflicts / tensions (new, honest)

1. **Server save is authenticated-only; the OOM safety net must not be.** The
   zero-knowledge saved-decks design (saved-decks.md) means a real "Save Deck"
   requires Discord OAuth. The owner's constraint is about not losing work to a
   PDF-render OOM, which must hold for anonymous users too. D9 resolves this by
   making the _local draft_ (F1) the universal safety net and the _server save_
   the authenticated promotion — they are two layers, not one. The nudge copy
   must not imply an anonymous user's work is unsaved when the local draft has it.
2. **D10 moves Generate PDF off /display.** Some users expect to generate a PDF
   without leaving the page. The trade is deliberate: keeping the heavy render on
   the dedicated Print page is exactly what honors the owner's "PDF relies on
   client mem" constraint (a single place, after the save gate, that can OOM
   without taking unsaved work with it). If the owner wants a quick inline PDF
   too, it must sit AFTER the same F3 save gate — flag as open question.
3. **Center-region contention (D12 browse vs. the sheet stack).** Browse results
   and the print-sheet stack both want the center. The `Print sheets`/`Browse results` switch is the resolution, but on phones the center is already tight
   (letterboxed sheet, §2); browse results there render as a single-column scroll
   list rather than a grid. Not a blocker, but the phone browse view is a reduced
   grid by necessity.
4. **Confidence "confirmed" wording.** The `resolved`/`suggested` status is a
   two-state proxy, not a true probability; showing a literal "92% confident"
   risks implying a calibrated model output that isn't there for `resolved`
   cards. The element should read a _resolved_ card as "confirmed" and only show
   a numeric confidence where the backend actually exposes one for a _suggested_
   card — otherwise it overstates certainty. Owner/impl to confirm the exact copy.

## A4. Mockup notes (polish additions)

`display-mockup.html` gains, without disturbing the demo strip or the scaled
forced-view mechanism (§8): the two-co-equal-primary Finish footer (Save Deck /
Print & Export) + secondary Export row and a "draft backed up ✓" indicator (D9);
the dual-mode Add/Browse toggle on the search bar with a center-region `Sheets | Browse` switch and a browse-results demo state (D12); a right-rail Status row and
a search-bar invalid-identifiers alert (D13); the left-rail confidence element
(set symbol + confidence + Scryfall-hover note + "not this printing", D14); the
Finish (foil/cardstock) section and a Cardback swatch strip in the right rail
(D11/D16); and the Color Calibration group extended with a K (black) channel
(#270). It also demonstrates D17: the sheets now render with a hairline pinline
(no drawn frame), a tightened inter-page gap, no per-sheet label lines, and a
single floating `n/M` pill (six demo sheets) wired to an `IntersectionObserver`
that updates it live while scrolling — sticky to the top-right of the center
column so it never collides with the rails/drawers at any breakpoint. All new
interactive bits are vanilla-JS toggles consistent with the existing mockup; no
CDN, still file://-openable. **D18**: the print sheets now render the asymmetric
default gutter — the `.sheet` grid splits its single `gap` into `column-gap: 2.27cqw` (2·3.175mm bleed only, `spacing.col=0`, columns touching) and `row-gap: 7.46cqw` (2·3.175mm bleed + 14.5mm = 20.85mm, `spacing.row=14.5`, rows visibly
separated); `1cqw = 2.794mm` since the sheet's inline-size represents 279.4mm.
Applies at every breakpoint (the sheet is `container-type: inline-size`, so the
gutter scales with the fit-to-width sheet on phone/tablet/desktop alike).
**D19**: the right rail's Page Setup group gains a **Card Spacing (mm)** control —
two numeric inputs (Horizontal X / Vertical Y, defaults 0 / 14.5) with a
LINK/UNLINK toggle between them (opens unlinked, since the defaults are
asymmetric; linking makes one value drive both) and helper text on the
strip-cutter/die-cutter rationale. Placed after the Margins control, it is a
vanilla-JS toggle consistent with the existing mockup; still file://-openable, no
CDN. In the real page these inputs write the `DisplayPage.tsx:646` spacing memo
(X→`spacing.col`, Y→`spacing.row`), persisted per deck. Behavior emulated from an
owner-supplied AGPL-tool screenshot — patterns only, no source consulted.
