```
TASK: Public Federation Export v1 spec — HOLD, PR #92
(https://github.com/ProxyPrints/ProxyPrints.github.io/pull/92) on
branch `federation-public-export-v1-spec`, commit `a6fddad8`. No PR
opened against upstream. Nothing built.

DELIVERY NOTE: this report uses a session-unique relay branch
(`report-relay-cvq14g`) per the retired-bare-`report-relay` lesson in
`docs/lessons.md` ("Cross-session branch-name collisions on a
'standing convention' name") — discovered mid-session that my own
prior reports had landed on the shared bare `report-relay` branch
alongside an unrelated session's commits, exactly the collision that
lesson now documents. Adopting the corrected convention from here on.

WHAT SHIPPED, per the seven spec sections requested:
1. `docs/federation/public-export-v1.md` — full HOLD spec. §1: draft
   verdict record shape (content_phash, printing IDs in both the
   mpc-autofill family's set+collector AND the MIT-lineage's
   scryfall_id, resolved attribute conclusions, basis/vote-weight
   provenance, per-record version), never images, human-confirmed-only.
2. §2: the exact content_phash recipe transcribed from
   MPCAutofill/cardpicker/local_phash.py (current code, not memory) —
   art-crop-box fractions, imagehash.phash hash_size=8, distance
   threshold 20/margin 5 with the real tuning methodology preserved
   (26-card sample, stated as such, not oversold as exhaustive) — plus
   a precise specification (not code, per HOLD status) for a standalone
   MIT-licensed reference hashing tool.
3. §3: ed25519 via minisign, recommended over ssh-keygen -Y with
   reasoning (external-consumer UX, not cryptographic).
4. §4: R2 recommended over GitHub Pages with reasoning (reuses existing
   image-cdn infra, zero-egress fits unknown external consumer
   patterns); versioned JSONL, full snapshot + dated increments;
   regeneration follows this fork's existing run_id/ledger/dry-run-
   default conventions rather than inventing new automation shape.
5. §5: CC0 vs. ODbL license options, one paragraph each on consequences
   for both named consumer ecosystems specifically — flagged as an
   explicit owner decision, not chosen in the doc.
6. §6: two concrete consumer stories (sibling mpc-autofill fork
   importing as suggestions into its own gate; MIT-lineage client tool
   auto-suggesting printing+bleed via phash/scryfall_id join).
7. §7: explicit no-subscriber/no-peer-trust/no-ingestion statement,
   unchanged from federation-v1.md's existing publisher-only posture.

DEVIATIONS from spec, each with reasoning:
- Corrected the task's own framing rather than transcribing it:
  `alex-taxiera/proxy-print` is AGPL-3.0, not MIT — verified by
  fetching the actual GitHub repo (license metadata) and its README
  directly. `acoreyj/proxies-at-home` is confirmed MIT. Both are named
  in the doc; only one is actually MIT-licensed, stated plainly in §6b
  rather than quietly writing both as "the MIT projects."
- Folded forward the `docs/federation-v1.md` Participation-modes/
  Known-gate-issue content (commit `ca40919d`, previously only on the
  sibling `claude/upstream-readiness-audit-cvq14g` branch — not yet on
  `master`) into this PR, since the new spec's entire premise
  ("v1 posture: publisher-only") depends on it and a reviewer of just
  this PR needs it present to make sense of the doc. Did NOT fold
  forward that branch's `docs/upstreaming/readiness-audit.md` edits
  (same source commit, different file) — that's unrelated upstream-
  ladder content, out of scope for a federation-specific PR; every
  reference to that doc was instead reworded to avoid a broken link
  (see next item) while it stays on its own branch.
- No reference implementation code shipped, per HOLD status — §2 is a
  precise specification (interface, dependencies, exact algorithm) a
  future build can follow mechanically, not a working script. The task's
  own closing line ("Build... begins on owner approval") reads
  "reference implementation" in §2 as part of that build gate, not an
  exception to it.
- Discovered this new spec's cross-references to
  `docs/upstreaming/readiness-audit.md` would be broken links on
  `master` (that doc doesn't exist there — still on a separate unmerged
  branch) - not caught by assumption, caught by actually running
  `.github/scripts/docs_lint.py` locally. Reworded every such reference
  to plain prose describing the sibling-branch status rather than a
  path-shaped backtick reference, re-ran the lint to confirm clean.
- Added `docs/README.md` "Plans & proposals" table entry and matching
  `CLAUDE.md` flat-index entry, per `docs/documentation-process.md`'s
  now-standing parity requirement between the two indexes (a
  convention that didn't exist when this session started - discovered
  it mid-task after `master` moved substantially since the last check).

VERIFICATION: what ran, with results —
- `python3 .github/scripts/docs_lint.py` — clean (0 findings) after
  fixes; 1 real finding caught and fixed before that (an illustrative
  future file path written as a path-shaped backtick reference,
  reworded to plain prose).
- Fetched `acoreyj/proxies-at-home` and `alex-taxiera/proxy-print`
  directly (WebFetch, GitHub repo page + raw README) rather than
  trusting the task's "MIT proxy-tool lineage" framing — one confirmed
  MIT, one corrected to AGPL-3.0.
- Read `MPCAutofill/cardpicker/local_phash.py`'s actual current source
  for the content_phash recipe (crop box, hash_size, thresholds,
  including its own tuning-methodology comments) rather than
  reconstructing from `docs/federation-v1.md`'s older, less precise
  mention of "imagehash.phash, hash_size=8, 64-bit."
- `git apply --check` + real apply of just the federation-v1.md hunk
  from commit `ca40919d` (not the whole commit, which also touched an
  unrelated file this PR doesn't include) — applied clean, verified by
  reading the resulting file, not assumed correct from the patch alone.
- `git status --short` / `git diff --cached --stat` before commit —
  confirmed the diff is exactly what was intended (4 files, no stray
  changes).

OPEN ITEMS / DECISIONS NEEDED:
1. Owner: review PR #92, the whole point of the HOLD. Two specific
   open sub-decisions flagged inline in the spec itself, not just this
   report: (a) §1's record-shape question (one record per observed
   image vs. one record per printing with an array of known hashes),
   (b) §5's CC0-vs-ODbL license choice.
2. Owner/next session: once this PR and
   `claude/upstream-readiness-audit-cvq14g` both eventually merge,
   `docs/federation/public-export-v1.md`'s reworded cross-references to
   the upstream-readiness audit doc could be tightened back into real
   links — not urgent, current prose is accurate either way, just less
   directly clickable than a real link would be.
3. Standing note, not specific to this task: `report-relay` (bare) is
   retired per `docs/lessons.md`; this and all future reports from this
   session use `report-relay-cvq14g` going forward.

LIVE STATE: PR #92 open against `ProxyPrints/ProxyPrints.github.io`
`master` (this fork, not upstream), branch
`federation-public-export-v1-spec` at `a6fddad8`. Nothing merged, no
code changed, nothing built. `claude/upstream-readiness-audit-cvq14g`
and `upstream-feat-local-file-source` branches unchanged, still
awaiting their own separate owner decisions. Session holding on PR #92
review.
```
