```
TASK: Reconciliation sweep — inventory all outstanding work on
ProxyPrints/ProxyPrints.github.io (open PRs, branches without merged
PRs, parked HOLD items), classified per the orchestration lane's
dispatch. Read-only inventory; nothing merged, closed, deleted, or
pushed as part of this sweep. Deferred from the 2026-07-19
drafting/ratification session per its Dispatch-cadence rule (see
proxyprints-orchestration's progress.md, "Dead ends / WIP state");
unblocked once PRs #136/#137 landed.

WHAT SHIPPED:

OPEN PRS (1 total):
- #116 "Proposal H: Select Version section unified spec" (HOLD,
  docs-only, +124/-1, branch
  claude/proposal-h-select-version-spec-04bam2) — CLASSIFIED
  awaiting-owner-merge, but not actually mergeable yet: "Formatting and
  static type checking" check is RED (pre-commit step failure, run
  29670063827 / job 88147314285); the other 3 checks are green. Needs
  a formatting fix before an owner merge click actually resolves it.

BRANCHES (59 total on origin, excluding master; upstream/* remote
branches belong to chilli-axe/mpc-autofill and were excluded):

- Merged into master, branch not yet deleted (5): safe cleanup —
  claude/questionfeed-count-diagnosis-inqvoq-followup,
  worktree-catalog-completion-part2, worktree-local-printing-id-pilot,
  worktree-ocr-normalization-fix, worktree-queue-question-feed.
  CLASSIFIED superseded-close.
- Had a PR that merged, branch not yet deleted (7): #93, #98, #97,
  #92, #107, #26, #115 — content confirmed landed via `gh pr list
  --head`. CLASSIFIED superseded-close.
- Had a PR that closed WITHOUT merging, content confirmed superseded
  elsewhere (3): #71 (bleed-override work landed separately as
  docs/reports/proposal-b-pr2-bleed-override-ui.md), #95 (the
  documented #88/#94/#95 duplicate-rebuild incident already in
  CLAUDE.md), #84 (design content now lives in master's
  docs/proposals/proposal-h-unified-display-page.md). CLASSIFIED
  superseded-close.
- Never had a PR anywhere, real multi-file content (6, all
  upstream-fix-*/upstream-feat-*): upstream-feat-local-file-source,
  upstream-fix-frontend-searchable-the, upstream-fix-image-cdn-cors,
  upstream-fix-pdf-canvas-preview, upstream-fix-pdf-eager-wasm-load,
  upstream-fix-pdf-thumbnail-worker-route. Checked both this fork and
  chilli-axe/mpc-autofill — no PR either place. CLASSIFIED mid-flight
  resumable, intentionally dormant (consistent with the "upstream
  deprioritized" stance).
- Never had a PR, single-file doc/report additions (4):
  claude/frontend-polish-review-52vy6h, assets/whatsthat-branding,
  claude/ui-content-audit-docs,
  claude/extractable-primitives-ledger-08cik4. CLASSIFIED mid-flight
  resumable — real, small, self-contained; owner call on PR-ing vs.
  discarding.
- report-relay*/*-relay* delivery branches (~23): report-relay,
  report-relay-6121bf36(-2..-10),
  report-relay-catalog-completion-part2-{1784403566,1784407416,1784411650},
  report-relay-cvq14g, report-relay-discord-signin-diagnosis-d0e8e5,
  report-relay-part4-status-confirmation-eeaa5d,
  report-relay-proposal-g-{checkpoint-8f2c1a,final-wrap-c81e4f,pr4b-complete-3f9a2c,pr88-recovery-7b21d4},
  report-relay-test-suite-audit-we1qms,
  report-relay-wiki-review-verify-3f9a2c,
  claude/proposal-h-relay{,2..7}-04bam2,
  claude/priority-fix-relay-04bam2. CLASSIFIED superseded-close by
  design (one-shot report-delivery vehicles per CLAUDE.md's
  report-relay convention).
- worktree-finish-upstream-460: no PR anywhere, oldest commit in the
  set (2026-07-14), a self-merge
  ("Merge branch 'worktree-merge-upstream-460' into
  worktree-finish-upstream-460"). NOT CLASSIFIED — flagged for a
  closer look, likely superseded by later upstream work but unconfirmed.

PARKED HOLD ITEMS: two found. #116 (above) and
docs/federation/public-export-v1.md ("SPEC DECIDED... BUILD hold
remains" — spec merged via #92, implementation intentionally not
started). docs/federation-v1.md is a separate, older spec with no HOLD
marker (just "implementation pending"), not counted as parked. No
other docs/proposals/*.md carries an active HOLD marker.

DEVIATIONS: none from the requested scope. Did not open/read every
no-PR branch's full diff, did not line-by-line verify report-relay
content against corrections/lessons.md, did not check
proxyprints-orchestration's own branches (out of scope — that repo's
own housekeeping belongs to whoever operates it, not this sweep).

VERIFICATION: `gh pr list -R ProxyPrints/ProxyPrints.github.io
--state open`, `gh pr view` on each closed/merged PR referenced above,
`gh pr list --head <branch>` cross-referenced against the current
branch list, `gh api .../check-runs` on #116's HEAD commit (not the
legacy Status API, per CORR-0006). All read-only.

OPEN ITEMS / DECISIONS NEEDED:
1. #116: fix the formatting/type-check failure before it's genuinely
   mergeable — currently blocked on that, not on an owner click.
2. worktree-finish-upstream-460: needs a closer look before
   classifying; oldest unclassified branch in the set.
3. Report-relay branches: flagged risk — if any durable fact inside
   one wasn't distilled into docs/lessons.md, corrections/, or
   progress.md before the branch went stale, deleting it loses that
   fact permanently. Recommend an owner or docs-lane spot-check before
   any bulk deletion, not a blind sweep.
4. The 5 merged-and-stale + 7 merged-with-PR branches (12 total) are
   safe to delete per the merge-duty precondition already in CLAUDE.md
   (`gh pr list --base <branch>` empty) — not done in this sweep since
   it was scoped read-only; a follow-up cleanup pass can action this
   list directly.
5. The 4 no-PR single-file docs and the 6 dormant upstream-* branches
   are real, owner-decidable: PR them, or explicitly mark discarded.

LIVE STATE: nothing merged, closed, deleted, or pushed by this sweep
itself. This report is being committed on a fresh worktree branch as
part of the same session's ongoing work.
```
