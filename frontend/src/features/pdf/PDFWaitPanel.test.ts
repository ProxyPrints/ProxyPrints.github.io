import { derivePDFWaitPhase } from "@/features/pdf/PDFWaitPanel";

describe("derivePDFWaitPhase", () => {
  it("is idle when nothing is generating", () => {
    expect(derivePDFWaitPhase(false, null)).toBe("idle");
    expect(derivePDFWaitPhase(false, { completed: 5, total: 5 })).toBe("idle");
  });

  it("is fetching while generating with no progress signal yet", () => {
    expect(derivePDFWaitPhase(true, null)).toBe("fetching");
  });

  it("is fetching while generating with completed behind total", () => {
    expect(derivePDFWaitPhase(true, { completed: 3, total: 10 })).toBe(
      "fetching"
    );
  });

  it("is assembling once every image has resolved but generation hasn't finished", () => {
    expect(derivePDFWaitPhase(true, { completed: 10, total: 10 })).toBe(
      "assembling"
    );
    // completed can end up slightly ahead of total on decks with duplicate identifiers
    // (pdf.worker.ts's own comment) - still reads as "assembling", not a false "fetching".
    expect(derivePDFWaitPhase(true, { completed: 12, total: 10 })).toBe(
      "assembling"
    );
  });
});
