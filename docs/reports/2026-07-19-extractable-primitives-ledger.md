# Extractable-primitives ledger — session report, 2026-07-19

```
TASK: repo-wide extractable-primitives ledger, branch
claude/extractable-primitives-ledger-08cik4, commit 02a0b1f7 (pushed, no
PR opened — none requested).

WHAT SHIPPED:
1. docs/upstreaming/extractable-primitives.md — one ledger, split into
   4 area tables covering the whole codebase (frontend search/browse,
   frontend PDF/export, backend, docs/federation tooling): primitive |
   file(s) | problem solved | candidate consumers | entanglement status
   | license note. 27 rows total: 17 CLEAN, 10 entangled (one of those
   10 is entangled-with-image-cdn-infra, outside the 4 tether
   categories but flagged honestly anyway).
2. SEED PASS — audited every named starter (embeddable
   GridSelectorResults, exported PDF hooks, sheet-level virtualization,
   missing-image placeholder, RequestedPrintingBadge, lh4 rate limiter,
   sanitisation drift fix, OCR crop/preprocessing helpers, batch-flush
   checkpoint pattern, docs single-transform pipeline, federation hash
   tool) plus additional candidates surfaced along the way (generic UI
   kit, concurrency helpers, phash storage utility, ES connection
   helpers, upstream-wiki-drift tracker). Judged each honestly —
   several "obviously reusable" pieces turned out entangled by
   co-location (a clean function sitting in a file whose *other*
   top-level imports pull in the vote system), not by their own logic.
3. MECHANICAL TETHER — check_extractable_primitives_tether() added to
   .github/scripts/docs_lint.py, riding the existing docs-lint CI job
   (every PR touching docs/**, weekly regardless). For every row
   marked CLEAN, it greps the listed file(s)' own import statements
   (TYPE_CHECKING-guarded imports excluded) against a hardcoded
   fork-only-module allowlist (vote system / CanonicalPrinting-
   consensus / auth-Discord — exact modules and symbols live as
   constants in the script, not duplicated in the doc). One level
   deep, not transitive — documented as a known limitation, same
   shape as docs_lint.py's existing heuristics.
4. CONVENTION LINE added to CLAUDE.md's Tooling rules: sessions add or
   remove a ledger row when an extraction/refactor produces or
   destroys a clean primitive, judged at write time.

DEVIATIONS:
- The tether ended up ~190 lines, not literally "tiny" — Python and TS
  import syntax both needed real handling (multi-line parenthesized
  Python imports, named-symbol imports from shared files like
  store/api.ts) to avoid false negatives. Kept regex-based rather than
  a real AST/import-graph resolver, matching docs_lint.py's existing
  style and its own stated "known limitations, not a heavier tool"
  convention.
- Rows beyond the named seed list (generic UI kit, concurrency
  helpers, phash storage utility, ES connection helpers) were added —
  the instruction to "judge each honestly" implied a repo-wide audit,
  not a checklist limited to the 11 named starters.
- docs/upstreaming/extractable-primitives.md was NOT added to
  .github/wiki-publish-map.json. Reasoning: the doc is explicitly HOLD
  (owner review pending) and documentation-process.md's stated
  exclusion for docs/proposals/ ("drafts/HOLD specs — not yet real,
  shouldn't read as if they are") applies in spirit even though this
  file lives under docs/upstreaming/, not docs/proposals/. Listed as
  an open decision below rather than assumed either way.

VERIFICATION:
- `python3 .github/scripts/docs_lint.py` — clean, exit 0, against the
  real repo state (all 17 CLEAN rows genuinely pass the tether).
- `python3 -m py_compile .github/scripts/docs_lint.py` — compiles.
- Manual sanity checks: known-entangled files (local_fallback.py,
  local_phash.py, bleedPriorResolution.ts, search_functions.py)
  correctly flagged; known-clean files (local_ocr.py with its
  TYPE_CHECKING-only reference, utils.py, RenderIfVisible.tsx)
  correctly pass; found and fixed one real bug mid-verification (the
  first regex draft didn't match multi-line parenthesized Python
  imports, silently missing local_fallback.py's actual entanglement —
  caught by testing against a known-bad file, not by inspection). One
  end-to-end test against a scratch table with a deliberately false
  CLEAN claim confirmed the full row-parsing path fails correctly.
- Did not run the frontend/backend test suites — no runtime source
  changed, only docs/ and a CI lint script; out of scope for this task.

OPEN ITEMS / DECISIONS NEEDED:
1. Add docs/upstreaming/extractable-primitives.md to
   .github/wiki-publish-map.json now, or hold back until the HOLD
   review clears? Currently not added.
2. Real per-row upstreaming decisions (does this fork actually want to
   send any of the 17 CLEAN primitives to upstream mpc-autofill /
   proxies-at-home / a federation peer) are explicitly out of scope
   for this audit and left undecided in the doc itself — the owner may
   want to prioritize a short list from it.
3. frontend/src/features/clientSearch/ (the Orama-based client-side
   search indexer) was flagged by the audit as substantial enough to
   deserve its own dedicated extractable-primitives pass rather than
   folding into this table's rows — not started.

LIVE STATE: branch claude/extractable-primitives-ledger-08cik4 pushed
to origin at commit 02a0b1f7 (plus this report as a follow-up commit).
No PR opened. Nothing running, nothing deployed, nothing left
mid-flight.
```
