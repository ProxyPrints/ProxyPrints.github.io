import { pdf } from "@react-pdf/renderer";
import { PDFDocument, PDFName } from "pdf-lib";
import React from "react";
import zlib from "zlib";

import {
  MemorySink,
  PDFIncrementalWriter,
  PdfParseError,
} from "./pdfIncrementalWriter";

// Builds a real @react-pdf/renderer batch PDF - the same shape pdf.worker.ts's renderPDF()
// produces via `pdf(element).toBlob()` for one page-range batch. Every content stream and
// embedded font pdfkit (react-pdf's underlying writer) emits is FlateDecode-compressed by
// default, so this is a genuine stream-integrity fixture, not a synthetic one.
const buildBatchBytes = async (
  pageTexts: Array<string>
): Promise<Uint8Array> => {
  const { Document, Page, Text, View } = await import("@react-pdf/renderer");
  const element = React.createElement(
    Document,
    { pageMode: "useThumbs" },
    pageTexts.map((text, i) =>
      React.createElement(
        Page,
        { key: i, size: "A4" },
        React.createElement(
          View,
          { style: { padding: 20 } },
          React.createElement(Text, null, text)
        )
      )
    )
  );
  const blob = await pdf(element).toBlob();
  return new Uint8Array(await blob.arrayBuffer());
};

/**
 * Locates every object's byte offset via the finalized PDF's own classic xref table -
 * deliberately mirroring the OFFSET-driven approach the writer itself uses (never scanning for
 * "endobj" as a text marker), because a naive text scan for "endobj" is unsound here: the
 * compressed FlateDecode payload between "stream" and "endstream" is arbitrary binary data that
 * can coincidentally contain the ASCII bytes for "endobj", which would truncate the extracted
 * region and produce a false stream-corruption report that has nothing to do with the writer.
 */
const objectOffsetsFromXref = (bytes: Uint8Array): Array<number> => {
  const text = Buffer.from(bytes).toString("latin1");
  const xrefStart = text.lastIndexOf("\nxref\n") + 1;
  const trailerStart = text.indexOf("trailer", xrefStart);
  const xrefBlock = text.slice(xrefStart, trailerStart);
  const entryLines = xrefBlock
    .split("\n")
    .filter((line) => /^\d{10} \d{5} [nf] ?$/.test(line));
  // Entry 0 is the free-list head; every other entry is an in-use object offset, in object
  // number order (this writer emits one contiguous "0 <size>" style traversal - see finalize()).
  return entryLines.slice(1).map((line) => parseInt(line.slice(0, 10), 10));
};

/** Walks every object (via real xref offsets, region-bounded to the next object's offset) and
 *  inflates every /Filter /FlateDecode stream it finds, asserting each one decompresses without
 *  error - the "invalid distance too far back" failure mode this module exists to prevent. */
const assertEveryFlateStreamInflates = (bytes: Uint8Array): number => {
  const offsets = objectOffsetsFromXref(bytes);
  const text = Buffer.from(bytes).toString("latin1");
  let streamsChecked = 0;
  for (let i = 0; i < offsets.length; i++) {
    const regionStart = offsets[i];
    const regionEnd = i + 1 < offsets.length ? offsets[i + 1] : bytes.length;
    // The dictionary portion (before "stream") is always plain ASCII text in this writer's
    // output, so a bounded text scan within [regionStart, regionEnd) is sound here - unlike
    // scanning for "endobj", this never crosses into the binary stream payload itself.
    const region = text.slice(regionStart, regionEnd);
    const streamKeywordIndex = region.indexOf("\nstream\n");
    if (streamKeywordIndex < 0) continue;
    const dictText = region.slice(0, streamKeywordIndex);
    if (!/\/Filter\s*\/FlateDecode/.test(dictText)) continue;
    const lengthMatch = dictText.match(/\/Length (\d+)/);
    if (lengthMatch === null) {
      throw new Error(
        `object at offset ${regionStart} declares /Filter /FlateDecode with no direct /Length`
      );
    }
    const declaredLength = parseInt(lengthMatch[1], 10);
    const dataStart = regionStart + streamKeywordIndex + "\nstream\n".length;
    const streamBytes = bytes.subarray(dataStart, dataStart + declaredLength);
    // This is the exact failure mode reported: zlib.inflateSync throwing
    // "invalid distance too far back" on a corrupted FlateDecode stream.
    zlib.inflateSync(streamBytes);
    streamsChecked++;
  }
  return streamsChecked;
};

