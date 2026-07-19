```
TASK: Ledger commission — license provenance + protected core (owner
amendment to the extraction ladder, HOLD) — branch
claude/upstream-readiness-audit-cvq14g — PR #123 (open, awaiting review)

WHAT SHIPPED:
1. PROVENANCE COLUMN — added to all 41 rows across
   docs/upstreaming/readiness-audit.md's three decomposition tables
   (11 backend + 20 frontend + 10 CI/tooling — not the 27 the commission
   estimated; stated plainly rather than force-fit to match). Uniform as
   expected (own-work / upstream-GPL3), with exactly one flagged
   exception: IV.5's vendored flag icons, already a known finding, not
   new.
2. PROVENANCE AUDIT — one-time sweep of the WHOLE repo (not just the 41
   ladder rows): MPCAutofill/, frontend/, schemas/, image-cdn/,
   desktop-tool/, cloudflare-static-site/, github-release-reverse-proxy/,
   docker/, .github/. NOT "expected clean, confirmed clean" — found 4
   real external-origin items, 2 missing full license-notice compliance:
   - frontend/src/components/flags.tsx + 3 SVGs: lipis/flag-icons, MIT
     (already the ladder's own IV.5 finding).
   - frontend/src/components/RenderIfVisible.tsx: vendored from
     NightCafeStudio/react-render-if-visible. A sub-pass first assumed
     MIT without checking — WRONG, caught and corrected in this same
     task: verified directly against GitHub's own license metadata, it's
     actually Apache License 2.0.
   - frontend/src/components/OverflowList.tsx: mattrothenberg/
     react-overflow-list, verified MIT.
   - MPCAutofill/cardpicker/local_pilot_data/keyrune/: keyrune npm
     package's font+codepoints, vendored for server-side OCR/phash.
     Already fully compliant (a complete LICENSE.md checked in
     alongside) — the one pre-existing positive precedent, cited as the
     absorption protocol's own template.
   Full findings + swept-clean scope in
   docs/upstreaming/license-provenance.md §1.
3. PROTECTED CORE — exact file list (9 files: vote_consensus.py,
   printing_consensus.py, tag_consensus.py, artist_consensus.py,
   local_phash.py, local_fallback.py, federation-hash-tool/
   hash_my_cards.py + its test, test_federation_hash_tool_parity.py) in
   license-provenance.md §2. Real, tested CI lint shipped:
   .github/scripts/check_protected_core_license.py — fails if a
   protected-core file imports (or is itself marked) AGPL via a
   `# PROVENANCE:` header comment. Wired into docs-lint.yml as a new
   `protected-core-license` job. Passes today, 0 findings, correctly —
   nothing in this repo is AGPL-marked; it exists to catch the day that
   changes. CORRECTION to the commission's own framing: it said
   protected-core files "MUST remain GPL-3-clean" — that's wrong for
   federation-hash-tool/hash_my_cards.py specifically, which is
   deliberately MIT (already decided, docs/federation/public-export-v1.md
   §5, a distinct choice from the rest of the GPL-3.0 repo so third-party
   consumers can use it without copyleft attaching). The real, corrected
   invariant the CI lint enforces: "no AGPL-derived code," not
   "everything must be GPL-3" — AGPL would poison either license, not
   just the copyleft one.
4. ABSORPTION PROTOCOL — written (license-provenance.md §3): bounded
   module, verbatim license header, PROVENANCE comment, ledger row,
   NOTICE entry. PROTECTED CORE is explicitly exempt from ever receiving
   external code this way — patterns only, reimplement from a written
   description, never from the source file.
