/**
 * The display page rail's Slot Actions section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Same action list
 * (getCardSlotMenuActions), same handlers, as CardSlot.tsx's own 3-dot dropdown/context menu -
 * "rendered as a plain action list inside the section body instead of a dropdown/context-menu
 * overlay," per the design doc's own component-mapping row for this section.
 *
 * Editor-polish round (EP4, SPEC-editor-polish.md §D.1 `.slotacts-top .iact`, REV RD5) - gains
 * an additive, optional `compact` prop: `32×30` icon-only buttons in a horizontal, wrapping row
 * (rail-head placement, beside the subject image), instead of the full-width `outline-*` button
 * column below (still the bottom `ControlStack`'s own look before this round - now retired
 * entirely, since EP4 moves every caller of this component to `compact`). Same `menuActions`,
 * same handlers, same per-action `data-testid`s either way - only the layout/size differs, so
 * every existing "click `display-slot-action-delete`" test keeps working regardless of which
 * variant is mounted.
 *
 * diverges from upstream: upstream renders the CardSlotMenuActions list only as Dropdown.Items /
 * a context menu (CardSlotContextMenu.tsx); this rail renders the SAME action list as a button
 * row/column instead. Behavior/actions are identical; only the presentation diverges
 * (SPEC-display-left-rail.md §8's buttons-look-like-buttons audit; SPEC-editor-polish.md §D.1).
 */
import styled from "@emotion/styled";
import React from "react";
import Button from "react-bootstrap/Button";

import { doesSearchQueryFilterOnPrinting } from "@/common/processing";
import { Faces, SearchQuery, useAppDispatch } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { getCardSlotMenuActions } from "@/features/card/CardSlotMenuActions";
import { showChangeQueryModal } from "@/store/slices/modalsSlice";
import {
  bulkRemovePrintingFilter,
  deleteSlots,
  duplicateSlot,
} from "@/store/slices/projectSlice";

// EP4 - the compact rail-head icon button: 32×30, 14px glyph, transparent/`#abb6c2`/1px
// `#abb6c2`, danger variant `#f0a6a3`/1px `#d9534f`, hover fills solid. A plain `.danger`
// CLASS, not a transient (`$`-prefixed) styled-component prop: emotion only auto-filters
// `$`-prefixed props from reaching the DOM when `styled()` wraps a plain intrinsic tag
// (`styled.button`) - wrapping another REACT COMPONENT (`styled(Button)`, as here) can't do
// that filtering, since `Button` itself has no idea a `$`-prefixed prop needs stripping before
// its own `...rest` spread onto the native `<button>` (confirmed live - the unfiltered version
// of this component leaked a literal `$danger="true"` DOM attribute, a real React console
// warning, not just a lint nit).
const IconAction = styled(Button)`
  width: 32px;
  height: 30px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
  background: transparent;
  color: var(--theme-light);
  border: 1px solid var(--theme-light);

  &:hover:not(:disabled),
  &:focus:not(:disabled) {
    background: var(--theme-light);
    color: var(--theme-btn-ink);
  }

  &.danger {
    color: #f0a6a3;
    border-color: var(--bs-danger);
  }

  &.danger:hover:not(:disabled),
  &.danger:focus:not(:disabled) {
    background: var(--bs-danger);
    /* Tokyo-11 ink flip - danger is light, dark ink reads far better (6.46:1 vs. 2.65:1). */
    color: var(--theme-btn-ink);
  }
`;

interface SlotActionsSectionProps {
  face: Faces;
  slot: number;
  searchQuery: SearchQuery | undefined;
  /** Called after Delete so the rail can drop back to its idle state - the just-deleted slot's
   * own selection reference would otherwise dangle, pointing at a slot that no longer exists. */
  onDeleted: () => void;
  /** EP4 - `true` (the rail-head mount) renders the compact icon row; omitted/`false` (no
   * remaining caller after this round, kept for the "additive, behaviour-preserving prop" rule)
   * keeps the original full-width labelled button column. */
  compact?: boolean;
}

