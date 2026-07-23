# /display LEFT RAIL (card pane) — implementation-ready spec

Design round 2026-07-23 (owner-approved directions + two mid-round addenda).
Builds ON TOP of open PR #352 (Select Version tiles already shrunk to dense
72 / medium 88 / hero 112; group separator removed; buttons being shrunk).
Companion mockup (self-contained, phone-reviewable, forced Desktop/Tablet/Phone
frames): `display-left-rail-mockup.html` (same directory). Owner reviews the
mockup in a browser BEFORE any implementation; Yori builds this spec verbatim
into PR #352 after approval.

Scope = the LEFT rail / card surface only (proposal-h-display-layout-spec.md
§4.1). Center sheet and RIGHT rail are shown in the mockup for three-region
context only and are out of this round's scope. All primitives are the
installed react-bootstrap 2.10.10 / Bootstrap 5.3.8 family — **no new
dependencies**; every shared component gains only additive, optional,
behavior-preserving props.

---

## 0. THEME FIDELITY — the real #302 tokens (extracted, not approximated)

Source: `frontend/node_modules/bootswatch/dist/superhero/_variables.scss` +
`frontend/src/styles/styles.scss` (#302 overrides) + `custom.css`. The prior
mockup's `shared.css` used the STALE pre-#302 palette (`#2b3e50` body /
`#df691a` accent) — do not reuse it. Correct live values:

| Token                                 | Value                                                        | Use                                                           |
| ------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------- |
| `$body-bg`                            | `#0f2537`                                                    | page background (Superhero native, kept by #302 T2)           |
| `$secondary` / card bg / offcanvas bg | `#4e5d6c`                                                    | rail surface, `AutofillCollapse` cards                        |
| `$dark` / `$input-bg`                 | `#22303f`                                                    | rail-head, artist-line, inputs, demoted raised blocks         |
| confidence-chip surface               | `#2b3e50`                                                    | D14 band (matches shipped ConfidenceElement)                  |
| `$body-color` / `$gray-100`           | `#ebebeb`                                                    | text                                                          |
| `$input-placeholder-color`            | `#8fa0b0`                                                    | muted text / placeholders                                     |
| `$light`                              | `#abb6c2`                                                    | neutral outline-button text (`btn-outline-light`)             |
| `$primary` (= `$orange`)              | `#df6919` (hover `#be5915`)                                  | accent, primary buttons, active segments                      |
| `$success`                            | `#5cb85c`                                                    | confirmed ✓                                                   |
| `$danger`                             | `#d9534f`                                                    | delete / exclude / "not this printing"                        |
| `$warning`                            | `#ffc107`                                                    | degraded badge, suggested-confirm ribbon                      |
| `$info`                               | `#5bc0de`                                                    | "Alt / non-canonical" tile tag                                |
| `$input-border-color`                 | `#4e5d6c`                                                    | control borders                                               |
| `$border-radius`                      | **`0`**                                                      | Superhero is FLAT — buttons/inputs/badges/segments are square |
| font                                  | `Lato, -apple-system, "Segoe UI", Roboto, Arial, sans-serif` |                                                               |

**Deliberate radius exceptions (already in shipped `ConfidenceElement`
RailRoot CSS — kept, not invented):** the D14 confidence band uses `6px`; its
inner status pills `10px`. The D17 sheet pinline uses `7px`. Everything else
stays square per Superhero. No element in this spec diverges from the current
theme's palette; the only proposed look-change flagged in the mockup as
`.propose` is the **#353 "Save as my defaults" seam** (a disabled affordance,
not a live control).

---

## 1. Breakpoint behavior — left rail placement (react-bootstrap primitives)

The left rail is ONE node: `Offcanvas responsive="lg"` (existing, R2). Content
composition is IDENTICAL at every breakpoint ("united on mobile and desktop",
D2) — only the chrome differs. The mockup's single `leftRail()` builder proves
the content can't drift between breakpoints.

