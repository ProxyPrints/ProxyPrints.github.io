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

Multiple Claude Code sessions/worktrees on this box can and do run `next dev` at the same time; Playwright's `webServer.reuseExistingServer: true`
will happily attach to whatever's already listening on 3000, which may
belong to a different worktree entirely — producing screenshots of stale
code with no error. Before trusting a suspicious screenshot, check `ps aux | grep "next dev"` for a PID under a different `.claude/worktrees/*` path.
Point your own run at a different port instead of killing another
session's process, unless the user directly confirms it's abandoned — then
verify the PID's cwd via `readlink -f /proc/<pid>/cwd` before killing.
Corollary: always kill your own leftover dev server when your task ends —
it's a landmine for the next concurrent session, not something to leave
running because it "seems harmless."

## Absolute paths to the repo root silently target the wrong checkout in a worktree session

`/home/ubuntu/ProxyPrints.github.io/<path>` and
`/home/ubuntu/ProxyPrints.github.io/.claude/worktrees/<name>/<path>` are
two entirely separate files on disk that happen to share a relative
path — git worktrees don't share a working directory, only `.git`
history/objects. A worktree session that reuses an absolute
`/home/ubuntu/ProxyPrints.github.io/...` path (e.g. copy-pasted from an
earlier grep, or muscle-memory from a non-worktree session) silently
edits/commits the **main checkout's** copy of a tracked file, on
whatever branch it has checked out (usually `master`) — not the
worktree's branch. The edit "succeeds" with no error, and `git status`
inside the worktree shows nothing wrong, because from the worktree's own
perspective nothing happened at all. Caught only by an unexpectedly
empty `git status --short` right before a commit that should have had
staged content. Fix: always use relative paths (or a path built from the
session's actual `pwd`) for file operations once inside a worktree,
never a hardcoded absolute repo-root path remembered from earlier in the
conversation. Exception: `WORKERS.md` and `journal/` are gitignored and
by established convention (see CLAUDE.local.md) live in the **main
checkout** specifically, so their absolute main-checkout paths are
correct on purpose — the trap is specifically for git-tracked files that
need to land on the worktree's branch.

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
exist; `git show <sha> --stat` and `git merge-base --is-ancestor <sha> origin/master` disproved both claims in under a minute. Always check
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
snapshot assertions hardcode exact sequence-derived values (e.g. `"Artist 0"`) that depend on total call count up to that point — so a brand-new,
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
several full `node_modules` copies was 4.7GB and invisible to a `du -sh repo/*` sanity check before excluding things from a Docker build context).

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

**(3) A negative z-index on that sticky element (per (1) above) is a ticking
time bomb once anything inside it needs to be clickable.** An uncontained
`z-index: -1` escapes all the way up to whatever ancestor DOES establish a
stacking context — which can be many levels up, or the document root — and
can make the sticky element's _entire subtree_, descendants included,
unclickable at the browser's hit-testing layer (`elementFromPoint` at a
descendant's own on-screen coordinates resolves to a grandparent instead),
even though everything still paints exactly where expected and looks
completely normal in a screenshot. This is silent as long as the sticky
element only ever shows static content — the bug was latent in this
codebase's own starburst card panel for months before an unrelated feature
added the first interactive control inside it. Fix: give the sticky
element's _own parent_ a real, local stacking context — `position: relative`
**and** an explicit non-`auto` `z-index` (e.g. `0`) together.
`position: relative` alone does not establish one; that gap alone is worth
budgeting a full extra "fixed, still broken" round for. Diagnose via
`document.elementFromPoint(x, y)` at the target's own
`getBoundingClientRect()` center, not via CSS inspection or screenshots —
a screenshot cannot distinguish "renders here" from "is hit-testable here."

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
first be checked against the deploy itself — `gh run list`/`gh run view --log` for the right commit SHA, the live bundle content via `curl`, and
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

## prettier@2.7.1's markdown formatter can silently corrupt text on a second pass

Running prettier on an already-prettier-formatted `.md` file is not
guaranteed to be a no-op: a real non-idempotency bug turns bare
`node_modules`-style intraword-underscore text into `node*modules`, and
`_italic_` emphasis into a broken `\_italic*`, with no error — it just
writes wrong content. Reproduced deterministically (not flaky) by adding
new prose to `docs/infrastructure.md` and running `pre-commit run prettier`/`npx prettier --write` twice in a row. Fix was to reword the two
trip points (wrap the bare `node_modules` mention in backticks, swap
`_hidden_` for `**hidden**`) rather than fight the formatter, then verify
by running the hook an extra time and confirming zero further diff before
trusting it as a stable fixed point. Most `docs/*.md` files in this repo
still have pre-existing prettier drift (predates this bug, out of scope to
mass-fix) — the pre-commit hook is now actually installed on this machine
(`pip install --user pre-commit && pre-commit install`, written into the
shared `.git/hooks/pre-commit` so it applies across every worktree of this
repo), so the next session that touches one of those drifted files should
diff prettier's output for corruption like this rather than committing it
blindly.

## "Icons not rendering" can be a data gate, not a rendering bug — check the API payload before the font pipeline

