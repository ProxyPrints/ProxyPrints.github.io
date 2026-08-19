/**
 * Hand-rolled incremental PDF writer - the output side of wtc-pdf-stream's memory-bounded
 * export. Replaces pdfMerger.ts's "accumulate every batch in one pdf-lib document, then
 * save()" approach: pdf-lib is entirely in-memory (copyPages copies every page's content
 * stream AND its image XObjects into the target; save() materialises the whole document as
 * one Uint8Array), so the merged target alone scales with total page count - that peak
 * memory is the OOM this module exists to eliminate.
 *
 * Instead, each batch's partial PDF (rendered by @react-pdf/renderer) is parsed into its
 * objects, the objects actually reachable from the batch's pages are renumbered into global
 * numbers and written STRAIGHT to an injected byte sink (the worker sinks to OPFS, tests use
 * MemorySink). Nothing accumulates in the JS heap: peak memory is bounded by one batch's
 * render plus the small per-batch parse tables, never by the total page count. There is no
 * in-memory representation of the output document at any point - the only whole-PDF buffer
 * that ever exists is the batch Blob @react-pdf/renderer already produced.
 *
 * PDF grammar coverage is deliberately narrow - "a small tokenizer": dicts, arrays, numbers,
 * names, (hex) strings, streams and indirect references at the object-graph level. Content
 * stream internals are never parsed - streams are opaque byte runs copied verbatim. The
 * parser validates its input as it goes and THROWS on any structural mismatch rather than
 * emitting a corrupt PDF silently (a corrupt export is worse than a failed one).
 */

// The /Pages node and /Catalog are written by finalize() once, after every batch's objects.
// Their numbers are reserved up front (not appended at the end) because every copied page's
// /Parent must already point at the /Pages node number when its batch is emitted. Object
// numbers are independent of file order in PDF, so the /Pages node and /Catalog can be the
// FIRST numbers assigned yet the LAST objects written.
export const PDF_PAGES_NODE_NUMBER = 1;
export const PDF_CATALOG_NUMBER = 2;
const FIRST_BATCH_OBJECT_NUMBER = 3;

const PDF_HEADER = "%PDF-1.3\n%\u00e2\u00e3\u00cf\u00d3\n";

export interface ByteSink {
  /** Appends `view`'s bytes to the output. Implementations must consume the whole view. */
  write(view: Uint8Array): void | Promise<void>;
}

/**
 * In-memory sink for tests (and the worker's last-resort fallback when OPFS is unavailable).
 * Accumulates the written chunks without ever concatenating them; callers that need the
 * whole document as one buffer (a Blob for the hand-off) do that explicitly via
 * toUint8Array() at the end - nothing here holds a whole-document buffer implicitly.
 */
export class MemorySink implements ByteSink {
  private readonly chunks: Array<Uint8Array> = [];
  private readonly maxWriteBytes: number;
  private totalBytes = 0;

  constructor(options: { maxSingleWriteBytes?: number } = {}) {
    this.maxWriteBytes =
      options.maxSingleWriteBytes ?? Number.POSITIVE_INFINITY;
  }

  async write(view: Uint8Array): Promise<void> {
    if (view.byteLength > this.maxWriteBytes) {
      throw new Error(
        `MemorySink single write of ${view.byteLength} bytes exceeds the ${this.maxWriteBytes}-byte cap`
      );
    }
    // Copy: the writer may reuse the buffer it hands us.
    this.chunks.push(new Uint8Array(view));
    this.totalBytes += view.byteLength;
  }

  get byteLength(): number {
    return this.totalBytes;
  }

  /** Number of separate write() calls received - lets tests assert chunked emission. */
  get writeCount(): number {
    return this.chunks.length;
  }

  /** The largest single write() received - the memory-invariant assertion surface. */
  get maxWriteBytesSeen(): number {
    let max = 0;
    for (const chunk of this.chunks) {
      if (chunk.byteLength > max) max = chunk.byteLength;
    }
    return max;
  }

