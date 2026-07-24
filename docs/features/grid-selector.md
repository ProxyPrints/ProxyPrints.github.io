# Grid selector (card version picker) & result card display

`GridSelectorModal.tsx` — the modal that lets a user pick between every
matched image for a card slot, seeing them all at once in a grid
(`CardResultSet.tsx` → `Card.tsx`). Also covers `Card.tsx`'s general
image-loading/error states, since those apply to every card render
across the app, not just inside this modal.

**Post-route-swap reachability (2026-07-24, issue #272 parity wave 3):**
per-slot picking on the unified `/editor` page goes entirely through the
rail's own Select Version section below (a different component,
`SelectVersionResults.tsx` — no modal, no grouping/filters-sidebar/Jump-to-
Version UI of its own). `GridSelectorModal.tsx` itself has exactly one
surviving mount post-swap: `CardbackToolbarButton`/`CommonCardback.tsx`'s
project-wide cardback picker (testid `cardback-grid-selector`, title
"Select Cardback"), reachable from the right rail's Cardback button once
the project is non-empty. It's otherwise unchanged and fully generic (a
bare `imageIdentifiers` array + `onClick` callback) — every grouping/
filter/keyboard/mobile-viewport behavior below applies identically
regardless of which caller's identifiers feed it. `GridSelectorModal.spec.ts`/
`GridSelectorModalVariants.spec.ts`/`CardSlot.visual.spec.ts`'s own two
grid-selector snapshot tests were re-ported onto this cardback mount in
that wave — see `openDisplayCardbackGridSelector` (`frontend/tests/ test-utils.ts`) for the helper and its own comment for the full rationale.

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
`docs/proposals/proposal-h-unified-display-page.md`'s (historical doc —
see its own banner) §4.4′ specifies,
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
  **On the `/display` rail's stacked (funnel) layout specifically**
  (2026-07-23 continuous-grid round): this same, still-completely-
  unmodified mount is now visually a small `transform: scale(0.72)`
  "confirm ribbon" overlay in the tile's corner instead of a full block
  rendered below the tile — see
  [`display-left-rail.md`](display-left-rail.md)'s "Select Version —
  continuous grid" section for the full affordance-by-affordance
  mapping; the sidebar/modal layout keeps the original full-size mount
  described above, unchanged.