5. DISCLOSURE MECHANICS:
   - README source-region: BUILT. A new `license-provenance`
     README-REGION in docs/readme-sections.md, wired into the EXISTING
     readme emit mode (publish_readme.py, shipped earlier today as PR
     #119) — no new machinery needed, the pipeline already did this job.
     readme.md's License section now reads "GPL-3.0. Complete
     corresponding source: this repository. Third-party-derived modules
     are listed in NOTICE."
   - NOTICE file: BUILT. New root NOTICE consolidating full, compliant
     attribution (copyright + complete license text) for all 3
     incompletely-attributed sweep findings, closing the real gaps §1
     found; points to keyrune's own already-complete LICENSE.md rather
     than duplicating it.
   - Site footer link: NOT built here — explicitly routed to the
     frontend lane per the commission's own instruction. This cloud
     session has no direct channel to that parallel session (the same
     constraint that made an earlier, unrelated misdirected task
     un-actionable this session). Queued as an addressable deliverable
     in license-provenance.md §4.3 for whoever picks it up next.
6. CLAUDE.md CONVENTION LINE — added to the Tooling rules section:
   external code enters only via the absorption protocol; protected core
   accepts patterns, never code; default posture is patterns-yes/
   code-case-by-case-with-owner-sign-off.

DEVIATIONS:
1. Branch handling: the designated branch
   (claude/upstream-readiness-audit-cvq14g) was 70 commits behind master
   when this task started — this is the actual branch the "extractable-
   primitives ledger" lives on (docs/upstreaming/readiness-audit.md's own
   ladder), discovered by tracing the commission's references through
   federation/public-export-v1.md §8 back to this branch, not assumed.
   Merged current master into it first (3 real conflicts: CLAUDE.md,
   docs/federation-v1.md, docs/infrastructure.md) rather than rebasing,
   to avoid rewriting already-pushed history on a branch with no PR
   protecting it. One of the three conflicts (an AUTHED_VOTE_GATE_MODE
   reference) had gone stale on BOTH sides — resolved with the actual
   current state (that setting is now genuinely shipped, not still a
   HOLD spec as either side's conflicting text claimed), verified
   directly against the real proposal-g doc rather than picking either
   stale side.
2. Row count: 41 ladder rows classified, not the 27 the commission
   estimated. Reported honestly rather than force-fit.
3. models.py is explicitly NOT on the mechanical protected-core file
   list, despite holding the VoteSource/AbstractWeightedVote/
   CanonicalPrintingMetadata/CardPrintingTag class definitions — it also
   holds dozens of unrelated models, and a file-level import lint against
   it would either miss real violations or false-positive constantly.
   Documented as a manual-review item instead, matching docs_lint.py's
   own established "narrow v1, no heavyweight AST library" precedent.
4. Opened as a real PR (#123) rather than pushing without one, per the
   owner's own mid-task follow-up ("open the PR — ship as one reviewable
   unit").

VERIFICATION: docs_lint.py clean. publish_readme.py: idempotent (2
consecutive runs byte-identical), its own 8 unit/parity tests pass
(including the new license-provenance region), real build matches
committed readme.md. publish_wiki.py's 4 tests unaffected; real wiki
publish (scratch dir) still exits 0 with the new marker comments present
in wiki-home-intro.md. check_protected_core_license.py: 10 unit tests
pass, INCLUDING a real deliberate-violation fixture (a fake AGPL-marked
local import actually trips the lint, not just "passes against the real
repo, trust us"); real repo check: 9 files, 0 findings. black 22.8.0 /
isort 5.12.0 / ruff 0.0.257 clean on all new/touched Python. prettier
2.7.1 clean on every touched markdown/YAML file. Deferred: no live CI run
yet (the new protected-core-license and readme-parity-affecting changes
haven't executed in GitHub Actions — first real run happens when PR
#123's checks fire).

OPEN ITEMS / DECISIONS NEEDED (mirrored from license-provenance.md §5):
1. Are the two incomplete-attribution findings (RenderIfVisible.tsx,
   OverflowList.tsx) adequately closed by the new NOTICE file, or should
   the individual source files also get expanded inline comments
   (belt-and-suspenders, not required by either license)?
2. Is the models.py manual-review-item treatment (§2, above) acceptable,
   or is a real per-symbol check worth building?
3. Confirm the corrected invariant ("no AGPL-derived code, whatever the
   file's own license is" — not "everything must be GPL-3") is the
   intended protected-core policy, given the hash tool's deliberate MIT
   licensing.
4. Who picks up the site footer link — the frontend lane directly, or
   should it route back to this session instead?
5. Does the 41-vs-27 row-count discrepancy matter going forward, or is it
   just a number worth having correct?

LIVE STATE: branch claude/upstream-readiness-audit-cvq14g pushed to
origin (fast-forward, no force needed — no collision with any concurrent
push). PR #123 open against master, unmerged, awaiting owner review — CI
(docs-lint.yml, including the two new jobs) will run automatically on the
PR. This report committed to report-relay-cvq14g and pushed.
```