| Tier    | Width      | Bootstrap | Left rail chrome                                                                     |
| ------- | ---------- | --------- | ------------------------------------------------------------------------------------ |
| Phone   | `<768`     | xs+sm     | `placement="bottom"` 72vh bottom-sheet, opens on slot tap; rounded top + drag handle |
| Tablet  | `768–991`  | md        | `placement="start"` drawer, opens on slot tap; "Card details" edge handle when idle  |
| Laptop  | `992–1199` | lg        | Inline sticky **380px** column                                                       |
| Desktop | `≥1200`    | xl        | Inline sticky **380px** column                                                       |

Sizing: inline width `380px`; `overflow-y:auto` own scroll container; sticky
`top:0` (action-bar height via CSS var, not a constant — issue #250); the
inline wrapper's `position:relative; z-index:0` pair is scoped to inline tiers
only (portal note). None of this changes in this round — it's the shipped R2
shell. This round only restyles/recomposes the rail's INTERIOR.

**Phone reachability (hard requirement):** every surface below is inside the
one `overflow-y:auto` rail scroll container, so all of it is reachable in the
72vh phone bottom-sheet by scrolling. No surface is desktop-only. Verified in
the mockup's native phone frame and its scaled forced-Desktop-on-phone frame.

---

## 2. DENSITY — named padding/margin changes (mechanical)

Owner: "remaining unneeded padding gone." Rail blocks BUTT against each other
separated by 1px borders — vertical rhythm comes from each block's own compact
padding, NOT an inter-block `gap`. Concrete changes (each is a class/inline
edit in `DisplayPage.tsx`'s rail region or its `RailRoot` styled-component):

| Element (current)                   | Current pad/margin                                      | New                                                                                                        | Note                                                                                                       |
| ----------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `RailRoot` inter-section gap        | (RailScroll `gap`/margins)                              | `gap:0` + 1px `border-bottom` per block                                                                    | blocks touch, no floating gaps                                                                             |
| `RailHeader` `.rail-head`           | `p-2` (8px)                                             | `padding:8px 10px`, no bottom margin                                                                       | keep, tighten horizontally                                                                                 |
| `.artist-line`                      | `px-2 py-1` (8/4)                                       | `padding:8px 10px`                                                                                         | promote to a band, `border-bottom`                                                                         |
| D14 `.confidence`                   | `margin:6px 0; padding:6px 8px; border-radius:6px` chip | `margin:0; padding:8px 10px`, full-width band, `border-bottom` (keep 6px on the inner set-icon/pills only) | kills the floating-chip inset margin                                                                       |
| Select Version wrapper `.px-2 pt-2` | 8/8-top                                                 | `padding:8px 10px`                                                                                         |                                                                                                            |
| Unified filter block                | (n/a — new)                                             | `padding:6px 8px; margin-bottom:6px`                                                                       |                                                                                                            |
| `.vgrid` result grid                | (per-group wrappers)                                    | single `d-flex flex-wrap gap-2` (6px)                                                                      | see §7 — also removes the seams                                                                            |
| `AutofillCollapse` header in rail   | Superhero `.card-header` `0.5rem 1rem` (8/16)           | rail-scoped `padding:7px 10px`                                                                             | trims 6px horizontal per demoted section                                                                   |
| `AutofillCollapse` body `pad`       | `pad={2}` (8px)                                         | keep `pad={2}` but drop `Container` default gutter                                                         | Container adds `--bs-gutter-x/2`=12px unless overridden; `p-2` already overrides — verify no double gutter |
| Slot-actions list rows              | text rows w/ `py`?                                      | button stack `gap:6px`                                                                                     | see §8                                                                                                     |

Net effect: ~6–14px reclaimed per section boundary and per demoted header,
consistent across the rail. All values are the mockup's live values.

---

## 3. D14 CONFIDENCE ELEMENT (HARD CONSTRAINT — locked owner decision, #271 c.2026-07-21)

**Kills two things** (context confirmed: `ConfidenceElement.tsx` is ~30%
placeholder — a WORD instead of set-icon+checkmark, a disabled ✗, no hover —
AND the old `DeckbuilderConfirmAffordance` still co-renders in `RailHeader`):

1. `RailHeader` (`DisplayPage.tsx`) — **REMOVE** the
   `DeckbuilderConfirmAffordance` mount entirely (lines ~454–460). The old
   "Confirm?" badge + ComparePin + Y/N buttons is SUPERSEDED and must not
   appear anywhere in the rail. (It stays untouched in `CardSlot.tsx`/editor
   and inside `SelectVersionResults` moment-(a) — this removal is the rail
   HEADER mount only.)
2. `ConfidenceElement.tsx` — **rewrite** the placeholder to the full
   interactive form below.

**Location:** the PROMOTED identity zone, directly under card name +
`RequestedPrintingBadge`, above the artist line (it is identity, not demoted
metadata). Full-width band, surface `#2b3e50`, `border-bottom`, `padding 8px 10px`.

**Visual form (both states shown in the mockup — toggle in the demo strip):**

The **set symbol IS the confidence anchor** (existing `components/SetIcon.tsx`,
a Keyrune `ss ss-<code>` glyph; the mockup uses an inline-SVG placeholder for
it since Keyrune is a webfont and the mockup is CDN-free). A 30px circular
chip; a small corner overlay on the icon carries the confidence signal:

- **Human-confirmed** (`cardDocument.canonicalCard != null`): a small **green
  ✓ badge** (`$success`, 15px, bottom-right of the set icon) + a green
  **"Confirmed"** status pill. NO numeric score.
- **Not confirmed** (only `suggestedCanonicalCard`): the **numeric confidence
  score** as an orange badge on the set icon (e.g. `92%`, bottom-right) + an
  amber **"N% confident"** pill.

Row layout: `[set icon] SET · NUM [status pill] [✗ not this printing →right]`.

- **Scryfall reference on hover:** `OverlayTrigger` + `Popover` (react-bootstrap)
  anchored on the set icon, showing the printing's Scryfall image —
  **display-only, from Scryfall's own CDN, nothing stored** (governing premise
  - #271). Build the URL with the existing `scryfallReference.ts`
    (`buildScryfallReferenceUrl`) shape. Keyboard: the set icon is
    `tabIndex=0`; the popover opens on `focus` as well as `hover` (`trigger={['hover','focus']}`).
- **One-click "✗ not this printing":** a real button (`btn-outline-danger btn-sm`,
  §8) that casts a REAL human vote via the existing `useTagVoting` /
  `AttributeVotingPanel` submission path (no new vote semantics — the human
  half of the Stage-D funnel, #271; composes with review queue #262). Replaces
  today's `disabled` placeholder button.

**A11y:** `data-testid="display-confidence-element"` (kept); set icon
`role="button"` + `aria-label="Show reference image for <SET> <NUM>"`;
status pill has `aria-label` spelling out "confirmed printing" /
"machine-suggested, N percent confidence" (don't rely on the % glyph alone);
the ✗ button `aria-label="Vote: this is not printing <SET> <NUM>"`; hit target
≥ the 30px icon (meets 24px min; pad the tap area to 40px on touch via the
band padding). `RequestedPrintingBadge` stays as-is above it.

**Honesty note (carry to owner):** the `resolved`/`suggested` split is a
two-state proxy, not a calibrated probability. A `resolved` card shows
"Confirmed" (no number). The numeric score is shown ONLY for a `suggested`
card and ONLY where the backend actually exposes one — today
`suggestedCanonicalCard` exposes a machine-cast VOTE, not a % (spec A3
conflict #4). See Open Item 1: the numeric-score data source must be confirmed
before the "N%" is wired to anything real; until then it renders the
qualitative "Suggested" the shipped placeholder already uses, in the D14
visual frame.

---

## 4. SOURCES ACCORDION (brief item 1)

Replaces the flat ~247-row per-source toggle list (today: `SourceSettings.tsx`,
a `Table` of `Toggle` rows with only one "Enable/Disable all drives" button,
reached only via the Search Settings modal) with a disclosure in the LEFT rail
(sources gate art availability → they belong with the card surface; the owner
brief explicitly says "the left panel"). **Deviation from layout-spec §4.2**
(which put Search Settings in the RIGHT rail): honored the newer, explicit
owner brief; flagged in Open Item 4.

**Collapsed = one summary row doing real state-communication:**
`Sources · <N> of <M> enabled` (N in `$success`), plus a **pinned-favourites
chip strip** visible while collapsed (the #353 seam — account-tied preferred
sources land later; leave the affordance now). Chevron on the right.

**Expanded body:**

1. **Type-to-filter** `Form.Control` (`placeholder="Filter sources…"`) — client
   filter over the ~247 names.
2. **Bulk actions** row: `Enable all` · `Disable all` · `Invert` (all
   `btn-outline-light btn-sm`, §8). `Enable all`/`Disable all` reuse
   `SourceSettings`'s existing `toggleAllSourceActiveness`; `Invert` is new-thin
   (map each `[pk, enabled]` → `[pk, !enabled]`).
3. **`☆ Save these as my defaults`** — `btn-outline-success btn-sm btn-block`,
   `disabled` with `title` naming #353 (the seam; labelled `.propose` in the
   mockup).
4. **Toggle list**: the existing per-source `Toggle` (On/Off, `onstyle="primary"`
   `offstyle="secondary"`) + name + a **★ pin star** per row (pins to the
   collapsed favourites strip; local state now, account-bound under #353). The
   list is its own `max-height:190px; overflow-y:auto` inner scroll so it never
   dominates the rail.

**TWO interaction shapes mocked (demo-strip toggle "Sources shape"):**

- **(A) Inline accordion** — body pushes rail content down, rides the rail's
  single `overflow-y:auto` container. **← RECOMMENDED.**
- **(B) Overlay dropdown** — body floats over rail content in an absolutely
  positioned panel.

**Recommendation: INLINE, with reasoning.** On phone the left rail is itself a
72vh bottom-sheet Offcanvas and on tablet a start-drawer; an overlay dropdown
there is an overlay-over-an-overlay — cramped, and re-creates the
stacking/clipping hazard the base spec explicitly warns against (§context, the
portal/z-index trap). Inline pushes content and stays inside the ONE rail
scroll container at ALL breakpoints, so it's uniformly phone-reachable with no
nested overlay. The overlay's only advantage (not scrolling the rail) is moot
because the toggle list has its own inner scroll regardless. Owner's own note
("rail overlays get cramped on phone") points the same way.

**react-bootstrap mapping:** shell = `AutofillCollapse` (same component the
demoted sections use; the summary count is its `title` node, the pinned strip
sits in the header region so it's visible while collapsed). Filter =
`Form.Control`. Bulk = `Button` in a `d-flex gap-2 flex-wrap`. Toggles = the
existing `react-bootstrap-toggle` `Toggle`. **Additive props only:**
`SourceSettings.tsx` gains optional `variant?: "modal" | "rail-accordion"`,
`filterQuery?`, `onInvert?`, `pinnedPks?`, `onTogglePin?` — all defaulting to
today's modal behavior so the Search Settings modal caller is byte-for-byte
unchanged. (Alternatively a thin new `SourcesAccordion.tsx` composing
`SourceSettings`'s existing `searchSettingsSlice` selectors + the
`toggle*`/`getSourceRowsFromSourceSettings` helpers — Yori's call; either keeps
`SourceSettings` upstream-clean.)

**A11y:** summary row is a `button` (`aria-expanded`, `aria-controls`);
filter input `aria-label="Filter sources"`; each Toggle keeps its existing
label; pin star is a `button` with `aria-pressed` + `aria-label="Pin <name> as a favourite source"`; bulk buttons are real buttons. Hit targets ≥40px
(`ToggleButtonHeight`).

---

## 5. ARTIST SUPPORT LINK → clear button crediting MTG Artist Connection (brief item 3)

Today `ArtistSection.tsx` renders `Art by <ArtistSupportLink>` as a bare orange
`<a>`. New: keep the credit line `Art by <Name>` (plain), and render the
support link **as a button that visibly names the destination site**:

> **`Support on MTG Artist Connection ↗`** — `btn-outline-primary btn-sm`

Reuses `ArtistSupportLink.tsx` unchanged: it already accepts `className` +
`children` and already fixes `target="_blank"`, `rel="noopener noreferrer"`,
`title="via MTG Artist Connection"`, and appends the `box-arrow-up-right`
icon. Caller passes `className="btn btn-outline-primary btn-sm"` and children
`"Support on MTG Artist Connection"`. **Zero-crawl preserved:** text credit
only — no fetched logo/asset (docs/features/artist-support-links.md). Gating is
unchanged (`canonicalArtist != null` → button; `null` → plain "Unknown", never
a button pointing nowhere).

**A11y:** the anchor already carries a discernible name via its text; the icon
is decorative (`aria-hidden`). Button hit target ≥`btn-sm` height (~31px) +
band padding.

---

## 6. UNIFIED Frame + Treatment filter (addendum item 1)

Owner: "i want the filters list unified, treatment and frame type can sit in
one spot to save space." Taxonomy (from `attributeChips.ts`): two exclusion
groups `Border Color` {Black/White/Silver Border} and `Frame Style`
{Old/Modern/Future Border}, plus five independent tri-state STANDALONE chips
{Full Art, Borderless, Showcase, Extended Art, Etched}. The funnel today
renders three separate labelled axes (Border / Frame / Treatment).

**New:** merge **Frame + Treatment into ONE block** (Border stays its own
exclusive row directly above — owner named only Frame+Treatment):

```
BORDER   [Any][Black][White][Silver]                        ← exclusive segments
FRAME    [Any][Old][Modern][Future]  │ TREATMENT  ·FullArt +Borderless ·Showcase −Extended ·Etched
                                       └ one block ─────────────────────────────────────────────┘
```

- **Frame Style** = `ToggleButtonGroup type="radio"` (mutual exclusivity kept;
  re-tap active → back to "Any", D23 pattern already in `FUNNEL_AXES`).
- **Treatment** = five **tri-state** chips preserving `attributeChips.ts`'s
  `nextChipState` cycle **untouched(·) → positive/include(+) → negative/exclude(−)
  → untouched**, rendered as independent `Button`/`ToggleButton`s carrying a
  `data-state`; `+`/`−`/`·` glyph + include(green)/exclude(red strikethrough)/
  neutral styling. (This is the FILTER surface — filtering by include/exclude;
  it does NOT itself cast tag votes. Where a treatment tag is only
  machine-`suggested` on the surviving set, the existing funnel implicit-vote
  awareness/F4b path still applies to the PICK, unchanged.)
- Only axes with ≥1 surviving candidate render (`chipMembershipState`,
  unchanged). At phone the frame segments + treatment chips `flex-wrap` within
  the one block (verified in the mockup's phone frame).

**Mapping:** additive change to `attributeChips.ts`'s `FUNNEL_AXES` /
`SelectVersionResults.tsx` filter renderer — render Frame and Treatment axes
inside one bordered `.ufilter` container instead of two stacked blocks. No
change to membership/filter math, tag names, or the exclusive-group semantics.
**A11y:** the block is a `fieldset` with a visually-hidden legend "Frame and
treatment filters"; Frame group is a radiogroup; each Treatment chip is a
button with `aria-pressed` reflecting include, and its `aria-label` spells the
state ("Extended Art: excluded"). Shown at desktop AND phone.

---

## 7. CONTINUOUS Select Version grid — kill the group seams (addendum item 2, hardened)

Owner (verbatim, from the live 390px screenshot `8f5b65ce`): **"the 5 cards
should be in 1 section."** The live page fragments ~6 candidates into stacked
single-column mini-blocks split by a `Confirm?`/Y·N block, a `+N more of this printing` link row, and `suggested`/`More like this` link rows (see the mockup's
**Before (live)** toggle — a faithful recreation for side-by-side review; the
owner's own screenshot is the ground-truth `before`, path in Verification).

**Hard requirement:** ALL candidate tiles pack into **ONE continuous
multi-column flex-wrap grid** (`d-flex flex-wrap gap-2`), the
canonical → non-canonical → unknown order preserved **as sort order only —
zero visual partitioning**. Per-group affordances **annotate the relevant
tile** instead of occupying rows between groups:

| Affordance                            | Old (row, breaks grid) | New (tile annotation)                                                                                                                       |
| ------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Requested printing                    | —                      | `REQ` corner badge (`$primary`), sorts first                                                                                                |
| Canonical / resolved                  | group header           | tiny `✓` corner tag (`$success`) on the tile                                                                                                |
| Non-canonical / custom                | group header           | `Alt` corner tag (`$info`) on the tile                                                                                                      |
| Unknown                               | group header           | `?` corner tag (muted) on the tile                                                                                                          |
| "+N more of this printing"            | full-width text link   | inline **ghost tile** (same footprint, dashed, `+N`) right after the cluster rep; expands the cluster **in place**                          |
| Suggested-printing confirm (moment a) | `Confirm?`/Y·N block   | small **corner ribbon** (`$warning`, "?") on the suggested rep; tap = the existing `DeckbuilderConfirmAffordance` action, no separate block |
| "suggested" / "More like this"        | link rows              | folded into the corner ribbon + the existing funnel awareness line (no standalone rows)                                                     |

Implementation: `SelectVersionResults.tsx` — replace the per-group wrapper
`<div>`s (each a block that forced a line break) with a SINGLE flat flex-wrap
container over the already-computed ordered list (`selectVersionGrouping.ts`
ordering is untouched — it's now a sort key, not a sectioning key). Tile
annotations are absolutely-positioned children of each `SelectVersionTile`.
Tile widths stay PR #352's `4.5rem`/72 dense, 88 medium, 112 hero (count-
proportional, `FUNNEL_DENSE_ABOVE`/`FUNNEL_HERO_AT_OR_BELOW` unchanged). At the
~340px phone rail this yields 3–4 columns; at the 380px desktop rail 4 columns —
one grid either way. The `DeckbuilderConfirmAffordance` and the implicit-vote
mechanics are unchanged in behavior; only their MOUNT moves from a row to a
tile-corner trigger.

**A11y:** the grid is a `role="list"`; each tile `role="listitem"` + an
`aria-label` that includes its group ("canonical printing", "alternate/custom",
"unknown") and requested/suggested status, so the sort-order semantics survive
for a screen reader even though the visual separators are gone; the ghost
"+N" tile is a `button` (`aria-label="Show N more copies of <SET> <NUM>"`); the
confirm ribbon is a `button` with the same label the old Confirm badge used.

---

## 8. BUTTONS-LOOK-LIKE-BUTTONS audit (brief item 4 + addendum item 3)

**Rule:** anything clickable that performs an ACTION reads as a button
(bordered/filled per Superhero, square, `.btn`); links that NAVIGATE may stay
links. On the dark rail surface `btn-outline-secondary` (text `#4e5d6c`) is
near-invisible — use `btn-outline-light` (`#abb6c2`) for neutral actions,
`btn-outline-primary` for the accent action, `btn-outline-danger` for
destructive/negative.

| Action (left pane)                      | Current                     | Corrected                                       | Rationale                                                       |
| --------------------------------------- | --------------------------- | ----------------------------------------------- | --------------------------------------------------------------- |
| Artist support                          | bare orange `<a>`           | `btn-outline-primary btn-sm` (§5)               | action-ish outbound support; also credits the site              |
| D14 "✗ not this printing"               | `disabled` bare button      | `btn-outline-danger btn-sm`, live vote          | casts a real vote                                               |
| Select Version **Filters** disclosure   | underlined text (reference) | **`btn-outline-light btn-sm`** with ▾/▸ chevron | **see recommendation below**                                    |
| Slot Actions (Change Query / Duplicate) | bare text rows              | `btn-outline-light btn-sm btn-block` stack      | perform actions                                                 |
| Slot Actions (Delete)                   | bare text row               | `btn-outline-danger btn-sm btn-block`           | destructive                                                     |
| Sources bulk (Enable/Disable/Invert)    | one `btn` today             | three `btn-outline-light btn-sm`                | actions                                                         |
| Sources "Save as my defaults"           | —                           | `btn-outline-success btn-sm` disabled (#353)    | seam                                                            |
| Sources pin ★                           | —                           | icon `button` (`aria-pressed`)                  | toggles a pin                                                   |
| "+N more" / ghost tile                  | text link                   | `button` (ghost tile)                           | expands in place                                                |
| Suggested-confirm ribbon                | Confirm?/Y·N                | `button` (tile ribbon)                          | opens the confirm action                                        |
| Empty-state "Find this card ↗"          | text link                   | **stays a link** (styled w/ ↗ icon)             | pure NAVIGATION out to Scryfall — the rule's explicit exception |

**Filters-toggle recommendation (explicit, asked for):** the RULE WINS — render
Filters as a **button** (`btn-outline-light btn-sm` + chevron), not underlined
text. It performs an action (expands/collapses the filter disclosure), so it is
exactly what the rule targets; the reference mockup's underlined-text treatment
is the drift, not the standard. This also AGREES with upstream (below). No
strong counter-case: a disclosure control reads more discoverably as a button,
and the chevron already signals expand/collapse state.

**Upstream-divergence lines** (for `docs/upstreaming/` per the owner's
documentation requirement — add each as a `// diverges from upstream:` note at
the change site so it carries into the extractable-primitives/upstreaming docs):

- **Artist support button** — _diverges from upstream:_ chilli-axe/mpc-autofill
  has no artist-support surface at all; this is a fork-only feature
  (`ArtistSupportLink`), additive, upstreamable independently. The button
  styling (`btn-outline-primary`) is a fork choice with no upstream analogue.
- **Slot Actions as a button stack** — _diverges from upstream:_ upstream renders
  the `CardSlotMenuActions` list only as `Dropdown.Item`s / a context menu
  (`CardSlotContextMenu.tsx`); the rail renders the SAME action list as stacked
  `btn-outline-*` buttons. Behavior/actions identical; presentation diverges.
- **D14 "✗ not this printing"** — _diverges from upstream:_ fork-only confidence
  element (#271); no upstream counterpart.
- **Sources Invert + type-filter + pin** — _diverges from upstream:_ upstream
  `SourceSettings` exposes only a single "Enable/Disable all" button and drag
  reorder; Invert, the filter input, and per-source pin are fork additions.
- **Filters toggle as a button** — _does NOT diverge from upstream:_ upstream's
  `GridSelectorFilters` already renders the settings/Filters toggle as a
  `Button` (`settingsToggleRef`), so conforming to the actions-are-buttons rule
  keeps us aligned with upstream and only corrects the reference mockup's
  text-link drift. (Recorded so the divergence ledger shows this was checked,
  not assumed.)

---

## 9. File-level change rows (what Yori edits — all in PR #352)

| File                                                                                            | Change                                                                                                                      | Additive/behavior-preserving?                                            |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `features/display/ConfidenceElement.tsx`                                                        | rewrite placeholder → full D14 (SetIcon + ✓/score overlay, `OverlayTrigger`+`Popover` Scryfall, live `useTagVoting` ✗ vote) | rewrite of a fork-only display component                                 |
| `features/display/DisplayPage.tsx` (`RailHeader`)                                               | REMOVE `DeckbuilderConfirmAffordance` mount (D14 supersedes)                                                                | removal; component untouched, still used elsewhere                       |
| `features/display/DisplayPage.tsx` (`RailRoot`/rail region)                                     | density (§2); mount Sources accordion; keep promoted `ConfidenceElement`                                                    | additive/CSS                                                             |
| `features/display/ArtistSection.tsx`                                                            | render `ArtistSupportLink` as `btn-outline-primary btn-sm` crediting "MTG Artist Connection"                                | props-level, `ArtistSupportLink` unchanged                               |
| `features/searchSettings/SourceSettings.tsx` **or** new `features/display/SourcesAccordion.tsx` | rail-accordion variant: summary count, filter, Invert, pins, #353 seam                                                      | additive optional props / thin new composer; modal caller byte-identical |
| `features/gridSelector/SelectVersionResults.tsx`                                                | ONE continuous flex-wrap grid; tile-corner annotations; unified Frame+Treatment block; density                              | grid/render change; ordering + vote logic unchanged                      |
| `features/attributeChips/attributeChips.ts`                                                     | render Frame+Treatment axes in one block (FUNNEL_AXES rendering)                                                            | additive; taxonomy/tri-state unchanged                                   |
| `features/display/scryfallReference.ts`                                                         | reuse `buildScryfallReferenceUrl` for the D14 popover image URL                                                             | reuse, no change                                                         |

No new npm dependency. No change to `GridSelectorModal.tsx` (editor modal),
`CardSlot.tsx`, or `DeckbuilderConfirmAffordance.tsx` internals.

---

## 10. Accessibility summary (consolidated)

- **Hit targets:** ≥40px for toggles/pins (`ToggleButtonHeight`); ≥31px
  `btn-sm` + band padding for rail buttons; D14 set icon padded to 40px on
  touch.
- **Keyboard:** D14 set icon `tabIndex=0`, popover on `focus`; Sources summary
  `button` with `aria-expanded`; every corrected action is a real
  focusable/Enter-Space `button`; tri-state chips reachable + `aria-pressed`;
  ghost/ribbon tiles are buttons.
- **ARIA:** Sources accordion `aria-controls`/`aria-expanded`; unified filter
  is a `fieldset`/`radiogroup`; result grid `role=list`/`listitem` carrying
  group+status labels so the "one grid" visual doesn't erase the
  canonical/custom/unknown semantics for AT; D14 status spelled out (not
  glyph-only).
- **Contrast:** all text/borders use the real Superhero tokens (§0), which
  clear AA on `#0f2537`/`#4e5d6c`/`#22303f`/`#2b3e50` surfaces (orange body
  text at 4.61:1 per the #302 note; `btn-outline-light` `#abb6c2` chosen over
  the invisible `btn-outline-secondary`).

---

## 11. Open items / owner decisions

1. **D14 numeric-score data source.** The brief locks "NUMERIC CONFIDENCE
   SCORE when not confirmed," but the backend today exposes a
   machine-cast VOTE (`suggestedCanonicalCard`), not a calibrated %. Confirm the
   real source of the number before wiring it; until then D14 shows the
   qualitative "Suggested" in the D14 frame. (Design shows `92%` as a
   placeholder value.)
2. **Should "✗ not this printing" appear on an already-confirmed printing?**
   The mockup keeps it visible (de-emphasised) so disputing settled consensus
   is always possible; alternative is to hide it once `resolved`. Owner call.
3. **Sources shape** — confirm INLINE (recommended) over overlay.
4. **Sources placement: left rail (this brief) vs. right-rail Search Settings
   (layout-spec §4.2).** This design put it in the LEFT rail per the explicit
   brief (sources gate art). Confirm the modal `SourceSettings` is
   replaced/kept alongside.
5. **Pinned-favourites persistence (#353).** Seam only now (local state);
   confirm the account-tied "save as my defaults" scope lands under #353 as
   assumed.
6. **Group corner-tag copy** (`✓` / `Alt` / `?`) and whether a
   canonical/custom/unknown label should surface anywhere for sighted users
   beyond the corner tag, or ordering + tag is enough (owner wanted zero
   partitioning — current design shows the minimal tag).
