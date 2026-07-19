```
TASK: Test-suite audit + verification-policy proposal. READ-ONLY (propose,
delete nothing; HOLD with this report). Branch: report-relay-test-suite-audit-we1qms
(new, for this relay only). No source/test files edited, no commits to app code.

WHAT SHIPPED (all 5 requested items):

=== 1. INVENTORY ===

Ran each suite once from a clean state (Jest: fresh `npm ci` first, see DEVIATIONS #1;
Playwright: full run, see DEVIATIONS #2 for why it ran twice; backend: host venv
`~/.venvs/mpcautofill-pilot`, real testcontainers-backed Postgres/ES).

| Suite | Total | Pass | Fail | Other | Wall-clock |
|---|---|---|---|---|---|
| Jest (`npx jest`) | 391 | 369 | 22 | - | 9.1s |
| Playwright (`npx playwright test`, corrected env — see DEVIATIONS #2) | 243 | 211 | 31 | 1 timedOut | 326.8s (~5.5min) |
| Backend pytest (`python -m pytest`) | 910 | 906 | 4 | - | 131.7s (~2.2min) |

**10 slowest individual tests overall** (all Playwright — Jest/pytest max individual
test times are 467ms and ~1.1s respectively, not competitive):
1. 30.1s — `visual/DynamicLogo.visual.spec.ts` "dynamic logo, backend configured" (this one FAILED — timed out at 30s)
2. 25.9s — `InvalidIdentifiersStatus.spec.ts` (param case 1)
3. 25.7s — `ImportXML.spec.ts` "import an XML and use the project cardback"
4. 25.3s / 25.1s — `InvalidIdentifiersStatus.spec.ts` (2 more param cases)
5. 16.5s / 15.9s / 14.7s — `PDFGenerator.spec.ts` (3 tests, all real PDF generation work)
6. 13.7s / 13.6s — `AddCardToFavorites.spec.ts` (2 tests)

**Disproportionate-runtime flags**:
- `InvalidIdentifiersStatus.spec.ts` — 3 parametrized cases averaging ~25s each
  (90.2s file total) to assert a status-message string renders for a few known-bad
  identifiers. Worth checking whether this needs a real search round-trip per case or
  could share one page load across cases — but I did not read this file's internals
  closely enough to recommend a specific fix, just flagging the ratio.
- `visual/DynamicLogo.visual.spec.ts` "backend configured" — 30s (full test timeout)
  for a single visual snapshot of an animated logo; this one actually failed (timed
  out), see item 5 below, so its slowness and its failure are likely the same root
  cause, not two separate findings.
- Everything else's per-test cost looks proportionate to what it exercises (real
  crypto operations in `savedDecks/*`, real PDF byte generation in
  `PDFGenerator.spec.ts`, real multi-card import flows) — I did not find padding or
  obviously-wasteful setup elsewhere.

=== 2. OVERLAP ANALYSIS ===

Conservative pass — I read enough of each candidate to have real evidence, not a
guess, but did not do an exhaustive line-by-line read of all ~40 Jest files + 44
Playwright specs + ~30 pytest files in the time available. Treat this as a solid
first pass, not a completionist audit.

**Retire/merge candidates found: none with high confidence.** This codebase's test
suite is unusually disciplined already — e.g. `PrintingConfirmStrip.tsx` was
deleted outright as dead code once Stage 7 made it redundant (per
`docs/features/printing-tags.md`), rather than left with orphaned tests. I did not
find an analogous case of a still-existing redundant test pair.

**One naming-hygiene finding (not a retirement candidate)**: `tests/ModerationQueue.spec.ts`
no longer tests a `ModerationQueue` component (that component was deleted in the
Stage-7 queue redesign) — its own header comment says so. It currently tests the
navbar `AuthWidget`'s login/logout links, and cross-references `ModerationTab.spec.ts`
for the actual moderation surface. The tests are current and correct; only the
filename is stale. Suggest a rename (`AuthWidget.spec.ts` or similar) as a trivial
follow-up, not a merge/retire action.

**The "green test with a seatbelt on a bug" incident, located**: `docs/reports/level1-scryfall-reference-regression.md`
(2026-07-18). QuestionFeed's Level-1 confirm-suggestion screen shipped (PR #49)
without a reference image, and the 12 pre-existing `QuestionFeed.test.tsx` tests
plus its Playwright coverage stayed green the whole time — not because they asserted
something wrong, but because **none of them asserted on the reference image's
presence at all**. This is a coverage-gap class, not a redundancy class: nothing here
is a candidate to retire; if anything it argues for *adding* assertions when a new
UI surface bypasses an existing one (Level 1 bypasses Level 2's grid), not removing
any. Noted explicitly since the task brief referenced this incident by name and I
wanted to confirm what actually happened before citing it. Relevant to the MATRIX
critique below.

**EXEMPT list (protects a specific past incident, per docs/lessons.md — verified,
not just assumed)**: I did not find any of these on any retirement-adjacent list to
begin with (my candidate list is empty), so there's nothing to mark exempt this
pass. Flagging the ones I'd protect on principle if this audit is redone with a
deeper pass: the `factory.Sequence` shared-factory regression test pattern
(lessons.md), the `z-index`/stacking-context CardPanel test, and the msw/playwright
0.4.5 patch's own coverage — all three exist because a real incident happened once.

**call_count/mock-assertion spot check**: found 3 backend files using
`assert_called`/`call_count` (`test_local_identify_printing_tags.py`,
`test_search_functions.py`, `test_printing_consensus.py`). Spot-checked
`test_printing_consensus.py`'s usage — it asserts `reindex_card_safely` fires
exactly once per real state transition (not per redundant re-vote), which is
*documented, load-bearing behavior* from Stage 3.5's design
(`docs/features/printing-tags.md`), not an implementation-detail smell. Did not find
a genuine "asserts an incidental implementation detail" case in this spot check.

=== 3. THE MATRIX — critique, not a rubber stamp ===

**docs-only → `docs_lint` + pinned prettier. Nothing else.** ACCURATE AS-IS.
`.github/scripts/docs_lint.py` exists, is CI-wired (`docs-lint.yml`), and I confirmed
it runs locally in ~2s (`python3 .github/scripts/docs_lint.py` → "docs-lint: clean.").
No changes needed to this row.

**backend-only → scoped pytest for touched modules + mypy/black/isort; full suite in
CI only.** GAP: there is no `pytest-picked`/`pytest-testmon` or equivalent installed
(checked `requirements.txt` — only `pytest`, `pytest-django`, `pytest-elasticsearch`).
"Scoped pytest for touched modules" currently has no mechanical definition — it means
"manually pass the test file path(s) that obviously correspond to what you touched,"
which works but isn't enforceable/discoverable the way Jest's `--changedSince` is.
Recommend either (a) spell this out explicitly in CLAUDE.md as "run
`pytest cardpicker/tests/test_<module>.py` for each touched `cardpicker/<module>.py`,
by naming convention" so it's a mechanical rule, or (b) add `pytest-picked` as a dev
dependency. Separately: full local backend suite is not actually slow (131.7s/~2.2min
with real testcontainers) — "CI only" is a reasonable default but a worker who wants
certainty before pushing can afford to just run the full thing locally too; this is a
good candidate for the "when in doubt, run more" clause rather than a hard rule.

**frontend component → tsc + jest for touched features + TARGETED Playwright + eslint/
prettier. Full Playwright = CI.** ACCURATE IN SPIRIT, but needs one load-bearing
prerequisite added explicitly: **before trusting ANY local Playwright result, confirm
`frontend/.env.local`'s `NEXT_PUBLIC_BACKEND_URL` is either unset or exactly
`http://127.0.0.1:8000`** (the origin MSW's handlers are hardcoded to intercept, per
`frontend/src/common/test-constants.ts`). A mismatch doesn't error — it silently
routes requests around every mock, past MSW entirely, and produces mass "stuck on
Loading..." failures that look exactly like a systemic regression (I hit this
directly this session: 236/243 specs failed with a stale `.env.local` value left
over from unrelated live-backend verification work, all 27 spot-checked specs passed
once corrected — see DEVIATIONS #2 and the new troubleshooting.md entry below). This
is now documented so it doesn't cost the next person the same investigation time.
Also: the Level-1 coverage-gap incident (item 2 above) means "targeted Playwright for
the touched surface" is only as safe as that surface's existing spec *coverage*, not
just its existence — a scoped run doesn't rescue you from an assertion that was never
written. Worth a one-line acknowledgment in the matrix that scoping trades exhaustive
coverage for speed and that's a real, accepted tradeoff, not a free lunch.

**/display-area → above + DisplayPage* specs + flag-on production build (stays
local).** ACCURATE. One correction: currently exactly one spec file matches
(`DisplayPage.spec.ts`) — the glob is future-proofed correctly, just noting there's
no plural set to enumerate yet. Flag-on build: confirmed `next.config.js` uses
`output: "export"` (static export) and `NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED` is a
build-time-inlined env var, so a flag-on build's *output* genuinely differs from a
flag-off build and can't be skipped — but see SPEED LEVERS below on cache reuse for
the *compile* step.

