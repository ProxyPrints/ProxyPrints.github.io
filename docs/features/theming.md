# Theming — the token file, the layering, and the "born grey" fix

2026-07-24 theme-defaults pass. Fixes the recurring complaint that new/
un-opted-in Bootstrap components (Modal, Dropdown, Popover, Toast, the plain
`Card.Header` cap, `Offcanvas`, table-head/table-dark, the `Form.Select`
chevron) rendered as flat Superhero-stock grey instead of the site's own dark
navy chrome, by giving every Bootstrap variable override ONE canonical source
instead of a scattered literal.

## The token file

[`frontend/src/styles/_theme-tokens.scss`](../../frontend/src/styles/_theme-tokens.scss)
is the single source of truth for the site's palette and corner-radius
tiers. It defines plain SCSS variables (`$theme-*`) with no Bootstrap
dependency — nothing in this file imports Bootstrap or Bootswatch. Every
value is the SPEC-display-left-rail.md §D.0 binding palette (itself the
issue #302 palette), reproduced verbatim.

Colour tokens (darkest → most-raised):

| Token                   | Value     | What it's for                                                                                    |
| ----------------------- | --------- | ------------------------------------------------------------------------------------------------ |
| `$theme-body-bg`        | `#0f2537` | page background, the darkest layer                                                               |
| `$theme-raised-bg`      | `#22303f` | floating chrome one step off the page — rail-head/artist-line, the Sources list + filter inputs  |
| `$theme-panel-bg`       | `#4e5d6c` | Superhero's native `$secondary`/`$gray-600` — Card bodies, D14 seticon, secondary buttons/badges |
| `$theme-card-header-bg` | `#4e5d6b` | one hex digit off `$theme-panel-bg`, **by design** (owner ruling, 2026-07-23)                    |
| `$theme-band-bg`        | `#2b3e50` | the D14 confidence-strip token                                                                   |
| `$theme-divider`        | `#16202b` | every rail block boundary                                                                        |
| `$theme-text`           | `#ebebeb` | body text                                                                                        |
| `$theme-muted`          | `#8fa0b0` | muted text/placeholder                                                                           |
| `$theme-light`          | `#abb6c2` | `btn-outline-light` family, the form-select indicator chevron                                    |
| `$theme-primary`        | `#df6919` | primary accent (Superhero-native)                                                                |
| `$theme-primary-hover`  | `#be5915` | primary accent hover                                                                             |
| `$theme-success`        | `#5cb85c` | success                                                                                          |
| `$theme-danger`         | `#d9534f` | danger                                                                                           |
| `$theme-warning`        | `#ffc107` | warning                                                                                          |
| `$theme-info`           | `#5bc0de` | info                                                                                             |
| `$theme-input-border`   | `#4e5d6c` | input border colour                                                                              |

Corner-radius tokens (added by the owner's same-round extension —
"a future 'rounded buttons' ruling should be a token change like
everything else"):

| Token                | Value  | What it's for                                                                                                                                                |
| -------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `$theme-radius-none` | `0`    | no rounding, ever — kept distinct from `-base` so a future `-base` bump can't accidentally round something that must stay square                             |
| `$theme-radius-sm`   | `0`    | Bootstrap's `-sm` tier (small buttons/inputs)                                                                                                                |
| `$theme-radius-base` | `0`    | the sitewide default tier (buttons/cards/inputs/`-lg`)                                                                                                       |
| `$theme-radius-pill` | `10px` | our OWN "status-pill" component convention (D14 statepill, etc) — see the "two different pills" note below; NOT wired into Bootstrap's `$border-radius-pill` |

Both token families currently equal what the site already ships (flat `0`,
plus the existing `10px` pill exception) — introducing them changed **zero
rendered pixels**; see Verification below.

## The layering

[`frontend/src/styles/styles.scss`](../../frontend/src/styles/styles.scss)
is the only file that imports Bootstrap/Bootswatch, and it now follows one
rule throughout: **every Bootstrap variable override assigns from a
`$theme-*` token, never a literal hex/number.** Concretely, in this order:

1. `@import "theme-tokens";` — pulls in every `$theme-*` variable above.
2. A block of plain SCSS variable assignments (`$dark`, `$input-bg`,
   `$card-cap-bg`, `$modal-content-bg`, `$border-radius`, `$btn-border-radius`,
   etc.), each set to a `$theme-*` token.
3. `@import "~bootswatch/dist/superhero/variables";` then the Bootstrap
   core imports.

Step 2 has to come before step 3 because Bootswatch/Bootstrap declare their
own defaults with SCSS's `!default` flag — a variable already assigned
(step 2) is left alone by every later `!default` assignment downstream,
Bootswatch's or Bootstrap core's alike. This is the same mechanism the
pre-existing `$dark`/`$input-bg`/`$input-color` overrides (issue #302) always
used; this pass just extends it and gives it one shared source file instead
of inline literals.

**To retheme the site**, edit `_theme-tokens.scss` only — every consumer
(the Bootstrap variable overrides in `styles.scss`, and any fidelity spec
asserting one of these values, see below) is meant to pick the new value up
automatically or need a one-line spec update, never a hunt through component
files for a scattered literal.

## The "born grey" inventory this pass fixed

Superhero's own `_variables.scss` sets several component defaults straight
to `$gray-600` (`#4e5d6c`) — correct for the "panel" role (`$theme-panel-bg`
is the _same_ value, deliberately), but wrong for surfaces that are
conceptually "raised chrome" floating above the page, which should read
`$theme-raised-bg` (`#22303f`) instead. Nothing had ever routed these away
from the Superhero stock value, so every consumer was "born grey":

| Bootstrap variable                                                 | Was                                                                                                | Now                                                                                                                          | Real surfaces affected                                                                                                      |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `$modal-content-bg`                                                | `$gray-600` (`#4e5d6c`)                                                                            | `$theme-raised-bg`                                                                                                           | every `<Modal>` sitewide — Search Settings, the grid selector (Cardback/version picker), Change Query, etc.                 |
| `$dropdown-bg`                                                     | `$gray-600`                                                                                        | `$theme-raised-bg`                                                                                                           | dropdown menus                                                                                                              |
| `$popover-bg`                                                      | `$gray-600`                                                                                        | `$theme-raised-bg`                                                                                                           | popovers (e.g. the D14 set-icon popover)                                                                                    |
| `$toast-background-color`                                          | `$gray-600`                                                                                        | `$theme-raised-bg`                                                                                                           | toasts                                                                                                                      |
| `$card-cap-bg`                                                     | `$table-hover-bg` (a near-transparent tint of `$card-bg`, reading as barely-lighter-grey-on-grey)  | `$theme-card-header-bg`                                                                                                      | plain `<Card><Card.Header>` (not `AutofillCollapse`, which already inline-styles its own header)                            |
| `$table-head-bg` / `$table-dark-bg`                                | `$light` (a pale blue-grey)                                                                        | `$theme-raised-bg`                                                                                                           | any future `.table-light`/`.table-dark` variant (unused today — see "known gaps" below)                                     |
| `$form-select-indicator-color`                                     | `$gray-800` (Bootstrap core default, near-black)                                                   | `$theme-light`                                                                                                               | the `<Form.Select>` chevron (e.g. Print Options' bleed-override select) — was nearly invisible against the dark `$input-bg` |
| the standalone `.offcanvas { background-color: $secondary; }` rule | a literal `$secondary` override, predating Superhero, that had started actively fighting the theme | removed — `$offcanvas-bg-color` now explicitly set to `$theme-body-bg` before the Superhero import, same pattern as the rest | the left/right rail's own outer `Offcanvas` chrome                                                                          |

**What's grey on purpose — do not "fix" this.** `$theme-panel-bg` (`#4e5d6c`)
is Superhero's native `$secondary`/`$gray-600`, and it's the _correct,
approved_ token for: Bootstrap Card bodies (including
`AutofillCollapse`'s "demoted body" — SPEC-display-left-rail.md §D.1
explicitly locks this to `#4e5d6c`), the D14 seticon, and `variant="secondary"`
buttons/badges. `$card-bg` itself was deliberately left untouched by this
pass — routing it to `$theme-raised-bg` would have been a **fidelity
regression** against that exact spec-locked row. If a surface still looks
grey after this pass, check whether it's one of these approved-panel
surfaces before assuming it's a leftover default.

**Two different pills.** Bootstrap's own `$border-radius-pill` (default
`50rem`, a true stadium shape) already backs a real, unrelated pill usage —
e.g. `SearchSettings.tsx`'s `<Badge pill>`. `$theme-radius-pill` (`10px`)
is our own separate "status-pill" component convention (D14 `.statepill`,
etc.), applied as a literal at each call site, never through Bootstrap's
pill variable. Wiring `$border-radius-pill` to `10px` would have visibly
reshaped the `<Badge pill>` — deliberately not done.

**Known gaps, deliberately out of scope this round:**

- `$list-group-bg` was NOT set, even though Superhero also defaults it to
  `$gray-600`. `frontend/src/styles/styles.scss` has
  `// @import "~bootstrap/scss/list-group";` commented out entirely — the
  `.list-group`/`.list-group-item` CSS classes don't exist in the compiled
  output at all today, so `<ListGroup>` (used unstyled in `MyDecksPage.tsx`,
  `SavedDecksLandingPanel.tsx`, `ShareDeckModal.tsx`, `DrivesPanel.tsx`)
  is a separate, pre-existing "born unstyled" bug, not a grey-default one.
  Enabling that partial is a real CSS-surface change needing its own
  visual verification pass across four pages — left for a follow-up.
- Table variant colours (`$table-head-bg`/`$table-dark-bg`) were fixed even
  though no `.table-light`/`.table-dark` variant is used anywhere in the
  codebase today (`AutofillTable.tsx`/`SourceSettings.tsx` both use the
  plain, un-variant table) — future-proofing only, verified inert today.

## Relationship to the fidelity specs

`DisplayLeftRailFidelity.spec.ts` asserts real `getComputedStyle` values for
several of these same tokens (e.g. the divider colour, the D14 band, the
AutofillCollapse header hex). Those assertions are the actual literal
values, not variable references — so **retheming means updating both**
`_theme-tokens.scss` and the relevant spec-file literal in the same change,
never just one. This pass changed zero of those literals (see Verification),
because every value it introduced already equalled what those specs already
enforced.

## Verification (2026-07-24 pass)

- `DisplayLeftRailFidelity.spec.ts` (11 tests) and `DisplayPage.spec.ts`
  (33 tests) — both pass unchanged, before and after the corner-radius
  token addition.
- `npx tsc --noEmit` — clean.
- `npm test` (jest) — 65 suites / 573 tests pass.
- `npx prettier@2.7.1 --check` — clean on every changed file.
- `next build` (static export) — compiles cleanly.
- Pixel-sampled before/after screenshots of the two previously-grey modal
  surfaces named in the task (Search Settings modal, the grid-selector/
  Cardback-picker modal) confirm the exact swap: background sampled at
  `rgb(78, 93, 108)` (`#4e5d6c`) before, `rgb(34, 48, 63)` (`#22303f`)
  after, at the same coordinate in both. `variant="secondary"` buttons in
  the same screenshots (e.g. "Close Without Saving") are pixel-identical
  before/after, confirming the approved-panel surfaces weren't touched.
