```
TASK: Federation design doc update — branch
`claude/upstream-readiness-audit-cvq14g`, commit `ca40919d`, pushed.
Doc-only, no code changed, as specified. Nothing touches upstream.

WHAT SHIPPED, per the three items:
1. `docs/federation-v1.md` gained a "Participation modes" section:
   SUBSCRIBER (read-only, zero trust config, zero Sybil surface),
   PUBLISHER (emits, requires the full vote/consensus/human-gate
   stack), FULL PEER (both, not a v1 target). States explicitly: v1
   launch posture for ProxyPrints is publisher-only (emit, consume
   nothing — zero catalog-integrity risk since nothing a peer
   publishes can reach our tables), and expected onboarding for any
   new participant is subscriber-first.
2. A "Consumer component — the upstream-shaped chunk" subsection
   under Participation modes: the subscriber half (verdict table on
   content_hash, phash tooling, signature verification, agreement
   badge) is dependency-free — no vote system needed — and is the
   only plausibly upstream-shaped piece of the federation program.
   Added as a new Tier 6 on `readiness-audit.md`'s ladder ("blocked
   on a precondition that doesn't exist yet" — a live peer, not a
   size/risk problem), distinct from Tier 5's too-large/risky framing.
3. A "Known gate issue (tracked, not built)" section: documents that
   `VoteSource.FEDERATED` is excluded from
   `vote_consensus.py`'s `_MACHINE_DERIVED_SOURCES` set, so
   `is_human_backed_source(FEDERATED)` returns `True` today - verified
   directly against current code (`vote_consensus.py:31`), not just
   asserted. Design fix: `FEDERATED_VOTE_GATE_MODE` setting (default
   suggestion-tier, not gate-clearing), promotable per-peer via
   Dawid-Skene reliability estimation, mirroring Proposal G's
   `AUTHED_VOTE_GATE_MODE` idiom. Flagged only - nothing built,
   per instruction.

DEVIATIONS from spec, each with reasoning:
- Verified two claims against real sources before writing them into a
  design doc, rather than transcribing the request verbatim: (a) the
  gate-issue claim, confirmed against `vote_consensus.py`'s actual
  `_MACHINE_DERIVED_SOURCES` set and `is_human_backed_source()`
  implementation — accurate as described; (b) "Proposal G's
  AUTHED_VOTE_GATE_MODE pattern" — this doesn't exist anywhere in
  `docs/` on any branch this session had already touched; found it on
  `claude/user-accounts-saved-decks-m8eyf5` (a different, unmerged
  session's work) and read the actual pattern (env flag +
  `AUTHED_VOTE_GATE_MODE`/`AUTHED_VOTE_WEIGHT`, `authed_vote_weight()`
  helper, "config not migration" shape) before citing it, rather than
  guessing at what it might say. Cited its real location and unmerged
  status explicitly in the doc so a reader knows that precedent could
  still shift.
- Placed "Known gate issue" after "Import rules" (gate/weight-adjacent
  content) and "Consumer component" right after "Participation modes"
  (role-adjacent content) rather than both at the document's end —
  judged this reads better than a flat append, without changing any
  existing section's content.

VERIFICATION: what ran with results —
- `is_human_backed_source(VoteSource.FEDERATED)` claim: confirmed via
  direct `grep`/`Read` of `MPCAutofill/cardpicker/vote_consensus.py`
  on current `origin/master` — `_MACHINE_DERIVED_SOURCES = {DEDUCTION,
  OCR}`, `FEDERATED` absent, function returns `source not in
  _MACHINE_DERIVED_SOURCES`. Matches the task's claim exactly.
- `AUTHED_VOTE_GATE_MODE` claim: confirmed via
  `git grep`/`git show` across all `origin/*` branches — real content
  on `claude/user-accounts-saved-decks-m8eyf5`'s
  `docs/proposals/proposal-g-user-accounts-saved-decks.md` §7-9, not
  fabricated, not yet merged.
- `VOTE_FEDERATED_WEIGHT` default (1.0) and the Dawid-Skene framing in
  `docs/theory.md` cross-checked directly rather than assumed from the
  task description alone.
- `git diff --stat`: exactly the two doc files, +107/-0, no code
  touched — confirms the "doc-only, no code" constraint held.

OPEN ITEMS / DECISIONS NEEDED: none new. Standing items from prior
reports (frontend-direction answer gating Phase 2; `origin`-side
secrets for the CI workflows) are unchanged and not repeated here.

LIVE STATE: `claude/upstream-readiness-audit-cvq14g` pushed to
`origin` at `ca40919d`. No PR opened. No code changes anywhere this
turn. Lane returns to dormant per the instruction ("stays doc-only
until a peer exists").
```
