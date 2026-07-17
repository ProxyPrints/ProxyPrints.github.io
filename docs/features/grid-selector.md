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

## Key files

- `frontend/src/features/gridSelector/GridSelectorModal.tsx`,
  `GridSelectorFilters.tsx`, `JumpToVersion.tsx`
- `frontend/src/features/card/Card.tsx` (+ new `Card.test.tsx`),
  `CardResultSet.tsx`, `CardSlot.tsx`
- Tests: `frontend/tests/GridSelectorModalAccessibility.spec.ts`
  (keyboard nav + a large-grid focus-perf check),
  `frontend/tests/GridSelectorModalMobile.spec.ts` (autofocus fallback +
  mobile filters default), `frontend/tests/CardImageStates.spec.ts`
  (error placeholder + slow-load hint)

## Known gaps

- Item 11 (preview-before-commit) from the same Phase-1 survey was
  explicitly deferred, not built — see the frontend-polish PR-B
  description for the full reasoning.
- The perf check for item 2 covers keyboard-focus responsiveness against
  a 150-synthetic-card grid in a mocked sandbox; it doesn't reproduce
  real backend/ES latency or real image-CDN load timing at that scale.
