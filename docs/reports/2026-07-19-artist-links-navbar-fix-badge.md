# Artist Support Links v1, Discord sign-in fix, item (c) badge — 2026-07-19

```
TASK: Three items — Artist Support Links v1, PRIORITY Discord sign-in fix,
      item (c) requested-printing badge. Branches/PRs below, all open,
      none merged yet.

WHAT SHIPPED:

1. ARTIST SUPPORT LINKS v1 (branch claude/artist-support-links-v1, commit
   8aa8df7, PR #105, base master):
   - New frontend/src/components/ArtistSupportLink.tsx: buildArtistSupportURL()
     builds https://www.mtgartistconnection.com/artist/<encodeURIComponent(name)>
     deterministically from the artist's display name - no per-artist
     database, no crawling, no existence check by design (MTG Artist
     Connection is a client-rendered SPA where every route, including
     unknown-artist ones, returns HTTP 200 - a status-based check is
     structurally meaningless there per the owner's own recon).
   - ArtistSupportLink component: fixed target=_blank/rel=noopener
     noreferrer/hover title/box-arrow-up-right icon. Gating (only render
     once an artist is confirmed/known) is the caller's job.
   - Surface 1: CardDetailedViewModal's "Canonical Aritst" row - shows
     the link whenever canonicalArtist is set, still "Unknown" otherwise.
   - Surface 2: /whatsthat's post-answer moment - ArtistVotePicker gained
     an optional onArtistConfirmed callback (fires only for a real named
     vote, never "Unknown artist"); QuestionFeed.tsx shows "Art by <Name>
     - support them" below the picker once fired, reset every new item.
     ArtistVotePicker's other caller (AttributeVotingPanel) doesn't pass
     the callback - unchanged there.
   - Credits: about.tsx now credits MTG Artist Connection by name,
     explains link-out-only nature, invites the operator to reach out for
     a richer integration later (not started - tracked as a follow-on).
   - Docs: docs/features/artist-support-links.md (new), CLAUDE.md docs
     index updated.

2. PRIORITY FIX: Discord sign-in nested-anchor bug (branch
   claude/navbar-nested-anchor-fix, commit e3d6f14, PR #107, base master):
   - Root cause (per the owner's own diagnosis, confirmed by reading the
     actual code): Navbar.tsx wrapped <AuthWidget /> in
     <Nav.Link eventKey="auth">. React-bootstrap's Nav.Link-with-eventKey
     renders its own <a href="#"> around its children; AuthWidget already
     renders a real <a> for both auth states (sign-in/sign-out) - nested
     anchors, invalid HTML, outer <a> silently swallowed every click on
     the inner one. No error, no console warning, correct href throughout.
   - Fix: replaced the Nav.Link wrapper with a plain <div className="m-0
     py-0"> preserving the same spacing - AuthWidget needs none of
     Nav.Link's active/eventKey machinery.
   - New tests/Navbar.spec.ts: real Playwright click on the rendered
     sign-in/sign-out button, asserting navigation actually initiates
     (page.waitForURL toward the login/logout URL), not just that the
     anchor has the right href - exactly the test class the owner asked
     for. VERIFIED it actually catches the bug: temporarily reverted
     Navbar.tsx to the original nested-anchor markup, re-ran both tests -
     both failed deterministically (page.waitForURL timeout) - then
     restored the fix and confirmed both pass again.
   - docs/lessons.md entry added, generalizing the failure mode
     ("components that each correctly render an anchor can compose into
     invalid nested-anchor HTML that silently swallows clicks - render
     assertions pass; only click-through tests catch a click thief").

3. ITEM (c): requested-printing badge on editor slots (branch
   claude/item-c-requested-printing-badge, commit 019b384, PR #110, base
   master):
   - No written spec for "item (c)" existed anywhere in the repo (verified
     via full docs/git-history search before starting) - only the
     four-word label from an earlier verbal decision. Asked two
     clarifying questions before building (link target/platform was
     already settled for item 1 above; scope/trigger for item (c) was
     genuinely unrecoverable) - answers: badge shows the REQUESTED
     printing (expansion code + collector number from the slot's own
     search query), not the resolved canonicalCard and not consensus
     status; always-visible whenever the query names a specific printing,
     independent of whether an image is selected yet; degraded style
     mirrors the same EditorSearchResponse.degradedQueries flag Proposal
     H's PR 2b already wired up for /display's rail header.
   - Extracted the existing inline /display rail-header badge into a new
     shared frontend/src/features/card/RequestedPrintingBadge.tsx
     component (per the owner's explicit "same component if cleanly
     reusable, so the two surfaces can't drift" instruction) - DisplayPage.tsx
     now consumes it instead of its own inline copy. data-testid
     display-printing-badge renamed to requested-printing-badge to match
     (existing DisplayPage.spec.ts tests updated, not removed).
   - Mounted in CardSlot.tsx as a new sibling to DeckbuilderConfirmAffordance
     (which stays gated on a selected image existing; this badge is not -
     it's about what was requested, not what's currently shown).
   - docs/features/printing-tags.md: new "Item (c)" bullet documenting the
     distinction from Level 0 and the extraction rationale.

DEVIATIONS from spec:
- Artist Support Links: none against the owner's answered clarifying
  questions.
- Discord fix: none - implemented exactly as diagnosed and prescribed.
- Item (c): none against the owner's answered clarifying questions. One
  interpretive call made explicit in the PR/report: "grid-selector
  card-detail area" in the owner's Artist Support Links answer was
  interpreted as CardDetailedViewModal (no such distinct area exists
  inside GridSelectorModal.tsx itself - confirmed via code search) -
  flagged at the time, not silently assumed.

VERIFICATION:
- Artist Support Links: new Jest unit tests (ArtistSupportLink.test.tsx,
  3 tests) + 2 new Playwright specs (ArtistSupportLink.spec.ts for
  surface 1, 2 new tests in QuestionFeedArtistAndTag.spec.ts for surface
  2) - all passing except ArtistSupportLink.spec.ts's 2 tests, which hit
  a known, pre-existing, documented sandbox limitation (the Card Details
  modal-open click sequence times out deterministically in this cloud
  sandbox regardless of code changes - reproduced identically against
  completely untouched ArtistVotePicker.spec.ts tests using the same
  helper, confirmed via docs/lessons.md's existing entry on this exact
  symptom). Full repo jest suite 394/394 passing at the time, tsc clean,
  eslint clean, next build clean.
- Discord fix: new tests/Navbar.spec.ts (2 tests), both passing, and
  POSITIVELY VERIFIED to fail against the original bug (not just passing
  incidentally) via a temporary revert-and-rerun. Spot-checked
  SavedDecks.spec.ts + ModerationTab.spec.ts (both navbar-dependent) for
  regressions - all passing. Full repo jest suite 391/391, tsc clean,
  eslint clean (0 warnings even), next build clean.
- Item (c): 3 new Playwright tests in CardSlot.spec.ts + 2 updated in
  DisplayPage.spec.ts - full combined run 38/38 passing. Full repo jest
  suite 391/391, tsc clean, eslint clean, next build clean.
- Deferred in all three: no live-site check (cloud sandbox has no egress
  to proxyprints.ca - documented sandbox limitation, not task-specific).

OPEN ITEMS / DECISIONS NEEDED:
1. PR #105 (Artist Support Links v1), #107 (Discord fix), #110 (item (c))
   all open, unmerged - owner's call on merge order/timing. #107 is the
   priority item per the owner's own framing ("the owner's G lifecycle
   test is waiting on this deploy") - flagging it first for merge
   attention. Per CLAUDE.md's standing rule, I did not attempt to merge
   any of these myself (gh pr merge / the merge tool is gated behind
   explicit human review, not something to work around even under
   explicit urgency framing) - offering the choice back to you.
2. Note for whoever next touches ArtistSupportLink.spec.ts: its 2 tests
   are correct but currently unverifiable in THIS cloud sandbox
   specifically (see VERIFICATION above) - re-run them in CI/a real
   browser rather than assuming they're broken if this sandbox reports
   red again.
3. STANDING PACING RULE APPLIED: stopping here rather than starting
   /whatsthat branding integration (the next queued item) - it's a new
   feature, not a follow-up to any of the three items above, matching
   the session's own standing pacing rule ("next item is a new feature"
   triggers a stop-and-report). Queued items remain a menu, not a
   mandate - your call on whether/when to proceed.

LIVE STATE:
- claude/artist-support-links-v1 pushed, PR #105 open.
- claude/navbar-nested-anchor-fix pushed, PR #107 open (priority).
- claude/item-c-requested-printing-badge pushed, PR #110 open.
- claude/questionfeed-double-ask-fix (PR #101, prior task) still open,
  unmerged as of this report - owner said "accepted, queued for merge"
  but it hasn't landed on master yet as of the last fetch.
- This report's own branch report-relay-6121bf36-6, pushed with this
  file, not yet merged.
- No dev servers or other background processes left running.
```