The Keyrune set-symbol icons live inside `CanonicalCardFilter`, which
renders nothing at all unless at least one card document from `/2/cards/`
has non-null `canonicalCard` — a Postgres-side field set only by
`import_canonical_card_data` followed by an `update_database` re-ingestion
(confirmed match) or by a resolved printing-tag vote. A prod DB where those
never ran shows no filter section anywhere, which presents exactly like a
frontend asset/font failure. Diagnose from the data end first: one look at
a `/2/cards/` response (`"canonicalCard": null` everywhere?) beats auditing
the entire font pipeline. The asset chain itself was verified good
end-to-end (postinstall vendoring → Pages artifact → glyph render), and
`getKeyruneChar` already lowercases codes, so case mismatch is a dead end
here.

## Cloud sandboxes can't reach the live site — deploy-run logs are the next-best ground truth

Claude Code web sessions' egress allowlist blocks proxyprints.ca (and
nearly everything else), so "check the live site" is impossible there.
Two substitutes proved decisive: the `deploy-frontend.yml` run log prints
the full tar listing of the exact artifact GitHub Pages serves (proves
whether a file shipped), and an `npm ci && npm run build` replica of the
workflow plus Playwright against `localhost` (allowed) exercises that same
artifact in a real browser (Chromium at
`executablePath: /opt/pw-browsers/chromium`; default Playwright download is
absent). State clearly in the report that live behavior itself was not
observed.

## Seeding `Tag` rows via a data migration breaks tests that assert on the whole table — use a management command instead

Tried seeding six new `Tag` rows via a Django data migration (RunPython).
Broke 5 unrelated tests (`test_views.py::TestGetTags::*`,
`test_tag_votes.py::TestPostTagConsensus::test_returns_an_entry_for_every_seeded_tag`)
because they assert the _complete_ `Tag` table is empty in a fresh DB
(besides the synthetic, never-persisted `"NSFW"` pseudo-tag from
`cardpicker/tags.py`) — a migration runs unconditionally at DB-setup time,
including the test database, so any migration-seeded row becomes
permanent baseline state for every test in the suite, not just the ones
that care about it. The repo's existing 13-tag `DEFAULT_TAGS` taxonomy
(`cardpicker/default_tags.py`) is deliberately _not_ wired into any
migration for exactly this reason — it's a manual, idempotent
`seed_default_tags` management command only. Any future tag/taxonomy
seeding should follow that same pattern (a `..._tags.py` module +
`get_or_create` + a thin management-command wrapper), never a migration,
regardless of how the request is phrased ("data migration" in a task spec
should be read as "a repeatable seeding step," not literally
`migrations.RunPython`, when the target table has DB-wide list-all
consumers).

## A call-count-based MSW mock breaks under React 18 Strict Mode's dev-time double-invoke

A Playwright mock like "return item X on the first `GET`, then a
caught-up/empty response on every call after" is a trap in this codebase
(`reactStrictMode: true` in `next.config.js`): Strict Mode double-invokes
effects on mount in dev (mount → cleanup → mount again), so a fetch effect
fires twice before the app "really" settles. A naive counter-based mock
hands its one real item to the _first_ (thrown-away) invocation and the
empty response to the second (kept) one — the UI never shows the item at
all, and the resulting test failure (a locator that never appears) looks
identical to a real rendering/interception bug, not a mock-design one.
Symptom to watch for: a Playwright test times out waiting for content
that a Jest/RTL test covering the identical interaction passes for
instantly — Jest doesn't run Strict Mode's double-invoke the same way a
real browser mount does. Fix: make the mock's "have I served the real
item yet" state track a genuine domain event the flow itself causes
(e.g. a specific vote being submitted), not a raw request count.

## Ad hoc prod DB/ES access goes through `docker compose run`/`exec`, never a persistent host-side connection script

The base `docker-compose.yml` publishes Postgres/ES to `127.0.0.1`, and
the DB credentials are public dev defaults (no secret needed) — so a
host-side script pointed at `127.0.0.1:5432`/`9200` connects to live
production data with no further authorization required to _run_ it again
later. That's the hazard: the container boundary (`docker exec`/`docker compose run`) is the actual behavioral guard on an otherwise-open
localhost port, and a saved wrapper script quietly removes it, becoming
ambient capability for whichever future session finds the file — same
class of risk as leaving a dev server squatting a shared port. One-off
reads for a specific task are fine; a durable script that outlives the
task's intent is not, even when nothing in it is secret.

**Scope, made explicit (2026-07-15)**: the rule guards paths to
**production** data specifically, not "any DB access from a host venv."
`pytest`'s own `testcontainers` fixtures (`cardpicker/tests/conftest.py`)
spin up throwaway, isolated Postgres/ES on different ports
(`47000`/`9300`, not `5432`/`9200`) for the lifetime of one test session
and destroy them after — no path to the real service ever exists in that
flow, so running the test suite from a host venv is not an exception to
this rule, it's simply outside its scope. The venv still never gets
settings/scripts pointing at the real `127.0.0.1:5432`/`9200` ports -
that boundary is unchanged. If a test or fixture is ever found reaching
the real ports instead of its testcontainer, that's a stop-and-report,
not a judgment call. Corollary: mounting the Docker socket into a
container to sidestep this (so tests run "through docker" too) is a
strictly worse trade, not a safer one - it hands the container the
equivalent of host root, a larger ambient capability than the
direct-DB-connection risk it would replace. Declined as an option; don't
build it for this or future workarounds.
