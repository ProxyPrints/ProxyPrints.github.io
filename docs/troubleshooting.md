# Troubleshooting

Symptom-first index. Grep this file for your error text or observed
behavior before re-deriving a fix from scratch. Each entry: symptom →
cause → fix → refs.

**Why symptom-first, not cause-first**: several of these entries were
already documented (in `docs/lessons.md` or a feature doc) by cause the
first time they happened, and still recurred — sometimes 2-3 more times —
because a worker hitting the symptom didn't know which cause-shaped
heading to look under. Indexing by what you actually see when you hit the
problem is the fix for that; grep the exact error text, not a guess at
its root cause.

## CI mypy fails on a package that "isn't even used" / a stub-type error that never reproduces locally

**Symptom**: the "Formatting and static type checking" GitHub Actions
workflow fails on a package that seems unrelated to your change, or a
type error you've never seen locally — and a fresh local `pre-commit run mypy` (or full local test run) stays green.

**Cause**: mypy's pre-commit hook has its own isolated dependency
resolution (`.pre-commit-config.yaml`'s `additional_dependencies`) and
`mypy_django_plugin` genuinely _imports_ (not just statically analyzes)
everything reachable from `cardpicker/models.py` to introspect Django
models. Any transitive import reachable from that chain but not listed in
the hook's `additional_dependencies` is a hard `ModuleNotFoundError` in
CI's isolated hook env — while your local venv (installed from the full
`requirements.txt` for pytest) silently has it, masking the crash
completely. Trust CI history over a matching local run for anything
touching the models.py import chain.

**Fix**: add the missing transitive dependency to `.pre-commit-config.yaml`'s mypy `additional_dependencies` (and usually pin it in
`requirements.txt` too). Verify via `gh run list`/`gh run view --log` —
not just a local re-run — that CI is actually clean afterward.

**Recurred 3 times**: Pillow via `cardpicker/models.py` (fixed by
`9837a4cd`, follow-on real type errors fixed by `40e04d54`; documented
[[lessons.md]]), numpy via `imagehash` (`24e7d293`), the hash-at-ingest
import chain (`update_database → local_phash → imagehash/pytesseract`,
`journal/2026-07-16-hash-at-ingest.md`).

## 5-6 unrelated test snapshots break after adding one new test file (RETIRED 2026-07-23)

**This whole class of bug is now structurally impossible** — see "Root
fix" below. Kept as history because the root cause (`factory.Sequence`
counters being process-global) is a generically useful fact about
`factory_boy`, and because the old symptom text is still what you'd grep
for if you hit something snapshot-related in this suite.

**Old symptom**: a brand-new test file (using an existing shared factory)
was added, and several _other_, seemingly-unrelated tests started
failing — often `test_views.py::TestGetTags::*` or similar snapshot-style
assertions with a hardcoded value like `"Artist 0"`.

**Cause**: `factory.Sequence` counters in `cardpicker/tests/factories.py`
are process-global for the whole pytest run. `test_views.py` is the only
module in the suite whose assertions embed a sequence-derived value (via
`__snapshots__/test_views.ambr`, reached through
`brainstorm_canonical_card`'s default `CanonicalCardFactory`/
`CanonicalArtistFactory` SubFactory chain) — so that value implicitly
depended on total call count up to that point in collection order, and
_any_ other file using the same shared factories could shift it.

**Old fix (retired)**: an autouse fixture local to every _new_ test file
that captured each shared factory's `next_sequence()` before the test
body ran and called `reset_sequence(n, force=True)` both immediately and
again in teardown, keeping that file's own usage invisible to the rest of
the suite. This recurred 3 times after being documented ([[lessons.md]])
because each new file had to independently rediscover which factories
count as "shared" (deductive-backfill work, then again in
`test_purge_machine_votes.py`), and needed a special-cased, `request.node.name`-gated variant (`test_views.py`'s old
`_preserve_shared_factory_sequences_for_insulated_tests`) for the case of
a single new _test_ inside an existing file, since a same-scope
`populated_database`-consuming test shifted every later test in the same
file.

