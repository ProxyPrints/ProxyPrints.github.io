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
are actually separable. (`8c957aa5`, 2026-07-16.)

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
