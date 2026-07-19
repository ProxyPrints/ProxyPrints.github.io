# /whatsthat mobile funnel pass + PWA installability — 2026-07-19

```
TASK: Mobile funnel pass (item 1 of the queue extension) - /whatsthat
      thumb-native tap targets/one-hand reach/chip-ring + PWA
      installability (manifest + icons from the branding assets).
Branch: claude/whatsthat-mobile-funnel-pwa
Commit: 1e6f8efd
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/118 (base master, open)

WHAT SHIPPED:
1. TAP TARGETS / ONE-HAND REACH - audited via real Playwright screenshots
   + boundingBox() measurements at 390px BEFORE writing any fix code, not
   assumption. Measured baseline: Bootstrap's own default .btn height
   ~38px (short of the 44px floor WCAG 2.5.5/Apple HIG call for); the
   "Filter by attribute" toggle ~26px (variant="link" className="p-0"
   zeroes Bootstrap's own padding entirely - the worst offender, and the
   ONLY way to reach the attribute-chip filter); attribute chip pills
   ~30-35px. Fixed with two new QuestionFeed.tsx styled wrappers around
   react-bootstrap's Button:
   - ThumbButton (min-height: 44px, flex-centered) - applied to every
     stacked full-width action: Level 1 (YES/NOT SURE/NO/SKIP), Level 2
     (None of these/Art matches/Skip), Level 3 (Confirm & continue/Skip),
     the artist question's Skip, and the fetch-error retry button.
   - FilterToggleButton (same 44px floor, real padding restoring a hit
     area without looking like a filled button) - had to REMOVE the
     existing className="p-0", not just add a style, since Bootstrap's
     p-0 utility carries !important and would have silently defeated any
     styled-component override left in place alongside it.
   - AttributeChipPanel.tsx's own Chip styled-button gained
     min-height/min-width: 44px, flex-centered (text/padding otherwise
     unchanged).
   - Level 3's Confirm/Skip pair (previously always side-by-side, so
     ~half-width each on a phone) gained flex-column flex-sm-row,
     matching the full-width-stack pattern every other level already used.
   - The chip-ring's own mobile REFLOW (single-column stack below `sm`)
     was audited and found already correct per its own existing "MOBILE
     OVERRIDE" comment - not touched, only the tap-target sizing was a
     real defect.
2. PWA INSTALLABILITY - scoped to /whatsthat only (start_url/scope both
   "/whatsthat" in the new frontend/public/whatsthat-manifest.json), not
   a site-wide manifest on _document.tsx - the game is the installable
   "app" here, not the whole catalog/editor. Linked from whatsthat.tsx's
   own next/head <Head> (<link rel="manifest">, a theme-color meta
   matching the page's own #ff4719, an apple-touch-icon) - confirmed via
   the actual static-export output (out/*.html) that this content lands
   ONLY in whatsthat.html, not any other page's generated markup, proving
   the scoping is real under output: "export", not just visually unused
   elsewhere. Icons (whatsthat-icon-192.png/-512.png, Chrome's own
   minimum installability sizes) rasterized from whatsthat-mark.svg (the
   just-shipped branding integration's own source asset - PR #114) via a
   one-off Playwright screenshot script (not committed, not a new
   build-time pipeline - the PNGs are checked in directly like the SVGs
   themselves), centered on the page's own orange (#ff4719) background.
   No service worker/offline caching added - explicit per the brief ("no
   offline scope beyond the default"); noted in docs as a real gap for
   Chrome's strictest install-prompt heuristics rather than silently
   built around.
3. BEFORE/AFTER SCREENSHOTS - sent directly (before/after Level 1 buttons,
   before/after chip-ring, both at 390px).
4. Docs: docs/features/printing-tags.md gained two new bullets (tap
   targets, PWA installability) alongside the existing funnel-level
   documentation.

DEVIATIONS from spec: none against the owner's queued spec. One scope
note stated explicitly in the PR body: whatsthat-mark.svg/-wordmark.svg
were copied onto this branch independently (not stacked on the still-
open branding PR #114) specifically to avoid the GitHub stacked-PR
auto-close hazard documented in docs/lessons.md - if #114 merges first,
this PR's own copies become a harmless identical-content no-op diff to
resolve; if this merges first, #114's own copies become the same.

VERIFICATION:
- New tests/QuestionFeedTapTargets.spec.ts (3 tests): real measured
  heights (not just CSS-rule existence) for Level 1's 4 buttons, Level
  2's filter toggle + 3 exit buttons, and an attribute chip, all
  asserted >= 44px at a real 390px viewport.
- New tests/WhatsThatPWA.spec.ts (2 tests): manifest/theme-color/apple-
  touch-icon present on /whatsthat with correct hrefs; absent entirely
  on a different page (/editor), proving the scoping doesn't leak.
- Full /whatsthat-touching Playwright suite (QuestionFeedConfirmSuggestion,
  QuestionFeedLevels, QuestionFeedArtistAndTag, QuestionFeedMobileLayout,
  QuestionFeedLayoutReconciliation, NoMatchReasonStrip, plus the two new
  files): 32/32 passing, run to completion uncontested (learned from an
  earlier self-inflicted collision this session - see the LIVE STATE note
  below - never touched git branch state while a background Playwright
  run was still active for the remainder of this task).
- Full repo test suite (npx jest --runInBand): 399/399 passing, 42/42
  suites.
- npx tsc --noEmit: clean.
- npx eslint on all touched files: 0 errors, pre-existing <img> warnings
  only (unrelated, same warnings present before this change).
- npx next build: production build succeeds; the static-export output
  itself (not just the dev server) was inspected directly to confirm
  per-page manifest scoping, per item 2 above.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #118 open, unmerged - your call on timing, same as the other open
   PRs from this session.
2. Duplicate-asset note (see DEVIATIONS) - whichever of #114/#118 merges
   second will show a trivial identical-file no-op in its own diff for
   the three branding SVGs; not a real conflict, just worth knowing
   going in rather than being surprised by it.
3. Chrome's strictest "Add to Home Screen" native prompt heuristic can
   want a service worker in addition to a valid manifest - not built
   here per the explicit "no offline scope beyond the default" brief.
   Flagging in case that's a gap worth closing in a later pass, not
   silently deciding it doesn't matter.
4. STANDING PACING RULE APPLIED: stopping here rather than starting the
   homepage panel (next queued item) - it's a new feature, not a follow-
   up to this pass, matching the session's own standing pacing rule.

LIVE STATE:
- claude/whatsthat-mobile-funnel-pwa pushed, PR #118 open.
- This report's own branch report-relay-6121bf36-8, pushed with this
  file, not yet merged.
- No dev servers or other background processes left running. Process
  note for any future session: earlier in this same task a background
  Playwright run got corrupted mid-run because a `git checkout` to a
  different branch happened in the same working directory while it was
  still live - diagnosed, the run was safely re-done from a clean state
  afterward, and no code was actually affected (confirmed by re-running
  from a stable state), but the lesson (never switch branches while a
  background test/dev-server process is active in the same directory)
  is now in docs/lessons.md.
```
