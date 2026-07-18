```
TASK: Proposal G — user accounts + saved decks. Final wrap-up: all 5
sequenced PRs merged, docs added, 2 more design-only addenda handled.

WHAT SHIPPED (since docs/reports/2026-07-18-proposal-g-pr88-recovery.md):
1. All 5 sequenced Proposal G PRs are now MERGED to master:
   - #85 schema+backend, #86 sign-in relocation, #94 (opaque-blob
     saved-decks API - the recreation after #88's stacked-PR
     base-deletion auto-close; a second, independent recovery attempt
     also landed as #94 within the same minute, so my own recreation
     (#95) was closed by the owner as a duplicate - confirmed a
     concurrent-session collision, not an error), #89 (crypto module),
     #93 (frontend UI wiring, PR4b).
   - PR #93's diff naturally shrank to just its own genuine content once
     #86/#89/#94 merged (its base was the `master` branch ref, not a
     fixed commit) - no rebase/force-push was ever needed; someone else
     also merged master into it (a clean, conflict-free merge commit)
     before it landed.
2. Caught and fixed a real mistake in my own tooling: an `update_pull_request`
   call meant to refresh PR #93's body accidentally stored the literal
   `$(cat <<'EOF' ... EOF)` bash-heredoc wrapper as the PR body text -
   that syntax only works inside the Bash tool, not as a literal string
   passed to a non-shell MCP tool. Caught on the next read-back and
   fixed with a clean second update.
3. Two more design-only spec addenda handled (PR #99, still open):
   - **PR-6, deck portability**: export/import of the complete encrypted
     bundle (no unlock needed to export), a versioned public format as
     the actual portability contract, a standalone decrypt tool as the
     trust anchor, honest offline-attackability limits, explicit
     rejection of server-bound key material.
   - **PR-7, art provenance**: per-slot provenance in a future
     `deckPayload` version so un-indexed slots render from the source
     drive directly instead of breaking; explicit moderation-bypass
     rationale; XML 2.0 optional attributes for third-party
     phash-to-federation-verdict joins; a hard line that provenance
     never enters the federation verdict export; import/PDF-export scope
     boundaries for un-indexed slots per the owner's follow-up
     clarification.
   - Nothing built for either - both are spec-only, per explicit
     instruction each time.
4. `docs/features/saved-decks.md` added (crypto mental model, backend
   endpoints/constants, frontend file map, the PR-5/6/7 addenda,
   owner-only pointers) now that the core build is fully merged - this
   is the task-end docs update CLAUDE.md's convention calls for once
   something changes what a USER sees. Indexed in `docs/README.md`.
5. Fixed a real staleness bug caught while doing that: `docs/README.md`'s
   "Plans & proposals" status table still said HOLD for Proposal G even
   after the spec doc's own header had been updated to "BUILT AND
   MERGED" - changed to PARTIAL (core shipped, PR-5/6/7 addenda still
   HOLD), matching the existing precedent for proposal-c's identical
   shape.

DEVIATIONS: none new - see the two prior reports for PR4b/recovery
deviations, all still accurate.

VERIFICATION:
  - PR #93/#94's CI ("Backend tests") reconfirmed as the same 14
    pre-existing, environment-only failures each time it fired, tracked
    against a rising passed-count - no new failures introduced by
    anything in this segment.
  - Every doc change: `python3 .github/scripts/docs_lint.py` clean,
    `prettier --check` clean (fixed once via `--write` where needed).

OPEN ITEMS / DECISIONS NEEDED:
1. PR #99 (PR-6 + PR-7 design addenda + docs) is open, CI pending, no
   review comments yet - subscribed, ~1hr check-in scheduled.
2. Wiki note (restated, now genuinely actionable): the project's GitHub
   wiki likely wants a new "Saved Decks" user-facing page now that this
   feature is live in production. Flagged in PR #99's body per the
   cloud-session convention (docs/ updated directly; wiki itself is not,
   per that same convention) - the owner or a server session should
   action the actual wiki page.
3. Both prior reports' owner-only items stand unchanged: Discord
   credentials confirmation, and the PIPEDA data-inventory paragraph
   (verbatim text is in the interim checkpoint report and in the spec
   doc's §8 itself - not re-quoted here to avoid drift between copies).

LIVE STATE:
  - master: Proposal G's full core build (schema, backend API, crypto
    module, sign-in relocation, frontend UI) is merged and live.
  - Open: PR #99 (docs + PR-6/PR-7 design, no code) - only remaining
    open Proposal G artifact.
  - Closed, not merged (historical, content preserved elsewhere): #88
    (auto-closed, base-deletion trap; content lives on in merged #94),
    #95 (my own independent recreation of #88; closed as a duplicate of
    #94 by the owner once the concurrent-session collision was
    noticed - content is a strict subset of what #94 already carries,
    confirmed by the owner's own diff).
  - Branch `claude/proposal-g-saved-decks-api` (old, orphaned by #88's
    closure) and `claude/proposal-g-saved-decks-api-v2` (my #95
    recreation, now closed) both left in place, untouched.
  - This is the actual end of the originally-requested Proposal G build:
    every sequenced PR has merged, the only open item is a small,
    design-only docs PR with nothing left to build against the current
    scope.
```