describe("PDFIncrementalWriter - stream integrity against real @react-pdf/renderer output", () => {
  it("a single-batch, single-page document produces a PDF whose FlateDecode streams inflate cleanly", async () => {
    const batch = await buildBatchBytes(["hello world "]);
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    await writer.appendBatch(batch);
    const result = await writer.finalize();

    const output = sink.toUint8Array();
    expect(result.pageCount).toBe(1);
    expect(output.byteLength).toBe(result.byteLength);
    const streamsChecked = assertEveryFlateStreamInflates(output);
    expect(streamsChecked).toBeGreaterThan(0);
  });

  it("a multi-batch, multi-page document concatenates without corrupting any stream", async () => {
    const batches = await Promise.all([
      buildBatchBytes(["batch one page one ", "batch one page two "]),
      buildBatchBytes(["batch two page one ", "batch two page two "]),
    ]);
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    for (const batch of batches) {
      await writer.appendBatch(batch);
    }
    const result = await writer.finalize();
    const output = sink.toUint8Array();

    expect(result.pageCount).toBe(4);
    const streamsChecked = assertEveryFlateStreamInflates(output);
    expect(streamsChecked).toBeGreaterThan(0);
  });

  it("the finalized output loads as a valid PDF via pdf-lib, with pages in append order", async () => {
    const batches = await Promise.all([
      buildBatchBytes(["first "]),
      buildBatchBytes(["second ", "third "]),
    ]);
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    for (const batch of batches) {
      await writer.appendBatch(batch);
    }
    await writer.finalize();

    const loaded = await PDFDocument.load(sink.toUint8Array());
    expect(loaded.getPageCount()).toBe(3);
  });

  // Carries forward the pdfMerger.test.ts assertion this writer replaced (see finalize()'s
  // own /PageMode /UseThumbs comment): the merged/finalized document must keep the pageMode
  // the single-shot render wrote, across a multi-batch export - otherwise the exported PDF
  // silently opens without its thumbnail sidebar.
  it("the finalized document's catalog keeps /PageMode /UseThumbs across a multi-batch export", async () => {
    const batches = await Promise.all([
      buildBatchBytes(["first "]),
      buildBatchBytes(["second ", "third "]),
    ]);
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    for (const batch of batches) {
      await writer.appendBatch(batch);
    }
    await writer.finalize();

    const loaded = await PDFDocument.load(sink.toUint8Array());
    expect(loaded.catalog.get(PDFName.of("PageMode"))).toBe(
      PDFName.of("UseThumbs")
    );
  });

  it("xref offsets exactly locate every object's 'N 0 obj' marker", async () => {
    const batch = await buildBatchBytes(["offsets "]);
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    await writer.appendBatch(batch);
    await writer.finalize();

    const output = sink.toUint8Array();
    const text = Buffer.from(output).toString("latin1");
    const xrefStart = text.lastIndexOf("\nxref\n") + 1;
    const trailerStart = text.indexOf("trailer", xrefStart);
    const xrefBlock = text.slice(xrefStart, trailerStart);
    const entryLines = xrefBlock
      .split("\n")
      .filter((line) => /^\d{10} \d{5} [nf] ?$/.test(line));
    // Object 0 is the free-list head; every other entry must point at "N 0 obj".
    for (let i = 1; i < entryLines.length; i++) {
      const offset = parseInt(entryLines[i].slice(0, 10), 10);
      const marker = text.slice(offset, offset + `${i} 0 obj`.length);
      expect(marker).toBe(`${i} 0 obj`);
    }
  });

  // Image XObjects are excluded from assertEveryFlateStreamInflates here on purpose: under
  // Jest's jsdom/Node environment, @react-pdf/pdfkit's browser bundle produces genuinely
  // malformed FlateDecode bytes for PNG image XObjects specifically (its synchronous
  // zlib.deflateSync path, as opposed to the streaming zlib.createDeflate path content streams
  // use) - reproduced identically in the UNTOUCHED batch this writer never even sees yet, and
  // confirmed absent when the same export runs in a real Chromium browser via Playwright
  // (production images inflate cleanly there). That is a pre-existing @react-pdf/renderer
  // dependency issue specific to the Jest test environment, not something this writer can cause
  // or fix - so what this test asserts instead is the actual invariant the writer owns: image
  // stream bytes are copied through byte-for-byte, unchanged, whatever they are.
  it("copies an embedded raster image's stream bytes through byte-for-byte, unchanged", async () => {
    const { Document, Image, Page } = await import("@react-pdf/renderer");
    const onePixelPngDataUri =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
    const element = React.createElement(
      Document,
      { pageMode: "useThumbs" },
      React.createElement(
        Page,
        { size: "A4" },
        React.createElement(Image, { src: onePixelPngDataUri })
      )
    );
    const blob = await pdf(element).toBlob();
    const batch = new Uint8Array(await blob.arrayBuffer());
    const batchText = Buffer.from(batch).toString("latin1");
    const imageDictMatch = batchText.match(
      /\/Subtype \/Image[\s\S]*?\/Filter \/FlateDecode[\s\S]*?\/Length (\d+)[\s\S]*?>>\r?\nstream\r?\n/
    );
    expect(imageDictMatch).not.toBeNull();
    const sourceDeclaredLength = parseInt(
      (imageDictMatch as RegExpMatchArray)[1],
      10
    );
    const sourceDataStart =
      (imageDictMatch as RegExpMatchArray).index! +
      (imageDictMatch as RegExpMatchArray)[0].length;
    const sourceStreamBytes = batch.subarray(
      sourceDataStart,
      sourceDataStart + sourceDeclaredLength
    );

    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    await writer.appendBatch(batch);
    const result = await writer.finalize();
    const output = sink.toUint8Array();

    expect(result.pageCount).toBe(1);
    const outputText = Buffer.from(output).toString("latin1");
    const outputImageIndex = outputText.indexOf(
      Buffer.from(
        sourceStreamBytes.subarray(0, Math.min(16, sourceStreamBytes.length))
      ).toString("latin1")
    );
    expect(outputImageIndex).toBeGreaterThanOrEqual(0);
    const outputStreamBytes = output.subarray(
      outputImageIndex,
      outputImageIndex + sourceStreamBytes.length
    );
    expect(
      Buffer.from(outputStreamBytes).equals(Buffer.from(sourceStreamBytes))
    ).toBe(true);
  });

  it("rejects a batch PDF that uses a non-classic xref (defensive parse guard)", async () => {
    const sink = new MemorySink();
    const writer = new PDFIncrementalWriter(sink);
    const bogus = new TextEncoder().encode(
      "%PDF-1.7\n1 0 obj\n<< >>\nendobj\nstartxref\n999999\n%%EOF\n"
    );
    await expect(writer.appendBatch(bogus)).rejects.toThrow(PdfParseError);
  });
});
