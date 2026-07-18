```
TASK: CLOUD session (upstream-readiness) — consolidated docs/conventions
hygiene batch. Branch: docs-conventions-hygiene-batch-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/100 (against
this fork's own master — never upstream).

WHAT SHIPPED:

1. CLAUDE.md conventions:
   (a) Report-relay rule extended — replies must now carry the full
       GitHub blob URL to the pushed report, not just branch+path.
   (b) New merge-duty rule — never delete a branch in the same action
       as merging its PR; precondition `gh pr list --base <branch>`
       must return empty before deleting; when in doubt, don't delete.
       Cites how PR #88 was lost (stacked-PR base-deletion trap).
   (c) New rule — search for an existing recovery before rebuilding a
       lost/auto-closed PR. Cites #88 rebuilt in parallel by two
       sessions same day, with #95 duplicating #94's already-shipped
       recovery (created 39s after #94 merged).
2. Proprietary-name genericization: "Proxxied" (proposal-b, proposal-c,
   proposal-g) and "Steam Deck" (proposal-b) design-reference mentions
   genericized. Ran a second, independent research-agent sweep across
   all of docs/ afterward — no further hits found. "Moxfield" kept
   (named factual import source, not a design comparison); historical
   docs/reports/ files untouched per instruction.
3. proposal-c-context-menu-restyle.md: Part (b) (solid-color
   utilitarian restyle direction) marked SUPERSEDED by Proposal H in
   both the file's summary line and Part (b)'s own section header —
   kept as historical record, not an active plan; "do not build
   against it" noted explicitly.
4. proposal-b-bleed-normalization.md: decision 4's stale persistence
   note (written before PR-2 shipped, said "project state
   (projectSlice), not session-only") corrected to describe what
   actually shipped — identifier-keyed localStorage, deliberately
   device-local, mirroring favoritesSlice's pattern. projectSlice does
   hold a live Redux copy for the session, but localStorage is what
   actually survives reload. Cross-checked against real code
   (projectSlice.ts, cookies.ts, listenerMiddleware.ts, constants.ts)
   and against proposal-g's own §5, which already independently
   describes this exact mechanism correctly ("deliberately device-
   local, NOT part of SavedDeck state") — the correction now matches
   that existing, accurate description instead of contradicting it.
5. proposal-h-unified-display-page.md §1: alex-taxiera/proxy-print's
   license label corrected from MIT to AGPL-3.0 (verified directly
   against its actual GitHub license metadata), fixing a prior
   assumption that it shared acoreyj/proxies-at-home's MIT license
   just because it's credited from that project. acoreyj/proxies-at-
   home's own MIT label is correct and unchanged; attribution wording
   updated to not conflate the two licenses.

DEVIATIONS:

- Item 5's source instruction was truncated mid-sentence ("Proposal H
  design doc §1: if it labels alex-taxiera/proxy-print as MIT," — no
  completion given). Applied the inferred completion (correct the
  label to AGPL-3.0) since it matches this session's own independently
  verified research from earlier in the task, and is the only
  MIT-labeled claim about that project in the file. Flagging explicitly
  in the PR body in case more than this one correction was intended -
  no further action taken pending confirmation.
- Item 2's "Approved spec (verbatim)" line in proposal-b (the
  MEMORY DISCIPLINE bullet) was edited despite the file's own stated
  convention that the approved-spec section stays a verbatim record of
  what was approved. Judged proprietary-name removal (a legal/IP
  hygiene concern applying repo-wide per this task's explicit
  instruction) to take precedence over that narrower verbatim-record
  convention, which is about preserving decisions/content, not literal
  third-party product names. Noting this call rather than silently
  overriding the file's own stated rule.

VERIFICATION:

- `python3 .github/scripts/docs_lint.py` — clean, no broken
  [[wiki-links]], markdown links, or backtick-path-shaped references.
- Independent research-agent sweep of all docs/ (excluding
  docs/reports/) for other proprietary/commercial product-name design
  comparisons, using both phrase-pattern greps and a targeted
  candidate-name list — zero new hits; confirmed every other
  capitalized product-like name in scope is a factual named
  integration (Discord OAuth, Google Drive, Scryfall, DriveThruCards/
  MakePlayingCards/PringlePrints/NotMPC as real export destinations,
  etc.), not a design-reference comparison, and therefore correctly
  out of scope.
- proposal-b's persistence correction cross-checked directly against
  shipped frontend code (projectSlice.ts, cookies.ts,
  listenerMiddleware.ts, constants.ts) rather than trusting either the
  task's framing or the doc's own prior text at face value.

OPEN ITEMS / DECISIONS NEEDED:

1. Item 5's cut-off instruction — confirm the AGPL-3.0 correction is
   the complete intended fix, or supply the rest of the original
   sentence if more was meant.
2. PR #100 is open against this fork's own master, awaiting the
   owner's merge-queue action (per standing rule: no `gh pr merge` from
   this session).

LIVE STATE: branch docs-conventions-hygiene-batch-cvq14g pushed to
origin; PR #100 open against ProxyPrints/ProxyPrints.github.io master,
unmerged. No branch deletions performed this task. No uncommitted work
left behind.
```
