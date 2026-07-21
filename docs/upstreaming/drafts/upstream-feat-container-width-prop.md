# Draft: `upstream-feat-container-width-prop`

**Status: prep only — no branch cut yet.** This is a motivation/PR-body
draft for an upstream-shaped fix, written ahead of the fork implementation
it will be extracted from. Per the standing rule, nothing touches
upstream's repo without the owner personally sending it, and per this
prep task's own scope, the `upstream-feat-*` branch itself is **not** cut
yet either — see "Sequencing" below for why and what unblocks it.

## Verdict: defensible — genuine upstream self-consistency gap, not just a fork problem

**Evidence basis**: this was judged from `upstream/master`'s own code
(component widths, grid structure, and git history) — the live site
was not run; there was no way to render upstream's `/editor` at a real
1400px+ viewport. Every claim below is anchored to a specific line or
commit on `upstream/master`, not inference from our fork's `/display`
experience.

- `frontend/src/common/constants.ts:76` on `upstream/master`:
  `export const ContentMaxWidth = 1200;` — present verbatim, this fork
  has never touched it. `frontend/src/features/ui/Layout.tsx:49`'s
  `MaxWidthContainer` applies it as a hard `max-width` on every page's
  content, including `/editor` (`frontend/src/pages/editor.tsx` wraps
  `ProjectEditor` in `ProjectContainer`, `Layout.tsx`'s exported
  `MaxWidthContainer`-wrapping component — no page opts out).
- `frontend/src/components/ProjectEditor.tsx`'s `ChooseArtPanel` splits
  the capped 1200px into a `lg={8}` left panel (`CardGrid`, ~800px minus
  gutters) and a `lg={4}` right panel (status/settings, ~400px) — so the
  card grid's actual available width is roughly two-thirds of an
  already-capped number, not two-thirds of the viewport.
- `frontend/src/features/card/CardGrid.tsx`'s own `<Row xxl={4} lg={3} md={2} sm={1} xs={1}>` (fronts and backs) is a Bootstrap breakpoint prop:
  it declares that at viewport ≥1400px (Bootstrap's `xxl` breakpoint,
  keyed to real viewport width via media query, not container width) the
  grid should show 4 columns instead of 3. That is upstream's own
  developer stating an intent for a wider layout at wide viewports.
- **That intent can never manifest as intended**: because the outer
  container is capped at 1200px regardless of viewport, the `xxl={4}`
  breakpoint fires correctly (viewport ≥1400px) but the 4 columns are
  squeezed into the same ~800px the `lg={3}` case already had — cards get
  narrower per column at the exact viewport size the code chose to add a
  _fourth_ column, rather than wider. Every pixel of viewport past 1400px
  is unused whitespace on either side of the centered container.
- **This wasn't a deliberate joint decision — it's an unreconciled gap.**
  Git history on `upstream/master` shows `CardGrid.tsx`'s `xxl={4}`
  breakpoint already present by commit `6730b9e6` (2022-11-27), while
  `ContentMaxWidth` was introduced over six months later by commit
  `2160c6f7` ("try to clean up old css a little", 2023-05-30) — a general
  CSS-cleanup commit that touches `layout.tsx`, `navbar.tsx`,
  `dynamicLogo.tsx`, and `constants.ts`, but never touches
  `CardGrid.tsx`. The container cap was added without anyone revisiting
  the grid's own breakpoint choice, so the two have been silently
  inconsistent on any upstream editor session at a ≥1400px viewport ever
  since.

**Framing, precisely**: this is not a claim that upstream's `/editor` is
visibly "broken" — nothing clips, errors, or overflows; cards still
render, just smaller than the code's own `xxl={4}` breakpoint intended at
the exact viewport width it targets. The defensible claim is narrower:
**two pieces of upstream's own code disagree with each other** — a
component-level breakpoint asking for more columns at wide viewports,
and a container-level cap that guarantees those columns can never be
wider than the `lg` case already gave them. That's worth an _additive,
opt-in_ fix upstream, not a claim that the shipped cap itself was wrong
for every other page (it likely still is right for prose-width pages
like the FAQ or About page, where 1200px is a reasonable reading-width
choice).