export function SlotActionsSection({
  face,
  slot,
  searchQuery,
  onDeleted,
  compact = false,
}: SlotActionsSectionProps) {
  const dispatch = useAppDispatch();

  // Mirrors CardSlot.tsx's own handleShowChangeSelectedImageQueriesModal - the stringified-query
  // form (with expansion/collector-number suffix) the change-query modal expects, not the raw
  // SearchQuery object.
  const handleChangeQuery = () => {
    let stringifiedSearchQuery: string | null = null;
    if (searchQuery?.query) {
      stringifiedSearchQuery = searchQuery.query;
      if (searchQuery.expansionCode) {
        stringifiedSearchQuery += ` (${searchQuery.expansionCode})`;
        if (searchQuery.collectorNumber) {
          stringifiedSearchQuery += ` ${searchQuery.collectorNumber}`;
        }
      }
    }
    dispatch(
      showChangeQueryModal({
        slots: [[face, slot]],
        query: stringifiedSearchQuery,
      })
    );
  };

  const menuActions = getCardSlotMenuActions({
    onChangeQuery: handleChangeQuery,
    onDuplicate: () => dispatch(duplicateSlot({ slot, quantity: 1 })),
    onDelete: () => {
      dispatch(deleteSlots({ slots: [slot] }));
      onDeleted();
    },
    onUnfilterPrinting: () =>
      dispatch(bulkRemovePrintingFilter({ slots: [[face, slot]] })),
    showUnfilterPrinting: !!doesSearchQueryFilterOnPrinting(searchQuery),
  });

  if (compact) {
    // EP4 (§D.1 `.slotacts-top .iact`) - icon-only, 32×30, in a wrapping row beside the subject
    // image; `aria-label` carries the action's own label text since there's no visible text
    // here for it to come from.
    return (
      <div
        className="d-flex flex-wrap slotacts-top"
        style={{ gap: "6px", marginTop: "8px" }}
        data-testid="display-slot-actions-section"
      >
        {menuActions.map((action) => (
          <IconAction
            key={action.key}
            className={action.key === "delete" ? "iact danger" : "iact"}
            size="sm"
            onClick={action.onClick}
            aria-label={action.label}
            title={action.label}
            data-testid={`display-slot-action-${action.key}`}
          >
            <i
              className={`bi bi-${action.bootstrapIconName}`}
              aria-hidden="true"
            />
          </IconAction>
        ))}
      </div>
    );
  }

  return (
    <div
      className="d-flex flex-column"
      // CSS-fidelity pass (SPEC-display-left-rail.md §2/§8, 2026-07-23) - `gap-2` (0.5rem/8px)
      // approximated the density table's own literal "button stack gap:6px" - no exact Bootstrap
      // spacing-scale match, so it's set directly, same as the rest of this round's exact-px
      // values (`.d14`/`.ufilter`/`.vgrid` etc).
      style={{ gap: "6px" }}
      data-testid="display-slot-actions-section"
    >
      {/* Buttons-look-like-buttons audit (SPEC-display-left-rail.md §8): these were already real
          `Button`s, not bare text rows as the audit's own summary table (item 4) describes -
          `outline-secondary` (`$secondary`/`#4e5d6c` on the dark rail surface) was the actual
          near-invisible problem the audit's rule targets, not the element type. `Delete` (the
          one destructive action, keyed off `getCardSlotMenuActions`' own "delete" key) gets
          `outline-danger`; every other action gets `outline-light` (`$light`/`#abb6c2`) instead
          of the near-invisible `outline-secondary`. `w-100` replaces Bootstrap 4's removed
          `btn-block` (BS5 idiom) so each action still fills the rail's width. */}
      {menuActions.map((action) => (
        <Button
          key={action.key}
          variant={action.key === "delete" ? "outline-danger" : "outline-light"}
          size="sm"
          className="text-start w-100"
          onClick={action.onClick}
          data-testid={`display-slot-action-${action.key}`}
        >
          <RightPaddedIcon bootstrapIconName={action.bootstrapIconName} />
          {action.label}
        </Button>
      ))}
    </div>
  );
}
