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

  it("shows the slot's name and query text instead of a blank hole when it has no resolved image", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: undefined,
            name: "Slot 1",
            queryText: "lightning bolt (2ED 162)",
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    const label = screen.getByTestId("page-preview-empty-slot-label");
    expect(label).toHaveTextContent("Slot 1");
    expect(label).toHaveTextContent("lightning bolt (2ED 162)");
    expect(screen.queryAllByRole("img")).toHaveLength(0);
  });

  it("shows just the name, no stray query line, when queryText is omitted (e.g. a shared cardback slot)", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[{ imageUrl: undefined, name: "Slot 1" }]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(
      screen.getByTestId("page-preview-empty-slot-label")
    ).toHaveTextContent("Slot 1");
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
    // Genuinely unfilled grid capacity (no project slot at all) - distinct from a real slot
    // that just hasn't resolved an image yet, which gets the name/query placeholder above.
    expect(
      screen.queryAllByTestId("page-preview-empty-slot-label")
    ).toHaveLength(0);
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

describe("PagePreview - bleed badge (Proposal B PR-3)", () => {
  it("renders the hedged badge when willGenerateBleed is true", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={3}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: "https://example.com/1.png",
            name: "Card 1",
            willGenerateBleed: true,
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(screen.getByTestId("page-preview-bleed-badge")).toHaveTextContent(
      "Bleed will be generated"
    );
  });

  it("renders no badge when willGenerateBleed is false", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={3}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: "https://example.com/1.png",
            name: "Card 1",
            willGenerateBleed: false,
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(
      screen.queryByTestId("page-preview-bleed-badge")
    ).not.toBeInTheDocument();
  });

  it("renders no badge when willGenerateBleed is omitted (signal not yet available)", () => {
    render(
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

    expect(
      screen.queryByTestId("page-preview-bleed-badge")
    ).not.toBeInTheDocument();
  });
});

describe("PagePreview - orphan badge (issue #324 follow-up)", () => {
  it("renders the orphan badge with the given label when orphanLabel is set", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: "https://example.com/1.png",
            name: "Card 1",
            orphanLabel: "Your file",
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(screen.getByTestId("orphan-badge")).toHaveTextContent("Your file");
  });

  it("renders no orphan badge when orphanLabel is omitted (a non-orphan card)", () => {
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

    expect(screen.queryByTestId("orphan-badge")).not.toBeInTheDocument();
  });

  it("renders no orphan badge on a slot with no resolved imageUrl, even with orphanLabel set", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: undefined,
            name: "Card 1",
            orphanLabel: "Your file",
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
      />
    );

    expect(screen.queryByTestId("orphan-badge")).not.toBeInTheDocument();
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

// Proposal H R7/D17 (docs/proposals/proposal-h-display-layout-spec.md) - the /display-only
// screen-presentation variant. PDFGenerator.tsx's own fast preview never passes
// screenPresentation, so its call site must keep today's white-page/box-shadow look with zero
// behavior change - a future refactor that silently flipped the default would otherwise only be
// caught by eyeballing a screenshot.
describe("PagePreview - screenPresentation prop (R7/D17)", () => {
  it("defaults to the classic white page + box-shadow look when the prop is omitted (PDFGenerator's own call site)", () => {
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

    const page = screen.getByTestId("page-preview-page");
    expect(page).toHaveStyle({ background: "white" });
    expect(page.style.boxShadow).not.toBe("");
    expect(page.style.border).toBe("");
  });

  it("renders a fully clear page with a hairline border and rounded corners instead, when screenPresentation is true (/display's own call site)", () => {
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
        screenPresentation
      />
    );

    const page = screen.getByTestId("page-preview-page");
    expect(page).toHaveStyle({ background: "transparent" });
    expect(page.style.boxShadow).toBe("");
    expect(page.style.border).not.toBe("");
    expect(page.style.borderRadius).not.toBe("");
  });
});

// Cardback flow round (SPEC-cardback-pdfwait.md OWNER AMENDMENT 3) - the flip button's own
// non-default-back indicator dot, gated the SAME way the flip button itself is (flippable cells
// only - never rendered on a genuinely empty slot, and never without onSlotFlip wired at all).
describe("PagePreview - custom-cardback indicator dot (OWNER AMENDMENT 3)", () => {
  it("renders the dot on a flippable slot whose hasCustomCardback is true", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: "https://example.com/1.png",
            name: "Custom-back card",
            flippable: true,
            hasCustomCardback: true,
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
        onSlotFlip={() => undefined}
      />
    );

    expect(
      screen.getByTestId("page-preview-slot-custom-cardback-indicator")
    ).toBeInTheDocument();
    expect(screen.getByTestId("page-preview-slot-flip")).toHaveAccessibleName(
      "Preview the other face of this card (custom cardback)"
    );
  });

  it("renders no dot on a flippable slot following the deck default (hasCustomCardback false/undefined)", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: "https://example.com/1.png",
            name: "Default-back card",
            flippable: true,
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
        onSlotFlip={() => undefined}
      />
    );

    expect(screen.getByTestId("page-preview-slot-flip")).toBeInTheDocument();
    expect(
      screen.queryByTestId("page-preview-slot-custom-cardback-indicator")
    ).toBeNull();
  });

  it("same gating as the flip button itself - no dot (and no flip button) on a genuinely empty slot, even if hasCustomCardback were somehow true", () => {
    render(
      <PagePreview
        pageWidthMM={A4_WIDTH_MM}
        pageHeightMM={A4_HEIGHT_MM}
        bleedEdgeMM={0}
        margins={zeroMargins}
        spacing={zeroSpacing}
        slots={[
          {
            imageUrl: undefined,
            name: "Slot 1",
            flippable: false,
            hasCustomCardback: true,
          },
        ]}
        showCutLines={false}
        maxWidthPx={400}
        onSlotFlip={() => undefined}
      />
    );

    expect(screen.queryByTestId("page-preview-slot-flip")).toBeNull();
    expect(
      screen.queryByTestId("page-preview-slot-custom-cardback-indicator")
    ).toBeNull();
  });
});
