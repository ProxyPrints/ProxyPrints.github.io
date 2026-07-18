```
TASK: /whatsthat visual diagnosis - branding status, starburst, orange background
Branch (fix): claude/starburst-oversize-fix -> PR #91 (base: master)
Branch (report): report-relay-6121bf36-3

ANSWER 1 - BRANDING STATUS: NOT SHIPPED. No code for it exists anywhere
in the repo - `find frontend/src/assets -iname "*whatsthat*"` returns
nothing, and there is no commit in history touching
`assets/whatsthat-branding` or any whatsthat-branding integration.
Confirmed against the current master tip (cceb7eb) directly, not just
the task tracker. Queue position: behind Artist Support Links v1 and
item (c) (printing-info badge) per the standing owner-set priority
order - task #45 in the tracker, still `pending`. The 3 SVGs being
invisible on the live site is EXPECTED, not a bug. This item closes -
no further action until its turn in the queue.

ANSWER 2 - THE STARBURST (fixed, see PR #91):
- WHICH component: `BurstSvg` (an `<svg>` styled-component,
  `frontend/src/features/printingTags/cardPanel.tsx`), with its jagged
  `<polygon>` shapes rendered inline in
  `frontend/src/features/questionFeed/QuestionFeed.tsx` (~line 466) using
  the procedurally-generated frames from `starburstShape.ts`. Separate
  from the whatsthat branding assets entirely - unrelated code path,
  confirmed the branding integration (answer 1) never touches this file.
- WHERE IT CAME FROM: `BurstSvg`'s sizing rule (`width: 140%` of
  `CardPanel`'s own rendered width) originated in the pre-redesign
  `PrintingTagQueue.tsx`, carried over "verbatim" (the extracting
  commit's own stated intent) into `cardPanel.tsx` by `9d71851`
  ("Queue redesign frontend"). In the OLD layout the card's own column
  was `Col md={4}` (33% of the row) - in the redesign, the card column
  widened to `Col md={7}` (58%), but the 140% figure was never re-tuned
  for the new, much-wider column. The starburst's shape/color/animation
  mechanism itself is unaffected and working exactly as coded (confirmed
  via screenshot: correct blue/white jagged double-layer, correct
  flicker frames) - only its SIZE is the defect.
- WHAT IT'S SUPPOSED TO LOOK LIKE vs. WHAT IT RENDERED AS: per the
  module's own comments, a "radiating starburst... behind the game
  itself" that reads as a contained dramatic accent "behind the card"
  with the card readable in front, explicitly NOT meant to cover the
  page's own heading/candidate-grid text (the z-index stacking fix
  earlier in the same file exists specifically to prevent that). What it
  actually rendered as: on a 1280px desktop viewport the burst measured
  ~927x927px - large enough to visually collide with the "What's That
  Card?" page heading and the "Still need help with N cards" / "Filter
  by attribute" stats line above the card, both real page content, not
  candidate-grid chrome. Same collision on a 390px mobile viewport.
  Confirmed live via local Playwright + MSW mock render (screenshots
  attached to this report, both widths, before/after).
- FIX: `BurstSvg`'s width reduced 140% -> 55%, calibrated empirically
  (iterative screenshot checks, not a blind guess) until the burst no
  longer reaches into the heading/stats text at either viewport while
  still reading as a dramatic full accent behind the card. Verified:
  tsc/jest/eslint/prettier clean (one PRE-EXISTING, unrelated tsc error
  in DisplayPage.tsx from a concurrent session's PR #87 - see open items
  below, not touched by this fix). Screenshots: before-desktop.png,
  after-desktop.png, before-mobile.png, after-mobile.png (sent
  alongside this report).

ANSWER 3 - ORANGE BACKGROUND: INTENTIONAL, not an overshoot, and NOT
from a recent content pass. `STARBURST_BACKGROUND_COLOR = "#ff4719"`
(`starburstShape.ts`) is the full-bleed background on `StarburstBackground`
(`whatsthat.tsx`), introduced in commit `ea2b0bd` (2026-07-13, five days
before the most recent /whatsthat-touching commit) and never changed
since - `git log -p` on the file shows exactly one definition of this
constant, ever. The code comment at the color's use site explicitly
documents it as a deliberate, contrast-checked choice ("black reads
better here than the white this started as - checked contrast against
both the orange background (~6.2:1) and the starburst's own blue
(~6.2:1)"), and the color itself is sourced from the same reference gif
the starburst shape/palette was modeled on ("colours sampled directly
from the reference gif's flat fill"). The most recent /whatsthat commit
(`80b509e`, "Reconcile /whatsthat's chip-ring and funnel design eras on
mobile") touched CardPanel's sticky/z-index behavior and
AttributeChipPanel's responsive layout only - no diff to `whatsthat.tsx`
or `starburstShape.ts` at all, confirmed via `git show --stat`. There is
no "recent content pass" commit that touched this color; the owner's
attribution appears to be mistaken, or refers to something not yet
identified from the description alone. Current screenshot attached
(after-desktop.png / after-mobile.png, same files as answer 2) so the
owner can confirm-or-correct the intent directly, per the original ask.

DEVIATIONS: none - answered all three questions with evidence before
fixing anything, fixed only the starburst (the one item explicitly
authorized), left the DisplayPage.tsx tsc error untouched (out of scope,
unrelated feature area, not mine to fix without being asked).

VERIFICATION:
- npx tsc --noEmit: clean except 1 pre-existing, unrelated error in
  src/features/display/DisplayPage.tsx (Card|undefined not assignable
  to Card - from PR #87, a concurrent session's /display route work
  that landed on master after PR #82's type-tightening merged and never
  accounted for the now-optional useCardDocumentsByIdentifier return
  type). Confirmed via git log/git show this is NOT caused by this
  task's change (a one-line CSS width value in cardPanel.tsx has no
  relation to Card typing).
- npx jest --runInBand: 32 suites / 345 tests passing.
- npx eslint + npx prettier --check on cardPanel.tsx: clean.
- Local Playwright/MSW render, both before and after, at 1280px and
  390px - screenshots attached.
- PR #91 opened against master:
  https://github.com/ProxyPrints/ProxyPrints.github.io/pull/91

OPEN ITEMS / DECISIONS NEEDED:
1. DisplayPage.tsx:555 has a real, live tsc error on current master
   right now (unrelated to this task) - a collision between PR #82's
   type-tightening (useCardDocumentsByIdentifier now returns
   CardDocument | undefined) and PR #87's new /display route, which
   landed after #82 merged and assumes the old non-optional type. Not
   fixed here per the explicit "before fixing anything beyond the
   starburst" instruction. Flagging for whoever owns Proposal H/the
   /display route, or for a dedicated follow-up task.
2. The orange background's origin genuinely doesn't match "a recent
   content pass" per the git history checked - if the owner has a
   specific commit/PR in mind, naming it would let this be re-checked
   against that specific diff rather than the general /whatsthat commit
   history.

LIVE STATE: PR #91 open against master, not merged. No local dev
servers or background processes left running. Scratch diagnostic
Playwright spec (not committed) created and deleted during
investigation - no trace left in the repo.
```