**Root fix**: the burden was on the wrong side. Instead of every module
that merely _uses_ the shared factories protecting the one module that
_asserts_ on their exact values, `test_views.py` now pins those factories
to a fixed baseline (`Factory.reset_sequence(0, force=True)`) before every
one of its own tests (`_pin_shared_factory_sequences`, module-level
autouse). Its snapshots are now self-determined regardless of suite
composition, collection order, or how many tests ran before it — no other
file in `cardpicker/tests/` needs to know `test_views.py` exists, and the
old capture/restore fixture + `_SHARED_FACTORIES` list was deleted from
all 31 other files that carried it. This also retired the `--snapshot-update` single-file-vs-full-suite divergence variant that used to
apply here (updating `test_views.ambr` in isolation used to bake in wrong
values because a full-suite run consumed sequence numbers a single-file
run didn't) — since the pin always resets to the same baseline regardless
of what ran before, `pytest cardpicker/tests/test_views.py --snapshot-update` and a full-suite `--snapshot-update` now produce
identical output, both scopes work.

## Seeding rows via a data migration breaks tests that assert a table is empty/complete

**Symptom**: a new data migration seeds rows into a table, and several
unrelated tests that assert the table's _complete_ contents in a fresh
DB start failing.

**Cause**: a migration runs unconditionally at DB-setup time, including
the test database — any migration-seeded row becomes permanent baseline
state for every test in the suite, not just ones that care about it.

**Fix**: seed via a manual, idempotent management command
(`get_or_create` + a thin wrapper), never `migrations.RunPython`,
regardless of how literally a task spec says "data migration." Follow the
existing `seed_default_tags`/`seed_no_match_reason_tags`/
`seed_attribute_tags` pattern.

**Recurred**: hit and documented once for `Tag` seeding
([[lessons.md]]), and independently again the same day
(`journal/2026-07-14-tag-taxonomy-followup.md`) before the lesson had
even been written down.

## nginx 502s everything after a django container restart

**Symptom**: every API request 502s after `docker compose up -d django worker` (or anything that recreates the `django` container) —
`connect() failed (111: Connection refused) ... upstream: "http://<stale-ip>:8000/..."` in nginx's logs.

**Cause**: nginx's `upstream django-api { server django:8000; }` resolves
the `django` service name to a Docker-internal IP once at nginx's own
startup/reload, not per-request. Recreating the django container assigns
it a new internal IP; nginx keeps proxying to the old one.

**Fix**: `sudo docker compose -f docker-compose.prod.yml restart nginx`
after any command that recreates the `django` container. See
[[infrastructure.md]]'s Docker/backend deploy section.

## TesseractNotFoundError / OCR tests fail without the real tesseract binary

**Symptom**: `TesseractNotFoundError` inside the `mpcautofill_django`
container, or OCR-dependent tests fail in CI specifically (not locally).

**Cause**: tesseract-ocr wasn't originally in the Docker image's build
stage, and CI test runners also lack the real binary. Important
distinction: the `mpcautofill_django` Docker image DOES have the real
binary baked in now, but the "Backend tests" GitHub Actions job
(`.github/actions/test-backend/action.yml`) never uses that image — it's
a bare `ubuntu-latest` runner with `pip install -r requirements.txt` and
nothing else, so it never has tesseract and never will unless that
action is changed. A local check against the Docker image (which has the
binary) will not catch a missing mock; only CI, or a local repro with
`pytesseract.pytesseract.tesseract_cmd` pointed at a bogus path, will.

**Fix**: tests mock tesseract directly rather than requiring the real
binary in CI (`ddb6dce9`, "Fix CI: mock tesseract in tests") — any test
whose code path reaches `local_ocr.run_tesseract` (directly, or
transitively via `local_fallback.detect_illus_anchor`'s unconditional
call whenever `fetch_card_image` returns a non-`None` image) must
`monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "<expected text>")`. This has already recurred once past the original
fix: 10 tests added in `test_local_identify_printing_tags.py` across
2026-07-15 to -17 (`e6b09d14`, `3b2b5b7d`, `c7010bd8`) called `run_pilot`
with a real fetched image and skipped the mock, passing locally (host
venv/Docker image both have the binary) but failing CI outright — fixed
2026-07-19. See [[features/printing-tags.md]]'s build history (`git log e4eb6cb3 -- docs/features/printing-tags.md`) for the full timeline if you
need it.

## prettier rewrites already-correct markdown into broken text

**Symptom**: running the prettier pre-commit hook on a markdown file
changes text that was already correct — e.g. `*italic*` becomes a broken
`\_italic*`, or `node_modules` gets mangled — especially on a _second_
pass over a file prettier already formatted once.

**Cause**: a real non-idempotency bug in prettier@2.7.1 on specific text
patterns (backtick-adjacent underscores/asterisks in particular).

**Fix**: reword the two known trip points (backtick-wrap the term, or use
`**bold**` instead of `_italic_`/`*italic*`) rather than fight the
formatter. Verify by re-running the hook and confirming zero further
diff. See [[lessons.md]] for the specific patterns found so far.

## A Playwright test hangs on a stuck loading spinner / blank `src=""` image, and the same test passes in an isolated worktree

**Symptom**: a Playwright test times out with `<div class="spinner-border"> ... subtree intercepts pointer events` blocking a click on a card image,
and `page.getByAltText(...)` resolves to an `<img src="">` that never
finishes loading — reproducible several times in a row against the
session's long-running `next dev` server on port 3000, for a test file
that has nothing to do with your actual diff.

**Cause**: a `next dev` process that has been alive for a long time (many
hours, dozens of Playwright runs, repeated file edits triggering fast
refresh) accumulates state that isn't reproducible in a freshly-started
server — confirmed by swapping `frontend/src` between a branch and
`master` **on the same live server** (both failed identically) versus
running the identical test in a brand-new `git worktree` with its own
freshly-started `next dev` on a different port (passed 30/30, twice each,
both `master` and the branch). The failure tracks the **server process's
age/history**, not the source code. Likely candidates: stale webpack HMR
module chunks, or accumulated fetch/image-cache pollution from earlier
test runs' mocked network state leaking across the dev server's lifetime
— not confirmed further since the worktree test was decisive enough to
stop investigating.

**Fix**: before concluding a test failure is a real regression, reproduce
it in a **fresh, isolated `git worktree`** with its own newly-started dev
server on a different port (the same technique used for before/after
screenshots — see [[lessons.md]]'s worktree-dev-server-collision entry),
not just by editing files in place on the session's existing long-running
server. If the isolated run passes, restart the main session's dev server
(`kill` the old `next dev`/`next-server` PIDs, start fresh) rather than
trusting further results from the stale one. Don't spend time root-causing
the exact HMR/cache mechanism unless it recurs after this fix.

**Addendum (2026-07-22, /whatsthat animation-sync fix)**: this exact
symptom — `revealed` (backing `question-feed`'s loading spinner) stuck
`false` forever, `<img src="">` never settling — recurred on a
genuinely fresh, isolated dev server (a brand-new worktree, freshly
killed and restarted, confirmed via `ps`/`readlink -f /proc/<pid>/cwd`
that no other session's server was reused), so it was **not** always the
stale-server artifact described above. The real cause that time: a
`useEffect` keyed on `item?.card.identifier` doing settle/gate logic
whose _reset_ lived unconditionally in the fetch handler
(`setRevealed(false)` etc. on every resolution, not just ones landing on
a genuinely new identifier). Two consecutive feed items can legitimately
share an
identifier (the existing fetch-handler comment already documents this
for `chipStates`), and dev-mode React Strict Mode's double effect
invocation makes a duplicate resolution routine even outside that case
— when it happens, the reset fires again but the identifier-keyed catch-
up effect has no dependency change to re-trigger it on, permanently
stranding the reset state. **Fix**: don't key a catch-up/settle effect on
a value that can legitimately repeat between consecutive items — key it
on a counter bumped unconditionally in the same reset block instead
(`imageGeneration` in `QuestionFeed.tsx`), so the effect re-runs every
time the reset does, with no dependency on whether the identifier text
itself changed. **Distinguishing the two causes**: the stale-server
version reproduces identically regardless of source code (swapping
branches on the _same_ long-running server fails the same way); this
version reproduces intermittently even on a fresh server and stops
reproducing (verified via a 15-iteration `--workers=1` loop with zero
source edits mid-run) once the generation-counter fix lands — a single
clean pass proves nothing for an intermittent race like this, only a
multi-iteration loop does.

## `npx prettier --write` reformats far more of a frontend file than you touched (trailing commas, wrapped ternaries appearing everywhere)

**Symptom**: running `npx prettier --write` on a file you made one small,
targeted edit to produces a diff spanning dozens of unrelated pre-existing
lines — trailing commas added to multi-line function calls, ternary
expressions gaining parentheses, multi-value CSS properties reformatted
onto separate lines — none of which you changed.

**Cause**: `frontend/`'s actual formatting contract is prettier **2.7.1**,
pinned via `.pre-commit-config.yaml`'s `pre-commit/mirrors-prettier` hook
(`rev: "v2.7.1"`) — not via `frontend/package.json`, which doesn't list
`prettier` as a direct dependency at all. `frontend/node_modules/.bin/prettier`
resolves to whatever transitive version `package-lock.json` happens to pin
(confirmed 3.7.4 on `master` as of 2026-07-17) — a different major version
with different defaults (`trailingComma: "all"` vs `"es5"`, plus 3.x's
wrapped-ternary and multi-value-transition formatting changes). Since none
of `frontend/`'s actual source files are formatted to 3.x's rules, running
the wrong binary against any file reformats every pre-existing line it
touches, not just your edit.

**Fix**: always run `npx --yes prettier@2.7.1 --write <files>` explicitly
in a sandbox without pre-commit installed — never bare `npx prettier` or
`node_modules/.bin/prettier`. Verify with `npx prettier@2.7.1 --version`
prints `2.7.1` before trusting a diff as edit-scoped. If a diff already
shows this kind of unrelated mass reformatting, it's a signal to check the
prettier version immediately, not to assume the file was simply
out-of-date.

## Worker-thread DB queries silently miss data / "too many clients already"

**Symptom**: either (a) a test using a `ThreadPoolExecutor` for a DB query
passes locally but the worker thread sees no rows under pytest-django's
default `db` fixture, or (b) in production, `psycopg2.OperationalError: FATAL: sorry, too many clients already` crashes a long-running command.

**Cause**: Django DB connections are thread-local. (a) A worker thread
can't see an uncommitted test transaction under the default `db` fixture.
(b) A `ThreadPoolExecutor` constructed _inside_ a per-chunk loop (instead
of once for the whole run) leaks one Postgres connection per chunk, since
nothing closes a thread-local connection when its thread is torn down —
this exhausts `max_connections` over a long run.

**Fix**: (a) use the `transactional_db` fixture instead of `db` for any
test that touches the DB from a worker thread — same fix as an existing
`test_sources.py` precedent (`journal/2026-07-15-local-printing-id-pilot.md`). (b) hoist `ThreadPoolExecutor` construction to
wrap the entire loop, not per-chunk — see [[features/printing-tags.md]]'s
build history for the incident this was found in.

## Entrypoint + migrate composition traps (boot-time rescan, deploy/migrate fusion)

Two distinct symptoms, same root subsystem: `docker/django/entrypoint.sh`
always runs `migrate` before anything else on `django`/`worker` start.

**Symptom 1 — API unreachable for 10+ minutes after a deploy**: a purely
schema-only migration (e.g. one nullable column) triggers a full catalog
rescan across every source before gunicorn binds; if a per-source
`IntegrityError` crashes the container mid-rescan, it stays down (no
restart policy) with `docker compose logs` looking identical to a
slow-but-alive container on casual inspection.

**Cause 1**: entrypoint used to gate
`import_sources`/`update_database`/`update_dfcs` behind `migrate --check`
("did any migration apply") — the wrong proxy for "does catalog content
need rescanning."

**Fix 1**: entrypoint now only runs `migrate` + `import_sources` before
binding; content sync is scheduled (daily/weekly django-q jobs) plus a
fresh-bootstrap-only guard (`eaece1fd`, #18). Hardened a week later with
`restart: unless-stopped` on every service (`8b1ec5e5`) plus a systemd
unit + verified reboot test (`ac6bb7e3`). See
[[infrastructure.md]]'s "Startup vs. scheduled catalog sync" and
"Boot-time recovery" sections for current behavior.

**Symptom 2 — a live long-running job crashes mid-query with `column ... does not exist` right after an unrelated deploy**: recreating the
persistent `django`/`worker` containers to ship new code applied a
column-rename migration (`Card.image_hash` → `content_phash`, PR #27) as
an unintended side effect, while a separate one-off container
(`docker compose run --rm worker ...`, a live full-catalog pilot job) was
still running the _old_ image against the same database. The rename
executed mid-query under the live job, which crashed on its next read.

**Cause 2**: entrypoint's fix for Symptom 1 (above) made `migrate` run
_unconditionally_ on every `django`/`worker` start, by design (PR #18 —
so a container that failed to migrate self-heals on its next boot). That
means `docker compose up -d django worker` is a fused deploy+migrate
step with no way to do one without the other — a "build → deploy →
migrate" plan that assumes three separable steps may already be two.

**Fix 2**: never recreate the persistent `django`/`worker` containers
while any other container on an older image is actively running against
the same database, unless every pending migration is strictly additive
(nullable column, new table — anything old-code ORM simply ignores). For
a non-additive migration (rename, type change, NOT NULL backfill): stop
the long-running job first and restart it after the deploy, or apply the
migration manually from an old-code container before recreating anything.
Check `entrypoint.sh` (or equivalent) before assuming deploy and migrate
are actually separable. (`8c957aa5`, 2026-07-16.) Even when Fix 2's
own condition holds (strictly additive), starting `django` and `worker`
together (`docker compose up -d django worker`) still races their two
entrypoint migrate steps against each other — observed once, 2026-07-17,
as one container crashing on `column ... already exists` before
self-healing via `restart: unless-stopped`; harmless for an additive
migration, but worth knowing the crash-then-recover blip is expected,
not a new problem.

**Related gotcha, same incident**: `GIT_SHA=$(git rev-parse --short HEAD) sudo docker compose build ...` bakes `unknown` instead of the real SHA —
`sudo` doesn't preserve environment variables set before it on the same
command line. Use `sudo env GIT_SHA=$SHA docker compose build ...` or
`sudo -E` instead. Cosmetic only (git-SHA baking is best-effort
visibility, never the staleness guard itself), but silently wrong if
unfixed.

## Frontend ships an API shape change before the backend redeploys ("undefined cards"-class bugs)

**Symptom**: a page renders a literal `undefined` where a number/value
should be (e.g. "undefined cards"), immediately after merging a PR that
changes an API response shape — with no code regression in the PR's own
tests, which all pass.

**Cause**: the frontend (GitHub Pages) and backend (persistent
`django`/`worker` containers) deploy on separate pipelines. Pages
auto-ships on merge/push to `master`; the backend only picks up a merged
change once someone explicitly redeploys the persistent containers
(`docker compose up -d django worker`). A frontend-only merge that
changes an API response's shape is live on Pages within minutes, but the
backend can lag by hours or longer if nothing triggers a redeploy —
"stale but schema-compatible" is false the moment a shape change merges;
that assumption only holds for the deploy-skew window _before_ the shape
actually changed, not after.

**Fix**: (a) merging an API-shape-changing PR isn't "done" — it isn't
complete until the persistent containers are explicitly redeployed to
match; track that as a first-class follow-up, not an implicit side effect
of the merge. (b) independent of (a), any frontend consumer of a
versioned/typed API response should defensively handle the previous shape
at runtime — TypeScript's compile-time cast can't catch a live shape
mismatch against whatever the backend is actually serving right now.

**Incident**: 2026-07-16/17, questionFeed's `remainingEstimate` field
changed from a plain `number` to a `QuestionFeedCounts` object (#29).
Pages shipped the new frontend immediately; the persistent backend
containers were still serving the old plain-number shape. `QuestionFeed.tsx`'s headline read `counts.total` on what was actually a
raw number at runtime, rendering the literal string "undefined cards" in
production. Fixed on the frontend side with a runtime shape guard
(`normalizeQuestionFeedCounts()`, #34) that degrades gracefully to the
old copy when it detects the legacy shape — worth keeping permanently,
since every future backend deploy has the same skew window, not just this
one incident.

## A quicktype-generated frontend type is "missing" a field

**Symptom**: a `PrintingCandidate`/`Tag`/etc. TypeScript type (generated
by quicktype) doesn't have a field that "should obviously already be in
the payload," or a schema field you hand-added to the `.ts` file directly
disappears on the next build.

**Cause**: `schema_types.py`/`schema_types.ts` both say "Generated by
quicktype. Do not manually modify this file." — the source of truth is
the JSON Schema under `schemas/schemas/`.

**Fix**: edit the JSON Schema source file, then `cd schemas && npm run build`. Run black/isort/prettier on the output afterward — raw quicktype
output isn't formatted, so an unformatted diff is mostly noise, not the
real change.

**Recurred 3+ times**: see [[features/printing-tags.md]]'s build history
and `journal/2026-07-14-tag-taxonomy-followup.md`.

## Bulk fetch through image-cdn runs faster than the configured rate limit, zero 429s

**Symptom**: a bulk fetch job against the image CDN (e.g. the
`content_phash` backfill) sustains a throughput well above the
configured ceiling (observed ~10.5/s against a configured 3/s), with
zero `429`/rate-limit-rejection lines anywhere in the job's own log,
for an extended period (50+ minutes observed) — not a brief burst.

**Cause**: the Worker's `IMAGE_FULL_TIER_RATE_LIMITER` binding
(`image-cdn/wrangler.toml`, `namespace_id = "1002"`,
`simple = { limit = 30, period = 10 }` = 3 req/sec — config confirmed
directly from the repo file, the Cloudflare dashboard exposes the
binding's existence/namespace but not its configured limit/period) is
not enforcing its configured ceiling at this volume. Two specific
application-level bug hypotheses were checked and both **ruled out**
by direct code read, not left as open guesses:

1. Routing bypass — confirmed as a real, separate cause (see above):
   `get_worker_image_url` always builds the `/images/google_drive/full/...`
   URL regardless of `dpi`, and the Worker's `"full"` case has no cache
   short-circuit, so every request does unconditionally reach
   `fetchWithRateLimit`.
2. Per-key scoping — checked 2026-07-17, **not the cause**: every
   caller of `fetchWithRateLimit` against this specific limiter was
   enumerated (`grep -rn "fetchWithRateLimit\|\.limit(" image-cdn/src/`
   — exactly one call site exists, `image-cdn/src/handler/image.ts:45`)
   and its key argument is the literal string
   `"global-image-full-tier-rate-limit"` — a fixed, shared constant,
   not a per-URL/per-card value. Inside `fetchWithRateLimit` itself
   (`image-cdn/src/utils.ts:17`, `limiter.limit({ key })`), the same
   `key` parameter is reused across every retry attempt in the loop
   too. So every full-tier request, across every retry, genuinely
   shares one counter — a fresh-counter-per-image bug would explain
   the symptom, but the code does not have that bug.

With both application-level hypotheses ruled out and the dashboard
confirming the binding itself exists at the right namespace with (per
the repo config) the right limit/period, the remaining explanation is
Cloudflare's Rate Limiting binding not enforcing atomically/globally at
this request volume — a documented characteristic of the product at
scale, but not confirmable further in this environment: `wrangler`
here requires Node 22+ (box has 20.20.2) and full
`CLOUDFLARE_API_TOKEN`/dashboard request-analytics access is
unavailable.

**Fix (working control, 2026-07-17)**: client-side pacing at the fetch
call itself — `cardpicker/local_phash.py`'s `_RateLimiter` (a strict
minimum-interval pacer, not a token bucket, shared across every worker
thread) plus `DEFAULT_BACKFILL_RATE_LIMIT_PER_SEC`, wired through
`run_content_phash_backfill`'s `rate_limit_per_sec` param and the
`local_backfill_content_phash` command's `--rate-limit-per-sec` flag
(default matches the Worker's own configured-but-non-enforcing 3/sec).
Any other bulk caller of the image CDN's full tier should assume the
same and add its own client-side pacing — don't rely on the Worker
binding alone at bulk volume. No Worker-side code fix is queued for
this specific gap (the key-scoping fix that would normally follow this
kind of diagnosis doesn't apply here — the key was already correct);
if Cloudflare dashboard/API access becomes available later, revisit
whether the binding itself needs a support ticket or config change.

**Refs**: `docs/features/image-cdn.md`, `docs/features/catalog-completion-plan.md`'s Part 2 section.

## A cloud-sandbox Playwright run fails ~24-29 specs that all pass locally with real network

**Symptom**: a batch of otherwise-unrelated Playwright specs
(`AddCardToFavorites`, `ArtistVotePicker`, `PrintingTagPicker`,
`TagVotePicker`, `ReportCard`, `Toasts`, `CardDetailedViewModal.visual`,
intermittently `New.visual`) fails together, every time, in a given
cloud/agentic dev sandbox — never a partial subset, never a different
failure signature — while GitHub Actions CI passes the same specs
cleanly on the same code.

**Cause**: the sandbox environment these specs were authored in has no
real network egress to the image-CDN domains
(`cdn.proxyprints.ca`/`img.proxyprints.ca`) the app fetches card images
from — every card image fails to load regardless of the diff under
test, producing a consistent, diff-independent failure signature. One
representative failure traced directly to a `getByAltText` call timing
out waiting on a real image load (see PR #35's body for the full
investigation). Confirmed as the correct diagnosis, not just a
plausible guess: re-ran this exact bucket (26 specs including all of
the above) on 2026-07-17 from this box, with a real dev server pointed
at real `NEXT_PUBLIC_IMAGE_WORKER_URL`/`NEXT_PUBLIC_IMAGE_BUCKET_URL`
values and genuine outbound network access — all 26 passed. GitHub
Actions CI runners have real egress too, which is why this bucket has
never shown up there.

**Fix**: there is nothing to fix in application code — this is an
environment property, not a bug. Don't chase these failures as
regressions when they show up in a sandbox; don't add sandbox-specific
skips or mocks to work around it either, since that would silently
weaken the tests everywhere. To get a genuine real-image signal from
this kind of environment, either run against a real dev server with
real CDN env vars and real egress (this box, or any environment with
outbound network access), or trust GitHub Actions CI's own run.

**Refs**: PR #35's body (root-cause investigation), PRs #36/#37/#41
(reference back to #35 rather than re-investigating).

## A worktree merge silently loses its merge state / a push produces a single-parent commit with the right content but the wrong git history

**Symptom**: after resolving a real merge conflict in a git worktree
(a directory whose own `.git` is a _file_ pointing at the real gitdir,
not a directory) and pushing the result, GitHub still reports the PR
as `CONFLICTING`/`DIRTY` even though the pushed commit's file content
is verifiably correct (a direct `git diff` against the target branch
shows exactly the expected changes, nothing missing).

**Cause**: writing directly to `.git/MERGE_HEAD` (e.g. via
`git rev-parse origin/master > .git/MERGE_HEAD`, intending to manually
restore merge state so the next `git commit` produces a real 2-parent
merge commit) silently fails in a worktree, because `.git` there is a
file containing a `gitdir: <path>` pointer, not a directory — the
shell redirect (`>`) can't write into it, and by default that failure
doesn't stop the rest of the command chain. The following `git commit`
still succeeds, but as an ordinary single-parent commit (parent = the
branch's own prior tip), not a merge commit. The tree/content is
correct — it came from a real 3-way merge whose resolution was
preserved via a stash — but the commit graph no longer shows the
target branch as an ancestor, so GitHub's mergeability check performs
its own fresh 3-way merge attempt against the current base and
re-encounters the original conflict.

**Fix**: check `git log -1 --format="%P" <commit>` after any commit
you expect to be a real merge — it should list two parent SHAs. If it
lists only one where two were expected, the tree is still salvageable
(assuming a real merge actually happened first, e.g. via `git merge`,
and you have the resulting SHA or a stash of it): rebuild a correct
2-parent commit directly with
`git commit-tree <tree-sha> -p <parent1> -p <parent2> -m "..."`, reusing
the already-verified tree rather than re-doing the merge. Verify with
the same `%P` check before pushing. If the flawed single-parent commit
was already pushed, this requires a force-push to replace it — treat
that with the same care as any other force-push (fresh, explicit
confirmation first), even though the tree content itself is unchanged.

**Refs**: none yet — first occurrence, 2026-07-17, during the
frontend-package PR #41 conflict resolution.

## User reports "Vote failed" / a generic tag-submission error — check nginx access logs for 429s first

**Symptom**: a real user reports a vote/tag submission failing with a
generic frontend toast ("Vote failed" / "Something went wrong
submitting your tag - please try again.") and `docker logs mpcautofill_django` shows nothing around the reported time.

**Cause**: the empty django logs are a red herring, not evidence of a
missing traceback — check `docker logs mpcautofill_nginx` for the
actual HTTP status first. In the one confirmed case so far (2026-07-17,
`Changeling Outcast` border/frame chips), the real cause was a `429`
from `cardpicker.views.post_submit_tag_vote`'s rate limit (a real user
voting quickly enough to trip it), not a `500` — the backend behaved
exactly as designed (a clean, well-shaped JSON error, checked before
any request-body parsing or vote-casting) and there was never an
exception to log anywhere. The generic toast is a separate, real
frontend bug: `frontend/src/store/api.ts`'s `APISubmitTagVote` already
throws `{name, message}` parsed from the backend's response body on
any non-200, but every caller (`AttributeChipPanel.tsx` confirmed;
likely also `QueueTagQuestion.tsx`/`TagVotePicker.tsx`/
`ArtistVotePicker.tsx`/`NoMatchReasonStrip.tsx`/`PrintingTagPicker.tsx`
— same generic-string pattern, not yet individually confirmed) uses a
bare `.catch(() => {...})` that discards the thrown error and shows a
hardcoded generic message regardless of what actually failed.

**Shared rate-limit detail**: `post_submit_tag_vote`,
`post_submit_printing_tag`, and the artist-vote submission view all
share one `@ratelimit(...)` budget (`_printing_tag_rate_limit_key`/
`_printing_tag_rate_limit_rate` in `views.py`, keyed by the
client-generated `anonymousId`) — `PRINTING_TAG_SUBMISSION_RATE`
(`settings.py`, 300/h as of 2026-07-17, was 20/h) covers a session's
whole voting activity across all three endpoints, not a per-endpoint
budget. A user mixing tag/printing/artist votes rapidly can trip it
faster than "N tag votes alone" would suggest.

**Fix**: for the rate-limit class of failure specifically, nothing to
fix server-side once the rate is sane for real usage (raised to 300/h
alongside this entry — see `settings.py`'s own comment for the full
reasoning). The frontend's swallowed-error-message bug — noted here as
still open — was fixed the same day by PR #47: every vote-submission
`.catch(...)` (`AttributeChipPanel.tsx`, `PrintingTagPicker.tsx`,
`QueueTagQuestion.tsx`, `ArtistVotePicker.tsx`, `TagVotePicker.tsx`,
`NoMatchReasonStrip.tsx`) now surfaces the real error via
`errorToNotification`/`isRateLimited` (`common/apiErrors.ts`), so a 429
reads as a friendly rate-limit message instead of a generic failure.

**Refs**: `MPCAutofill/MPCAutofill/settings.py` (rate + LOGGING
comments), `frontend/src/store/api.ts`'s `APISubmitTagVote`.

## A single Jest test fails only in the full `npx jest` run, passes every time alone or with `-t`

**Symptom**: `npx jest` (default parallel workers) fails one specific
test deterministically on every run, always at a `waitFor`/`findBy*`
timeout — but `npx jest path/to/file.test.tsx` (whole file) and
`npx jest -t "the failing test name"` (isolated) both pass reliably,
every time, no code change in between.

**Cause**: this sandbox's CPU is shared across as many parallel Jest
worker processes as `npx jest` defaults to spawning (one per detected
core) — under that contention, a test whose passing path depends on a
real (non-fake-timer) React state update landing inside the default
1000ms `waitFor` window can lose the race purely from scheduling
delay, not from a logic bug. `QuestionFeed.test.tsx`'s
`revealCard()` helper (fires a synthetic `animationEnd` on
`RevealOverlay`, since jsdom never runs the real CSS animation) hit
exactly this: reliably reproduces the timeout under full-suite
parallelism, reliably passes standalone or under `--runInBand`.

**Fix**: don't chase it as a logic bug once `--runInBand` (single
worker, no contention) passes 3/3 — that's the confirming test, and
matches the file's own comment about jsdom never firing animations for
real. Where a helper's caller depends on the state update actually
having landed (not just the event having fired), make the helper wait
for its own effect (e.g. `revealCard()` now also asserts the overlay
is gone via `waitFor`) rather than firing-and-hoping — this doesn't
eliminate resource-contention timeouts entirely, but keeps the
helper's contract honest. For a one-off local verification, prefer
`npx jest --runInBand` over chasing the parallel-worker flake.

**Refs**: `frontend/src/features/questionFeed/QuestionFeed.test.tsx`'s
`revealCard()`.

## A Playwright click-through-navigation test fails locally on the first attempt but is genuinely green in CI

**Symptom**: `npx playwright test` (default `retries: 0` locally,
since `playwright.config.ts` only sets `retries: 2` when `CI` is set)
fails a real-browser click test deterministically — `page.click()`
succeeds (correct single `<a href>`, no nested-anchor interception,
click lands exactly on the target element per
`document.elementFromPoint`) but `expect(page).toHaveURL(...)`
times out, URL never changes. A `[Fast Refresh] rebuilding` console
line lands right around the click. CI's own check-run for the same
commit shows green, and its merged Playwright HTML report doesn't
even surface the test by name for grepping (CI's `reporter: "blob"`
prints no per-test lines to the job log at all — its silence isn't
evidence either way).

**Cause**: Next.js dev mode (`next dev`, used by both local and CI
Playwright runs per `playwright.config.ts`'s `webServer.command`)
compiles each page on first visit, not at server start. A test that
navigates and clicks immediately can land its click while that
first-visit compile/HMR cycle is still settling, interrupting the
pending client-side `next/link` transition. This is a real, first-
attempt flake, not a nested-anchor bug (rule that class out first via
`document.elementFromPoint`/DOM inspection before spending time here)
and not a mock/CI-status-lying situation.

**Fix**: don't chase it as an app bug once `npx playwright test <file> --retries=2` (matching CI's own configured retry count exactly) shows
the failing tests passing on retry, marked `flaky` rather than
`failed` — that's the confirming test. CI's `retries: 2` is an
existing, deliberate project policy (not something to second-guess
per-PR); a test passing via that policy is a legitimate CI green, not
a masked failure. Don't try to verify a specific test's CI outcome by
grepping job logs when the workflow uses `reporter: "blob"` — it
prints nothing per-test regardless of pass/fail; download the merged
`playwright-report` artifact (`gh run download <run-id> -n playwright-report`) if a real per-test read is needed, though its
`index.html` is a JS-rendered SPA, not plain-text-greppable either.

**Refs**: `frontend/tests/HomepagePanel.spec.ts`,
`frontend/playwright.config.ts`'s `retries`/`webServer`.

## `test_valid_url[tappedout*]`/`[manastack]` fails with `InvalidURLException`, unrelated to your change

**Symptom**: `cardpicker/tests/test_integrations.py::TestMTGIntegration::test_valid_url[tappedout]`,
`[tappedout_with_www]`, or (as of 2026-07-22, PR #321) `[manastack]`
fails with an `InvalidURLException` in CI on a PR that never touched the
import-sites code (tappedout: #209, #213, #215; manastack: PR #321 -
confirmed via direct `curl` that `manastack.com/api/deck/list` returns a
genuine live 500, identical across two separate CI runs, not a one-off
network blip).

**Cause**: that parametrize case makes a real HTTP request to the live
site named in its `Decks` enum value — a genuine external-network
dependency the test never declared. Whenever that site 503s, 500s,
redirects, or is otherwise unreachable, `ImportSite.request`'s
`default_is_response_valid` check fails and raises, and the test goes
red for a reason with nothing to do with the PR's diff. Every site in
this parametrize (archidekt, cubecobra, magic-ville, manastack, scryfall,
tappedout) is equally exposed to this in principle - tappedout and
manastack are just the two that have actually been observed breaking so
far, not the only two capable of it.

**Fix**: `test_valid_url` wraps the call in
`requests_mock.Mocker(real_http=True)` and registers a mock response for
each site once it's been observed flaking - `tappedout.net`/
`www.tappedout.net` (matched via `TappedOut.get_host_names()`) and, as of
this fix, `manastack.com` (matched via `ManaStack.get_host_names()`,
mocked with a JSON body shaped to match `ManaStack.retrieve_card_list`'s
own `response_json["list"]["cards"]` parsing so that code path still gets
real coverage, not just a bypass) - while every other, not-yet-observed-
flaking site in the same parametrize stays on the `real_http=True`
fallback untouched. Chosen over a named `skipif` (the `MOXFIELD_SECRET`-
gated pattern just above it in the same file) because there's no config
flag to gate any of these on - only live reachability - and mocking keeps
real parsing coverage instead of dropping it. If a THIRD site in this
parametrize starts flaking in CI, the fix is the same pattern again: add
one more `mock.get(...)` matching that site's `get_host_names()`, not a
skip.

**Refs**: `MPCAutofill/cardpicker/tests/test_integrations.py`'s
`test_valid_url`, `MPCAutofill/cardpicker/integrations/game/mtg.py`'s
`TappedOut`/`ManaStack`, `MPCAutofill/cardpicker/integrations/game/base.py`'s
`ImportSite.request`.

## `test_rate_limited_after_exceeding_the_configured_rate` fails intermittently in CI, passes on rerun, unrelated to your change

**Symptom**: `TestPostSubmitTagVote::test_rate_limited_after_exceeding_the_configured_rate`
(`cardpicker/tests/test_tag_votes.py`) fails in CI (`assert 200 == 429` -
the test's SECOND request wasn't rate-limited as expected) on a PR that
never touched rate-limiting, tag votes, or `views.py` (first observed PR
#380, 2026-07-23). Re-running the SAME CI job with zero code changes
passed clean (4m12s) - confirmed non-deterministic, not a real
regression, before landing.

**Cause**: `post_submit_printing_tag`'s own docstring already names the
mechanism: `django-ratelimit` here "relies on Django's default
(in-process) cache" - a single process-lifetime `LocMemCache`, not
something pytest-django's per-test DB-transaction rollback resets. The
sibling endpoint this specific test exercises (`post_submit_tag_vote`)
shares the same in-process cache backend. Whichever OTHER test in the
same worker process happens to run immediately before this one, and how
many rate-limited requests it fires against an overlapping cache key/
window, can leave the sliding-window counter in a different state than a
fresh run would see, so the outcome depends on execution order/
parallel-worker assignment, not just this test's own two requests. This
is a pre-existing structural gap (no per-test cache clear), not
something a single PR's diff can trigger or fix incidentally.

**Fix applied so far**: none - out of scope for a diff that doesn't
touch rate-limiting; confirmed-flaky via a clean rerun and documented
here instead of silently waved through, per this project's own
"a red Backend-tests check now means something real - investigate it"
rule (CLAUDE.md). If this starts recurring often enough to cost real
review time, the real fix is a per-test cache clear (e.g. an autouse
fixture calling `django.core.cache.cache.clear()`), the same category of
fix `test_valid_url`'s own entry above applies to network flakiness -
not attempted here since one observed occurrence doesn't yet justify
guessing at the right isolation boundary for every rate-limited endpoint
in the same file.

**Refs**: `MPCAutofill/cardpicker/tests/test_tag_votes.py`'s
`TestPostSubmitTagVote`, and `MPCAutofill/cardpicker/views.py`'s
`post_submit_printing_tag`/`post_submit_tag_vote` `@ratelimit` decorator
and `_printing_tag_rate_limit_rate`'s own in-process-cache comment.

## Every PR's prettier pre-commit check fails on a docs file the PR never touched

**Symptom**: the "Formatting and static type checking" CI job fails the
`prettier` hook on `docs/upstreaming/upstream-wiki-drift.md` or
`docs/upstreaming/drift-log.md` — files your branch's diff doesn't
include (issue #214, surfaced by PR #213).

**Cause**: PR CI checks out the merge commit (branch + `master`), so any
non-prettier-conformant content the weekly bot workflows
(`docs-upstream-wiki-drift.yml`, `upstream-drift-monitor.yml`) committed
straight to `master` rides along into every open PR's CI run and fails a
file the PR never changed.

**Fix**: both auto-generated files are excluded from the `prettier`
pre-commit hook via an `exclude:` pattern in `.pre-commit-config.yaml` —
machine-generated weekly reports aren't hand-edited, so a hook gate on
them protects nothing and only produces false reds. `drift-log.md` was
also reformatted once so `master` itself started clean; the exclude is
what keeps it that way regardless of what the bots commit next.

**Refs**: `.pre-commit-config.yaml`'s `prettier` hook,
`.github/workflows/docs-upstream-wiki-drift.yml`,
`.github/workflows/upstream-drift-monitor.yml`.

## Docs record a migration as "live on production" but `showmigrations` disagrees

**Symptom**: `docs/infrastructure.md` and `docs/features/catalog-completion-plan.md`
recorded Stage C migrations `0068`–`0072` as applied to the persistent
production Postgres (commit `d1860257`, issue #211); a separate PR's
own notes additionally described migrations `0073`–`0075` as having
auto-applied via a one-off `docker compose run --rm django ...`
container's normal entrypoint `migrate` step. Neither matched the
persistent DB's actual state: running `manage.py showmigrations`
directly against the live containers, both before and after the
2026-07-20 django/worker rebuild, showed only `0068` applied
beforehand — `0069`–`0075` landed only once the containers were
recreated from a fresh `master` image.

**Cause**: "the migrate step should have run" is a plausible-sounding
inference, not a verification step — it was narrated secondhand in a
PR's own notes and then copied into docs as fact, never checked
against the persistent DB directly. A one-off `run --rm` container's
entrypoint genuinely does run `migrate` against whatever Postgres its
compose resolution points at, but that's a claim about mechanism, not
evidence about what actually happened on this specific run against
this specific database.

**Fix**: before recording ANY migration as "live on production" in
docs, run `showmigrations` (e.g. `docker compose -f docker-compose.prod.yml exec django python manage.py showmigrations cardpicker`) directly against the persistent containers and quote its
real output — don't infer live status from "the migrate step should
have applied it" reasoning, however mechanically plausible. Re-check
immediately before and after any deploy/rebuild that's supposed to
apply migrations, so a stale doc claim is caught by direct evidence
rather than propagating silently through a chain of secondhand PR/doc
narration.

## A management-command test file is missing from the deployed prod container even though the command's own code fix is present

**Symptom** (found 2026-07-20, during the Stage C fetch/compute timing
diagnostic — `docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md`):
`cardpicker/tests/test_run_image_evidence_cohort.py` (added by commit
`0226a4de`, the `manager.shutdown()`-ordering fix) does not exist anywhere
under `/MPCAutofill/MPCAutofill/cardpicker/tests/` inside the running
`mpcautofill_django` container, confirmed via `find`. This is NOT simply
"the container predates that commit" — the SAME commit's actual code fix
(reading `stop_event.is_set()` into a local before `manager.shutdown()`) IS
present in the container's own `run_image_evidence_cohort.py`, byte-verified
via `docker cp` + diff against the current `master` checkout. So one file
from a single commit is live in the deployed image and a second file from
the identical commit is absent.

**Ruled out, not confirmed**: `.dockerignore` does not exclude `tests/` (checked
directly — only `frontend/test-results` and `test-results` are listed); the
`Dockerfile`'s `COPY MPCAutofill /MPCAutofill/MPCAutofill` copies the whole
directory unconditionally, with no stage-specific exclusion of `tests/` for
the `webserver`/`worker` targets. Neither explains a single-file gap within
one commit.

**Cause: not determined this session** — plausible candidates (an
out-of-band hotfix of just the command file without a full rebuild; a build
that ran from a checkout mid-commit; some other test-discovery quirk) were
not investigated further, since this diagnostic's own actual verification
need (does the new `--profile` code run correctly against a real prod
cohort) was satisfiable directly via live `--dry-run` invocations instead of
via this specific unit test. Left open rather than guessed at.

**Workaround used this session**: `docker cp` the test file (along with the
two modified source files) into the running container before testing, then
`docker cp` the pre-diagnostic originals back afterward (diff-verified
clean) — see the report above for the full sequence. This is a workaround
for verifying a specific change against a live container, not a fix for the
underlying gap.

**If you hit this again**: before assuming a rebuild will restore parity,
diff the deployed container's file tree against the exact commit `git log`
says built it (`get_baked_git_sha`/`GIT_SHA` file, `cardpicker.utils`) file
list, not just a spot-check of the files you happen to be touching — this
gap was found by accident (checking whether a stub needed updating), not by
a systematic audit, so other quietly-missing files may exist unnoticed.

## A later "share/export this deck" design assumes a saved deck's DEK is stable, but it isn't

**Symptom**: implementing a feature that shares or otherwise re-uses a saved
deck's existing DEK across time (e.g. a share link that's supposed to keep
tracking a deck's _live_ ciphertext) breaks the instant the deck is edited
again — or, when designing such a feature, a spec's prose implies the
deck's DEK only changes on an explicit action ("rotate"), never as a side
effect of ordinary use.

**Cause**: `encryptDeckPayloadForSave` (`frontend/src/features/savedDecks/deckPayload.ts`)
mints a FRESH DEK on every single call to `saveDeck` — including an
ordinary content-editing "Update {name}" save of an already-saved deck, not
just first-save (see `SaveDeckModal.tsx`'s `handleSubmit`, which always
calls `encryptDeckPayloadForSave` regardless of whether `key` is null).
There is no code path that reuses an existing deck's DEK across saves. A
design (this repo's own "PR-5, per-deck share links" spec included) can be
written assuming the DEK is a stable, rarely-changing secret that only a
deliberate "rotate" action touches — that assumption doesn't hold in this
codebase and was never going to, once PR-4 shipped fresh-DEK-per-save.

**Fix**: don't build anything that expects a saved deck's DEK, or its
wrapped form, to survive an ordinary edit-save unchanged. Instead, snapshot
whatever needs to be independent of future edits (ciphertext, wrapped-DEK
material, etc.) at the moment it's captured — exactly what
`SavedDeckKind.SNAPSHOT` already does for the load-safety flow, and what
`SavedDeckShare` (PR-5) does for share links: a frozen copy taken at
creation time, not a live reference. See
[`features/saved-decks.md`](features/saved-decks.md)'s "Per-deck share
links" section for the full writeup of this exact case.

## `psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "pg_type_typname_nsp_index"` in django/worker startup logs during a rebuild

**Symptom**: a raw `IntegrityError` traceback (Postgres `UniqueViolation`
on `pg_type_typname_nsp_index`, a catalog-level constraint on
composite/enum type names, not anything defined in this repo's own
models) appears in the `django` or `worker` container's startup log
during `migrate`, immediately after a prod rebuild — looking identical,
at a glance, to the "entrypoint migrate crash" failure mode documented
above.

**Cause**: `docker/django/entrypoint.sh` runs `migrate` on **both**
`django` and `worker` container startup (see "Entrypoint + migrate
composition traps" above), and a prod rebuild starts both containers
close together. When a migration creates a Postgres composite/enum type
(anything that registers a row in `pg_type`), two concurrent `migrate`
invocations can both pass Django's own "has this migration already
applied" check before either commits, then both attempt the same
type-creating DDL — one wins, the other raises this `UniqueViolation`.
This is a benign startup race between the two containers' own `migrate`
steps, not data loss or a corrupt migration.

**How to confirm it's this and not real damage**: check that the
migration named in the traceback shows as applied
(`python manage.py showmigrations <app>`) and that the table/type it
creates has the expected schema (`\d <table>` in `psql`, or
`Model.objects.first()` field-by-field) — if both check out, the losing
container's `migrate` simply no-opped after the race and the winning
one's write stands; no rerun or manual intervention needed. Confirmed
exactly this outcome for `0076_saveddeckshare` on 2026-07-20 (8 columns,
schema correct, migration applied) immediately after seeing this
traceback in a fresh rebuild's logs.

**Fix**: none applied — this is an accepted, self-healing race inherent
to running `migrate` from two containers on the same startup, not a bug
in the migration itself. If it starts blocking a container from reaching
a healthy state (rather than just logging once and continuing), that
would indicate a real regression and is worth revisiting; gating one of
the two containers' `migrate` calls behind a lock, or having only one
container run it, is a fix not yet implemented.

## Adding one more always-visible `Navbar.tsx` link fails unrelated Playwright specs with "`<a>` from `<nav>` subtree intercepts pointer events"

**Symptom**: `SavedDecks.spec.ts`'s Export/Import tests (and potentially
other specs whose target element sits just below the fixed navbar) start
failing in CI/Playwright with a `page.waitForEvent("download")` or
`locator.click` timeout, and the retry log shows an unrelated navbar
link (e.g. `<a href="/editor" class="nav-link">`) "intercepts pointer
events" over the real target. The PR's own diff looks unrelated — it
only added one new item to `Navbar.tsx`'s left-hand `Nav`.

**Cause**: `frontend/src/features/ui/Layout.tsx`'s `ContentContainer` and
several other components (`Explore.tsx`, `ProjectEditor.tsx`,
`FinishedMyProject.tsx`) hardcode a fixed pixel offset from
`NavbarHeight` (`frontend/src/common/constants.ts`, `= 50`) assuming the
navbar is always exactly one row tall. In the fully-authenticated,
every-backend-feature-enabled state, the left-hand `Nav`'s flex row is
already near its horizontal wrapping budget — Bootstrap shrinks the flex
items instead of moving them to a new line, so a long label ("What's
That Card?") wraps internally and the _whole_ fixed navbar renders
taller than `NavbarHeight` (confirmed via `page.locator("nav.navbar").boundingBox()`:
64px tall on `origin/master` already, vs. the hardcoded 50px offset —
a pre-existing, marginal, still-clickable overlap). Adding one more
always-visible link to that same row pushes the real height further
(88px), and now the _entire_ target button sits under the taller bar
rather than just its top few pixels, making it fully unclickable instead
of merely graze-overlapped.

**How to confirm it's this and not a real click-target bug in your own
change**: screenshot the affected page (`page.screenshot()`) and compare
`page.locator("nav.navbar").boundingBox()` before/after your diff at the
same viewport/auth state — if `origin/master` already shows the navbar's
real height exceeding `NavbarHeight`'s 50px (even by a little), your
change didn't invent the bug, it just widened an existing crack.

**Fix**: don't add width to the already-crowded left-hand `Nav` when a
new always-visible link is needed — put it in the right-hand
`ms-auto` cluster instead (today just `AuthWidget` + the download-manager
icon button + the Sources button, with real spare width). This keeps the
navbar's real rendered height identical to `origin/master`'s (confirmed
via the same `boundingBox()` check) rather than papering over the
symptom with a longer Playwright timeout or a spec edit.

**Partial deeper fix landed** (fix round on PR #305/#308's `/whatsthat`
quiz-reveal hero, owner review) —
`frontend/src/common/useNavbarHeight.ts` replaces the constant with a
real `ResizeObserver`-measured value, but only for the two consumers a
live report actually confirmed broken: `Layout.tsx`'s `ContentContainer`
(sitewide — every page's own top-of-content offset) and
`/whatsthat`'s own `PageColumn` height calc. Every other consumer
(`Explore.tsx`, `ProjectEditor.tsx`, `FinishedMyProject.tsx`) still uses
the static constant directly — this issue stays open for that broader
swap. The hook also only measures the navbar's _current_ height; it
doesn't change anything about the underlying wrapping behaviour above
(a crowded, every-link-visible state can still jump from 64px to 88px
when one more link tips it to a second line) — the hook picks that jump
up correctly via its own `ResizeObserver`, but the wrapping itself is
still exactly the layout fragility this entry describes.

## A `reparse_collector_evidence`/Stage D retraction pass silently never routes its own newly-touched cards to slow-path review

**Symptom**: `manage.py local_calculate_verdicts --write` runs cleanly
over a cohort that was previously retracted/re-scanned (e.g. via
`reparse_collector_evidence --selector parser-bug`/`--selector no-text`),
casts real join-key votes/skips (`[join-key] considered=N votes=...`),
and the gate passes — but
`CardScanLog.objects.filter(anonymous_id="stage-d-slow-path-v1", run_id=<this run>)`
comes back empty. The command's own `[slow-path]` log line for that
invocation shows `considered=0`/`routed=0` (or is easy to miss entirely
if only the `[join-key]` line is being read) even though the same
invocation's join-key stage just produced fresh no-match votes/no-hit
skips that should qualify for routing.

**Cause**: `reparse_collector_evidence.reparse_and_retract` deletes a
retracted card's stale `stage-d-join-key-v1` `CardPrintingTag`/
`CardScanLog` rows before re-voting, but never touches that card's own
`stage-d-slow-path-v1` `CardScanLog` row from whichever ORIGINAL routing
pass first flagged it. `local_calculate_verdicts._slow_path_eligible_cards_queryset`
excludes any card that already carries a `stage-d-slow-path-v1` row,
unconditionally — this is the calculator's own idempotence/resume
mechanism (never re-route a card twice), but it has no way to
distinguish "already correctly routed under its current conclusion" from
"routed once, under a conclusion that's since been retracted and
replaced." A card retracted-and-revoted at the join-key layer is
therefore silently excluded from ever being re-routed at the slow-path
layer, even though `local_calculate_verdicts --write` correctly re-ran
BOTH stages in the same invocation immediately afterward — the atomic
combination worked exactly as designed, it just had nothing new to do
for these specific cards.

**How to confirm it's this**: for the cards in question, check
`CardScanLog.objects.filter(anonymous_id="stage-d-slow-path-v1", card_id__in=<cohort>)`
— if a row exists with a `run_id` OLDER than the retraction that just
ran, that's the stale marker; the calculator saw it and (correctly, per
its own exclusion logic) didn't write a second one.

**Practical read on severity, verified 2026-07-21**: this is currently
harmless for `#262`/`#265`'s review-cluster backend specifically —
`cardpicker/review_clusters.py`'s `_review_queue_card_ids()` only checks
for the EXISTENCE of a `stage-d-slow-path-v1` row (any `run_id`), and its
clustering signals are re-read fresh from each card's CURRENT
`ImageEvidence` row at query time, never from anything stored on the
stale `CardScanLog` row itself (which, additionally, has no per-card
"why routed" field to be stale in the first place —
`skip_reason` is hardcoded to the literal `"to-review"` for every row
this calculator ever writes). A card in this state is therefore still
fully visible and correctly clusterable today. The gap only becomes a
real bug for a FUTURE consumer that reads something more specific from
that row (e.g. a per-card routing reason, which doesn't exist yet).

**Fix** (spec'd, not yet built — see
`docs/features/catalog-completion-plan.md`'s "Recovery-arc lessons"
section): extend `reparse_and_retract` to also delete the retracted
card's own `stage-d-slow-path-v1` `CardScanLog` row in the same pass it
deletes the `stage-d-join-key-v1` rows, mirroring the existing delete
and reusing the same safety gate. Until that ships, treat any retraction
pass as needing a manual check of whether its cohort also needs its
slow-path marker cleared before the next `local_calculate_verdicts --write` can actually re-route it under its new conclusion.

## Playwright tests behave like a 1280×720 desktop viewport even though `playwright.config.ts` sets 800×600

**Symptom**: a change that's supposed to be invisible/behave differently
below some breakpoint (a responsive drawer, a collapsed toolbar, a
media-query-gated style) shows up as always-inline/always-expanded in
every existing test in the suite, even though the `chromium` project's
`use` block clearly declares `contextOptions: { viewport: { width: 800, height: 600 } }`.

**Cause**: `contextOptions` is not a real Playwright `TestOptions`
field — Playwright's actual browser-context config lives at the
top level of `use` (`viewport`, `reducedMotion`, etc. directly), not
nested under a `contextOptions` key. `playwright.config.ts`'s `chromium`
project spreads `...devices["Desktop Chrome"]` first (which sets a
top-level `viewport: {1280, 720}` and `reducedMotion` is absent
entirely), then adds a sibling `contextOptions: {...}` object that
Playwright silently ignores — so every test in the repo has actually
been running at Desktop Chrome's stock 1280×720, full-motion, the whole
time. Confirmed by evaluating the real rendered viewport/computed style
inside a test (`page.evaluate(() => window.innerWidth)` and inspecting
an Offcanvas's actual class list) rather than trusting the config file's
stated intent.

**Fix**: for a test that genuinely needs a narrower/specific viewport
(or `reducedMotion`), use `test.use({ viewport: {...}, reducedMotion: "reduce" })` at the top level of a `test.describe` block (or per-test) —
that field name IS real and reliably overrides the project default for
just that scope, unaffected by the dead `contextOptions` wrapper. Don't
"fix" the stale 800×600 intent in the project config itself as a
drive-by — every existing spec in the repo was authored and passing
against the _actual_ 1280×720 desktop viewport, so correcting the config
to match its stated intent would silently change the effective
breakpoint tier (and therefore behavior) of the entire existing suite in
one line, far outside whatever single feature change prompted noticing
this. Filed during issue #266 (mobile `/display` responsive shell,
`frontend/tests/DisplayPage.spec.ts`'s phone-viewport describe block).

## A `ResizeObserver`-driven layout value is "stuck" at its initial default in one CI shard/spec but correct everywhere you check it manually

**Symptom**: a value derived from a `ResizeObserver` (e.g. a measured
container width feeding a child's render size) intermittently renders as
its unclamped, un-narrowed default rather than the real, smaller,
currently-available size — causing that child to overflow its own flex
column and visually spill under/over a sibling. Manual verification
(screenshots, a scratch Playwright script hitting the same page) shows
the correct, narrow value every time; only a specific CI shard, or a
specific _other_ spec file exercising the same page more deeply
(clicking further into nested UI before checking), reproduces it.
Playwright reports the interaction failure as an unrelated element
"intercepts pointer events" — the real target is exactly where expected,
but something else (the wrongly-sized sibling) paints on top of it at
that screen position.

**Cause**: an observer wired up via the "lazy-ref-initialization" pattern
(`if (ref.current == null) ref.current = new ResizeObserver(...)`,
directly in a component's render body — a legitimate React pattern for
an _expensive object that should exist exactly once_, but not
StrictMode-safe for one that also needs `observe()`/`disconnect()`
called on it from a callback ref) can end up with more than one live
instance simultaneously in `next dev`'s `reactStrictMode: true` (double-
invoke mount/cleanup/mount in development only). Each instance calls the
same state setter independently; whichever instance's callback fires
_last_ wins, and if a stale/duplicate instance is still attached to (or
re-observing) a node whose size hasn't yet settled to its final,
flex-constrained value, its late-firing callback silently overwrites the
correct measurement with a stale, too-large one. This is a genuinely
timing-dependent race — it doesn't reproduce every run, and a single
manual check right after the interaction you expect to trigger it can
easily land on the "correct" side of the race, which is why it slipped
through this change's own pre-push manual/screenshot verification and
only showed up as a real CI shard failure in a different spec file that
happened to interact more deeply (and therefore add more time/render
passes) before checking the result.

**Fix**: don't hand-roll `observe()`/`disconnect()` calls against a
lazily-constructed single observer instance from a plain callback ref.
Use the standard React pattern instead: a callback ref that writes the
DOM node into `useState`, plus a `useEffect` keyed on that state value
that creates a _fresh_ `ResizeObserver` scoped to the current node and
returns its own `disconnect()` as the cleanup function. This makes
setup/cleanup pairing explicit and StrictMode's double-invoke
mount→cleanup→mount cycle exercise it correctly every time — there is
never more than one live observer racing to set state, regardless of how
many times the effect re-runs. Confirmed via `page.addInitScript()`
wrapping `window.ResizeObserver` to log every `constructed`/`observe`/
`disconnect`/`fired: <width>` call — the lazy-ref version showed multiple
constructed instances and a final stale `fired: 960` (the unclamped
default) even though the container was genuinely ~488px wide by then;
the state+effect version settled on one instance and the correct value.
Filed during issue #266 (`frontend/src/features/display/DisplayPage.tsx`'s
sheet-region fit-to-width `ResizeObserver`, caught by
`tests/SelectVersionSection.spec.ts` failing in CI shard 4/4 only, not in
the 39 tests run locally pre-push).

## Running backend `pytest` on the production box without touching the live `docker-compose.prod.yml` stack

**Symptom**: you're on the production Oracle-box machine (not a cloud/web
session), need to run backend tests for a small fix, and the only running
Django/Postgres/Elasticsearch containers are the live, traffic-serving
`mpcautofill_*` ones from `docker-compose.prod.yml` — rebuilding or
`exec`-ing into them to run a test suite risks disrupting production, and
there's no obvious per-worktree isolated stack (container names are fixed
machine-wide, not per-worktree).

**Cause**: `MPCAutofill/manage.py`/`pytest` need real Postgres +
Elasticsearch to run against, but this box's only running instances are
production's own. It's easy to assume you have to spin up (or touch) the
prod compose stack to get there.

**Fix**: you don't need to touch the prod containers at all. A
pre-provisioned host venv already exists at
`/home/ubuntu/.venvs/mpcautofill-pilot` with Django/pytest/pytest-django/
tesseract/elasticsearch-dsl already installed — check for it before
creating a fresh one. `MPCAutofill/MPCAutofill/settings.py`'s own
`DATABASE_HOST`/`ELASTICSEARCH_HOST` env-var defaults are already
`localhost`, and `docker-compose.prod.yml` already exposes Postgres on
`127.0.0.1:5432` and Elasticsearch on `127.0.0.1:9200` — so
`/home/ubuntu/.venvs/mpcautofill-pilot/bin/python -m pytest` run directly
from `MPCAutofill/` on the host connects to the live containers' exposed
ports with zero env overrides needed. This is safe: pytest-django creates
its own ephemeral `test_*` database via `CREATE DATABASE` for the run and
tears it down after (the standard pytest-django lifecycle) — it never
reads or writes the actual production `mpcautofill` database/index. No
docker rebuild, no `docker compose exec`, no risk to the live stack.
Verified 2026-07-21 running `cardpicker/tests/test_local_ocr.py`,
`test_local_identify_printing_tags.py`, `test_image_evidence.py`,
`test_golden_set.py`, `test_local_calculate_verdicts.py`, and
`test_reparse_collector_evidence.py` together (370 passed) this way
against the live prod containers with no observed impact.

## Running the full `pytest cardpicker` suite gets mass `docker.errors.APIError`/`OperationalError: connection to server` failures across unrelated files

**Symptom**: a full `pytest cardpicker -q` run (not a targeted file/module)
produces hundreds of `ERROR`s spread across many files that have nothing to
do with your change (`test_views.py`, `test_vote_consensus.py`,
`test_sources.py`, etc.) — either `django.db.utils.OperationalError: connection to server at "localhost"`, or, on a worse collision,
`docker.errors.APIError: 500 Server Error for http+docker://localhost/...`
(e.g. `Bind for 0.0.0.0:9300 failed: port is already allocated`, or the
same for `:47000`). Individually running the files your change actually
touches passes cleanly (100%), which is the tell that this isn't a
regression in your code. Every test in an affected run shows as `ERROR`,
not `FAILED`, and the traceback bottoms out in `cardpicker/tests/conftest.py`'s
`postgres_container`/`elasticsearch_container` fixtures, not in your own
code.

**Cause**: this repo's `db`/`transactional_db` pytest fixtures spin up
throwaway `testcontainers` Postgres/Elasticsearch containers per test run
(`cardpicker/tests/conftest.py`) on **fixed** host ports (`POSTGRES_PORT = 47000`, `ELASTICSEARCH_PORT = 9300` - the latter is also
`pytest_elasticsearch`'s own hardcoded default) - a full-suite run
launches (and tears down) a lot of them in a short window. This machine
runs more than one Claude Code worktree session at a time (see
`WORKERS.md` at the repo root, machine-local); every worktree shares the
same Docker daemon, so two sessions running `pytest` at the same moment
compete for the same Postgres connection ceiling and/or try to bind the
same two fixed host ports - only one port-bind wins, and testcontainers
surfaces the loser's failure as a raw Docker API error rather than a
friendly retry/backoff message. `docker ps`/`ps aux | grep pytest` will
show another session's containers/process still running if this is the
cause. A related, quieter form of the same root cause needs no other
session at all: if a PRIOR run of yours was interrupted (or one of its
fixtures failed) before its own `postgres_container`/
`elasticsearch_container.stop()` teardown ran, the now-orphaned container
keeps holding the port for every subsequent run of yours too - `docker ps -a` showing a `romantic_elion`/`relaxed_mccarthy`-style random-named
container still `Up` on `:47000`/`:9300` from an earlier failed session
is the tell.

**Fix**: this is infrastructure contention, not a code bug - don't debug
your own change against it. Before trusting a full-suite failure list,
check for a concurrent `pytest` process (`ps aux | grep pytest`) and
concurrent testcontainers (`docker ps`) from another session. If found,
wait for it to finish (or coordinate via `WORKERS.md`) and re-run - don't
debug your own code against a result contaminated by another session's
resource contention; trust your own affected-files-only run
(individually and together) as the primary verification signal in the
meantime, with a full-suite run as a nice-to-have confirmation, not the
only valid one, when this box is shared. If instead the container
holding the port is an ORPHAN of your own prior failed run (you recognize
the run as yours and it's been sitting idle, not freshly created) rather
than a live concurrent session's, it's safe to `docker rm -f <name>` it
and retry immediately - but never remove a container you don't recognize
as your own leftover, since a live session's containers still mid-test
are exactly the "port is already allocated" collision this entry
describes, not a target for cleanup. Confirmed one 2026-07-23 session
hitting this twice in the same task (once from a genuine concurrent
session, once from its own prior run's orphaned containers) - `docker rm -f` on the confirmed-orphan case, then a plain retry once ports read
free resolved both.

## A per-instance `viewBox` crop on an inlined SVG shows the _entire_ source art instead of just its own band

**Symptom**: three separate `<svg viewBox="...">` elements, each meant to
crop a different horizontal band out of the same inlined wordmark path
data (`WhatsThatWords.tsx`, issue #305), all render the full, uncropped
wordmark at slightly different sizes instead of their own distinct slice
— confirmed via `getAttribute("viewBox")` in a live page that each
element's `viewBox` attribute IS correct, and `overflow: hidden` is
already set and computes correctly too, yet the bug persists.

**Cause**: two independent CSS behaviors compound here, neither obviously
connected to "SVG cropping" on its own:

1. A root-level `<svg>` (i.e. one that isn't nested inside another `<svg>`
   in the DOM) can still be affected by a Flexbox ancestor's default
   `align-items: stretch` — if the flex container is `flex-direction: column`, `stretch` operates on the CROSS axis, which for a column flex
   is WIDTH. A replaced element (SVG counts) with CSS `width: auto` is
   exactly the trigger condition for `stretch` to override its own
   intrinsic (`height` × viewBox-aspect-ratio-derived) width and force it
   to the full container width instead.
2. Once the SVG's rendered box is stretched far wider than its own
   viewBox's aspect ratio, `preserveAspectRatio`'s default `xMidYMid meet`
   recomputes its internal scale against that stretched box — and at a
   large enough width/height mismatch, more of the underlying artwork
   becomes visible within the (correctly, `overflow: hidden`-clipped) box
   than the viewBox rectangle alone would suggest, because the box itself
   grew, not because the crop stopped applying. `overflow: hidden` and a
   correct `viewBox` attribute are both real and both necessary, but
   neither one controls the SVG's own rendered box size — that's ordinary
   CSS layout, upstream of either.

**Fix**: stop the stretch at the source — add `align-items: flex-start`
(or `center`, matching whatever horizontal alignment is wanted) to the
flex-column parent, so each SVG child keeps its own intrinsic,
height-derived width instead of being forced to the container's full
width. Diagnosed by isolating the exact repro in a minimal throwaway HTML
page (one flex-column parent, three stacked SVGs, no React/Next in the
loop at all) rather than debugging inside the full app — confirmed the
same three-line reproduction failed identically, and that removing only
the flex-column wrapper (testing the single SVG alone) fixed it, which is
what pointed at the flex cross-axis stretch specifically rather than the
SVG/viewBox mechanics themselves.

## `/display`'s floating "n/M" sheet-position pill under-reports the last sheet (shows `2/3` instead of `3/3`) after scrolling all the way down

**Symptom**: `DisplayPage.spec.ts`'s sheet-position-pill test (test title
carries a trailing "(D17)" — the test's own name literally quotes the
retired label from `proposal-h-display-layout-spec.md`'s [sheet-presentation
refinement decision](proposals/proposal-h-display-layout-spec.md#sheet-presentation-refinement),
kept verbatim here since it's a direct quote of the code, not a fresh
reference) — "the floating sheet-position
pill updates live while scrolling at phone width" — fails with
`getByTestId('display-sheet-position-indicator')` stuck at `"2/3"` after
scrolling the last sheet into view via `scrollIntoView({ block: "center" })` at 390px wide — reproduces 100% of the time in isolation, both
locally and in CI (not the intermittent kind), even though the same test
was merely marked "flaky" (2 real failures then a lucky pass) in the PR
that introduced it (#313).

**Cause**: the indicator's `IntersectionObserver` (`DisplayPage.tsx`,
`visibleSheetIndex`) decides "which sheet is current" purely by a thin
vertical center band (`rootMargin: "-45% 0px -45% 0px"`) against the
page viewport. That heuristic structurally can't ever select the FIRST
or LAST sheet once the scrollable `content-container` (Layout.tsx) is
already at its true scroll extreme and a boundary sheet is short enough
that there's no room left below/above it to move its own center through
that band — confirmed by measuring the container directly:
`scrollHeight - clientHeight` (the real max scroll) was ~250px, but
centering the last (short) sheet would have needed roughly 500px+ of
scroll, a shortfall of 250-280px that no amount of further scrolling can
close, because the container is already at its true bottom. This isn't
specific to any one card count or viewport — it's inherent to a fixed
center-band test whenever a boundary sheet is short relative to the
viewport, and is unrelated to Footer/Navbar sizing (`/display` doesn't
even render a `Footer`).

**Fix**: inside the same `IntersectionObserver` callback, read the
scroll container's own `scrollTop`/`scrollHeight`/`clientHeight`
(via `entries[0].target.closest('[data-testid="content-container"]')`)
and check the true scroll extremes FIRST — at `scrollTop <= EPSILON`,
force index `0`; at `scrollTop + clientHeight >= scrollHeight - EPSILON`,
force the last index — falling through to the existing center-band
`Math.min(...intersectingIndices)` logic only when not at an edge. Kept
as a single writer to `visibleSheetIndex` (not a second `scroll`
listener racing the observer) since the observer already re-fires on the
same settling scroll event that changes intersection state. Verified
5/5 clean repeats of the sheet-position-pill test plus the full 28-test `DisplayPage.spec.ts`
suite and CI's own shard-2/4 (76 tests) locally.

## `run_image_evidence_cohort` (Stage C) parent process's RSS climbs unboundedly and OOMs the whole box on a long run

**Symptom**: a long (tens-of-thousands-of-cards) `run_image_evidence_cohort`
invocation shows parent-process RSS climbing steadily over the run's
lifetime — not a leveling-off/plateau — reaching tens of GB and either
OOM-killing the whole box or (if a watchdog is in place) getting stopped
partway through. Arithmetic: retained bytes ÷ cards processed lands around
250-350KB/card, which is the size of one raw fetched card image buffer, not
anything decoded or persisted.

**Cause**: the decoupled fetch/compute driver (`_run_cohort`, added by the
Stage C fetch/compute decoupling — #228/#235,
`docs/features/catalog-completion-plan.md`'s "Stage C: fetch/compute
decoupling" section) submitted every card in the cohort to the fetch thread
pool UP FRONT, and only gated COMPUTE submission behind `--queue-depth`. The
design doc's own memory-budget arithmetic for that section silently assumed
fetch completion was ALSO bounded by that window — the implementation never
enforced it. Fetch (I/O-bound, paced by a 6-way concurrency limiter)
completes cards faster than the CPU-bound compute stage consumes them, so
fetch raced arbitrarily far ahead of consumption over a multi-hour run,
accumulating raw image buffers for the entire fetched-but-not-yet-consumed
backlog — in the worst case, most of the remaining cohort. A secondary,
much smaller (~1% of the effect) contributor: the `fetch_futures` collection
tracking submitted futures was never pruned as futures were consumed, so
even already-handled results stayed referenced (and their retained image
bytes stayed resident) for the rest of the run.

**Fix** (2026-07-22): fetch submission is now drip-fed
(`_submit_more_fetch`), bounded by the same `--queue-depth` knob already
used to gate compute submission, so total outstanding fetch-stage work (in
flight + completed-but-not-yet-consumed) never exceeds that window regardless
of cohort size. The `fetch_futures` tracking set now discards each future the
instant its result is consumed. The command also logs the parent's own RSS
(from `/proc/self/status`) on every progress line — so the next time this (or
anything like it) accumulates unexpectedly, the log itself shows it climbing
— and a new `--max-rss-mb` flag (off by default) turns crossing a threshold
into a clean, resumable stop instead of relying on the OS OOM-killer; the
command's own resume filter (skip cards whose `ImageEvidence` row already
carries every manifest extractor's version key) makes a re-invocation after
any stop safe. Diagnosed via a synthetic repro (tracked, weakref-observable
payload objects standing in for real fetched bytes, no live prod run) that
reproduced the exact growth-with-cohort-size pattern before the fix and
confirmed the bound held after it — see
`cardpicker/tests/test_run_image_evidence_cohort.py`'s
`TestRunCohortFetchMemoryBound` for the same property turned into a
permanent regression guard.

## `guard_master.py` denies a `git merge`/`git push` you ran from inside a feature worktree

**Symptom**: a command like `cd /path/to/feature-worktree && git merge origin/master` (resolving a feature branch's conflicts against master) gets
denied with `[guard_master] git merge into master is owner-only, always`,
even though the branch actually being merged into isn't master.

**Cause**: `guard_master.py`'s `git merge`/`git push` rules judged branch
state via `current_branch(cwd)`, where `cwd` is the session's registered
working directory — not wherever the command's own `cd <path> &&` chain
actually pointed git at. A session whose registered cwd happens to be a
master checkout gets every `cd <other-dir> && git merge ...` it runs
judged against master, regardless of what's actually checked out at
`<other-dir>`. Confirmed in production 2026-07-22: this wrongly blocked
legitimate feature-branch conflict resolution.

**Fix** (2026-07-22): added `effective_dir(command, session_cwd, target_re)`
— splits the command into simple-command segments on `;`, `&`, `|`, `&&`,
and `||`, locates the segment matching the merge/push the calling rule
already detected, then walks backward from it collecting only the
segments joined to it by an unbroken chain of `&&` (a `cd` behind a `;`,
single `&`, `|`, or `||` boundary is a different shell statement and is
deliberately not followed — real `&&` semantics mean only a genuinely
chained `cd` can be trusted to have actually run before the merge/push
did). Processes that chain applying each whole-segment `cd <path>` in
turn; falls back to `session_cwd` (today's pre-fix behavior) whenever
there's no leading `cd` chain, or any `cd` in it targets a path that
isn't a real directory — a resolution failure is never more permissive
than session-cwd-only judging. Used in both the `git merge` and `git push` worktree rules' `current_branch(...) == "master"` checks.
Unchanged: the unconditional `gh pr merge` denial, the `--ff-only`
exemption, all deny messages, `log_stub`'s behavior, and the push rule's
`in_worker_worktree` gate (still computed from raw session cwd, since it
identifies which _session_ is running, not which directory a given
command targets). See `.claude/hooks/test_guard_master.py` for the
regression cases.

**Same-day tightening**: the first cut of this fix also resolved a bare
`git -C <path>` anywhere in the command via an unanchored scan. That
turned out to be a false-ALLOW risk in the opposite, more dangerous
direction: an earlier, unrelated `git -C /some/repo status && git merge origin/master` could get its unrelated `-C` path substituted in for the
real merge's own context, wrongly ALLOWing a genuine merge-into-master.
Confirmed by direct trace, then closed by dropping `git -C` support
entirely rather than anchoring it — `effective_dir()` now only follows
`cd` chains. This reopens a narrower, safe gap: a bare `git -C <path> merge/push ...` command isn't recognized as a merge/push attempt at all
today, since the calling rules' own detection regexes require "git" and
"merge"/"push" adjacent with no intervening flag — accepted, since
under-triggering only ever produces an unnecessary DENY, never a wrong
ALLOW, and `cd`-chains are the pattern that actually occurred in
production.

## `DisplayPage.spec.ts`'s "floating sheet-position pill updates live while scrolling at phone width (D17)" fails intermittently with "2/3" instead of "3/3"

**Symptom**: `tests/DisplayPage.spec.ts`'s sheet-position-pill test
(phone viewport, 18 cards / 3 sheets) intermittently reports the
`display-sheet-position-indicator` still reading `2/3` after
`scrollIntoView({block:"center"})` on the last sheet, where `3/3` is
expected - reproduces even running that ONE test alone,
`--repeat-each=5`+, on both a freshly-modified branch and on plain
`origin/master` with zero changes.

**Cause**: a genuine, pre-existing flake in this test's own
IntersectionObserver-based timing (its `rootMargin: "-45% 0px -45% 0px"`
thin center-band check races the browser's `scrollIntoView` completing),
not a regression from any particular change - confirmed by reproducing
the same ~1-in-6 failure rate on unmodified `origin/master` in this same
sandboxed VM. A change that happens to add or remove incidental
rendering cost nearby (e.g. widening a `useMemo`'s dependency array on
the sheet-content builder) can shift the failure rate up or down without
being the actual cause - don't chase a "regression" here without first
checking the identical test against a clean `origin/master` checkout in
the same environment, `--repeat-each=5` or more (a single passing/failing
run either way is not enough evidence).

**Fix/mitigation**: none applied - this is a test-timing flake to
tolerate (retry) rather than a product bug to fix; if it starts failing
CI at a rate that matters, the real fix is loosening the test's own
`scrollIntoView`-then-assert race (e.g. an explicit
`waitForFunction`/poll on the indicator text before asserting, instead of
relying on `expect(...).toContainText`'s own retry window alone), not
touching the sheet-content pipeline it happens to render.

## A styled-component CSS template literal throws confusing `TS1005`/`TS1351`/`TS1443` parse errors a few lines below a comment that "looks fine"

**Symptom**: adding an explanatory `//` comment INSIDE an
emotion/styled-components CSS template literal (between the opening
`` styled.div` `` and its own closing backtick) produces a cascade of
unrelated-looking TypeScript parse errors - `TS1005: ',' expected`,
`TS1351: An identifier or keyword cannot immediately follow a numeric literal`, `TS1443: Module declaration names may only use ' or " quoted strings` - pointing at code several lines AFTER the comment, not at the
comment itself.

**Cause**: the comment contains a literal backtick character (e.g.
writing `` `minmax(0, 7.5rem)` `` or `` `position: sticky` `` inline to
mark it as code). A JS/TS template literal has no concept of a "CSS
comment" - stylis (the CSS preprocessor emotion/styled-components run
template-literal content through) treats `//...` as a comment, but that
processing happens AFTER the JS parser has already tokenized the
template literal as a plain string. The JS parser itself doesn't know or
care that stylis will later treat some of this text as a comment - it
just scans for the next unescaped backtick to close the string, or `${`
to start an interpolation. A literal backtick anywhere inside - even
inside what stylis would consider a `//` comment - closes the JS
template literal early, and everything after that point (until the NEXT
stray backtick, which reopens ANOTHER unintended template literal) gets
parsed as ordinary TypeScript code instead of CSS-in-JS string content,
producing parse errors that land wherever that reopened/misparsed region
happens to contain something syntactically invalid.

**Fix**: never use a literal backtick inside a comment that lives
between a styled-component's own opening/closing backticks - drop the
backticks around the quoted CSS/prop name entirely (plain text reads
fine: `minmax(0, 7.5rem) track` instead of `` `minmax(0, 7.5rem)` ``
track), or move the comment to sit OUTSIDE the template literal (a
regular `//` comment directly above the `const X = styled.div` line
declaration has no such restriction - backticks there are just ordinary
text in a real JS single-line comment, not inside a string at all).
`npx tsc --noEmit` catches this immediately and precisely once you know to look
for a stray backtick upstream of the reported line - the error location
itself is not where the actual mistake is.

## `getWorkerImageURL`/other `NEXT_PUBLIC_*`-reading helpers return `undefined` when called directly from Playwright TEST code (not the app)

**Symptom**: a Playwright spec imports a shared helper that reads a
`NEXT_PUBLIC_*` env var (e.g. `common/image.ts`'s `getWorkerImageURL`,
used to compute an expected URL for `page.route()` interception) and
calls it directly in the test body - it returns `undefined` even though
`playwright.config.ts`'s `webServer.env` clearly sets that exact
variable, and the app's own BROWSER-rendered `<img src>` resolves to a
real, correct URL built from the same helper.

**Cause**: `NEXT_PUBLIC_*` variables are inlined into the BROWSER bundle
by Next.js's webpack build step at the point the dev server starts
(`playwright.config.ts`'s `webServer.command: "npm run dev"` spawns that
process with `env` scoped to just that child process) - they are not,
and were never meant to be, environment variables available to arbitrary
Node code. The Playwright TEST RUNNER itself (`npx playwright test`) is
a completely separate Node process with no bundling step of its own, so
`process.env.NEXT_PUBLIC_IMAGE_WORKER_URL` (or any other
`NEXT_PUBLIC_*` var) is simply unset there regardless of what
`webServer.env` configures for the spawned dev server.

**Fix**: if a test genuinely needs to compute the same URL production
code would build (e.g. to `page.route()`-intercept it, rather than
guessing/hardcoding a pattern that can drift out of sync with the real
implementation), set `process.env.<THE_VAR>` explicitly at the top of
that test body to mirror `playwright.config.ts`'s own `webServer.env`
value, immediately before calling the helper - this only affects the
Node-side computation in the test, not the already-running browser
(which resolved its own copy independently, at its own build time), so
it's safe and has no effect beyond that one calculation. Also watch for
`page.route()`'s string argument being a GLOB pattern, not a literal
string - a computed CDN URL with a `?jpgQuality=100`-style query suffix
needs its `?` escaped (or the whole pattern passed as a `RegExp`
instead), since glob `?` means "exactly one arbitrary character," not
literal query-string syntax.

## `docker exec mpcautofill_django ps` → "executable file not found"

**Symptom**: `sudo docker exec mpcautofill_django ps aux` (or any other
`ps` invocation inside the running Django container) fails immediately
with something like `OCI runtime exec failed: exec: "ps": executable file not found in $PATH`.

**Cause**: the container's base image doesn't ship a `ps` binary at
all — this isn't a `$PATH` misconfiguration, `ps` genuinely isn't
installed.

**Fix**: use the compose CLI's own process view instead of shelling in —
`sudo docker compose -f docker-compose.prod.yml top <service>` (e.g.
`top django`) reads process info from the host's own view of the
container, no in-container binary required. `docker compose` v2 with
the space, per this repo's own tooling convention — never the
hyphenated `docker-compose` v1 binary.

## Logged out of admin/moderation after a backend deploy

**Symptom**: an owner/moderator session that was logged in via Discord
OAuth (or Django admin) stops being authenticated right after a backend
deploy that recreates the `mpcautofill_django` container — same
browser, same cookies present, just no longer treated as logged in.

**Cause**: **unconfirmed as of this writing** — a container recreate
does invalidate the session, but which layer actually breaks it (an
in-memory/process-local session store losing state on restart, vs. an
OAuth token the recreate somehow invalidates) has not been isolated.
Don't assert a specific mechanism until it has actually been traced
through a recreate.

**Fix**: log back in; no workaround needed beyond that. **Next
occurrence**: before writing this off as "expected," reproduce
deliberately (recreate the container, watch whether the session
survives) and confirm which layer is actually responsible, then replace
this entry's cause with the confirmed one.
