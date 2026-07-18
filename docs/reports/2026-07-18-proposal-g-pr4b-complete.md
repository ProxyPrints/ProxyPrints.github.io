```
TASK: Proposal G — user accounts + saved decks, PR4b (UI wiring, final piece)
BRANCH: claude/proposal-g-ui-wiring
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/93 (open, base master)
PRIOR PRS (still open, this branch carries forward the frontend files it
needs from each rather than stacking — see WHAT SHIPPED item 1):
  - PR #85 https://github.com/ProxyPrints/ProxyPrints.github.io/pull/85 (schema+backend)
  - PR #86 https://github.com/ProxyPrints/ProxyPrints.github.io/pull/86 (sign-in relocation)
  - PR #88 https://github.com/ProxyPrints/ProxyPrints.github.io/pull/88 (draft; saved-decks API)
  - PR #89 https://github.com/ProxyPrints/ProxyPrints.github.io/pull/89 (crypto module)
This report supersedes the interim checkpoint at
docs/reports/2026-07-18-proposal-g-checkpoint.md (still accurate for
PRs #85/#86/#88/#89 — nothing there changed). This is now the FULL and
FINAL build: all 5 sequenced PRs are open, dependency order unchanged.

WHAT SHIPPED (10 commits on claude/proposal-g-ui-wiring):
1. Carried forward the exact frontend files PR4b needs from two still-open
   PRs, rather than stacking three PRs deep (docs/lessons.md's stacked-PR
   base-deletion trap): schema_types.ts + the Kind->VoteQueueRequestKind
   import fix from PR #88, savedDeckCrypto.ts + tests + the jest.setup.ts
   polyfill from PR #89, and the sign-in-relocation navbar/AuthWidget
   changes from PR #86 (since "My Decks" needs sign-in visible everywhere
   to be reachable). Verified byte-identical against each source branch.
2. Redux plumbing: features/savedDecks/deckPayload.ts (the plaintext shape
   encrypted wholesale, including its own name; deviceLocal marking for
   local-file-sourced slots), savedDeckSessionSlice (tracks which saved
   deck the editor represents, session-only), projectSlice.loadProject /
   finishSettingsSlice.loadFinishSettings (atomic whole-project replace —
   no existing reducer did this), selectIsCurrentProjectDirty.
3. CryptoSessionProvider: a React Context (not Redux — CryptoKey isn't
   serializable) holding the in-memory master key and session status,
   mounted in Layout.tsx.
4. The 7 saved-deck/crypto-profile RTK Query endpoints wired into
   store/api.ts, with cache tags and skip options so anonymous sessions
   never fire a doomed authenticated request.
5. PassphraseSetupModal (first-save flow, verbatim-spirit unrecoverability
   warning), RecoveryKeyDisplay (the show-once download/print/copy +
   acknowledge-gate step, shared by both flows below), UnlockModal
   (once-per-session unlock, with a "Forgot your passphrase?" recovery
   branch that reissues a fresh recovery key).
6. My Decks page (/myDecks): lists every saved deck, decrypted client-side
   once unlocked; named decks and snapshots in separate groups; "Open in
   editor", per-deck delete, a "Lock" action, and account reset (two-click
   confirm naming the exact deck count — reachable whether locked or
   unlocked, since recovering access when unlock is impossible is its
   whole point).
7. Editor wiring: SavedDeckPanel (reverse breadcrumb + Save button,
   authenticated-only), SaveDeckModal (name prompt, local-file-slot
   warning), LoadSafetyModal (the loss-proof-by-construction load flow —
   dirty+logged-in always saves a safety copy first: "Update {name}" vs
   "Save as new snapshot" if the current content is itself an
   already-saved deck, or just an inline-renameable snapshot save if it
   was never saved — never skippable), and the one-time anonymous->login
   adopt-by-save toast.
8. Real-browser Playwright smoke coverage (tests/SavedDecks.spec.ts, 3
   specs) verifying the Save action/breadcrumb, My Decks nav visibility,
   and empty-state message all render correctly in an actual browser.

DEVIATIONS from spec (each with reasoning):
1. get_saved_decks returns full per-deck ciphertext, not lightweight
   metadata (carried from PR3/the interim report — unchanged, restated
   here since PR4b's My Decks page is the first thing that actually
   consumes this): a deck's title lives inside its ciphertext under the
   ZK design, so there's no server-visible field for a lightweight list;
   the client decrypts every row. An explicit, eyes-open tradeoff per
   §8's own exhaustive field enumeration.
2. Local-file "honest re-pick placeholder" (§4) is the card grid's
   existing empty-slot/re-search UI, not a bespoke tile state —
   deviceLocal: true slots simply have no selectedImage on load, which
   the grid already renders as "pick an image" with the original search
   query intact. Avoids new UI surface for a case the app already
   handles; noted explicitly rather than silently simplified.
3. Account reset's "Discord-gated" requirement (§8) is satisfied by
   requiring an already-authenticated session — same as every other
   saved-deck action — rather than a fresh Discord re-auth redirect. The
   backend's post_reset_saved_decks has no freshness/recency check of
   its own to justify one; a redirect step with no backend enforcement
   behind it would be security theater, not a real gate.
4. The anonymous->login adopt toast (§4) is informational only, pointing
   at the Save button, rather than an actionable "save now" button
   embedded in the toast itself. The existing Toasts system has no
   action-button support; extending shared toast infra for this one
   caller wasn't worth it.

OWN-CAUGHT BUGS (found and fixed during this build, unprompted):
1. PR4a's recovery flow never reissued a fresh recovery key, even though
   the ZK addendum's recovery flow explicitly re-wraps BOTH slots
   (passphrase under the new passphrase, recovery under a FRESH recovery
   key) once the old recovery key has actually been used — an ordinary
   passphrase change correctly leaves the recovery slot alone (separate,
   already-tested case), but the full recovery path was a distinct case
   savedDeckCrypto.ts didn't cover at all. Added
   rewrapMasterKeyWithNewRecoveryKey; extended the recovery-flow test to
   prove the new key works and the superseded old one no longer does.
2. cryptoSession.tsx's status computation fell through to "anonymous"
   whenever isAuthenticated was false — including the instant before the
   whoami query itself had even resolved. Caught via a genuine
   UnlockModal test failure (a misleading "wrong passphrase" error), not
   flakiness: a real click could slip through during that window and
   attempt to unlock/save a crypto profile before the authenticated
   check had settled. Fixed by giving whoami's own in-flight state a
   distinct "loading" status ahead of the isAuthenticated check; added a
   regression test that delays the whoami response and asserts "loading"
   appears first, plus an isProfileLoading guard in UnlockModal itself
   (both the submit handler and the button's disabled state).
3. A whole-project `next lint` pass (not run until the final verification
   step, since per-file lint had been used throughout the branch) caught
   two real simple-import-sort/imports errors in files that had each
   individually passed per-file checks earlier in the branch's history —
   fixed; no behavior change.

DESIGN ADDENDUM handled mid-build (design-only, nothing built):
The owner sent a ZK addendum expanding the "deck sharing" future-work
bullet into a full PR-5 design (key-in-URL-fragment share creation,
unauthenticated recipient decrypt, revocation with an optional
DEK-rotation-on-revoke option, tests required). Written into the spec
doc (docs/proposals/proposal-g-user-accounts-saved-decks.md, new "PR-5,
post-v1" subsection) on PR #85's branch, confirmed additive to the
existing schema (a new SavedDeckShare table, no changes to
SavedDeck/UserCryptoProfile needed) — nothing built, per the addendum's
own instruction.

VERIFICATION:
  - Full jest suite: 380 tests, 39 suites, all passing (up from 348 at
    the crypto-module-only checkpoint).
  - tsc --noEmit: clean throughout every commit.
  - next lint (whole project, not just changed files): clean — the two
    real errors this caught were fixed (see OWN-CAUGHT BUGS #3); every
    remaining warning is pre-existing and unrelated to this work.
  - prettier --check: clean on every commit.
  - Real-browser Playwright run (tests/SavedDecks.spec.ts, 3 specs) against
    a live local dev server — actual WebCrypto, actual Next.js routing,
    actual Bootstrap modals, not jsdom. Used a TEMPORARY executablePath
    override for this sandbox's browser-binary version mismatch (per
    environment policy: never run playwright install); both
    playwright.config.ts and tests/global-setup.ts were reverted to
    their committed state before pushing — only the new spec file
    shipped.
  - "Backend tests" CI failures on the prior PRs (#85/#88) continued to
    be the same 14 pre-existing, environment-only failures documented in
    docs/troubleshooting.md — reconfirmed via docs/reports/2026-07-18-
    proposal-g-checkpoint.md's own count-tracking; no new failures
    introduced by anything in this segment (this segment is
    frontend-only and doesn't touch the backend test suite at all).

OPEN ITEMS / DECISIONS NEEDED:
1. OWNER-ONLY (restated from the interim checkpoint report — unchanged):
   Discord application credentials (DISCORD_CLIENT_ID/DISCORD_CLIENT_SECRET)
   are a pre-existing mechanism (moderator login already uses them), not
   new to Proposal G — confirm they're configured in production for the
   now much larger ordinary-user audience.
2. OWNER-ONLY (restated, unchanged): the PIPEDA/legal data-inventory
   paragraph is in the interim checkpoint report in full; nothing about
   it changed in this segment (PR4b builds UI over the same server-side
   data model, doesn't add any new stored field).
3. Merge-time checklist, all 4 dependency PRs: retarget PR #88's base to
   master once PR #85 merges (already an item in #88's own description);
   rebase claude/proposal-g-ui-wiring onto master once #86/#88/#89 merge
   — the carried-forward commits will already match what landed there.
4. No user-facing docs/wiki update yet for any of these 5 PRs — deferred
   until they land on master together and there's real merged,
   user-facing behavior to describe, per CLAUDE.md's wiki-maintenance
   convention. Flagged in every PR's own checklist.

LIVE STATE:
  - 5 branches pushed: claude/proposal-g-schema-backend,
    claude/proposal-g-signin-navbar, claude/proposal-g-saved-decks-api,
    claude/proposal-g-crypto-module, claude/proposal-g-ui-wiring.
  - 5 PRs open: #85, #86, #88 (draft), #89, #93 (this one). All
    subscribed via subscribe_pr_activity; #93 has a ~1-hour check-in
    scheduled for CI/review-comment status.
  - This is the last piece of the originally-requested build — Proposal
    G's frontend+backend implementation is now fully scoped and open for
    review across all 5 PRs. Next actions are owner review/merge
    sequencing, not further unprompted feature work, unless review
    comments arrive on any of the 5 open PRs.
```