  toUint8Array(): Uint8Array {
    const merged = new Uint8Array(this.totalBytes);
    let offset = 0;
    for (const chunk of this.chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return merged;
  }
}

export interface AppendBatchResult {
  /** Pages copied from this batch's /Pages /Kids, in batch order. */
  pagesAppended: number;
  /** Objects written to the sink for this batch (pages + reachable resources). */
  objectsEmitted: number;
  bytesWritten: number;
}

export interface FinalizeResult {
  pageCount: number;
  byteLength: number;
}

// ─────────────────────────────────────────────────────────────────────────────────────────
// PDF syntax - an intentionally small tokenizer over raw object bytes.
// ─────────────────────────────────────────────────────────────────────────────────────────

export class PdfParseError extends Error {}

const isDelimiter = (code: number): boolean =>
  code === 0x28 /* ( */ ||
  code === 0x29 /* ) */ ||
  code === 0x3c /* < */ ||
  code === 0x3e /* > */ ||
  code === 0x5b /* [ */ ||
  code === 0x5d /* ] */ ||
  code === 0x7b /* { */ ||
  code === 0x7d /* } */ ||
  code === 0x2f /* / */ ||
  code === 0x25; /* % */

const isWhitespace = (code: number): boolean =>
  code === 0x00 ||
  code === 0x09 ||
  code === 0x0a ||
  code === 0x0c ||
  code === 0x0d ||
  code === 0x20;

type PdfToken =
  | { kind: "dict-open" }
  | { kind: "dict-close" }
  | { kind: "array-open" }
  | { kind: "array-close" }
  | { kind: "name"; value: string; raw: string }
  | { kind: "number"; raw: string; isInteger: boolean; numericValue: number }
  | { kind: "reference"; objectNumber: number; generation: number; raw: string }
  | { kind: "string"; raw: string }
  | { kind: "hex-string"; raw: string }
  | { kind: "keyword"; value: string; raw: string };

/** A PdfToken narrowed to a parsed name - the only kind legal as a dictionary key. */
type PdfNameToken = Extract<PdfToken, { kind: "name" }>;

/**
 * A lazy scanner over one object's byte region. Whitespace and comments are skipped between
 * tokens; numbers are merged with a following "G R" pair into a single reference token when
 * the pattern holds (the only lookahead the grammar needs - a stray "R" after two numbers
 * is not valid PDF anywhere else, so the match is unambiguous). Laziness is essential: for a
 * stream object the dict tokens are followed by OPAQUE binary data that must never enter the
 * scanner (a compressed font program can contain any byte, including delimiter bytes that
 * would otherwise throw).
 */
class PdfTokenizer {
  private readonly bytes: Uint8Array;
  private readonly end: number;
  pos: number;
  private readonly decoder = new TextDecoder("latin1");
  private pending: PdfToken | null = null;

  constructor(bytes: Uint8Array, start: number, end: number) {
    this.bytes = bytes;
    this.end = end;
    this.pos = start;
  }

  private skipWhitespaceAndComments(): void {
    for (;;) {
      while (this.pos < this.end && isWhitespace(this.bytes[this.pos])) {
        this.pos++;
      }
      // A comment runs to the end of the line; the EOL is whitespace the next iteration
      // swallows. Two iterations handle "whitespace, comment, whitespace" in one pass.
      if (this.pos < this.end && this.bytes[this.pos] === 0x25) {
        while (this.pos < this.end && this.bytes[this.pos] !== 0x0a) {
          this.pos++;
        }
        continue;
      }
      return;
    }
  }

  private readLiteralString(start: number): PdfToken {
    // Depth > 0 handles nested (unbalanced) parens inside string text - PDF allows
    // unescaped parens if they balance. Escaped parens and octal escapes are walked
    // without interpreting them; the raw bytes are preserved verbatim anyway.
    let depth = 1;
    let i = this.pos + 1;
    while (i < this.end && depth > 0) {
      const code = this.bytes[i];
      if (code === 0x5c /* \ */) {
        i += 2; // escape: skip the escaped char (octal runs overshoot by one here, harmless:
        // the RAW span is what matters, not the decoded value).
        continue;
      }
      if (code === 0x28) depth++;
      else if (code === 0x29) depth--;
      i++;
    }
    if (depth !== 0) {
      throw new PdfParseError("unterminated literal string in PDF object");
    }
    this.pos = i;
    return {
      kind: "string",
      raw: this.decoder.decode(this.bytes.subarray(start, i)),
    };
  }

  private readHexString(start: number): PdfToken {
    let i = this.pos + 1;
    while (i < this.end && this.bytes[i] !== 0x3e) i++;
    if (i >= this.end) {
      throw new PdfParseError("unterminated hex string in PDF object");
    }
    i++; // consume '>'
    this.pos = i;
    return {
      kind: "hex-string",
      raw: this.decoder.decode(this.bytes.subarray(start, i)),
    };
  }

  private readName(start: number): PdfToken {
    let i = this.pos + 1;
    while (
      i < this.end &&
      !isWhitespace(this.bytes[i]) &&
      !isDelimiter(this.bytes[i])
    ) {
      i++;
    }
    const raw = this.decoder.decode(this.bytes.subarray(start, i));
    // Decode #xx escapes for VALUE comparison (the raw is re-emitted verbatim, so decoded
    // value and raw only diverge for names react-pdf never emits - /Parent, /Length, /Type
    // etc. are always plain). The value carries NO leading slash; raw does.
    let value = "";
    for (let j = 1; j < raw.length; j++) {
      if (raw[j] === "#" && j + 2 < raw.length) {
        const hex = parseInt(raw.slice(j + 1, j + 3), 16);
        value += String.fromCharCode(Number.isNaN(hex) ? 0 : hex);
        j += 2;
      } else {
        value += raw[j];
      }
    }
    this.pos = i;
    return { kind: "name", value, raw };
  }

