import { PDFDocument, PDFName } from "pdf-lib";

import {
  appendPDFDocument,
  createMergedPDFDocument,
  saveMergedPDFBlob,
} from "./pdfMerger";

// Builds the kind of Blob @react-pdf/renderer's pdf().toBlob() produces - a real, loadable
// PDF with one page per given size - so the merge runs against genuine pdf-lib documents.
const partialPDFBlob = async (
  pageSizes: Array<[number, number]>
): Promise<Blob> => {
  const doc = await PDFDocument.create();
  for (const [width, height] of pageSizes) {
    doc.addPage([width, height]);
  }
  const bytes = await doc.save();
  // Same ArrayBufferLike->ArrayBuffer re-wrap saveMergedPDFBlob does (see pdfMerger.ts) - the
  // modern TS DOM lib's BlobPart rejects pdf-lib's @types-era Uint8Array signature.
  return new Blob([new Uint8Array(bytes)], { type: "application/pdf" });
};

describe("pdfMerger - incremental merge of partial PDFs", () => {
  it("starts with zero pages and the pageMode the single-shot render wrote (UseThumbs)", async () => {
    const merged = await createMergedPDFDocument();
    expect(merged.getPageCount()).toBe(0);
    // PDFName.of is instance-cached by pdf-lib, so identity comparison proves the catalog
    // entry is exactly UseThumbs - the value react-pdf's <Document pageMode="useThumbs">
    // serialized, which the old all-at-once render always carried.
    expect(merged.catalog.get(PDFName.of("PageMode"))).toBe(
      PDFName.of("UseThumbs")
    );
  });

  it("appends every page of a partial in document order", async () => {
    const merged = await createMergedPDFDocument();
    await appendPDFDocument(
      merged,
      await partialPDFBlob([
        [100, 200],
        [300, 400],
      ])
    );
    expect(merged.getPageCount()).toBe(2);
    expect(merged.getPage(0).getSize()).toEqual({ width: 100, height: 200 });
    expect(merged.getPage(1).getSize()).toEqual({ width: 300, height: 400 });
  });

  it("concatenates successive partials in the order they are appended", async () => {
    const merged = await createMergedPDFDocument();
    await appendPDFDocument(merged, await partialPDFBlob([[100, 200]]));
    await appendPDFDocument(
      merged,
      await partialPDFBlob([
        [300, 400],
        [500, 600],
      ])
    );
    expect(merged.getPageCount()).toBe(3);
    expect(merged.getPage(0).getSize()).toEqual({ width: 100, height: 200 });
    expect(merged.getPage(1).getSize()).toEqual({ width: 300, height: 400 });
    expect(merged.getPage(2).getSize()).toEqual({ width: 500, height: 600 });
  });

  it("merging never loses previously appended pages, even for a boundary partial", async () => {
    // pdf-lib has no zero-page representation: a create() with no addPage() calls round-trips
    // save() -> load() as a 1-page document, and every worker batch carries >= 1 page anyway
    // (batchStartPage <= totalPages). Asserting on that quirk would test pdf-lib, not the merge;
    // the real invariant is that a later append preserves everything appended before it.
    const merged = await createMergedPDFDocument();
    await appendPDFDocument(merged, await partialPDFBlob([[100, 200]]));
    const pagesBefore = merged.getPageCount();
    await appendPDFDocument(merged, await partialPDFBlob([]));
    expect(merged.getPageCount()).toBe(pagesBefore + 1);
    expect(merged.getPage(0).getSize()).toEqual({ width: 100, height: 200 });
  });

  it("saveMergedPDFBlob returns a loadable application/pdf carrying every merged page and the pageMode", async () => {
    const merged = await createMergedPDFDocument();
    await appendPDFDocument(merged, await partialPDFBlob([[100, 200]]));
    await appendPDFDocument(merged, await partialPDFBlob([[300, 400]]));
    const blob = await saveMergedPDFBlob(merged);
    expect(blob.type).toBe("application/pdf");
    // Same cross-realm conversion appendPDFDocument does: jsdom's arrayBuffer() is not
    // instanceof pdf-lib's ArrayBuffer, so re-wrap before handing bytes to PDFDocument.load.
    const loaded = await PDFDocument.load(
      new Uint8Array(await blob.arrayBuffer())
    );
    expect(loaded.getPageCount()).toBe(2);
    expect(loaded.getPage(0).getSize()).toEqual({ width: 100, height: 200 });
    expect(loaded.getPage(1).getSize()).toEqual({ width: 300, height: 400 });
    // getCatalog is not a method - the catalog is a pdf-lib property accessor (same shape the
    // first test reads via merged.catalog.get(...)).
    expect(loaded.catalog.get(PDFName.of("PageMode"))).toBe(
      PDFName.of("UseThumbs")
    );
  });
});
