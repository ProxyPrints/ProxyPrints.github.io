/**
 * A higher-level wrapper for the `Card` component with additional functionality.
 * Similar to the `CardSlot` component, but tailored specifically for use with
 * the project cardback (displayed in the right panel of the project editor).
 */

import React, { memo, useState } from "react";
import Button from "react-bootstrap/Button";

import { Back } from "@/common/constants";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { wrapIndex } from "@/common/utils";
import { RightPaddedIcon } from "@/components/icon";
import { MemoizedEditorCard } from "@/features/card/Card";
import { CardFooter } from "@/features/card/CardFooter";
import { GridSelectorModal } from "@/features/gridSelector/GridSelectorModal";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import {
  bulkReplaceSelectedImage,
  selectProjectCardback,
  setSelectedCardback,
} from "@/store/slices/projectSlice";
import { selectSearchSettings } from "@/store/slices/searchSettingsSlice";

//# region grid selector

interface CommonCardbackGridSelectorProps {
  searchResults: Array<string>;
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
}

export function CommonCardbackGridSelector({
  searchResults,
  show,
  handleClose,
}: CommonCardbackGridSelectorProps) {
  //# region queries and hooks

  const dispatch = useAppDispatch();
  const projectCardback = useAppSelector(selectProjectCardback);
  const filterCardbacks = useAppSelector(
    (state) => selectSearchSettings(state).searchTypeSettings.filterCardbacks
  );

  //# endregion

  //# region callbacks

  const setSelectedImageFromIdentifier = (image: string): void => {
    if (projectCardback != null) {
      dispatch(
        bulkReplaceSelectedImage({
          currentImage: projectCardback,
          selectedImage: image,
          face: Back,
        })
      );
      dispatch(setSelectedCardback({ selectedImage: image }));
    }
  };

  //# endregion

  return (
    <GridSelectorModal
      title="Select Cardback"
      testId="cardback-grid-selector"
      imageIdentifiers={searchResults}
      selectedImage={projectCardback}
      show={show}
      handleClose={handleClose}
      onClick={setSelectedImageFromIdentifier}
      applySearchSettings={filterCardbacks}
    />
  );
}

export const MemoizedCommonCardbackGridSelector = memo(
  CommonCardbackGridSelector
);

//# endregion

//# region common cardback

interface CommonCardbackProps {
  selectedImage: string | undefined;
}

export function CommonCardback({ selectedImage }: CommonCardbackProps) {
  //# region queries and hooks

  const dispatch = useAppDispatch();
  const searchResults = useAppSelector(selectCardbacks);

  //# endregion

  //# region state

  const [showGridSelector, setShowGridSelector] = useState<boolean>(false);

  //# endregion

  //# region callbacks

  const handleCloseGridSelector = () => setShowGridSelector(false);
  const handleShowGridSelector = () => setShowGridSelector(true);
  const setSelectedImageFromIdentifier = (image: string): void => {
    if (selectedImage != null && selectedImageIndex != null) {
      dispatch(
        bulkReplaceSelectedImage({
          currentImage: selectedImage,
          selectedImage: image,
          face: Back,
        })
      );
      dispatch(
        setSelectedCardback({
          selectedImage: image,
        })
      );
    }
  };

  //# endregion

  //# region computed constants

  const selectedImageIndex: number | undefined =
    selectedImage != null ? searchResults.indexOf(selectedImage) : undefined;
  const previousImage: string | undefined =
    selectedImageIndex != null
      ? searchResults[wrapIndex(selectedImageIndex + 1, searchResults.length)]
      : undefined;
  const nextImage: string | undefined =
    selectedImageIndex != null
      ? searchResults[wrapIndex(selectedImageIndex - 1, searchResults.length)]
      : undefined;
  const cardHeaderTitle = "Cardback";
  const cardFooter = (
    <CardFooter
      searchResults={searchResults}
      selectedImageIndex={selectedImageIndex}
      selected={false}
      setSelectedImageFromIdentifier={setSelectedImageFromIdentifier}
      handleShowGridSelector={handleShowGridSelector}
    />
  );

  //# endregion

  return (
    <div data-testid="common-cardback">
      <MemoizedEditorCard
        imageIdentifier={selectedImage}
        previousImageIdentifier={previousImage}
        nextImageIdentifier={nextImage}
        cardHeaderTitle={cardHeaderTitle}
        cardFooter={cardFooter}
        noResultsFound={searchResults.length === 0}
      />
      {showGridSelector && (
        <MemoizedCommonCardbackGridSelector
          searchResults={searchResults}
          show={showGridSelector}
          handleClose={handleCloseGridSelector}
        />
      )}
    </div>
  );
}

//# endregion

//# region cardback toolbar button (issue #240, design doc §5's CommonCardback row)

/**
 * A standalone trigger for the same self-contained cardback picker `CommonCardback` (above)
 * already owns - for a surface with no per-slot swatch/prev-next `CardFooter` to hang a "change"
 * button off (the unified display page's toolbar, `DisplayPage.tsx`), this exposes just the
 * button+modal half directly rather than the full swatch card. Reuses
 * `MemoizedCommonCardbackGridSelector`'s existing `GridSelectorModal` verbatim - same
 * `searchCardbacks` results, same `bulkReplaceSelectedImage`/`setSelectedCardback` dispatch on
 * selection. NOT the same "no modal, ever" exception the design doc's §4.4′ carves out for the
 * per-slot Choose Image picker - that ban is specifically about a second modal stacking over an
 * already-open rail/drawer; this standalone, project-wide picker opens directly from the toolbar
 * with nothing else open behind it, so it keeps its existing modal as-is (see §5's row).
 */
export function CardbackToolbarButton() {
  const searchResults = useAppSelector(selectCardbacks);

  const [showGridSelector, setShowGridSelector] = useState<boolean>(false);
  const handleShowGridSelector = () => setShowGridSelector(true);
  const handleCloseGridSelector = () => setShowGridSelector(false);

  return (
    <>
      <Button
        size="sm"
        variant="outline-secondary"
        onClick={handleShowGridSelector}
      >
        <RightPaddedIcon bootstrapIconName="image" />
        Cardback
      </Button>
      {showGridSelector && (
        <MemoizedCommonCardbackGridSelector
          searchResults={searchResults}
          show={showGridSelector}
          handleClose={handleCloseGridSelector}
        />
      )}
    </>
  );
}

//# endregion
