# SPEC — `/editor` design repass (rails carry the work)

**STATUS: PROPOSAL, not ratified.** Companion mockup:
[`editor-repass-mockup.html`](editor-repass-mockup.html) (same directory;
self-contained, no CDN, open via `file://`; the top demo strip forces
Desktop / Tablet / Phone at any window width via a transform-scaled frame, so
the whole composition is reviewable on a phone).

Design target: `frontend/src/features/display/DisplayPage.tsx` (route
`frontend/src/pages/editor.tsx`) and the components it composes. No source
changed by this round — spec + mockup only.

Inherited on top of, and composing with, the four prior `/editor` rounds
([`rail-delegacy`](../rail-delegacy/SPEC-rail-delegacy.md),
[`editor-polish`](../editor-polish/SPEC-editor-polish.md),
[`cardback-pdfwait`](../cardback-pdfwait/SPEC-cardback-pdfwait.md), and the
left-rail round written up in
[`docs/features/display-left-rail.md`](../../../features/display-left-rail.md)),
under the living layout spec
[`proposal-h-display-layout-spec.md`](../../proposal-h-display-layout-spec.md)
and the ratified art-picker funnel
[`docs/reference/funnel-spec.md`](../../../reference/funnel-spec.md).

Every colour, radius and spacing value below is a token from
[`frontend/src/styles/_theme-tokens.scss`](../../../../frontend/src/styles/_theme-tokens.scss)
(Tokyo-11). No new palette values are introduced.

---

## §0. The organising claim

`/editor` divides into three regions with three jobs: the left rail chooses
an image, the centre **is** the print artifact, the right rail configures the
print. A control belongs to the region whose job it serves, and it belongs
_in_ that region — visible beside the thing it changes — rather than behind a
button that summons it over the thing it changes.

Measured against that claim, the page has two systematic faults, and most of
the nine reported problems are one or the other:

1. **The left rail is not primarily an image surface.** Its art picker is the
   fifth block down; the tiles it draws are 72–112px; the asset behind each
   tile is 800×800. The surface whose entire job is "look at art and pick
   some" spends its first screen on metadata and its pixel budget on assets it
   throws away. (Items R1, R2, R3.)
2. **Settings are scattered across surfaces that don't own them.** Search
   configuration lives in three places, two of which write the same slice.
   Export configuration lives in a modal. Cardback selection lives in four
   places. The rails end up thin and the dialogs end up fat — the inverse of
   the intended division. (Items R4, R6, R9.)

The rest is finish: one visual vocabulary instead of three (R10), density
(R11), a glyph that means the wrong thing (R8), a paragraph doing a number's
job (R5), and two buttons that should read as siblings (R7).

---

## §1. Numbered items

Each item states the problem it solves, the diagnosis from code, the proposal,
and the ratified decisions it keeps / refines / contradicts.

---

### R1 — Size art tiles to the surface, and stop shipping an 800px asset into a 72px box

**Problem.** Card images in the left rail are far too small for a surface
whose primary content is card images; they read as incidental. They are also
wasteful: the asset fetched is many times the size drawn.

**Diagnosis.**

- Tile width comes from `FUNNEL_TIER_TILE_WIDTH_REM`
  (`features/gridSelector/SelectVersionResults.tsx`): `dense: 4.5rem` (72px),
  `medium: 5.5rem` (88px), `hero: 7rem` (112px), selected by
  `funnelDisclosureTier(survivorCount)`. The rail's inline width is a fixed
  380px at every tier ≥992px, and roughly 360px on the phone bottom sheet —
  so at the dense tier the rail draws four 72px tiles across a column that
  could carry three at 112px or two at 170px.
- The asset is a single "small" tier with no responsive variant. `Card.tsx`
  resolves, in order: the CDN bucket key `<identifier>-small-google_drive`,
  the worker path `/images/google_drive/small/<id>.jpg`, and finally
  `cardDocument.smallThumbnailUrl` — which the backend builds as
  `https://drive.google.com/thumbnail?sz=w800-h800&id=<identifier>`
  (`MPCAutofill/cardpicker/sources/source_types.py`).
- `next.config.js` sets `images: { unoptimized: true }`, so `next/image` emits
  a plain `<img>` with that exact URL: no `srcset`, no `sizes`, no
  server-side resize. The 800px asset is what the browser downloads and
  decodes, whatever box it lands in.

So a dense tile downloads ~11× the linear resolution it draws (≈123× the
pixels), and the reason the tile is small is unrelated to the reason the asset
is large — they are two independent faults that happen to compound.

**Proposal.**

1. **Tile width derives from a column count, not a survivor count.** The rail
   is a fixed-width column; the number of tiles that read well across it is a
   property of the column, not of how many results there are. Resting density
   is **3-up**: with the rail's `8px 10px` interior padding and a 6px gutter,
   `(380 − 20 − 12) / 3 = 116px` → **112px tiles** (88×112 at the 63:88 card
   aspect… i.e. 112px wide, 156px tall). At `N ≤ 2` the grid goes **2-up at
   170px**. Below 380px (the phone bottom sheet at ~360px content width) the
   same 3-up rule yields 105px; the grid is `flex-wrap` already, so this needs
   no breakpoint of its own.
2. **A real `thumb` asset tier.** Add a third size alongside `small`/`large`,
   targeting ~2× the largest drawn box (≈340px). For the Drive fallback this
   is a URL parameter change (`sz=w340-h340`) and nothing else. For the CDN
   bucket and the worker it is a new key/path (`<identifier>-thumb-…`,
   `/images/google_drive/thumb/…`) and therefore a backend/worker change, not
   a frontend one — see open question 2 for how to sequence that honestly.
3. **`small` keeps its current meaning** and stays what the centre sheet slots
   use, since those draw at ~150px on a 960px sheet and will draw larger under
   pinch/zoom later.

**Render-cost note.** At the resting 3-up density a 380px rail shows ~9 tiles
per screen instead of ~16, so _fewer_ images are on screen at once even though
each is larger. With the `thumb` tier, decoded bitmap per visible tile drops
from 800×800 (2.56 MB decoded RGBA) to 340×340 (0.46 MB) — an 82% reduction
per tile, and the dominant term in the rail's memory footprint. Without the
`thumb` tier, R1 alone _increases_ decoded-pixel pressure only if more tiles
are visible; at 3-up they are not.