  /**
   * Reads an integer or real number, then checks for the "G R" pair that makes the whole
   * sequence an indirect reference. `raw` of a reference covers all three tokens so emit
   * can replace the whole span in one write. On a non-reference, only the number itself is
   * consumed.
   */
  private readNumberOrReference(): PdfToken {
    const start = this.pos;
    let i = this.pos;
    if (this.bytes[i] === 0x2b || this.bytes[i] === 0x2d) i++; // sign
    const intStart = i;
    while (i < this.end && this.bytes[i] >= 0x30 && this.bytes[i] <= 0x39) i++;
    let isInteger = i > intStart;
    if (i < this.end && this.bytes[i] === 0x2e) {
      isInteger = false;
      i++;
      while (i < this.end && this.bytes[i] >= 0x30 && this.bytes[i] <= 0x39)
        i++;
    }
    // Exponent (e.g. 1.5e3) - neither react-pdf nor pdf-lib emit one, but the grammar
    // allows it; consuming the full token keeps the raw span correct.
    if (i < this.end && (this.bytes[i] === 0x65 || this.bytes[i] === 0x45)) {
      isInteger = false;
      i++;
      if (i < this.end && (this.bytes[i] === 0x2b || this.bytes[i] === 0x2d))
        i++;
      while (i < this.end && this.bytes[i] >= 0x30 && this.bytes[i] <= 0x39)
        i++;
    }
    this.pos = i;

    // Would-be reference: only non-negative integers can be object numbers (spec 7.3.8).
    const numberRaw = this.decoder.decode(this.bytes.subarray(start, i));
    if (isInteger && !numberRaw.startsWith("-")) {
      const savePos = this.pos;
      let scan = this.pos;
      const advance = (): void => {
        while (scan < this.end && isWhitespace(this.bytes[scan])) scan++;
      };
      advance();
      const genIntStart = scan;
      while (
        scan < this.end &&
        this.bytes[scan] >= 0x30 &&
        this.bytes[scan] <= 0x39
      ) {
        scan++;
      }
      if (scan > genIntStart) {
        const afterGen = scan;
        advance();
        if (
          scan < this.end &&
          this.bytes[scan] === 0x52 && // 'R'
          (scan + 1 >= this.end ||
            isWhitespace(this.bytes[scan + 1]) ||
            isDelimiter(this.bytes[scan + 1]))
        ) {
          scan++;
          this.pos = scan;
          return {
            kind: "reference",
            objectNumber: parseInt(numberRaw, 10),
            generation: parseInt(
              this.decoder.decode(this.bytes.subarray(genIntStart, afterGen)),
              10
            ),
            raw: this.decoder.decode(this.bytes.subarray(start, this.pos)),
          };
        }
      }
      // Not a reference - rewind to just after the number.
      this.pos = savePos;
    }

    return {
      kind: "number",
      raw: numberRaw,
      isInteger,
      numericValue: parseFloat(numberRaw),
    };
  }

  private readKeyword(start: number): PdfToken {
    let i = this.pos;
    while (
      i < this.end &&
      !isWhitespace(this.bytes[i]) &&
      !isDelimiter(this.bytes[i])
    ) {
      i++;
    }
    this.pos = i;
    const raw = this.decoder.decode(this.bytes.subarray(start, i));
    return { kind: "keyword", value: raw, raw };
  }

  private advance(): PdfToken | null {
    this.skipWhitespaceAndComments();
    if (this.pos >= this.end) return null;
    const code = this.bytes[this.pos];
    switch (code) {
      case 0x3c:
        if (this.pos + 1 < this.end && this.bytes[this.pos + 1] === 0x3c) {
          this.pos += 2;
          return { kind: "dict-open" };
        }
        return this.readHexString(this.pos);
      case 0x3e:
        if (this.pos + 1 < this.end && this.bytes[this.pos + 1] === 0x3e) {
          this.pos += 2;
          return { kind: "dict-close" };
        }
        throw new PdfParseError("unexpected '>' in PDF object");
      case 0x5b:
        this.pos++;
        return { kind: "array-open" };
      case 0x5d:
        this.pos++;
        return { kind: "array-close" };
      case 0x2f:
        return this.readName(this.pos);
      case 0x28:
        return this.readLiteralString(this.pos);
      case 0x52:
        // A bare 'R' that was not consumed by a reference pattern - invalid PDF, but the
        // tokenizer surfaces it as a keyword so the caller can fail with context.
        this.pos++;
        return { kind: "keyword", value: "R", raw: "R" };
      default:
        break;
    }
    if (code === 0x2b || code === 0x2d || code === 0x2e) {
      // Signed or leading-dot real - read as a number by trying the fraction path.
      return this.readNumberOrReference();
    }
    if (code >= 0x30 && code <= 0x39) {
      return this.readNumberOrReference();
    }
    return this.readKeyword(this.pos);
  }

  next(): PdfToken | null {
    if (this.pending !== null) {
      const token = this.pending;
      this.pending = null;
      return token;
    }
    return this.advance();
  }

