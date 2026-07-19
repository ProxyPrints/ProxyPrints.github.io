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

## 5-6 unrelated test snapshots break after adding one new test file

**Symptom**: a brand-new test file (using an existing shared factory) is
added, and several _other_, seemingly-unrelated tests start failing —
often `test_views.py::TestGetTags::*` or similar snapshot-style
assertions with a hardcoded value like `"Artist 0"`.

**Cause**: `factory.Sequence` counters in `cardpicker/tests/factories.py`
are process-global for the whole pytest run. A snapshot assertion that
hardcodes a sequence-derived value implicitly depends on total call count
up to that point in collection order — a new test file using the same
shared factory shifts that count.

**Fix**: an autouse fixture local to the new test file(s) only, that
captures each shared factory's `next_sequence()` before the test body
runs and calls `reset_sequence(n, force=True)` both immediately (undo the
peek's own increment) and again in teardown — zero net drift. Don't touch
`conftest.py` or existing test files.

**Recurred 3 times after being documented** ([[lessons.md]]) because each
new test file has to independently rediscover which factories count as
"shared": deductive-backfill work (had to add `SourceFactory`/
`CanonicalArtistFactory` to the list), and again in
`test_purge_machine_votes.py` (catalog-completion work). When adding a
test file that uses any factory from `cardpicker/tests/factories.py`,
apply this pattern preemptively rather than waiting to see which
snapshots break.

**Variant: a new TEST inside an EXISTING file, not a new file** (E-2,
`test_views.py`, `d7e4653c`) — the same drift, different trigger. Adding
one new test to `TestPostEditorSearchResults` (which uses the class's own
function-scoped `populated_database` autouse fixture, same as every other
test in the class) shifted `TestGetSampleCards`/`TestNewCardsFirstPages`/
`TestNewCardsPage`/`TestPostExploreSearchResults` downstream in the same
file - going from N to N+1 tests using a sequence-consuming fixture
permanently shifts everything after it, file-wide autouse isn't an option
here (it would reset the ambient count for ~200 _other_, correctly-passing
tests in the same file that depend on it). The fix has to be scoped to
just the one new test, which is non-trivial: a same-scope fixture the test
merely _requests_ instantiates too late to see the pre-existing-fixture
"before" value, because same-scope autouse fixtures always instantiate
first. Resolution: a **module-level autouse fixture, gated on
`request.node.name`** - inert (immediate no-op `yield`) for every test
except the one named test, so it wins fixture-ordering priority (module-
level autouse beats class-level autouse at the same nominal scope) while
having zero effect on the rest of the file. See
`test_views.py::_preserve_shared_factory_sequences_for_insulated_tests`.

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
stage, and CI test runners also lack the real binary.

**Fix**: tesseract is now baked into the Dockerfile's shared builder
stage — don't reach for a host-venv workaround. Tests mock tesseract
directly rather than requiring the real binary in CI (`ddb6dce9`, "Fix
CI: mock tesseract in tests"). See [[features/printing-tags.md]]'s build
history (`git log e4eb6cb3 -- docs/features/printing-tags.md`) for the
full timeline if you need it.

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