**Ratified decisions.**

- **CONTRADICTS** the 2026-07-23 owner fix-round tightening recorded in
  `SelectVersionResults.tsx`'s own comment ("the elements of the cardpicker are
  too large still" — `medium` 104→88px, `hero` 150→112px, `dense` pinned to the
  editor-completion mockup's 72px). **Reason:** that round tightened tiles to
  fit _more_ of them into the rail, which is the right move when the rail must
  also carry four other blocks above the picker. R3 removes those blocks from
  above the picker, so the constraint that motivated the tightening is gone,
  and the tightening now works against the surface's own job. The 72px figure
  also has a specific provenance — the editor-completion mockup's
  `.version-grid .card63` — which was a value for a grid inside a modal, not
  inside a 380px rail.
- **REFINES** funnel-spec **F1/D21** (count-proportional disclosure). The
  thresholds stay, stay named (`FUNNEL_DENSE_ABOVE = 8`,
  `FUNNEL_HERO_AT_OR_BELOW = 2`), and keep driving what F1 actually needs them
  for — whether the chip axes and the advanced-filter disclosure are expanded.
  They stop driving tile width. D21's own text says the tier exists because
  "you need to narrow" at high counts; that argues for showing _filters_, not
  for shrinking _art_.
- **KEEPS** the funnel's continuous single grid, its sort-key ordering, and
  every tile-corner annotation (`✓`/`Alt`/`?`/`REQ`, the ghost tile, the
  scaled confirm ribbon, the dashed suggested marker) unchanged in kind — they
  scale with the tile.

---

### R2 — Cap the survivor grid: the funnel must not mount 243 tiles

**Problem.** The page hangs on large projects and on heavily reprinted cards.

**Diagnosis.** There is no windowing, virtualisation or pagination anywhere in
`features/gridSelector/` — a search across that directory for
`RenderIfVisible`, `IntersectionObserver`, or any slice/limit of the result
array returns nothing. Every survivor becomes a mounted tile. A heavily
reprinted card is not an edge case: Lightning Bolt returns 243 versions.

Each tile is not just an `<img>` — it is a `MemoizedEditorCard` with its own
image-state hook, favourites selector, printing-match `OverlayTrigger`, and
(under the vote layer) suggested/unknown badge computation. `loading="lazy"`
on the image (`Card.tsx`, set unless `priority`) correctly defers the
_network fetch_ for off-screen tiles, but it does not defer mounting,
reconciliation, or the per-tile subscriptions — and it does not help the
tiles that _are_ on screen.

The centre region, by contrast, is already handled: sheets are chunked by
`paginateSlotsForDisplay` and each `PagePreview` mounts through
`RenderIfVisible`. The rail never got the same treatment.

**Proposal.** Window the survivor grid. Render the first `N` survivors
(proposed **60**, a named constant beside the existing funnel constants) and
append a **"Show 60 more" ghost tile** as the grid's last cell. The `GhostTile`
primitive already exists for in-place cluster expansion and already knows how
to become a collapse control once expanded — this is the same affordance,
applied to the grid instead of a cluster, so it introduces no new visual
element and no full-width row (which the continuous-grid round explicitly
removed).

The window resets on slot change (the rail already fully remounts per slot via
its caller's `key`) and on any chip change (a filter is the intended way to
narrow; the window is a floor under the cost of _not_ filtering).

**Render-cost note.** This is the item with the largest effect. At 243
survivors × 112px tiles, the difference is 60 mounted tiles versus 243 —
and, combined with R1's `thumb` tier, a worst-case visible-decode budget of
~9 × 0.46 MB rather than an unbounded fetch queue of 800px assets. The
`loading="lazy"` behaviour is kept, not replaced: windowing bounds the DOM,
lazy loading bounds the network.

**Ratified decisions.** Nothing prior addresses grid size at all — F1's
disclosure tiers change tile _size_ by count but never cap the _number_
rendered. This is a genuine gap rather than a reversal, so nothing is
contradicted. **KEEPS** F1's "one continuous grid, zero visual partitioning"
rule: the ghost tile is a grid cell, not a section break.

---

### R3 — Left rail, reordered: art first

**Problem.** Vertical space is used poorly; the most useful information is not
reachable without scrolling. This is worst in the left panel.

**Diagnosis.** The rail's current block order (`Rail`, `DisplayPage.tsx`):

| #   | Block                                          | What it is                                                                                   |
| --- | ---------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1   | `RailHeader`                                   | slot/face label, card name, subject preview, Front/Back toggle, compact slot-action icon row |
| 2   | `Cardback (this slot)` + `SlotCardbackControl` | per-slot back-face picker                                                                    |
| 3   | `PromotedZone`                                 | `ConfidenceElement` → `MoreDetailsSection` → `IdentifyPanel` → `ArtistSection`               |
| 4   | `SourcesAccordion`                             | which catalog sources are searchable                                                         |
| 5   | **`Select Version`**                           | **the art picker**                                                                           |
| 6   | `ControlStack`                                 | print options + report                                                                       |

The art picker is the fifth block. **Measured in the companion mockup at a
380px rail** (which reproduces the shipped block set at the shipped `8px 10px`
padding and 1px dividers): **446px of rail sits above `Select Version` at
rest, and 766px once the per-slot cardback picker is expanded.** On the phone
bottom sheet (72vh ≈ 570px on a 390×844 device) that means blocks 1–4 consume
the entire sheet before a single tile is drawn, and the expanded case is
larger than the sheet itself. This is the same fault as R1 seen from a
different angle: the surface is not organised around its own job.

Two blocks are also in the wrong rail entirely. The per-slot cardback (2) is
above the art picker on a surface whose job is picking _front_ art; and it is
a back-face concern that most projects never touch. Sources (4) gates what is
searchable, which is why the left-rail round put it here — but gating and
choosing are different acts, and the gate does not need to sit above the
choice.

**Proposal.** New order:

