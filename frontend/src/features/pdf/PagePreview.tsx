/**
 * WYSIWYG page preview, without PDF rendering (Proposal A of the print-preview design task -
 * see the held proposal artifact for the full findings/mocks this implements). Feeds off the
 * same computeLayout() the PDF generator itself uses, so slot positions match exactly, and
 * renders with plain DOM/CSS - no canvas, no @react-pdf/renderer, no pdf.js. Card art is drawn
 * from the small-tier thumbnail URLs the caller already has in memory (the same URLs the
 * editor grid displays) - this component never fetches an image itself, so it adds zero new
 * image memory beyond whatever's already resident (the anti-crash requirement the whole design
 * task is built around; see the artifact's RAM findings on Proxxied's export-time crash class).
 *
 * "CSS-transform-scaled": the page itself is sized in real mm (a valid absolute CSS unit,
 * browsers already know 1mm = 96/25.4 px), then the whole thing is scaled down via
 * `transform: scale()` to fit the available preview width - so every measurement inside stays
 * in mm, matching computeLayout()'s own units, and only the single outer transform changes
 * when the preview panel resizes.
 */

import React, { useMemo } from "react";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import {
  computeLayout,
  LayoutMargins,
  LayoutSpacing,
} from "@/features/pdf/layout";

// Matches the CSS spec's own absolute definition of "mm" (96px per inch, 25.4mm per inch) -
// used only to size the outer non-scaled wrapper so it doesn't reserve extra blank space
// around the scaled-down page; every measurement on the page itself stays in real "mm" units.
const CSS_PX_PER_MM = 96 / 25.4;

export interface PagePreviewSlotContent {
  /** Small-tier thumbnail URL already resident in the browser/editor - never fetched by this
   * component. Undefined renders an empty placeholder slot (e.g. a page with fewer cards than
   * grid capacity). */
  imageUrl: string | undefined;
  /** Rendered as the slot's accessible name; also shown as a fallback label when imageUrl is
   * undefined. */
  name: string;
}

export interface PagePreviewProps {
  pageWidthMM: number;
  pageHeightMM: number;
  bleedEdgeMM: number;
  margins: LayoutMargins;
  spacing: LayoutSpacing;
  /** One entry per slot on this page, in the same row-major order computeLayout() returns.
   * Fewer entries than grid capacity is fine - remaining slots render empty. */
  slots: Array<PagePreviewSlotContent>;
  /** Renders a dashed trim-line rectangle inside each slot's bleed box, matching the PDF
   * generator's own drawCardCutLines toggle - a visual approximation (not exact
   * CutLineCorner geometry, which stays PDF-only), for at-a-glance placement checking, not
   * print-accurate cut-line rendering. */
  showCutLines: boolean;
  /** Width, in real CSS px, of the preview panel this scales down to fit. */
  maxWidthPx: number;
  /** Proposal H (docs/proposals/proposal-h-unified-display-page.md): when provided, each slot
   * becomes clickable and calls back with its row-major index - the unified display page's own
   * slot-select interaction. Omitted by existing callers (PDFGenerator's fast preview), which
   * stay non-interactive with zero behavior change. */
  onSlotClick?: (index: number) => void;
  /** Row-major index of the slot to render with a selected outline. Ignored when onSlotClick
   * isn't provided. */
  selectedSlotIndex?: number;
}

export function PagePreview({
  pageWidthMM,
  pageHeightMM,
  bleedEdgeMM,
  margins,
  spacing,
  slots,
  showCutLines,
  maxWidthPx,
  onSlotClick,
  selectedSlotIndex,
}: PagePreviewProps) {
  const layout = useMemo(
    () =>
      computeLayout(
        pageWidthMM,
        pageHeightMM,
        CardWidthMM,
        CardHeightMM,
        bleedEdgeMM,
        margins,
        spacing
      ),
    // deliberately depend on each primitive field, not the margins/spacing objects themselves -
    // callers (e.g. PDFGenerator) construct a fresh { top, bottom, left, right } object every
    // render, which would defeat this memo entirely if it were a dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      pageWidthMM,
      pageHeightMM,
      bleedEdgeMM,
      margins.top,
      margins.bottom,
      margins.left,
      margins.right,
      spacing.row,
      spacing.col,
    ]
  );

  const scale = maxWidthPx / (pageWidthMM * CSS_PX_PER_MM);
  const slotWidthMM = CardWidthMM + 2 * bleedEdgeMM;
  const slotHeightMM = CardHeightMM + 2 * bleedEdgeMM;

  return (
    <div
      data-testid="page-preview"
      style={{
        width: maxWidthPx,
        height: pageHeightMM * CSS_PX_PER_MM * scale,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: pageWidthMM + "mm",
          height: pageHeightMM + "mm",
          position: "relative",
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          background: "white",
          boxShadow: "0 2px 10px rgba(0, 0, 0, 0.25)",
        }}
      >
        {layout.slots.map((slot, index) => {
          const content = slots[index];
          const isSelected = onSlotClick != null && selectedSlotIndex === index;
          return (
            <div
              key={index}
              data-testid="page-preview-slot"
              onClick={
                onSlotClick != null ? () => onSlotClick(index) : undefined
              }
              role={onSlotClick != null ? "button" : undefined}
              aria-label={onSlotClick != null ? content?.name : undefined}
              aria-pressed={onSlotClick != null ? isSelected : undefined}
              style={{
                position: "absolute",
                left: slot.xMM + "mm",
                top: slot.yMM + "mm",
                width: slotWidthMM + "mm",
                height: slotHeightMM + "mm",
                overflow: "hidden",
                background: "#d9d9d9",
                cursor: onSlotClick != null ? "pointer" : undefined,
                outline: isSelected ? "3px solid #df691a" : undefined,
                outlineOffset: isSelected ? "-3px" : undefined,
              }}
            >
              {content?.imageUrl != null && (
                <img
                  src={content.imageUrl}
                  alt={content.name}
                  loading="lazy"
                  decoding="async"
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    display: "block",
                    pointerEvents: "none",
                  }}
                />
              )}
              {showCutLines && (
                <div
                  data-testid="page-preview-cut-line"
                  style={{
                    position: "absolute",
                    left: bleedEdgeMM + "mm",
                    top: bleedEdgeMM + "mm",
                    width: CardWidthMM + "mm",
                    height: CardHeightMM + "mm",
                    outline: "0.25mm dashed rgba(220, 30, 30, 0.75)",
                    pointerEvents: "none",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