  peek(): PdfToken | null {
    if (this.pending === null) {
      this.pending = this.advance();
    }
    return this.pending;
  }
}

// ─────────────────────────────────────────────────────────────────────────────────────────
// Value tree + object parsing
// ─────────────────────────────────────────────────────────────────────────────────────────

type PdfValue =
  | { kind: "dict"; entries: Array<{ name: PdfNameToken; value: PdfValue }> }
  | { kind: "array"; items: Array<PdfValue> }
  | { kind: "reference"; objectNumber: number; generation: number; raw: string }
  | { kind: "name"; value: string; raw: string }
  | { kind: "number"; raw: string; isInteger: boolean; numericValue: number }
  | { kind: "string"; raw: string }
  | { kind: "hex-string"; raw: string }
  | { kind: "keyword"; value: string; raw: string };

/**
 * One parsed object. The object's region is [regionStart, regionEnd) in the batch bytes;
 * `stream` is set when the dictionary is followed by a `stream` keyword, with the DATA
 * kept as an offset range (never copied) and `length` the verified data byte count.
 */
interface ParsedObject {
  number: number;
  generation: number;
  dict: PdfValue;
  stream: { dataStart: number; dataEnd: number; length: number } | null;
  /** True for leaf page objects - the /Parent rewrite and finalize bookkeeping attach
   *  only to these. */
  isPage?: boolean;
}

const nameOf = (nameToken: PdfToken): string =>
  nameToken.kind === "name" ? nameToken.value : "";

const dictValueEntry = (dict: PdfValue, key: string): PdfValue | undefined =>
  dict.kind === "dict"
    ? dict.entries.find((entry) => nameOf(entry.name) === key)?.value
    : undefined;

/** Coerces a value to its numeric form - a number, or the number an indirect ref points
 *  at (used for /Length). Anything else is a parse error. */
const valueAsNumber = (
  value: PdfValue,
  resolveRef: (num: number, generation: number) => ParsedObject
): number => {
  if (value.kind === "number") return value.numericValue;
  if (value.kind === "reference") {
    const target = resolveRef(value.objectNumber, value.generation);
    return valueAsNumber(target.dict, resolveRef);
  }
  throw new PdfParseError("expected a number or indirect number reference");
};

/**
 * Parses one object's region into its dict (and stream extents if any). The region must
 * begin at the object's "N G obj" marker (xref offsets are validated against that here)
 * and run through its "endobj". `resolveRef` loads another object by batch number - needed
 * to resolve an indirect /Length: the value must be a plain number.
 */
const parseObject = (
  bytes: Uint8Array,
  regionStart: number,
  regionEnd: number,
  resolveRef: (num: number, generation: number) => ParsedObject
): ParsedObject => {
  const tokenizer = new PdfTokenizer(bytes, regionStart, regionEnd);
  const headerNumber = tokenizer.next();
  const headerGeneration = tokenizer.next();
  const headerKeyword = tokenizer.next();
  if (
    headerNumber?.kind !== "number" ||
    !headerNumber.isInteger ||
    headerGeneration?.kind !== "number" ||
    !headerGeneration.isInteger ||
    headerKeyword?.kind !== "keyword" ||
    headerKeyword.value !== "obj"
  ) {
    throw new PdfParseError(
      "object region does not start with an 'N G obj' marker"
    );
  }

  const parseValue = (): PdfValue => {
    const token = tokenizer.next();
    if (token === null) {
      throw new PdfParseError("truncated PDF object (missing value)");
    }
    switch (token.kind) {
      case "dict-open": {
        const entries: Array<{ name: PdfNameToken; value: PdfValue }> = [];
        for (;;) {
          const next = tokenizer.peek();
          if (next === null) {
            throw new PdfParseError("unterminated dictionary in PDF object");
          }
          if (next.kind === "dict-close") {
            tokenizer.next();
            break;
          }
          if (next.kind !== "name") {
            throw new PdfParseError(
              "dictionary key is not a name in PDF object"
            );
          }
          tokenizer.next();
          const value = parseValue();
          entries.push({ name: next as PdfNameToken, value });
        }
        return { kind: "dict", entries };
      }
      case "array-open": {
        const items: Array<PdfValue> = [];
        for (;;) {
          const next = tokenizer.peek();
          if (next === null) {
            throw new PdfParseError("unterminated array in PDF object");
          }
          if (next.kind === "array-close") {
            tokenizer.next();
            break;
          }
          items.push(parseValue());
        }
        return { kind: "array", items };
      }
      case "dict-close":
      case "array-close":
        throw new PdfParseError("unexpected closing bracket in PDF object");
      case "name":
      case "number":
      case "string":
      case "hex-string":
      case "keyword":
      case "reference":
        return token;
      default:
        throw new PdfParseError(`unexpected token kind in PDF object`);
    }
  };

  const dict = parseValue();

  let stream: ParsedObject["stream"] = null;
  const maybeStream = tokenizer.peek();
  if (maybeStream?.kind === "keyword" && maybeStream.value === "stream") {
    tokenizer.next();
    let dataStart = tokenizer.pos;
    // The keyword "stream" shall be followed by exactly one end-of-line marker, which is
    // not part of the data.
    if (bytes[dataStart] === 0x0d && bytes[dataStart + 1] === 0x0a) {
      dataStart += 2;
    } else if (bytes[dataStart] === 0x0a || bytes[dataStart] === 0x0d) {
      dataStart += 1;
    }
    // Resolve the declared /Length (direct integer, or an indirect reference to a number
    // object), then verify it against the ACTUAL data extent found in the bytes - the
    // mandated byte-exact check. /Length guides the split so binary stream data can never
    // be mis-shifted by a coincidental "endstream" byte sequence inside it.
    const lengthEntry = dictValueEntry(dict, "Length");
    if (lengthEntry === undefined) {
      throw new PdfParseError("stream dictionary without /Length");
    }
    const declaredLength = valueAsNumber(lengthEntry, resolveRef);
    if (!Number.isInteger(declaredLength) || declaredLength < 0) {
      throw new PdfParseError("stream /Length is not a non-negative integer");
    }
    const dataEnd = dataStart + declaredLength;
    if (dataEnd > regionEnd) {
      throw new PdfParseError(
        `stream /Length ${declaredLength} exceeds the object region`
      );
    }
    // The data shall be followed by an end-of-line marker and the endstream keyword; not
    // counting the EOL, the actual data length must equal /Length exactly.
    let afterData = dataEnd;
    if (bytes[afterData] === 0x0d) afterData++;
    if (bytes[afterData] === 0x0a) afterData++;
    const endstreamIndex = indexOfAscii(
      bytes,
      "endstream",
      afterData,
      regionEnd
    );
    if (endstreamIndex !== afterData) {
      throw new PdfParseError(
        `stream /Length ${declaredLength} does not match the actual data extent ` +
          `(endstream found at ${endstreamIndex}, expected ${afterData})`
      );
    }
    // Everything the tokenizer must see from this point is past the endstream keyword.
    tokenizer.pos = afterData + "endstream".length;
    stream = { dataStart, dataEnd: endstreamIndex, length: declaredLength };
  }

  // The object must end with an endobj keyword (plus trailing whitespace).
  const trailing = tokenizer.next();
  if (trailing?.kind !== "keyword" || trailing.value !== "endobj") {
    throw new PdfParseError("PDF object does not end with 'endobj'");
  }

  return {
    number: headerNumber.numericValue,
    generation: headerGeneration.numericValue,
    dict,
    stream,
  };
};

/** Scans `bytes` for the ASCII sequence `needle` within [start, end). Returns the index or
 *  -1. Byte-level to stay dependency-free (stream data never passes through the decoder). */
const indexOfAscii = (
  bytes: Uint8Array,
  needle: string,
  start: number,
  end: number
): number => {
  const first = needle.charCodeAt(0);
  outer: for (let i = start; i + needle.length <= end; i++) {
    if (bytes[i] !== first) continue;
    for (let j = 1; j < needle.length; j++) {
      if (bytes[i + j] !== needle.charCodeAt(j)) continue outer;
    }
    return i;
  }
  return -1;
};

/** Locates and parses the classic xref table. Returns the per-object start offsets and the
 *  trailer dict. Throws on xref streams / any modern structure react-pdf cannot emit -
 *  @react-pdf/renderer always writes a classic table (verified against its 4.x writer). */
const parseXrefAndTrailer = (
  bytes: Uint8Array
): {
  offsetsByNumber: Map<number, number>;
  trailer: PdfValue;
  xrefOffset: number;
} => {
  const startxrefIndex = indexOfAscii(bytes, "startxref", 0, bytes.length);
  if (startxrefIndex < 0) {
    throw new PdfParseError("no startxref marker found in batch PDF");
  }
  // The offset digits follow the keyword, on the next line ("startxref\n12345") or the same
  // line ("startxref 12345"), with CRLF possible - the FIRST integer in a bounded window
  // after the keyword absorbs all layouts and never reaches the %%EOF marker (has no digits).
  const offsetWindow = new TextDecoder("latin1").decode(
    bytes.subarray(
      startxrefIndex + 9,
      Math.min(bytes.length, startxrefIndex + 40)
    )
  );
  const offsetMatch = offsetWindow.match(/(\d+)/);
  const xrefText = offsetMatch === null ? "" : offsetMatch[1];
  const xrefOffset = parseInt(xrefText, 10);
  if (!Number.isFinite(xrefOffset) || xrefOffset < 0) {
    throw new PdfParseError(`malformed startxref offset '${xrefText}'`);
  }

  // The line at `xrefOffset` must start the table with the xref keyword; react-pdf writes
  // "xref\n". An xref STREAM (type /XRef in the trailer with compressed entries) is a
  // different structure this writer does not target - reject loudly, never mis-parse.
  if (
    bytes[xrefOffset] !== 0x78 || // 'x'
    bytes[xrefOffset + 1] !== 0x72 || // 'r'
    bytes[xrefOffset + 2] !== 0x65 || // 'e'
    bytes[xrefOffset + 3] !== 0x66 // 'f'
  ) {
    throw new PdfParseError(
      "batch PDF uses a non-classic xref (xref stream) - unsupported"
    );
  }

  const offsetsByNumber = new Map<number, number>();
  let pos = xrefOffset + 4; // after "xref"
  // Subsections: "<first> <count>\n" followed by `count` 20-byte entries.
  // react-pdf emits a single "0 <size>" subsection; pdf-lib can emit more.
  for (;;) {
    // skip EOL and any blank lines
    while (pos < bytes.length && isWhitespace(bytes[pos])) pos++;
    if (
      pos < bytes.length &&
      bytes[pos] === 0x74 // 't' of 'trailer'
    ) {
      break;
    }
    const lineStart = pos;
    while (pos < bytes.length && bytes[pos] !== 0x0a) pos++;
    const line = new TextDecoder("latin1").decode(
      bytes.subarray(lineStart, pos)
    );
    const m = line.match(/^(\d+)\s+(\d+)\s*$/);
    if (m === null) {
      throw new PdfParseError(`malformed xref subsection header '${line}'`);
    }
    const first = parseInt(m[1], 10);
    const count = parseInt(m[2], 10);
    // The header-line scan stops AT its EOL; consuming it keeps the 20-byte entry stride
    // aligned (each entry's own trailing EOL is its 20th byte).
    if (pos < bytes.length && bytes[pos] === 0x0a) pos++;
    for (let i = 0; i < count; i++) {
      // Entries are exactly 20 bytes: "nnnnnnnnnn ggggg n EOL" (EOL = \r\n or space+\n or
      // \n) - parse defensively but never out of the fixed stride.
      if (pos + 19 >= bytes.length) {
        throw new PdfParseError("truncated xref table");
      }
      const entryText = new TextDecoder("latin1").decode(
        bytes.subarray(pos, pos + 20)
      );
      const entry = entryText.match(/^(\d{10})\s(\d{5})\s([nf])/);
      if (entry === null) {
        throw new PdfParseError(`malformed xref entry '${entryText}'`);
      }
      if (entry[3] === "n") {
        offsetsByNumber.set(first + i, parseInt(entry[1], 10));
      }
      pos += 20;
    }
  }

  // trailer dict
  const trailerTokenSeek = indexOfAscii(bytes, "trailer", pos, bytes.length);
  if (trailerTokenSeek < 0) {
    throw new PdfParseError("no trailer keyword after xref table");
  }
  const trailerTokenizer = new PdfTokenizer(
    bytes,
    trailerTokenSeek + 7,
    startxrefIndex
  );
  const parseTrailerValue = (): PdfValue => {
    const token = trailerTokenizer.next();
    if (token === null) {
      throw new PdfParseError("truncated trailer dictionary");
    }
    if (token.kind === "dict-open") {
      const entries: Array<{ name: PdfNameToken; value: PdfValue }> = [];
      for (;;) {
        const next = trailerTokenizer.next();
        if (next === null) {
          throw new PdfParseError("unterminated trailer dictionary");
        }
        if (next.kind === "dict-close") break;
        if (next.kind !== "name") {
          throw new PdfParseError("trailer dictionary key is not a name");
        }
        entries.push({ name: next, value: parseTrailerValue() });
      }
      return { kind: "dict", entries };
    }
    if (token.kind === "array-open") {
      const items: Array<PdfValue> = [];
      for (;;) {
        const peeked = trailerTokenizer.peek();
        if (peeked === null) {
          throw new PdfParseError("unterminated trailer array");
        }
        if (peeked.kind === "array-close") {
          trailerTokenizer.next();
          break;
        }
        // Scalar items (and nested arrays/dicts via the recursive call) are parsed by
        // parseTrailerValue, which consumes the item token itself.
        items.push(parseTrailerValue());
      }
      return { kind: "array", items };
    }
    if (token.kind === "dict-close" || token.kind === "array-close") {
      throw new PdfParseError("unexpected closing bracket in trailer");
    }
    return token;
  };
  const trailer = parseTrailerValue();

  if (dictValueEntry(trailer, "Encrypt") !== undefined) {
    throw new PdfParseError("encrypted PDF batches are not supported");
  }

  return { offsetsByNumber, trailer, xrefOffset };
};

// ─────────────────────────────────────────────────────────────────────────────────────────
// The writer
// ─────────────────────────────────────────────────────────────────────────────────────────

export class PDFIncrementalWriter {
  private readonly sink: ByteSink;
  private offset = 0;
  private nextObjectNumber = FIRST_BATCH_OBJECT_NUMBER;
  /** Global number of every exported page, in document order. */
  private readonly pageGlobalNumbers: Array<number> = [];
  /** Byte offset of each emitted object by its global number; index 0 unused. */
  private readonly objectOffsets: Array<number> = [];
  private headerWritten = false;

