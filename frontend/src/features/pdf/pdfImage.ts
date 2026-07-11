import { getBucketImageURL, getWorkerImageURL } from "@/common/image";
import { SourceType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

export type PDFImageQuality =
  | "small-thumbnail"
  | "large-thumbnail"
  | "full-resolution";

/**
 * Small/large thumbnails: try the R2 bucket domain first (no Worker compute
 * on a cache hit), falling back to the Worker on a miss (which also
 * populates the cache for next time). Mirrors Card.tsx's bucket-first /
 * worker-fallback behaviour, but via a HEAD check instead of <img onError>
 * since @react-pdf/renderer's <Image> component has no onError hook to key a
 * retry off of.
 */
const getThumbnailURL = async (
  cardDocument: CardDocument,
  size: "small" | "large",
  jpgQuality: number
): Promise<string | undefined> => {
  const bucketURL = getBucketImageURL(cardDocument, size);
  if (bucketURL !== undefined) {
    try {
      const response = await fetch(bucketURL, { method: "HEAD" });
      if (response.ok) {
        return bucketURL;
      }
    } catch {
      // network error reaching the bucket domain - fall through to the worker
    }
  }
  return getWorkerImageURL(cardDocument, size, undefined, jpgQuality);
};

/**
 * Resolve the image source for a card in a PDF, honouring the requested quality
 * tier and the card's source (Google Drive image worker, or a local file).
 * Shared by the standard PDF render path and the SCM render path.
 */
export const getPDFImageURL = async (
  cardDocument: CardDocument,
  imageQuality: PDFImageQuality,
  dpi: number | undefined,
  jpgQuality: number,
  fileHandles: { [identifier: string]: FileSystemFileHandle }
): Promise<string | Blob | undefined> => {
  switch (cardDocument.sourceType) {
    case SourceType.GoogleDrive:
      switch (imageQuality) {
        case "small-thumbnail":
          return getThumbnailURL(cardDocument, "small", jpgQuality);
        case "large-thumbnail":
          return getThumbnailURL(cardDocument, "large", jpgQuality);
        case "full-resolution":
          return getWorkerImageURL(cardDocument, "full", dpi, jpgQuality);
        default:
          throw new Error(`invalid imageQuality ${imageQuality}`);
      }

    case SourceType.LocalFile:
      const handle = fileHandles[cardDocument.identifier];
      if (handle !== undefined) {
        return URL.createObjectURL(await handle.getFile());
      } else {
        throw new Error(
          `could not get handle for file ${cardDocument.identifier}`
        );
      }
    default:
      throw new Error(
        `cannot get PDF thumbnail URL for card ${cardDocument.identifier}`
      );
  }
};
