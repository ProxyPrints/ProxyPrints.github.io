import { Document, Image, Page, pdf, Text, View } from "@react-pdf/renderer";
import { PDFDocument } from "pdf-lib";
import React from "react";
import zlib from "zlib";

import { MemorySink, PDFIncrementalWriter } from "./pdfIncrementalWriter";

const samplePngDataUri = (): string => {
  const width = 300;
  const height = 400;
  const raw = Buffer.alloc(height * (1 + width * 3));
  let p = 0;
  for (let y = 0; y < height; y++) {
    raw[p++] = 0;
    for (let x = 0; x < width; x++) {
      raw[p++] = (x * 3 + y) % 256;
      raw[p++] = (x + y * 2) % 256;
      raw[p++] = 128;
    }
  }
  const idat = zlib.deflateSync(raw);
  const crc32 = (buf: Buffer): number => {
    const table: Array<number> = [];
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    let crc = 0xffffffff;
    for (let i = 0; i < buf.length; i++)
      crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer): Buffer => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length, 0);
    const typeData = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(typeData), 0);
    return Buffer.concat([len, typeData, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const png = Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return `data:image/png;base64,${png.toString("base64")}`;
};

it("final validation: large deck through PDFIncrementalWriter is a valid, loadable PDF", async () => {
  const element = React.createElement(
    Document,
    { pageMode: "useThumbs" },
    Array.from({ length: 8 }, (_, i) =>
      React.createElement(
        Page,
        { key: i, size: "A4" },
        React.createElement(
          View,
          null,
          React.createElement(Image, { src: samplePngDataUri() }),
          React.createElement(Text, null, `page ${i}`)
        )
      )
    )
  );
  const blob = await pdf(element).toBlob();
  const batchBytes = new Uint8Array(await blob.arrayBuffer());

  const BATCH_COUNT = 100; // 100 * 8 = 800 pages
  const sink = new MemorySink();
  const writer = new PDFIncrementalWriter(sink);
  for (let i = 0; i < BATCH_COUNT; i++) {
    await writer.appendBatch(new Uint8Array(batchBytes));
  }
  const result = await writer.finalize();
  const output = sink.toUint8Array();

  // Independent library, independent of this writer's own parser: proves the file is a
  // genuinely valid, standards-conforming PDF, not just internally self-consistent.
  const loaded = await PDFDocument.load(output);

  console.log(
    `FINAL VALIDATION: pageCount=${result.pageCount} byteLength=${result.byteLength} ` +
      `(${(result.byteLength / 1024 / 1024).toFixed(
        2
      )} MB), pdf-lib pageCount=${loaded.getPageCount()}`
  );

  expect(result.pageCount).toBe(800);
  expect(loaded.getPageCount()).toBe(800);
  expect(output.byteLength).toBe(result.byteLength);
}, 120_000);
