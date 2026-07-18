/**
 * A higher-level wrapper for the `Card` component with additional functionality.
 * Card slots allow modifying the selected image for the given slot number and face,
 * both via previous/next arrows and the grid selector. Clicking the selected image
 * displays the detailed view. Card slots can be deleted, which also deletes the
 * card slot for the same slot number in the other face.
 */

import { useSortable } from "@dnd-kit/react/sortable";
import React, { memo, useRef, useState } from "react";
import Dropdown from "react-bootstrap/Dropdown";

import {
  CardSelectedEventName,
  getCardSelectedEventDetail,
} from "@/common/cardDom";
import {
  areSearchQueriesEqual,
  doesSearchQueryFilterOnPrinting,
} from "@/common/processing";
import {
  Faces,
  SearchQuery,
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import { useLongPress } from "@/common/useLongPress";
import { wrapIndex } from "@/common/utils";
import { RightPaddedIcon } from "@/components/icon";
import { MemoizedEditorCard } from "@/features/card/Card";
import { CardFooter } from "@/features/card/CardFooter";
import { CardSlotContextMenu } from "@/features/card/CardSlotContextMenu";
import {
  CardSlotMenuAction,
  getCardSlotMenuActions,
} from "@/features/card/CardSlotMenuActions";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { GridSelectorModal } from "@/features/gridSelector/GridSelectorModal";
import { selectCardDocumentByIdentifier } from "@/store/slices/cardDocumentsSlice";
import { showChangeQueryModal } from "@/store/slices/modalsSlice";
import {
  bulkAlignMemberSelection,
  bulkRemovePrintingFilter,
  deleteSlots,
  duplicateSlot,
  expandSelection,
  selectAllSelectedProjectMembersHaveTheSameQuery,
  selectProjectMember,
  selectSelectedSlots,
  setSelectedImages,
  toggleMemberSelection,
} from "@/store/slices/projectSlice";
import { selectSearchResultsForQueryOrDefault } from "@/store/slices/searchResultsSlice";
import store from "@/store/store";

interface CardSlotProps {
  id: string;
  searchQuery: SearchQuery | undefined;
  face: Faces;
  slot: number;
}

//# region grid selector

interface CardSlotGridSelectorProps {
  face: Faces;
  slot: number;
  searchResultsForQuery: Array<string>;
  selectedImage?: string;
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
  setSelectedImageFromIdentifier: {
    (selectedImage: string): void;
  };
  searchq?: string;
}

export function CardSlotGridSelector({
  face,
  slot,
  searchResultsForQuery,
  selectedImage,
  show,
  handleClose,
  setSelectedImageFromIdentifier,
  searchq,
}: CardSlotGridSelectorProps) {
  return (
    <GridSelectorModal
      testId={`${face}-slot${slot}-grid-selector`}
      imageIdentifiers={searchResultsForQuery}
      selectedImage={selectedImage}
      show={show}
      handleClose={handleClose}
      onClick={setSelectedImageFromIdentifier}
      searchq={searchq}
    />
  );
}

export const MemoizedCardSlotGridSelector = memo(CardSlotGridSelector);

//# endregion

// Proposal C part (a) (docs/proposals/proposal-c-context-menu-restyle.md): renders whatever
// action list its caller passes in - CardSlot builds that list once (getCardSlotMenuActions)
// and shares it with both this dropdown AND the new right-click/long-press context menu below,
// per the approved "one menu component, two triggers" decision. This component owns only the
// 3-dot toggle + Popper-anchored Dropdown.Menu chrome, not the actions themselves anymore.
const CardGridContextMenu = ({
  actions,
}: {
  actions: CardSlotMenuAction[];
}) => {
  return (
    <Dropdown className="card-context-menu" align="end">
      <Dropdown.Toggle
        variant=""
        aria-label="More options"
        data-testid="more-select-options"
      >
        <i className="bi bi-three-dots" />
      </Dropdown.Toggle>
      <Dropdown.Menu>
        {actions.map((action) => (
          <Dropdown.Item key={action.key} onClick={action.onClick}>
            <RightPaddedIcon bootstrapIconName={action.bootstrapIconName} />{" "}
            {action.label}
          </Dropdown.Item>
        ))}
      </Dropdown.Menu>
    </Dropdown>
  );
};

//# region card slot

export function CardSlot({ id, searchQuery, face, slot }: CardSlotProps) {
  //# region queries and hooks

  const dispatch = useAppDispatch();
  const { ref, handleRef, isDragging } = useSortable({ id, index: slot });
  const elementRef = useRef<Element | null>(null);
  const setElementRef = (element: Element | null) => {
    ref(element);
    elementRef.current = element;
  };
  const searchResultsForQueryOrDefault = useAppSelector((state) =>
    selectSearchResultsForQueryOrDefault(
      state,
      searchQuery?.query,
      searchQuery?.cardType,
      searchQuery?.expansionCode,
      searchQuery?.collectorNumber,
      face
    )
  );
  const projectMember = useAppSelector((state) =>
    selectProjectMember(state, face, slot)
  );
  const selectedImage = projectMember?.selectedImage;
  const selectedSlots = useAppSelector(selectSelectedSlots);
  const selectedQuery = useAppSelector((state) =>
    selectAllSelectedProjectMembersHaveTheSameQuery(state, selectedSlots)
  );
  const modifySelectedSlots =
    selectedSlots.length > 1 &&
    projectMember?.selected &&
    areSearchQueriesEqual(selectedQuery, searchQuery);
  const slotsToModify: Array<[Faces, number]> = modifySelectedSlots
    ? selectedSlots
    : [[face, slot]];

  //# endregion

  //# region state

  const [showGridSelector, setShowGridSelector] = useState<boolean>(false);
  // Proposal C part (a): the right-click/long-press context menu's own open state - null when
  // closed, the trigger's viewport (x, y) when open. Separate from showGridSelector/the 3-dot
  // dropdown's own internal state (react-bootstrap's Dropdown owns that itself).
  const [contextMenuPosition, setContextMenuPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);

  //# endregion

  //# region callbacks

  const handleCloseGridSelector = () => setShowGridSelector(false);
  const handleShowGridSelector = () => setShowGridSelector(true);
  const handleShowChangeSelectedImageQueriesModal = () => {
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
  const closeContextMenu = () => setContextMenuPosition(null);
  const handleContextMenu = (event: React.MouseEvent) => {
    event.preventDefault();
    setContextMenuPosition({ x: event.clientX, y: event.clientY });
  };
  const longPressHandlers = useLongPress((x, y) =>
    setContextMenuPosition({ x, y })
  );
  const toggleSelectionForThisMember = (
    event: React.MouseEvent<HTMLButtonElement>
  ) => {
    if (event.detail === 2) {
      // double-click
      dispatch(bulkAlignMemberSelection({ slot, face }));
    } else if (event.shiftKey) {
      // shift-click
      dispatch(expandSelection({ slot, face }));
    } else {
      dispatch(toggleMemberSelection({ slot, face }));
    }
  };

  const setSelectedImageFromIdentifier = (selectedImage: string) => {
    dispatch(
      setSelectedImages({
        slots: slotsToModify,
        selectedImage,
        deselect: true,
      })
    );
    const selectedCardDocument = selectCardDocumentByIdentifier(
      store.getState(),
      selectedImage
    );
    if (elementRef.current != null && selectedCardDocument != null) {
      elementRef.current.dispatchEvent(
        new CustomEvent(CardSelectedEventName, {
          bubbles: true,
          composed: true,
          detail: getCardSelectedEventDetail(selectedCardDocument),
        })
      );
    }
  };

  //# endregion

  //# region computed constants

  const searchResultsForQuery = searchResultsForQueryOrDefault ?? [];
  const selectedImageIndex: number | undefined =
    selectedImage != null
      ? searchResultsForQuery.indexOf(selectedImage)
      : undefined;
  const previousImage: string | undefined =
    selectedImageIndex != null
      ? searchResultsForQuery[
          wrapIndex(selectedImageIndex + 1, searchResultsForQuery.length)
        ]
      : undefined;
  const nextImage: string | undefined =
    selectedImageIndex != null
      ? searchResultsForQuery[
          wrapIndex(selectedImageIndex - 1, searchResultsForQuery.length)
        ]
      : undefined;
  const cardHeaderTitle = `Slot ${slot + 1}`;
  // Proposal C part (a): single source of truth for the slot's actions, shared by the 3-dot
  // dropdown below and the right-click/long-press context menu rendered at the bottom of this
  // component - "one menu component, two triggers" per the approved decision. Reuses the
  // stringified-query version of change-query (previously only nameOnClick's own behavior;
  // CardGridContextMenu's old inline handler passed the raw query with no expansion/collector
  // suffix) rather than keeping two subtly different implementations of the same action.
  const menuActions = getCardSlotMenuActions({
    onChangeQuery: handleShowChangeSelectedImageQueriesModal,
    onDuplicate: () => dispatch(duplicateSlot({ slot, quantity: 1 })),
    onDelete: () => dispatch(deleteSlots({ slots: [slot] })),
    onUnfilterPrinting: () =>
      dispatch(bulkRemovePrintingFilter({ slots: [[face, slot]] })),
    showUnfilterPrinting: !!doesSearchQueryFilterOnPrinting(searchQuery),
  });
  const cardHeaderButtons = (
    <>
      <button
        className="card-select"
        onClick={toggleSelectionForThisMember}
        aria-label={`select-${face}${slot}`}
      >
        <i
          className={`bi bi${
            projectMember?.selected ?? false ? "-check" : ""
          }-square`}
          aria-label={`${face}${slot}-${
            projectMember?.selected ?? false ? "" : "un"
          }checked`}
        ></i>
      </button>
      <CardGridContextMenu actions={menuActions} />
    </>
  );
  const cardFooter = (
    <CardFooter
      searchResults={searchResultsForQuery}
      selectedImageIndex={selectedImageIndex}
      selected={projectMember?.selected ?? false}
      setSelectedImageFromIdentifier={setSelectedImageFromIdentifier}
      handleShowGridSelector={handleShowGridSelector}
    />
  );

  //# endregion

  return (
    <div
      ref={setElementRef}
      data-testid={`${face}-slot${slot}`}
      style={{ opacity: isDragging ? 0.7 : undefined }}
      onContextMenu={handleContextMenu}
      {...longPressHandlers}
    >
      <MemoizedEditorCard
        imageIdentifier={selectedImage}
        previousImageIdentifier={previousImage}
        nextImageIdentifier={nextImage}
        cardHeaderTitle={cardHeaderTitle}
        cardFooter={cardFooter}
        cardHeaderButtons={cardHeaderButtons}
        handleRef={handleRef}
        searchQuery={searchQuery}
        nameOnClick={handleShowChangeSelectedImageQueriesModal}
        noResultsFound={
          searchResultsForQueryOrDefault != null &&
          searchResultsForQueryOrDefault.length === 0
        }
      />

      {selectedImage != null && (
        <DeckbuilderConfirmAffordance
          cardIdentifier={selectedImage}
          searchQuery={searchQuery}
          onOpenGridSelector={handleShowGridSelector}
        />
      )}

      {searchResultsForQuery.length > 1 && showGridSelector && (
        <MemoizedCardSlotGridSelector
          face={face}
          slot={slot}
          searchResultsForQuery={searchResultsForQuery}
          selectedImage={selectedImage}
          show={showGridSelector}
          handleClose={handleCloseGridSelector}
          setSelectedImageFromIdentifier={setSelectedImageFromIdentifier}
          searchq={searchQuery?.query ?? undefined}
        />
      )}

      {contextMenuPosition != null && (
        <CardSlotContextMenu
          actions={menuActions}
          position={contextMenuPosition}
          onClose={closeContextMenu}
        />
      )}
    </div>
  );
}

export const MemoizedCardSlot = memo(CardSlot);

//# endregion
