# Cross-session lessons

Terse, reusable lessons learned the hard way on this repo. One entry each —
if you need the full story, `git log`/`git blame` the relevant file. Add new
entries here only if they're genuinely reusable across unrelated future
tasks, not a one-off narrative (those belong in `journal/` or a feature doc
under `docs/features/`).

## Trust CI history, not a matching local venv, once a change touches Django's model-import chain
A local mypy run can pass identically across many sessions and still not be
what CI actually checks, if your venv has dependencies CI's isolated
pre-commit hooks don't (e.g. `mypy_django_plugin` genuinely imports, not just
statically analyzes, everything reachable from `cardpicker/models.py` —
importing Pillow there but never listing it in `.pre-commit-config.yaml`'s
mypy `additional_dependencies` crashed CI's mypy hook outright while every
local run silently fell back to treating PIL types as `Any` and stayed
green). Before trusting "matches the documented/previously-seen error
count," check `gh run list`/`gh run view --log` for the actual CI history,
not just a local re-run — especially for anything on the models.py import
chain.

## Concurrent worktree dev servers collide on port 3000
Multiple Claude Code sessions/worktrees on this box can and do run `next
dev` at the same time; Playwright's `webServer.reuseExistingServer: true`
will happily attach to whatever's already listening on 3000, which may
belong to a different worktree entirely — producing screenshots of stale
code with no error. Before trusting a suspicious screenshot, check `ps aux
| grep "next dev"` for a PID under a different `.claude/worktrees/*` path.
Point your own run at a different port instead of killing another
session's process, unless the user directly confirms it's abandoned — then
verify the PID's cwd via `readlink -f /proc/<pid>/cwd` before killing.
Corollary: always kill your own leftover dev server when your task ends —
it's a landmine for the next concurrent session, not something to leave
running because it "seems harmless."

## Swap in a debug color to disambiguate same-colored overlapping elements
A pixel/computed-color check at one sample point can be genuinely ambiguous
when two adjacent elements intentionally share a color (e.g. a themed
overlay bleeding onto a neighboring placeholder using the same palette).
Rather than reasoning it out from computed styles, temporarily force one
element to an unmistakable color never used elsewhere on the page (e.g.
`lime`), confirm the mechanism visually, then revert and re-check against
the real palette.

## Sample cyclic/periodic animations repeatedly, not once
A single before/after comparison of a value driven by a short repeating
cycle (e.g. a 150ms x 5-frame animation loop) can coincidentally land on
the same frame twice and falsely read as "static." Sample several times
across at least one full cycle and count distinct values instead of
trusting one pair.

## Verify cross-session "investigation reports" against git, don't take them as ground truth
A report relayed from a different Claude Code session (even one working on
a related codebase) is a claim, not a fact — treat it exactly like any
other unverified input. One such report claimed a fix commit was "still
unmerged on a branch" and described unrelated file changes that didn't
exist; `git show <sha> --stat` and `git merge-base --is-ancestor <sha>
origin/master` disproved both claims in under a minute. Always check
`git show`/`git merge-base`/`git ls-remote` before acting on a relayed
finding.

## Elasticsearch index mapping can drift from the schema declared in code
`documents.py`'s declared field types (e.g. `KeywordField`) don't
automatically stay in sync with the live index's actual `_mapping` — a
field can silently end up `text`-analyzed instead, breaking exact-match
`terms` queries on uppercase values with zero errors anywhere. If search
returns zero results despite a healthy, populated backend, compare the
live `_mapping` API against `documents.py` before assuming it's a query
bug. Fix: `manage.py search_index --rebuild -f` inside the django
container.

## `factory.Sequence` counters are process-global for the whole test run
Shared factories (`cardpicker/tests/factories.py`) increment a single
sequence counter across every test file in a pytest session, and some
snapshot assertions hardcode exact sequence-derived values (e.g. `"Artist
0"`) that depend on total call count up to that point — so a brand-new,
otherwise-unrelated test file can silently break unrelated snapshots just
by sorting earlier in collection order and using the same factory. Fix
pattern: an autouse fixture local to the new test file(s) only that
captures each shared factory's `next_sequence()` before the test body runs
and calls `reset_sequence(n, force=True)` both immediately (undo the peek's
own increment) and again in teardown, leaving zero net drift. Don't touch
`conftest.py` or existing test files to fix this.

## Use `du -sh path/.[!.]* path/*`, not a bare `path/*` glob, when sizing what's actually large
A plain shell glob silently skips dotfiles/dot-directories, which can dwarf
everything else being measured (a hidden worktrees directory carrying
several full `node_modules` copies was 4.7GB and invisible to a `du -sh
repo/*` sanity check before excluding things from a Docker build context).

## `position: sticky` and `overflow` interact in two non-obvious, easy-to-get-backwards ways
(1) A sticky element always paints in front of ordinary in-flow siblings
regardless of DOM order or a descendant's own z-index — `position: sticky`
unconditionally establishes a stacking context, so anything positioned
inside it (even at `z-index: auto`) paints ahead of plain content outside
it. Fix by giving the sticky element itself (not just its positioned
descendant) a negative z-index once you've confirmed no unwanted overlap
exists at any breakpoint. (2) Any ancestor with `overflow` other than
`visible` silently breaks `position: sticky` further down the tree, even if
that ancestor never itself scrolls — with no error or warning. If clipping
is needed for a purely visual reason (e.g. bleeding an effect at a panel
edge), prefer `clip-path: inset(0)`, which clips identically without
establishing a scroll container. Verify by scripting an actual scroll and
measuring `getBoundingClientRect()` at multiple offsets — a static
screenshot at one scroll position won't reveal a broken sticky context.

## A new wrapper placed around an existing effect can silently fight that effect's own CSS
When component B is later wrapped around component A, check whether B's own
CSS (especially `overflow`) contradicts something A was deliberately built
without. A hover-zoom effect was built with no `overflow: hidden` on its own
wrapper specifically so enlarged art could pop out uncropped; a placeholder
component added two rounds later wrapped around it out of habit with
`overflow: hidden` (not needed for its own purposes — `object-fit: cover`
already contained its image), silently re-clipping the hover-zoom it wrapped.

## Verify a deploy against real evidence before assuming the code is wrong
A user report of "none of these changes seem to have taken effect" should
first be checked against the deploy itself — `gh run list`/`gh run view
--log` for the right commit SHA, the live bundle content via `curl`, and
response headers (`Last-Modified` matching the deploy timestamp,
`cf-cache-status` not edge-cached) — before assuming the code is broken.
One such report turned out to be a real deploy that genuinely shipped the
change; the actual bug was a separate, real CSS issue that only became
visible once a live Playwright pass (not just curl) was used to drive the
page.

## Check for existing `data-testid` collisions before reusing a naming convention
Before giving a new component a testid that follows an existing naming
pattern (e.g. `<feature>-queue`), grep for whether a sibling component
already uses that exact string — especially one that stays mounted (hidden)
after its tab loses focus, which can produce two simultaneously-mounted
elements sharing one testid the instant a user switches tabs.
