```
TASK: Absorption check for #467 (frontend toSearchable "the"-fix) —
branch `claude/upstream-readiness-audit-cvq14g`, commit `8b3e3ea9`,
pushed. No PR opened; nothing touches upstream.

WHAT SHIPPED, per the five items:

1. FIRST FINDING: **the task's stated premise does not hold up.**
   Checked directly (not assumed): our `origin/master`'s current
   `frontend/src/common/processing.ts::toSearchable` does NOT contain
   the "the"-stripping lines — the bug does not exist on proxyprints.ca
   today. Our fork independently fixed this identical bug via commit
   `206a0266`, merged as our own PR #20 (`121b5c06`), on 2026-07-13/15 —
   *before* #467 was even opened upstream (2026-07-13) or merged
   (2026-07-18). This isn't new information either:
   `docs/infrastructure.md` already documented "our own fork had
   already fixed the identical bug in its own processing.ts" before
   this check started — the premise was checkable against the repo's
   own existing docs, not just git archaeology.

2. CROSS-LAYER SAFETY: backend `to_searchable()`
   (`cardpicker/search/sanitisation.py`) stopped stripping "the" via
   the literal *shared* upstream commit `4e960183` ("do not sanitise
   'the' in card names", PR #460, author AurelienBou/glandu-sr),
   merged into our `master` ~2026-07-04 — verified this is the same
   SHA on both `origin/master` and `upstream/master`
   (`git merge-base --is-ancestor` confirms), not an independent
   reapplication. Our frontend fix (item 1) was written ~9 days later
   specifically to restore parity with that backend fix (per its own
   commit message). Upstream's own backend never stripped "the" as of
   #460 either — confirmed by reading `upstream/master`'s current
   `sanitisation.py` directly, same file we share.

   Also worth recording: frontend's `toSearchable` and backend's
   `to_searchable` are NOT actually a query-time/index-time pair for
   the *same* index — frontend's copy is used only by the client-side
   (Local Folder/Orama) search (`clientSearchService.worker.ts`,
   `indexer.ts`), rebuilt fresh client-side every session, no persisted
   index to desync. Backend's copy is used for both index-time
   (`sources/update_database.py`) and query-time
   (`search/search_functions.py`) ES normalization — same single
   Python function called from both sites, structurally immune to
   index/query drift within that layer. The real (and only) risk this
   whole area has ever had is the two *layers'* copies drifting from
   each other, which is exactly what happened historically (both within
   our own fork for ~9 days, and upstream for the full time until
   #467) — and is what item 3 below verifies isn't currently happening.

3. VERDICT: **zero absorption needed** — not "frontend-only is
   provably safe" (a false choice given the actual finding), but "there
   is no gap to close": both layers already agree, and have since
   before #467 existed. Verified empirically, not just by reading
   source: ran the actual current `toSearchable` (Node.js, transcribed
   verbatim from `processing.ts`) and `to_searchable` (Python, imported
   directly from `sanitisation.py`) against 8 real card names, including
   two substring-only "the" cases a careless word-boundary bug could
   mishandle differently per layer ("Theros", "Bother" — neither
   contains the word "the" as a token, only as a substring). Output was
   byte-identical on all 8 across both languages. A live-ES query
   simulation wasn't possible in this sandbox (no Docker/ES available,
   consistent with this session's standing environment constraint) —
   this direct-execution comparison is the honest substitute: if the
   normalized strings match, whatever ES indexes and whatever the
   frontend/backend query with will match too, regardless of whether a
   live ES instance was reachable here.

   Recorded in `docs/infrastructure.md`'s existing #467 narrative
   (edited in place, not a new doc) rather than filed separately, per
   this repo's own docs convention.

4. Convention added to `docs/upstreaming/conventions.md`: "Back-
   absorption is a tracked task, not an assumption... author ≠
   absorbed; check explicitly (cross-layer, not just the one file the
   PR touched) rather than assuming parity."

5. `docs/upstreaming/drift-log.md` refreshed: `upstream/master` has not
   moved since the 2026-07-18 seed (`git rev-list --count
   c3d10253..upstream/master` = 0) — all six tracked branches'
   applies-clean/commits-since/touching-files figures re-verified
   identical to the seed, only the "Last run" timestamp updated
   (18:27 UTC).

DEVIATIONS from spec: none from the five items as given. Where the
task's own stated "finding to verify" turned out to be false, reported
that plainly (item 1) rather than working around it or writing the doc
as if it were true.

VERIFICATION: what ran, with results —
- `git show origin/master:frontend/src/common/processing.ts` — no
  "the"-stripping lines present.
- `git cat-file -t 206a0266` + `git show 206a0266`/`121b5c06` — real
  commits, exact same two-line removal + same test case as #467.
- `git merge-base --is-ancestor 4e960183 upstream/master` — confirms
  shared commit, not independently reapplied.
- `git show upstream/master:MPCAutofill/cardpicker/search/sanitisation.py`
  — no "the" handling on upstream's backend either.
- `grep -rn "toSearchable(" frontend/src` /
  `grep -rn "to_searchable(" MPCAutofill/cardpicker` — mapped every real
  call site on both sides to confirm the index-time/query-time
  structure described in item 2.
- Direct execution: Node.js script transcribing the exact current
  `toSearchable` body + Python import of the exact current
  `to_searchable` — 8 test names, byte-identical output, shown in full
  in the commit this relays.
- `git rev-list --count c3d10253..upstream/master` = 0 — confirms
  upstream hasn't moved since the last drift check.

OPEN ITEMS / DECISIONS NEEDED: none new.

LIVE STATE: `claude/upstream-readiness-audit-cvq14g` pushed to
`origin` at `8b3e3ea9`. No code changes — `frontend/src/common/processing.ts`
and `MPCAutofill/cardpicker/search/sanitisation.py` are unmodified;
this task was pure investigation + doc updates. Lane returns to
dormant.
```

Full blob URL (once this relay commit lands):
https://github.com/ProxyPrints/ProxyPrints.github.io/blob/report-relay/docs/reports/2026-07-18-absorption-check-467.md
