```
TASK: Terminology correction, "AI" -> "machine" for OCR/phash/deduction
vote sources (owner-directed accuracy fix). Branch
claude/ai-to-machine-terminology, commit ae5c0b28, pushed to origin.
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/76 (open,
base master).

WHAT SHIPPED, per the four numbered items:

1. **docs/theory.md**: SS4's "AI weight 0.5 by default" -> "machine weight
   0.5 by default". The Dawid-Skene paragraph keeps the literal
   `PRINTING_TAG_AI_WEIGHT` name where it cites code, glossed exactly per
   spec ("a legacy name — it weights machine-derived sources: OCR and
   deduction; no generative AI is involved"), plus one added clause noting
   the actual rename below (`PRINTING_TAG_MACHINE_WEIGHT`, old name kept
   as a backward-compatible env fallback) so the doc stays accurate given
   item 3 was also done. Swept the rest of the file: no other bare "AI"
   framing found.

2. **Frontend grep** (`grep -rn "\bAI\b" frontend/src`, all `.ts`/`.tsx`,
   real files not test/spec):
   - `frontend/src/pages/whatsthat.tsx:95` — **changed**. Real user-facing
     copy on the live `/whatsthat` page's intro paragraph: "contested and
     AI-suggested cards come first" -> "contested and machine-suggested
     cards come first". This is the occurrence the owner reported seeing
     on the site.
   - `frontend/src/features/questionFeed/QuestionFeed.tsx:546` —
     **changed**, for consistency. A code comment (not user-facing)
     describing the same headline logic the fixed string above sits next
     to: "an unresolved AI-suggested printing" -> "an unresolved
     machine-suggested printing".
   - `frontend/src/mocks/handlers.ts:590` — **checked, left alone,
     flagged rather than guessed**: `["ai-art", "AI art"]`. Verified
     against `MPCAutofill/cardpicker/reason_tags.py:36`
     (`("ai-art", "AI-generated artwork", "AI art")`) — this is a real,
     seeded backend tag meaning literally "this card's artwork was
     AI-generated" (a genuine Magic-proxy attribute, alongside
     `custom-art`/`upscaled`), completely unrelated to the vote-source
     "machine vote" terminology this task is about. Not touched.
   - New vocabulary matches the already-established house term: confirmed
     `AttributeChipPanel.tsx`'s existing "Community + machine votes lean
     {direction}..." tooltip copy (from #64) as the precedent both fixes
     now align with.

3. **Backend hygiene (own small piece, folded into the same commit)** —
   done, not flag-only; judged low-risk given the fallback design and
   existing test coverage to extend:
   - `MPCAutofill/MPCAutofill/settings.py`: renamed
     `PRINTING_TAG_AI_WEIGHT` -> `PRINTING_TAG_MACHINE_WEIGHT`, reading
     the new env var name first and falling back to the old one
     (`env.float("PRINTING_TAG_MACHINE_WEIGHT", default=env.float("PRINTING_TAG_AI_WEIGHT", default=0.5))`),
     with a one-line deprecation comment. This resolves the rebinding
     caution behind the original no-rename decision directly: an existing
     deployment's `docker/.env` or repo secret still using the old env
     var name keeps working unchanged.
   - Updated both `_SOURCE_WEIGHTS` usages in `vote_consensus.py`, plus
     every comment elsewhere that cited the setting name as a *live*
     value (`purge_machine_votes.py`, `deductive_backfill.py`,
     `local_residual_classify.py`, `test_purge_machine_votes.py`) — these
     describe current code, not a historical event, so they needed to
     track the rename.
   - Added `TestMachineWeightRename` (`test_vote_consensus.py`) directly
     asserting `_SOURCE_WEIGHTS[VoteSource.DEDUCTION]` and `[VoteSource.OCR]`
     both still equal `settings.PRINTING_TAG_MACHINE_WEIGHT`, and that the
     value is still `0.5` — direct proof the rename changed no actual
     weight. Mirrors the existing `TestFederatedWeighting`-style pattern
     already in that file.
   - **Caught and fixed my own bug before it shipped**: my first attempt
     inserted the new test class in the middle of the pre-existing
     `TestFederatedWeighting` class, splitting two of its methods
     (`test_federated_vote_with_human_backed_true_satisfies_the_gate` and
     its sibling) into the wrong class. Found on the post-edit diff
     review, fixed by moving the new class to after
     `TestFederatedWeighting` closes, verified via `py_compile` + a
     `grep` of every `class`/`def test_` line confirming correct nesting.
   - **Verification without Django** (not installed in this sandbox, a
     documented limitation of this environment): `py_compile` on every
     touched `.py` file (all clean), plus a standalone Python simulation
     of `environ.Env.float`'s fallback semantics covering all three real
     scenarios — neither var set (-> 0.5), only the old var set (-> its
     value), both set (-> new var wins) — all three correct. This is
     logic verification, not a substitute for the actual Django test
     suite (`test_vote_consensus.py::TestMachineWeightRename`) — flagging
     that gap explicitly rather than claiming a full test run.

4. **docs/ sweep** (`grep -rn "\bAI\b" docs/`, every `.md` file):
   - `docs/features/printing-tags.md` — 5 prose spots fixed ("AI/deduction/OCR"
     -> "machine (deduction/OCR)", "one non-AI vote" -> "one non-machine
     vote", "AI-only votes" -> "machine-only votes",
     "AI-suggested-but-unconfirmed" -> "machine-suggested-but-unconfirmed",
     "AI/admin weights" -> "machine/admin weights", "AI-derived" ->
     "machine-derived"), plus the `PRINTING_TAG_AI_WEIGHT` code citation
     updated to the new `PRINTING_TAG_MACHINE_WEIGHT` name (this one
     describes live code, unlike theory.md's deliberately-preserved
     legacy citation). 2 `VoteSource.AI` mentions kept literal (accurate
     historical citations of the actual pre-split enum value, already
     self-explanatory in context — "a label split of what was originally
     one VoteSource.AI value"). 1 real `AI-Generated` tag mention kept
     (same reason_tags.py tag as the frontend finding above).
   - `docs/features/catalog-completion-plan.md` — 1 prose spot fixed
     ("artist AI vote" -> "artist machine vote").
   - `docs/federation-v1.md` — no change needed: its one `VoteSource.AI`
     mention is the same kind of accurate historical citation, and the
     surrounding prose already says "machine-derived source" correctly.
   - `docs/infrastructure.md` — no change: its two "AI" mentions
     (`"not AI-generated ones"`, `"AI-disclosure paragraph"`,
     `"AI-assistance signal"`) are entirely about AI-assisted *PR
     authorship* disclosure norms for upstreaming (i.e., generative-AI
     coding-assistant disclosure) — a completely different meaning of
     "AI" than the vote-source terminology this task is about. Confirmed
     by reading the full paragraph before ruling it out.

FLAGGED, NOT ACTED ON (a real but out-of-scope observation, not a decision
this task asked for): a broader sweep of `MPCAutofill/` turns up "AI" used
loosely as shorthand for "machine vote" in many more places this task
didn't ask me to touch — code comments/docstrings in
`deductive_backfill.py`, `question_feed.py`, `vote_consensus.py`,
`printing_consensus.py`, `local_residual_classify.py`, several test files'
inline comments, and the management command
`deductive_backfill_printing_tags.py`'s own `help` string. Also: three
Django migration files (`0050`, `0053`, `0054`) contain literal
`("ai", "AI")` as a frozen historical `choices=` value — these must never
be edited (migrations are an immutable record of what the schema actually
was at that point; the *live* `VoteSource` enum in `models.py` was
confirmed to have **no** "AI" choice at all anymore, already
USER/ADMIN/DEDUCTION/OCR/FEDERATED). This task's scope was docs/theory.md,
frontend user-facing strings, a docs/ sweep, and the one setting rename —
not a whole-codebase comment sweep. Noting this as a candidate for a future,
separately-scoped cleanup pass, not done here.

VERIFICATION: `python3 -m py_compile` on every touched `.py` file (clean,
after fixing the test-class-nesting bug caught on review); a standalone
fallback-logic simulation (3/3 scenarios correct); `docs_lint.py` clean
across all of `docs/`; `npx prettier --check` clean across every touched
Markdown and TSX file (one TSX file needed `--write` for a cosmetic
rewrap after the string-length change, applied and reverified). No live
Django test run — flagged above as a real gap, not silently skipped.

OPEN ITEMS / DECISIONS NEEDED: none blocking. The flagged broader-sweep
candidate above is the only follow-up worth a decision, and it's
explicitly optional/future, not gating this PR.

LIVE STATE: branch claude/ai-to-machine-terminology pushed to origin at
ae5c0b28. PR to be opened immediately after this report merges into the
same branch. On merge, docs/**'s change to theory.md/printing-tags.md/
catalog-completion-plan.md will fire docs-wiki-publish.yml automatically
(per the standing pipeline) — the Theory wiki page should show SS4's
correction post-publish; verification of that is the next step once this
merges.
```
