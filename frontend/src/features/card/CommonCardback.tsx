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
import { MemoizedEditorCard } from "@/features/card/Card";
import {
  countBackFacesAffectedByApplyAll,
  resolveCustomBackSlotThumbnails,
} from "@/features/card/cardbackApply";
import { CardbackApplyPrompt } from "@/features/card/CardbackApplyPrompt";
import { setUserDefaultCardback } from "@/features/card/cardbackDefaultPreference";
import { CardbackSwatchStrip } from "@/features/card/CardbackSwatchStrip";
import { CardFooter } from "@/features/card/CardFooter";
import { GridSelectorModal } from "@/features/gridSelector/GridSelectorModal";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  applyCardbackToAllSlots,
  bulkReplaceSelectedImage,
  selectProjectCardback,
  selectProjectMembers,
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
  const projectMembers = useAppSelector(selectProjectMembers);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();
  const filterCardbacks = useAppSelector(
    (state) => selectSearchSettings(state).searchTypeSettings.filterCardbacks
  );

  //# endregion

  //# region state

  // Cardback flow round (SPEC-cardback-pdfwait.md §C.2) - the toolbar entry is project-wide
  // canonical: a pick already bulk-replaces every slot following the OLD project cardback, so the
  // apply/default prompt renders inline in THIS SAME modal (never a second stacked one) once a
  // pick has been made, rather than closing immediately - `closeOnSelect={false}` below.
  const [lastPickedImage, setLastPickedImage] = useState<string | undefined>(
    undefined
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
    }
    dispatch(setSelectedCardback({ selectedImage: image, explicit: true }));
    setLastPickedImage(image);
  };

  const handleApplyAll = () => {
    if (lastPickedImage != null) {
      dispatch(applyCardbackToAllSlots({ selectedImage: lastPickedImage }));
    }
  };
  const handleSetDefault = () => {
    if (lastPickedImage != null) {
      void setUserDefaultCardback(lastPickedImage);
    }
  };
  const handleModalClose = (
    event?: React.MouseEvent<HTMLButtonElement, MouseEvent>
  ) => {
    setLastPickedImage(undefined);
    if (event != null) {
      handleClose(event);
    } else {
      handleClose();
    }
  };

  //# endregion

  //# region computed constants

  const customBackThumbnails =
    lastPickedImage != null
      ? resolveCustomBackSlotThumbnails(
          projectMembers,
          lastPickedImage,
          cardDocumentsByIdentifier
        )
      : [];

  //# endregion

  return (
    <GridSelectorModal
      title="Select Cardback"
      testId="cardback-grid-selector"
      imageIdentifiers={searchResults}
      selectedImage={projectCardback}
      show={show}
      handleClose={handleModalClose}
      onClick={setSelectedImageFromIdentifier}
      applySearchSettings={filterCardbacks}
      closeOnSelect={false}
      footerContent={
        lastPickedImage != null && (
          <CardbackApplyPrompt
            affectedCount={countBackFacesAffectedByApplyAll(
              projectMembers,
              lastPickedImage
            )}
            customBackThumbnails={customBackThumbnails}
            onApplyAll={handleApplyAll}
            onSetDefault={handleSetDefault}
            onDismiss={() => setLastPickedImage(undefined)}
          />
        )
      }
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
          explicit: true,
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

//# region cardback rail control (R9, editor-repass round)

/**
 * The right rail's Cardback section on the unified display page (DisplayPage.tsx) - the R9
 * swatch-strip surface replacing the old single `CardbackToolbarButton` trigger. The strip
 * (`CardbackSwatchStrip`) IS the picker: a pick dispatches the same project-wide
 * `bulkReplaceSelectedImage`/`setSelectedCardback` pair the modal's own grid uses. The two
 * project-wide actions sit beneath the strip as plain buttons with the R9 task's exact names,
 * acting on the strip's currently-selected project cardback (the apply/set-default prompt
 * component itself is for the modal's own footer - see `CommonCardbackGridSelector`). A
 * "Browse all cardbacks…" button keeps the full `GridSelectorModal` (filters/sort/search)
 * reachable, unchanged - proposal-h's own strip + "Choose cardback…" pairing, so the modal
 * stays the page's one full-browse path and its existing test coverage keeps a host.
 */
export function CardbackRailControl() {
  const dispatch = useAppDispatch();
  const searchResults = useAppSelector(selectCardbacks);
  const projectCardback = useAppSelector(selectProjectCardback);

  const [showGridSelector, setShowGridSelector] = useState<boolean>(false);
  const [applyDone, setApplyDone] = useState(false);
  const [defaultDone, setDefaultDone] = useState(false);

  const handleSelect = (image: string) => {
    setApplyDone(false);
    setDefaultDone(false);
    if (projectCardback != null) {
      dispatch(
        bulkReplaceSelectedImage({
          currentImage: projectCardback,
          selectedImage: image,
          face: Back,
        })
      );
    }
    dispatch(setSelectedCardback({ selectedImage: image, explicit: true }));
  };

  const handleApplyAll = () => {
    if (projectCardback != null) {
      dispatch(applyCardbackToAllSlots({ selectedImage: projectCardback }));
      setApplyDone(true);
    }
  };
  const handleSetDefault = () => {
    if (projectCardback != null) {
      // Annex A-2 - seam-mocked: no real persistence layer exists for the default preference yet.
      void setUserDefaultCardback(projectCardback);
      setDefaultDone(true);
    }
  };
  const handleShowGridSelector = () => setShowGridSelector(true);
  const handleCloseGridSelector = () => setShowGridSelector(false);

  return (
    <div data-testid="cardback-rail-control">
      <h6>Cardback (project)</h6>
      <CardbackSwatchStrip
        imageIdentifiers={searchResults}
        selectedImage={projectCardback}
        onSelect={handleSelect}
        testId="cardback-rail-strip"
      />
      <div className="d-flex flex-wrap gap-2 mt-2">
        <Button
          size="sm"
          variant={applyDone ? "outline-success" : "outline-secondary"}
          disabled={projectCardback == null}
          onClick={handleApplyAll}
          data-testid="cardback-rail-apply-all-button"
        >
          {applyDone ? "Applied to all ✓" : "Apply to all card backs"}
        </Button>
        <Button
          size="sm"
          variant={defaultDone ? "outline-success" : "outline-secondary"}
          disabled={projectCardback == null}
          onClick={handleSetDefault}
          data-testid="cardback-rail-set-default-button"
        >
          {defaultDone ? "Default set ✓" : "Set as my default cardback"}
        </Button>
      </div>
      <Button
        size="sm"
        variant="outline-light"
        className="mt-2"
        onClick={handleShowGridSelector}
        // Named/visible enough to find, but never caught by a generic /Cardback/ name locator
        // (it's "Browse all cardbacks…", not a bare "Cardback" label) - test-utils and specs
        // use the dedicated testid below, the same discipline the old toolbar button's own
        // OWNER AMENDMENT 3 comment called for.
        data-testid="cardback-browse-all-button"
      >
        Browse all cardbacks…
      </Button>
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
