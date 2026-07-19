# docs/reports/

Relayed work-product reports — point-in-time findings from a session or
agent pass, written up for a later reader instead of staying trapped in
that session's own transcript. Not living reference: check each report's
own "as of" date before trusting anything in it as current.

`schema.json` is a structured mirror of the six-field standing report
format (CLAUDE.md's Reporting convention) — the prose report is still
the record of truth for a human reader; the schema exists for tooling
that needs to route on verdict/deviations/open-items without
re-parsing prose. Tiered: a `summary` object read on every report, and
a `detail` object read only when the summary signals it's needed.

- `2026-07-18-part3-fullrun.md` — Part 3 catalog-completion fullrun
  status + backfilled HOLD #P3 record.
- `2026-07-18-part3-fullrun-data-loss.md` — the fullrun dry-run's
  stdout capture lost to a `--rm` race, and the write-pass decision
  fork that followed.
- `2026-07-18-part3-write-pass-complete.md` — Part 3's write pass
  completion: bounds verified, zero-resolution assertion, queue
  spot-check.
- `2026-07-18-pr62-hard-gate.md` — PR #62's full pytest hard-gate
  results, a real snapshot-drift regression found and fixed, schema
  regen consistency check.
- `2026-07-18-pr62-merge-and-deploy.md` — PR #62 merged, the item-C
  deploy sequence, the live E-2 ground-truth check against production.
- `2026-07-18-merge-sweep-checkpoint-1.md` — merge-sweep checkpoint
  covering PRs #64/#65/#66/#67/#69 (recreated as #72 after a
  base-branch-deletion incident).
- `2026-07-18-ai-to-machine-terminology.md` — "AI" → "machine"
  terminology fix for OCR/phash/deduction vote sources, docs +
  frontend + a backward-compatible settings rename.
- `2026-07-18-wiki-review-findings.md` — publish-script link-rewrite
  fix, Part 3 write-pass status update, and a targeted staleness
  mini-pass across proposal docs and docs/README.md.

Note: a separate, unrelated session also used the bare `report-relay`
branch name for its own work (upstream-ladder CI, federation-v1 doc
updates) — a genuine cross-session branch-name collision, not a typo.
Only this session's own file above (`2026-07-18-part3-fullrun.md`) was
pulled from that branch; the other session's commits on it were left
untouched, not reviewed or merged here.