  constructor(sink: ByteSink) {
    this.sink = sink;
  }

  private async writeBytes(view: Uint8Array): Promise<void> {
    await this.sink.write(view);
    this.offset += view.byteLength;
  }

  private async writeText(text: string): Promise<void> {
    await this.writeBytes(new TextEncoder().encode(text));
  }

  /**
   * Parses one batch partial and streams every object reachable from its pages into the
   * sink. The batch's /Catalog, /Pages node and any /Info subtree are dropped - pages are
   * re-homed under the writer's single global /Pages node at finalize().
   */
  async appendBatch(batchBytes: Uint8Array): Promise<AppendBatchResult> {
    if (!this.headerWritten) {
      await this.writeText(PDF_HEADER);
      this.headerWritten = true;
    }
    const bytes = batchBytes;
    const { offsetsByNumber, trailer, xrefOffset } = parseXrefAndTrailer(bytes);

    // Region extents: each object spans [offset, next-offset) by ascending offset; the last
    // object ends where the xref table begins.
    const byOffset = Array.from(offsetsByNumber.entries()).sort(
      (a, b) => a[1] - b[1]
    );
    const regionsByNumber = new Map<number, [number, number]>();
    for (let i = 0; i < byOffset.length; i++) {
      const [num, start] = byOffset[i];
      const end = i + 1 < byOffset.length ? byOffset[i + 1][1] : xrefOffset;
      regionsByNumber.set(num, [start, end]);
    }

    // Object cache + /Length resolver. /Length targets resolve through the same cache but
    // are never emitted - they are direct-ized at emit time.
    const objectCache = new Map<number, ParsedObject>();
    const parseNumberedObject = (
      num: number,
      generation: number
    ): ParsedObject => {
      const cached = objectCache.get(num);
      if (cached !== undefined) return cached;
      const region = regionsByNumber.get(num);
      if (region === undefined) {
        throw new PdfParseError(`reference to unknown object ${num} 0 R`);
      }
      const parsed = parseObject(
        bytes,
        region[0],
        region[1],
        parseNumberedObject
      );
      if (parsed.generation !== generation) {
        throw new PdfParseError(
          `object ${num} generation ${parsed.generation} referenced as ${generation}`
        );
      }
      objectCache.set(num, parsed);
      return parsed;
    };

    // The batch's page sequence: trailer /Root -> /Catalog -> /Pages -> /Kids, following
    // nested /Pages nodes (defensive - react-pdf emits a flat tree).
    const catalogRef = dictValueEntry(trailer, "Root");
    if (catalogRef?.kind !== "reference") {
      throw new PdfParseError("trailer /Root is not an indirect reference");
    }
    const catalog = parseNumberedObject(
      catalogRef.objectNumber,
      catalogRef.generation
    );
    const pagesRef = dictValueEntry(catalog.dict, "Pages");
    if (pagesRef?.kind !== "reference") {
      throw new PdfParseError("catalog /Pages is not an indirect reference");
    }

    const pageNumbers: Array<number> = [];
    const collectPages = (
      pagesNodeNumber: number,
      nodeGeneration: number
    ): void => {
      const node = parseNumberedObject(pagesNodeNumber, nodeGeneration);
      const kids = dictValueEntry(node.dict, "Kids");
      if (kids?.kind !== "array") {
        throw new PdfParseError("/Pages /Kids is not an array");
      }
      for (const kid of kids.items) {
        if (kid.kind !== "reference") {
          throw new PdfParseError(
            "/Pages /Kids entry is not an indirect reference"
          );
        }
        const kidObject = parseNumberedObject(kid.objectNumber, kid.generation);
        const type = dictValueEntry(kidObject.dict, "Type");
        const typeName = type?.kind === "name" ? `/${type.value}` : undefined;
        if (typeName === "/Pages") {
          collectPages(kid.objectNumber, kid.generation);
        } else if (typeName === "/Page") {
          kidObject.isPage = true;
          pageNumbers.push(kid.objectNumber);
        } else {
          throw new PdfParseError(
            `/Pages /Kids entry has unsupported /Type ${typeName ?? "<none>"}`
          );
        }
      }
    };
    collectPages(pagesRef.objectNumber, pagesRef.generation);

    // Reachability walk from the pages (DFS, pages first so they get the lowest global
    // numbers). /Length and page /Parent refs are skipped: /Length is direct-ized at emit
    // and page /Parent is rewritten to the global /Pages node - neither target is carried.
    const visitedOrder: Array<number> = [];
    const visited = new Set<number>();
    const visit = (num: number): void => {
      if (visited.has(num)) return;
      visited.add(num);
      visitedOrder.push(num);
      const obj = parseNumberedObject(num, 0);
      enqueueRefs(obj.dict);
    };
    const enqueueRefs = (value: PdfValue): void => {
      if (value.kind === "reference") {
        visit(value.objectNumber);
        return;
      }
      if (value.kind === "array") {
        for (const item of value.items) enqueueRefs(item);
        return;
      }
      if (value.kind === "dict") {
        for (const entry of value.entries) {
          const key = nameOf(entry.name);
          if (key === "Length" || key === "Parent") continue;
          enqueueRefs(entry.value);
        }
      }
    };
    for (const pageNum of pageNumbers) visit(pageNum);

    // FIRST pass: assign every visited object its global number, so references during
    // emission resolve even when the target is emitted later (an object may reference a
    // resource that comes after it in visit order).
    const globalByBatchNumber = new Map<number, number>();
    for (const batchNum of visitedOrder) {
      globalByBatchNumber.set(batchNum, this.nextObjectNumber++);
    }

    // SECOND pass: emit in the same order.
    const pagesInBatch = new Set(pageNumbers);
    const batchStartOffset = this.offset;
    let objectsEmitted = 0;
    for (const batchNum of visitedOrder) {
      const obj = parseNumberedObject(batchNum, 0);
      const global = globalByBatchNumber.get(batchNum) as number;
      this.objectOffsets[global] = this.offset;
      await this.writeText(`${global} 0 obj\n`);

      const ctx = {
        isPage: pagesInBatch.has(batchNum),
        streamLength: obj.stream?.length,
        globalByBatchNumber,
      };
      await this.emitValue(obj.dict, ctx);

      if (obj.stream !== null) {
        await this.writeText("\nstream\n");
        await this.writeBytes(
          bytes.subarray(obj.stream.dataStart, obj.stream.dataEnd)
        );
        await this.writeText("\nendstream\n");
      }
      await this.writeText("endobj\n");
      objectsEmitted++;
      if (obj.isPage === true) {
        this.pageGlobalNumbers.push(global);
      }
    }

    return {
      pagesAppended: pageNumbers.length,
      objectsEmitted,
      bytesWritten: this.offset - batchStartOffset,
    };
  }

