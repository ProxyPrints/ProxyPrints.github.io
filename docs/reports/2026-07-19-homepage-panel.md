# 2026-07-19 — Homepage panel (PR #120)

```
TASK: Homepage "what is this, really?" landing panel. Branch
claude/homepage-panel, commit 4731d248, PR #120 (open, unmerged).
Owner instruction: "GO on the homepage panel (pacing word: given).
Per the queued spec: a landing section confessing what the site is
- live catalog stats, 'play the identification game' -> /whatsthat,
'your decks, encrypted so even we can't read them' -> sign-in/My
Decks. Light touch, no page redesign, branding assets in
frontend/public/ are yours to use. One addition since the spec was
written: the chart pipeline (server lane, post-Part-4) will produce
docs/assets/charts/catalog-coverage-strip.svg - leave a clearly
marked slot/placeholder for it in the panel rather than building a
stats widget from scratch - the chart becomes the stat when it
lands. Screenshots at desktop + phone width."

WHAT SHIPPED:
1. New frontend/src/features/ui/HomepagePanel.tsx: a two-card panel
   ("Play the identification game" -> /whatsthat with the branding
   mark; "Your decks, encrypted so even we can't read them" ->
   /myDecks) plus a deliberately inert CatalogStatsSlot placeholder
   div (no data fetching, text "Live catalog stats - coming soon",
   dashed border, data-testid homepage-panel-catalog-stats-slot).
   Both CTAs are real <a> elements via react-bootstrap's
   `Card.Link as="a"` + next/link `passHref legacyBehavior`, not
   onClick-injection navigation.
2. Gating: the whole panel returns null unless
   useRemoteBackendConfigured() is true - the identical selector
   Navbar.tsx already uses to show/hide its own /whatsthat and My
   Decks links, so the panel can't ever offer a CTA the navbar
   itself wouldn't also offer.
3. Wired into frontend/src/pages/index.tsx between the existing
   JumpIntoEditorButton and ProjectOverview sections (<hr /> on
   both sides, no other page structure touched).
4. Tests: frontend/src/features/ui/HomepagePanel.test.tsx (Jest/RTL,
   2 cases: renders both CTA hrefs + stats slot when a backend is
   configured; renders nothing when it isn't) and
   frontend/tests/HomepagePanel.spec.ts (Playwright, 3 cases: panel
   renders, click-through to /whatsthat via toHaveURL, click-through
   to /myDecks via toHaveURL - real clicks, not href-only assertions,
   per the standing bar from the Discord nested-anchor fix).
5. docs/features/homepage-panel.md (new): gating rationale, the two
   CTA cards, and an explicit note that the chart-serving path for
   docs/assets/charts/*.svg isn't established yet and this doc
   doesn't guess at it.
6. CLAUDE.md docs/ index: added the homepage-panel.md entry.
7. docs/lessons.md: added "Verification must run against the
   committed/pushed state, not the working tree" - a process lesson
   from a CI-caught gap (auto-fix hooks rewriting files after local
   verification ran), not specific to this PR's own code but
   surfaced during this task's wrap-up.

DEVIATIONS from spec:
- No live catalog-stats widget was built, by explicit owner
  instruction in the addendum message - the slot is inert on
  purpose, not an oversight or a deferred TODO.
- Used Card.Link as="a" + legacyBehavior instead of the
  <Link><div><Button></div></Link> pattern already present elsewhere
  in index.tsx (JumpIntoEditorButton), because that existing pattern
  relies on onClick-injection rather than a true anchor - given the
  Discord nested-anchor lesson this session already paid for, real
  anchor semantics were worth the small inconsistency with the
  pre-existing button. Not a rewrite of the existing button - only
  the new panel's own CTAs use the new pattern.

VERIFICATION:
- npx tsc --noEmit: clean.
- npx jest: 401/401 passing across 43 suites (includes the 2 new
  HomepagePanel.test.tsx cases).
- npx eslint: clean.
- npx next build (static export): succeeds.
- Playwright HomepagePanel.spec.ts: 3/3 passing, including both
  real click-through navigation assertions.
- Screenshots taken at desktop (1280px) and phone (390px) width via
  scrollIntoViewIfNeeded() + locator screenshot (fullPage was
  truncating to viewport height on the phone-width run - see
  docs/lessons.md's existing entries for the general pattern of not
  trusting a first-pass capture); both already sent to the user via
  SendUserFile as homepage-panel-desktop.png / homepage-panel-mobile.png.
- Per the lessons.md entry just added: git status was confirmed
  clean on claude/homepage-panel immediately after the final commit,
  before this report was written, so the verification above is
  against the actual pushed commit 4731d248, not a pre-hook working
  tree.
- NOT verified: live-site rendering (cloud sandbox can't reach
  proxyprints.ca - see docs/lessons.md's existing entry on this).

OPEN ITEMS / DECISIONS NEEDED:
1. PR #120 needs the owner's merge call. PR #118 (mobile funnel pass
   + PWA installability) is also still open awaiting merge.
2. The chart-serving path for docs/assets/charts/*.svg on the live
   static-export site is not yet established anywhere in the repo -
   flagged in docs/features/homepage-panel.md rather than guessed
   at. Whoever wires CatalogStatsSlot to the real chart will need to
   resolve this first.
3. A new queue-extension message ("SITE FUNNEL CONNECTIVE PASS", 3
   items: tappable /whatsthat stats header expanding an "about this
   catalog" panel with a coverage-strip chart slot + doc-sourced
   copy + a /guide link, collapsed-by-default with dismissal memory;
   a post-vote acknowledgment line, session-local count only, zero
   persistence/telemetry; a chart-footer CTA convention embedded in
   docs' own chart markup) arrived mid-task. Per the standing pacing
   rule, this is queued but NOT started - it's a new feature set
   requiring its own explicit "GO" from the owner, same as every
   other item this session.
4. Residue quiz variant (design-only, gated on the server's feed
   API) remains queued from an earlier message, also not started.

LIVE STATE:
- Branch claude/homepage-panel pushed to origin, PR #120 open.
- Branch report-relay-6121bf36-9 pushed to origin with this report.
- No dev servers or background processes left running.
- No uncommitted changes anywhere in the working tree.
```
