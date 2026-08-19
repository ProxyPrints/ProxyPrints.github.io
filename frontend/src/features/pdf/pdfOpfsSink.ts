import type { ByteSink } from "./pdfIncrementalWriter";

// pdf.worker.ts's own OPFS-backed ByteSink - the piece pdfIncrementalWriter.ts's module doc
// refers to as "the worker sinks to OPFS" but never shipped. Writing to a private-origin file
// instead of an in-memory buffer is what actually removes the assembly-memory ceiling: nothing
// the writer produces is ever held in the worker's JS heap at once, matching PAGES_PER_BATCH's
// existing bound on render memory with an equivalent bound on write memory.
export interface RenderByteSink extends ByteSink {
  /** Closes the sink and returns everything written, without loading it into the JS heap. */
  toBlob(): Promise<Blob>;
}

const OPFS_TEMP_FILE_PREFIX = "pdf-export-";

export class OpfsSink implements RenderByteSink {
  private constructor(
    private readonly root: FileSystemDirectoryHandle,
    private readonly writable: FileSystemWritableFileStream,
    private readonly fileHandle: FileSystemFileHandle
  ) {}

  static async create(): Promise<OpfsSink> {
    const root = await navigator.storage.getDirectory();
    const fileHandle = await root.getFileHandle(
      `${OPFS_TEMP_FILE_PREFIX}${crypto.randomUUID()}.pdf`,
      { create: true }
    );
    const writable = await fileHandle.createWritable();
    return new OpfsSink(root, writable, fileHandle);
  }

  async write(view: Uint8Array): Promise<void> {
    // Same ArrayBufferLike->ArrayBuffer re-wrap pdfMerger.ts's saveMergedPDFBlob does - the
    // modern TS DOM lib's FileSystemWriteChunkType rejects pdf-lib/TS-era ArrayBufferLike views.
    await this.writable.write(new Uint8Array(view));
  }

  async toBlob(): Promise<Blob> {
    await this.writable.close();
    return this.fileHandle.getFile();
  }
}

// Removes any temp files a PRIOR renderPDF() call's OpfsSink left behind. Deliberately not
// self-cleaning inside OpfsSink itself: the File returned by toBlob() is handed off (postMessage
// transfer, then a browser download) on a timeline this module doesn't control, and removing the
// backing OPFS entry too early risks invalidating that File in some browsers. Running this once
// at the START of the NEXT render is safe - by then the previous render's Blob has already been
// fully consumed - and requires no cleanup bookkeeping of its own.
export const cleanupStaleOpfsSinks = async (): Promise<void> => {
  try {
    const root = await navigator.storage.getDirectory();
    for await (const name of root.keys()) {
      if (name.startsWith(OPFS_TEMP_FILE_PREFIX)) {
        await root.removeEntry(name).catch(() => undefined);
      }
    }
  } catch {
    // OPFS unavailable, or directory iteration unsupported - nothing to clean up.
  }
};

export const isOpfsAvailable = (): boolean =>
  typeof navigator !== "undefined" &&
  navigator.storage !== undefined &&
  typeof navigator.storage.getDirectory === "function";
