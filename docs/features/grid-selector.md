# Grid selector (card version picker) & result card display

`GridSelectorModal.tsx` — the modal that lets a user pick between every
matched image for a card slot, seeing them all at once in a grid
(`CardResultSet.tsx` → `Card.tsx`). Also covers `Card.tsx`'s general
image-loading/error states, since those apply to every card render
across the app, not just inside this modal.

## Frontend-polish UX pass (PR-B, 2026-07-17)

Presentation/interaction fixes from the frontend-polish package's
"Search & Browsing" area (items 2, 8, 9, 14, 15). Item 11 (a
preview-before-commit affordance) was explicitly deferred — flagged as
touching the core one-tap selection interaction, needs a slower,
more isolated follow-up per the owner's Phase-2 direction.

- **Keyboard navigation** (`Card.tsx`): the clickable result-card wrapper
  (`BSCard`, plain react-bootstrap `Card`) was mouse-only — no `tabIndex`,
  no `role`, no way to Tab to a card or activate it with Enter/Space. Now
  conditionally focusable/keyboard-activatable, but **only** when
  `cardOnClick` is actually provided — a card with no click handler (e.g.
  a `DatedCard` on the What's New page) doesn't pretend to be a button.
  The single real `cardOnClick` call site (`CardResultSet.tsx`'s
  `CardGridCard`) ignores its event argument entirely, so re-invoking it
  from a `keydown` handler with a cast event is safe — see the comment at
  the call site if that call site ever changes. No visible-focus-style
  CSS was added here beyond the browser default outline (`.mpccard` has
  no `outline: none` override) — a more polished custom focus-visible
  treatment is PR-D's dedicated a11y-focus-states item, not duplicated
  here.
- **Modal autofocus** (`GridSelectorModal.tsx`): `onEntered` used to
  unconditionally try to focus the Jump-to-Version input via `focusRef`,
  even though that section is collapsed by default
  (`viewSettingsSlice`'s `jumpToVersionVisible` initial state is
  `false`) — `AutofillCollapse` keeps its children mounted (not
  unmounted) when collapsed, so the input element genuinely exists in the
  DOM, but calling `.focus()` on a collapsed-but-mounted input is a
  silent no-op in a real browser (it's not "focusable" per browser rules
  while effectively invisible). Now reads `jumpToVersionVisible` and only
  focuses the real input when that section is genuinely open; otherwise
  falls back to focusing the always-visible "Filters" toggle button
  (`settingsToggleRef`) so keyboard focus always lands somewhere real.
- **Mobile filters default** (`GridSelectorModal.tsx`): `settingsVisible`
  used to default to `true` unconditionally, splitting the filters and
  results columns 6/6 even on a narrow phone viewport, squeezing results
  into ~half the screen. Now defaults to `false` below Bootstrap's `sm`
  breakpoint (576px, `SmallViewportFiltersBreakpointPx`) via a lazy
  `useState` initializer reading `window.innerWidth` — purely an initial
  default, still user-toggleable either way via the same Filters button.
  Also added `flex-wrap` to the header's title+Filters-button flex
  container as a defensive fix for a title/button collision observed at
  narrow widths.
- **Slow image-load feedback** (`Card.tsx`): a card image stuck loading
  showed only a bare spinner indefinitely, with nothing distinguishing a
  slow-but-working fetch from a genuinely stuck one. Now shows a small
  "Still loading…" hint (`SlowLoadHintDelayMS = 6000`) alongside the
  spinner once a fetch has been pending that long, reset whenever loading
  finishes or the card identifier changes.
- **404/error placeholder restyle** (`Card.tsx`): a failed image fetch
  (a real production path — dead Google Drive links, not just a sandbox
  artifact) used to show `public/error_404*.png` — a solid-black asset
  that reads as a harsh black square at grid scale against the card's own
  `#4e5d6c` placeholder background. Replaced with a styled
  `ErrorPlaceholder` div (same `#4e5d6c` background, a subtle
  `exclamation-triangle` icon + "Image unavailable" text) instead of a
  static raster asset — real text instead of text baked into a PNG, and
  visually consistent with the card's own placeholder state. The
  `error_404*.png` files themselves were left in `public/` (not deleted —
  no longer referenced from code, but removing static assets wasn't part
  of this pass's scope).

## Select Version section (issue #167, Proposal H §4.4′)

The unified display page's (`/display`) rail's Select Version surface
(promoted + always open since the editor-completion package's left-panel
fidelity rebuild - see that section's own note below; was the "Choose
Image" accordion before that round) no longer renders the flat
`GridSelectorResults`/`CardResultSet` grid — it mounts
`SelectVersionResults.tsx`, which groups the same
candidate identifier list into the three ordered groups
`docs/proposals/proposal-h-unified-display-page.md`'s §4.4′ specifies,
and weaves in its three verification moments. **Scope: this replaces the
results renderer for `/display`'s embedded picker ONLY** —
`GridSelectorModal.tsx`'s classic modal (the editor grid's version picker,
and every other caller of `GridSelectorResults`) is completely
unchanged; `GridSelectorResults.tsx`/`CardResultSet.tsx` still exist and
still back that modal.

- **Grouping** (`selectVersionGrouping.ts`, pure, unit-tested directly —
  no React/Redux): buckets candidates into `canonical` (one cluster per
  distinct real printing, keyed by `canonicalCard`/`suggestedCanonicalCard`'s
  own `identifier` — the same Scryfall printing UUID regardless of which
  field happens to be populated for a given copy, so a resolved copy and
  a still-suggested copy of the exact same printing cluster together
  automatically), `nonCanonical` (cards with no printing data but a
  resolved no-match reason tag — `altered-frame`/`custom-art`/`ai-art`,
  three of the six seeded reason tags — grouped by that tag), and
  `unknown` (the residue: no printing data, no classifying tag — kept
  flat, not representative-grouped, per the spec's own wording).
  Representative selection within a cluster is the highest-DPI copy,
  ties broken toward a resolved copy over a suggested one. A printing
  cluster's `status` is "resolved" the instant ANY member of it has a
  human-resolved `canonicalCard` — the edge case this needed a real
  decision on: `canonicalCard`/`suggestedCanonicalCard` are per-copy,
  not per-printing, so one upload of a printing can be community-resolved
  while a different upload of the exact same printing is still merely
  machine-suggested. Ordering: the slot's own requested printing (if
  present in the result set at all) sorts first regardless of its own
  status, then resolved printings, then suggested ones.
- **Moment (a), suggested-printing Confirm**: a suggested-status
  printing group's representative mounts `DeckbuilderConfirmAffordance.tsx`
  verbatim (same component, same votes, unchanged) — via a `SearchQuery`
  _synthesized_ from the representative's own `suggestedCanonicalCard`
  (not the slot's real search query). This works because
  `DeckbuilderConfirmAffordance`'s existing gate
  (`isUnconfirmedCanonicalImport`) only needs "query names a printing AND
  `getPrintingMatchLabel` returns null," and that function always returns
  null while `printingTagStatus` isn't `Resolved` — exactly the
  precondition for `suggestedCanonicalCard` to exist in the first place.
  No fork of the component was needed. Its `onOpenGridSelector` callback
  is a no-op here (there's no separate modal to open — this tile is
  already inside the picker).
- **Moment (b), art-as-filter** — **sidebar/modal layout only** (see the
  FUNNEL round below, which replaces this on the `/display` rail): a
  plain binary toggle-chip row (`FilterChipBar`, NOT
  `AttributeChipPanel.tsx`'s tri-state vote-casting ring — a new, thin
  component per the spec's own component table), built on
  `attributeChips.ts`'s existing `ALL_ATTRIBUTE_CHIPS` taxonomy/display
  names. A "More like this" button on any tile with at least one
  resolved attribute tag seeds the filter from that card's own `tags`.
- **Moment (c), filtered-selection confirm chip** — **sidebar/modal
  layout only**, retired on the rail by D20 (see below): after selecting
  a card while a filter tag is active, a `ConfirmChip` appears if that
  specific card's `tagVoteStatuses[tagName]` is `"suggested"` (not yet
  resolved) for the active tag — one tap casts a real `APISubmitTagVote`
  (`voteSurface: "select-version"`, a new value alongside the existing
  `"question-feed"`/`"deckbuilder"`), dismissing costs nothing. Tracked
  in local component state (not persisted, not module-level) — resets
  whenever the rail's `Rail` component remounts for a new slot selection
  (`DisplayPage.tsx`'s own `key`-based remount).
  - **Deviation from the spec's literal text (documented, not silent)**:
    the spec's Data-dependencies table describes moment (b)'s filter as
    matching only against `Card.tags` (resolved-only), but moment (c)
    can only ever fire if the filter itself lets a merely-`"suggested"`
    match through — a tag that passed a resolved-only filter is by
    definition already resolved on that card, so the confirm-chip
    scenario the spec describes could never actually occur under a
    strictly-resolved-only filter. `filterByActiveAttributeTags` in
    `SelectVersionResults.tsx` therefore matches on resolved OR
    suggested per active tag — the only reading that makes the spec's
    own (b) and (c) passages internally consistent.

## The art-picker FUNNEL (funnel-spec.md F1-F7, D20-D24 — supersedes moments (b)/(c) on the rail)

The owner-ratified funnel round replaced the flat moment-(b) chip wall
and the two-tap moment-(c) confirm on the `/display` rail's `Select Version` surface (`layout="stacked"`) with a single top-to-bottom
column: head (count · active-tag pills · Filters disclosure) → per-axis
segmented chips → the existing E4 advanced-filters disclosure →
an implicit-vote awareness line → a count-proportional survivors grid.
**The `layout="sidebar"` branch (the theoretical /editor modal caller,
not actually wired anywhere today) is byte-for-byte unchanged** — it
still renders the flat `FilterChipBar` and the two-tap `ConfirmChip`
described above.

- **Per-axis segmented chips** (`attributeChips.ts`'s `FUNNEL_AXES`):
  Border and Frame render as radio-exclusive `ToggleButtonGroup`s (one
  segment active at a time; re-tapping the active segment clears the
  axis back to "any" — D23, since a native radio input doesn't fire a
  change event for a click on an already-checked option, this is
  handled on the `ToggleButton`'s own `onClick`, ahead of the group's
  `onChange`); Treatment (Full Art/Borderless/Showcase/Extended/Etched)
  renders as an independent-checkbox group. Only axes with ≥1
  surviving candidate render at all (`chipMembershipState`, computed
  over the OTHER axes' current filter — never the axis's own selection,
  so picking Black doesn't make White/Silver permanently vanish from
  their own axis).
- **Three chip states** (F3): SETTLED (some survivor resolves the tag —
  `card.tags`), SUGGESTED (every carrying survivor only has it via
  `card.suggestedFilterTagNames` — see the compliance note below, dashed
  border + trailing `⌇`, vote-layer-gated), or absent (no surviving
  candidate carries the attribute at all). **Deviation from the spec's
  ground-truth text (documented, not silent)**: the spec describes
  filtering/membership as reading raw Scryfall fields via
  `chip.matches()`/`filterCandidatesByChipStates`
  (`attributeChips.ts`), which are built for the distinct
  `PrintingCandidate` schema (`QuestionFeed.tsx`'s own feed items) — the
  `CardDocument`s this rail actually has carry no `borderColor`/`frame`/
  `fullArt`/etc fields at all. Every chip in this taxonomy is already
  Tag-consensus-backed (this file's own top-of-file comment), so
  membership/filtering here reads `tags`/`suggestedFilterTagNames`
  instead — functionally equivalent, and the spec's own "metadata"
  membership state (F3.3) stays honestly unreachable, exactly as its own
  carve-out anticipates.
  - **Compliance fix (owner-ratified condition 6, caught in PR #329
    review)**: the SUGGESTED read and F4b's implicit-vote support set
    originally sourced from `card.tagVoteStatuses[tag] === "suggested"`.
    That field is a source-agnostic collapse — the backend serializer
    maps BOTH `CONTESTED` and `UNRESOLVED` to the same `"suggested"`
    string, with no implicit-vote exclusion and no weight floor — so a
    tag with ONLY implicit votes (or one sub-threshold machine vote, or
    a REJECT-leaning split) also read `"suggested"` there. Since F4b
    casts a NEW implicit vote for every SUGGESTED chip a pick satisfies,
    sourcing membership off `tagVoteStatuses` let an already-implicit
    signal seed MORE implicit votes for itself — the exact self-seeding
    loop condition 6 forbids. Fixed: both the SUGGESTED membership read
    (`attributeChips.ts`'s `chipMembershipState`/
    `candidateSatisfiesAttributeTag`) and the implicit-support set
    (`SelectVersionResults.tsx`'s `handleSelect`, via the `voteLayer. suggestedTagNames` seam) now read `card.suggestedFilterTagNames`
    instead — the backend's own implicit-excluded, floor-gated,
    already-RESOLVED/CONTESTED/PENDING_APPROVAL/SENSITIVE-excluded
    computation (`get_suggested_filter_tags_overlay`,
    docs/features/printing-tags.md). The SETTLED read (`card.tags`) is
    unaffected — resolved facts carry no such loop risk. `null`/absent
    `suggestedFilterTagNames` (the backend wiring for this field lands
    in a parallel PR — until deployed the wire value is `null`)
    degrades to "no suggested carriers," never a crash — the funnel
    stays fully functional on settled/metadata chips alone. Pinned as a
    regression test (`SelectVersionResults.test.tsx`'s "condition 6"
    case + `tests/SelectVersionSection.spec.ts`'s matching e2e test):
    a card whose `tagVoteStatuses` says `"suggested"` but whose
    `suggestedFilterTagNames` excludes the tag renders no suggested
    chip and casts no implicit vote for it.
- **Count-proportional disclosure** (F1/D21, named constants
  `FUNNEL_DENSE_ABOVE = 8` / `FUNNEL_HERO_AT_OR_BELOW = 2`): `>8`
  survivors → axes shown + advanced filters auto-expanded once + dense
  ~72px tiles; `3–8` → axes shown + medium ~88px tiles; `≤2` → axes
  collapse to the head's active-pill summary + expanded (`compressed= false`) ~112px hero tiles; `0` → an empty state with a "Clear filters" link.
  **Owner fix round (2026-07-23, "the elements of the cardpicker are
  too large still")**: `medium`/`hero` had no design-doc grounding
  (invented during the funnel round itself, unlike `dense`'s
  mockup-sourced 72px) and had drifted to 104px/150px - tightened to
  88px/112px (`FUNNEL_TIER_TILE_WIDTH_REM`,
  `SelectVersionResults.tsx`), and the tile-wrapping rows' gap dropped
  from Bootstrap's `gap-2` (8px) to `gap-1` (4px) so more tiles fit per
  row at the rail's ~380px width. `dense`'s 72px is untouched - it
  already matched the reference.
  **Same PR, follow-up owner round ("keep the ordering, but drop the
  separator please")**: the DOM ordering (canonical → non-canonical →
  unknown, still `selectVersionGrouping.ts`'s own ordering, untouched)
  used to read as visually separate blocks because each per-group
  wrapper div (`renderPrintingGroup`/`renderReasonTagGroup`) carried its
  own `mb-2` bottom margin. That margin is dropped - no other DOM
  change - so the rail now reads as one continuous grid with no visible
  gap/seam at a group boundary. Those wrapper divs never carried any
  `role="group"`/`aria-label` grouping semantics to begin with, so
  nothing accessibility-bearing needed preserving.
- **D20 implicit vote — the pick IS the vote, no second tap.** Picking a
  candidate while ≥1 chip is active computes `supportTagNames` (active
  tags the candidate satisfies ONLY via a suggested/unconfirmed vote,
  never an already-resolved one) and calls the `voteLayer. onImplicitSupport(candidate, supportTagNames)` seam on EVERY pick
  (even with an empty set, so the caller can retract a PREVIOUS pick's
  support — see below). When `supportTagNames` is non-empty: the active
  chips clear and a brief (~2.6s) `aria-live` ack fades in ("Supported
  {tags} ✓ — filters cleared"); an awareness line (`ⓘ Picking a card here supports {tags} for it. Undo by re-picking.`) discloses this
  BEFORE the pick, whenever ≥1 chip is active and the vote layer is on.
  Copy always says "supports," never "confirms." The two-tap
  `ConfirmChip` is retired on this surface (its logic folds into this
  automatic mechanic).
- **Retraction = deselection (F4d)**: `DisplayPage.tsx`'s own
  `handleImplicitSupport` holds a per-slot (`face`-`slot` keyed)
  `useRef` of the last-cast `{identifier, tagNames}` — deliberately
  living ABOVE `<Rail>` (which fully remounts per slot selection), so it
  survives a slot's own component teardown. On every call: retracts
  whatever the PREVIOUS pick cast (`APIRetractImplicitVote`, one call
  per tag), then casts the new `supportTagNames`
  (`APICastImplicitVote`, one call for the whole set) if any. Both
  calls are fire-and-forget — a refused/failed implicit vote never
  surfaces a user-visible error (the pick itself always succeeds).
- **F5 — votes-off completeness (adoption requirement)**: a single
  optional `voteLayer?: VoteLayerProps` prop
  (`onImplicitSupport`/`suggestedTagNames`/`awarenessCopy`) is the
  funnel's entire vote-layer attach seam. `undefined` (any caller that
  doesn't supply it) renders a complete, votes-off, metadata-only
  filter UI: no SUGGESTED chips, no awareness line, no vote on pick, no
  reset/ack. `DisplayPage.tsx` is the one caller that supplies it today
  (always, in production); `SelectVersionResults.test.tsx` covers the
  `voteLayer=undefined` path directly, since there's no live in-app
  toggle to reach it end-to-end.
- **Context menu on `/display` slots (F6/D22)**: `PagePreview.tsx`
  gained additive `onSlotContextMenu?(index, x, y)` — right-click
  (`preventDefault`ed, scoped to slots only), long-press
  (`useLongPress`, extracted per-slot into `PagePreviewSlotEl` so the
  hook can be called once per slot), and a new visible `⋯` cue button
  (bottom-right of each tile — its own corner, deliberately separated
  from the top-left/top-right corners a future selection-checkbox/flip
  button would use) all open the SAME existing `CardSlotContextMenu` +
  `getCardSlotMenuActions` (Change Query/Duplicate/[Unfilter
  Printing]/Delete — no new action). `DisplayPage.tsx` mounts one
  shared menu instance for whichever slot was triggered. Absent
  `onSlotContextMenu` (every other `PagePreview` caller, e.g.
  `PDFGenerator`'s fast preview), renders with zero behavior change —
  no cue, no long-press handlers, the browser's native menu untouched.
- **Open items, not resolved here (owner call needed)**: (1) group 2's
  sub-order beyond "frame type first" — this build picked
  `altered-frame > custom-art > ai-art`
  (`SELECT_VERSION_REASON_TAG_PRIORITY`), an arbitrary but documented
  choice, since the spec doesn't pin `custom-art` vs. `ai-art`'s relative
  order.
- **Resolved by the editor-completion package's left-panel fidelity
  rebuild (E2/E3/L4)**: the rail heading is now genuinely "Select
  Version" (the once-deferred pure-copy rename above), promoted to an
  always-visible, always-open surface with no `AutofillCollapse` wrapper
  at all - it's no longer one accordion among several (D3: art selection
  is the primary surface, not something a user has to expand). The same
  round also fixed the rail-specific fidelity breakages this section used
  to carry: `initialSettingsVisible={false}` on `useGridSelectorSearch`
  (Filters starts collapsed in the rail regardless of viewport width -
  previously auto-opened cramped on any desktop-width rail) and
  `layout="stacked"` on `SelectVersionResults` (the Filters disclosure
  renders full-width, stacked, in the rail's own scroll container instead
  of the modal's `Col lg={3}` sidebar split - "Jump to Version" no longer
  wraps vertically, bottom controls no longer clip at the rail edge). The
  always-on `FilterChipBar` wall moved INTO the Filters disclosure for
  the stacked/rail caller (still reachable, no longer a permanent
  multi-row height sink atop every result); `GridSelectorFilters` gained
  an additive `hiddenSections` prop the rail uses to drop "View"
  (Group-by/Compressed - both redundant in the rail: it groups results
  itself, and the 380px rail already forces compact tiles). Every one of
  these is additive/optional and defaults to today's modal behavior -
  `GridSelectorModal.tsx`'s own caller passes none of them and is
  unaffected.
  - **CORRECTION (owner live-review, "Select Version has oversized
    dropdowns")**: the "the 380px rail already forces compact tiles"
    claim just above was wrong - confirmed live via a real screenshot
    combined with a `getBoundingClientRect()` diff, one candidate tile
    rendered at ~300px wide (nearly the full rail width), not compact
    at all. Root
    cause: `SelectVersionTile`'s own wrapper (`SelectVersionResults.tsx`)
    set `width: compressed ? "auto" : undefined` - a no-op, not a real
    constraint. A plain block-level `<div>` in normal flow with
    `width: auto` fills its containing block exactly the same as one
    with no width declared at all (only flex/grid items, floats, or
    absolutely-positioned boxes actually shrink-to-fit on `auto` - a
    static block never does), and every printing-group/reason-tag-group
    wrapper was a plain block div, one per line, with no shared row to
    even shrink within. `compressed` genuinely does something on
    `MemoizedEditorCard` itself (hides the header/footer text - see
    `Card.tsx`), just nothing that constrains overall tile WIDTH; that
    always came from whatever grid/row wrapped a tile (e.g.
    `CardResultSet.tsx`'s `CardRow` `variant="embedded"`, built for
    exactly this narrow-rail scenario but never wired into
    `SelectVersionResults.tsx`). Fixed directly: `SelectVersionTile`'s
    wrapper now gets a real fixed `4.5rem` (72px - the owner-approved
    editor-completion mockup's own `.version-grid .card63` value, not a
    guessed number) width when `compressed`, and each group's tiles
    (representative + expanded "+N more", and the flat "unknown" group)
    render inside a `d-flex flex-wrap gap-2` row instead of stacking one
    per line, so multiple compact tiles now sit side by side per the
    mockup's own density.

## Key files

- `frontend/src/features/gridSelector/GridSelectorModal.tsx`,
  `GridSelectorFilters.tsx`, `JumpToVersion.tsx` — the classic modal
  variant (unchanged by issue #167)
- `frontend/src/features/gridSelector/GridSelectorResults.tsx`,
  `CardResultSet.tsx` — the flat grid renderer, still backing the modal
  variant above; no longer used by `/display`
- `frontend/src/features/gridSelector/SelectVersionResults.tsx`
  (+ `SelectVersionResults.test.tsx`), `selectVersionGrouping.ts`
  (+ `selectVersionGrouping.test.ts`) — the `/display`-only Select
  Version section (issue #167) and its FUNNEL round (F1-F7)
- `frontend/src/features/attributeChips/attributeChips.ts` —
  `FUNNEL_AXES`, `chipMembershipState`, `candidateSatisfiesAttributeTag`
  (funnel round, additive to the existing chip taxonomy)
- `frontend/src/features/pdf/PagePreview.tsx` — `onSlotContextMenu`,
  the extracted `PagePreviewSlotEl`, the `⋯` menu cue (funnel round F6)
- `frontend/src/features/display/DisplayPage.tsx` — the funnel's
  `voteLayer` wiring (`handleImplicitSupport`, the retract-on-reselect
  ref) and the center-sheet context-menu mount
- `frontend/src/common/schema_types.ts`, `frontend/src/store/api.ts` —
  hand-maintained `CastImplicitVoteRequest`/`RetractImplicitVoteRequest`
  types + `APICastImplicitVote`/`APIRetractImplicitVote` (the frontend
  half of PR #325's backend contract)
- `frontend/src/features/card/Card.tsx` (+ new `Card.test.tsx`),
  `CardSlot.tsx`
- Tests: `frontend/tests/GridSelectorModalVariants.spec.ts` (keyboard nav
  - a large-grid focus-perf check, autofocus fallback, mobile filters
    default — merged from the former `GridSelectorModalAccessibility.spec.ts`
    and `GridSelectorModalMobile.spec.ts`), `frontend/tests/CardImageStates.spec.ts`
    (error placeholder + slow-load hint), `frontend/tests/SelectVersionSection.spec.ts`
    (grouping/ordering, moment (a)/(b)/(c) behavior on the sidebar layout — issue
    #167 — plus the funnel's implicit-cast/reset/ack and retract-on-reselect
    end-to-end flows), `frontend/src/features/gridSelector/SelectVersionResults.test.tsx`
    (axis exclusivity, membership-driven axis rendering, disclosure tiers,
    SUGGESTED-chip rendering, F5 votes-off completeness), `frontend/tests/ DisplayPage.spec.ts` (F6: right-click + the `⋯` cue opening the shared
    context menu on the center sheet)

## Known gaps

- Item 11 (preview-before-commit) from the same Phase-1 survey was
  explicitly deferred, not built — see the frontend-polish PR-B
  description for the full reasoning.
- The perf check for item 2 covers keyboard-focus responsiveness against
  a 150-synthetic-card grid in a mocked sandbox; it doesn't reproduce
  real backend/ES latency or real image-CDN load timing at that scale.
- Issue #167's Select Version section: see its own "Open items" bullet
  above for the one still-owner-decidable gap (group 2's ai-art/custom-art
  order). The rail's own Filters-column cramping (the previous bullet
  here) was fixed by the editor-completion package's left-panel fidelity
  rebuild - see this section's own "Resolved by..." paragraph above
  (`layout="stacked"` drops the `Col lg={3}` sidebar split for the rail
  caller specifically; `GridSelectorModal.tsx`'s own sidebar layout is
  unchanged, so this is a rail-only fix, not a change to the shared
  column-breakpoint default itself).
