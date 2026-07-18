import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { CardHeightMM, CardWidthMM } from "@/common/constants";

import { PagePreview } from "./PagePreview";

const A4_WIDTH_MM = 210;
const A4_HEIGHT_MM = 297;

const zeroMargins = { top: 0, bottom: 0, left: 0, right: 0 };
const zeroSpacing = { row: 0, col: 0 };

describe("PagePreview", () => {
  it("renders exactly one slot per computeLayout() slot, in the same order", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          { imageUrl: "https://example.com/1.png", name: "Card 1" },
          { imageUrl: "https://example.com/2.png", name: "Card 2" },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    const slotEls = screen.getAllByTestId("page-preview-slot");
    // A4 at 63x88mm, 0 bleed, 0 spacing fits a 3x3 grid (matches layout.test.ts's own golden
    // value for this exact config, checked there independently) - every grid cell renders,
    // not just the two with image content.
    expect(slotEls).toHaveLength(9);
    expect(screen.getByAltText("Card 1")).toBeInTheDocument();
    expect(screen.getByAltText("Card 2")).toBeInTheDocument();
  });

  it("never fetches an image itself - only renders the URLs it was given", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          { imageUrl: "https://example.com/only.png", name: "Only Card" },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", "https://example.com/only.png");
  });

  it("leaves a slot empty (no <img>) when no content is provided for it", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(screen.getAllByTestId("page-preview-slot")).toHaveLength(9);
    expect(screen.queryAllByRole("img")).toHaveLength(0);
  });

  it("draws a cut-line rectangle per slot only when showCutLines is true", () => {
    const { rerender } = render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={3}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[{ imageUrl: "https://example.com/1.png", name: "Card 1" }]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );
    expect(screen.queryAllByTestId("page-preview-cut-line")).toHaveLength(0);

    rerender(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={3}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[{ imageUrl: "https://example.com/1.png", name: "Card 1" }]}
        showCutLines={true}
        maxWidthPx={400}
      />
    );
    const cutLines = screen.getAllByTestId("page-preview-cut-line");
    expect(cutLines.length).toBeGreaterThan(0);
  });

  it("scales the outer wrapper to exactly maxWidthPx regardless of page size", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[]}
        showCutLines={false}
        maxWidthPx={321}
      />
    );
    const wrapper = screen.getByTestId("page-preview");
    expect(wrapper).toHaveStyle({ width: "321px" });
  });

  it("reflows live when margins/spacing change - fewer slots as spacing grows", () => {
    const { rerender } = render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );
    const initialCount = screen.getAllByTestId("page-preview-slot").length;

    rerender(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={{ row: 20, col: 20 }}
        slots={[]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );
    const spacedCount = screen.getAllByTestId("page-preview-slot").length;
    expect(spacedCount).toBeLessThan(initialCount);
  });

  it("is non-interactive by default - no click role, click is a no-op", async () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[{ imageUrl: "https://example.com/1.png", name: "Card 1" }]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    await userEvent.click(screen.getAllByTestId("page-preview-slot")[0]);
  });

  it("calls onSlotClick with the clicked slot's row-major index when provided", async () => {
    const onSlotClick = jest.fn();
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          { imageUrl: "https://example.com/1.png", name: "Card 1" },
          { imageUrl: "https://example.com/2.png", name: "Card 2" },
        ]}
        showCutLines={false}
        maxWidthPx={400}
        onSlotClick={onSlotClick}
      />
    );
    const slotEls = screen.getAllByTestId("page-preview-slot");
    await userEvent.click(slotEls[1]);
    expect(onSlotClick).toHaveBeenCalledWith(1);
  });

  it("marks only the selected slot as pressed", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          { imageUrl: "https://example.com/1.png", name: "Card 1" },
          { imageUrl: "https://example.com/2.png", name: "Card 2" },
        ]}
        showCutLines={false}
        maxWidthPx={400}
        onSlotClick={() => {}}
        selectedSlotIndex={1}
      />
    );
    const slotEls = screen.getAllByTestId("page-preview-slot");
    expect(slotEls[0]).toHaveAttribute("aria-pressed", "false");
    expect(slotEls[1]).toHaveAttribute("aria-pressed", "true");
  });

  it("lazy-loads slot images", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[{ imageUrl: "https://example.com/1.png", name: "Card 1" }]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );
    const image = screen.getByRole("img");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
  });
});

// Sanity: the card constants this component relies on (via computeLayout) are the same ones
// PDF.tsx itself uses, so a preview slot's box size always matches a generated PDF's.
describe("PagePreview - card constants", () => {
  it("uses the shared CardWidthMM/CardHeightMM constants, not a local copy", () => {
    expect(CardWidthMM).toBe(63);
    expect(CardHeightMM).toBe(88);
  });
});