| #   | Block                             | Change                                                                                                                                                                                                                            |
| --- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Identity head**                 | `RailHeader` + `ConfidenceElement` merged into one band: slot/face · card name · subject preview · set icon + confidence pill + `✗ not this printing` · Front/Back toggle · slot-action icons. One block boundary instead of two. |
| 2   | **`Select Version` (the funnel)** | unchanged in kind; now directly under the head, at R1's density                                                                                                                                                                   |
| 3   | **Artist line**                   | unchanged (`ArtistSection`, the named support button)                                                                                                                                                                             |
| 4   | **Demoted group**, all collapsed  | More details · Identify this card · Sources · Cardback (this slot) · Print options · Report                                                                                                                                       |

Everything below 3 stays reachable and stays collapsed-by-default, exactly as
the de-clutter hierarchy requires; only the boundary between "promoted" and
"demoted" moves, and the picker moves above it.

Merging identity and confidence into one band is what buys the space: the two
blocks today carry two separate `8px 10px` padding pairs and two `1px`
dividers to say things about the same subject (which card is in this slot, and
how sure we are it is that card).

**Measured, same mockup, same 380px rail:** rail above `Select Version` falls
from **446px** (shipped resting order) to **158px** — a 288px reduction, and
645px against the cardback-expanded case. The picker's first tile row is on
the first screen at every tier, including the 72vh phone sheet.

**Ratified decisions.**

- **CONTRADICTS** `display-left-rail.md`'s shipped order, in which
  `PromotedZone` (confidence + more-details + identify + artist) renders before
  `Select Version`. **Reason:** the promoted zone earned its position when it
  was the answer to "what is this card?", asked of a surface that was mostly
  metadata. Once the surface is mostly art, the same question is better
  answered _inside_ the identity head — one line, always visible — than as
  three stacked blocks the user scrolls past to reach the thing they came for.
- **KEEPS** that same round's §3 ruling that confidence is identity, not
  demoted metadata, and renders before the artist line. R3 strengthens it:
  confidence stops being a separate band _below_ the header and becomes part
  of the header.
- **KEEPS** the [left-rail de-clutter hierarchy](../../proposal-h-display-layout-spec.md#left-rail-declutter-hierarchy)
  in full — art selection and artist support promoted, everything else
  collapsed-but-not-deleted. R3 makes it more literally true than the shipped
  order does.
- **KEEPS** `display-left-rail.md`'s deliberate deviation putting Sources in
  the left rail rather than the right. Sources gate art availability; the
  deviation stands. R3 only demotes the accordion below the picker it gates.
- **CONTRADICTS** `SPEC-cardback-pdfwait.md`'s `PKG1b` placement of the
  per-slot cardback control as a promoted rail block. **Reason:** see R9.

---

### R4 — One search bar, one home for search settings

**Problem.** Search is buried and duplicated; there should not be redundant
search surfaces, and search settings should fold in naturally rather than
living behind their own control.

**Diagnosis.** Search _configuration_ currently exists in three places, two of
which write the same Redux slice:

| Surface                       | Where                          | Contents                                                                                                       |
| ----------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `SearchSettings` modal        | right rail, own trigger button | source list, search type (fuzzy/precise), filters (DPI/size/language)                                          |
| `SourcesAccordion`            | left rail, inline              | the same source list — writes `searchSettingsSlice` directly, same `setLocalStorageSearchSettings` persistence |
| Funnel `▸ Filters` disclosure | left rail, inside the picker   | sort · jump · source · DPI · size · language                                                                   |

The source list appears in all three. DPI/size/language appear in two. The
modal is the only one of the three that is a dialog, and it is the one that
contains nothing the other two don't.

The search _bar_ is not buried vertically — it is in the top action bar — but
it is buried in reading order: the bar's children render `SavedDeckPanel`
(deck name + save) first, then the Add/Browse group. On phone it is worse: the
search group carries `order: 9` and `flex-basis: 100%`, so it drops _below_
the deck panel and the gear onto its own row.

**Proposal.**

1. **Search leads the action bar.** The Add/Browse group becomes the first
   child at every width; `SavedDeckPanel` follows it; the gear stays pinned
   right (`ms-auto`). On phone the search group's `order` flips negative so it
   is the first row, not the last.
2. **Retire the `SearchSettings` modal trigger from this page.** Its three
   contents already have inline homes: sources → the left-rail accordion;
   DPI/size/language → the funnel's advanced disclosure; search type
   (fuzzy/precise) → the funnel's advanced disclosure, as its first row (see
   open question 6 — it is a global preference sitting among per-card filters).
   The `SearchSettings.tsx` component itself is not deleted; it loses its
   `/editor` mount.
3. **The bar gains a magnifier adornment** (`bi-search`) inside the input, and
   the mode segments read `Add` / `Browse` unchanged. The adornment matters
   for R8: it establishes the magnifier as this page's "find a card" glyph.
4. **The search group gets a `max-width`** (proposed 560px). Its current
   `flex: 1 1 240px` with no ceiling grows the input to roughly 900px on a
   1400px desktop, at which width a single-line "Add cards…" field reads as a
   text area. This surfaced while building the mockup, not from code reading.

**Render-cost note.** Net negative DOM: one modal + backdrop mount removed,
one 6px adornment added.

**Ratified decisions.**

