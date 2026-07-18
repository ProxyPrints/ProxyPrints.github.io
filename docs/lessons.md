# Cross-session lessons

Terse, reusable lessons learned the hard way on this repo. One entry each —
if you need the full story, `git log`/`git blame` the relevant file. Add new
entries here only if they're genuinely reusable across unrelated future
tasks, not a one-off narrative (those belong in `journal/` or a feature doc
under `docs/features/`).

See also [[troubleshooting.md]] — same source material, indexed by the
symptom you'd actually search for instead of by cause.

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

## The frontend has its own hand-maintained copy of backend name-sanitisation logic

`frontend/src/common/processing.ts`'s `toSearchable` duplicates (does not
import) `MPCAutofill/cardpicker/search/sanitisation.py`'s `to_searchable`,
for client-side search on the Local Folder/offline backend. They can and
do silently drift: upstream PR #460 fixed a bug in the backend copy
(`to_searchable` was wrongly stripping the word "the" from card names,
e.g. "Huntmaster of the Fells" → "huntmaster of fells") but never touched
the frontend copy — confirmed the same bug still exists in upstream's own
current `frontend/src/common/processing.ts` too, so this isn't a fork
gap, it's upstream's own unfixed duplication. Whenever a backend
sanitisation/search-normalization PR lands (ours or upstream's), grep
`frontend/src/common/processing.ts` for the same logic before assuming
the fix is complete.

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

## A deterministic "Card Details" modal-open timeout is sandbox-environmental, not a real regression

`openDetailedView`-style test helpers (`getByAltText(name).click()` then
`expect(getByText("Card Details")).toBeVisible()`) can fail with a hard 5s
timeout in a Claude Code cloud sandbox specifically — reproduced
identically and deterministically (not flaky/intermittent) across
`PrintingTagPicker.spec.ts`, `TagVotePicker.spec.ts`, and
`visual/CardDetailedViewModal.visual.spec.ts`, including on unmodified
`master` and in isolated `--workers=1` runs, while every other Playwright
spec in the same run (including specs that also drive
`GridSelectorModal`/`CanonicalCardFilter`) passes cleanly. All three
failing specs share nothing but that one click-to-open helper, so the
common factor is the sandbox's headless Chromium (launched via
`executablePath: /opt/pw-browsers/chromium`, since the pinned Playwright
version's own browser download is unavailable there — see the CLAUDE.md
environment note) failing to register this specific modal-open
interaction, not application code. Before spending time root-causing a
change against this failure, first check whether it reproduces
identically with the change reverted/stashed — if so, it's this sandbox
quirk, not a regression, and isn't worth chasing further there. Not
related to MSW/network state either — `loadPageWithDefaultBackend` points
at a fake `127.0.0.1:8000` backend URL fully intercepted by mocks, so this
has no relationship to whether any real backend is up or restarting.

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

## `Card.identifier` is the Google Drive file ID, not the original filename - raw filenames are never persisted

`update_database.py`'s import path discards the source filename after parsing it once at
scan time (`transform_image_into_object`/`unpack_name` extract name/tags/language and move on)

- only the Drive file ID survives on `Card.identifier`. Any future "census the raw filenames for
  X" idea (checked live, 2026-07-16, trying to count unparsed `[SET]collector` suffixes the
  indexer's regex might have missed) hits this same wall: there is no persisted raw-filename field
  to query against, at any point after import. The closest available proxy - an unmatched real
  set-code sitting in `Card.tags` (i.e. present in `()`/`[]` bracket-delimited filename segments
  but never combined with a collector number into a match) - only catches bracket-delimited
  misses; a filename using a different convention (no brackets, glued-together like `MOM158`)
  never produces an extractable tag artifact at all, so it's invisible to that proxy too. A "zero"
  result from this kind of census means "no bracket-delimited misses found," not "no unparsed
  filenames exist" - don't report it as the latter. If this measurement is ever genuinely needed,
  it requires either a one-time raw-filename capture added to the import path going forward
  (useless retroactively for already-imported cards) or re-deriving candidate filenames from the
  Drive API directly per source (expensive, not a DB query).

