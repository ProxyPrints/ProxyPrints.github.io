/**
 * Proposal C part (a) (docs/proposals/proposal-c-context-menu-restyle.md) - the slot-action
 * list shared by the existing 3-dot dropdown (CardSlot.tsx's CardGridContextMenu) and the new
 * right-click/long-press context menu (CardSlotContextMenu.tsx). One list of actions, two
 * trigger surfaces, per the approved decision ("one menu component, two triggers") - this
 * module is the "one menu" half; each trigger renders the same array with its own markup.
 */

export interface CardSlotMenuAction {
  key: string;
  label: string;
  bootstrapIconName: string;
  onClick: () => void;
}

export interface CardSlotMenuActionHandlers {
  onChangeQuery: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onUnfilterPrinting: () => void;
  /** Mirrors CardGridContextMenu's existing doesSearchQueryFilterOnPrinting(searchQuery) gate -
   * only this one action is conditional; the rest always show. */
  showUnfilterPrinting: boolean;
}

/**
 * Same 4 actions, same order, as the existing 3-dot dropdown - deliberately NOT including
 * "change image" (that lives on the card's own counter/footer, not this menu, in the current
 * app) or any new action, per the approved scope: this menu's content is defined as "the same
 * as the 3-dot button," not a superset.
 */
export function getCardSlotMenuActions(
  handlers: CardSlotMenuActionHandlers
): CardSlotMenuAction[] {
  const actions: CardSlotMenuAction[] = [
    {
      key: "change-query",
      label: "Change Query",
      bootstrapIconName: "arrow-repeat",
      onClick: handlers.onChangeQuery,
    },
    {
      key: "duplicate",
      label: "Duplicate",
      bootstrapIconName: "copy",
      onClick: handlers.onDuplicate,
    },
  ];
  if (handlers.showUnfilterPrinting) {
    actions.push({
      key: "unfilter-printing",
      label: "Unfilter Printing",
      bootstrapIconName: "filter",
      onClick: handlers.onUnfilterPrinting,
    });
  }
  actions.push({
    key: "delete",
    label: "Delete",
    bootstrapIconName: "x-circle",
    onClick: handlers.onDelete,
  });
  return actions;
}