- **REFINES** [the dual-mode browse decision](../../proposal-h-display-layout-spec.md#dual-mode-browse-search-bar):
  both modes, the shared input, the `Print sheets`/`Browse results` centre
  switch and the `+ Add` on browse tiles are all unchanged. Only the bar's
  ordering changes.
- **CONTRADICTS** the base layout spec's §4.2 placement of a **Search
  Settings** section in the right rail. **Reason:** the right rail's job is
  print configuration; search configuration is a left-rail concern by the same
  logic the left-rail round already used to move Sources there. Keeping a
  right-rail trigger for a left-rail concern is what produced the duplication.
- **KEEPS** [the import-dropdown variety confirmation](../../proposal-h-display-layout-spec.md#import-dropdown-variety-confirmation)
  — the `Import ▾` Text/XML/CSV/URL dropdown is unchanged and stays beside the
  input.
- **KEEPS** the ratified funnel's `▸ Filters` advanced-disclosure seam
  (F1's B′, `GridSelectorFilters`' `hiddenSections`/stacked mode) as the
  destination — this is the disclosure absorbing two more rows, not a new one.

---

### R5 — Margin profile: let the numbers explain, and drop the paragraph

**Problem.** The margin-profile explanation consumes too much space for what
it conveys.

**Diagnosis.** `MarginProfileControl.tsx` renders `definition.description` as a
persistent muted paragraph under the select. Immediately below it,
`BleedGrantedReadout` states, per axis, exactly how much bleed the current
combination actually grants versus what was requested. The paragraph describes
a trade-off in prose; the readout quantifies the same trade-off in
millimetres, live, for the settings actually in effect. The prose is the
weaker of the two and it is the one that is always expanded.

**Proposal.** Remove the resting-state description block. The profile's
trade-off surfaces three ways instead, none of which costs vertical space:

1. Each `<option>` carries its own short suffix in the label
   (`Rear-feed — 3mm + 20mm trailing`), so the trade-off is legible at the
   moment of choosing.
2. An `ⓘ` affordance on the `Margin profile` label opens the full description
   as a popover, on hover/focus/tap.
3. `BleedGrantedReadout` stays exactly as it is — it is the load-bearing half
   and it is already correct.

Net: roughly three wrapped lines of muted text removed from the resting right
rail, with no information lost.

**Ratified decisions.**

- **KEEPS**, untouched, every margin-profile _value_ and all of the fit
  arithmetic: the profile table, `maxBleedForFourColumns`, `fitAxisWithBleed`,
  `computeLayout`, the rear-feed default, and the granted-vs-requested readout
  itself. This item changes presentation only.
- **REFINES** the granted-readout decision's own framing — that a number
  stating how much bleed renders is strictly more useful than a flag stating
  only that it is less than requested. R5 extends the same argument one step:
  it is also more useful than a paragraph.

---

### R6 — Export settings belong in the right rail, not in a dialog

**Problem.** Print/PDF settings live in a separate dialog instead of the right
rail.

**Diagnosis.** `features/export/DisplayExportPDF.tsx` (753 lines) mounts a
`Modal` reached from `Export ▾ → PDF`. It contains: card-selection mode, page
range, image quality (DPI + JPG quality), cut-line placement and geometry,
corner rounding, an advanced page-margin override, and a Silhouette/SCM mode
switch that swaps the whole body for a second panel. That is the largest
single collection of settings on the page, and it is the only one that is not
in a rail.

Its own module comment gives the rationale: these are choices about the output
_file_, not the sheet's layout, so they sit "alongside the export affordance
itself… rather than joining the right rail's Page Setup section, which governs
what the live sheet shows".

The distinction is real. It does not imply a dialog. Several of these settings
have a direct visual analogue on the sheet the user is already looking at —
cut-line placement and geometry, corner rounding, and the page-margin override
all change what the printed page looks like, and the centre region exists
precisely to show that. Putting them behind a modal covers the preview at the
exact moment it would be most useful.

Separately, the export has no progress indication of any kind: `PDFWaitPanel`
(the progress bar plus the wait-time minigame) is mounted only by `/print`'s
`PDFGenerator`, never by the editor's own export, and a measured 14-card
project took ~50 seconds (recorded in issue #811). A modal that unmounts on
export cannot host that progress; a rail section can.

**Proposal.** The right rail gains an **Export** section directly above the
pinned footer:

- A two-segment mode control at the section head — `Standard grid` /
  `Silhouette (SCM)` — swapping the body between the modal's two existing
  panels. This is exactly the swap the modal already performs; it becomes a
  visible segmented control instead of a hidden branch.
- Body: card selection · page range · image quality (DPI, JPG) · cut lines
  (placement + geometry) · corner rounding · advanced page-margin override.
  Image quality stays visible in both panels, as it is today.
- The footer's `Export ▾ → PDF` item becomes a direct **Download PDF**
  action — no intermediate settings step, because the settings are already on
  screen.
- The export progress bar lives at the top of the pinned footer, above the
  buttons, where it persists for the whole render.

Page Setup and Export stay separate sections, preserving the distinction the
modal's comment was defending: Page Setup governs the sheet; Export governs the
file. They are simply both in the rail.

**Render-cost note.** Net negative. A modal mount, a backdrop, and a focus trap
are removed; ~40 form-control nodes are added to a rail that already scrolls.
Both sections are `AutofillCollapse`-style disclosures, so the resting cost is
the two headers.

**Ratified decisions.**

- **CONTRADICTS** `DisplayExportPDF.tsx`'s own stated grouping rationale.
  Noted explicitly because it is a deliberate reversal — though it is a code
  comment recording an implementation choice, not an owner-ratified decision in
  the D-ledger, so this is a smaller contradiction than it first reads.
- **TENSION** with [the print-page funnel decision](../../proposal-h-display-layout-spec.md#print-page-funnel-destination),
  which made `/print` the destination that owns heavy PDF generation. The
  editor's own export already superseded that in practice (the co-equal
  `Print / Export →` button was folded away once `DisplayExportPDF` gained its
  own Drive save). R6 completes that direction rather than opening it. What
  remains genuinely undecided is whether `/print` is retired — open question 4.
- **KEEPS** the [finish-footer](../../proposal-h-display-layout-spec.md#finish-footer-save-before-print)
  invariant in full: the draft flush, cardback-reminder and save-before-export
  gate still run before any render begins. Saving still gates PDF; PDF never
  gates saving. R6 changes where the settings live, not the order of
  operations.

---

### R7 — Save and Export as siblings

**Problem.** Save and Export have mismatched visual weight; they should read
as siblings.

**Diagnosis.** In `FinishFooter.tsx`, `Save Deck` is a full-width
`variant="primary"` block inside a `d-grid`. `Export ▾` is a `Dropdown` toggle
at its own natural width, in a `d-flex` row it shares with the download-manager
button, at default (secondary) weight. So the two differ in width, in fill, and
in whether they are alone on their line — three axes of difference for two
actions of the same rank.

**Proposal.** One two-column grid holding both:

- `Save Deck` (or `Sign in to Save`) — `variant="primary"`, column 1.
- `Export ▾` — `variant="outline-primary"`, column 2. Same height, same
  radius (`--theme-radius-base`), same type size, same column width.
- The download-manager counter becomes a small icon-only button pinned to the
  right of the pair, outside the two-column grid, so it never competes with
  either.
- The `✓ Draft backed up locally` note stays below, unchanged.
- The export progress bar (R6) sits above the pair.

**Ratified decisions.**

- **REFINES** [the finish-footer decision](../../proposal-h-display-layout-spec.md#finish-footer-save-before-print),
  whose own footer layout specified "two co-equal `btn-primary` buttons of
  equal width side by side" — the second of which (`Print / Export →`) has
  since been folded into the Export dropdown. R7 restores the co-equal pairing
  that decision described, with `Export ▾` as the second member. Two primaries
  side by side would now be wrong, since only one of the pair is a commitment;
  `outline-primary` is the sibling weight for the other.
- **KEEPS** the anonymous-session behaviour: the button becomes a real sign-in
  link, never a dead control.

---

### R8 — The requery control gets a magnifier

**Problem.** The requery-card icon reads as a flip control. A magnifying glass
would say "find a different printing."

**Diagnosis.** `getCardSlotMenuActions` (`features/card/CardSlotMenuActions.ts`)
gives the `change-query` action the glyph `bi-arrow-repeat` — Bootstrap's two
circular arrows. It renders in two places: as a labelled row in the slot
context menu, and as an **icon-only** 32×30 button in the rail head's compact
action row (`SlotActionsSection`, `compact` variant), where the label survives
only as `aria-label`/`title`.

Meanwhile the sheet slot's top-right corner button is `⟲` — a single circular
arrow — for flip. Two circular-arrow glyphs, on the same screen, one meaning
"turn this card over" and the other meaning "search again". Without a visible
label on the second one, there is nothing to disambiguate them.

**Proposal.** `change-query` → **`bi-search`**. Both triggers change together
(the menu row and the rail-head icon button read from the same action list), so
the two stay consistent by construction.

**Corner-map check** (required before adding any slot glyph). The slot corner
map, as ruled and as built in `PagePreview.tsx`, is:

| Corner       | Control                                 |
| ------------ | --------------------------------------- |
| top-left     | selection checkbox                      |
| top-right    | `⟲` flip (with the custom-cardback dot) |
| bottom-right | `⋯` context-menu cue                    |
| bottom-left  | _free_                                  |

**No collision:** the requery control is not a slot corner affordance at all —
it lives in the rail head's action row, on a different surface. This item adds
nothing to any corner and leaves bottom-left free. The corner map is
**KEPT** intact.

The other magnifier this round introduces is R4's search-bar adornment. That is
not a collision but a correspondence: both mean "find a card", one for the
project and one for a slot.

**Ratified decisions.** **KEEPS** the corner-map ruling and the
one-action-list/two-triggers rule. Nothing contradicted — the glyph was never
ruled on.

---

### R9 — Cardback: one picker primitive, two homes, no third copy

**Problem.** The cardback selector appears in several odd places, and when
expanded in the left rail it renders incorrectly and shows redundant buttons.

**Diagnosis.** Four surfaces:

| #   | Surface                 | What it mounts                                                                                                      |
| --- | ----------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1   | Right rail              | `CardbackToolbarButton` → the project-wide `GridSelectorModal`                                                      |
| 2   | Left rail, block 2 of 6 | `SlotCardbackControl` — expands `GridSelectorResults variant="embedded"`, then appends `CardbackApplyPrompt`        |
| 3   | Pre-export              | `useCardbackReminderGate` → a modal that mounts a _third_ copy of the picker (`MemoizedCommonCardbackGridSelector`) |
| 4   | Sheet slot              | the custom-back dot on the `⟲` flip button — an indicator, not a picker                                             |

The left-rail rendering fault is specific: `GridSelectorResults variant="embedded"` is the _modal's_ results body — its own search input,
filter row and sort controls, laid out for a modal's width — dropped into a
380px column. Then, after a pick, `CardbackApplyPrompt` appends **Apply to all
card backs** and **Set as my default cardback**: two project-wide actions
rendered inside a per-slot control, duplicating exactly what surface 1 already
offers. That is the "redundant buttons" report, and it is a placement error
rather than a styling one — those two actions are not per-slot concerns.

**Proposal.** One picker primitive — a **swatch strip**: the deck's cardback
options as tappable thumbnails in a horizontal, wrapping row, active one
outlined, with a `More…` cell only when the deck carries more backs than fit
two rows. Then:

- **Project cardback → right rail.** It is a project setting, like paper size.
  The strip replaces the modal trigger. `Apply to all card backs` and `Set as my default cardback` live here, where they belong, as two buttons under the
  strip.
- **Per-slot cardback → left rail, demoted.** Same strip primitive, no
  apply-all, no set-default, no embedded modal body. Moves from block 2 into
  R3's collapsed demoted group.
- **Pre-export reminder keeps its modal but drops its picker.** The reminder is
  a genuine interrupt at a genuine decision point, and interrupts are the
  legitimate exception to "rails carry the work". Its `Choose a cardback`
  button opens the right rail scrolled to the Cardback section (on phone and
  tablet, that is the gear drawer) instead of mounting a third picker. The
  `Use current & continue` path and the dismiss-equals-continue behaviour are
  unchanged.
- **The sheet's custom-back dot stays.** It is the only cheap signal that a
  slot diverges from the deck default.

**Render-cost note.** Removes two of the three picker mounts. Each mount is a
full `useGridSelectorSearch` + results grid over the cardback identifier set;
the strip renders `min(deckCardbacks, 12)` thumbnails at 54px and nothing else.

**Ratified decisions.**

- **KEEPS and finally builds** [the cardback swatch strip](../../proposal-h-display-layout-spec.md#cardback-swatch-strip),
  which authorised exactly this strip in exactly this right-rail section and
  has not shipped. Its own escape hatch ("if it crowds the rail at 300px it is
  acceptable to drop back to the button-only form") is noted; the strip at 54px
  fits four across a 300px rail with padding, so the escape hatch should not be
  needed.
- **CONTRADICTS** `SPEC-cardback-pdfwait.md`'s `PKG1b` promotion of the
  per-slot cardback control to a top-level rail block. **Reason:** it is a
  back-face concern on a surface whose job is front art, and most projects
  never diverge from the deck default. Demoting it costs one tap for the
  minority case and buys the picker its first screen for everyone.
- **KEEPS** `PKG1b`'s "no modal, ever" rule for the per-slot picker — the strip
  honours it more literally than the embedded modal body did.
- **KEEPS** the cardback reminder gate's own dismissal semantics (✕/Esc/outside
  click = continue, never cancel) and its once-per-print-session behaviour.

---

### R10 — One visual vocabulary

**Problem.** Elements are inconsistent across the page.

**Diagnosis.** Three idioms for the same weight class, and three for the same
control type:

**Neutral buttons.** The left rail was corrected to `outline-light` by the
buttons-look-like-buttons audit, which found `outline-secondary`
(`$secondary` → `--theme-panel-bg`) near-invisible against dark chrome. The
audit did not reach the other two surfaces: the action bar still uses
`outline-secondary` for the Add/Browse segments and the gear, and the right
rail uses it for the View toggle. So the same finding is fixed in one region
and live in two.

**Toggles.** Three shapes express one idea. `ToggleButtonGroup` segmented
controls (Add/Browse, Front/Back, the funnel's Border/Frame axes); a plain
`Button` whose _label_ flips (`Showing: Fronts` ↔ `Showing: Backs`, right rail
View); and `react-bootstrap-toggle` switches (Sources rows, already restyled
once into a static two-cell segmented shape).

**Section headings.** The left rail uses a 10px uppercase muted legend; the
right rail uses `<h6>`; the funnel uses `.select-version-heading` at 14px.

**Proposal.**

1. `outline-light` (`--theme-light`) is the neutral button variant on every
   dark surface — action bar and right rail included. `outline-secondary`
   leaves this page.
2. Any binary or n-ary state choice is a `ToggleButtonGroup`. The right rail's
   View control becomes `Fronts | Backs` segments, matching Add/Browse and
   Front/Back. `react-bootstrap-toggle` survives only in the Sources list,
   where the two-cell segmented restyle already makes it read as a segmented
   control.
3. One section-heading style everywhere: the left rail's 10px uppercase muted
   legend (`--theme-muted`, `letter-spacing: 0.05em`). Right-rail `<h6>`s and
   the funnel heading adopt it.
4. One radius everywhere: `--theme-radius-base` (6px) for buttons and inputs,
   `--theme-radius-card` (8px) for cards/popovers, `--theme-radius-pill` (10px)
   for status pills. These are already the tokens; the item is to stop having
   components that miss them.

**Ratified decisions.** **EXTENDS** the buttons-look-like-buttons audit to the
two regions it did not cover, on the audit's own stated reasoning. **KEEPS**
the `AutofillCollapse` header hex (`#4E5D6B`, ruled deliberate and one digit
from `$secondary` by design) — it is explicitly not a consistency defect and
must not be "fixed". Under the Tokyo-11 palette the corresponding pair is
`--theme-card-header-bg` / `--theme-panel-bg`, and the same rule applies.

---

### R11 — Density

**Problem.** Padding can be trimmed and things reordered so the most useful
information is reachable without scrolling — in the left panel especially, and
generally.

**Diagnosis.**

- **Right rail.** `Offcanvas.Body` → `p-3` (16px), each section `mb-3` (16px),
  each heading an `<h6>` with Bootstrap's own `margin-bottom: 0.5rem` and 16px
  type. Four sections therefore spend ~96px on inter-section margin alone,
  before any control. The left rail already solved this: blocks butt against
  each other separated by a 1px `--theme-divider` hairline, with rhythm coming
  from each block's own `8px 10px` padding.
- **Action bar.** `px-3 py-2` plus `gap-2`, and one structural cost: the
  invalid-identifiers status is wrapped in an unconditional
  `<div className="w-100" style={{ order: 20 }}>`. The wrapper renders whether
  or not its child does, and a `flex-basis: 100%` item in a wrapping flex row
  claims a whole flex line — zero-height when empty, but still adding the row's
  `gap-2` (8px) on a clean project, which is the common case.

**Proposal.**

1. The right rail adopts the left rail's shipped density verbatim: 1px
   `--theme-divider` block boundaries, `8px 10px` interior padding, 10px
   uppercase legends (R10 §3), no `mb-3` between sections. Predicted saving at
   four sections: ~70px of the resting scroll height.
2. The action bar's invalid-identifiers wrapper becomes conditional — the
   `w-100` div renders only when there is something to show. Predicted saving:
   one 8px gap row on every clean render.
3. Action-bar padding `px-3 py-2` → `px-3 py-1` with a 32px control height
   (the same height R7 gives the footer pair), which is enough for a `btn-sm`
   and its focus ring.

Both rails then use the same density language, which is also half of R10.

**Ratified decisions.** **KEEPS** and **EXTENDS** the left-rail density round
(block boundaries as 1px dividers rather than inter-block gaps). **KEEPS** the
spacing-scale contract: `_theme-tokens.scss` states its 4/8 scale is
future-specs-only and does not retroactively re-space shipped surfaces. The
`8px 10px` pair carried forward here is a known off-scale value owned by the
left-rail spec; this round propagates the existing value rather than inventing
a new one, which is the conservative reading of that contract. Flagged rather
than silently resolved — see open question 7.

---

## §2. REUSE INVENTORY

Per element: what existing component is reused, versus what is net-new. The
standing convention is to reuse rather than fork; a proposal that quietly
invents parallel components is more expensive than it looks.

| Element                | Reused existing                                                                                                                                                                                       | Net-new                                                                                                     | Fork?                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| R1 tile sizing         | `SelectVersionResults` `SelectVersionTile`/`MemoizedEditorCard`; `FUNNEL_TIER_TILE_WIDTH_REM` becomes a column-count derivation                                                                       | one constant pair (`FUNNEL_TILE_COLUMNS`, `FUNNEL_HERO_COLUMNS`)                                            | **No**                                                                                                                 |
| R1 `thumb` asset tier  | `common/image.ts` `getBucketImageURL`/`getWorkerImageURL` (`size` union grows a third member); `Card.tsx`'s existing three-step fallback                                                              | a `"thumb"` size member; backend `sz=` parameter; CDN key + worker path (backend/worker work, not frontend) | **No**                                                                                                                 |
| R2 grid windowing      | `GhostTile` (already the in-place expand/collapse affordance); `useGridSelectorSearch.sortedFilteredIdentifiers`                                                                                      | `FUNNEL_WINDOW_SIZE` constant + a window state in the stacked branch                                        | **No**                                                                                                                 |
| R3 identity head       | `RailHeader` + `ConfidenceElement` composed into one band; `SetIcon`, the confidence pill, the Scryfall `OverlayTrigger`/`Popover`, `APISubmitPrintingTag` ✗ vote all unchanged                       | the merged band's own layout only                                                                           | **No** — composition, not a rewrite                                                                                    |
| R3 demoted group       | `AutofillCollapse` (the existing disclosure), `SourcesAccordion`, `MoreDetailsSection`, `IdentifyPanel`, `PrintOptionsSection`, `ReportCardPanel`                                                     | —                                                                                                           | **No**                                                                                                                 |
| R4 bar ordering        | `ActionBarSearchGroup` styled-component (order/flex rules only); `ImportText` `variant="inline"`; `Import.tsx` dropdown                                                                               | search-input adornment                                                                                      | **No**                                                                                                                 |
| R4 settings absorption | `GridSelectorFilters` `hiddenSections`/stacked mode (already the advanced disclosure); `searchSettingsSlice` + `setLocalStorageSearchSettings`                                                        | two rows moved into the existing disclosure                                                                 | **No** — `SearchSettings.tsx` loses a mount, keeps its code                                                            |
| R5 profile note        | `MarginProfileControl`, `MARGIN_PROFILES`, `BleedGrantedReadout`                                                                                                                                      | `<option>` label suffixes + an `ⓘ` `OverlayTrigger`/`Popover`                                               | **No**                                                                                                                 |
| R6 Export section      | every control in `DisplayExportPDF.tsx` moves verbatim; `useDisplayPDFProps`, `pdfDownload.tsx`'s `useDownloadPDF`/`useSaveToDrivePDF`, `PDFProps` all unchanged                                      | the section shell + the `Standard/SCM` segmented control (replacing a hidden branch with a visible one)     | **No** — the `Modal` wrapper is dropped, its body is not rewritten                                                     |
| R6 progress bar        | `PDFWaitPanel` (currently mounted only by `/print`'s `PDFGenerator`); `reportImageProgress`/`reportImageFailure` already flow through `PDFProps`                                                      | a second mount site                                                                                         | **No**                                                                                                                 |
| R7 footer pair         | `FinishFooter`, `useSaveDeckFlow`, `DisplayExportMenu`, `OpenDownloadManagerButton`                                                                                                                   | grid layout + variant change                                                                                | **No**                                                                                                                 |
| R8 glyph               | `getCardSlotMenuActions` — one string                                                                                                                                                                 | —                                                                                                           | **No**                                                                                                                 |
| R9 swatch strip        | `CommonCardback`'s own gallery data; `selectCardbacks`; `cardbackApply.ts`'s `applyCardbackToAllSlots`/`countBackFacesAffectedByApplyAll`/`resolveCustomBackSlotThumbnails`; `setUserDefaultCardback` | **one net-new `CardbackSwatchStrip` component**, used by both homes                                         | **No** — it replaces two mounts of `GridSelectorResults variant="embedded"`/`GridSelectorModal`, it does not fork them |
| R9 reminder gate       | `useCardbackReminderGate` keeps its modal, its suppression logic and its dismissal semantics                                                                                                          | a rail-open callback replacing the embedded picker                                                          | **No**                                                                                                                 |
| R10 vocabulary         | react-bootstrap `Button`/`ToggleButtonGroup`; `_theme-tokens.scss`                                                                                                                                    | —                                                                                                           | **No**                                                                                                                 |
| R11 density            | `RailRoot`'s existing divider/padding rules, applied to the right rail                                                                                                                                | —                                                                                                           | **No**                                                                                                                 |

**One net-new component in the whole round** (`CardbackSwatchStrip`), and it
exists to _delete_ two heavier mounts. Everything else is composition, a
constant, a variant, or a string.

---

## §3. Render cost, consolidated

The page hangs on large projects. Treating render cost as a design input, the
round's net effect:

| Item              | Effect on images / DOM at once                                                                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| R2 grid windowing | **Largest win.** Bounds the survivor grid at 60 mounted tiles instead of the full result set (243 for a heavily reprinted card). |
| R1 `thumb` tier   | ~82% less decoded bitmap per visible rail tile (800² → 340²).                                                                    |
| R1 3-up density   | ~9 visible tiles per rail screen instead of ~16 — larger tiles, fewer of them.                                                   |
| R3 reorder        | No change to node count; moves the expensive block above the fold so the cheap blocks are the ones scrolled past.                |
| R4                | −1 modal mount.                                                                                                                  |
| R6                | −1 modal mount, −1 backdrop, −1 focus trap; +~40 form controls inside a collapsed disclosure.                                    |
| R9                | −2 picker mounts (each a full `useGridSelectorSearch` + results grid); + ≤12 54px thumbnails.                                    |
| R11               | Neutral on nodes; −1 flex line in the action bar.                                                                                |

**Unchanged and deliberately so:** the centre sheet's existing virtualisation
(`paginateSlotsForDisplay` + `RenderIfVisible` per sheet) and `loading="lazy"`
on card images. Windowing bounds the DOM; lazy loading bounds the network; they
are complementary and this round keeps both.

**Not addressed by this round:** the export itself fetches every card at full
resolution before encoding (~50s / 63MB for 14 cards, per issue #811). That is
a pipeline cost, not a layout one. R6 gives it a place to _report_ progress; it
does not make it faster.

---

## §4. Out of scope, stated explicitly

- `fitAxisWithBleed`'s layout arithmetic and the margin-profile values. R5
  touches only the prose beside them.
- The bleed-slack allocation analysis (issue #799) — a change to the same
  arithmetic, deferred on its own merits.
- The attribute-chip unknown-axis semantics (issue #789); the survivor-filter
  half already landed, and the tile now carries an unknown-attribute badge.
  R1/R2 change how those tiles are sized and how many mount, not which ones
  survive.
- Sheet zoom/pan, and multi-select across sheet page boundaries — both still
  genuinely open elsewhere.
- Whether `/print` is retired (open question 4).

---

## §5. Open questions the owner must rule on

Each is answerable without reading the rest of this document.

1. **Resting tile density in the left rail: 3-up at 112px, or 2-up at 170px?**
   3-up is proposed. 2-up is roughly the size of the sheet's own slots and
   would make the rail read as a gallery rather than a picker; it shows ~6
   tiles per screen instead of ~9.

2. **The `thumb` asset tier — ship it partially or not at all?** The Drive
   fallback is a one-parameter change and helps only cards without a CDN
   entry. The CDN bucket key and the worker path are backend/worker work.
   Options: (a) frontend-visible half now, backend later; (b) hold R1's tile
   sizing until all three land together; (c) ship tile sizing now and accept
   the 800px asset until the backend catches up.

3. **Survivor window size, and does "Show more" append or paginate?** 60 +
   append is proposed. Appending keeps scroll position; paginating keeps the
   ceiling hard.

4. **Is `/print` in scope for retirement?** R6 moves the last settings that
   only `/print` used to own into the editor's rail. If `/print` stays, its
   `PDFGenerator` keeps its own separate copy of the same settings — the
   pre-existing settings-portability gap, now wider.

5. **The pre-export cardback reminder: link to the rail (proposed) or keep the
   embedded picker?** Linking removes the third picker mount but adds a step
   for a user who wants to choose right now.

6. **Search type (fuzzy/precise) is a global preference. Does it belong in the
   funnel's per-card advanced disclosure?** Proposed yes, as its first row,
   labelled as applying to all searches. The alternative is leaving one small
   surface for it and accepting a fourth search-settings home.

7. **`8px 10px` interior padding is off the 4/8 spacing scale** that
   `_theme-tokens.scss` declares for new spec rounds. R11 propagates the
   existing left-rail value into the right rail for consistency. Ruling
   needed: propagate the off-scale value (consistent with what ships), or
   move both rails to `8px 8px` (on-scale, a visible re-space of a shipped
   surface)?

8. **R3 merges the confidence element into the identity head.** Confirm that
   the ✗ _not this printing_ control keeps its current always-visible,
   opacity-de-emphasised treatment on an already-confirmed printing, at the
   smaller scale a merged head implies.

---

## §6. Mockup notes

[`editor-repass-mockup.html`](editor-repass-mockup.html) — self-contained,
vanilla JS only, no CDN, `file://`-openable.

- The fixed top **demo strip** forces **Desktop / Tablet / Phone** at any
  window width, using the transform-scaled-frame mechanism the prior bundles
  established: one breakpoint stylesheet used both inside media queries (Auto)
  and bare (forced); forced Desktop/Tablet render at
  `scale = innerWidth / frameWidth` with a negative `margin-bottom`, and
  because any transform makes the frame the containing block for fixed
  descendants, the drawers scale with the frame. **The full desktop
  composition is reviewable on a ~390px phone.**
- A **Before / After** toggle flips the left rail between the shipped block
  order (R3's diagnosis table) and the proposed one, and the tiles between
  72px and 112px, so R1 and R3 can be judged as a difference rather than
  described.
- **Results: many / some / few / none** exercises R1+R2 together — the
  windowed grid, the "Show 60 more" ghost tile, and the hero tier.
- The right rail shows R5 (no description paragraph, `ⓘ` on the label,
  granted-vs-requested readout intact), R6 (the Export section with its
  Standard/SCM segmented control), R9 (the cardback swatch strip with
  apply-all/set-default beneath it), R7 (the sibling footer pair with the
  progress bar above), and R11's density.
- Theme values are the live Tokyo-11 tokens from `_theme-tokens.scss`, inlined
  as CSS custom properties with the same names: `--theme-body-bg` `#1a1b26`,
  `--theme-raised-bg` `#24283b`, `--theme-panel-bg` `#2f3549`,
  `--theme-card-header-bg` `#2f3548`, `--theme-band-bg` `#222234`,
  `--theme-divider` `#16161e`, `--theme-text` `#c0caf5`, `--theme-muted`
  `#a3aad0`, `--theme-primary` `#ff9e64`, `--theme-accent` `#bb9af7`,
  `--theme-success` `#9ece6a`, `--theme-danger` `#f7768e`, `--theme-warning`
  `#e0af68`, `--theme-info` `#7dcfff`, `--theme-btn-ink` `#1a1b26`, radii
  6/6/8/10.
- Card art is drawn as CSS gradients with a title band, not fetched — the
  mockup has no network access by construction and the round is about
  geometry, not artwork.

### Verified

Driven in a real Chromium (Playwright) at **1400**, **768** and **390** px,
Auto and all three forced views, both rail modes, all four result states:

- The demo strip switches breakpoints, and the forced Desktop frame scales to
  fit a 390px window with both rails and their drawers legible.
- Rail-above-picker heights and tile widths measured via `getBoundingClientRect`
  at a 380px rail: 446 / 766 / 158 px and 72 / 112 / 170 px as quoted in R1 and
  R3.
- Result states: `many` → 12 tiles + the "Show 60 more" ghost cell; `some` → 5
  tiles, no ghost; `few` → 2 tiles at 170px with the axes collapsed to the
  pill line; `none` → the empty state with the directed-help link, axes
  collapsed.
- Console clean (the only entry over `http://` was a favicon 404, an artifact
  of the local static server used because the browser tool blocks the `file:`
  scheme — the mockup itself loads no external resource).