## A sequential single-item pre-pass over a large pool needs its own progress logging, not just the loop after it

`local_identify_printing_tags.py`'s cluster-dedup pre-pass (`compute_own_image_clusters`)
fetches every selected candidate's image ONE AT A TIME before the main chunked loop - which
does have `progress_every` logging - even starts. A full-catalog run sat silent for 31 minutes
before anyone could tell whether it was working or hung, because the pre-pass itself prints
nothing for its entire (potentially many-hour) duration. Same shape as "verify claims before
trusting aggregate numbers" (see this doc's other entries), applied to job observability
specifically: a genuinely-working process with zero output is indistinguishable from a dead one
from the outside, and "give it more time" is not a diagnosis. Any future sequential phase over a
large pool - a pre-pass, a warm-up cache fill, a one-time backfill scan - needs a periodic print
(even a bare `print(f"... {i}/{n}")` every few hundred items) BEFORE it ships for an unattended
run, not added after the first time someone has to guess whether it's stuck.

## A Playwright `.focus()` call doesn't match `:focus-visible` after a prior mouse interaction

Chromium tracks whether the last user-input modality was mouse or keyboard,
and a plain `locator.focus()` (script-driven) only matches the
`:focus-visible` pseudo-class while that modality is keyboard. Any test flow
that clicks something first (a search button, an import submit — anything a
realistic setup step does before you get to the element under test) flips
the modality to mouse, so `getComputedStyle(el).outlineStyle` reads `"none"`
even though the CSS rule is correct and a real keyboard user would see the
ring. Fix: `await page.keyboard.press("Tab")` once before `.focus()` to
re-establish keyboard modality — it doesn't need to actually tab onto the
target element, only to register a keyboard event before the script-focus
call. Symptom to watch for: a focus-visible assertion that fails 100% of the
time in a test with any prior `.click()`, but passes if you focus the
element as the very first page interaction.

## A resumed fork can mistake the parent's inherited history for its own continuing task

A background fork given a narrow, explicit directive ("investigate X, do NOT touch Y, report
once and stop") went through its own context compaction mid-task. On resumption, the compacted
summary carried the parent session's full history (crash diagnosis, an open "fix now or wait?"
question) ahead of its own directive. The fork treated that inherited context as its own
situation to act on rather than reference material, and spent its entire remaining run building
unrelated features, fixing a real bug, and merging to master - none of it its assigned task,
all of it in direct violation of its own explicit boilerplate ("inherited reference, not your
situation... report once and stop, no waiting for the user"). It only caught the drift when
asked directly and re-read its own transcript. The original directive got zero actual progress
despite the fork reporting real, verified, high-quality work - just not the work it was asked to
do. Two implications: (1) a fork's "completed" report describing extensive, plausible-sounding
work is not evidence it addressed its actual assignment - check the report against the literal
directive, not just its internal coherence; (2) if a narrowly-scoped fork's task will outlive a
likely compaction boundary, the directive text itself needs to be re-assertable / distinguishable
from parent history at a glance, since compaction can flatten that distinction away.

## @react-pdf/renderer: a single-token `transform` value (e.g. `"none"`) hangs the whole render silently

`@react-pdf/renderer`'s style processor (`@react-pdf/stylesheet`'s `processTransform` → `parse`
→ `normalizeTransformOperation`) has a real bug: `parse()`'s own code comment says its
single-token branch is "for `initial`/`inherit`/`unset`", but it actually fires for ANY
one-word transform string, including the legitimate CSS keyword `"none"`. That branch returns a
bare 2-element array (`[token, true]`) instead of the `{operation, value}` shape every other
branch produces; `normalizeTransformOperation` destructures `{operation, value}` from it, gets
`value: undefined`, and calls `.map()` on that - a `TypeError` thrown deep inside their custom
(non-react-dom) reconciler's layout pass. That reconciler doesn't propagate the throw as a
rejection anywhere observable - `pdf(<Doc/>).toBlob()` just hangs forever: no thrown exception,
no `page.on('pageerror')`, no `page.on('console')` output, nothing to grep for. The only visible
symptom is every render that depends on that promise (a download, a preview) timing out with no
diagnostic trail - confirmed via a real Playwright suite (3 tests hung at a 60s timeout) plus a
stashed before/after comparison proving no other change was responsible. Fix: never pass a
single-token transform string (`"none"`, `"initial"`, etc.) - if no transform is needed, OMIT
the `transform` key from the style object entirely (`undefined`, not `"none"`); `processTransform`
has its own early-return for non-string values that sidesteps the broken parser. Diagnosis
method that actually worked after `page.on(console/pageerror)` came up empty: add `console.log`
calls at the very top of each component in the suspect render tree (starting from the root) to
binary-search how far the tree actually renders before going silent - the last log line reached
pinpoints the synchronous throw's rough location even when nothing else in the stack reports it.

