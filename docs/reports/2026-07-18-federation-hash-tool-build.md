```
TASK: Federation export BUILD, client-side half — PR #97
(https://github.com/ProxyPrints/ProxyPrints.github.io/pull/97),
branch `federation-hash-tool-build`, commit `ae285804`. Plus two
follow-up commits on PR #92's branch
(https://github.com/ProxyPrints/ProxyPrints.github.io/pull/92):
`3e2d91e0` (spec correction) and `ca0b444b` (cross-link update),
final commit `ca0b444b`. No PR against upstream, nothing coordinated
with the server-side build.

WHAT SHIPPED:
1. `federation-hash-tool/` — standalone, MIT-licensed, Django-free
   (Pillow + imagehash only) reference implementation of the
   content_phash recipe: `hash_my_cards.py` (CLI: hash a folder,
   optional `--export-url` to fetch a published export and report
   matches within the spec's own distance threshold), `readme.md`
   (install/usage/recipe summary/minisign verification one-liner/
   license), `requirements.txt`, 23 unit tests.
2. A real, material correction to the spec (PR #92, commit
   `3e2d91e0`): §2's original recipe omitted the bleed-vs-trimmed
   image classification step the actual backend
   (`compute_content_phash_for_card`) performs before cropping —
   found while implementing against the real call chain, not assumed
   correct because the section had already gone through owner review.
   Fixed the spec doc itself, then built the tool to match the
   corrected recipe.
3. A permanent CI regression test
   (`MPCAutofill/cardpicker/tests/test_federation_hash_tool_parity.py`),
   added mid-build per an explicit follow-up instruction: the tool is
   now an external contract, so a future backend phash-recipe change
   should fail CI with a decision attached (version the recipe or fix
   the drift), not silently break every consumer's joins. Imports the
   tool via `sys.path` (not a package dependency) specifically to keep
   the tool itself Django-free — the coupling only exists in the
   direction that makes sense (backend tests depend on the tool, not
   vice versa).
4. Repo tooling wiring: `.pre-commit-config.yaml`'s mypy hook gained
   `federation-hash-tool/` in its checked paths; `mypy.ini`'s
   test-exclude pattern gained `federation-hash-tool/tests/` (matching
   `desktop-tool/tests/`'s existing treatment — avoids a `tests`
   module-name collision between the two sibling standalone-tool
   directories, both of which define a top-level `tests` package).
5. Cross-link update (PR #92, commit `ca0b444b`): §2's "Reference
   implementation" section updated from "not built here" to point at
   the now-existing PR #97.

DEVIATIONS from spec, each with reasoning:
- Fixed §2 on the *already-open* PR #92 branch rather than treating it
  as a separate, brand-new correction PR — it's the same spec that PR
  already owns, and PR #92 hadn't merged yet (checked directly, not
  assumed), so there was a live branch to fix rather than a merged doc
  to patch separately.
- Added the permanent parity test to the backend's own test suite
  (`MPCAutofill/cardpicker/tests/`), not the tool's own `tests/`
  directory — the tool's design goal (stated in its own docstring) is
  staying dependency-free of Django; a test that imports Django backend
  code belongs on the side that already has that dependency, protecting
  the contract from the side most likely to accidentally break it.
- Caught and fixed a real bug in my own first draft of that test before
  it could be committed: an initial pass converted the backend's
  int-encoded hash to its hex form via a needless
  int→decimal-string→int→hex round trip, and used a dead-import hack to
  silence an unused-import warning that was never actually going to
  fire. Rewrote it cleanly (direct int→hex conversion, no unused
  imports at all) — caught by rereading the diff before committing, not
  shipped and found later.
- Caught and fixed a real bug in the tool's own test suite too, before
  first commit: `test_trimmed_and_bleed_versions_of_the_same_art_converge`
  originally used hand-guessed pixel crop margins to simulate a
  trimmed-vs-bleed image pair, and genuinely failed (22 bits apart, not
  a flake) because the guessed margins didn't match the real
  bleed-margin fraction constants. Fixed by computing the margins from
  the module's own `_WIDTH_MARGIN_FRACTION`/`_HEIGHT_MARGIN_FRACTION`
  constants instead of guessing.

VERIFICATION: what ran, with results —
- **Byte-for-byte parity against the real backend**, checked directly:
  built a throwaway venv with the actual Django app loaded (`SECRET_KEY`
  + `DJANGO_SETTINGS_MODULE` env vars, same technique used earlier this
  session for the local-file-source extraction — this sandbox has no
  live backend to test against otherwise) and ran both implementations
  against 5 synthetic images spanning every `classify_bleed_edge`
  branch (bleed, trimmed, ambiguous, plus a large-bleed size variant) —
  identical hash output on all 5.
- **The permanent parity test itself**, executed directly (bypassing
  `pytest-django`'s Docker-gated session — confirmed again this run
  that even DB/ES-independent tests can't be collected without it, same
  finding as the local-file-source extraction): all 4 tests
  (`test_art_crop_box_constant_matches`,
  `test_classify_bleed_edge_matches_on_every_fixture`,
  `test_normalize_crop_box_matches_on_every_bleed_classification`,
  `test_full_hash_matches_on_every_fixture_image`) pass against the
  real backend code, run as actual class-instance method calls, not
  just eyeballed logic.
- `ruff` (`v0.0.257`), `black` (`22.8.0`), `isort` (`5.12.0`,
  `--profile black`) run directly against every new/changed Python
  file with the exact pinned versions from `.pre-commit-config.yaml` —
  clean.
- `mypy` (`v1.7.0`) run against `desktop-tool/ MPCAutofill/
  federation-hash-tool/` together (matching the real hook's exact
  invocation) in a venv built from the pinned
  `MPCAutofill/requirements.txt` — 0 issues across all 165 checked
  source files. (Note: an earlier ad-hoc venv with piecemeal-installed
  dependency versions showed 7 pre-existing unrelated errors during
  this same session's local-file-source work; this run's
  requirements.txt-pinned venv shows none, which is the more
  trustworthy result — the earlier ones were an artifact of my own
  inconsistent dependency resolution, not real repo state. Noting the
  discrepancy rather than silently picking whichever result was more
  convenient.)
- `federation-hash-tool`'s own test suite: 23/23 pass (`pytest
  tests/`), including the corrected precision test above.
- `python3 .github/scripts/docs_lint.py`: clean, re-run after every doc
  edit on the PR #92 branch, not just once at the end.
- Manually ran the CLI against a real temp folder of synthetic images —
  confirmed correct hash output, `--json`, and `--threshold` behavior
  by hand, not just via the unit tests.

OPEN ITEMS / DECISIONS NEEDED:
1. Owner/merge queue: PR #97 (the tool) is ready. PR #92 (the spec) has
   two new commits since it was last marked ready — still ready, just
   with the corrected recipe and the new cross-link; no new open
   decisions on that PR.
2. Server-side build (management command, signing, cron, publish)
   remains queued behind Part 4 + the cluster-consistency pre-flight,
   per the owner's own sequencing — nothing in this task changes that
   queue or requires anything from it. `federation-hash-tool/` has
   nothing real to join against (`--export-url`) until that lands, but
   works standalone (hashing a folder with no export) right now.

LIVE STATE: PR #97 open (tool + permanent parity test), PR #92 open
with 2 new commits (spec correction + cross-link), both against this
fork's own `master`, neither merged by this session. No code touches
upstream. `upstream-feat-local-file-source` and the upstream-ladder CI
workflows remain separately unmerged and unchanged. Session holding.
```