  /**
   * Re-emits a parsed value with reference rewrites: indirect refs -> global numbers, page
   * /Parent -> the global /Pages node, and stream /Length -> a direct integer (the source
   * value was already verified against the true stream extent in parseObject). Every other
   * token is emitted from its raw source text, so formatting never changes semantics.
   */
  private async emitValue(
    value: PdfValue,
    ctx: {
      isPage: boolean;
      streamLength: number | undefined;
      globalByBatchNumber: Map<number, number>;
    }
  ): Promise<void> {
    if (value.kind === "dict") {
      await this.writeText("<< ");
      for (const entry of value.entries) {
        const key = nameOf(entry.name);
        if (key === "Length" && ctx.streamLength !== undefined) {
          // Direct-ize: `/Length <n>` replaces whatever the source declared.
          await this.writeText(`/Length ${ctx.streamLength} `);
          continue;
        }
        if (key === "Parent" && ctx.isPage) {
          await this.writeText(`/Parent ${PDF_PAGES_NODE_NUMBER} 0 R `);
          continue;
        }
        await this.writeText(`${entry.name.raw} `);
        await this.emitValue(entry.value, ctx);
        await this.writeText(" ");
      }
      await this.writeText(">>");
      return;
    }
    if (value.kind === "array") {
      await this.writeText("[");
      for (const item of value.items) {
        await this.writeText(" ");
        await this.emitValue(item, ctx);
      }
      await this.writeText(" ]");
      return;
    }
    if (value.kind === "reference") {
      const global = ctx.globalByBatchNumber.get(value.objectNumber);
      if (global === undefined) {
        throw new PdfParseError(
          `unvisited reference ${value.objectNumber} ${value.generation} R in reachable object`
        );
      }
      await this.writeText(`${global} 0 R`);
      return;
    }
    await this.writeText(value.raw);
  }

