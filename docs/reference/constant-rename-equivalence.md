# Constant-rename equivalence check

**What it is.** `.github/scripts/constant_rename_equivalence.py` — an
AST-level checker that proves a constant-renaming or constant-extraction
refactor changed no behaviour, and that catches the concurrent merge that
silently breaks one.

**When to run it.** Any time a branch renames, extracts, moves or retires a
module-level constant — `*_SKIP_REASON`, `*_ANONYMOUS_ID`,
`*_EXTRACTOR_VERSION`, a weight, a threshold. It runs itself in CI
(`.github/workflows/constant-rename-equivalence.yml`), but the useful moment
is before you push, on the branch, where the output is a two-line diff
instead of a red check.

```bash
# HEAD vs its merge-base with origin/master
python3 .github/scripts/constant_rename_equivalence.py

# the name-resolution half alone: one revision, no diff needed
python3 .github/scripts/constant_rename_equivalence.py --check-references
```

Exit code is the number of findings (0 = clean), matching
`docs_lint.py`'s and `check_protected_core_license.py`'s convention.
Stdlib only; it reads source text via `git cat-file` and never imports or
executes it, so it needs no Django or third-party dependencies.

## Why it exists — the #567/#568 incident, 2026-07-29

PR #567 renamed `SLOW_PATH_TO_REVIEW_REASON` to
`SLOW_PATH_TO_REVIEW_SKIP_REASON` in
`MPCAutofill/cardpicker/local_calculate_verdicts.py`, as part of adopting
the `*_SKIP_REASON` declaration convention that
[`skip-reasons.md`](skip-reasons.md)'s roster tether depends on.

Concurrently, PR #568 added **brand new** code in
`MPCAutofill/cardpicker/catalog_stats.py` that imported and used the **old**
name.

Git auto-merged the two with **no conflict**. It could not have done
otherwise: #568 only ADDED lines, and #567 only touched a nearby docstring,
so the rename and the new references never textually collided. Nothing else
caught it either — not the full backend suite (3,036 tests), and not the
committed lint chain as it stood.

The merged result would have raised, at module-**import** time:

```
ImportError: cannot import name 'SLOW_PATH_TO_REVIEW_REASON'
```

in a module imported by the catalog-stats view **and** by the hourly
`warm_catalog_stats` job. Thirteen reference sites needed fixing across six
modules. The throwaway script that found it was written for one PR and
lived in a session scratchpad; this file is the version that does not get
lost.

The general shape of the defect: **a textual merge cannot see a name graph.**
Two changes that never touch the same lines can still produce a tree in
which a name no longer resolves, or resolves to a different value. Only
something that resolves names across the whole tree at both revisions can
tell.

## What it checks

Two independent checks, in increasing order of strength.

### 1. References — one revision, no false positives

Every `from x import NAME` whose NAME matches the pattern must actually be
declared in `x`, and every matching ALL-CAPS name a module reads must
resolve to a declaration somewhere in the tree. A violation is an
`ImportError`/`NameError` waiting to happen, unconditionally — there is no
judgment call and nothing to tune.

This is the half that runs on **every** Python PR. Note that on a
`pull_request` event, `actions/checkout` gives you the **merge result**, not
the branch tip — which is exactly the revision the #567/#568 bug existed in
and neither contributing branch did.

### 2. Equivalence — two revisions

For each module in scope, parse it at both revisions, then **normalise both
sides** by:

- inlining every module-level constant whose name matches the pattern, with
  the constant map built across the **whole tree** at each revision, so a
  cross-module `from x import Y_SKIP_REASON` resolves;
- deleting those declarations, their `__all__` entries, and the imports that
  only pulled them in;
- deleting every docstring (prose is expected to change — in a rename PR it
  is usually most of the diff);
- constant-folding f-strings and string `+` concatenation;

and comparing `ast.dump()` trees. **Identical trees mean every expression
that used to evaluate to a given value still evaluates to the same value,
under a different name.** A difference is reported with the module, the node
path, and both sides rendered back to source:

```
::error file=MPCAutofill/cardpicker/catalog_stats.py::normalised trees differ at Module.body[21].body[7].value.keywords[1].value
        9952865b: 'to-review'
        90c34e3c: 'to-review-v2'
```

Scope is deliberately narrow: the modules that touch a constant whose
declared **name** changed between the two revisions — which includes modules
the diff never touched, and that is the point. `--all` widens it to every
module mentioning the pattern; `--paths` narrows it to an explicit list.

## The pattern is a parameter

`--pattern` is a regex `re.search`-ed against ALL-CAPS module-level constant
names. The default covers the families this repo actually refactors:

```
SKIP_REASON|ANONYMOUS_ID|_VERSION|_WEIGHT|_THRESHOLD|_PREFIX|_REASON
```

It is a `search`, not a suffix test, for a concrete reason:
`LANDS_PHASH_SKIP_REASON_PREFIX` ends in `_PREFIX`, not `_REASON`, and its
value is composed at runtime as `f"{PREFIX}{reason}"` — which is also why
the f-string folder has to fold a _single interpolated constant_ back into
the surrounding literal, not just whole f-strings. `--pattern '.'` inlines
every ALL-CAPS module-level constant, the strongest and slowest setting.

## Honest limits

Stated plainly rather than discovered later:

- The equivalence check is a proof about **pure** refactors. A PR that
  renames a constant _and_ changes behaviour in the same modules will be
  reported. That is correct, not a false positive: the tool cannot know the
  behaviour change was intended, only that the refactor was not
  behaviour-preserving. Split the PR, or read the reported node and land it
  knowingly.
- A matching constant that is declared but never referenced is deleted from
  both sides by normalisation, so a change to _its_ value alone is invisible
  to the tree comparison. Those are surfaced separately as informational
  `note:` lines — not failures, because a legitimate constant-_extraction_
  refactor moves the same multiset.
- Declarations whose right-hand side is not a static expression (a call
  outside the `frozenset`/`set`/`tuple`/`list`/`dict` allowlist, a
  comprehension) are not inlined. They are listed as `note:` so you know
  what the proof did **not** cover.
- It reasons about names, not types or control flow. It is not a
  replacement for mypy or the test suite; it covers a gap both of them have
  demonstrably passed over.

**Do not weaken the normaliser to make a real repo pass.** The one time a
reported difference looked spurious, it was the production-breaking bug
above. Investigate before excluding.

## Tests

`.github/scripts/tests/test_constant_rename_equivalence.py`, run by the same
workflow and by `python3 .github/scripts/tests/test_constant_rename_equivalence.py`.
Every rule has a passing and a failing case, including a genuine
behaviour change (a renamed constant whose _value_ also moved) — a checker
that only ever reports "identical" proves nothing. Two real-repo tests pin
the incident: the committed tree resolves every matching reference, and the
actual #567 commit still normalises identically against its parent across
the twelve pipeline modules it touched.
