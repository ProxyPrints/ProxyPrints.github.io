As of: 2026-07-18
What this is: Proposal C — (a) a right-click/long-press context menu on editor card slots, (b) a solid-color utilitarian restyle direction. Part (a) is APPROVED (4 decisions below) and built this pass. Part (b)'s direction is still HOLD pending its own token-build PR, per the owner's explicit "Part (b)'s first increment follows as its own PR."

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

### Decisions (approved) and what was built

1. **Coexist, don't replace.** `CardGridContextMenu` (the 3-dot dropdown) is unchanged in behavior — it still works exactly as before, now rendering from a shared action list instead of its own inline handlers. The right-click/long-press menu is a second, independent trigger for the same actions.
2. **Multi-select scope: v1 matches current behavior exactly.** Delete/duplicate/change-query stay single-slot (identical to the 3-dot dropdown's existing scope, since both now literally call the same handlers) — no new multi-select logic was added. Extending delete/duplicate to multi-select is logged as a real, separate follow-up (task #38 in this session's tracker), not folded into this PR, since it touches destructive-action confirm design.
3. **Long-press: pointer-events based, no library.** `frontend/src/common/useLongPress.ts` - a `pointerdown` + `setTimeout` + cancel-on-move/up/cancel implementation, touch-only (`event.pointerType === "touch"`; mouse users get the real `onContextMenu` trigger instead, so a mouse "long press" was never built - it would fight the slot's other mouse interactions, like dnd-kit's sortable drag handle). Never calls `preventDefault` on `pointerdown`/`pointermove`, so native scroll is never blocked - a real scroll gesture's movement exceeds the tolerance almost immediately, canceling the timer.
   **Collision check with the Level-0 compare-pin** (`DeckbuilderConfirmAffordance.tsx`): verified by reading its source - it uses `onMouseEnter`/`onMouseLeave`/`onClick` only, no `onPointerDown`/`onTouchStart`/timer-based gesture of any kind. There is no long-press there to collide with; confirmed, not assumed.
4. Menu content: same 4 items the 3-dot dropdown already had (Change Query, Duplicate, Unfilter Printing when applicable, Delete) - **not** the 5-item list with "Change Image" this doc's earlier survey draft proposed. "Change image" was never part of `CardGridContextMenu`'s own content (it lives on the card's counter/footer instead) — the approved decision was "same menu content as the 3-dot button," so the shipped menu matches that literally rather than the earlier draft's mistaken addition.

**Shipped** (branch `claude/proposal-c-context-menu-restyle`): `frontend/src/features/card/CardSlotMenuActions.ts` (the single action-list definition, shared by both triggers), `frontend/src/common/useLongPress.ts`, `frontend/src/features/card/CardSlotContextMenu.tsx` (the positioned popup - deliberately NOT built on react-bootstrap's `Dropdown`, which anchors to a toggle element via Popper rather than an arbitrary point; instead renders plain elements with Bootstrap's own `.dropdown-menu`/`.dropdown-item` CSS classes directly, fixed-positioned at the trigger's (x, y), for visual parity without fighting Popper's anchor assumption), and `CardSlot.tsx`'s wiring (`onContextMenu` + the long-press handlers on the slot's root element, plus lifting the action-list construction out of `CardGridContextMenu` into `CardSlot` itself as the shared source of truth).

**One incidental fix while unifying the two menus**: `CardGridContextMenu`'s old inline "Change Query" handler passed `searchQuery?.query ?? null` with no expansion code/collector number - a different, less complete implementation than `CardSlot`'s own `nameOnClick` handler (used when clicking the card's name), which builds a full `"query (SET) NUM"` string. Unifying into one shared handler required picking one; kept the more complete version, so the 3-dot dropdown's "Change Query" now pre-fills the same as clicking the card name always did.

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
