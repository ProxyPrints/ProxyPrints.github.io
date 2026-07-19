```
TASK: Duplicate-work discovery + resolution on PR #129 (federated gate
fix + wiki-publish follow-up) — branch
federated-gate-wiki-publish-followup-cvq14g — PR #129 (open, reduced
scope) + PR #127 (a different concurrent session, unaffected by this
session, left open for the owner to review normally)

WHAT SHIPPED:
1. CI FAILURE INVESTIGATED, ROOT-CAUSED AS PRE-EXISTING/UNRELATED — PR
   #129's "Backend tests" job failed (14 tests). Investigated: none of
   the 14 failures touch vote_consensus.py or anything this PR changed
   — they're TesseractNotFoundError (binary missing in the CI runner),
   a JSONDecodeError on a missing snapshot fixture, and a moxfield URL
   check returning None. Confirmed via list_workflow_runs: every recent
   test-backend.yml run across ~15 unrelated branches also shows
   "failure" — this is a standing, pre-existing environmental issue
   affecting every PR in this repo right now, not something this
   session's change caused. test_vote_consensus.py itself: 0 failures
   (898 passed, 1 skipped total in the run).
2. DUPLICATE WORK FOUND while investigating that CI run's neighboring
   runs: PR #127 (branch claude/federated-machine-derived-gate-fix, a
   DIFFERENT concurrent Claude Code session, opened 2026-07-19T04:23:22Z
   — before this session's own push) independently built the exact
   same federated-gate defensive fix: same file
   (MPCAutofill/cardpicker/vote_consensus.py), same
   VoteSource.FEDERATED -> _MACHINE_DERIVED_SOURCES addition, same
   defensive-default reasoning, functionally identical diff (confirmed
   via a direct file-diff comparison, not assumed from titles alone).
3. RESOLVED by reverting the duplicate, not by asking the owner to
   arbitrate between two near-identical diffs: vote_consensus.py,
   test_vote_consensus.py, and the docs/federation-v1.md doc update
   reverted out of THIS branch (a new commit, "Revert the federated-gate
   code fix from this branch — duplicate of PR #127" — no force-push,
   no history rewrite, the original commit stays in this branch's
   history as a record). PR #129 retitled and its body rewritten to
   reflect the reduced scope (wiki-publish-map.json only) and explain
   why. Left ONE comment on PR #127 (not touched further) flagging a
   real, small gap in ITS OWN body: it claims "no doc changes needed,"
   but docs/federation-v1.md's "Known gate issue" section still says
   the bug "returns True today" and "Status: flagged, not built" —
   both go stale the moment #127 merges. Did not close or otherwise
   act on PR #127 itself — not this session's PR to close, and it's
   healthy (same pre-existing CI noise, nothing #127-specific).

DEVIATIONS: none from standing convention — this is exactly the
"search for an existing recovery/duplicate first, don't silently ship
the same change twice" discipline CLAUDE.md already establishes for
lost/auto-closed PRs (the #88 precedent), applied here to a live
duplicate found mid-flight rather than a lost one found after the
fact.

VERIFICATION: docs_lint.py clean after the revert; real publish_wiki.py
scratch-dir run still succeeds, 0 link errors, wiki-publish-map.json's
4 new entries still generate correctly. git diff origin/master --stat
confirms the branch now touches exactly one file
(.github/wiki-publish-map.json, 20 insertions) — no residual trace of
the reverted duplicate in the branch's net diff against master.

OPEN ITEMS / DECISIONS NEEDED:
1. docs/federation-v1.md's "Known gate issue" section still needs
   updating to describe the shipped fix accurately, once PR #127
   merges — flagged on #127 itself; whoever picks it up (that session,
   or a follow-up here) should update it. Not done in either PR right
   now, to avoid the doc going stale in one direction (claiming a fix
   landed before #127 actually merges) or the other (never getting
   updated because both sessions assumed the other would).
2. PR #127 is a different session's PR — not this session's to merge,
   close, or further modify. Surfaced here for the owner's awareness
   since it directly explains why PR #129 changed scope mid-review.

LIVE STATE: branch federated-gate-wiki-publish-followup-cvq14g pushed
(commit 601170b2 on top of 76b0f7e0, no force-push). PR #129 open
against master, reduced scope (wiki-publish-map.json only), title/body
updated to explain the reduction. PR #127 (a different session's PR)
left open and untouched beyond one clarifying comment. This report
committed to report-relay-cvq14g and pushed.
```
