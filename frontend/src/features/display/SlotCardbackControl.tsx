/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2, `PKG1b` rail entry) - the left rail's
 * per-slot cardback control: a thumbnail of the slot's own resolved back face + a "Choose a
 * different back…" button. Unlike the right-rail entry (`CardbackRailControl`, a project-wide
 * pick), this is a per-slot pick - it dispatches `setSelectedImages` for THIS SLOT'S back face
 * only, never `bulkReplaceSelectedImage`/`setSelectedCardback` (those are project-wide concepts).
 *
 * R9 (editor-repass round, item 2) - the embedded `GridSelectorResults` body (search/filters/
 * sort, the same "embedded" variant `SelectVersionResults` uses for the front/back art picker)
 * is replaced by the shared `CardbackSwatchStrip` primitive: same strip the right rail and the
 * pre-export reminder use, no search/sort, no apply-all/set-default affordances here, never a
 * modal (§C.2's own "the rail per-slot picker is already the 'no modal, ever' surface").
 */
import styled from "@emotion/styled";
import React, { useState } from "react";
import Button from "react-bootstrap/Button";

import { Back } from "@/common/constants";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { CardbackSwatchStrip } from "@/features/card/CardbackSwatchStrip";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  selectProjectCardback,
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
  const cardbackSearchResults = useAppSelector(selectCardbacks);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();

  const [pickerOpen, setPickerOpen] = useState(false);

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
    setPickerOpen(false);
  };

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
          <CardbackSwatchStrip
            imageIdentifiers={cardbackSearchResults}
            selectedImage={backImage}
            onSelect={handlePick}
            testId="slot-cardback-strip"
          />
        </div>
      )}
    </div>
  );
}
