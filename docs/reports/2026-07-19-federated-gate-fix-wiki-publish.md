```
TASK: Two follow-ups queued after PR #123 (license provenance ledger)
merged — federated gate defensive fix + wiki-publish the upstreaming
docs — branch federated-gate-wiki-publish-followup-cvq14g — PR #129
(open, awaiting review)

WHAT SHIPPED:
1. FEDERATED GATE DEFENSIVE FIX — VoteSource.FEDERATED added to
   MPCAutofill/cardpicker/vote_consensus.py's _MACHINE_DERIVED_SOURCES,
   with a comment pointing at docs/federation-v1.md's
   FEDERATED_VOTE_GATE_MODE design as the eventual real, per-peer-
   promotable mechanism. is_human_backed_source(VoteSource.FEDERATED)
   now returns False (was True) — makes the safe behavior the default
   before any federation importer exists, per the owner's own framing.
   docs/federation-v1.md's "Known gate issue" section updated to record
   both the original bug and the current state (defensive fix shipped,
   real per-peer mechanism still design-only). Existing test
   test_user_admin_federated_are_human_backed asserted the old, buggy
   behavior — updated (split into test_user_admin_are_human_backed +
   a new test_federated_is_not_human_backed_by_default regression
   guard). The test class's own docstring, which incorrectly claimed
   FEDERATED was "human-backed by default," corrected too.
2. WIKI PUBLISH — .github/wiki-publish-map.json's "Understanding the
   system" group gained 4 entries: docs/upstreaming/readiness-audit.md
   (wiki: Readiness-Audit), license-provenance.md (License-Provenance),
   conventions.md (Upstreaming-Conventions), drift-log.md (Drift-Log).
   docs/upstreaming/drafts/ deliberately NOT added — draft PR
   descriptions, point-in-time content, same reasoning
   docs/proposals/reports/audits are already excluded from wiki
   publication for.

DEVIATIONS: none from the owner's instructions — both items folded into
one PR as directed.

VERIFICATION:
- docs_lint.py — clean.
- Real publish_wiki.py run (scratch dir): exit 0, all 4 new pages
  generated, zero link-resolution errors — spot-checked
  Readiness-Audit.md's own rendered output: GENERATED PAGE header
  correct, mermaid dependency-graph code fence intact, and a real
  in-repo markdown link (to license-provenance.md) correctly rewritten
  to the actual new wiki page name (License-Provenance), proving the
  link-rewrite machinery handles the new pages correctly end to end.
- publish_wiki.py's 4 link-rewrite tests and publish_readme.py's 8
  tests — unaffected, still pass.
- check_protected_core_license.py — still clean, 9 files, 0 findings
  (vote_consensus.py is itself a protected-core file; the new comment
  citing federation-v1.md carries no AGPL marker).
- black 22.8.0 / isort 5.12.0 / ruff 0.0.257 — clean on all touched
  Python. prettier 2.7.1 — clean on touched JSON/markdown.
- The exact _MACHINE_DERIVED_SOURCES set-membership fix was verified
  in ISOLATION (a standalone Python reproduction of the same logic,
  outside Django) — all 5 assertions pass (DEDUCTION/OCR/FEDERATED
  False, USER/ADMIN True).

DEFERRED, stated plainly rather than glossed over: the real Django
pytest suite for MPCAutofill/cardpicker/tests/test_vote_consensus.py
could NOT run in this sandbox. No Postgres/ES/Docker available (per
this repo's own standing cloud-session constraint), and
`pip install -r requirements.txt` fails building `ratelimit`'s legacy
setup.py under Python 3.13 (an environment-specific build failure, not
a code issue). This is the same documented limitation
docs/upstreaming/readiness-audit.md's own Phase 2 status note already
recorded for upstream-feat-local-file-source's test coverage. The
isolated logic check above and static analysis (black/isort/ruff) are
what actually ran; the real pytest run — including
TestFederatedModelFields's db-fixture-dependent tests, which need a
real database and were NOT exercised at all — should happen in CI or a
real dev environment before this PR merges.

OPEN ITEMS / DECISIONS NEEDED:
1. The real pytest run (deferred above) should be confirmed green
   before merge — this session could not run it.
2. Wiki page naming: "Readiness-Audit" / "License-Provenance" /
   "Upstreaming-Conventions" / "Drift-Log" chosen for consistency with
   existing names (Vote-System, Upstream-Wiki-Drift) — flag if
   different names are preferred (wiki URLs have no redirects, so
   correcting a name later abandons the old URL).

LIVE STATE: branch federated-gate-wiki-publish-followup-cvq14g pushed
to origin, PR #129 open against master, unmerged, awaiting review and
(critically) a real CI/pytest run this session couldn't perform
locally. This report committed to report-relay-cvq14g and pushed.
```
