> Durable copy of the owner-ratified 2026-07-22 `/display` left-rail
> art-picker funnel spec, sourced verbatim from
> `/home/ubuntu/.claude/jobs/1901e529/tmp/funnel-spec.md` (review/design
> artifact; implemented in PR #329). This is the raw decision record —
> for the narrative, de-lettered account of what it changed and why, see
> [`../features/grid-selector.md`](../features/grid-selector.md)'s "The
> art-picker FUNNEL" section, which is the living, authoritative doc for
> this surface. Reference only; not re-derived or updated after
> ratification — it is a point-in-time record of the ruling, not a
> living spec. (This file was recovered during the 2026-07-23 D-lettering
> sweep: `docs/features/grid-selector.md` cited decisions D20–D24 and a
> "funnel-spec.md" companion that had never been committed to the repo —
> see [`../lessons.md`](../lessons.md) for the general pattern this
> exemplifies.)

# /display left-rail ART-PICKER FUNNEL — breakpoint spec

**STATUS: OWNER-RATIFIED 2026-07-22** (all four open questions ruled; D20 automatic
support confirmed, D21 thresholds accepted as named constants, D22 `⋯` cue placed
bottom-right, no finish axis). Companion mockup: `funnel-mockup.html` (same
dir; open via `file://`, use the top demo strip to force Desktop/Tablet/Phone at
any window width — phone-reviewable). **This spec COMPOSES with, and revises
nothing structural in, the two approved foundations:**

- `display-layout-spec.md` (D1–D19) — the three-region /display layout; §4.1's
  left rail is the container this funnel lives inside.
- `editor-completion-spec.md` (E1–E26) — the left-rail fidelity + center-sheet
  interaction round; **E3/E4** (Select Version fidelity, filter disclosure) and
  **E9/E13** (context menu) are the exact seams this funnel refines.

It specifies the **art-picker funnel** — the single filter→survivors surface — at
reference fidelity, plus the /display context-menu surfacing. All primitives are
react-bootstrap **2.7.2** / Bootstrap 5.3.x. **No new dependencies.** Read from
the real code, not assumed (see §0).

**Numbering.** Spec items are **F1–F7** (this document's own namespace — distinct
from `display-layout-spec.md` §A1's change-inventory `F1–F14` rows, which are file
rows, not spec items). Owner decisions continue the shared **D-ledger at D20–D24**
(the display ledger ended at D19). File-change rows are **XF1–XF12**.

**Theme fidelity (verified against live SCSS + built values, not approximated).**
`frontend/src/styles/styles.scss` top block, live on proxyprints.ca:
`$primary` = Superhero-native **`#df6919`** (orange; the `$blue` override was
deleted); `$dark`/rails/inputs = **`#22303f`**; `$secondary` = **`#4e5d6c`**;
text = **`#ebebeb`**; **`$body-bg` is KEPT at Superhero-native `#0f2537`** (owner
amended theme-spec T2 — orange link text is 4.61:1 (AA) on `#0f2537` vs 3.24:1
(fails) on the mockup's `#2b3e50`). Rail/panel palette matches the approved
`display-mockup.html`/`editor-completion-mockup.html` §5 lift (chrome `#22303f`,
panel/field/slot `#2B3E50`, divider `#16202b`, accent `#df6919`, muted
`#aab7c4`/`#8fa0b0`). The mockup inlines THOSE; the outer page field is drawn
`#0f2537` (live), labeled in the mockup.

---

## 0. Ground truth (read from the real code, 2026-07-22)

The funnel taxonomy and half the vote machinery **already exist** — the funnel is
mostly re-arranging and re-labeling extant parts, plus one clean votes-layer seam.

- **The chip taxonomy is already axis-grouped.**
  `frontend/src/features/attributeChips/attributeChips.ts` exports
  `EXCLUSION_GROUPS` — **Border Color** (Black/White/Silver) and **Frame Style**
  (Old/Modern/Future Frame), each an `ExclusionGroup {id,label,chips}` — plus
  `STANDALONE_CHIPS` (Full Art, Borderless, Showcase, Extended Art, Etched).
  `ALL_ATTRIBUTE_CHIPS` = standalones ++ every group's chips. Within an exclusion
  group a positive selection already excludes siblings; across groups selections
  AND. **So F2's "per-axis stacked-exclusive" model is the data model that already
  ships — it is only rendered wrong today** (a flat 11-chip wall).
- **`filterCandidatesByChipStates(candidates, chipStates)`** (same file) already
  ANDs positive/negative chip states over candidates using each chip's
  `matches(candidate)` predicate — and **every `matches` predicate reads a plain
  Scryfall field** (`candidate.borderColor`, `.frame`, `.fullArt`,
  `.isShowcase`…). **Filtering therefore needs ZERO vote data** — this is the
  votes-off seam (F5) already present in code.
- **The current wrong rendering.** `SelectVersionResults.tsx`'s internal
  `FilterChipBar` maps `ALL_ATTRIBUTE_CHIPS` into one flat `FilterChipRow` — all
  11 chips, no axis grouping — with a hardcoded **blue** active fill
  `rgba(13, 110, 253, 0.25)` (a stale **pre-theme-flip literal**; must become the
  orange accent). This is E3/E4's "chip wall" (Bkg 1) and the funnel's redesign
  target.
- **The three membership states already have a data source.** `CardDocument`
  (`common/schema_types.ts`) carries `tags: string[]` (consensus-**resolved**),
  `tagVoteStatuses?: {[tag]: TagVoteDisplayStatus}` (with a `"suggested"` value),
  and `suggestedCanonicalCard`. `SelectVersionResults.filterByActiveAttributeTags`
  already matches a card on **resolved OR suggested** per active tag
  (`card.tags.includes(tagName) || card.tagVoteStatuses?.[tagName] === "suggested"`). `selectVersionGrouping.ts` types `PrintingGroupStatus = "resolved" | "suggested"`. **F3's SETTLED/SUGGESTED distinction is a query over
  data that already flows.**
- **The implicit-vote mechanic already exists as a TWO-tap variant.**
  `SelectVersionResults.tsx`'s `ConfirmChip` / `suggestedActiveTagNames`
  ("moment (c)"): after you select a card while filters are active, for each
  active tag the card matches only via `tagVoteStatuses === "suggested"` (not a
  resolved `card.tags` entry), a _"Looks {tag}? ✓ ✕"_ affordance appears and ✓
  casts a real `APISubmitTagVote(…, polarity=1, source="select-version")`.
  `getAutoTagChips(candidate)` (attributeChips.ts) computes every chip a candidate
  satisfies. **F4 replaces the second (✓) tap with the pick itself** (D20).
- **`useTagVoting`** owns the optimistic tap→`APISubmitTagVote`→reconcile/revert
  cycle, including the **retract sentinel** (`CHIP_POLARITY.untouched = 0`,
  `cardpicker.views.RETRACT_POLARITY`) — a vote of polarity 0 withdraws a prior
  vote. **F4's "retraction = deselection" rides this exact sentinel.**
- **The context menu is built and shared.** `CardSlotContextMenu.tsx` renders
  Bootstrap `.dropdown-menu` items **fixed-positioned at an arbitrary (x,y)**;
  `getCardSlotMenuActions.ts` is the one shared action list (Change Query ·
  Duplicate · [Unfilter Printing] · Delete); `CardSlot.tsx` wires right-click
  (`onContextMenu`→preventDefault) and touch `useLongPress` (500ms, cancels
  > 10px). E9 already extends this list for the sheet. **F6 mounts it on
  > `PagePreview` slots + adds the visible touch cue E9 deliberately omitted.**
- **`ToggleButtonGroup`/`ToggleButton`** (react-bootstrap 2.7.2) are already
  imported in `DisplayPage.tsx` — the segmented-control primitive F2 needs, no new
  dep.

---

## 1. The design in one screen (all breakpoints)

The funnel is the always-open **Select Version** surface (E3's promoted, open art
surface — the demoted accordions below it, E5, are untouched). It is ONE vertical
column, top→bottom:

```
┌── Select Version ──────────────────────────────┐   promoted, open (E3)
│ 12 versions · [Black ×][Full Art ×] · ▸ Filters │  A. funnel head (count · active · disclosure)
├─────────────────────────────────────────────────┤
│ Border   [ Black | White | Silver ]             │  B. per-axis segmented chips (F2)
│ Frame    [ Old | Modern | Future ]              │     only axes with ≥1 survivor render (F3)
│ Treatment[ Full Art ][ Showcase ][ Etched⌇ ]    │     ⌇ = SUGGESTED (dashed, unconfirmed)
│ ▸ More filters (Sort · Jump · Source · DPI…)    │  B′. E4 advanced set, disclosed
├─────────────────────────────────────────────────┤
│ ⓘ Picking supports "Black · Full Art" for this  │  C. implicit-vote awareness line (F4a)
│    card. Undo by re-picking. — votes-on only    │
├─────────────────────────────────────────────────┤
│ [ survivors grid — count-proportional (F1) ]    │  D. survivors
│  many → dense 72px tiles                        │
│  few  → larger tiles, expanded                  │
│  one  → single hero tile                        │
└─────────────────────────────────────────────────┘
        pick a survivor  →  (F4b) support cast · (F4c) chips reset · ack fades
```

The **container** placement per breakpoint is entirely inherited from
display-layout-spec §4.1 (this funnel does not touch rail placement):

| Tier    | Width      | Rail container (D-spec §4.1)   | Funnel content width                            |
| ------- | ---------- | ------------------------------ | ----------------------------------------------- |
| Phone   | `<768`     | Bottom sheet 72vh (tap a slot) | full-sheet (~360px), head A sticky at sheet top |
| Tablet  | `768–991`  | Start drawer 380px             | 380px                                           |
| Laptop  | `992–1199` | Inline left, sticky, 380px     | 380px                                           |
| Desktop | `≥1200`    | Inline left, sticky, 380px     | 380px                                           |

So the funnel's own responsive behavior is chiefly **vertical-budget** adaptation
(count-proportional disclosure, F1) at a near-constant ~360–380px content width;
the phone bottom-sheet is the tightest budget and drives the collapse thresholds.

---

## F1 — ONE funnel: filter narrows, survivors show, count-proportional disclosure

**Problem it fixes.** Today filtering + alternate-art live in more than one place
in the rail: the flat `FilterChipBar` wall (atop results), the `GridSelectorFilters`
sidebar column (beside results, Bkg 2/4/5), and the version grid. The funnel
unifies them into the single top→bottom column of §1: **head → chips → advanced →
awareness → survivors.** One surface, one scroll, one mental model.

**Count-proportional disclosure** (owner ask — "few results → larger tiles /
expanded; many → denser grid"). Let `N` = surviving candidate count after active
chips. The funnel picks a disclosure tier from `N`:

| `N` (survivors)        | Chip section (B)                                                                         | Survivors grid (D)                                         | Rationale                                             |
| ---------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------- |
| **`N > 8`** (many)     | **axes shown** + advanced B′ auto-expanded                                               | **dense**: `compressed` tiles ~72px, 3–4/row               | you need to narrow; chips + advanced earn their space |
| **`3 ≤ N ≤ 8`** (some) | **axes shown** (still narrow-able), B′ collapsed                                         | **medium** tiles ~104px, 2–3/row                           | narrowing still useful; give art more room            |
| **`N ≤ 2`** (few)      | **collapsed** to `A`'s active-pills line (axes one tap away — nothing left to partition) | **large**: hero tile(s), expanded metadata line under each | the answer is basically here                          |
| **`N = 0`**            | collapsed to the pills line + "no versions match — relax a filter"                       | E17 empty state + directed-help "Find this card ↗"         | dead-end recovery                                     |

Thresholds are the design's; tune at build. **Axes stay visible while there is
anything left to narrow (many + some); they collapse to the head's active-pill
summary only at few/none** — the reviewed behavior (the mockup demonstrates it),
chosen over hiding the primary filter at 8 results. This **refines E4/L9's hard
`compressed=true`**: compressed is the _many-results_ default; _some_ relaxes to
medium tiles and _few_ to expanded hero tiles (see D21). The tier is derived from
the same `sortedFilteredIdentifiers.length` `useGridSelectorSearch` already
computes — no new state.

**Implementation seam.** The funnel is the **`layout="stacked"`** branch of
`SelectVersionResults` that E3 already introduced (additive, default `"sidebar"`
keeps the /editor modal byte-for-byte). This spec fills in what `"stacked"`
renders: head A, the axis-grouped chip section B (F2), the E4 advanced disclosure
B′, awareness line C (F4), survivors D at the count-proportional tier. The
`initialSettingsVisible=false` (E3/Bkg 5) still governs B′.

---

## F2 — Per-axis stacked-exclusive chips (segmented, not chip soup)

**Model (already in `attributeChips.ts` — render it correctly):**

- **Exclusive axes** = `EXCLUSION_GROUPS`. Render each as a react-bootstrap
  **`ToggleButtonGroup type="radio"`** (one `name` per axis) of `ToggleButton`s —
  the segments are visually joined and at most one is active, so mutual exclusion
  is _structurally_ obvious (a radio segmented control, not free-floating chips).
  - **Border**: Black / White / Silver (`BORDER_COLOR_GROUP`).
  - **Frame**: Old / Modern / Future (`FRAME_STYLE_GROUP`).
  - Re-selecting the active segment clears the axis (back to "any") — the
    tri-state cycle collapses to two states here because filtering wants
    positive-or-off, not the QuestionFeed's positive/negative/off (see D23 note).
- **Non-exclusive axis** = `STANDALONE_CHIPS`, presented as one **Treatment** axis
  rendered as a **`ToggleButtonGroup type="checkbox"`** (multiple allowed): Full
  Art, Borderless, Showcase, Extended Art, Etched. Independent toggles; multiple
  combine as AND with each other and with the exclusive axes (unchanged
  `filterCandidatesByChipStates` semantics).
- **Across axes = AND.** Already how `filterCandidatesByChipStates` composes; no
  change.

**Layout.** Each axis is one labelled row: a left gutter axis label (`Border`,
`Frame`, `Treatment`) + the segmented group, wrapping within the row only if the
segments exceed 360px. This is the compact form that keeps F2 from re-becoming
Bkg 1's height wall — **combined with F3's membership rule (only axes with ≥1
surviving candidate render), a typical card shows 1–2 axis rows, not 11 chips.**

**Honesty flag / D23.** The task names "border color, frame, finish, tag
attributes" as example axes. **There is no "finish" chip axis in the catalog
taxonomy** — foil/finish is a _print setting_ (`finishSettingsSlice`,
right-rail Finish section per D11), not a per-card attribute vote dimension, and
"Etched" is the only finish-adjacent chip (it lives in Treatment). This spec does
**not** invent a finish axis (would fork fake catalog knowledge). Axes shipped:
**Border, Frame, Treatment.** If the owner wants a genuine finish/foil _filter_
over catalog data, that needs a new seeded tag dimension — flagged, not assumed.

---

## F3 — Chip membership from OUR catalog's knowledge (three visual states)

A chip is a filter over the surviving candidate set; its **membership state** is
derived from what the catalog knows about the candidates that carry the attribute.
Three visually distinct states:

1. **SETTLED (normal chip).** The attribute is resolved for the candidates it
   filters — either **plain Scryfall metadata** (`chip.matches(candidate)` is
   definitively true from a Scryfall field: `borderColor`, `frame`, `fullArt`,
   `isShowcase`, …) **or consensus-resolved** (`card.tags.includes(tagName)`).
   Visual: solid segmented control, orange (`#df6919`) when active, `#4E5D6C`
   border when inactive. No vote copy. **Border/Frame/Treatment chips are
   SETTLED by Scryfall metadata in the overwhelming common case** — this is why
   the funnel filters correctly with the vote layer entirely off (F5).
2. **SUGGESTED (dashed + explicitly marked unconfirmed).** The _only_ candidates
   the chip would filter in carry the attribute via a **machine-suggested,
   unconfirmed** catalog vote — `tagVoteStatuses?.[tagName] === "suggested"` **and
   not** in `card.tags` and **not** Scryfall-settled. Visual: **dashed
   `#df6919` border**, a trailing **`⌇` glyph**, muted fill, and the label reads
   with an _"unconfirmed"_ affordance (title/tooltip: _"Our catalog leans this
   way but hasn't confirmed it — picking supports it"_). This is the exact
   `filterByActiveAttributeTags` "suggested match" condition, surfaced on the chip
   instead of hidden. **Never shown for a resolved attribute; never shown for a
   sensitive/moderation-gated tag** (D24 — sensitive tags are moderation-gated and
   must not leak a lean).
3. **Plain metadata (normal chip, no vote dimension).** A chip whose attribute has
   no vote dimension at all (pure Scryfall field, no seeded consensus tag behind
   it) renders identically to SETTLED but carries **no** suggested-capable
   treatment and casts **no** implicit vote on pick — it is inert to the vote
   layer. In today's taxonomy Border/Frame/Treatment are all vote-backed _and_
   metadata-backed; this state exists so the model is honest when a future
   metadata-only chip (no `Tag` row) is added.

**Aggregation over candidates.** For a chip in an axis: SETTLED if ANY surviving
candidate settles the attribute (metadata or resolved); SUGGESTED only if every
supporting candidate is suggested-not-resolved. Computed from the same
`CardDocument.tags` / `tagVoteStatuses` already on each result — no new fetch.

---

## F4 — Implicit-vote mechanic (UX only; backend built in parallel)

When the user picks a card **while filter chips are active**, the pick casts a
small **SUPPORTING** vote for the active attributes the picked card satisfies, then
filters reset. **The word is always "support," never "confirm"** — votes are
bounded reinforcement, never decisive.

- **(a) Before — awareness line (F4a).** While ≥1 chip is active AND the vote layer
  is on, a subtle **inline line C** sits between the chip section and the survivors
  grid (NOT a modal, NOT a toast): _"ⓘ Picking a card here **supports** {active
  attribute list} for it. Undo by re-picking."_ Muted `#aab7c4`, small, an `ⓘ`
  glyph — reads as an ambient note, not a prompt. It names the exact tags at
  stake so the user knows what a pick means _before_ they act. Absent when no chip
  is active or votes are off.
- **(b) The pick — support cast (F4b).** On tile select, compute
  `supportTags = getAutoTagChips(candidate) ∩ activeChips`, **restricted to tags
  the candidate does NOT already resolve** (`!card.tags.includes(tag)` — don't
  re-vote a settled fact; mirrors moment (c)'s gate). For each, cast
  `APISubmitTagVote(…, polarity = +1, source = "select-version-implicit")` — a
  **small/bounded** supporting vote (the backend weights implicit-source votes
  below explicit taps; the funnel just tags the source). Sensitive tags are
  excluded (D24). If `supportTags` is empty the pick is an ordinary selection with
  no vote.
- **(c) After — reset + brief acknowledgment (F4c).** Immediately after the pick:
  **the active chips clear** (`chipStates`→all off) so the funnel returns to its
  unfiltered rest state, and a **brief non-modal ack** fades in for ~2s: _"Supported
  {tags} ✓ — filters cleared"_ (an `aria-live="polite"` inline strip in the head A
  region, reusing the pill/ack visual family; or a single `Toasts` entry). It
  auto-dismisses; nothing to click. This replaces the two-tap `ConfirmChip` ✓ —
  the pick _is_ the support (D20).
- **(d) Retraction = deselection (F4d).** Changing or deselecting the pick
  **withdraws** the support — no separate "undo my vote" surface. Re-selecting a
  different version for the slot, or clearing the slot, re-casts the just-supported
  `supportTags` at **polarity 0** (the `RETRACT_POLARITY` sentinel `useTagVoting`
  already uses), keyed by (`anonymousId`, card, tag) so the ledger nets to
  withdrawn. The awareness line C names this ("Undo by re-picking"); no extra UI.
  Implementation holds the last pick's `supportTags` in the slot's transient state
  so the retract knows what to withdraw.

**Non-survey guarantee.** The funnel never _asks_ — no ✓/✕ prompt, no rating, no
extra tap. Support is a side effect of the pick the user was already making,
disclosed by line C and reversible by re-picking. `ConfirmChip` (the two-tap
prompt) is **retired from this surface** (D20); its logic is subsumed.

---

## F5 — Votes-off completeness (adoption requirement)

The whole funnel degrades cleanly to a votes-unaware editor. **The vote layer
ATTACHES over base components via additive optional props** — absent them, the
funnel is a pure metadata filter.

**Base (votes-off) — always present, no vote data required:**

- Head A (count · active pills · `▸ Filters`).
- Per-axis segmented chips B — filter via `chip.matches` (Scryfall fields only).
- Advanced filters B′ (E4: Sort/Jump/Source/DPI/size/language — all metadata).
- Survivors grid D + count-proportional disclosure (F1) — driven by
  `sortedFilteredIdentifiers.length`.
- Pick a survivor → sets the slot's image. **No vote, no reset-with-ack, no
  awareness line, no confirm** — the pick is an ordinary selection.
- Every chip renders **SETTLED/plain** — **no SUGGESTED state** (no dashed
  chips, no `⌇`, no "unconfirmed" copy).

**Vote layer (votes-on) — attaches when the seam props are supplied:**

- `tagVoteStatuses` per result → SUGGESTED chip rendering (F3 state 2).
- Awareness line C (F4a), implicit support-on-pick (F4b), reset + ack (F4c),
  retraction (F4d).

**The seam.** A single optional prop bundle on the `layout="stacked"`
`SelectVersionResults` (and the funnel container `DisplayPage` composes):

```
voteLayer?: {
  onImplicitSupport(candidate, activeTagNames): void;   // F4b/c/d
  suggestedTagNames(card): string[];                     // F3 state-2 read
  awarenessCopy(activeTagNames): string;                 // F4a
} | undefined     // undefined ⇒ votes-off, base funnel only
```

Absent (`undefined`) → the base funnel. `tagVoteStatuses` is _already_ optional on
`CardDocument`; when the backend doesn't populate it, `suggestedTagNames` returns
`[]` and every chip is SETTLED with zero branching in the base render. **No element
is missing or broken in either state** — votes-off is the strict subset.

---

## F6 — Context menu on /display slots (right-click · long-press · visible cue)

Surface the **existing** `CardSlotContextMenu` on the /display center
`PagePreview` slots — the same component `CardSlot.tsx` already triggers on the
/editor grid, extended by E9's action list. **No new menu component, no fork.**

- **Desktop — right-click.** On a `PagePreview` slot, `onContextMenu` →
  `preventDefault()` → open `CardSlotContextMenu` at the event `(x,y)`. Scoped to
  slots only (exactly `CardSlot.handleContextMenu`) — the **browser-default menu is
  untouched everywhere else** (hard constraint).
- **Touch — long-press.** Reuse the existing `useLongPress` (500ms, cancels on
  > 10px move) on each slot; opens the same menu at the touch point. Long-press vs.
  > drag is disambiguated by the same movement cancel (E11/E13).
- **Visible cue (the net-new bit — D22).** A small **`⋯` affordance** on each slot
  tells touch users a menu exists (a menu with no visible trigger is undiscoverable
  on touch). Tapping `⋯` opens the same menu anchored to the button's rect.
  Revealed on hover/focus (desktop), **persistent on touch / once any menu-capable
  state exists.** Placement (RULED 2026-07-22): the **BOTTOM-RIGHT corner of each
  slot tile — its own corner**, deliberately separated from E24's flip (top-right)
  to avoid mis-taps on phone. Corner map: E8 checkbox = top-left, E24 flip =
  top-right, D22 `⋯` = bottom-right. This **revises E9's "gesture-invoked, no
  visible three-dots button"** stance (the owner wants a touch-visible cue) — see
  D22.
- **Actions.** The single `getCardSlotMenuActions` list (E9's extended version:
  Jump to version · Set back face… · Change query · Set quantity… · Duplicate ·
  Add to selection · Disable slot · [Unfilter printing] · Delete). This funnel
  round adds **no new action** — it only ensures the list is reachable on /display
  via all three triggers (right-click, long-press, `⋯`), plus **Shift+F10 /
  ContextMenu key** on a focused slot (E13/E16, unchanged).

---

## F7 — ADOPTION BOUNDARY (required section)

Names exactly which components are **base editor** vs. **vote layer**, the **props
seam** where the vote layer attaches, and **what votes-off means per element.**

### 7.1 Base editor vs. vote layer, per element

| Element                                  | Base editor (votes-off, always present) | Vote layer (attaches over base)                | Props seam                                |
| ---------------------------------------- | --------------------------------------- | ---------------------------------------------- | ----------------------------------------- |
| Funnel head A (count · active · Filters) | full                                    | —                                              | —                                         |
| Per-axis segmented chips B (F2)          | filter via `chip.matches` (metadata)    | SUGGESTED rendering per chip (F3.2)            | `voteLayer.suggestedTagNames(card)`       |
| Advanced filters B′ (E4)                 | full (Sort/Jump/Source/DPI…)            | —                                              | —                                         |
| Awareness line C (F4a)                   | **absent**                              | present when ≥1 chip active                    | `voteLayer.awarenessCopy`                 |
| Survivors grid D + disclosure (F1)       | full                                    | —                                              | —                                         |
| Pick a survivor                          | sets slot image only                    | + support-on-pick, reset, ack, retract (F4b–d) | `voteLayer.onImplicitSupport`             |
| Chip SUGGESTED state (F3.2)              | **absent** (all SETTLED/plain)          | dashed `⌇` unconfirmed chips                   | `suggestedTagNames` returns `[]` when off |
| Center context menu (F6)                 | full (base editing actions)             | — (menu is not vote-gated)                     | —                                         |

### 7.2 The single attach seam

`voteLayer?: VoteLayerProps | undefined` on the `layout="stacked"`
`SelectVersionResults` (composed by `DisplayPage`). `undefined` ⇒ base funnel.
`CardDocument.tagVoteStatuses` being optional is the data-side half of the same
seam. **No shared component gains a required prop; every addition is additive,
optional, behavior-preserving** (the /editor GridSelector modal, which never
passes `voteLayer`, is unchanged).

### 7.3 REUSE INVENTORY (existing component vs. new, per element)

| Element                     | Reused existing                                                                                                               | Net-new                                                                | Fork?                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------- |
| Chip taxonomy / axes        | `attributeChips.ts` `EXCLUSION_GROUPS` + `STANDALONE_CHIPS` + `filterCandidatesByChipStates` + `getAutoTagChips`              | axis-metadata wrapper to drive segmented render + membership           | **No**                                                          |
| Segmented axis control      | react-bootstrap `ToggleButtonGroup`/`ToggleButton` (already in `DisplayPage.tsx`)                                             | thin per-axis mapping                                                  | **No**                                                          |
| Chip button render / states | `attributeChipRender.tsx` (`confidenceFill`, `leanTooltip`, `renderAttributeChip`) as the SUGGESTED-lean precedent            | SETTLED/SUGGESTED segmented skin (dashed `⌇`)                          | **No** (skin, not fork)                                         |
| Funnel container            | `SelectVersionResults.tsx` `layout="stacked"` (E3 additive)                                                                   | fill in stacked render (A/B/B′/C/D)                                    | **No**                                                          |
| Advanced filters B′         | `GridSelectorFilters.tsx` `hiddenSections`/stacked (E3/E4 additive)                                                           | —                                                                      | **No**                                                          |
| Survivors grid / tiles      | `SelectVersionResults` `SelectVersionTile`/`MemoizedEditorCard`; count from `useGridSelectorSearch.sortedFilteredIdentifiers` | count-proportional tier picker                                         | **No**                                                          |
| Implicit vote cast/retract  | `useTagVoting` (`APISubmitTagVote`, `RETRACT_POLARITY` sentinel); `ConfirmChip` cast path                                     | `onImplicitSupport` wiring pick→support→reset→ack; retract-on-reselect | **No** (`ConfirmChip` two-tap **retired** on this surface, D20) |
| Context menu                | `CardSlotContextMenu.tsx` + `getCardSlotMenuActions.ts` + `useLongPress` (E9 extended)                                        | wire onto `PagePreview` slots + `⋯` cue (D22)                          | **No**                                                          |
| Post-pick ack               | `Toasts` / D17 pill visual family                                                                                             | inline `aria-live` ack strip                                           | **No**                                                          |

---

## 2. Per-breakpoint behavior (390 / tablet / 1400)

Container placement is inherited (§1 table / D-spec §4.1); the funnel's own
adaptation is vertical-budget + touch-target.

- **Phone (390) — bottom sheet 72vh.** Head A is **sticky** at the sheet top
  (count · active pills · `▸ Filters`) so narrowing controls stay reachable while
  the survivors scroll under it. Axis segmented rows wrap within their row if the
  three segments exceed the width; `ToggleButton` min-height 44px (thumb target —
  matches `attributeChipRender.tsx`'s existing 44px floor). Count-proportional
  disclosure matters most here: `N>8` still shows chips but the grid is the dense
  3-col; `N≤2` hides chips and the hero tile fills the tight sheet. Awareness line
  C is one wrapping line above the grid. Context-menu `⋯` cue is **persistent**
  (touch); long-press also works.
- **Tablet (768–991) — start drawer 380px.** Same funnel; full drawer height gives
  room, so `N>8` chips + a medium grid coexist without A needing to stick (it may
  still stick for consistency). `⋯` persistent (assume touch); right-click also
  available on hybrid devices.
- **Desktop (1400) — inline left 380px, sticky.** Full rail height; B and B′ can
  both be expanded at `N>8` with the dense grid below. `⋯` reveals on hover;
  right-click is the primary menu trigger. Awareness line C sits inline; the ack
  strip fades in the head region.

No horizontal overflow at any width — the funnel is a single 360–380px column that
scrolls vertically inside the rail's own `overflow-y:auto` (D-spec §4.1).

---

## 3. Change inventory (file-level, additive/optional — every existing caller preserved)

- **XF1** `attributeChips.ts` — add axis metadata so the funnel can render
  segmented per-axis groups + membership: an `AXES` descriptor (`Border`
  exclusive, `Frame` exclusive, `Treatment` multi) over the existing
  `EXCLUSION_GROUPS`/`STANDALONE_CHIPS` (no taxonomy change); a
  `chipMembershipState(candidates, tagName) → "settled"|"suggested"|"metadata"`
  helper (F3) reading `tags`/`tagVoteStatuses`. Pure functions; no behavior change
  to existing callers.
- **XF2** `SelectVersionResults.tsx` — the `layout="stacked"` branch (E3) renders
  the funnel: head A, axis-grouped chips B via `ToggleButtonGroup` (replacing the
  flat `FilterChipBar` on this surface), E4 advanced disclosure B′, awareness line
  C, survivors D at the F1 count-proportional tier. **Fix the stale blue active
  fill** `rgba(13,110,253,0.25)` → the theme accent (`var(--bs-primary)` /
  `#df6919`). Modal (`layout="sidebar"`) path unchanged.
- **XF3** `SelectVersionResults.tsx` — additive `voteLayer?: VoteLayerProps`
  (F5/F7 seam). When absent: base funnel (no SUGGESTED, no awareness, no
  support-on-pick). Retire `ConfirmChip`/`suggestedActiveTagNames` two-tap on this
  surface (D20), folding its cast path into `onImplicitSupport`.
- **XF4** new `attributeChipRender.tsx` skin (or a sibling) — SETTLED/SUGGESTED
  segmented button styling (dashed `#df6919` + `⌇` for suggested); reuse
  `leanTooltip` copy discipline ("not confirmed").
- **XF5** `useGridSelectorSearch.ts` — expose the survivor count (already computed
  as `sortedFilteredIdentifiers`) to drive the F1 disclosure tier; additive read,
  no new state. `initialSettingsVisible=false` (E3) governs B′.
- **XF6** `DisplayPage.tsx` (left rail) — compose the funnel: pass `layout="stacked"`
  - (when votes on) `voteLayer` wiring `onImplicitSupport`→`useTagVoting` cast
    (`source="select-version-implicit"`, polarity +1) → reset `chipStates` → fire
    ack; hold last-pick `supportTags` for retract-on-reselect (F4d).
- **XF7** `DisplayPage.tsx` (center) — wire `PagePreview` slot `onContextMenu`
  (preventDefault, open `CardSlotContextMenu` at x,y) + `useLongPress` + the `⋯`
  cue button (F6/D22); mount the existing menu with the E9 action list. (This row
  overlaps E-spec X8; here it is scoped to the menu-trigger surfacing + the cue.)
- **XF8** `PagePreview.tsx` / `PagePreviewSlotContent` — additive optional
  `onSlotContextMenu?(index,x,y)` + a `showMenuCue?: boolean` slot flag (the `⋯`).
  Absent ⇒ renders as today (E-spec X7 already adds the sibling interaction
  props; this adds the cue flag). Behavior-preserving.
- **XF9** post-pick ack — reuse `Toasts` or an inline `aria-live` strip in the
  head A region (no new component).
- **XF10** tests — Playwright/RTL: axis segmented render (exclusive within Border,
  multi within Treatment); SUGGESTED chip dashed + `⌇` only when
  `tagVoteStatuses==="suggested"`; **votes-off**: no SUGGESTED, no awareness, pick
  casts no vote; **votes-on**: pick under active chips casts support + resets +
  acks, reselect retracts; count-proportional tiers at N=1/5/12/0; center
  right-click + long-press + `⋯` all open the menu; browser-default menu intact
  off-slot.
- **XF11** `common/tagDisplayNames` — no change (funnel uses `useTagDisplayName`
  for axis/chip labels, as `FilterChipBar` already does).
- **XF12** docs — `docs/features/printing-tags.md` questionFeed/select-version
  section gains the implicit-support-on-pick source + retraction note at build
  time (task-end doc edit-in-place, per CLAUDE.md).

---

## 4. Owner decisions (D-ledger, continuing D19)

- **D20 — Implicit support is the PICK ITSELF (one gesture), not a second tap.**
  The existing two-tap `ConfirmChip` ("Looks {tag}? ✓ ✕") is retired on the
  Select Version surface. Picking a card while chips are active casts the bounded
  supporting vote for the active tags the card satisfies-via-suggested, resets the
  filters, and shows a brief fading ack; re-picking retracts. Awareness line C
  discloses this _before_ the pick; retraction needs no separate UI. **Rationale:**
  the owner's ask is explicitly "the pick supports … then filters reset" — a
  survey-free, one-gesture mechanic. **RULED 2026-07-22: AUTOMATIC support-on-pick
  confirmed** — the pick itself is the vote; there is **no** one-tap-offer variant.
  Awareness line C + trivial re-pick retraction are the safety, and the backend
  weights implicit-source votes low.
- **D21 — Count-proportional disclosure tiers refine E4's hard `compressed=true`.**
  `N>8` → axes shown + advanced expanded + dense compressed grid; `3–8` → axes
  shown + medium tiles; `≤2` → axes collapse to the head's active-pill summary +
  expanded hero tiles; `0` → empty/directed-help. **Axes stay visible while
  narrowing is still useful (many + some), collapsing only at few/none** —
  reviewed as better UX than hiding the primary filter at 8 results. **RULED
  2026-07-22: thresholds ACCEPTED as proposed (`>8` dense / `3–8` medium / `≤2`
  hero), with the requirement that they ship as NAMED CONSTANTS** (e.g.
  `FUNNEL_DENSE_ABOVE = 8`, `FUNNEL_HERO_AT_OR_BELOW = 2`) so post-launch tuning
  is a one-line change — not inline magic numbers in the tier picker (XF5).
- **D22 — A visible `⋯` context-menu cue on each /display slot (revises E9).** E9
  specified "gesture-invoked, no visible three-dots button"; the owner now wants a
  touch-discoverable cue. **RULED 2026-07-22: the `⋯` cue sits BOTTOM-RIGHT of each
  slot tile — its OWN corner, deliberately separated from E24's flip button (which
  keeps the top-right) to avoid mis-taps on phone.** Corner map after this ruling:
  E8 selection checkbox = top-left, E24 flip = top-right, D22 `⋯` menu cue =
  bottom-right (bottom-left free). This resolves tension 5's corner-crowding — the
  three controls now occupy three separate corners rather than stacking two in the
  top-right. Revealed on hover/focus (desktop), persistent on touch.
- **D23 — Filter chips are positive-or-off on this surface (two-state), not the
  QuestionFeed's tri-state.** The QuestionFeed's chips cycle
  untouched→positive→negative→untouched (a describe-what-you-see vote). The
  _funnel_ filter wants "narrow to this / don't" — a segmented radio (exclusive
  axes) or checkbox (Treatment). Negative filtering isn't exposed here; it's a
  filter, not a survey. (The implicit vote on pick is separate and always
  positive/support.) Confirm no negative-filter need.
- **D24 — SUGGESTED state and implicit support exclude sensitive/moderation-gated
  tags.** A leaning-but-unconfirmed sensitive attribute must not surface a dashed
  chip or receive a support vote from a pick — sensitive tags are moderation-gated
  (docs/features/moderation.md). The funnel's `suggestedTagNames`/`supportTags`
  both filter sensitive tags out. Stated so it's approved, not assumed.

---

## 5. Conflicts / tensions (honest)

1. **F2/F3 vs. E3/E4's "kill the chip wall" (Bkg 1).** E3/E4 removed the always-on
   11-chip `FilterChipBar` from the visible surface because it was a height sink.
   The funnel brings chips back to the visible surface — but as **compact
   per-axis segmented rows, membership-filtered** (only axes with ≥1 survivor
   render), so a typical card shows 1–2 rows, not 11 chips. This is the owner's
   newer, explicit "one place for filtering" direction refining E3/E4's
   de-clutter; the height-sink failure is avoided by segmentation + membership +
   count-proportional collapse, not by hiding chips. Called out because it is a
   deliberate re-exposure of a surface a prior round demoted.
2. **D20 retires `ConfirmChip`.** The two-tap confirm is live code with tests. The
   funnel subsumes its cast path; the tests migrate to the support-on-pick
   assertions (XF10). Flagged so the implementer removes it deliberately, not by
   accident.
3. **Automatic vote on every qualifying pick.** Even bounded, an
   always-fires-on-pick vote is a stronger default than an explicit tap. **RULED
   D20: automatic confirmed** — the before-line (C) + trivial re-pick retraction
   are the accepted mitigations, and the backend weights implicit-source votes low.
4. **"finish" axis doesn't exist (F2/D23 note).** The task's example axis list
   includes "finish"; the catalog has no finish chip dimension. No fake axis was
   forged — **RULED: foil/finish stays a PRINT SETTING (`finishSettingsSlice`,
   right-rail Finish section, D11), NOT a vote/filter dimension.** Axes shipped:
   Border, Frame, Treatment only.
5. **`⋯` cue vs. corner-crowding (D22) — RESOLVED by the D22 ruling.** The three
   slot controls now occupy three separate corners (E8 checkbox top-left, E24 flip
   top-right, D22 `⋯` bottom-right); no corner stacks two controls. The mockup
   shows all three at true tile scale.

---

## 6. Open questions — ALL RULED 2026-07-22 (none open)

1. **D20 — automatic support-on-pick, or a one-tap offer?** → **RULED: automatic**
   (the pick is the vote; no one-tap variant).
2. **D21 count-proportional thresholds** (`>8` / `3–8` / `≤2`)? → **RULED:
   accepted as proposed, shipped as named constants** (one-line post-launch tuning).
3. **D22 `⋯` placement**? → **RULED: bottom-right of each tile** (own corner,
   separated from the flip).
4. **Finish filter axis**? → **RULED: no finish axis** — foil stays a print
   setting, not a vote/filter dimension.

No open questions remain; the spec is owner-ratified.

---

## 7. Mockup notes (`funnel-mockup.html`)

Self-contained (no CDN, vanilla JS, `file://`-openable). The fixed top **demo
strip** forces **Desktop / Tablet / Phone** at any window width via the proven
transform-scaled-frame mechanism from `display-mockup.html`/
`editor-completion-mockup.html` (§8): a single `CHUNKS` breakpoint stylesheet used
both inside media queries (Auto) and bare (forced); forced Desktop/Tablet render
as a `scale = innerWidth / frameWidth` zoomed-out preview with negative
`margin-bottom`, and because any transform makes the frame the containing block
for fixed descendants, the drawers scale with the frame — **the full composition
is visible on a ~390px phone.** Extra demo controls (do not disturb the strip):

- **Votes toggle** (F5) — flips the whole funnel votes-on ↔ votes-off; watch the
  SUGGESTED chips, awareness line C, and post-pick ack appear/disappear with zero
  layout breakage.
- **Results: many / some / few / none** (F1/D21) — flips the survivor count so the
  reviewer sees the count-proportional disclosure tiers (dense grid + expanded
  chips → medium → hero → empty/directed-help).
- **Pick a survivor** — demonstrates the F4 flow live: awareness line names the
  tags → pick casts support → chips reset → ack fades; a **Re-pick** shows the
  retraction copy.
- The per-axis segmented chips (F2) render as joined `ToggleButtonGroup`-style
  segments (Border/Frame radio-exclusive, Treatment multi), membership-filtered.
- A compact **center-slot strip** demonstrates F6: hover reveals the `⋯` cue;
  clicking `⋯` (or right-click) opens the real `CardSlotContextMenu`-styled menu;
  a note marks the long-press/touch path.

Theme values are the LIVE ones (§Theme fidelity): rail `#22303f`, panel/field
`#2B3E50`, secondary `#4E5D6C`, divider `#16202b`, accent `#df6919`, text
`#EBEBEB`, muted `#aab7c4`/`#8fa0b0`; the outer page field is drawn `#0f2537`
(live `$body-bg`) and labeled. Any element proposing a look change from current is
labeled in the mockup.

---

## 8. Verification

Playwright screenshots at **390px** and **1400px**, inspected, fixes applied; see
the completion report for what the screenshots caught. (No repo changes — artifacts
only.)
