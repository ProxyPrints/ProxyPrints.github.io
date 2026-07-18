```
TASK: CLOUD session (upstream-readiness) — docs/conventions hygiene
batch, follow-up items 6-7 (items 1-5 already relayed and merged into
PR #100). Same branch: docs-conventions-hygiene-batch-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/100

WHAT SHIPPED:

6. docs/lessons.md — checked first (per instruction) whether these
   entries already existed: PR #91 and PR #78 both confirmed real and
   merged via pull_request_read. PR #91's own diff was checked
   directly (get_files) — it touched only cardPanel.tsx and
   whatsthat.tsx, no docs/lessons.md edit, so its two findings were
   genuinely undocumented. PR #78's own PR body already stated it adds
   a lessons.md entry, and it does exist (the "A rewrite that 'extracts
   X verbatim'..." section) — not duplicated, instead cross-referenced
   from the new entry.
   (a) Added "A value carried 'verbatim' out of its old context can
       silently stop meaning what it meant" — states the general class,
       cites PR #91's starburst 140%-of-33%-column width surviving into
       a 58% column as Instance 1, and cross-references the existing
       PR #78 entry as Instance 2 rather than restating it.
   (b) Added "Bootswatch Superhero hardcodes some component colors as
       literal properties, not CSS custom-property references" — PR
       #91's .btn-primary background-color finding, with the "verify
       computed styles, not var definitions" check stated explicitly.
7. Standard close: docs_lint.py clean; pinned prettier v2.7.1 (matching
   .pre-commit-config.yaml's exact pin) run across every file the whole
   batch touched (CLAUDE.md, docs/lessons.md, all 4 proposal docs) —
   clean after one fix (prettier's own --write pass converted my
   *asterisk* emphasis to _underscore_ and, separately, an accidental
   line-start "- " in my own prose got parsed as a stray markdown list
   item; reworded to an em dash, matching the file's existing dash
   convention, and reran --check clean).
   Wiki: no separate wiki edit made — this batch changes only
   docs/CLAUDE.md conventions (no user- or admin-facing product
   surface), so the "did this change what a USER sees or an ADMIN
   does?" trigger doesn't fire; noting per instruction that the
   automated wiki republish on merge is itself today's process-
   evolution documentation update, nothing further to do.

DEVIATIONS: none from items 6-7 as given. Item 5 (previous relay)
confirmed correct by the owner in the message that supplied items 6-7 —
no further action needed there.

VERIFICATION:
- python3 .github/scripts/docs_lint.py — clean.
- npx prettier@2.7.1 --check on every file the batch touches — clean.
- PR #91 and PR #78 verified live via GitHub (pull_request_read +
  get_files for #91), not assumed from the task's own citation.

OPEN ITEMS / DECISIONS NEEDED: none.

LIVE STATE: branch docs-conventions-hygiene-batch-cvq14g now has 2
commits (items 1-5, then items 6-7), pushed to origin. PR #100 open
against ProxyPrints/ProxyPrints.github.io master, description updated
to cover all 7 items, unmerged, awaiting the owner's merge-queue
action. No branch deletions performed. No uncommitted work left
behind.
```
