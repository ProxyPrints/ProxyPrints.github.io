/**
 * The display page rail's Slot Actions accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Same action list
 * (getCardSlotMenuActions), same handlers, as CardSlot.tsx's own 3-dot dropdown/context menu -
 * "rendered as a plain action list inside the section body instead of a dropdown/context-menu
 * overlay," per the design doc's own component-mapping row for this section.
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
      className="d-flex flex-column gap-1"
      data-testid="display-slot-actions-section"
    >
      {menuActions.map((action) => (
        <Button
          key={action.key}
          variant="outline-secondary"
          size="sm"
          className="text-start"
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