  /**
   * Writes the /Pages node, /Catalog, xref table and trailer - the only tail objects, in a
   * single forward pass with zero seeks. Returns the final byte length (the caller then
   * closes / hands off the sink).
   */
  async finalize(): Promise<FinalizeResult> {
    if (!this.headerWritten) {
      // Zero batches (an empty export that never rendered): emit an empty, valid document.
      await this.writeText(PDF_HEADER);
      this.headerWritten = true;
    }
    const pageCount = this.pageGlobalNumbers.length;

    // /Pages node (global number 1) - written LAST in the file; object numbers need not
    // follow file order.
    const pagesNodeOffset = this.offset;
    this.objectOffsets[PDF_PAGES_NODE_NUMBER] = pagesNodeOffset;
    const kidsText = this.pageGlobalNumbers.map((g) => `${g} 0 R`).join(" ");
    await this.writeText(
      `${PDF_PAGES_NODE_NUMBER} 0 obj\n` +
        `<< /Type /Pages /Kids [ ${kidsText} ] /Count ${pageCount} >>\nendobj\n`
    );

    const catalogOffset = this.offset;
    this.objectOffsets[PDF_CATALOG_NUMBER] = catalogOffset;
    await this.writeText(
      `${PDF_CATALOG_NUMBER} 0 obj\n` +
        `<< /Type /Catalog /Pages ${PDF_PAGES_NODE_NUMBER} 0 R /PageMode /UseThumbs >>\n` +
        `endobj\n`
    );

    // xref table: one entry per object 0..highest, classic 20-byte rows. Entry 0 is the
    // free head; everything else points at its recorded offset.
    const objectCount = this.nextObjectNumber; // next free number == count of used numbers
    const xrefOffset = this.offset;
    await this.writeText("xref\n");
    let entryIndex = 0;
    while (entryIndex < objectCount) {
      const chunkStart = entryIndex;
      const chunkEnd = Math.min(objectCount, entryIndex + 20);
      await this.writeText(`${chunkStart} ${chunkEnd - chunkStart}\n`);
      for (let num = chunkStart; num < chunkEnd; num++) {
        if (num === 0) {
          await this.writeText(`0000000000 65535 f \n`);
        } else {
          const offset = this.objectOffsets[num];
          await this.writeText(
            `${String(offset).padStart(10, "0")} 00000 n \n`
          );
        }
      }
      entryIndex = chunkEnd;
    }
    await this.writeText(
      `trailer\n<< /Size ${objectCount} /Root ${PDF_CATALOG_NUMBER} 0 R >>\n` +
        `startxref\n${xrefOffset}\n%%EOF\n`
    );

    return { pageCount, byteLength: this.offset };
  }
}