- **Moment (b), art-as-filter** — **sidebar/modal layout only** (see the
  FUNNEL round below, which replaces this on the `/display` rail): a
  plain binary toggle-chip row (`FilterChipBar`, NOT
  `AttributeChipPanel.tsx`'s tri-state vote-casting ring — a new, thin
  component per the spec's own component table), built on
  `attributeChips.ts`'s existing `ALL_ATTRIBUTE_CHIPS` taxonomy/display
  names. A "More like this" button on any tile with at least one
  resolved attribute tag seeds the filter from that card's own `tags`.
- **Moment (c), filtered-selection confirm chip** — **sidebar/modal
  layout only**, retired on the rail by the [implicit-vote-is-the-vote
  decision](#implicit-vote-is-the-vote) (see below): after selecting
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

## The art-picker FUNNEL (supersedes moments (b)/(c) on the rail)

Spec items below are this section's own **F1-F7** numbering (distinct from
`proposal-h-display-layout-spec.md`'s own F1-F14 change-inventory rows).
The five owner decisions this round locked (2026-07-21/22, PR #329) are
written out in prose at each relevant bullet below and are no longer
cross-referenced by bare letter-number — see
[`docs/reference/funnel-spec.md`](../reference/funnel-spec.md) for the
full raw ratification record (ground truth, per-breakpoint behavior,
file-level change inventory, and the "all open questions ruled"
closeout) this section summarizes.

The owner-ratified funnel round replaced the flat moment-(b) chip wall
and the two-tap moment-(c) confirm on the `/display` rail's `Select Version` surface (`layout="stacked"`) with a single top-to-bottom
column: head (count · active-tag pills · Filters disclosure) → per-axis
segmented chips → the existing E4 advanced-filters disclosure →
an implicit-vote awareness line → a count-proportional survivors grid.
**The `layout="sidebar"` branch (the theoretical /editor modal caller,
not actually wired anywhere today) is byte-for-byte unchanged** — it
still renders the flat `FilterChipBar` and the two-tap `ConfirmChip`
described above.

- <a id="funnel-chips-positive-or-off"></a>**Per-axis segmented chips are
  positive-or-off (two-state) for Border/Frame, not the QuestionFeed's
  tri-state** (locked 2026-07-22, PR #329; formerly labeled _D23_ in this
  document; full ratification text: `docs/reference/funnel-spec.md`'s
  §4). The QuestionFeed's chips cycle untouched→positive→negative→untouched
  (a describe-what-you-see vote); the funnel filter instead wants "narrow
  to this / don't" — a segmented radio for the exclusive axes (Border,
  Frame), with no negative-filter state exposed for either (the implicit
  vote on pick, below, is separate and always positive/support).
  Mechanically (`attributeChips.ts`'s `FUNNEL_AXES`): Border and Frame
  render as radio-exclusive `ToggleButtonGroup`s (one segment active at a
  time; re-tapping the active segment clears the axis back to "any" —
  since a native radio input doesn't fire a change event for a click on
  an already-checked option, this is handled on the `ToggleButton`'s own
  `onClick`, ahead of the group's `onChange`). Only axes with ≥1
  surviving candidate render at all (`chipMembershipState`, computed over
  the OTHER axes' current filter — never the axis's own selection, so
  picking Black doesn't make White/Silver permanently vanish from their
  own axis).
  **Treatment is the one exception, added 2026-07-23** (addendum item 1
  of `SPEC-display-left-rail.md`, owner-approved): it's no longer an
  independent-checkbox group rendered through the same generic axis
  component described above — it's a real tri-state cycle (untouched ->
  include -> exclude -> untouched, `TreatmentChipRow`/`nextChipState`)
  sharing one unified block with Frame instead of its own stacked row,
  specifically because the owner asked for a genuine include/exclude
  filter on Treatment (Full Art/Borderless/Showcase/Extended/Etched) —
  see [`display-left-rail.md`](display-left-rail.md)'s "Unified Frame +
  Treatment filter" section for the full implementation writeup
  (`excludedAttributeTags`, `filterOutExcludedChipsVotesGated`). Border/
  Frame's own two-state, positive-or-off behavior above is unchanged;
  this is a scoped, additive exception for Treatment only, not a reversal
  of the 2026-07-22 ratification (whose own "narrow to this / don't"
  reasoning was about the funnel-vs-QuestionFeed distinction generally,
  not a hard ban on ever adding an exclude state anywhere in the funnel).
- <a id="sensitive-tags-excluded-from-funnel"></a>**Three chip states**
  (F3): SETTLED (some survivor resolves the tag — `card.tags`), SUGGESTED
  (every carrying survivor only has it via `card.suggestedFilterTagNames`
  — see the compliance note below, dashed border + trailing `⌇`,
  vote-layer-gated), or absent (no surviving candidate carries the
  attribute at all). **The SUGGESTED state and its implicit-support-on-pick
  vote both exclude sensitive/moderation-gated tags** (locked 2026-07-22,
  PR #329; formerly labeled _D24_ in this document): a leaning-but-
  unconfirmed sensitive attribute must never surface as a dashed chip or
  receive a support vote from a pick, since sensitive tags are
  moderation-gated ([[moderation.md]]) and a suggested-chip lean would
  leak a machine guess ahead of human co-sign review. Mechanically this
  rides `get_suggested_filter_tags_overlay`'s own
  RESOLVED_APPLY/RESOLVED_REJECT/CONTESTED/PENDING_APPROVAL/SENSITIVE
  exclusion (see the compliance-fix note below) — `suggestedFilterTagNames`
  never carries a sensitive tag, so neither the chip render nor the
  implicit-vote support set can act on one. **Deviation from the spec's
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
- <a id="count-proportional-disclosure"></a>**Count-proportional disclosure
  tiers ship as named constants** (F1; locked 2026-07-22, PR #329;
  formerly labeled _D21_ in this document), refining the editor-completion
  package's hard `compressed=true`: `FUNNEL_DENSE_ABOVE = 8` / `FUNNEL_HERO_AT_OR_BELOW = 2` so post-launch tuning is a one-line
  change, not inline magic numbers in the tier picker. `>8`
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
  **Same PR, second follow-up owner round ("it's the buttons that are
  the largest, they're too big")**: every plain react-bootstrap
  `Button`/`ToggleButton` in the funnel (`size="sm"` alone measured
  ~31px tall, ~21px line-height) read as oversized next to the
  now-compact tiles and the reference mockup's own flat, low-chrome
  controls - the mockup's Filters disclosure isn't even a bordered
  button, it's plain underlined text next to the result count
  (`responsive-layout-2026-07-21.html` line 435: `14 results · <u> Filters</u>`). Three scoped `styled()` wraps
  (`CompactButton`/`CompactToggleButton`/`CompactLinkButton`,
  `SelectVersionResults.tsx`) tighten padding/font-size/line-height to
  match, applied ONLY at this file's own funnel-specific call sites
  (Filters toggle - also switched from `outline-primary` to `link`
  variant to match the reference's unbordered text shape - the per-axis
  segmented chips, and the already-link-styled "+N more"/"Show
  fewer"/"More like this"/"Clear filters" controls); measured live,
  "More like this" no longer wraps to two lines in a narrow tile as a
  side effect of the smaller font. `GridSelectorModal.tsx`'s own
  sidebar/modal layout is a completely separate return path in this
  same file (per this file's own top comment) and never renders through
  these wraps, so it's unaffected. Touch target: rather than shrinking
  the real hit area below ~40px on a touch breakpoint, each wrap adds
  an invisible `::after` (`inset: -12px`, `max-width: 767.98px` only)
  that pads the actual clickable box out to >=40px while the visual
  size stays reference-sized at every breakpoint - verified live via
  `getComputedStyle(el, "::after")` at a 390px viewport.
  **Same PR, third follow-up owner round (SPEC-display-left-rail.md §8's
  buttons-look-like-buttons audit, 2026-07-23)**: the Filters toggle's
  `link`/underlined-text shape from the round immediately above was
  itself superseded one round later - the audit's own rule ("anything
  clickable that performs an ACTION reads as a button") wins over the
  reference mockup's text-link treatment, so it's back to a real
  `outline-light` `Button` (`CompactButton`, unchanged padding/font-size
  from that round, just the variant/border/background restored) with a
  chevron - this ALSO happens to agree with upstream's own
  `GridSelectorFilters`, which already renders its settings toggle as a
  `Button`. See [`display-left-rail.md`](display-left-rail.md)'s
  "Buttons-look-like-buttons audit" section for the full round writeup.
- <a id="implicit-vote-is-the-vote"></a>**Implicit vote — the pick IS the
  vote, no second tap** (locked 2026-07-21/22, PR #329; formerly labeled
  _D20_ in this document). Picking a
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
- <a id="context-menu-visible-cue"></a>**Context menu on `/display` slots
  gains a visible `⋯` cue, bottom-right of each tile** (F6; locked
  2026-07-22, PR #329; formerly labeled _D22_ in this document — revises
  the editor-completion package's original "gesture-invoked, no visible
  three-dots button" stance now that the owner wants a touch-discoverable
  cue). `PagePreview.tsx`
  gained additive `onSlotContextMenu?(index, x, y)` — right-click
  (`preventDefault`ed, scoped to slots only), long-press
  (`useLongPress`, extracted per-slot into `PagePreviewSlotEl` so the
  hook can be called once per slot), and the new visible `⋯` cue button
  (bottom-right of each tile — its own corner, deliberately separated
  from the top-left/top-right corners a future selection-checkbox/flip
  button would use) all open the SAME existing `CardSlotContextMenu` +
  `getCardSlotMenuActions` (Change Query/Duplicate/[Unfilter
  Printing]/Delete — no new action). `DisplayPage.tsx` mounts one
  shared menu instance for whichever slot was triggered. Absent
  `onSlotContextMenu` (every other `PagePreview` caller, e.g.
  `PDFGenerator`'s fast preview), renders with zero behavior change —
  no cue, no long-press handlers, the browser's native menu untouched.
  **Editor-polish round (EPcue, SPEC-editor-polish.md §D.8, 2026-07-24)**:
  the cue grows `20×20` → `26×26` (glyph `13px` → `17px`), higher-contrast
  (`rgba(11,21,32,.92)` bg, `1.5px #abb6c2` border, `#fff` glyph,
  drop-shadow) so it reads over card art, and its render gate tightens
  from "a context menu is wired" alone to "the slot holds a card **and**
  a context menu is wired" — an empty slot now shows no cue at all. The
  same round also ships the `⟲` flip button this bullet's own "future
  selection-checkbox/flip button" note anticipated: top-right corner,
  same `26×26` sizing/reveal behaviour as the cue, an additive
  `onSlotFlip?(index)` prop plus a SEPARATE `content.flippable` flag
  (deliberately independent of `content.imageUrl` — gating the flip
  button on the CURRENTLY-effective face's own image, the same way the
  cue is gated, would strand a user the moment they flip to a face with
  no art of its own, since the very button that let them flip would
  vanish along with the image). `DisplayPage.tsx` tracks a per-slot
  `flippedPreviewSlots` set (sheet-local, preview-only — never touches
  `activeFace`/selection state) so flipping one slot never affects any
  other slot or the project's own Fronts/Backs view setting.
- <a id="ghost-tile-thumbnail"></a>**Ghost tile gains a thumbnail + `+N`
  (EP1, SPEC-editor-polish.md §D.4, 2026-07-24)**: the "+N more
  copies"/"Show fewer" ghost tile (the "already-link-styled" control the
  bullet above this one references) used to be a plain dashed empty box
  with text. It now renders the first hidden copy's own
  `smallThumbnailUrl`, dimmed (`rgba(11,21,32,.62)` overlay), with a
  centred `+N` and a "more copies" caption — a real preview of what's
  being compressed, not just a bare count. Only the EXPAND ("+N") ghost
  gets this treatment (`GhostThumb`/`GhostDim`/`GhostPlus`/`GhostCap`,
  `SelectVersionResults.tsx`); the COLLAPSE ("−") ghost stays plain text
  (nothing to preview there). Border REV: `1px rgba(235,235,235,.15)`
  (was `1px dashed #abb6c2`).
- <a id="data-driven-sort"></a>**Data-driven Sort (EP7, SPEC-editor-polish.md
  §D.4, REVISES RD2, 2026-07-24)**: the `.sortsel` `Form.Select` on the
  `layout="stacked"` (funnel/rail) surface stops being the backend-driven
  6-option `SortByOptions` list (`search.sortBy`/`dateCreatedDescending`
  etc. — that select is untouched on the OTHER, `layout="sidebar"`/modal
  path, which never had a funnel to begin with) and becomes a
  client-side comparator over fields the response already carries: **
  Confirmation status** (`canonicalCard` → `suggestedCanonicalCard` →
  neither), **Resolution (DPI) high→low**, **File size low→high**,
  **Pinned sources first** (reads the SAME `getLocalStoragePinnedSourcePks`
  helper `SourcesAccordion.tsx` writes, re-read fresh on every Sort
  change — not reactively synced mid-render if a pin is toggled
  elsewhere in the rail without reselecting the ordering), and **Name
  (A→Z)**. Only reorders the TOP-LEVEL canonical/non-canonical/unknown
  groups — `selectVersionGrouping.ts`'s own section ordering and each
  group's internal representative/rest ordering are untouched. "Community
  vote weight" (the dispatch's original seventh ordering) needs a
  per-card numeric weight the response doesn't carry yet
  (`suggestedCanonicalCardConfidence` is a currently-always-`undefined`
  seam) — owner-ruled (amendment 2, the same round): ship the five now,
  render NOTHING for vote-weight until that seam lands (no disabled
  placeholder).
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
  at all - it's no longer one accordion among several (per
  `proposal-h-display-layout-spec.md`'s [left-rail de-clutter
  decision](../proposals/proposal-h-display-layout-spec.md#left-rail-declutter-hierarchy):
  art selection is the primary surface, not something a user has to
  expand). The same
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
- Tests: `frontend/tests/GridSelectorModal.spec.ts` (23 tests) +
  `GridSelectorModalVariants.spec.ts` (7 tests: keyboard nav, a large-grid
  focus-perf check, autofocus fallback, mobile filters default — merged
  from the former `GridSelectorModalAccessibility.spec.ts` and
  `GridSelectorModalMobile.spec.ts`) — parity wave 3 (2026-07-24, issue
  #272) ported both onto the cardback mount (see the "Post-route-swap
  reachability" note above); `frontend/tests/CardSlot.spec.ts` (15 of 25
  tests ported the same wave — delete/duplicate/change-query/context-menu/
  auto-select coverage against the sheet's own slots, `page-preview-slot` +
  `page-preview-slot-menu-cue`; see this doc's own "Known gaps" for what
  wasn't ported) and its `visual/CardSlot.visual.spec.ts` companion (2 of 6
  aria-snapshot tests ported, retargeted onto the cardback mount, regex-
  tolerant on a handful of pre-existing third-party icon-font/tree-select
  rendering leaves — see that file's own module comment),
  `frontend/tests/CardImageStates.spec.ts`
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
- **Per-slot next/prev image-cycling has no unified-page equivalent**
  (found 2026-07-24, issue #272 parity wave 3). The classic grid's inline
  ❯/❮ arrows (`CardSlot.tsx`) let a user cycle a slot's selected image one
  step at a time, with wrap-around; the sheet's Select Version section is
  a browse-and-click surface only — no "next"/"previous" concept at all.
  `CardSlot.spec.ts`'s 3 cycling tests were dropped, not ported, for this
  reason (see that file's own module comment). Not tracked against any
  numbered gap in issue #272's own checklist — a new finding, flagged for
  the owner alongside this same wave's `card-dom-api.md` gap below.
- **`docs/features/card-dom-api.md`'s DOM API contract (`data-card-*`/
  `mpc:card-selected`) is unimplemented on the sheet's own placed-card
  slots** (found 2026-07-24, same wave) — see that doc's own "Known gap"
  entry for the full detail; cross-referenced here since the dropped test
  that surfaced it ("selecting an image in a CardSlot via the grid
  selector") lives in this feature's own `CardSlot.spec.ts`.