**crypto/auth/votes/migrations → full local battery, no shortcuts.** ACCURATE, no
changes. The `savedDecks/*` crypto tests are real (not mocked crypto), appropriately
among the slower Jest tests (300-470ms each) — consistent with the "blast radius
earns it" reasoning already in the draft.

**cross-cutting (shared components, processing.ts, types) → full local battery.**
ACCURATE, no changes. `processing.ts` has high fan-in (search re-rank, match
indicator, printing-tag consumption per `docs/features/printing-tags.md`) — this row
is correctly conservative.

**"When in doubt, run more" clause**: recommend exactly this one-liner, since the
draft asked for it and I found no reason to complicate it: *"If you're unsure which
tier your change falls under, run the next tier up — a slower local check is always
cheaper than a broken CI run or a live incident."*

=== 4. SPEED LEVERS (reported only, nothing applied) ===

- **`jest --changedSince` viability**: Jest 30.2.0 supports it natively (no plugin
  needed). Works fine for LOCAL use (this clone has full git history). Would NOT work
  inside CI as configured — `.github/workflows/test-frontend.yml` uses
  `actions/checkout@v6` with no `fetch-depth` override (shallow, depth 1) — but that's
  moot since the matrix already scopes `--changedSince`-style behavior to local-only
  and CI already runs the full suite (CI's `test-frontend.yml` already shards Jest 4
  ways, `shardTotal: [4]`, so CI's own speed lever is already in place independently).
- **Playwright worker parallelism**: `playwright.config.ts` has `workers: undefined`
  (Playwright's own default, roughly half of available CPUs outside CI). This box has
  8 CPUs (`nproc`). Headroom exists to raise this explicitly, but I'd caution against
  it based on what I just observed: running Jest + two full Playwright passes
  back-to-back on this box, concurrently with a live production pilot job
  (`local_lands_identify`, PID 3201080, untouched throughout — confirmed unaffected
  at the end), produced a cluster of `ERR_CONNECTION_REFUSED`/"browser has been
  closed" failures in the second Playwright run (see VERIFICATION below) that look
  like resource contention, not real bugs. Raising worker count on a box that's
  already sharing CPU with a live job could make this worse, not better. Recommend
  leaving `workers: undefined` as-is unless verified in isolation (no concurrent load).
- **Flag-on build cache reuse**: `frontend/.next/cache/webpack` exists (360MB,
  confirmed present from a prior build) and Next.js's webpack persistent cache is
  reusable across builds regardless of `NEXT_PUBLIC_*` values for unchanged modules —
  so a flag-on build CAN warm-start from the same cache directory as a normal build
  and will compile faster than a fully cold build. It cannot skip the build or reuse
  the flag-off build's *output* directly, though — the env var is inlined at build
  time, so the emitted bundles genuinely differ and a separate build run is still
  required, just a cheaper one.
- **Collection-flakiness mitigation**: I could not find a documented "Playwright
  collection flakiness" entry anywhere (`docs/troubleshooting.md`, `docs/lessons.md`,
  `docs/reports/`, `journal/`) under that name — see DEVIATIONS #2 for what I now
  strongly suspect this actually refers to (the `.env.local`/MSW-origin mismatch I
  found and fixed this session, freshly discovered, possibly not yet written up
  anywhere the task brief's author could cite it by name). The one thing that IS a
  documented, named, environment-independent Playwright flake is the msw/playwright
  0.4.5 `route.continue` race on `CardSlot.spec.ts` (`docs/infrastructure.md`) —
  already patched via `patch-package`, no further mitigation needed there. If the
  brief meant something else entirely, I don't have it; flagging honestly rather than
  guessing.

=== 5. SANITY-CHECK RIDE-ALONG — drift found ===

**Backend (4 failures, not 14)**: `docs/infrastructure.md`'s older count ("4 backend
tests fail... 2 Moxfield, 2 Google Drive creds") is what actually reproduces on THIS
box — confirmed: 2 moxfield (`test_valid_url[moxfield]`,
`test_valid_url[moxfield_without_www]`, real network calls to moxfield.com
returning None) + 2 Google Drive OAuth (`test_comprehensive_snapshot`, `test_upsert`,
real `credentials._refresh` failures). **Zero tesseract-missing failures** — verified
`tesseract 4.1.1` is installed at `/usr/bin/tesseract` on this host. The newer "14
failures, 11 tesseract-missing" bucket documented in
`docs/reports/2026-07-18-merge-sweep-checkpoint-2.md` is real but appears to describe
a CI or differently-provisioned sandbox environment, not this server box — the two
docs have drifted apart and should probably both note which venue each count applies
to, rather than reading as contradictory.

**Jest (22 failures, all one real, currently-broken cause — not resource
contention, not a known bucket)**: every failure is in
`src/features/searchSettings/comparison.test.ts`
(`comparison.ts`'s `areSetsEqual`/`compareSourceSettings` use ES2024
`Set.prototype.isSubsetOf`/`symmetricDifference`), which this environment's Node
20.20.2 does not implement (`typeof Set.prototype.isSubsetOf` → `undefined`; these
need Node 22+ or a polyfill, and there is no `core-js`/polyfill dependency in
`package.json`). Traced the code back to commit `751b3024` ("Vote-system Stage 3" —
an old commit, #9). This is real, currently red, and outside every documented
bucket. **This is the single most actionable finding in this audit**: either pin CI/
this box to Node 22+, or add a polyfill, or rewrite `comparison.ts` without ES2024
Set methods — I did not implement any of these (out of scope, read-only), just
confirmed the cause precisely.

**Playwright (31 failures + 1 timeout on the corrected-env run)**: mixed picture,
reported honestly rather than resolved cleanly given the time budget:
- A cluster in `ImportText/ImportCSV/ImportXML.spec.ts` (~20 of the 31) all show the
  identical `net::ERR_CONNECTION_REFUSED at http://localhost:3000/...` signature —
  the dev server refused the connection outright, not an app assertion failure.
- A few others (`GridSelectorModalMobile`, one `visual/DynamicLogo` case) show
  "Target page, context or browser has been closed" — a worker/browser died
  mid-test.
- Both signatures are consistent with resource contention: this was the *third*
  heavy suite run in a row on this box (broken Playwright run, then this corrected
  one, plus Jest, plus the live pilot job's own CPU/IO use throughout). I did NOT
  independently re-run these in isolation to confirm-or-clear them — that would have
  meant a fourth full suite pass, which felt like the wrong tradeoff for an audit
  task already well over its natural scope. **Recommend a clean, isolated re-run of
  just the Import*/GridSelectorModalMobile/DynamicLogo-visual specs** (not the whole
  suite) before treating any of these 31 as real regressions.
- The remaining handful (`DeckbuilderConfirmAffordance`, `Toasts` "/2/importSites",
  `visual/DynamicLogo` "no backend configured") have distinct, specific assertion
  failures unrelated to connection/contention — these look like they'd survive an
  isolated re-run and deserve individual triage, not written off as environmental.

DEVIATIONS from the brief, each with reasoning:

1. Ran `npm ci` before the first Jest pass, not requested explicitly. `node_modules`
   was 6 days stale relative to `package-lock.json` (2026-07-11 vs 2026-07-17),
   producing a spurious "missing generated file" suite failure on the very first
   run. A stale local install would have poisoned every number in this audit; fixing
   the install (not the code) before measuring felt squarely inside "run every suite
   once from clean."
2. Ran the full Playwright suite TWICE, not once. The first run (unmodified
   environment) showed 236/243 failing — I did not report that number as the
   finding and stop; I root-caused it first (see item 5/SPEED LEVERS above:
   `.env.local`'s stale `NEXT_PUBLIC_BACKEND_URL=http://localhost:80`, left over from
   unrelated prior live-backend-verification work on this box, silently defeats
   MSW's mocks since they're hardcoded to intercept `http://127.0.0.1:8000`),
   confirmed the fix with a small 27-test spot check, then re-ran the full suite
   with the corrected value via a one-off env var (no files edited) to get numbers
   that actually reflect the app's real state. Reporting the raw 236-failure number
   as this audit's headline finding would have been actively misleading.
3. Added a `docs/troubleshooting.md` entry for the `.env.local`/MSW-origin mismatch
   (see LIVE STATE) — CLAUDE.md's own convention says any blocker costing >15
   minutes gets an entry before the task closes, and this one cost real
   investigation time and will cost the next person the same time if undocumented.
   This is the one non-read-only-report action taken this session; flagging it
   explicitly since the task said "delete nothing" but didn't anticipate a
   documentation gap this concrete surfacing mid-audit. Happy to revert if you'd
   rather fold it into your own review pass instead.
4. Did not do a full line-by-line overlap read of every test file (see item 2's own
   caveat) — the combined suite is ~600+ individual tests across three languages/
   frameworks; a truly exhaustive redundancy audit is its own multi-day task. This
   pass is evidence-based but not exhaustive.

VERIFICATION:
- Jest: ran twice (stale install, then clean); final numbers are from the clean run.
- Playwright: ran twice (broken env, then corrected); final numbers are from the
  corrected run, with the raw broken-env run kept as evidence for the root-cause
  writeup, not discarded.
- Backend pytest: ran once, real testcontainers-backed Postgres/ES, no issues.
- Docker safety: baseline captured before any run (`docker-django-run-904d58989de3`,
  PID 3201080, `local_lands_identify --write --run-id 20260719T004057-e531b323`) and
  re-confirmed identical (same PID, same StartedAt, still running) after all suite
  runs completed. Production containers (`mpcautofill_django`/`worker`/`postgres`/
  `elasticsearch`/`nginx`) untouched throughout — never stopped, restarted, or
  execed into destructively.
- `docs_lint.py` confirmed runnable locally (clean, ~2s) as part of Matrix item 1's
  verification.

OPEN ITEMS / DECISIONS NEEDED:
1. Approve or reject the troubleshooting.md addition (DEVIATIONS #3) — committed on
   this same relay branch alongside this report (docs-only, low-risk, directly
   evidenced by this session's own root-cause work), so it lands together if this
   branch merges, or can be dropped independently if you'd rather fold it into your
   own review pass instead.
2. The Set-polyfill Jest failure (22 tests, `comparison.test.ts`) needs an owner
   decision: bump Node version, add a polyfill, or rewrite `comparison.ts` — I have
   no recommendation between these three, just the diagnosis.
3. Want an isolated re-run of the ~20-31 contention-suspected Playwright failures
   (Import*/GridSelectorModalMobile/DynamicLogo-visual) before they're trusted either
   as real bugs or written off? I did not do this pass (see DEVIATIONS #2/item 5).
4. Backend/frontend known-bucket docs (`infrastructure.md`'s "4" vs the 2026-07-18
   report's "14") should probably each note which environment they describe, so
   future audits don't have to re-derive this the way I just did.
5. Matrix row for backend-only: pick (a) document manual test-file-path convention,
   or (b) add `pytest-picked` — see item 3.
6. The matrix draft is otherwise ready to land in CLAUDE.md as proposed, with the
   corrections above folded in.

LIVE STATE:
- `docs/troubleshooting.md` gained one entry ("Nearly the entire Playwright suite
  fails at once, every test stuck on 'Loading...' or timing out") — committed on
  this relay branch alongside this report (see OPEN ITEM #1).
- `frontend/node_modules` was refreshed via `npm ci` (DEVIATIONS #1) — this is a
  real, intentional change to installed packages on disk, not reverted, since it
  brought the install back in sync with the committed `package-lock.json` (a fix,
  not a deviation from committed state).
- No git commits to application code. No test files edited. No retirements
  performed. Docker: unchanged, verified (see VERIFICATION).
- This report file + branch is the only new commit.
```
