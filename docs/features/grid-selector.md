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

The unified display page's (`/display`) rail "Choose Image" accordion
body no longer renders the flat `GridSelectorResults`/`CardResultSet`
grid — it mounts `SelectVersionResults.tsx`, which groups the same
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
- **Moment (b), art-as-filter**: a plain binary toggle-chip row
  (`FilterChipBar`, NOT `AttributeChipPanel.tsx`'s tri-state vote-casting
  ring — a new, thin component per the spec's own component table),
  built on `attributeChips.ts`'s existing `ALL_ATTRIBUTE_CHIPS`
  taxonomy/display names. A "More like this" button on any tile with at
  least one resolved attribute tag seeds the filter from that card's own
  `tags`.
- **Moment (c), filtered-selection confirm chip**: after selecting a
  card while a filter tag is active, a `ConfirmChip` appears if that
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
- **Open items, not resolved here (owner call needed)**: (1) group 2's
  sub-order beyond "frame type first" — this build picked
  `altered-frame > custom-art > ai-art`
  (`SELECT_VERSION_REASON_TAG_PRIORITY`), an arbitrary but documented
  choice, since the spec doesn't pin `custom-art` vs. `ai-art`'s relative
  order. (2) The "Choose Image" accordion title/testids were kept
  as-is (not renamed to "Select Version") to avoid churning every
  existing passing test that references that exact heading text — a
  pure-copy rename is a small, separate follow-up if the owner wants the
  label itself to match the spec's own name for this section.

## Key files

- `frontend/src/features/gridSelector/GridSelectorModal.tsx`,
  `GridSelectorFilters.tsx`, `JumpToVersion.tsx` — the classic modal
  variant (unchanged by issue #167)
- `frontend/src/features/gridSelector/GridSelectorResults.tsx`,
  `CardResultSet.tsx` — the flat grid renderer, still backing the modal
  variant above; no longer used by `/display`
- `frontend/src/features/gridSelector/SelectVersionResults.tsx`,
  `selectVersionGrouping.ts` (+ `selectVersionGrouping.test.ts`) — the
  `/display`-only Select Version section (issue #167)
- `frontend/src/features/card/Card.tsx` (+ new `Card.test.tsx`),
  `CardSlot.tsx`
- Tests: `frontend/tests/GridSelectorModalVariants.spec.ts` (keyboard nav
  - a large-grid focus-perf check, autofocus fallback, mobile filters
    default — merged from the former `GridSelectorModalAccessibility.spec.ts`
    and `GridSelectorModalMobile.spec.ts`), `frontend/tests/CardImageStates.spec.ts`
    (error placeholder + slow-load hint), `frontend/tests/SelectVersionSection.spec.ts`
    (grouping/ordering, moment (a)/(b)/(c) behavior — issue #167)

## Known gaps

- Item 11 (preview-before-commit) from the same Phase-1 survey was
  explicitly deferred, not built — see the frontend-polish PR-B
  description for the full reasoning.
- The perf check for item 2 covers keyboard-focus responsiveness against
  a 150-synthetic-card grid in a mocked sandbox; it doesn't reproduce
  real backend/ES latency or real image-CDN load timing at that scale.
- Issue #167's Select Version section: see its own "Open items" bullet
  above for the two owner-decidable gaps (group 2's ai-art/custom-art
  order, and the un-renamed "Choose Image" label). The Filters column
  (`GridSelectorFilters`) reused inside the rail still uses the same
  viewport-keyed Bootstrap column breakpoints as the classic modal's
  `FiltersColumn` (pre-existing, not introduced by this build) — cramped
  at the rail's ~380px width, a known layout gap `CardRow`'s own
  "embedded" variant comment already flags for the results grid and
  wasn't in this issue's scope to fix for the filters column too.
