# Theming — the token file, the layering, and the "born grey" fix

Two rounds live in this doc: the 2026-07-24 **theme-defaults pass** (fixed
"born grey" Bootstrap components by giving every override one canonical
token source) and the 2026-07-24 **Tokyo-11 re-theme** (swapped the palette
itself — this is the token file's first real "retheme the site" exercise,
and the section below on what that surfaced supersedes anything the
theme-defaults pass implied about how easy a repaint would be).

## The token file

[`frontend/src/styles/_theme-tokens.scss`](../../frontend/src/styles/_theme-tokens.scss)
is the single source of truth for the site's palette, corner-radius,
spacing, and type tokens. It defines plain SCSS variables (`$theme-*`) with
no Bootstrap dependency — nothing in this file imports Bootstrap or
Bootswatch — plus (added by the Tokyo-11 pass) a `:root { --theme-*: ...; }`
block that re-exposes the same values as CSS custom properties for
styled-components/inline-style call sites that can't reach a SCSS variable
(see "Runtime CSS-custom-property bridge" below).

**Current palette: "Tokyo-11"** (2026-07-24, owner ruling on the
theme-options palette-exploration study — 12 candidate palettes compared
under a strict-AAA contrast bar). Palette 11, "Tokyo × orange-action +
purple-accent": a Tokyo Night dark-navy base, a warm orange action colour,
and an additive purple accent layer, with Semi (6/8/10px) corner radii. This
supersedes the #302/`SPEC-display-left-rail.md` §D.0 palette the token file
previously reproduced verbatim — see that spec's own §D.0 header for a
pointer back to this file instead of a line-by-line color sync going
forward (its sizing/spacing rows are untouched and remain authoritative).

Colour tokens (darkest → most-raised):