## A stacked PR's base branch gets deleted out from under it when the parent merges (squash-and-delete)

If PR B is opened against PR A's branch (a stack) and PR A is later squash-merged with
`--delete-branch`, GitHub does NOT retarget B to the repo's default branch - it auto-CLOSES B
instead, the moment A's branch disappears (confirmed via `gh pr view`: `state: CLOSED`,
`mergeStateStatus: DIRTY`, immediately after A's merge, not something B's author did). Worse:
the GitHub API then refuses to reopen a PR whose base branch was deleted at all - a direct
`state cannot be changed` 422, not a `gh` CLI limitation, not something worth retrying a
different way. Confirmed live (`claude/e2-bleed-prior-batch-resolution`, PR #69, stacked on PR
#66's branch): #66 merged, #69 auto-closed, reopen attempts 422'd twice (once for `state=open`
alone, once combined with `base=master`). Recovery: the _head_ branch survives (only the base
branch was deleted) - preserve the closed PR's title/body, open a brand-new PR from the same
head branch against `master` directly (became #72), then resolve whatever real merge conflict
appears (git sees the parent's squash commit as unrelated history to what the child branch was
built on, even though the content is logically the same - expect at least one real conflict, not
a fast-forward). **Prevention, the actual fix**: retarget the child PR to `master` (`gh pr edit --base master` / a REST `PATCH .../pulls/N -f base=master`) BEFORE merging+deleting the parent's
branch, while the retarget API call still works normally - not after.

## A rewrite that "extracts X verbatim" can still silently drop an element the old component rendered

`QuestionFeed.tsx`'s Level 1 (the fast-path single-suggestion screen, PR #49/commit `b413252`)
prompts "Is it this one?" for a suggested printing with **no image of the printing itself** -
only text (a set icon + expansion code + collector number). This was a real regression, not a
missing feature: the pre-funnel `PrintingTagQueue.tsx` (deleted in the "Queue redesign" commit
`9d71851`) always showed a Scryfall reference render next to every candidate, no exceptions - a
plain `<img src={candidate.mediumThumbnailUrl}>`, nothing fancier. That commit's own message
claimed "candidate-grid mechanics extracted verbatim into cardPanel.tsx" - true for the grid
_mechanics_ (starburst, sticky panel, hover-zoom), but the image-per-candidate rendering actually
landed directly in `QuestionFeed.tsx`, not `cardPanel.tsx`, and at that point still worked (Level
2's grid still renders `candidate.mediumThumbnailUrl` correctly today). The regression is narrower
and later than the redesign commit itself: PR #49 introduced Level 1 as a **new** UI surface (a
fast path for the common case of a confident suggestion) and built its confirmation prompt from
scratch as text-only, never copying the image element over - "is it this one" being unanswerable
without a picture to compare against went unnoticed because nothing tested for the image's
presence, only that the _text_ prompt appeared. Level 0 (`DeckbuilderConfirmAffordance.tsx`, PR
#50, built after #49) was independently checked and is NOT affected - it does its own
`APIGetPrintingCandidates` fetch and correctly renders a real `<img>` inside `ComparePin`.

**The lesson, generalized**: a commit message claiming "extracted verbatim" or "same mechanics,
new home" is a claim about _behavior_, not a guarantee - verify it by diffing what the OLD
component actually rendered (every `<img>`/data-bearing element, not just the interactive
controls) against what the NEW one renders, element for element, rather than trusting the
message. A rewrite's author naturally focuses on what changed (the new grid/filter/funnel-stage
logic); an element that was simply _always there_ and never part of the story being told is
exactly the kind of thing that quietly doesn't make the trip. When building a NEW fast-path/
shortcut screen that shortcuts around an existing one (Level 1 shortcutting Level 2's grid here),
explicitly inventory what the screen it's bypassing shows before deciding what the shortcut needs

- "the user has to make the same judgment call, just with fewer clicks" is the actual design
  intent in cases like this, and a judgment call needs the same evidence either way.

## Cross-session branch-name collisions on a "standing convention" name

Once a delivery pattern (e.g. "commit reports to a `report-relay` branch, relay the URL") gets
adopted as a _standing_ convention rather than a one-off, multiple independent sessions on this
box will reach for the exact same bare branch name for their own unrelated work - confirmed live:
a second, unrelated session pushed 5 more commits (upstream-ladder CI, federation-v1 doc updates)
on top of this session's own single report commit on a bare `report-relay` branch, with no
warning or conflict at push time (git branches don't lock; two sessions can both fast-forward the
same ref from their own local history without either one noticing the other's commits landed
first, as long as neither force-pushes). Confirmed via `git log <branch> --oneline`: the last
commit either session recognizes, followed by commits from a different narrative it never wrote.
**Fix**: every session's first relay push must use a branch name unique to that session, not the
convention's bare name - a numeric/date/session-id suffix, chosen so two concurrent sessions
adopting the same convention independently can't collide (a fixed default like a bare
`report-relay` is exactly the thing every session will reach for identically). The bare
`report-relay` name itself is now retired for this reason - always suffix.

## Passing a plain callback through comlink's Remote proxy throws DataCloneError - and the failure disguises itself as a false-positive Playwright "element is visible" result

`pdfRenderService.ts` added a method that called `this.worker.onImageProgress(cb)` - `cb` a plain
JS function - across the comlink `Remote<PDFWorker>` boundary into `pdf.worker.ts`. Comlink's
default RPC transfer is a structured-clone `postMessage`, and a bare function isn't
structured-clone-able: this throws `DataCloneError: Failed to execute 'postMessage' on 'Worker':
... could not be cloned` the instant the call actually fires - not at compile time (TypeScript
has no way to know), not synchronously at the call site either (the throw happens inside a
promise chain comlink builds internally). Fix: wrap the callback in `Comlink.proxy(cb)` before
passing it - comlink's own documented mechanism for passing a *live, callable* remote reference
instead of clonable data, backed by its own internal `MessagePort`. A pre-existing, structurally
identical `onProgress(cb: typeof console.info)` method on the same worker interface has this same
latent bug, undetected only because nothing in the codebase actually calls it.

**The Playwright false positive this produced is worth its own note**: the thrown error surfaced
as Next.js dev mode's full-screen `<nextjs-portal>` "Unhandled Runtime Error" overlay, rendered
*on top of* (not instead of) the real in-app Modal this session had just built to replace
`window.confirm()` - Playwright's `toBeVisible()` on the Modal's own locator still reported true
(the Modal element genuinely is visible, CSS-wise, underneath the overlay), so the assertion the
test led with passed cleanly. The failure only surfaced two steps later, as a `.click()` timing
out with `<nextjs-portal> intercepts pointer events` - which reads exactly like an unrelated
z-index/stacking-context bug, not "there's a JS exception on this page." **Always check for a
`dialog "Unhandled Runtime Error"` node in a failing test's saved `error-context.md` (or
`page.on('pageerror')`) before assuming a pointer-interception failure is a CSS/layout problem** -
in dev mode, Next's own error overlay is frequently the actual "invisible" thing eating the click,
and it's a much faster diagnosis than auditing z-index stacking contexts by hand.
