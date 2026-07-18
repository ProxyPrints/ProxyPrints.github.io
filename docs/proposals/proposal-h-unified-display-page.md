As of: 2026-07-18
What this is: Proposal H — survey + design + static HTML mockups for a
single unified display page that replaces both the "Choose Art" grid
editor and the separate PDF-preview/export step with one page that IS
the live print-sheet preview, with a persistent card-details rail beside
it. **HOLD — zero feature code in this pass.** Design doc + mockups only,
per the owner-approved brief.

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
  *UI* and its persistence are explicitly listed as **not yet built**
  ("Shipped vs. not yet built," items 1–3) — only the algorithm exists
  today. The doc also already records the owner's decision that, once
  built, persistence goes to **`projectSlice`** (real project state),
  *not* `localStorage` — the brief's assumption of a localStorage-keyed
  map is superseded by that decision. This design treats the bleed
  override control as a rail instrument whose backing store Proposal B
  PR-2 will supply in `projectSlice`, not a new mechanism of its own —
  see §5 and §6.
- `frontend/src/common/schema_types.ts` — confirms `degradedQueries:
  string[]` on `EditorSearchResponse` (a search-server-level "this printing
  filter found nothing, retried unfiltered" list), used for the requested-
  printing badge's degraded styling.
- `docs/lessons.md`'s sticky/z-index entry — the concrete mechanism
  behind the brief's "own stacking context" requirement: `position:
  sticky` alone does *not* establish a stacking context for a
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
  **`alex-taxiera/proxy-print`** (MIT) — reusable, generically-described
  patterns, used here as: (a) a three-region page anatomy (deck input,
  a live paginated print-sheet grid as the visual center, a settings
  panel) rather than a wizard of separate steps; (b) grouping per-card
  controls behind a single dedicated interaction point per card, rather
  than scattering them across the grid; (c) keeping global print/export
  settings in one panel separate from per-card controls. No code,
  markup, or copy was copied from either project — pattern shapes only,
  attributed here per their MIT license.

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
true of the *whole export* (page N of M, paper size, bleed edge, guides,
Generate PDF/Save to Drive) lives in the toolbar. Anything that is true
of *one selected slot* (candidate art, confirm affordance, attribute
chips, requested-printing badge, bleed override, artist line, slot
actions) lives in the rail. Nothing straddles both — this is the same
split the brief specifies, and it maps cleanly onto existing state:
toolbar controls are exactly `PDFGenerator.tsx`'s current settings
panel (§1); rail controls are exactly the per-`CardSlot` instrument set
that already exists scattered across the editor grid today.

**No slot selected**: the rail shows an idle state — "Select a card on
the sheet to see its details" — rather than empty chrome. This is a new,
small piece of UI (not an existing component); everything inside an
*active* rail is 100% existing instruments per §5.

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
always-visible items are *status* the user needs to see the instant a
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
  `PagePreview.tsx`'s own `scale = maxWidthPx / (pageWidthMM *
  CSS_PX_PER_MM)` mechanism, unchanged).
- Rail: fixed **400px** (within the brief's 380–420px band), full
  toolbar-to-bottom height, `#4E5D6C` panel surface, **its own
  `overflow-y: auto` scroll container** independent of the page (the
  explicit fix for the cut-off-rail failure mode called out in the
  brief — see §1's lessons.md citation). `position: sticky; top:
  <toolbar height>px` at this width, and — per the sticky/z-index
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

### 4.1 Deck-input landing

1. User pastes/imports a decklist (unchanged: existing paste/CSV/XML/
   URL import surfaces, `features/import/*`).
2. Each decklist line becomes a slot exactly as today
   (`projectSlice`'s `SlotProjectMembers`), best-match image
   auto-selected per the existing search-and-select behavior.
3. Instead of landing on the editor grid, the user lands directly on
   this page: sheet page 1 of the new deck renders immediately, showing
   real thumbnail art already selected per slot — no separate
   "now go export" step exists to skip.
4. If any line's search was searched-then-retried without its printing
   filter (`degradedQueries`), the affected slot's sheet thumbnail
   carries the same degraded-style indicator the requested-printing
   badge already uses in the rail — see §5's mapping.

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

### 4.3 Confirm flow (printing confirmation)

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

### 4.4 Printing switch (Choose Image accordion section)

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
   generating, but it's no longer the *only* preview, as it effectively
   is today once a user leaves the fast-preview default.

## 5. Component mapping table

| Existing component / state | New location on this page | Change needed |
| --- | --- | --- |
| `PagePreview.tsx` + `layout.ts`'s `computeLayout()` | The sheet region, main surface | None — reused as-is, still fed small/mid-tier thumbnail URLs already resident in memory |
| `CardSlot.tsx` (minus its own grid-selector modal chrome) | Individual sheet slots | Restyle only: slot dimensions/positioning already come from `PagePreview`'s own absolute-mm layout, not `CardSlot`'s current grid-flow CSS; the click target and per-slot Redux wiring (`selectedImage`, `toggleMemberSelection`, etc.) carry over unchanged |
| `AutofillCollapse.tsx` | Rail's section chrome — one instance per accordion section (Choose Image / Attributes / Print Options / Artist / Slot Actions) | None — same component `PDFGenerator.tsx`'s own settings groups already use (`PageSizeSettings`, `EdgeSettings`, etc.); each rail section is one more caller with its own local `expanded` boolean, defaults per §2's amendment |
| `GridSelectorModal.tsx` + `GridSelectorFilters.tsx` + `JumpToVersion.tsx` | Rail's **Choose Image** accordion section (open by default), §4.4 | Props-level: rendered inline inside `AutofillCollapse`'s body instead of inside a `react-bootstrap` `Modal`; internal filter/search/debounce logic unchanged |
| `DeckbuilderConfirmAffordance.tsx` | Rail's **always-visible header** (outside the accordion — status, not a setting) | None — same component, mounted once for the selected slot instead of once per visible grid slot |
| `AttributeChipPanel.tsx` / `attributeChips.ts` | Rail's **Attributes** accordion section (collapsed by default) | Props-level: currently composed around a `cardSlot` node for the question-feed's ring layout (`CardArea`); the rail mounts the same `ChipRing`/`TopArea`/`LeftArea`/`RightArea` styled parts directly in a vertical arrangement inside the section body, rather than around a centered card image — the tri-state cycling and vote-submission logic is unchanged |
| Requested-printing badge (currently rendered inline per search-query display logic) | Rail's **always-visible header** (outside the accordion — status, not a setting) | Restyle + a new degraded-state style variant keyed off `degradedQueries` (existing field, not new data) |
| Manual bleed override (`ManualOverride`/`resolveBleedPlan` in `bleedNormalize.ts`) | Rail's **Print Options** accordion section (collapsed by default) | **New UI** — the algorithm exists but the control and its persistence are explicitly not-yet-built per Proposal B's own status doc (§1); this design assigns it a rail section but its build is Proposal B PR-2's scope, not this proposal's |
| Artist line + support link | Rail's **Artist** accordion section (collapsed by default) | **New UI** — no existing "Art by `<Name>`" line or outbound support link was found in the current codebase (see §1); artist name itself is already available wherever `canonicalCard`/candidate metadata carries it (e.g. `ArtistVotePicker.tsx`'s own artist-name handling) — this is new presentational wiring over existing data, not a new data source |
| `CardSlotMenuActions.ts` + `CardSlotContextMenu.tsx` (the shared 3-dot/right-click action list) | Rail's **Slot Actions** accordion section (collapsed by default) | None — same action list, rendered as a plain action list inside the section body instead of a dropdown/context-menu overlay |
| `PDFGenerator.tsx`'s settings sub-components (`PageSizeSettings`, `CardSelectionSettings`, `CardQualitySettings`, `EdgeSettings`, `CutLinesSettings`, `SpacingAndMarginsSettings`, `SCMSettings`) | Top toolbar (popover-collapsed below `lg`) | Restyle/relocate only — same state, same `PDFProps` shape |
| `downloadPDF`/`saveToDrivePDF`/`useDownloadPDF`/`useSaveToDrivePDF` | Top toolbar's Generate PDF / Save to Drive buttons | None |
| Page pagination (today implicit in `PDFGenerator`'s `fastPreviewFirstPage`-only fast preview) | Top toolbar's "Page N of M ◀▶" | **New** — today's fast preview only ever renders the *first* page; this proposal's sheet needs real pagination across every page `CardSelectionModeToPaginator` produces, not just page 1 |

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
3. **Switchover** — once the flag-gated page has full instrument
   parity with the editor + PDF tab combined, flip the default nav
   entry point to the new page; keep `/editor` and the PDF tab reachable
   behind a "classic view" link for one deprecation window.
4. **Retire old routes** — remove `/editor`'s grid-only view and the
   standalone PDF-generator tab once usage data / owner sign-off says
   it's safe; delete the flag.

This sequencing means nothing in this proposal blocks on nothing else
in it except step 4 on step 3, and the bleed-override rail slot on
Proposal B's own separate PR-2 — every other instrument is independently
shippable in any order once the shell from step 1 exists.

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