## Proposed shape of the fix

An optional prop on `Layout.tsx`'s exported container (`ProjectContainer`
or a new sibling), e.g. `maxWidth?: number | "fluid"`, defaulting to the
current `ContentMaxWidth` behavior — so every existing page (including
`/editor` if a maintainer prefers to leave it alone) is byte-for-byte
unaffected unless it explicitly opts in. `/editor` would be the first
real consumer, passing `maxWidth="fluid"` (or a wider explicit px value)
so `CardGrid`'s `xxl={4}` breakpoint can actually earn back the width its
own code already asks for at ≥1400px viewports.

## Sequencing: why no branch yet

This fork is building the same underlying primitive right now for its own
`/display` page, tracked as fork issue #287 (a /display-specific
container-width override, motivated by our three-region layout's own
28% measured width loss — a different, fork-only motivation from the
upstream one documented above; see that issue for the fork-side numbers).
That issue is open, **not yet implemented** — there is no fork commit to
extract or adapt yet, and no `upstream-feat-container-width-prop` branch
should be cut until there is one. Once #287 lands with a concrete
`maxWidth`/`fluid`-shaped prop on the shared container component, this
branch gets cut from that landed implementation, adapted onto
`upstream/master`'s own `Layout.tsx`/`ProjectContainer` (not copied
verbatim — the fork's version will carry `/display`-specific plumbing
upstream has no use for), following `docs/upstreaming/conventions.md`'s
full checklist (isolated worktree off `upstream/master`, single commit
where practical, hand-written PR body, `pre-commit run --all-files`
clean, etc.) before anything is pushed.

## Draft PR body (for when the branch is cut and the owner decides to send it — NOT final until re-verified against the landed implementation)

# Description

`Layout.tsx`'s `MaxWidthContainer` applies a fixed `ContentMaxWidth`
(1200px) to every page's content with no way to opt out. This is a
reasonable default for prose-width pages, but it silently caps
`/editor`'s `CardGrid` below the width its own `xxl={4}` breakpoint
(`CardGrid.tsx`) was written to use — that breakpoint has existed since
2022 and asks for a 4-column layout at ≥1400px viewports, but the
1200px container cap (added later, in the unrelated CSS-cleanup commit
`2160c6f7`) means those 4 columns are never wider than the existing
`lg={3}` case already gave them. Every pixel of viewport past 1400px is
unused whitespace either side of the centered container.

This adds an optional `maxWidth` prop to \[the container component\],
defaulting to the current 1200px value — every existing page is
unaffected unless it opts in. `/editor` opts in via \[prop value\], so
`CardGrid`'s existing `xxl={4}` breakpoint can render at the width it
already asks for on wide viewports.

## Checklist

- [ ] I have installed `pre-commit` and installed the hooks with
      `pre-commit install` before creating any commits.
- [ ] I have updated any related tests for code I modified or added new
      tests where appropriate.
- [ ] I have manually tested my changes as follows:
  - <!-- fill in once the branch exists: viewport-resize testing of
    /editor at 1200/1400/1920px, screenshot diff of CardGrid column
    count and width -->
- [ ] I have updated any relevant documentation or created new
      documentation where appropriate.

---

## Notes for whoever cuts the branch later

- Re-verify the `xxl={4}`/`ContentMaxWidth` line numbers and commit SHAs
  above against `upstream/master`'s tip at cut time — both may have
  moved.
- Confirm the fork's #287 implementation is genuinely additive/optional
  at the shared-component level before treating it as the extraction
  source — conventions.md item 5 (diff only the intended change) applies
  doubly hard here since `Layout.tsx` is shared by every page.
- This PR body's `# Description` above still has two `\[...\]`
  placeholders (the actual prop name/shape, and `/editor`'s opt-in
  value) — fill those from the landed implementation, don't guess ahead
  of it.
