As of: 2026-07-18
What this is: survey + mocks + HOLD for Proposal C — (a) a right-click/long-press context menu on editor card slots, (b) a solid-color utilitarian restyle direction. Scope deliberately kept small per the approving instruction: "C is survey+mocks+HOLD, not blind build." No code in this pass.

## Part (a) — context menu

### Survey: the actions already exist, just not the gesture

`frontend/src/features/card/CardSlot.tsx` already has every "obvious slot action" named in the approved scope — as a 3-dot dropdown button (`CardGridContextMenu`, a `react-bootstrap` `Dropdown` despite the misleading name; it isn't a right-click menu today), not a right-click/long-press surface. This means Proposal C's real new work is narrower than it first sounds: the actions and their Redux wiring are done; what's missing is triggering the same menu from `onContextMenu`/long-press instead of only a click on the 3-dot icon.

| Action | Existing handler | Dispatch |
|---|---|---|
| Change image | `handleShowGridSelector` (local state) | opens `GridSelectorModal`; selection → `setSelectedImages` (`projectSlice`) |
| Change query ("jump to search" in the approved scope — see note below) | `handleShowChangeSelectedImageQueriesModal` | `showChangeQueryModal` (`modalsSlice`) → opens `ChangeQueryModal` |
| Duplicate | `duplicateThisSlot` | `duplicateSlot` (`projectSlice`) |
| Delete | `deleteThisSlot` | `deleteSlots` (`projectSlice`) |
| Unfilter printing (conditional — only shown when the slot's query filters on printing) | `removePrintingFilter` | `bulkRemovePrintingFilter` (`projectSlice`) |

**Note on "jump to search"**: the approved scope's phrase doesn't literally match anything in the codebase. The closest existing action is "Change Query," which opens `ChangeQueryModal` to search again for this slot — that's what this doc proposes the context menu calls "jump to search" maps to. Flagging the terminology gap rather than silently assuming; if "jump to search" meant something else (e.g. navigating to `/explore` pre-filtered on this card), that doesn't exist today and would be new scope.

**Greenfield, no collision risk**: no `onContextMenu`, long-press, or gesture-detection code exists anywhere in `frontend/src` today — nothing to reuse for the gesture itself, but also nothing to avoid breaking.

### Proposed menu list (desktop right-click / mobile long-press)

Same five items as the table above, in the same order the existing dropdown already uses, styled to match `CardGridContextMenu`'s existing `RightPaddedIcon` + bootstrap-icon pattern (`bi-arrow-repeat`, `bi-copy`, `bi-filter`, `bi-x-circle`) so it reads as "the same menu, new entry point" rather than a second, differently-styled menu living alongside the first. Recommend the new context menu **call the exact same `Dropdown.Item onClick` handlers** already defined in `CardSlot.tsx` rather than reimplementing the five actions — the only new code is the trigger (gesture → open a menu positioned at cursor/touch point) and, on mobile, distinguishing a long-press from a scroll/drag gesture.

### Open decisions (owner sign-off needed before code)

1. **Does the new context menu replace the 3-dot dropdown, or coexist with it?** The 3-dot button is a real, working affordance for anyone who doesn't know right-click/long-press exists (discoverability) — recommend coexist, at least initially.
2. **Multi-select scope**: the survey found `setSelectedImages` (image-change actions) is already multi-select-aware via `slotsToModify`, but delete/duplicate/change-query are single-slot only in today's dropdown. Should a context-menu invocation on a slot that's part of a multi-selection act on the whole selection (matching how multi-select works elsewhere in the editor) or stay single-slot like today's dropdown? This is a real scope decision, not just styling — recommend matching today's dropdown behavior (single-slot) for v1, extending to multi-select only as a deliberate follow-up.
3. **Mobile long-press gesture library**: build a minimal custom long-press handler (a `setTimeout` + move-cancels-it pattern, ~20 lines, no new dependency) vs. pull in a small library. Recommend the custom handler — the gesture is simple enough that a dependency isn't obviously worth it, but flagging as a real choice rather than assuming.

## Part (b) — solid-color utilitarian restyle direction

### Current baseline

`frontend/src/styles/styles.scss` uses Bootswatch's **Superhero** theme (a dark theme with soft shadows/gradients on cards, buttons, and dropdowns) with one custom override (`$primary: #4c9be8`, a mid blue). This is the ONLY theme customization in the codebase today — everything else is stock Superhero + stock Bootstrap component imports. A "solid-color utilitarian" direction, inspired by Proxxied's aesthetic per the approved scope, is a genuine visual shift from Superhero's own soft/gradient default, not a small tweak.

### Direction proposal (tokens, not a build)

The instinct: strip Superhero's soft-shadow/gradient chrome down to flat, high-contrast fills and hairline borders, while staying inside Bootstrap's existing SCSS variable system (`$primary`, `$secondary`, `$body-bg`, etc.) rather than hand-rolling new components — the approved scope explicitly says "respecting the existing Bootstrap system."

- **Color**: keep the current blue (`#4c9be8`) as `$primary` — no reason to relitigate a working brand color — but flatten `$card-bg`/`$dropdown-bg`/`$btn-*` box-shadow variables to `none` and reduce border-radius tokens (`$border-radius`, `$btn-border-radius`) toward 2-4px instead of Superhero's rounder default. A secondary neutral (a slightly blue-shifted dark grey, not pure `#000`/`#222`) for panel backgrounds, distinct from the current near-black Superhero body background, would read as "chosen" rather than "default dark theme."
- **Type**: no change proposed — Superhero's default system-font stack is already utilitarian; a restyle direction doesn't need a type change to read as "flat/utilitarian," and swapping fonts is a bigger, separate-worthy decision.
- **Component-level**: buttons/dropdowns/cards lose their shadow + heavy rounding; badges/alerts keep semantic color (success/warning/danger) unchanged — utilitarian means flat and legible, not monochrome; losing at-a-glance status color would be a regression, not a style win.

### Explicitly not proposed here

No CSS diff, no before/after screenshot, no SCSS variable file edit. Per the approved scope ("mocks/design-tokens proposal only... NO sweeping restyle build without a separate go"), turning the direction above into an actual token set and screenshot comparison is real design work deserving its own pass, once the direction itself (flatten shadows/rounding, keep the existing blue, don't touch type) is confirmed as the right one to pursue.

### Open decision

**Scope of the eventual restyle build, if approved**: global (every Bootstrap component touched by the flattened tokens, one PR) vs. incremental (start with the highest-traffic surfaces — editor card slots, the navbar — and expand later). Recommend incremental once this direction is approved, to keep any single restyle PR reviewable.
