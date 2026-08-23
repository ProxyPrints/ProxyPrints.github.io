import styled from "@emotion/styled";
import React from "react";

import { Faces, useAppDispatch, useAppSelector } from "@/common/types";
import { countSiblingSlotsForImage } from "@/features/card/applySiblingImage";
import {
  applyImageToSiblingSlots,
  selectProjectMembers,
} from "@/store/slices/projectSlice";
import { setNotification } from "@/store/slices/toastsSlice";

const Wrapper = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 0.25rem;
  gap: 0.15rem;
`;

const ApplyButton = styled.button`
  border: 1px solid var(--theme-divider);
  border-radius: 0.35rem;
  padding: 0.05rem 0.5rem;
  font-size: 0.75rem;
  background: transparent;
  color: inherit;
  cursor: pointer;
`;

const Note = styled.div`
  font-size: 0.65rem;
  color: var(--theme-muted);
  text-align: center;
`;

export interface ApplySiblingImageAffordanceProps {
  face: Faces;
  slot: number;
}

export function ApplySiblingImageAffordance({
  face,
  slot,
}: ApplySiblingImageAffordanceProps) {
  const dispatch = useAppDispatch();
  const members = useAppSelector(selectProjectMembers);
  const { toUpdate, skippedDifferent } = countSiblingSlotsForImage(
    members,
    face,
    slot
  );

  if (toUpdate === 0) {
    return null;
  }

  const handleApply = () => {
    dispatch(applyImageToSiblingSlots({ face, slot }));
    dispatch(
      setNotification([
        Math.random().toString(),
        {
          name: "Image applied",
          message: `Applied this image to ${toUpdate} other cop${
            toUpdate === 1 ? "y" : "ies"
          } of this card.`,
          level: "info",
        },
      ])
    );
  };

  return (
    <Wrapper data-testid={`apply-sibling-image-${face}${slot}`}>
      <ApplyButton
        type="button"
        onClick={handleApply}
        data-testid={`apply-sibling-image-button-${face}${slot}`}
      >
        {`Apply to ${toUpdate} other cop${toUpdate === 1 ? "y" : "ies"}`}
      </ApplyButton>
      {skippedDifferent > 0 && (
        <Note data-testid={`apply-sibling-image-note-${face}${slot}`}>
          {`${skippedDifferent} other ${
            skippedDifferent === 1 ? "copy keeps its" : "copies keep their"
          } own art`}
        </Note>
      )}
    </Wrapper>
  );
}
