/**
 * R9 (editor-repass round, item 2) - the ONE cardback picker primitive a point-in-time
 * deserves: a compact swatch strip. Four surfaces share it - the right rail's Cardback section
 * (project-wide pick + the apply-all/set-default buttons beneath), the left rail's per-slot
 * control (per-slot pick, no buttons), the pre-export reminder gate (pick and proceed), and the
 * sheet slot's custom-cardback dot on the flip button (which is an INDICATOR, never a picker,
 * so it doesn't use this). Only this one component renders thumbnails for all of them.
 *
 * Render-cost cap (the R9 task's `min(deckCardbacks, 12)` thumbnails at 52px): `maxShown`
 * (default 12) limits how many swatches render; a dashed "More…" cell expands IN PLACE (flips
 * to "Fewer", the same affordance SelectVersionResults' own GhostTile uses) when the list
 * exceeds it, so a deck with hundreds of cardbacks never renders them all up front.
 *
 * Visual contract from editor-repass-mockup.html (lines 251-258): 52px swatch with the 63/88
 * aspect ratio, `--theme-radius-sm` corners, `1px` `--theme-divider` border, and the selected
 * state as a `2px` `--theme-accent` outline with `1px` offset. Markup uses a real <img> (alt =
 * card name) rather than the mockup's background-image so the swatches are keyboard- and
 * screen-reader-reachable and e2e can `getByAltText` them - same tokens, same pixels.
 */
import styled from "@emotion/styled";
import React, { useState } from "react";

import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";

/** R9's render-cost cap: min(deckCardbacks, 12) thumbnails render before the "More…" cell. */
const DEFAULT_MAX_SHOWN = 12;

const Strip = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
`;

const SwatchButton = styled.button<{ $selected: boolean }>`
  width: 52px;
  aspect-ratio: 63 / 88;
  padding: 0;
  border: 1px solid var(--theme-divider);
  border-radius: var(--theme-radius-sm);
  background: #2a2320;
  overflow: hidden;
  cursor: pointer;
  outline: ${(props) =>
    props.$selected ? "2px solid var(--theme-accent)" : "none"};
  outline-offset: 1px;

  img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
`;

const MoreCell = styled.button`
  width: 52px;
  aspect-ratio: 63 / 88;
  padding: 0;
  background: transparent;
  border: 1px dashed var(--theme-divider);
  border-radius: var(--theme-radius-sm);
  color: var(--theme-muted);
  font-size: 10px;
  font-family: inherit;
  cursor: pointer;
`;

export interface CardbackSwatchStripProps {
  imageIdentifiers: Array<string>;
  selectedImage?: string;
  onSelect: (identifier: string) => void;
  /** Render-cost cap - how many swatches render before collapsing into the "More…" cell. */
  maxShown?: number;
  /** Container testid - lets e2e scope alt-text lookups when two strips share a page. */
  testId?: string;
}

export function CardbackSwatchStrip({
  imageIdentifiers,
  selectedImage,
  onSelect,
  maxShown = DEFAULT_MAX_SHOWN,
  testId,
}: CardbackSwatchStripProps) {
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();
  const [expanded, setExpanded] = useState(false);

  const hasMore = imageIdentifiers.length > maxShown;
  const visibleIdentifiers =
    hasMore && !expanded
      ? imageIdentifiers.slice(0, maxShown)
      : imageIdentifiers;

  return (
    <Strip data-testid={testId}>
      {visibleIdentifiers.map((identifier) => {
        const cardDocument = cardDocumentsByIdentifier[identifier];
        const name = cardDocument?.name ?? "Cardback";
        return (
          <SwatchButton
            key={identifier}
            type="button"
            $selected={identifier === selectedImage}
            aria-label={name}
            aria-pressed={identifier === selectedImage}
            title={name}
            onClick={() => onSelect(identifier)}
          >
            {cardDocument?.smallThumbnailUrl != null && (
              <img src={cardDocument.smallThumbnailUrl} alt={name} />
            )}
          </SwatchButton>
        );
      })}
      {hasMore && (
        <MoreCell
          type="button"
          onClick={() => setExpanded((previous) => !previous)}
          data-testid={testId != null ? `${testId}-more` : undefined}
        >
          {expanded ? "Fewer" : "More…"}
        </MoreCell>
      )}
    </Strip>
  );
}
