```
TASK: Backend tests GitHub Actions check failing on master (reported
HEAD 65df7d8d, "Harvest-calculate pipeline Stage B" #131; master had
moved to 8f98127c #133 by the time this ran - both docs-only commits
in between, root cause unaffected). Branch:
worktree-agent-aea2752d83552fd91 (worktree of the same name). Commit:
90860de3. Pushed, not merged, no PR opened - per task instructions,
left for the owner to land.

WHAT SHIPPED:

1. Pulled the actual failure log for job 88203700809 (run 29691041443)
   via `gh api repos/.../actions/jobs/<id>/logs` (`gh run view
   --log-failed` returned nothing on this box's old gh 2.4.0 - noted
   as a tooling gap, not investigated further). 14 failed, 947 passed,
   1 skipped. Three distinct root causes, confirmed by checking ~100
   runs of Web CI history (`gh run list`) and job-level breakdowns on
   several: Backend tests has failed on every run for at least the
   past week, well before #131.

   a) 2 failures, `test_integrations.py::TestMTGIntegration::
      test_valid_url[moxfield*]` - `assert None`. `MTGIntegration.
      query_import_site` makes a real network call to moxfield.com;
      confirmed identical failure on a run from 2026-07-12, a week of
      persistent history. Live-network test flakiness/dependency, not
      a code bug, out of scope.

   b) 2 failures, `test_sources.py::TestUpdateDatabase::
      test_comprehensive_snapshot`/`test_upsert` - `json.decoder.
      JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
      Traced to `find_or_create_google_drive_service` reading an empty
      `client_secrets.json`, written by `.github/actions/test-backend/
      action.yml`'s `jsdaniell/create-json@v1.2.3` step from
      `secrets.GOOGLE_DRIVE_API_KEY`. Confirmed identical failure on
      the same 2026-07-12 run. Empty/misconfigured repo secret, not a
      code bug and not something I can fix without the secret value -
      out of scope, flagged as OPEN ITEM below.

   c) 10 failures, all `pytesseract.pytesseract.TesseractNotFoundError:
      tesseract is not installed or it's not in your PATH`, across
      `TestExpansionHintNarrowing`, `TestScanLog`, `TestConcurrency`,
      `TestClusterDedup` in `test_local_identify_printing_tags.py`.
      THIS is the genuine, scoped, code-level regression, and the one
      fixed this session (detail below).

