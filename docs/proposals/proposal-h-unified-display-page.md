> **HISTORICAL — SUPERSEDED.** This is the original Proposal H design
> doc (2026-07-21 draft). As of the 2026-07-21/22 review rounds,
> [`proposal-h-display-layout-spec.md`](proposal-h-display-layout-spec.md)
> is the **single living spec** for `/display` — it is newer, denser, and
> the doc every decision from the 2026-07-21 polish round onward and every shipped PR since #274
> was written against. This file's own single-toolbar/single-rail layout
> (§2–§3) and component-mapping table (§5) describe an EARLIER page shape
> that the newer spec's three-region (left rail / center sheet / right
> rail) layout replaced; most of this file's own body already
> self-annotates individual sections as SUPERSEDED or BUILT. Kept
> unmodified below for historical/archaeological context (why the design
> arrived where it did, the prior-art/license grounding in §1, which
> instruments were reused from which existing components) — not edited
> further, not a target for new content. A short list of items from this
> doc that were still genuinely open and not yet re-answered by the
> newer spec is carried forward in that file's own "Consolidation note"
> section (§A5) rather than left stranded here.

As of: 2026-07-21
What this is: Proposal H — survey + design + static HTML mockups for a
single unified display page that replaces both the "Choose Art" grid
editor and the separate PDF-preview/export step with one page that IS
the live print-sheet preview, with a persistent card-details rail beside
it. **PARTIAL — this doc's own design/mockup pass is complete and most of
§6's migration plan has since shipped as feature code** (route shell #87;
inline PDF export #109; missing-image slot names #104; requested-printing
badge #110/#102; the candidate/version picker #96; flat-scroll +
virtualization #115; the pane migration's remaining rail instruments —
Attributes, Print Options, Artist, Slot Actions — issue #164; §4.4′'s
Select Version section rework — issue #167, `SelectVersionResults.tsx` —
see `docs/features/grid-selector.md`'s own "Select Version section" entry
for what actually shipped vs. what's still open; and, most recently, the
milestone's post-export contribution prompt — issue #166,
`frontend/src/features/export/usePostExportContributionPrompt.ts` +
`PostExportContributionPrompt.tsx` — see `docs/features/printing-tags.md`'s
own entry for the full detail; and, most recently, **deck-input landing**
(§4.1, issue #238 — `/display`'s `isProjectEmpty` early return now mounts
`ImportText`/`ImportURL`/`ImportXML`/`ImportCSV` inline, the same
components `ProjectEditor.tsx`'s `AddCardsPanel` uses, in place of the
old plain "go to `/editor`" link — see §4.1's own updated status line);
and, most recently, **Search Settings toolbar parity** (§5, issue #239 —
the toolbar now mounts `SearchSettings.tsx` unmodified, alongside the
paper/bleed/guides controls; see §5's row and §6 step 4); and, most
recently, **Cardback toolbar parity** (§5, issue #240 — the toolbar now
mounts a new `CardbackToolbarButton` (`CommonCardback.tsx`), a
button+modal pairing that reuses `MemoizedCommonCardbackGridSelector`'s
existing `GridSelectorModal` verbatim; see §5's row and §6 step 4); and,
most recently, **Export ▾ toolbar parity** (§5, issue #241 — the toolbar
now mounts a new `DisplayExportMenu.tsx`, composing the same unmodified
`ExportXML.tsx`/`ExportImages.tsx`/`ExportDecklist.tsx` `Dropdown.Item`s
the classic editor's own "Download" dropdown already uses, alongside
Generate PDF/Save to Drive — `ExportPDF.tsx` itself stays out, since
Generate PDF already reuses `useDownloadPDF` directly rather than
opening the classic `PDFGenerator` modal that item dispatches to; see
§5's row and §6 step 4). **§6 step 4's toolbar instrument parity queue
(issues #239, #240, #241) is now complete** — every finding from the
2026-07-20 feature-parity audit against `/editor` has shipped; and, most
recently, **the mobile/tablet responsive shell** (§3, issue #266 — the
owner-approved 2026-07-21 review round produced a full three-region
layout spec superseding this doc's own §3/mockups for the responsive
behaviour specifically, see
[`proposal-h-display-layout-spec.md`](proposal-h-display-layout-spec.md)
and its companion mockup in `mockups/proposal-h/`. #266 shipped the
sheet region's fit-to-width `ResizeObserver` scaling, and both rails as
single `Offcanvas responsive={bp}` nodes — inline sticky columns at
laptop (left)/desktop (both), a `start` drawer (tablet) or `bottom`
72vh sheet (phone) for the left rail, an `end` drawer everywhere but
desktop for the new right rail. Deliberately NOT part of #266 (see the
spec's own issue-mapping and this repo's implementing PR): the
`CardDetailedViewBody` extraction + the [left-rail de-clutter](proposal-h-display-layout-spec.md#left-rail-declutter-hierarchy) content reorder (spec §7.5, its
own follow-up), the [4×2 grid](proposal-h-display-layout-spec.md#4x2-landscape-grid)/[margin](proposal-h-display-layout-spec.md#margin-defaults-epson-et-8500)/[bleed](proposal-h-display-layout-spec.md#default-bleed-3175mm) default changes and the [color calibration](proposal-h-display-layout-spec.md#deck-wide-color-calibration) decision's (new scope beyond #266–268, filed as their own
issues), and issues #267 (search-bar migration)/#268 (saved-decks
landing) themselves); and, most recently, **#267's own mapped rows**
(the populated-state action bar `proposal-h-display-layout-spec.md`'s
§266-review round deferred — see that doc's own updated "Implementation
status" line): a dual-mode Add/Browse search bar (the [Dual-Mode Browse](proposal-h-display-layout-spec.md#dual-mode-browse-search-bar) decision, v1 —
`CatalogBrowseResults.tsx`, filters-first plain text, no typed operator
grammar yet — that's #276), the existing `Import.tsx` Text/XML/CSV/URL
dropdown mounted verbatim beside it (the [Import-Dropdown Variety](proposal-h-display-layout-spec.md#import-dropdown-variety-confirmation) decision), and `InvalidIdentifiersStatus`
mounted at both the populated-state search bar and the empty-project
landing (the [Project Status Surface](proposal-h-display-layout-spec.md#project-status-surface) decision's landing/search-bar feedback half only — the right-rail
Status row is issue #272's own remaining scope). Deliberately NOT part
of #267 either: the [Finish Footer](proposal-h-display-layout-spec.md#finish-footer-save-before-print)/[Finish-Settings Relocation](proposal-h-display-layout-spec.md#finish-settings-relocation)/[Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel)/[Cardback Swatch Strip](proposal-h-display-layout-spec.md#cardback-swatch-strip) decisions (own future issues) and the [Sheet-Presentation Refinement](proposal-h-display-layout-spec.md#sheet-presentation-refinement)/[Inter-Card Spacing](proposal-h-display-layout-spec.md#default-inter-card-spacing) decisions (a later
sheet-presentation/spacing refinement to #266 that appeared in the spec
after #267's own task was scoped — #266-adjacent, not yet mapped to any
filed issue); and, most recently, **#268's own mapped rows** (landing
cohesion with saved decks, `proposal-h-display-layout-spec.md`'s §5/§6
rows S1–S3 — see that doc's own updated "Implementation status" line):
the empty-project `DeckInputLanding` gains a saved-decks column
(`SavedDecksLandingPanel.tsx`) beside the existing paste/URL/XML/CSV
import surfaces, `Col lg={4}`/`Col lg={8}` at ≥992px (decks first when
stacked), reusing `DeckRow` (now exported, `openLabel` prop) and a new
`useLoadSavedDeck` hook extracted from `MyDecksPage.tsx` — the identical
open/load/unlock/safety-save path, just without MyDecksPage's own
`navigateTo` hop, so loading a deck from the landing populates the
current project in place. Renders neither the panel nor its grid column
for an anonymous or zero-saved-deck session.
Still not built: §6 step 5/6 (switchover to make `/display` the
default nav entry point, then retiring `/editor` + the classic PDF tab).
A related but deliberately
unscoped finding from the same audit pass: `FinishSettings.tsx` (cardstock +
foil) is a genuinely distinct component from `CardQualitySettings`
(§5's existing PDFGenerator-settings row) — not a naming collision — yet
has zero mapping anywhere in this doc either; see §5's new row and Open
decision 7 for why this stays a correction, not a fifth tracked gap. See
`docs/features/grid-selector.md`, `docs/features/print-export-page.md`,
and `docs/features/pdf-generator.md` for the surfaces this page is meant
to eventually absorb.

## 0. Vision, in our own words

Today a deck goes through two separate surfaces: an editor grid
(`pages/editor.tsx`-driven `CardSlot` grid) for picking each card's art,
then a distinct PDF-generator tab (`PDFGenerator.tsx`) for print layout
and export. Proposal A already collapsed the second surface's own
preview into a real print-sheet simulation (`PagePreview.tsx`, shipped as
PR #53) rather than a generic thumbnail list, and Proposal B is adding
real per-side bleed handling on top of it. Proposal H's job is to stop
treating "pick art" and "preview the sheet" as two pages at all: one
page shows the print sheet — paginated through the deck, landscape,
DEFAULT 4 columns × 2 rows per sheet — as the permanent main surface,
and every per-card fix (wrong art, wrong printing, bleed override,
attribute vote, delete/duplicate) happens by selecting a slot on that
sheet and using a persistent details rail beside it. Generate PDF lives
on the same page, operating on the same data the sheet already shows —
no separate export step, no separate preview step.

This stands as our own design, driven by our own three constraints
(WYSIWYG-first per Proposal A, per-side bleed accuracy per Proposal B,
the fork's existing per-card instrument set) — not copied from, or
positioned as equivalent to, any specific external product. Where a
pattern below derives from an actual open-source project we name it and
its license (see §1); every other reference in this document is
described generically, on its own merits.

## 1. Grounding — what we read, and prior art

**Current codebase, read directly for this pass** (cite: file, what it
establishes):

- `frontend/src/features/card/CardSlot.tsx` — the existing per-slot
  component: owns `showGridSelector` state, renders
  `MemoizedEditorCard` + `DeckbuilderConfirmAffordance` +
  `MemoizedCardSlotGridSelector` + a context menu, wires prev/next-arrow
  navigation through `CardFooter`. This is the component the sheet's
  individual slots keep using unmodified — see §5.
- `frontend/src/features/gridSelector/GridSelectorModal.tsx` — the
  version-picker: a `Modal` with a collapsible filters column
  (`GridSelectorFilters`, defaults **closed below 576px** —
  `SmallViewportFiltersBreakpointPx`, line 49) and a result grid
  (`CardResultSet`), plus `JumpToVersion` (`GridSelectorFilters.tsx:16`,
  a "type an option number or paste an identifier" form gated behind its
  own visibility toggle in `viewSettingsSlice`).
- `frontend/src/features/pdf/PagePreview.tsx` — the existing WYSIWYG
  sheet renderer (Proposal A, PR #53): plain DOM/CSS at real mm sizes,
  `transform: scale()` down to fit, fed by `computeLayout()`
  (`layout.ts`) so slot geometry matches the PDF exactly, cut-line
  overlay via `showCutLines`. This is the renderer the unified page's
  sheet panel reuses directly.
- `frontend/src/features/pdf/layout.ts` — `computeLayout()`'s greedy
  per-dimension fit (`fitCardsInDimension`). Checked the actual math for
  the brief's "default 4×2" claim: A4 landscape (297×210mm), 5mm margins
  all sides, 0mm spacing, 0mm bleed → available width 287mm ÷ 63mm card
  width = 4 columns; available height 200mm ÷ 88mm card height = 2 rows.
  Re-ran it at a typical bleed edge (3.175mm, `BleedEdgeMM`): slot size
  becomes 69.35×94.35mm, still 4 columns × 2 rows (287÷69.35=4.1,
  200÷94.35=2.1). **4×2 is not a hardcoded grid — it's what
  `computeLayout()` already produces for A4-landscape-ish page sizes at
  realistic bleed values**, so "default 4×2" in this design means "default
  to a landscape page size in that range," not a new layout primitive.
- `frontend/src/features/pdf/PDFGenerator.tsx` — confirms the "fast"
  preview mode already exists in embryonic form: line 1099's own comment
  distinguishes the debounce-free `PagePreview` fast path from the
  heavier `@react-pdf/renderer`+pdf.js "exact" canvas path
  (`PDFCanvasPreview`). The settings panel (`PageSizeSettings`,
  `CardSelectionSettings`, `CardQualitySettings`, `EdgeSettings`,
  `CutLinesSettings`, `SpacingAndMarginsSettings`, `SCMSettings`) is the
  existing deck-level control set the new top toolbar consolidates —
  see §5.
- `frontend/src/features/card/DeckbuilderConfirmAffordance.tsx` — Level
  0 of the printing-tag funnel (`docs/features/printing-tags.md`): an
  inert "Confirm?" badge shown only when
  `isUnconfirmedCanonicalImport` is true, expanding on hover/click into a
  pinned Scryfall-sourced reference thumbnail (`ComparePin`) plus
  disabled-until-compared Y/N buttons. Reused verbatim in the rail — see
  §5.
- `frontend/src/features/attributeChips/attributeChips.ts` +
  `AttributeChipPanel.tsx` — the tri-state (untouched → positive →
  negative → untouched) chip taxonomy: two mutually-exclusive groups
  (Border Color, Frame Style) plus five standalone chips (Full Art,
  Borderless, Showcase, Extended, Etched). `ChipRing`'s CSS (lines 80–100)
  already collapses from a 3-column ring to a single vertical stack below
  576px — exactly the "ChipRing collapses to vertical stack below sm"
  behavior the brief calls for; nothing new to build there, only a new
  mounting context (rail body, not the question-feed's card-centered
  ring).
- `frontend/src/features/card/CardSlotMenuActions.ts` +
  `CardSlotContextMenu.tsx` — the shared "one menu, two triggers"
  action list (Change Query / Duplicate / [Unfilter Printing] / Delete),
  already used by both the 3-dot dropdown and the right-click/long-press
  context menu (Proposal C part (a)). Reused unmodified in the rail.
- `frontend/src/features/pdf/bleedNormalize.ts` — confirms
  `ManualOverride = "auto" | "force-bleed" | "force-trimmed"` and
  `resolveBleedPlan()` already implement all three modes at the
  algorithm level.
- `docs/proposals/proposal-b-bleed-normalization.md` (status doc, read
  in full) — **correction to the brief's premise**: the manual-override
  _UI_ and its persistence are explicitly listed as **not yet built**
  ("Shipped vs. not yet built," items 1–3) — only the algorithm exists
  today. The doc also already records the owner's decision that, once
  built, persistence goes to **`projectSlice`** (real project state),
  _not_ `localStorage` — the brief's assumption of a localStorage-keyed
  map is superseded by that decision. This design treats the bleed
  override control as a rail instrument whose backing store Proposal B
  PR-2 will supply in `projectSlice`, not a new mechanism of its own —
  see §5 and §6.
- `frontend/src/common/schema_types.ts` — confirms `degradedQueries: string[]` on `EditorSearchResponse` (a search-server-level "this printing
  filter found nothing, retried unfiltered" list), used for the requested-
  printing badge's degraded styling.
- `docs/lessons.md`'s sticky/z-index entry — the concrete mechanism
  behind the brief's "own stacking context" requirement: `position: sticky` alone does _not_ establish a stacking context for a
  z-indexed descendant to escape safely, and a naive negative z-index
  on the sticky element itself can make its entire subtree
  un-hit-testable. The fix (the sticky element's own parent needs
  `position: relative` **and** an explicit non-`auto` `z-index`
  together) is the exact rule this design's rail follows at ≥768px —
  see §3.
- `docs/README.md`'s proposal status table and `proposal-g-...md`'s
  document shape were used as the format precedent for this doc (As
  of/What this is header, `## Decisions` section, `## N.` numbered
  sections).

**Open-source prior art, named and attributed** (the only external
projects this document names — everything else above is generic pattern
language, per the amendment):

- **`chilli-axe/mpc-autofill`** (GPL-3, our own upstream) — the
  paste-decklist → per-slot search → click-slot-to-see-all-matches →
  per-face front/back handling → XML-export interaction model this whole
  page must preserve. Nothing here replaces that model; it's the floor
  the unified page still has to satisfy.
- **`acoreyj/proxies-at-home`** (MIT) and its own credited lineage
  **`alex-taxiera/proxy-print`** (AGPL-3.0 — corrected here; verified
  directly against its GitHub license metadata, not assumed MIT because
  the project it's credited from is) — reusable, generically-described
  patterns, used here as: (a) a three-region page anatomy (deck input,
  a live paginated print-sheet grid as the visual center, a settings
  panel) rather than a wizard of separate steps; (b) grouping per-card
  controls behind a single dedicated interaction point per card, rather
  than scattering them across the grid; (c) keeping global print/export
  settings in one panel separate from per-card controls. No code,
  markup, or copy was copied from either project — pattern shapes only,
  attributed here per each project's own actual license (MIT for the
  first, AGPL-3.0 for the second — not the same license, don't conflate
  them).

Two further generic patterns (not tied to any single named project,
each independently reachable from first principles and common in
card-catalog/deckbuilder UIs) inform the rail and printing-switch design:
a persistent details rail with its own independent scroll container that
updates on selection rather than opening a new surface each time; and a
printing-switch view organized as a thumbnail grid keyed by set code +
collector number rather than by internal ID, so a user can recognize a
version by the same label a real card back would carry.

## 2. Information architecture

One route, three regions, always visible together at ≥768px:

```
┌─────────────────────────────────────────────────────────────────┐
│ TOP TOOLBAR (deck-level, full width)                             │
│ deck name · Page N of M ◀▶ · paper/bleed/guides · Generate PDF   │
├─────────────────────────────────────────┬─────────────────────┤
│                                           │  DETAILS RAIL         │
│   SHEET (live print-sheet preview)       │  (persistent,         │
│   PagePreview, 4×2 default, one page     │   own-scroll,         │
│   of the deck at a time, click/tap a     │   updates on          │
│   slot to select it)                     │   slot select)        │
│                                           │                       │
└───────────────────────────────────────────┴─────────────────────┘
```

Below 768px the rail is not a column at all — it's a full-overlay
bottom sheet that opens on slot-select and closes back to the sheet
view (see §3's mobile section and §4.2).

**Deck-level vs. per-card, the actual dividing line**: anything that is
true of the _whole export_ (page N of M, paper size, bleed edge, guides,
Generate PDF/Save to Drive) lives in the toolbar. Anything that is true
of _one selected slot_ (candidate art, confirm affordance, attribute
chips, requested-printing badge, bleed override, artist line, slot
actions) lives in the rail. Nothing straddles both — this is the same
split the brief specifies, and it maps cleanly onto existing state:
toolbar controls are exactly `PDFGenerator.tsx`'s current settings
panel (§1); rail controls are exactly the per-`CardSlot` instrument set
that already exists scattered across the editor grid today.

**No slot selected**: the rail shows an idle state — "Select a card on
the sheet to see its details" — rather than empty chrome. This is a new,
small piece of UI (not an existing component); everything inside an
_active_ rail is 100% existing instruments per §5.

**Rail internal structure — AMENDMENT: collapsible accordion sections,
not a flat stack.** Once a slot is selected, the rail is not seven
instruments stacked top to bottom at equal weight — it's a short
always-visible status header followed by four collapsible sections,
built from `AutofillCollapse` (`frontend/src/components/AutofillCollapse.tsx`),
the same component the classic PDF-export panel already uses for its own
settings groups (`PageSizeSettings`, `EdgeSettings`,
`CutLinesSettings`, etc. in `PDFGenerator.tsx` — see §1/§5). Reusing it
here is a restyle/relocation, not a new interaction pattern:

```
┌ RAIL ───────────────────────────────────────┐
│ ALWAYS VISIBLE (status, not settings):       │
│  • selected card's identity (name, face)     │
│  • requested-printing badge ("<SET> <NUM>",  │
│    degraded style when applicable)           │
│  • Confirm? affordance, when applicable      │
├───────────────────────────────────────────────┤
│ ▾ Choose Image           (OPEN by default)    │  ← candidate/version picker
├───────────────────────────────────────────────┤
│ ▸ Attributes             (collapsed)          │  ← attribute chips
├───────────────────────────────────────────────┤
│ ▸ Print Options          (collapsed)          │  ← per-card bleed override
├───────────────────────────────────────────────┤
│ ▸ Artist                 (collapsed)          │  ← artist line
├───────────────────────────────────────────────┤
│ ▸ Slot Actions           (collapsed)          │  ← change/duplicate/delete
└───────────────────────────────────────────────┘
```

Rationale for the always-visible/open/collapsed split: the three
always-visible items are _status_ the user needs to see the instant a
slot is selected, with no click — they answer "what is this card and is
it right," not "what do I want to change." Choose Image opens by
default because picking the correct art is the single most common
reason a slot gets selected in the first place (matches the existing
funnel's own emphasis — see `DeckbuilderConfirmAffordance`'s NO path,
which already jumps straight to the version picker). Attributes/Print
Options/Artist/Slot Actions collapse by default because they're
secondary, deliberate actions a user opens only when they specifically
need them — an accordion, not a flat stack, is what keeps the rail from
becoming a scroll-heavy wall of controls every time a slot is selected.
Each section still lives inside the rail's own single
`overflow-y: auto` scroll container (§3) — the accordion changes what's
visible by default within that container, not the container itself. Only
one behavioral nuance versus `AutofillCollapse`'s existing usage:
every other caller in this codebase treats its sections as mutually
exclusive-ish via manual `expanded` state per instance with no enforced
single-open constraint, and the rail follows that same precedent —
multiple sections can be open at once (e.g. Choose Image open while the
user also expands Attributes), each section's `expanded` boolean is
independent, matching how `PDFGenerator.tsx`'s own settings groups
already behave.

## 3. Layout per breakpoint

All measurements below assume Bootstrap 5's stock breakpoints (sm 576 /
md 768 / lg 992 / xl 1200) and the Superhero palette (body `#2B3E50`,
panel `#4E5D6C`, text `#EBEBEB`, accent `#DF691A`, `border-radius: 0`).
See the mockups (§ mockups/README.md) for pixel-accurate renders of each
of these.

### Desktop, 1920×1080 (`desktop.html`)

- Toolbar: 64px tall, full width, flat `#2B3E50` bar.
- Sheet region: remaining width minus the rail, sheet itself
  center-aligned with generous side padding, capped at a comfortable max
  render width (the sheet is a fixed mm aspect ratio scaled down — see
  `PagePreview.tsx`'s own `scale = maxWidthPx / (pageWidthMM * CSS_PX_PER_MM)` mechanism, unchanged).
- Rail: fixed **400px** (within the brief's 380–420px band), full
  toolbar-to-bottom height, `#4E5D6C` panel surface, **its own
  `overflow-y: auto` scroll container** independent of the page (the
  explicit fix for the cut-off-rail failure mode called out in the
  brief — see §1's lessons.md citation). `position: sticky; top: <toolbar height>px` at this width, and — per the sticky/z-index
  lesson — the rail's own parent carries `position: relative` **and** an
  explicit `z-index: 0` together, so the rail's necessary stacking
  context never escapes to an ancestor and never becomes
  un-hit-testable.

### Laptop, 1366×768 (`laptop.html`)

- Same three-region layout; rail narrows to **340–360px** per the
  brief (mockup uses 350px). Sheet region shrinks proportionally; at
  this width a 4×2 sheet's own scaled render is still comfortably above
  a legible per-card thumbnail size.
- Toolbar's paper/bleed/guides controls collapse into a single "Print
  Settings" popover trigger rather than staying inline (still the same
  underlying controls — see §5's mapping) — this is the one concession
  laptop width needs versus desktop's fully-inline toolbar.

### Tablet, 768–992px (`tablet.html`)

- The rail is **not** a permanent column at this width — it becomes a
  **right-side off-canvas drawer**: hidden by default, the sheet takes
  the full content width, and selecting a slot slides the drawer in
  from the right (fixed position, same 768px+ sticky/stacking-context
  rule applies to the drawer itself once open, since it's still ≥768px).
  A visible "Details" tab/handle on the right edge shows a drawer is
  available even with nothing selected, distinct from the idle-rail
  text used at desktop/laptop width (there's no room to keep an idle
  panel visibly open at this width).
- Toolbar condenses to icon-only buttons with text labels revealed on
  focus/hover; page N of M and prev/next stay fully visible (highest-
  frequency actions).

### Mobile, <768px (`mobile.html` + `mobile-rail-open.html`)

- Single column. The sheet is the only thing on screen by default,
  full width, one page at a time exactly as at every other breakpoint.
  Toolbar collapses to a compact bar: deck name (truncated), page N of
  M with prev/next arrows, and a single overflow menu for the rest of
  the print settings.
- Per the brief's "KNOWN DEVICE LESSON": **no sticky positioning at
  all** below md. The rail-as-drawer pattern used at tablet width is
  replaced by a **bottom-sheet/full overlay** that mounts in plain
  document flow (not `position: fixed`/`sticky` with a negative
  z-index escape hatch) — selecting a slot pushes this overlay in as an
  ordinary stacked view, not a floating panel, sidestepping the whole
  negative-z-index/stacking-context failure class described in §1
  entirely rather than trying to patch around it at this width.
- Inside the open rail (`mobile-rail-open.html`): every instrument from
  §5 still present, but the two-column "ring" layouts (ChipRing) fall
  back to their own already-existing single-column stack (§1), and the
  confirm-affordance's comparison pin renders **stacked above** the
  candidate rather than pinned beside it — the brief's "comparison
  stacks vertically" requirement, matching `ComparePin`'s own existing
  CSS shape (a centered block above its anchor) with no code change
  needed, only a narrower available width to render it in.
- A close/back control returns to the sheet view; the sheet's scroll
  position is preserved (still on the same page of the deck).

## 4. Interaction flows

Each flow below is the same import/select/confirm/export sequence
already live in the editor + PDF tabs today, restated as it plays out
on one page instead of two.

### 4.1 Deck-input landing — BUILT (issue #238)

Status: **built**. `DisplayPage.tsx`'s `isProjectEmpty` early return now
renders `DeckInputLanding` — the same plain `ImportText`/`ImportURL`/
`ImportXML`/`ImportCSV` components `ProjectEditor.tsx`'s `AddCardsPanel`
mounts on the classic editor's own "Add Cards" tab, reused (not forked)
in place of the old "Head to the editor" `next/link`. Items 1–3 below
are what issue #238's own "Summary of the build" scoped and what
shipped; item 4 (a degraded-style indicator on the sheet's own
thumbnail) was **not** part of that issue's scope — it's a general
sheet-display concern that applies to any imported deck regardless of
which surface it arrived through, not something specific to this
landing state, and the issue body itself never mentioned it. Left as an
open, unscoped follow-up (not silently dropped, not silently built) —
see the note after item 4 below.

1. When `isProjectEmpty` is true, render the same import components
   `ProjectEditor.tsx`'s `AddCardsPanel` already mounts today for the
   classic editor's own "Add Cards" tab — `ImportText`, `ImportURL`,
   `ImportXML`, `ImportCSV` (`frontend/src/features/import/*.tsx`) —
   inline, in place of the current "go to /editor" link. These are not
   the `Import.tsx` dropdown's `*Button` modal variants (a different
   mount, used for the persistent "Add Cards" dropdown elsewhere in the
   classic editor); they're the plain components `AddCardsPanel` embeds
   directly, each already accepting an `onImportComplete` callback prop
   for exactly this purpose (confirmed by direct read of
   `ImportText.tsx`'s own prop shape). No new import logic needed: same
   components, same `addMembers`/`convertLinesIntoSlotProjectMembers`
   pipeline, same `onImportComplete` contract these components already
   expose.
2. Each decklist line becomes a slot exactly as today
   (`projectSlice`'s `SlotProjectMembers`), best-match image
   auto-selected per the existing search-and-select behavior.
3. `onImportComplete` has nothing to switch to here — unlike
   `ProjectEditor.tsx`'s own use of it to flip `Tab.Pane`s, this page has
   only the one layout. It's wired as a no-op (or omitted entirely):
   once `addMembers` fires, `isProjectEmpty` (the same selector
   `DisplayPage.tsx` already reads) flips false, and the component
   re-renders straight into the sheet + rail layout on its own — no
   separate "now go export" step exists to skip, matching this
   section's original intent.
4. If any line's search was searched-then-retried without its printing
   filter (`degradedQueries`), the affected slot's sheet thumbnail
   carries the same degraded-style indicator the requested-printing
   badge already uses in the rail — see §5's mapping. **Not built by
   issue #238** (see this section's status line above) —
   `PagePreviewSlotContent` (`PagePreview.tsx`) has no degraded field
   today, so this remains a real gap: a degraded query's
   only visible indicator anywhere on `/display` today is the rail's own
   `RequestedPrintingBadge`, once that specific slot is selected: there's
   still no sheet-level (small-scale, always-visible) signal. Noted here
   as a follow-up, not filed as its own issue yet.

Layout note: `AddCardsPanel`'s own existing two-column split (a text
paste column beside a File-or-URL accordion column, `ProjectEditor.tsx`
lines ~46–92) is the closest existing precedent for how this rendered
inline on `/display` — reused directly (`DeckInputLanding` in
`DisplayPage.tsx`), minus `AddCardsPanel`'s own `OverflowCol` wrapper
(sized via `NavPillButtonHeight + NavbarHeight`, both editor-tab-
specific and the latter a currently-wrong hardcoded constant per issue
#250 — see that component's own comment for why this landing instead
just flows inside `Layout.tsx`'s existing scroll container rather than
computing its own forced height).

### 4.2 Slot select

1. Click/tap a card on the sheet.
2. ≥768px: the rail's content updates in place to that slot's status
   header + accordion (§2's amendment, §5), replacing whatever was shown
   before — the rail itself never closes/reopens, only its contents
   swap, matching the "own-scroll, updates by hover/select" requirement.
   Each accordion section's expanded/collapsed state resets to its
   documented default (Choose Image open, the rest collapsed) on every
   new slot selection — an open Attributes section on slot 3 does not
   stay open when the user selects slot 4; carrying per-slot section
   state across selections is unnecessary complexity for a v1, given the
   rail already re-grounds the user on a new card's identity every time
   it swaps.
3. Tablet width: the off-canvas drawer opens (if not already open) and
   shows the same content.
4. <768px: the bottom-sheet/full overlay opens over the sheet view.
5. Selecting a second slot while the rail/drawer/overlay is already open
   simply swaps its contents again — no close-then-reopen animation
   round-trip.

### 4.3 Confirm flow (printing confirmation) — SUPERSEDED by the [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision (owner-ratified, issue #271 comment, locked 2026-07-21)

Status: the Y/N `DeckbuilderConfirmAffordance` badge flow originally
specified here (below, for history — see git blame) is SUPERSEDED by the
[Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) design addendum. **`proposal-h-display-layout-spec.md`'s own
[Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) entry is the canonical statement of this flow**; this section restates
it in this doc's own interaction-flow numbering and defers to that entry
on any wording conflict between the two. No successor "4.3′" section
exists — this section is rewritten in place rather than left as dead
history, unlike §4.4 below.

1. A slot whose search named a specific printing, or whose selected
   candidate carries printing-identity data (`canonicalCard` or
   `suggestedCanonicalCard`), shows a compact **confidence element** in
   the rail's promoted identity header (§2's amendment; always-visible,
   not inside any accordion section) once that slot is selected —
   directly under the card name + `RequestedPrintingBadge`. This is
   identity information, promoted, not demoted metadata (matches the
   [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision's own placement rationale).
2. The element itself: `[set icon] SET · COLLECTOR# · <confidence read> [✗ not this printing]`. The confidence read is **a small checkmark**
   next to the set icon when the printing is human-resolved consensus
   (`canonicalCard` present), or a **numeric confidence score** when it's
   only machine-suggested (`suggestedCanonicalCard` only, no
   `canonicalCard`) — never a bare "Confirm?" Y/N badge.
3. Hovering (desktop) or tapping (touch) the set icon opens an
   `OverlayTrigger`/`Popover` pinning the Scryfall reference image for
   that printing — display-serving only, straight from Scryfall's own
   CDN, nothing stored (satisfies the governing premise and #271's own
   note).
4. **"✗ not this printing"**: one click casts a real human vote through
   the existing consensus path (`useTagVoting`, the same submission path
   `AttributeVotingPanel`/`AttributeChipPanel.tsx` already use — no new
   vote semantics), the human half of the Stage D machine-vote funnel;
   composes with the review queue (#262). Shown only when the printing
   isn't yet human-resolved (paired with the numeric-confidence state).
5. There is no positive "Y, this is right" button in this flow. Positive
   confirmation instead flows through the funnel's own implicit/support
   voting mechanics (the [implicit-vote-is-the-vote](../features/grid-selector.md#implicit-vote-is-the-vote)
   decision — see `docs/features/grid-selector.md`'s
   "art-picker FUNNEL" section): picking a candidate while ≥1 attribute
   chip is active casts implicit support votes for the tags that pick
   satisfies. There is no separate explicit "confirm this printing"
   affordance parallel to the old Y button — a resolved printing simply
   never needs confirming again.

**Placeholder note (2026-07-22 audit):** `ConfidenceElement.tsx` — the
component this flow describes — currently ships as the narrower
PLACEHOLDER cut of the [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision (SetIcon + resolved/suggested read + a disabled
"not this printing" affordance, no live Scryfall-hover popover, no real
`useTagVoting` dispatch yet); the full interactive version this section
describes lands with the unified-page bundle PR. See that component's
own module comment.

**Superseded original (kept for history, not current):**

1. A slot whose search named a specific printing but whose selected
   image isn't yet the human-resolved consensus for that printing shows
   the existing "Confirm?" badge (`DeckbuilderConfirmAffordance`) — on
   the sheet's own thumbnail at small scale, and in the rail's
   always-visible header (not inside any accordion section) once that
   slot is selected.
2. Hover/tap the badge in the header: the same `APIGetPrintingCandidates`
   lookup fires, pinning a Scryfall-sourced reference thumbnail
   (`ComparePin`) above the candidate for comparison.
3. Y: casts the same `APISubmitPrintingTag` vote as today, badge clears
   for that identifier for the rest of the session.
4. N: same "pure navigation, no vote" behavior as today — expands (or
   focuses, if already open) the **Choose Image** accordion section
   (§4.4) already scoped to this slot.

### 4.4 Printing switch (Choose Image accordion section) — SUPERSEDED

Superseded by §4.4′ below (owner directive, "SELECT VERSION SECTION,
UNIFIED SPEC" — left as-is for history rather than rewritten, since
Step 2 PR 2a already shipped the embedded (non-modal) picker this
section originally called for; §4.4′ is the actual current spec).

1. From the rail's Slot Actions section (or directly from the
   requested-printing badge's N path), open — or focus, if already
   open — the **Choose Image** accordion section.
2. Content is the existing `GridSelectorModal`'s result grid
   (`CardResultSet`) plus its filters (`GridSelectorFilters`, collapsed
   by default below `sm`) and `JumpToVersion` — organized as a
   thumbnail grid identified by set code + collector number, matching
   the existing modal's own labeling convention already (no new
   identification scheme to design).
3. On ≥768px this renders **inside the rail's Choose Image section
   body** (not a separate modal stacked on top of the rail) — the
   section already has the vertical space and the rail's own scroll
   container; a second overlapping modal-over-drawer would be the exact
   "gets cut off, no independent scroll" failure the brief calls out to
   avoid, just recreated one layer up. On <768px, given the bottom-sheet
   already occupies the full viewport, the picker simply becomes that
   section's content for the duration of the pick (still no second
   stacked overlay).
4. Selecting an image dispatches the existing `setSelectedImages`
   action; the sheet's thumbnail for that slot updates immediately
   (same Redux state, same `PagePreview` render path — no new plumbing).

### 4.4′ Select Version section — unified spec (owner directive)

Status: **BUILT** (issue #167, `SelectVersionResults.tsx` — see
`docs/features/grid-selector.md`'s own "Select Version section" entry for
the concrete component/test breakdown and the deviations/open items that
build surfaced). Defines the left panel's Select Version section (2a's
`GridSelectorResults` "embedded" variant, which the left-panel-
unification amendment already established as the ONE surface for this
— no modal, ever, on `/display`; see that amendment's own text) — the
build replaced that flat variant's own results rendering with the
grouped display this section describes; `GridSelectorModal.tsx`'s
classic modal (used everywhere else in the app) is untouched.

**Purpose.** The picker maximizes both usefulness (find the right art
fast) and 1-click verification potential (every gap in the catalog's
knowledge is a visible, tappable confirmation opportunity). Browsing
and contributing are the same surface, not two separate flows bolted
together.

**Structure — three ordered groups:**

1. **Canonical, grouped by printing.** One representative per distinct
   printing — the highest-DPI copy in that printing's cluster. Resolved
   printings first, then machine-suggested, visually distinguished per
   the shared badge language (verified vs. suggested never blurred —
   same principle `RequestedPrintingBadge.tsx`'s degraded-style split
   already establishes). The slot's own REQUESTED printing sorts first
   with its badge. Expanding a printing reveals its other copies ("+N
   more of this printing").
2. **Non-canonical / likely-custom.** Cards with resolved custom-art /
   altered-frame / ai-art tags, sub-grouped by highest-confidence
   high-priority tags (frame type first), same
   one-representative-then-rest pattern as group 1.
3. **Unknown.** No printing data, no classifying tags — the honest
   residue, last.

**Verification woven in — three moments, one principle (every vote is
deliberate, none silent):**

- **(a) Suggested-printing Confirm.** Suggested-printing
  representatives carry the shared Confirm affordance — the same
  `DeckbuilderConfirmAffordance.tsx` component `CardSlot.tsx`'s editor
  slots already mount, same votes, same API `/whatsthat` itself uses.
  Never required, never blocking. (2026-07-22 audit note: the
  cross-reference this bullet used to make to "the rail header (2b)" is
  stale — that rail-header instance is superseded by the
  [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision/§4.3's
  confidence element; this grid-level badge is a separate mount, not the
  rail header one, and is unaffected by that supersession.)
- **(b) Art-as-filter.** Selecting/focusing any card offers "more like
  this" — filters the section to cards sharing its resolved tags
  (frame, border, fullart). One tap on/off, state visible as chips.
  This is filtering against `Card.tags` (already resolved-only — see
  Data dependencies below), NOT a new vote-casting UI: it reuses
  `attributeChips.ts`'s existing taxonomy/matching helpers
  (`ALL_ATTRIBUTE_CHIPS`, `filterCandidatesByChipStates`) as the shared
  tag vocabulary, rendered as a plain filter-chip bar — NOT a mount of
  `AttributeChipPanel.tsx`'s full vote-casting ring, which is a
  single-card-focus voting UI built for the question feed's different
  context and the wrong shape for filtering a whole result grid.
- **(c) Filtered-selection confirm moment.** When a user selects a card
  while attribute filters are active AND the matching tag(s) are
  suggested rather than resolved, selection succeeds normally and a
  one-tap inline chip follows (not a modal): "Looks retro-frame? ✓" —
  one tap casts a real `CardTagVote` via the existing
  `APISubmitTagVote` (`store/api.ts`, already used by
  `AttributeChipPanel.tsx` — same call, new small caller, not a new
  endpoint). Ignoring costs nothing, casts nothing. Resolved tags → no
  prompt, ever. Once per card per session (dismissal/cast state kept in
  local component state, not persisted — matches the "never repeats
  within a session" framing the owner used for the separate post-export
  contribution toast, task #31 — **now built, issue #166**, a
  `sessionStorage`-backed flag rather than local component state since it
  needs to survive this tab's own reloads; see
  `docs/features/printing-tags.md`'s own entry — though these remain two
  independent pieces of session-scoped UI state, not the same mechanism).
  NO vote
  is ever cast from selection alone — zero-telemetry and the
  deliberate-vote principle both hold, same as every other funnel this
  fork has built (`docs/features/printing-tags.md`).

**Data dependencies — audited against what `Card.serialise()`
(`MPCAutofill/cardpicker/models.py`) / `Card.json`
(`schemas/schemas/Card.json`) already carries, vs. what group 1/2's
grouping and moment (c) actually need:**

| Need                                                                                                                             | Already available?                       | Detail                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Resolved attribute tags (Full Art, Borderless, Old/Modern Border, etc.) for group 2's sub-grouping and moment (b)'s filter chips | **Yes, no change needed.**               | `Card.tags: string[]` already contains ONLY consensus-resolved tags — `tag_consensus.resolve_and_persist_tag_votes` explicitly merges a resolved APPLY into `card.tags` and explicitly does NOT write contested or pending-approval tags there. `attributeChips.ts`'s `ALL_ATTRIBUTE_CHIPS` tag names already match this taxonomy 1:1 (`cardpicker.attribute_tags.ATTRIBUTE_TAGS`) — the frontend can group/filter on `tags.includes(chip.tagName)` today, client-side, with zero backend change.                                                                                                                                                                                                                                                                     |
| Machine-suggested (not yet community-resolved) printing, for group 1's "then machine-suggested" ordering                         | **Yes — shipped, PR #195 (issue #184).** | `Card.serialise(include_suggested_printing=True)` now populates `SerialisedCard.suggestedCanonicalCard` from the printing named by a machine-cast (`VoteSource.DEDUCTION`/`OCR`) `CardPrintingTag` vote — mirroring `question_feed.py`'s `_confirm_suggestion_item` `ai_vote` lookup exactly, not `get_ranked_printing_candidates()` (that ranking search was judged too expensive to run per-card across a bulk result set; exposing an already-cast vote is free by comparison). Only populated while `printingTagStatus != RESOLVED`. Attached with zero extra queries per card via `suggested_printing_votes_prefetch()` on the two bulk endpoints (`2/cards/`, `2/explore/`). See [[../features/printing-tags.md]]'s "Card payload" entry for the full contract. |
| Suggested (unresolved/contested) attribute tags, for moment (c)'s "is the matching tag resolved or suggested" check              | **Yes — shipped, PR #195 (issue #184).** | `SerialisedCard.tagVoteStatuses: Record<string, "resolved" \| "suggested">` is now always populated (zero extra query cost — it's the already-loaded `tag_vote_statuses` JSONField), collapsing the 5-way DB status: `resolved_apply`/`resolved_reject` → `"resolved"`, `contested`/`unresolved` → `"suggested"`. `pending_approval` tags are excluded from the object entirely, same reason they're excluded from `Card.tags` today. See [[../features/printing-tags.md]]'s "Card payload" entry.                                                                                                                                                                                                                                                                    |

**Serializer-field ask — SHIPPED, PR #195 (issue #184), merged 2026-07-19,
ahead of this section's own build (issue #167):**

1. `suggestedCanonicalCard: CanonicalCard | null` on `Card`/`SerialisedCard`,
   opt-in via `Card.serialise(include_suggested_printing: bool = False)`.
   The confidence/score question this section originally left open was
   resolved by not adding one — the field exposes an already-cast machine
   vote rather than a freshly computed ranking, so there's no separate
   score to carry. The cost question was resolved toward precomputing:
   inline `get_ranked_printing_candidates()` per card was judged too
   expensive across a bulk result set, so the field reads an existing vote
   instead (prefetched, one extra query per page, not per card).
2. `tagVoteStatuses: Record<string, "resolved" | "suggested">` on
   `Card`/`SerialisedCard`, always populated (no opt-in flag needed — it's
   a zero-cost read of an already-loaded field). `pending_approval` tags
   are excluded entirely, per the constraint above.

Both landed as additive fields on the existing serializer, no schema
migration or new endpoint, exactly as scoped — not a client-side
workaround (e.g. fetching `printingCandidates` per-card across a whole
result set, which would multiply request volume against an endpoint
designed for a single focused slot, not bulk use). Full contract:
[[../features/printing-tags.md]]'s "Card payload" entry;
`MPCAutofill/cardpicker/tests/test_card_serialise.py` for the test
coverage.

**Component breakdown (build, once un-HOLD'd):**

| Component                                                         | New or reused | Notes                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Group/sub-group sectioning + "+N more of this printing" expansion | New           | Pure client-side grouping over the existing `GridSelectorResults` candidate list, keyed on `canonicalCard`/`suggestedCanonicalCard` once available; the "+N more" expansion is local component state, no new Redux slice                                                                                                                                                                                   |
| Suggested-printing Confirm badge (moment a)                       | Reused        | `DeckbuilderConfirmAffordance.tsx`, unchanged — proven inline in `CardSlot.tsx`'s editor slots (2026-07-22 audit: no longer cross-referenced to "the rail header (2b)" — that rail-header mount is superseded by the [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision/§4.3's confidence element; this grid-level badge is a separate, unaffected mount) |
| Art-as-filter chip bar (moment b)                                 | New, thin     | A plain filter-chip row (not `AttributeChipPanel.tsx`'s ring) built on `attributeChips.ts`'s existing `ALL_ATTRIBUTE_CHIPS`/`filterCandidatesByChipStates`/`useTagDisplayName` — filters against `card.tags`, no vote cast by filtering alone                                                                                                                                                              |
| Filtered-selection confirm chip (moment c)                        | New, thin     | Calls the existing `APISubmitTagVote` (same function `AttributeChipPanel.tsx` already calls); gated on the new `tagVoteStatuses` field being `"suggested"` for the active filter tag(s) on the just-selected card                                                                                                                                                                                          |

### 4.5 Export

1. "Generate PDF" in the top toolbar is the existing
   `PDFGenerator.tsx` `downloadPDF`/`useDownloadPDF` flow, operating on
   the exact `projectMembers`/settings state the sheet has been showing
   throughout — there is no separate "now configure the real export"
   screen to move to first, because the settings the toolbar exposes
   already are the real export's settings (today's `PageSizeSettings`/
   `EdgeSettings`/`CutLinesSettings`/etc., just relocated — see §5).
2. The existing image-fetch-failure confirm dialog
   (`confirmDespiteImageFailures`) and Google Drive save path
   (`saveToDrivePDF`) are unchanged.
3. Because the sheet the user has been looking at the entire session
   already is the WYSIWYG "fast" preview render path
   (`PagePreview`/`computeLayout`), there is no separate moment where a
   different, more-accurate render suddenly reveals a surprise — the
   existing "Switch to exact PDF preview" toggle (`PDFGenerator.tsx`
   line ~1330) remains available (moved into the toolbar) for anyone who
   wants the heavier pdf.js-rendered canvas confirmation before
   generating, but it's no longer the _only_ preview, as it effectively
   is today once a user leaves the fast-preview default.

## 5. Component mapping table

| Existing component / state                                                                                                                                                                                                                                                      | New location on this page                                                                                                                             | Change needed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PagePreview.tsx` + `layout.ts`'s `computeLayout()`                                                                                                                                                                                                                             | The sheet region, main surface                                                                                                                        | None — reused as-is, still fed small/mid-tier thumbnail URLs already resident in memory                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `CardSlot.tsx` (minus its own grid-selector modal chrome)                                                                                                                                                                                                                       | Individual sheet slots                                                                                                                                | Restyle only: slot dimensions/positioning already come from `PagePreview`'s own absolute-mm layout, not `CardSlot`'s current grid-flow CSS; the click target and per-slot Redux wiring (`selectedImage`, `toggleMemberSelection`, etc.) carry over unchanged                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `AutofillCollapse.tsx`                                                                                                                                                                                                                                                          | Rail's section chrome — one instance per accordion section (Choose Image / Attributes / Print Options / Artist / Slot Actions)                        | None — same component `PDFGenerator.tsx`'s own settings groups already use (`PageSizeSettings`, `EdgeSettings`, etc.); each rail section is one more caller with its own local `expanded` boolean, defaults per §2's amendment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `GridSelectorModal.tsx` + `GridSelectorFilters.tsx` + `JumpToVersion.tsx`                                                                                                                                                                                                       | Rail's **Choose Image** accordion section (open by default), §4.4                                                                                     | Props-level: rendered inline inside `AutofillCollapse`'s body instead of inside a `react-bootstrap` `Modal`; internal filter/search/debounce logic unchanged                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `ConfidenceElement.tsx` (net-new — supersedes the `DeckbuilderConfirmAffordance.tsx` row this table used to carry here, per the [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision/§4.3, owner-ratified 2026-07-21)            | Rail's **always-visible promoted identity header** (outside the accordion — status, not a setting)                                                    | **New UI** — set icon + checkmark/numeric-confidence read + Scryfall-hover `Popover` + `✗ not this printing` casting a `useTagVoting` vote (the [Printing-Confidence Funnel](proposal-h-display-layout-spec.md#printing-confidence-funnel) decision). 2026-07-22 audit: `ConfidenceElement.tsx` currently ships as the narrower PLACEHOLDER cut (no live hover popover, no real vote dispatch yet) — the full interactive version this row describes lands with the unified-page bundle PR; see that component's own module comment. `DeckbuilderConfirmAffordance.tsx` itself is unchanged and still mounted elsewhere (`CardSlot.tsx`'s editor slots, the Select Version grid's moment (a) badge) — only its former rail-header mount is what the Printing-Confidence Funnel decision replaces |
| `AttributeChipPanel.tsx` / `attributeChips.ts`                                                                                                                                                                                                                                  | Rail's **Attributes** accordion section (collapsed by default)                                                                                        | Props-level: currently composed around a `cardSlot` node for the question-feed's ring layout (`CardArea`); the rail mounts the same `ChipRing`/`TopArea`/`LeftArea`/`RightArea` styled parts directly in a vertical arrangement inside the section body, rather than around a centered card image — the tri-state cycling and vote-submission logic is unchanged                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Requested-printing badge (currently rendered inline per search-query display logic)                                                                                                                                                                                             | Rail's **always-visible header** (outside the accordion — status, not a setting)                                                                      | Restyle + a new degraded-state style variant keyed off `degradedQueries` (existing field, not new data)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Manual bleed override (`ManualOverride`/`resolveBleedPlan` in `bleedNormalize.ts`)                                                                                                                                                                                              | Rail's **Print Options** accordion section (collapsed by default)                                                                                     | **New UI** — the algorithm exists but the control and its persistence are explicitly not-yet-built per Proposal B's own status doc (§1); this design assigns it a rail section but its build is Proposal B PR-2's scope, not this proposal's                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Artist line + support link                                                                                                                                                                                                                                                      | Rail's **Artist** accordion section (collapsed by default)                                                                                            | **New UI** — no existing "Art by `<Name>`" line or outbound support link was found in the current codebase (see §1); artist name itself is already available wherever `canonicalCard`/candidate metadata carries it (e.g. `ArtistVotePicker.tsx`'s own artist-name handling) — this is new presentational wiring over existing data, not a new data source                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `CardSlotMenuActions.ts` + `CardSlotContextMenu.tsx` (the shared 3-dot/right-click action list)                                                                                                                                                                                 | Rail's **Slot Actions** accordion section (collapsed by default)                                                                                      | None — same action list, rendered as a plain action list inside the section body instead of a dropdown/context-menu overlay                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `PDFGenerator.tsx`'s settings sub-components (`PageSizeSettings`, `CardSelectionSettings`, `CardQualitySettings`, `EdgeSettings`, `CutLinesSettings`, `SpacingAndMarginsSettings`, `SCMSettings`)                                                                               | Top toolbar (popover-collapsed below `lg`)                                                                                                            | Restyle/relocate only — same state, same `PDFProps` shape. (2026-07-20 audit: `CardQualitySettings` here is image export DPI/JPG quality only — confirmed a genuinely distinct component from `FinishSettings.tsx` below, not a naming variant of it.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `FinishSettings.tsx` (cardstock select + foil toggle, `finishSettingsSlice`) — audit finding, 2026-07-20                                                                                                                                                                        | Top toolbar (same deck-level reasoning as the `PDFGenerator.tsx` settings row above)                                                                  | **New UI, deliberately not one of the four tracked gaps/issues below** — zero mapping anywhere in this doc prior to this audit pass; a corrective row only, its own toolbar treatment left to a future pass — see Open decision 7                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `downloadPDF`/`saveToDrivePDF`/`useDownloadPDF`/`useSaveToDrivePDF`                                                                                                                                                                                                             | Top toolbar's Generate PDF / Save to Drive buttons                                                                                                    | None                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Page pagination (today implicit in `PDFGenerator`'s `fastPreviewFirstPage`-only fast preview)                                                                                                                                                                                   | Top toolbar's "Page N of M ◀▶"                                                                                                                        | **New** — today's fast preview only ever renders the _first_ page; this proposal's sheet needs real pagination across every page `CardSelectionModeToPaginator` produces, not just page 1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `SavedDeckPanel.tsx` (Proposal G, `docs/features/saved-decks.md`) — reverse breadcrumb + Save button                                                                                                                                                                            | Top toolbar (doubles as this row's own "deck name" slot, per §2's IA — that slot went unbuilt here since Proposal G landed after this doc's own pass) | Props-level only (issue #165, "Proposal G save integration"): the component gained an optional `className` prop so it can drop its original vertical-stack `pt-2` and sit as one more item in the toolbar's horizontal flex-wrap row; renders nothing for an anonymous session, same as its `ProjectEditor.tsx` mount                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `SearchSettings.tsx` + its sub-panels (`SearchTypeSettings.tsx`, `FilterSettings.tsx`, `SourceSettings.tsx`) — audit finding, 2026-07-20, issue #239 — **BUILT**                                                                                                                | Top toolbar (new button, alongside the paper/bleed/guides controls)                                                                                   | Relocate only — same `Modal`, same `searchSettingsSlice` read/write, same `setLocalStorageSearchSettings` persistence path; the toolbar gains one more trigger button, no new state                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `CommonCardback.tsx` + its own `GridSelectorModal` instance + `projectSlice`'s `setSelectedCardback` — audit finding, 2026-07-20, issue #240 — **BUILT**                                                                                                                        | Top toolbar (new "Cardback" button opening the same self-contained modal `CommonCardback.tsx` already owns)                                           | Relocate only — reuses `MemoizedCommonCardbackGridSelector`'s existing `GridSelectorModal` verbatim, via a new `CardbackToolbarButton` export (`CommonCardback.tsx`) rather than mounting `CommonCardback` itself — that component's swatch/prev-next `CardFooter` chrome belongs to the editor's right panel, not a toolbar button. NOT the same "no modal, ever" exception §4.4′ carves out for the per-slot Choose Image picker — that ban is specifically about a second modal stacking over an already-open rail/drawer; a standalone project-wide cardback picker triggered directly from the toolbar has no such stacking hazard, so its existing modal is left as-is                                                                                                                     |
| `ExportXML.tsx` (`useDownloadXML`), `ExportImages.tsx` (`useDoImageDownload`), `ExportDecklist.tsx` (`useDownloadDecklist`) — audit finding, 2026-07-20, issue #241 — **BUILT** (`ExportPDF.tsx` itself excluded — already covered by the Generate PDF/Save-to-Drive row above) | Top toolbar, composed into an "Export ▾" dropdown alongside the existing Generate PDF / Save to Drive buttons                                         | Relocate only — same `Dropdown.Item`s, same download hooks, same `selectIsProjectEmpty`/`selectAnyImagesDownloadable` gating, via a new `DisplayExportMenu.tsx` composing the three unmodified items; `ExportPDF.tsx`'s own `Dropdown.Item` is deliberately NOT included, since this page's Generate PDF already reuses `useDownloadPDF` directly rather than opening the classic `PDFGenerator` modal `ExportPDF.tsx` dispatches to                                                                                                                                                                                                                                                                                                                                                             |

## 6. Migration/sequencing

Small PRs, existing editor left fully intact until the last step:

1. **New route behind a flag** — add the unified page at a new route
   (e.g. `/display`, name TBD — see Open Decisions), gated by a build/
   feature flag so it ships dark. No changes to `/editor` or the PDF
   tab in this PR; this PR is purely the new page's shell (toolbar +
   sheet, real pagination across the whole deck) reusing `PagePreview`/
   `computeLayout` as-is.
2. **Instrument parity** — land the rail, one instrument group at a
   time, each its own PR: candidate/version picker inline in the rail →
   confirm affordance → attribute chips → requested-printing badge →
   slot actions → artist line (new UI, per §5) → bleed override (blocked
   on Proposal B PR-2 actually landing the control + `projectSlice`
   persistence it depends on — sequenced after, not blocking this
   proposal's other instruments). Each PR is reviewable independently
   because each instrument is a self-contained existing component.
3. **Deck-input landing parity (issue #238) — DONE.** The most urgent of
   the four gaps a 2026-07-20 feature-parity audit against `/editor`
   found (see the top summary and §4.1): mounts `ImportText`/`ImportURL`/
   `ImportXML`/`ImportCSV` inline on `/display` when `isProjectEmpty` is
   true, replacing the old "go to /editor" link, per §4.1's flow (items
   1–3; item 4's sheet-level degraded indicator was out of this issue's
   own scope — see §4.1's status line).
4. **Toolbar instrument parity (issues #239, #240, #241) — DONE, queue
   complete.** The other three findings from the same audit, each its own
   small PR since each is a self-contained existing component being
   relocated, not rebuilt: a Search Settings toolbar button
   (`SearchSettings.tsx`, unchanged modal, issue #239 — **DONE**, mounted
   in `DisplayPage.tsx`'s toolbar alongside the paper/bleed/guides
   controls); a Cardback toolbar button (`CommonCardback.tsx`'s new
   `CardbackToolbarButton` export, unchanged modal — see §5's note on why
   this one keeps its own modal rather than following the Choose Image
   "no modal" exception, issue #240 — **DONE**, mounted in
   `DisplayPage.tsx`'s toolbar); and an Export ▾ dropdown
   (`DisplayExportMenu.tsx`) composing `ExportXML`/`ExportImages`/
   `ExportDecklist` alongside the existing Generate PDF / Save to Drive
   buttons (issue #241 — **DONE**, mounted in `DisplayPage.tsx`'s
   toolbar). See §5 for the full component mapping. This was the last
   item in the toolbar-parity queue — every finding from the 2026-07-20
   feature-parity audit against `/editor` has now shipped as feature
   code.
5. **Switchover** — once the flag-gated page has full instrument
   parity with the editor + PDF tab combined (steps 2–4 above), flip the
   default nav entry point to the new page; keep `/editor` and the PDF tab
   reachable behind a "classic view" link for one deprecation window.
6. **Retire old routes** — remove `/editor`'s grid-only view and the
   standalone PDF-generator tab once usage data / owner sign-off says
   it's safe; delete the flag.

This sequencing means nothing in this proposal blocks on nothing else
in it except step 6 on step 5, and the bleed-override rail slot on
Proposal B's own separate PR-2 — every other instrument (including the
new steps 3 and 4 above) is independently shippable in any order once
the shell from step 1 exists.

## Open decisions

1. **New route's URL/name.** `/display` is a placeholder in this doc;
   candidates include `/print`, `/sheet`, `/deck` — needs an owner call,
   ideally one that reads naturally as replacing both "Editor" and
   "Print!" in the nav.
2. **Toolbar popover threshold.** This doc collapses the full inline
   toolbar to a "Print Settings" popover somewhere between laptop
   (1366) and tablet (992) width — the exact breakpoint (`lg`? a custom
   value?) isn't picked; the laptop mockup shows the collapsed state,
   the desktop mockup shows the inline state, nothing shows the
   transition point itself.
3. **Tablet drawer default state on first visit.** Should the rail
   drawer auto-open once on landing (so a first-time tablet user
   discovers it exists) or always start closed with only the edge
   handle as discovery? No usage data exists yet either way.
4. **Multi-select interaction on the sheet.** The existing editor grid
   supports multi-slot selection (shift-click, double-click-to-align,
   `bulkAlignMemberSelection`) for bulk operations. This doc's flows
   (§4) only describe single-slot select → rail. Whether/how bulk
   selection maps onto a sheet-of-8-cards-per-page (versus the editor's
   full-deck-at-once grid) is unresolved — bulk-editing across page
   boundaries in particular has no obvious answer yet.
5. **Idle-rail vs. drawer-handle text**, exact copy — "Select a card on
   the sheet to see its details" (desktop/laptop idle state) and the
   tablet edge-handle label are placeholder copy in the mockups, not
   reviewed strings.
6. **Sheet zoom/pan for small-card legibility.** At laptop width with a
   340px rail, a 4×2 sheet's individual card renders are smaller than
   today's editor grid cards. Whether the sheet needs its own zoom
   control (independent of the browser's own zoom) is unresolved — noted
   as a possible follow-up, not designed here.
7. **`FinishSettings.tsx` (cardstock + foil) scoping.** A 2026-07-20
   audit confirmed this is a genuinely distinct component from
   `CardQualitySettings` (§5) — not a naming collision — and that it has
   zero mapping anywhere in this doc. Deliberately not scoped as one of
   the four tracked gaps/issues (see §5's new row); needs a future pass
   to decide its toolbar treatment before it's built.
8. **Adding more cards to a non-empty `/display` project.** Issue #238's
   fix (§4.1) only covers the empty-project landing case. `/editor`'s
   right panel keeps its `Import` dropdown mounted permanently, so more
   cards can be added at any time; `/display` has no equivalent toolbar
   affordance once a project is non-empty. Real gap for the "FULL
   feature parity" goal, but outside issue #238's own scope — noted here,
   not designed or filed as its own issue yet.
