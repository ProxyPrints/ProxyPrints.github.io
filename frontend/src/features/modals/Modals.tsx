import React from "react";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { MemoizedCardDetailedView } from "@/features/cardDetailedView/CardDetailedViewModal";
import { ChangeQueryModal } from "@/features/changeQuery/ChangeQueryModal";
import { InvalidIdentifiersModal } from "@/features/invalidIdentifiers/InvalidIdentifiersModal";
import { selectHiddenCardIdentifiersSet } from "@/store/slices/hiddenCardsSlice";
import {
  hideModal,
  selectModalProps,
  selectShownModal,
} from "@/store/slices/modalsSlice";

export function Modals() {
  //# region queries and hooks

  const dispatch = useAppDispatch();
  const modalProps = useAppSelector(selectModalProps);
  const shownModal = useAppSelector(selectShownModal);
  const hiddenCardIdentifiers = useAppSelector(selectHiddenCardIdentifiersSet);

  //# endregion

  //# region callbacks

  const handleClose = () => dispatch(hideModal());

  //# endregion

  // TODO: move the grid selector into here

  return (
    <>
      {modalProps !== null && (
        <>
          {"cardDetailedView" in modalProps &&
            !hiddenCardIdentifiers.has(
              modalProps.cardDetailedView.card.identifier
            ) && (
              <MemoizedCardDetailedView
                cardDocument={modalProps.cardDetailedView.card}
                show={shownModal === "cardDetailedView"}
                handleClose={handleClose}
              />
            )}
          {"changeQuery" in modalProps && (
            <ChangeQueryModal
              slots={modalProps.changeQuery.slots}
              query={modalProps.changeQuery.query}
              show={shownModal === "changeQuery"}
              handleClose={handleClose}
            />
          )}
        </>
      )}
      <InvalidIdentifiersModal
        show={shownModal === "invalidIdentifiers"}
        handleClose={handleClose}
      />
    </>
  );
}
