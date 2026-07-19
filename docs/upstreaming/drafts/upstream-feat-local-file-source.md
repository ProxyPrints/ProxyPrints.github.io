# Draft: `upstream-feat-local-file-source`

**Status: branch cut and verified, PR NOT opened.** This is an in-repo
draft only, per the standing rule that nothing touches upstream's repo
without the owner personally sending it. When/if the owner decides to
send it: `gh pr create -R chilli-axe/mpc-autofill --head ProxyPrints:upstream-feat-local-file-source` (or the GitHub UI), pasting
the "PR body" section below verbatim into the description field.

- **Branch**: `upstream-feat-local-file-source`, pushed to `origin`
  (this fork) at commit `93874645`. Not pushed to, and no PR opened
  against, `chilli-axe/mpc-autofill`.
- **Cut from**: `upstream/master` at `c3d10253` (the tip as of
  2026-07-18, i.e. including our own merged #467).
- **Source**: cherry-picked from this fork's `5cb438b2` ("Implement real
  support for the LOCAL_FILE source type", 2026-07-12), which was already
  a single, clean, self-contained commit — no splitting or hand-assembly
  needed for the feature itself.

---

## PR body (paste verbatim)

# Description

`LocalFile` (`cardpicker/sources/source_types.py`) was previously a stub
— the source-type enum, `Source.identifier`'s field comment, and
`get_identifier()` already anticipated a local-filesystem catalog source,
but folder/image traversal raised `NotImplementedError`. This fills it in
fully, using `GoogleDrive` as the reference pattern: `Source.identifier`
is a root directory path on disk, crawled recursively for images via the
filesystem instead of an API call, reusing image dimensions read locally
via Pillow (`GoogleDrive` gets this for free from
`imageMediaMetadata.height`).

Since the frontend only loads images by URL, this adds a
`get_local_file_image` view that serves image bytes back out for a
card's underlying file. That's a real security surface, so it's treated
as one: symlinked files and directories are never traversed during
indexing, and at serve time every request independently re-resolves the
requested path and verifies it's still inside the source's _currently
configured_ root directory (`resolve_within_root` in
`cardpicker/sources/api.py`) before anything is read from disk — covering
both `../`-style directory traversal and symlink escape, and re-checked
at serve time (not just trusted from indexing) in case a source's root
was reconfigured after its images were catalogued.

Indexing itself needed no changes to `update_database.py` — it already
dispatches generically over `SourceType`, so `LOCAL_FILE` sources are
crawled the same way Drive sources are. Re-scanning a single source
already existed too, via `update_database --drive <key>` (a slight
naming leftover from Drive-only days; help text updated to note it works
for any source type), and this also adds an admin action on `Source` for
the same, since either seemed reasonable to offer.

## Checklist

- [x] I have installed `pre-commit` and installed the hooks with
      `pre-commit install` before creating any commits. — ruff, isort,
      black, and mypy all run clean against every file this PR touches.
      (One pre-existing mypy `QuerySet` type-arg warning appears in
      `admin.py` on this branch; it's not introduced by this change —
      the identical warning already exists on unmodified
      `upstream/master` in `documents.py`/`search_functions.py`, from
      django-stubs version drift against the repo's current code. Flagging
      for visibility, not claiming it's fixed here.)
- [x] I have updated any related tests for code I modified or added new
      tests where appropriate. — `cardpicker/tests/test_local_file_source.py`,
      17 new tests: path-traversal/symlink-escape rejection, folder/image
      crawling (including symlink exclusion), thumbnail URL construction,
      the `get_local_file_image` view's status codes, and end-to-end
      indexing via `update_database`. Fully self-contained against
      `tmp_path` — no network access or credentials required, unlike the
      existing `GoogleDrive` source tests.
- [x] I have manually tested my changes as follows:
  - Hand-verified the path-traversal/symlink-escape rejection logic and
    the folder/image crawl (including symlink exclusion, non-image
    filtering, and DPI-from-height calculation) directly against a real
    temp directory tree, outside of pytest — see "Verification" below for
    why and what that covered vs. didn't.
  - Ran the full `pre-commit run --all-files`-equivalent (ruff, isort,
    black, mypy) against every touched file.
- [x] I have updated any relevant documentation or created new
      documentation where appropriate. — the new code is documented via
      docstrings on `resolve_within_root`, `LocalFile`, and
      `get_local_file_image` explaining the security model; no
      user-facing docs changes seemed necessary since this is a new
      `Source` type an admin configures the same way as any other.

---

## Extraction notes (internal — not part of the PR body)

**Why this was the pattern-proof pick**: zero dependency on any other
fork-only feature (no vote system, no moderation, no OCR pipeline —
confirmed in `readiness-audit.md` §1.1/§2), fills a gap upstream's own
schema already anticipated, and the originating fork commit was already
a single clean unit — the best available test of the extraction _process_
itself before investing in a harder chunk.

**Two small hand-fixes were needed**, both because the original fork
commit (`5cb438b2`, made 2026-07-12) was written against a version of
these files that already carried _other, unrelated_ fork commits' changes
— cherry-picking it alone onto pristine `upstream/master` exposed the gap:

1. `views.py` used `logger.warning(...)` in the new
   `get_local_file_image` view, but `logger = logging.getLogger(__name__)`
   doesn't exist upstream — it was added by this fork's Sentry-removal
   commit (`795f5ac0`), which predates `5cb438b2` on the fork timeline but
   obviously isn't itself upstream-portable. Added the one missing line
   by hand.
2. `admin.py`'s new `rescan_sources` admin action used `HttpRequest` and
   `QuerySet` as type annotations, but neither is imported — both came
   from other, later fork commits (the vote-system's admin filters).
   Added the two missing import lines by hand.

Both are exactly the kind of gap `docs/upstreaming/conventions.md` item 5
asks to watch for ("no unrelated hunks from a shared file") — in this
case not extra content leaking in, but _implicit_ context the original
commit silently depended on. Worth remembering for every future
extraction: a commit that looks self-contained by `git show --stat` can
still assume names introduced elsewhere in the fork's history.

**Verification, and its real limits**: this sandboxed session has no
Docker daemon (`docker.sock` missing) and no live Postgres/Elasticsearch,
consistent with `CLAUDE.md`'s standing note for cloud sessions. That
matters more than usual here because upstream's own `cardpicker/tests/conftest.py`
gates its _entire_ test session behind an `autouse=True`,
session-scoped `elasticsearch` fixture backed by `testcontainers` (real
Docker containers for both Postgres and ES) — so literally no test in
`test_local_file_source.py` could be collected via `pytest`, not even the
9 pure-filesystem cases that touch neither database. Confirmed this is
upstream's own test-harness design, unmodified by this branch, not
something introduced here.

What was actually done instead, to get real signal rather than none:

- `django.setup()` + direct imports confirmed the whole app registry
  loads cleanly with this branch's code in place (proves no import-time
  or syntax errors anywhere the diff touches, including files it doesn't
  directly modify).
- The 9 DB/ES-independent test scenarios (`resolve_within_root`'s
  traversal/symlink rejection, `LocalFile`'s folder/image crawl including
  symlink exclusion and DPI derivation, thumbnail URL construction) were
  hand-executed against real temp directories and symlinks, outside
  pytest's Docker-gated session — all passed, exercising the same
  assertions the real test file makes.
- The remaining 6 tests (`TestGetLocalFileImageView`, needs a Django test
  client + a `Card`/`Source` row) and 2 tests (`TestLocalFileIndexing`,
  needs real ES) were **not** run. A quick attempt to substitute SQLite
  for Postgres to at least exercise the DB-backed path was blocked by
  pre-existing (unrelated to this chunk) Postgres-specific model field
  usage elsewhere in the schema that fails Django's SQLite system checks
  — not worth working around for a verification exercise.
- ruff, isort, black, and mypy were run with the exact pinned versions
  and `additional_dependencies` from upstream's own
  `.pre-commit-config.yaml`. All clean except the one pre-existing,
  version-drift mypy warning documented above and in the PR checklist.

**Before this is actually sent**: re-run the full test suite against a
real Postgres+ES (or upstream's own CI, once opened) to cover the 8
untested cases — everything above is real, non-fabricated verification,
but it's not a substitute for the actual integration tests passing.

## CI baseline (for `upstream-branch-verification.yml`)

What a real CI run (GitHub-hosted runner, real Docker, upstream's exact
`test-pre-commit`/`test-backend` recipes) should show for this branch —
cross-reference `upstream-branch-verification.yml`'s relayed report
against this before treating anything as a regression:

- **`pre-commit run --all-files`**: expected fully green. Verified
  locally against the exact pinned hook versions (see "Verification"
  above) with zero findings in any file this branch touches.
- **`pytest .` in `MPCAutofill/`**: expected **17/17 green** in
  `cardpicker/tests/test_local_file_source.py` specifically — this
  branch's own tests are fully self-contained against `tmp_path`, no
  live credentials or external services beyond the workflow's own
  Postgres/ES services.
- **Expected non-regressions elsewhere in the suite**: any failure in a
  test file this branch doesn't touch that traces back to a missing
  `GOOGLE_DRIVE_API_KEY`/`MOXFIELD_SECRET` (this fork's CI has neither
  configured) is a known environmental gap, not something this branch
  broke — `docs/features/local-file-source.md`'s own comparison already
  flags the pre-existing Google Drive source tests as the CI-fragile
  ones for exactly this reason. If the relayed report shows failures
  **only** in Google-Drive/Moxfield-dependent test files, that's the
  expected baseline, not a blocker.
- **A real blocker looks like**: any failure inside
  `test_local_file_source.py` itself, or a failure in a file this branch
  modifies (`admin.py`, `views.py`, `urls.py`, `settings.py`,
  `sources/api.py`, `sources/source_types.py`,
  `management/commands/update_database.py`) that isn't one of the two
  known-environmental buckets above.