2. Root cause of (c): `local_identify_printing_tags.run_pilot`'s
   per-card compute path (line ~626) calls `local_fallback.
   detect_illus_anchor(image, ...)` UNCONDITIONALLY whenever
   `fetch_card_image` returns a non-None image, regardless of which
   `--engine` was requested. `detect_illus_anchor` falls through to
   `local_ocr.run_tesseract`, which needs the real tesseract binary.
   CI's "Backend tests" job (`.github/actions/test-backend/
   action.yml`) is a bare `ubuntu-latest` runner - `pip install -r
   requirements.txt` only, no Docker, no `apt-get tesseract-ocr` - so
   it never has the binary. This exact class of bug was already fixed
   once (commit `ddb6dce9`, "Fix CI: mock tesseract in tests") by
   establishing the convention that any test whose path reaches
   `run_tesseract` must `monkeypatch.setattr(local_ocr_module,
   "run_tesseract", lambda image: "<expected text>")` - stated as an
   explicit invariant in the test file's own module docstring. The 10
   failing tests were all added AFTER that fix, across three commits
   between 2026-07-15 and 2026-07-17 (`e6b09d14`, `3b2b5b7d`,
   `c7010bd8`), and simply didn't apply the established pattern - they
   pass locally (host venv and the `mpcautofill_django` Docker image
   both have tesseract baked in) but fail CI outright, silently, until
   now.

3. Fix: added the identical monkeypatch (`lambda image: ""`, matching
   every one of these 10 tests' blank/solid-fill fetched images - no
   text drawn on any of them, verified per-test) to all 10 failing
   tests in `MPCAutofill/cardpicker/tests/
   test_local_identify_printing_tags.py`. No production code touched -
   `local_ocr.py` and `local_fallback.py` are untouched (both are
   listed but not need to be modified; neither is PROTECTED CORE per
   the repo's PROTECTED CORE list, but the fix didn't require touching
   them regardless - it's test-only).

4. Updated `docs/troubleshooting.md`'s existing "TesseractNotFoundError"
   entry in place (edited, not appended) to: (a) explicitly distinguish
   "the Docker image has tesseract" from "CI's bare runner never does
   and never will unless the action changes" - the exact
   mental-model gap that let this recur silently; (b) record the
   recurrence (10 tests, 3 commits, 2026-07-15 to -17) and the
   generalized trigger condition (any test path reaching
   `local_ocr.run_tesseract`, directly or via `detect_illus_anchor`'s
   unconditional call whenever a fetched image is non-None) so the
   next new test in this file can check itself against this note
   before shipping. Ran `npx prettier@2.7.1 --check/--write` on the
   doc per this repo's own convention; clean before commit.

DEVIATIONS from spec: none. Moxfield/Google-Drive-secret failures (2a,
2b) were left alone exactly as instructed for "not yours to fix" cases
- reported, not worked around.

VERIFICATION:

- `python3 -m py_compile` on the edited test file: clean.
- `pytest --collect-only` inside a throwaway container built from the
  live `mpcautofill_django:latest` image (network `docker_default`,
  worktree's `MPCAutofill/` bind-mounted over the image's baked-in
  copy, container removed after): 145 tests collected, zero collection
  errors - confirms no syntax/import breakage from the edit.
- Full DB/ES-backed pytest run was NOT executed and is NOT claimed as
  verified. `conftest.py`'s `elasticsearch`/`postgres_container`
  fixtures are session-scoped `testcontainers`-backed (spin up their
  OWN sibling containers via the Docker socket) - the only way to run
  the real suite in this environment. Mounting the host Docker socket
  into a throwaway container was attempted and BLOCKED by the harness's
  auto-mode classifier as a sensitive action; I did not attempt to work
  around it. The alternative - repointing tests directly at the
  ALREADY-RUNNING production `mpcautofill_postgres`/`mpcautofill_
  elasticsearch` containers - was deliberately not attempted, since
  that risks writing to a live index/DB (explicitly disallowed by
  the repo's contributor guardrails), even though pytest-django's own
  `test_` -prefixed DB would likely have been safe; the ES side was
  the less certain half of that risk, so the whole path was skipped.
- In place of the full suite, directly reproduced the exact CI failure
  and the fix's effect, in isolation, inside that same throwaway
  container: called `local_fallback.detect_illus_anchor(blank_image,
  [], None)` with `pytesseract.pytesseract.tesseract_cmd` pointed at a
  nonexistent path (faithfully simulating CI's missing binary, since
  this container's real tesseract made the bug unreproducible
  as-is) - got the exact `TesseractNotFoundError` seen in the CI log.
  Re-ran the identical call with `local_ocr.run_tesseract` monkeypatched
  exactly as the 10 fixed tests now do - call succeeded, no exception.
  This directly proves the fix mechanism against the real production
  code path, without needing DB/ES.
- Explicitly NOT claiming: that all 10 tests' own assertions (vote
  counts, scan-log rows, cluster propagation, etc.) pass end-to-end -
  only that the tesseract crash is resolved and collection is clean.
  Recommend the owner (or CI itself, on push) confirm the full green
  run.

OPEN ITEMS / DECISIONS NEEDED:

1. Google Drive API key secret (`secrets.GOOGLE_DRIVE_API_KEY`) appears
   empty or invalid in this repo's GitHub Actions secrets - writes an
   empty `client_secrets.json`, breaking 2 tests every run for at
   least a week. Owner needs to check/rotate that secret; not
   something a session can fix.
2. Moxfield integration test makes a live network call in CI with no
   mock/cassette - genuinely flaky by design, independent of secrets.
   Worth a future decision: skip/mark xfail, or add a recorded fixture
   - flagging, not deciding, since it's a design choice.
3. This session's `gh` CLI (2.4.0, from 2022) doesn't support
   `--log-failed` cleanly on this repo - `gh api .../jobs/<id>/logs`
   worked as the fallback. Not urgent, but a `gh` upgrade would remove
   the need for that workaround next time.
4. Full pytest confirmation of the 10 fixed tests (not just the
   tesseract-crash portion) is still owed - either the owner runs it
   locally with real Docker-socket access, or the next CI run on this
   branch does it for free. Recommend just watching the next
   push/CI run rather than building special local infra for it.

LIVE STATE:

- Branch `worktree-agent-aea2752d83552fd91` pushed to origin, one
  commit (90860de3) ahead of the branch point. Not merged, no PR
  opened, per task instructions.
- Throwaway Docker container (`backend-test-verify-aea2752d`, from
  `mpcautofill_django:latest`, bind-mounted worktree code) was created
  for verification and REMOVED (`docker rm -f`) before this report -
  nothing left running.
- Could NOT add a row to `WORKERS.md` for this session: it's a
  gitignored, machine-local file that only exists in the main checkout
  (`/home/ubuntu/ProxyPrints.github.io/WORKERS.md`), not in this
  worktree, and the harness's edit-scope guard explicitly blocked
  writing to that main-checkout path from inside this worktree
  session ("Edit the worktree copy of this file instead"). No row was
  added anywhere. Table was empty (no other active sessions) when
  last read, so no coordination conflict resulted, but this is worth
  the owner's attention: the guard is doing exactly its job for
  git-tracked files, but WORKERS.md's whole design assumes one shared,
  editable-from-anywhere file, which this guard structurally prevents
  from a worktree. Flagging as tool-access signal per the task's ask.
- Guard/tool-access signal (all as asked, nothing pushed to master or
  merged for real):
  - `git push -u origin worktree-agent-aea2752d83552fd91` succeeded
    normally, as expected (own branch, not master).
  - `git push origin master` was never attempted for real. Read
    `.claude/hooks/guard_master.py` directly: it denies any `git push`
    whose target resolves to master (explicit token, or bare `git
    push`/`git push <remote>` while `HEAD` is `master`) when cwd is
    under `.claude/worktrees/` - which this session's cwd is - so it
    would have blocked it. `gh pr merge` is denied unconditionally by
    the same hook regardless of branch. Neither was invoked for real.
  - Editing `/home/ubuntu/ProxyPrints.github.io/WORKERS.md` (the
    main-checkout path, outside this worktree) WAS attempted for real
    (not a dry-run) and WAS blocked, with a clear, correctly-targeted
    error message pointing at the worktree copy instead - this is a
    different guard than `guard_master.py` (an edit-tool worktree-scope
    check), and it worked as intended.
  - Mounting `/var/run/docker.sock` into a throwaway container was
    attempted for real (for test verification, described above) and
    WAS blocked by the auto-mode permission classifier as a sensitive
    action. Not worked around.
```
