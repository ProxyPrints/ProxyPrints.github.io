/**
 * The display page rail's Slot Actions accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Same action list
 * (getCardSlotMenuActions), same handlers, as CardSlot.tsx's own 3-dot dropdown/context menu -
 * "rendered as a plain action list inside the section body instead of a dropdown/context-menu
 * overlay," per the design doc's own component-mapping row for this section.
 *
 * diverges from upstream: upstream renders the CardSlotMenuActions list only as Dropdown.Items /
 * a context menu (CardSlotContextMenu.tsx); this rail renders the SAME action list as a stacked
 * outline-light/outline-danger button column instead. Behavior/actions are identical; only the
 * presentation diverges (SPEC-display-left-rail.md §8's buttons-look-like-buttons audit).
 */
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

interface SlotActionsSectionProps {
  face: Faces;
  slot: number;
  searchQuery: SearchQuery | undefined;
  /** Called after Delete so the rail can drop back to its idle state - the just-deleted slot's
   * own selection reference would otherwise dangle, pointing at a slot that no longer exists. */
  onDeleted: () => void;
}

export function SlotActionsSection({
  face,
  slot,
  searchQuery,
  onDeleted,
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

  return (
    <div
      className="d-flex flex-column gap-2"
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
