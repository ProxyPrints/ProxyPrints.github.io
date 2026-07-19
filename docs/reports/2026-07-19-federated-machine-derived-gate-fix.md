# 2026-07-19 — FEDERATED machine-derived gate fix (PR #127)

```
TASK: Defensive fix for the federation consensus-gate finding.
Branch claude/federated-machine-derived-gate-fix, commit 1544136e,
PR #127 (open, unmerged). Owner instruction: "small follow-up after
PR #123 merges (queue behind pipeline work, not urgent but cheap):
defensive fix for the federation gate finding - add
VoteSource.FEDERATED to _MACHINE_DERIVED_SOURCES in
vote_consensus.py NOW, with a comment pointing at
federation-v1.md's FEDERATED_VOTE_GATE_MODE design as the eventual
real mechanism. One line + one test asserting
is_human_backed_source(FEDERATED) is False. This makes the safe
behavior the DEFAULT before any importer can exist, rather than a
thing the future importer must remember."

WHAT SHIPPED:
1. MPCAutofill/cardpicker/vote_consensus.py: added
   VoteSource.FEDERATED to _MACHINE_DERIVED_SOURCES (was
   {DEDUCTION, OCR}, now {DEDUCTION, OCR, FEDERATED}), with a
   comment explaining this is a defensive default ahead of any real
   importer and pointing at docs/federation-v1.md's
   FEDERATED_VOTE_GATE_MODE section for the eventual per-peer-
   promotable mechanism. Since all three consensus wrappers
   (printing_consensus.py, artist_consensus.py, tag_consensus.py)
   already call is_human_backed_source(vote.source) against this
   one shared set, this single line closes the gap everywhere at
   once - no per-wrapper changes needed.
2. MPCAutofill/cardpicker/tests/test_vote_consensus.py:
   TestIsHumanBackedSource updated. Before this fix,
   test_user_admin_federated_are_human_backed asserted
   is_human_backed_source(VoteSource.FEDERATED) is True - i.e. the
   test suite was actively encoding the gap as intended behavior.
   Now split into test_deduction_ocr_and_federated_are_not_human_backed
   (includes the FEDERATED assertion, now False) and
   test_user_and_admin_are_human_backed (USER/ADMIN only). Class
   docstring updated to match.

DEVIATIONS from spec: none - one line in vote_consensus.py, one
test assertion moved + flipped, comment pointing at
FEDERATED_VOTE_GATE_MODE as specified.

VERIFICATION:
- Confirmed the described gap was real before fixing: VoteSource.FEDERATED
  already existed in models.py, settings.VOTE_FEDERATED_WEIGHT already
  wired into _SOURCE_WEIGHTS, and the pre-existing test asserted FEDERATED
  read as human-backed - all three consensus wrappers call
  is_human_backed_source(vote.source) directly, so the gap was live in
  the actual resolution path, not just theoretical.
- This cloud sandbox has no Docker. The full pytest suite's
  elasticsearch fixture is session-scoped AND autouse=True on every
  test in the conftest, including ones with no DB dependency, so
  `pytest cardpicker/tests/test_vote_consensus.py` fails outright
  here with a docker.errors.DockerException before any test body
  runs - a pre-existing sandbox limitation (see docs/lessons.md's
  existing "Ad hoc prod DB/ES access" and "Cloud sandboxes can't
  reach the live site" entries for the same class of constraint),
  not something this diff caused.
- Verified instead with a standalone script (not pytest) that runs
  django.setup() directly and calls is_human_backed_source /
  _MACHINE_DERIVED_SOURCES without going through the ES-dependent
  fixture chain: confirmed VoteSource.FEDERATED in
  _MACHINE_DERIVED_SOURCES, and all 5 assertions from the updated
  test class (DEDUCTION/OCR/FEDERATED -> False, USER/ADMIN -> True)
  pass.
- black/isort/ruff: clean on both touched files.
- mypy: pre-existing, unrelated errors from a fresh venv's
  factory_boy type-stub gap (factories.py and TestFederatedModelFields,
  neither touched by this diff) - confirmed via git diff --stat that
  neither error-producing line is part of this change. Per
  docs/lessons.md's existing "trust CI history, not a matching local
  venv" entry, CI is authoritative for the full mypy/pytest run, not
  this sandbox's fresh venv.
- Per the just-added lessons.md verification-scope entry: git status
  --short confirmed clean on claude/federated-machine-derived-gate-fix
  immediately after the commit, before this report was written - the
  verification above is against the actual pushed commit 1544136e.

OPEN ITEMS / DECISIONS NEEDED:
1. PR #127 awaits the owner's merge call, same as the other open
   PRs (#118, #120).
2. The owner's instruction said "after PR #123 merges" but also
   "NOW" - PR #123 is still open (unmerged) as of this task. Read
   "NOW" as the operative instruction since this fix is orthogonal
   to PR #123's own content (a license-provenance audit, doesn't
   touch vote_consensus.py) and shipped without waiting. Flagging
   this reading in case "after #123 merges" was meant as a hard
   gate rather than sequencing color - if so, this PR's merge should
   simply wait behind #123's, no code change needed either way.
3. Full pytest verification (the ES-fixture-gated suite) was not run
   in this sandbox - deferred to CI, standard for this cloud-session
   environment.

LIVE STATE: branch claude/federated-machine-derived-gate-fix pushed
to origin, PR #127 open. Branch report-relay-6121bf36-10 pushed to
origin with this report. Temporary venv at /tmp/mpc_venv used for
local verification - not committed, not part of the repo. No dev
servers or background processes left running. Working tree clean.
```
