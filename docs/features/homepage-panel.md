# Homepage panel — "what is this, really?"

## What this is

A light-touch addition to `frontend/src/pages/index.tsx` (frontend-polish
package, queued item 2) — not a redesign of the existing homepage. The
brief was to "confess what the site is": the page above this panel
describes the print-shop wrapper (search, editor, PDF export), but says
nothing about two other real, shipped features a first-time visitor would
otherwise never discover — the community printing-identification game
(`/whatsthat`) and client-side-encrypted deck storage (`/myDecks`).

`frontend/src/features/ui/HomepagePanel.tsx` renders between the existing
"Jump into the project editor!" button and the pre-existing
`ProjectOverview` bullets, via `<HomepagePanel />` in `index.tsx`.

## Gating

The whole panel returns `null` without a remote backend configured
(`useRemoteBackendConfigured`) — the exact same condition `Navbar.tsx`
already uses to decide whether to show its own `/whatsthat` and `My Decks` nav links. Promoting a CTA to a route that would 404/no-op for a
Local-Folder-only visitor is worse than not showing it; this keeps the
panel's own gating identical to the nav's, rather than inventing a
second, possibly-drifting rule for the same underlying condition.

## The two CTA cards

- **Play the identification game** → `/whatsthat`, `variant="primary"`
  button, the `whatsthat-mark.svg` branding asset (from the branding
  integration, PR #114) as a small accent icon — not the page's own
  `#ff4719`/starburst treatment, which is that page's own loud identity
  and stays there.
- **Your decks, encrypted so even we can't read them** → `/myDecks`,
  `variant="outline-light"` button. `/myDecks` itself (`MyDecksPage.tsx`)
  already handles both the signed-out case ("Sign in from the navbar
  above...") and the signed-in-but-locked case, so this links there
  directly rather than branching on auth state itself.

Both are real anchors (`Card.Link as="a"` wrapped in `next/link`, not a
`div`/`Button` combination) with `data-testid`s
(`homepage-panel-whatsthat-link`/`homepage-panel-mydecks-link`) covered by
a real click-through Playwright test, not just an href assertion — see
`docs/lessons.md`'s nested-anchor entry for why that distinction matters.

## Catalog stats slot — deliberately NOT a stats widget

`CatalogStatsSlot` is a placeholder only (`data-testid="homepage-panel- catalog-stats-slot"`, text "Live catalog stats - coming soon") — it
fetches nothing and computes nothing. A chart pipeline (server lane,
post-Part-4) will produce `docs/assets/charts/catalog-coverage-strip.svg`;
per the owner's explicit instruction, this panel reserves the slot's
shape (full-width strip, card-styled border, positioned right after the
two CTA cards) rather than standing up a parallel live-stats widget from
a direct API call that the chart would then make redundant. Whoever wires
the chart in later replaces the placeholder body with an `<img>`/inline
`<svg>` of that file — no other layout change should be needed.

**Not yet resolved, flagged for whoever does that wiring**: the exact
serving path for `docs/assets/charts/*.svg` on the live site isn't
established yet (the chart pipeline itself doesn't exist as of this
panel) — could land in `frontend/public/` at build time, or be served via
the docs-as-site-source pipeline (Proposal I) under whatever route that
ends up using. This doc intentionally doesn't guess.

## Tests

- `HomepagePanel.test.tsx` (Jest/RTL) — the gating logic directly:
  renders with a remote backend configured, renders nothing without one.
- `tests/HomepagePanel.spec.ts` (Playwright) — both CTAs + the stats slot
  render with a real backend; both CTAs actually navigate on click.
