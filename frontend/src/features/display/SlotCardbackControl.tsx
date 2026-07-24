/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2, `PKG1b` rail entry) - the left rail's
 * per-slot cardback control: a thumbnail of the slot's own resolved back face + a "Choose a
 * different back…" button. Unlike the toolbar entry (`CommonCardbackGridSelector`, a
 * project-wide `GridSelectorModal` pick), this is a per-slot pick - it dispatches
 * `setSelectedImages` for THIS SLOT'S back face only, never `bulkReplaceSelectedImage`/
 * `setSelectedCardback` (those are project-wide concepts).
 *
 * "No modal, ever" (§C.2's own text: "the rail per-slot picker is already the 'no modal, ever'
 * surface") - reuses `GridSelectorResults`'s `"embedded"` variant + `useGridSelectorSearch`
 * directly (the exact same pair `SelectVersionResults.tsx` already uses for the rail's own
 * front/back art picker), never `GridSelectorModal`.
 */
import styled from "@emotion/styled";
import React, { useRef, useState } from "react";
import Button from "react-bootstrap/Button";

import { Back } from "@/common/constants";
import { useAppDispatch, useAppSelector } from "@/common/types";
import {
  countBackFacesAffectedByApplyAll,
  resolveCustomBackSlotThumbnails,
} from "@/features/card/cardbackApply";
import { CardbackApplyPrompt } from "@/features/card/CardbackApplyPrompt";
import { setUserDefaultCardback } from "@/features/card/cardbackDefaultPreference";
import { GridSelectorResults } from "@/features/gridSelector/GridSelectorResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  applyCardbackToAllSlots,
  selectProjectMembers,
  setSelectedImages,
} from "@/store/slices/projectSlice";

const Thumb = styled.div<{ $url: string | undefined }>`
  flex: 0 0 54px;
  width: 54px;
  aspect-ratio: 63 / 88;
  border: 1px solid rgba(var(--bs-body-color-rgb), 0.15);
  position: relative;
  background-color: #2a2320;
  background-image: ${(props) =>
    props.$url != null ? `url(${props.$url})` : "none"};
  background-size: cover;
  background-position: center;

  .cap {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.6);
    color: #a99;
    font-size: 8px;
    text-align: center;
    padding: 1px;
  }
`;

const Row = styled.div`
  display: flex;
  gap: 9px;
  align-items: flex-start;
`;

const Meta = styled.div`
  flex: 1;
  min-width: 0;

  .bname {
    font-size: 13px;
    color: var(--bs-body-color);
  }

  .bsub {
    font-size: 11px;
    color: var(--theme-muted);
  }
`;

export interface SlotCardbackControlProps {
  slot: number;
  /** The slot's own current back-face image, whatever it resolves to today (following the
   * project cardback, or already custom). */
  backImage: string | undefined;
  projectCardback: string | undefined;
}

export function SlotCardbackControl({
  slot,
  backImage,
  projectCardback,
}: SlotCardbackControlProps) {
  const dispatch = useAppDispatch();
  const projectMembers = useAppSelector(selectProjectMembers);
  const cardbackSearchResults = useAppSelector(selectCardbacks);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();

  const [pickerOpen, setPickerOpen] = useState(false);
  const [lastPickedImage, setLastPickedImage] = useState<string | undefined>(
    undefined
  );
  const focusRef = useRef<HTMLInputElement>(null);

  const search = useGridSelectorSearch({
    imageIdentifiers: cardbackSearchResults,
    active: pickerOpen,
  });

  const backDocument =
    backImage != null ? cardDocumentsByIdentifier[backImage] : undefined;
  const isCustom =
    backImage != null &&
    projectCardback != null &&
    backImage !== projectCardback;

  const handlePick = (image: string) => {
    dispatch(
      setSelectedImages({ selectedImage: image, slots: [[Back, slot]] })
    );
    setLastPickedImage(image);
    setPickerOpen(false);
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

  const customBackThumbnails =
    lastPickedImage != null
      ? resolveCustomBackSlotThumbnails(
          projectMembers,
          lastPickedImage,
          cardDocumentsByIdentifier
        )
      : [];

  return (
    <div data-testid="slot-cardback-control">
      <Row>
        <Thumb $url={backDocument?.smallThumbnailUrl}>
          <span className="cap">{isCustom ? "custom back" : "deck back"}</span>
        </Thumb>
        <Meta>
          <div className="bname">
            {backDocument?.name ?? "Deck default back"}
          </div>
          <div className="bsub">
            {isCustom ? "custom for this slot" : "follows project cardback"}
          </div>
          <Button
            size="sm"
            variant="outline-light"
            className="mt-1"
            data-testid="slot-cardback-choose"
            onClick={() => setPickerOpen((previous) => !previous)}
          >
            {pickerOpen ? "Cancel" : "Choose a different back…"}
          </Button>
        </Meta>
      </Row>
      {pickerOpen && (
        <div className="mt-2" data-testid="slot-cardback-picker">
          <GridSelectorResults
            variant="embedded"
            imageIdentifiers={cardbackSearchResults}
            selectedImage={backImage}
            onSelectImage={handlePick}
            focusRef={focusRef}
            search={search}
          />
        </div>
      )}
      {lastPickedImage != null && (
        <CardbackApplyPrompt
          entry="rail"
          affectedCount={countBackFacesAffectedByApplyAll(
            projectMembers,
            lastPickedImage
          )}
          customBackThumbnails={customBackThumbnails}
          onApplyAll={handleApplyAll}
          onSetDefault={handleSetDefault}
        />
      )}
    </div>
  );
}