| Token                   | Value                        | What it's for                                                                                                         |
| ----------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `$theme-body-bg`        | `#1a1b26`                    | page background, the darkest layer                                                                                    |
| `$theme-raised-bg`      | `#24283b`                    | floating chrome one step off the page — rail-head/artist-line, the Sources list + filter inputs                       |
| `$theme-panel-bg`       | `#2f3549`                    | Card bodies (incl. `AutofillCollapse`'s "demoted body"), the D14 seticon, secondary buttons/badges (`$secondary`)     |
| `$theme-card-header-bg` | `#2f3548`                    | one hex digit off `$theme-panel-bg`, mechanically preserving the #302 "deliberately distinct" pattern (see below)     |
| `$theme-band-bg`        | `#222234`                    | the D14 confidence-strip token ("conf" in the study)                                                                  |
| `$theme-divider`        | `#16161e`                    | every rail block boundary                                                                                             |
| `$theme-text`           | `#c0caf5`                    | body text — 7.54:1 on panel, 9.02:1 on raised (STRICT-AAA both)                                                       |
| `$theme-muted`          | `#a3aad0`                    | muted text/placeholder — WCAG/APCA audit remediation (2026-07-24, PR #432); see "Checked WCAG 2.2 criteria" below     |
| `$theme-light`          | = `$theme-text`              | not an audited study token — aliased to text, see the token file's own comment for why                                |
| `$theme-primary`        | `#ff9e64`                    | action colour — every button (8.40:1 STRICT-AAA with the flipped ink)                                                 |
| `$theme-primary-hover`  | `darken($theme-primary, 8%)` | derived by formula this round, not a hand-picked literal                                                              |
| `$theme-success`        | `#9ece6a`                    | success (9.35:1 STRICT-AAA)                                                                                           |
| `$theme-danger`         | `#f7768e`                    | danger (6.46:1 — AAA-LARGE only; see its own token-file comment)                                                      |
| `$theme-warning`        | `#e0af68`                    | warning (8.55:1 STRICT-AAA)                                                                                           |
| `$theme-info`           | `#7dcfff`                    | NOT a study-audited token — Tokyo Night's own cyan swatch, chosen to keep the pre-existing small "link" text AAA-safe |
| `$theme-btn-ink`        | `#1a1b26`                    | the "btn-ink" study token — the one dark ink used on every button variant                                             |
| `$theme-accent`         | `#bb9af7`                    | additive, UI-role-only — see "Accent scope boundary" below                                                            |
| `$theme-input-border`   | = `$theme-panel-bg`          | now a reference, not a coincidentally-equal literal                                                                   |

Corner-radius tokens — **"Semi"** tier (2026-07-24 Tokyo-11 ruling; was
"Flat"/`0` under the #302 palette):

| Token                | Value  | What it's for                                                                                                                    |
| -------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `$theme-radius-none` | `0`    | no rounding, ever — kept distinct from `-base`                                                                                   |
| `$theme-radius-sm`   | `6px`  | Bootstrap's `-sm` tier (small buttons/inputs)                                                                                    |
| `$theme-radius-base` | `6px`  | the sitewide default tier — buttons/inputs, including their own `-lg` variants (the study's table doesn't grow buttons past 6px) |
| `$theme-radius-card` | `8px`  | **new this round** — cards/modals/popovers/dropdowns, wired to `$border-radius-lg`                                               |
| `$theme-radius-pill` | `10px` | our own "status-pill" component convention (D14 statepill, etc) — unchanged; see "two different pills" below                     |

Both radius families changed from `0`/flat to the values above this round —
see Verification below for how that was checked (this is NOT a
zero-rendered-pixels pass the way the original theme-defaults round was;
radii visibly changed everywhere Bootstrap's own radius vars reach).

### Spacing scale (2026-07-24 owner extension)

A 4/8-based ladder — `$theme-space-1` (4px) through `$theme-space-6`
(32px), also exposed as `--theme-space-1`…`-6`. **Future-specs-only**: this
scale governs new spec rounds going forward. It does **not** retroactively
re-space any shipped surface — no component was touched to make an existing
value land on it. Some existing values are off-scale and stay that way
until their own spec is next revised for an unrelated reason:

| Surface                   | Shipped value | On the 4/8 ladder?                | Owning spec row                               |
| ------------------------- | ------------- | --------------------------------- | --------------------------------------------- |
| D14 band padding          | `8px 10px`    | `8px` yes, `10px` no              | `SPEC-rail-delegacy.md` §D.1 `.d14`           |
| Rail-head padding         | `8px 10px`    | `8px` yes, `10px` no              | `SPEC-rail-delegacy.md` §D.1 `.rail-head`     |
| Filters float panel width | `440px`       | n/a (a width, not a spacing step) | `SPEC-rail-delegacy.md` §D (Filters panel)    |
| `.notthis` pill padding   | `2px 10px`    | `2px`/`10px` no                   | `SPEC-editor-polish.md` §D.2 `.notthis` (EP8) |

### Type ramp (2026-07-24 owner extension)

`$theme-font-2xs` (10px) through `$theme-font-xl` (18px) — same
future-specs-only rule as spacing. Several existing rail/editor microtype
sizes (10/11/12/13/14/15px) already happen to land on these exact steps —
that's pre-existing coincidence in the shipped `SPEC-rail-delegacy.md`/
`SPEC-editor-polish.md` values, not this pass re-specing anything to match.

## Provenance convention (added this round — the doc had none before)

**Finding from this being the doc's first real "retheme the site"
exercise**: the pre-existing instructions here said nothing about how to
record a palette's licensing provenance when swapping it — the task that
drove the Tokyo-11 pass had to invent the convention below rather than
follow one. Fixed in place:

Whenever `_theme-tokens.scss`'s palette values change, the file's own
top-of-file header comment must carry a **PROVENANCE** line: the palette's
name, license, copyright holder, and an explicit "color values only, no
code" statement, matching this fork's [external code provenance
policy](../../CLAUDE.md) (values may be freely referenced; code reuse needs
a bounded-absorption path, never applies to a handful of hex constants
anyway). Any token pulling from a source OUTSIDE the named palette itself
(this round's `$theme-info`, drawn from the same upstream project's cyan
swatch but not one of the study's own 10 audited tokens) gets its own
inline comment explaining the deviation and its separate provenance
justification, right at that variable — not just in the file header.

## Accent scope boundary (new token this round)

`$theme-accent` is **additive** and **UI-role-only**. It is wired to:

- the D14 confidence pill (`.statepill.suggested`) and score badge
  (`.seticon .score`)
- the Sources list toggle's ON state (`.rail-source-toggle .toggle-on`)
- version-selection outlines (`.mpccard-highlight`, used by both
  `SelectVersionResults.tsx`'s grid and `CardResultSet.tsx`'s search-result
  highlight)
- the print sheet's selected-slot outline (`PagePreview.tsx`)

It is **never** applied to small paragraph/body text — the accent purple
clears only 6.74:1 on the D14 band surface (below strict-AAA-normal's 7:1),
"near-strict" per the study, legible on bold pill text/borders/outlines but
not prose. Bootstrap's global `$link-color` is **deliberately not** routed
to accent — it stays on `$primary` (orange), matching the pre-existing
convention several components already use `var(--bs-primary)` for
link-styled text (`Navbar.tsx`, `Footer.tsx`, `AuthWidget.tsx`). The
handful of small cyan "info" links elsewhere (`DisplayPage.tsx`'s identify
panel, `SharedDeckViewer.tsx`) stay on `$theme-info` instead, precisely
because they're small text and accent isn't AAA-safe there — see
`$theme-info`'s own token-file comment.

## Runtime CSS-custom-property bridge (added this round)

Two independent, parallel bridges expose token values to code that can't
read a SCSS `$theme-*` variable directly (styled-components/emotion
template literals, inline `style={}` props):

1. **`var(--bs-*)`** — Bootstrap 5.3's own `_root.scss` (imported via the
   Superhero/Bootstrap core chain below) automatically emits every
   `$theme-colors` entry (`$primary`/`$secondary`/`$success`/`$info`/
   `$warning`/`$danger`), `$body-bg`/`$body-color`, and the
   `$border-*`/`$border-radius*` family as `--bs-*` custom properties, all
   generated FROM the SCSS variables `styles.scss` sets from tokens. As
   soon as `styles.scss` assigns `$primary: $theme-primary` (etc — see that
   file's own "Tokyo-11: $theme-colors overrides" comment), every
   `var(--bs-primary)` consumer picks up the new value automatically, with
   zero additional wiring — this is true for `Navbar.tsx`/`Footer.tsx`/
   `AuthWidget.tsx`'s existing links AND for every react-bootstrap
   component's own internals (Bootstrap 5.3's `button-variant()` mixin
   itself emits `--bs-btn-bg`/`--bs-btn-color`/etc scoped per `.btn-*`
   rule, then reads them back via `var()` — so `.btn-primary`'s actual
   paint IS already runtime-var-driven, not a compiled-in literal).
2. **`var(--theme-*)`** — `_theme-tokens.scss`'s own `:root` block (see
   that file) for the tokens Bootstrap has no equivalent for: raised-bg,
   card-header-bg, band-bg, divider, muted, light, accent (+ its `-rgb`
   triplet), btn-ink, primary-hover, the radius-card/spacing tokens.
   Deliberately NOT duplicated here even though a component-friendly name
   would be nice: `--bs-body-bg`/`--bs-body-color` (+`-rgb`)/`--bs-primary`
   (+`-rgb`)/`--bs-secondary` (+`-rgb`, this literally IS
   `$theme-panel-bg`)/`--bs-success`/`--bs-danger`/`--bs-warning`/
   `--bs-info` (each +`-rgb`) already exist via bridge 1 — a second
   `--theme-*` copy of any of those would be a second source of truth for
   the same value, exactly what this bridge exists to prevent. Component
   code reaches for `var(--bs-secondary)` (not a hypothetical
   `--theme-panel-bg`) for the panel role, `var(--bs-body-color-rgb)` (not
   a hypothetical `--theme-text-rgb`) for text-tinted translucent borders,
   and so on.

**Scope discipline**: this is a bridge, not a migration. It makes the
_existing_ `--bs-*` surface Bootstrap already emits reachable and correct,
and adds the _missing_ `--theme-*` surface for tokens with no Bootstrap
equivalent — it does not convert every component's compiled SCSS/literal
CSS onto `var()` wholesale. Concretely:

- Component-local styled-components/inline styles compile to literal
  colour values UNLESS they explicitly reference `var(--bs-*)` or
  `var(--theme-*)` (this pass converted the surfaces enumerated in "What
  this pass swept," below — not every hex literal that ever existed
  sitewide).
- **Known potential-divergence surface, flagged rather than converted**:
  `custom.css`'s `.mpccard-highlight`/`.mpccard-hover` box-shadow glow uses
  `rgba(var(--theme-accent-rgb), .6)`/`rgba(var(--bs-body-color-rgb), .3)` —
  runtime-var-driven. If a future change ever needs those two effects to
  differ in intensity or hue from the raw accent/text tokens (e.g. a
  "selected" glow that should stay orange even after an accent-repainting
  re-theme), that divergence would have to be an explicit new token, not a
  silent literal edit to this file, since the whole point of the bridge is
  that editing `_theme-tokens.scss` is enough.
- Bootstrap's OWN internal component CSS (buttons, the border/radius
  family) is inherently kept in sync by mechanism 1 above without any
  fork-side literal to maintain at all — there is no divergence risk there
  by construction.

## The layering

[`frontend/src/styles/styles.scss`](../../frontend/src/styles/styles.scss)
is the only file that imports Bootstrap/Bootswatch, and it now follows one
rule throughout: **every Bootstrap variable override assigns from a
`$theme-*` token, never a literal hex/number.** Concretely, in this order:

1. `@import "theme-tokens";` — pulls in every `$theme-*` variable above.
2. A block of plain SCSS variable assignments (`$dark`, `$input-bg`,
   `$card-cap-bg`, `$modal-content-bg`, `$border-radius`,
   `$btn-border-radius`, `$primary`/`$secondary`/`$success`/`$danger`/
   `$warning`/`$info`, `$body-bg`/`$body-color`, `$color-contrast-dark`,
   `$min-contrast-ratio`, `$focus-ring-color`/`$focus-ring-opacity`/
   `$focus-ring-width`, `$btn-close-width`/`$btn-close-color`, etc.), each
   set to a `$theme-*` token (or, for the last two focus-ring inputs, a
   literal opacity/width that isn't itself a palette colour).
3. `@import "~bootswatch/dist/superhero/variables";` then the Bootstrap
   core imports.

Step 2 has to come before step 3 because Bootswatch/Bootstrap declare their
own defaults with SCSS's `!default` flag — a variable already assigned
(step 2) is left alone by every later `!default` assignment downstream,
Bootswatch's or Bootstrap core's alike. This is the same mechanism the
pre-existing `$dark`/`$input-bg`/`$input-color` overrides (issue #302) always
used; the theme-defaults pass extended it to the "born grey" components, and
the Tokyo-11 pass extends it again to `$primary`/`$secondary`/`$success`/
`$danger`/`$warning`/`$info`/`$body-bg`/`$body-color` — under #302 these
happened to already equal Superhero's own stock defaults, so no override was
ever needed; Tokyo-11 diverges from every one of them, surfacing the gap.

**To retheme the site**, edit `_theme-tokens.scss` only — every consumer
(the Bootstrap variable overrides in `styles.scss`, the `var(--bs-*)`/
`var(--theme-*)` runtime bridge, and any fidelity spec asserting one of
these values, see below) is meant to pick the new value up automatically or
need a one-line spec update, never a hunt through component files for a
scattered literal. The Tokyo-11 pass is the first real test of that claim —
see "What this pass swept" below for what still needed a manual per-file
edit versus what really was free.

## AAA contrast policy (owner-ruled 2026-07-24) + accessibility checklist

**Contrast**: two thresholds, from the theme-options study's own AAA
policy block, apply to every colour pairing in this palette:

- **AAA-normal, 7:1** — required for body/paragraph/small text (anything
  under ~18px or non-bold).
- **AAA-large, 4.5:1** — the floor for large/bold UI text (buttons, pills,
  headings).

A pairing is **STRICT-AAA-everywhere** only when it clears 7:1 even on
button/pill text. Tokyo-11 clears strict-AAA on body text (7.54/9.02:1) and
on 3 of 4 button variants (primary 8.40, success 9.35, warning 8.55); danger
(6.46:1 with the mandated `$theme-btn-ink`) is the one AAA-large-only
exception — see `$theme-danger`'s own token-file comment. **APCA is
advisory only** — this fork's binding bar is the WCAG 2.x relative-luminance
ratio above, computed the same way the study computed it (worst-case
surface, sRGB relative luminance); APCA numbers aren't tracked or asserted
anywhere in this codebase today.

**Checked WCAG 2.2 criteria** (a parallel audit, PR #432's report, is the
enforcement pass for these — this doc states the policy, that audit is where
conformance against it gets measured and tracked; cross-link from here
rather than duplicating its findings). Four concrete fixes from that
report's theme-layer findings were folded into this same pass:

- **Target size (2.5.8, ≥ 24×24 CSS px)**:
  - `.btn-close` (modal/offcanvas/toast dismiss ×, ~15 mounts sitewide)
    measured a stock 21×21 — `$btn-close-width` lifted to `25px` in
    `styles.scss`, a single theme-layer fix covering every mount. Self-
    verified via a real `boundingBox()` read in the fidelity spec (issue
    #434's own lesson: authored CSS isn't proof of the rendered size), not
    just the authored variable.
  - `.fbtoggle .btn` (the rail-head Front/Back segmented toggle,
    `DisplayPage.tsx`) measured 51–55×23px, 1px under the floor with no
    qualifying spacing exception — owner-ruled amendment (2026-07-24):
    `min-height: 24px` added (padding unchanged, so the segment's visual
    density doesn't change). Self-verified the same way (real
    `boundingBox()`, not authored CSS).
- **Focus visible / non-text contrast (2.4.7/2.4.11/1.4.11, ≥ 3:1)**:
  Bootstrap's default focus ring (`rgba($primary, .25)`) measured
  1.18–1.56:1 against this theme's dark surfaces — a 25%-alpha ring's real
  contrast depends on what's underneath it, which is exactly how it failed.
  Fixed at the single shared `$focus-ring-*` variable family every
  focus-visible surface sitewide derives from (`styles.scss`):
  `$focus-ring-color: $theme-accent` (not `$primary` — a distinct UI-signal
  colour, consistent with accent's UI-role contract) and
  `$focus-ring-opacity: 1` (fully opaque, so the ring's contrast is simply
  accent-vs-background, not blended with whatever's under a translucent
  ring). Accent measures 7.39/6.30/5.26:1 against body/raised/panel — every
  one clears 3:1 with real margin even on the toughest surface (panel).
  `$focus-ring-width` bumped `0.25rem` (4px) → `2px` for a crisper outline.
  Self-verified in the fidelity spec via the real `--bs-focus-ring-color`
  custom property Bootstrap emits, computed against panel.
- **Reduced motion**: `@media (prefers-reduced-motion: reduce)` disables
  transitions/animations — already the convention this codebase's other
  animated surfaces (e.g. `WhatsThatWords.tsx`) follow; this pass didn't
  add any new motion.

**WCAG-vs-APCA divergence note** (same audit): the audit computed
`$theme-muted` (originally `#8c94bf`) at APCA Lc 44.1 on body — adequate
only for large/bold text, but this token backs 10–13px legends/captions
sitewide. Lightened to `#a3aad0` rather than split into a second
"`-strong`" token (most call sites genuinely are small captions, and one
token is simpler to keep in sync than auditing every call site's own
font-weight/size to route it correctly). APCA itself isn't computable in
this repo's toolchain (no APCA library available in this environment), so
the remediation was verified via the WCAG proxy instead: contrast lifted
from 5.78/4.93/4.11 (body/raised/panel) to 7.50/6.39/5.34 — now clears
strict-AAA-normal on body, comes within a hair of it on raised, and clears
AA-normal (4.5) with real margin even on panel. This is the fork's standing
APCA policy going forward: **APCA numbers from an external audit are
treated as directional signal, remediated via the WCAG relative-luminance
formula this codebase can actually compute** — a real APCA library would
need to land in this repo before APCA itself could become a binding,
self-verified metric here.

## The "born grey" inventory the 2026-07-24 theme-defaults pass fixed

Superhero's own `_variables.scss` sets several component defaults straight
to `$gray-600` (`#4e5d6c`, the #302 palette's own panel colour) — correct
for the "panel" role under #302 (`$theme-panel-bg` was the _same_ value,
deliberately), but wrong for surfaces that are conceptually "raised chrome"
floating above the page, which should read `$theme-raised-bg` instead.
Nothing had ever routed these away from the Superhero stock value, so every
consumer was "born grey":

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

**What's grey on purpose — do not "fix" this.** `$theme-panel-bg`
(`#2f3549` under Tokyo-11; was `#4e5d6c`, Superhero's native
`$secondary`/`$gray-600`, under #302) is the _correct, approved_ token for:
Bootstrap Card bodies (including `AutofillCollapse`'s "demoted body" —
`SPEC-display-left-rail.md` §D.1 explicitly locked this role, just not this
exact hex any more), the D14 seticon, and `variant="secondary"`
buttons/badges. Under #302 this token happened to equal Superhero's own
`$gray-600` stock default, so no explicit `$secondary` override was needed;
Tokyo-11 breaks that coincidence, so `styles.scss` now explicitly sets
`$secondary: $theme-panel-bg` to keep this exact role intact under the new
palette (see that file's own "Tokyo-11: $theme-colors overrides" comment).
`$card-bg`itself remains deliberately untouched by either pass — routing it to`$theme-raised-bg` would be a fidelity regression against the
spec-locked Card-body role. If a surface still looks grey/wrong after a
retheme, check whether it's one of these approved-panel surfaces before
assuming it's a leftover default.

**Two different pills.** Bootstrap's own `$border-radius-pill` (default
`50rem`, a true stadium shape) already backs a real, unrelated pill usage —
e.g. `SearchSettings.tsx`'s `<Badge pill>`. `$theme-radius-pill` (`10px`)
is our own separate "status-pill" component convention (D14 `.statepill`,
etc.), applied as a literal at each call site, never through Bootstrap's
pill variable. Wiring `$border-radius-pill` to `10px` would have visibly
reshaped the `<Badge pill>` — deliberately not done, and still not done by
the Tokyo-11 radius pass.

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

## What this pass swept (Tokyo-11, 2026-07-24)

Beyond the token file and `styles.scss` wiring above, this pass migrated
every hardcoded old-#302-palette hex literal it found outside the token
file, across: `DisplayPage.tsx`, `SelectVersionResults.tsx`,
`SourcesAccordion.tsx`, `ConfidenceElement.tsx`, `RequestedPrintingBadge.tsx`,
`SlotActionsSection.tsx`, `Card.tsx`, `AutofillCollapse.tsx`,
`PagePreview.tsx`, `custom.css`, `SourceSettings.tsx`,
`SharedDeckViewer.tsx`, `AuthWidget.tsx` — each hex replaced with the
matching `var(--bs-*)`/`var(--theme-*)` reference (or, in `ConfidenceElement.tsx`'s
case, none needed — its only colour literals were danger-tint values now
sourced from `var(--theme-danger-rgb)`). `Footer.tsx`/`Navbar.tsx` already
used `var(--bs-primary)` before this pass (pre-existing precedent this
pass's bridge extends) and needed no changes.

## Relationship to the fidelity specs

`DisplayLeftRailFidelity.spec.ts` asserts real `getComputedStyle` values for
several of these same tokens (e.g. the divider colour, the D14 band, the
AutofillCollapse header hex). Those assertions are the actual literal
values, not variable references — so **retheming means updating both**
`_theme-tokens.scss` and the relevant spec-file literal in the same change,
never just one. The Tokyo-11 pass updated every one of that spec's colour
assertions to the new computed `rgb()`/`rgba()` values (comment-linked
per-row to this ruling) — see that spec file's own header comment for the
full list and docs/features/theming.md's Verification section below for how
they were re-derived.

## Verification (2026-07-24 theme-defaults pass)

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

## Verification (2026-07-24 Tokyo-11 pass)

- Self-measured computed-style token-conformance extraction (Playwright,
  1400px and 390px viewports): every sampled body/raised/panel/band/
  divider/text/primary/success/danger/warning/accent/btn-ink/radius surface
  matched its binding hex/px value — see the PR body for the exact mismatch
  count and sample list.
- Contrast spot-assertions added to the fidelity spec for the AAA pairs
  (text-on-panel, btn-ink-on-primary) — both pass their asserted thresholds.
- `DisplayLeftRailFidelity.spec.ts` and `DisplayPage.spec.ts` — full suites
  green with the updated literal values (colours/radii) described above.
- `npx tsc --noEmit`, `npm test` (jest), `npx prettier@2.7.1 --check`,
  `next build` — see the PR body for pass/fail and counts.
- Screenshots: `/display` editor at 1400px and 390px, a modal, and the
  `/print` page — paths in the PR body.
