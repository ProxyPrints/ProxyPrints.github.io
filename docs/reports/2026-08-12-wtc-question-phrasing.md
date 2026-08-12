```
TASK: WTC question phrasing (owner directive) — branch `feat/question-phrasing`, code commit 0d27f042
      (pushed to origin/feat/question-phrasing); report branch `report-relay-wtc-question-phrasing-20260812-0054`.

WHAT SHIPPED:
1. Question copy restated per the phrasing directive (frontend/src/features/questionFeed/QuestionFeed.tsx):
   - confirm_suggestion header "Anything else true of this card?" (was "Confirm the attributes")
   - identify_printing prompt "Which printing is this?" (removed the open-ended "You tell us — which
     printing?" variant; the question is now unconditional)
   - custom-art button "This is custom art" (was "🎨 Art matches, not an official printing")
   - suggested-printing prompt "Is this the EXACT printing?" (was "Is it this one?"; EXACT underlined
     via a new ExactWord span)
   - artist question "Who made this art?" (was "Who's the artist?")
2. Border question answer surface widened: BorderColorQuestion.tsx renders the FULL_ART_CHIP as a fifth
   chip ("No border — full art.") alongside the four BORDER_COLOR_GROUP chips. Full Art is an independent
   toggle that co-occurs with every border colour (§7), so it is a real border answer cast as an ordinary
   CardTagVote through the shared useTagVoting path — no new vote model, endpoint, or chip machinery.
   attributeChips.ts exports FULL_ART_CHIP (additive export, no rename).
3. New border ActionRow answer "Can't tell from this scan." (data-testid question-feed-cant-tell) records
   the abstention with reason `cannot-tell`; the plain Skip answer records an abstention with no reason.
   abstainAndAdvance gained an optional `reason` param; both Skip call sites now close over `()`
   (a bare onClick={abstainAndAdvance} would pass the MouseEvent through as reason and break the
   request body — found and fixed during verification).
4. Backend reason plumbing (additive-only): CardQuestionAbstention gains optional nullable `reason`
   CharField(32) + docstring (models.py), hand-written migration 0110 (same convention as 0104),
   SubmitQuestionAbstentionRequest.reason optional (schema_types.py), submitQuestionAbstention view
   passes it to get_or_create defaults (views.py), frontend APISubmitQuestionAbstention sends it only
   when present (api.ts). A reason-carrying abstention stays the same model — distinguishable, not new.
5. Tests: backend test_question_abstention.py — existing test now asserts reason defaults to None; new
   test_abstention_records_the_optional_reason_when_sent covers reason persistence. Frontend
   QuestionFeed.test.tsx — border test updated (Full Art chip present, tapping it casts a "Full Art"
   tag vote) plus a new "'Can't tell from this scan.' records the border abstention with reason and
   advances" test. mocks/handlers.ts questionFeedBorder fixture seeds "Full Art": 0 confidence.
6. Docs (edited in place, per convention): docs/features/wtc-question-model.md — §7 border section and
   §7.7 ruling 4 now describe the Full Art chip + Can't-tell answer + optional reason field; the
   identify_printing section documents the not-built "Same artwork, different printing." answer.

DEVIATIONS from spec:
1. "Same artwork, different printing." (identify_printing) is NOT built — stopped and reported per the
   directive. It must cast an illustration vote while provably casting no printing vote; every existing
   illustration-vote path (cast_illustration_vote) derives a printing vote at a live 1:1 match with no
   flag to suppress that derivation. Honoring "must NOT cast a printing vote" requires a backend
   suppression flag or a new endpoint — both outside the additive-only scope. Documented as a gap in
   wtc-question-model.md pending an owner decision on the suppression mechanism (see OPEN ITEMS 1).
2. No new endpoints, no new vote models anywhere; the only schema shape added is the optional nullable
   abstention `reason` field (migration 0110), which the directive's additive-only scope permits.

VERIFICATION:
- Frontend jest (targeted): QuestionFeed.test.tsx 30/30 PASS; attributeChips.test.ts +
  AttributeChipPanel.test.tsx 34/34 PASS.
- Full frontend suite: 656 passed / 22 failed across 4 suites (searchSettings/comparison,
  filters/CanonicalCardFilter, gridSelector/SelectVersionResults, display/useCardbackReminderGate).
  Stash-checked against the clean base: identical 22 failures with my changes absent — pre-existing
  environmental failures (postinstall-generated keyruneCodepoints.json asset missing; Set.prototype
  .isSubsetOf unavailable in this Node runtime), unrelated to this work.
- Backend pytest: test_question_abstention.py 8/8 PASS (includes the new reason test).
- python -m py_compile: clean on all changed Python files.
- tsc --noEmit: only pre-existing errors (missing generated keyrune asset; ReportCardPanel.test.tsx),
  none in changed files.
- docs_lint.py: clean.
- Pre-commit hooks: all pass after their own formatting fixes (end-of-file-fixer newline on the
  migration; prettier wrap on BorderColorQuestion.tsx + QuestionFeed.test.tsx) — folded into 0d27f042.
- Deferred: no live DB/Docker in this cloud session, so migration 0110 was NOT applied to a real
  database — unit tests exercise the model/migration through the Django test runner; the deploy-time
  migration apply is on the owner (see OPEN ITEMS 2). makemigrations --check was blocked by an
  unrelated staticfiles manifest error (favicon.ico) in this environment; the migration was
  hand-verified against the model instead (AddField matches the CharField(blank=True, null=True)).

OPEN ITEMS / DECISIONS NEEDED:
1. "Same artwork, different printing." — owner decision needed on the printing-vote suppression
   mechanism (a flag on the existing illustration-vote path vs a new endpoint) before this answer can
   be built. Currently a documented gap; nothing was invented.
2. Migration 0110 (cardpicker 0109→0110) must be applied to the live DB at deploy time — not run here
   (no DB access in this session).
3. Wiki maintenance (cloud-session convention): "wiki: WTC question feed page needs the new question
   phrasing + border answer surface (Full Art chip, 'Can't tell from this scan.' reason) reflected" —
   to be added to the PR's merge-time checklist.

LIVE STATE: nothing running or deployed. origin/feat/question-phrasing = 0d27f042 (12 files,
+205/−44). Report committed on report-relay-wtc-question-phrasing-20260812-0054 (this file). Owner
sequences the merge to master. Timestamp 2026-08-12T00:54Z.
```
