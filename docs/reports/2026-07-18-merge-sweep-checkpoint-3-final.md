TASK: SERVER session — mini merge sweep (7 PRs) + task #134 calibration pass, final
Branch/worktree: catalog-completion-part2

WHAT SHIPPED:

1. #77 (Proposal G bleed-override note) — merged, branch deleted.
2. #75 (chunk-load-error cache-transition recovery) — merged, branch
   deleted.
3. #74 (wiki+docs automation first-publish verify) — merged, branch
   deleted.
4. #76 (AI→machine terminology) — CI-decomposed (14 known-bucket
   failures, 130/130 snapshots pass), setting-rename shim confirmed
   shipped. Merged, branch deleted.
5. #73 (B PR-3 WYSIWYG bleed badge, stacked on closed PR #71/e3) —
   retargeted to master per the stacked-PR lesson. Resolved a real
   7-file conflict in a scratch clone; a collision warning fired,
   investigated, turned out to be my own scratch-clone residue at
   first — then a genuine second collision: the frontend session had
   independently retargeted + pushed its own resolution to the same
   PR. Discarded mine as instructed. Checked the frontend session's
   pushed head directly (not on their word): it did NOT match "verified
   green" — prettier failing on 4 files, 3 real Playwright failures in
   PagePreview.spec.ts (every test in the "fast page preview" describe
   block failing on the same symptom, reads as a render crash in the
   new badge code, not a flake). HELD, not merged, filed as task #135.
   #73 has since been retitled by the frontend session to "PR-2 + PR-3:
   manual-override UI + preview badge (recovered stack)" and remains
   open/unresolved as of this report - still theirs to fix.
6. #56 (UI content-accuracy audit findings, HOLD/draft) — disposition
   column was already fully populated by the #64 build-pass worker (all
   11 selected items "Built - ...", #11 "Not selected... process fix
   instead"); confirmed PR #64 itself already merged. No edit needed.
   Marked ready, merged as the paper record, branch deleted.
7. #19 (sandbox modal-open-timeout flake, 4 days old) — read in full:
   docs-only, no existing lessons.md entry covers it, content still
   accurate (deterministic Claude-Code-cloud-sandbox Playwright quirk,
   not a real regression, reproduces on unmodified master). Verdict:
   finish-and-merge. Resolved a clean append-only conflict in
   docs/lessons.md (both sides append distinct new sections). Merged,
   branch deleted.
8. report-relay-7 consolidated into master directly (single new report
   file, no PR needed - solo-repo push policy), stale branch deleted.
9. Task #134 (PR #66 bleed-measurement calibration, separately queued):
   ran the shipped algorithm against 30 real catalog images fetched
   through the production image-CDN (rate-limiter-respecting). Found a
   real, reproducible measurement bias (~2x overshoot vs true bleed
   target, root-caused to bleed+card-border color conflation, not a
   threshold or DPI bug - confirmed via a full threshold sweep and a
   dimension check). All 4 constants left at defaults - no single one
   cleanly fixes this without an unreviewed resolveBleedPlan behavior
   change, so it's documented in the code's calibration comment and
   tracked as a design follow-up in the proposal doc, not patched
   blind. Shipped as PR #80 (separate branch, since my actual worktree
   here is on an unrelated older branch, part3-evidence-recovery, that
   predates Proposal B entirely). Merged, branch deleted.
10. Two rounds of pre-existing, unrelated formatting drift found and
    fixed directly on master (docs/reports/cache-transition-resilience.md
    from #75's merge predating the CI-trigger fix; docs/audits/
    ui-content-audit.md from #56's merge) - both were blocking every
    other open PR's formatting check, not just the PR being worked at
    the time.
11. GitHub Pages deploy of the final master state confirmed successful
    (workflow run against the latest merge, status=completed,
    conclusion=success).

DEVIATIONS:

- #73: NOT merged despite the explicit "MERGE IT AS-IS, verified green"
  instruction, because direct inspection of the live check-runs at the
  given head SHA contradicted that characterization. Reasoning and full
  failure logs are in the earlier checkpoint-2 report (already relayed).
- Task #134: constants left unchanged rather than tuned, per its own
  "tune... if the defaults misbehave" framing - the defaults DO
  misbehave (documented at length), but no single constant fixes the
  actual root cause without becoming a same-session design decision
  beyond a calibration pass's charter. Flagged, not silently dropped.

VERIFICATION:

- Every merge checked via `gh api .../pulls/<n>` (mergeable_state) and
  `gh api .../commits/<sha>/check-runs` at the ACTUAL current head SHA,
  not assumed from a prior check or a report's characterization.
- Task #134's PR (#80): 8/8 existing bleedNormalize.test.ts tests still
  pass unchanged (comment/docs-only diff, confirmed no functional code
  change); full CI (formatting, lint, all 4 frontend test shards,
  Playwright report merge) green before merging.
- Pages deploy confirmed via the workflow-runs API, not assumed from the
  merge alone.

OPEN ITEMS / DECISIONS NEEDED:

1. #73 is still red/unresolved and is the frontend session's branch to
   fix - needs their attention, not further action from this session
   unless re-authorized.
2. Task #134's flagged production risk (resolveBleedPlan over-trimming
   real bled cards under the current OVERSIZED_MULTIPLE) needs owner or
   spec-owner input before anyone builds a fix - full reasoning in
   docs/proposals/proposal-b-bleed-normalization.md's "Tracked, not
   building" section and docs/reports/2026-07-18-bleed-calibration-134.md.
3. #78 and #79 are open PRs neither in my instructed queue nor touched
   by this session - noting their existence, not their content.

LIVE STATE: master deployed and confirmed live via Pages. Open PRs
remaining: #73 (held, frontend session's), #78, #79 (untouched, out of
this session's scope). No scratch clones or uncommitted work left
behind - all work either merged or, for #73, explicitly handed back.
Task queue: #134 completed; #135 (hold #73) still open, tracking the
frontend session's fix.
