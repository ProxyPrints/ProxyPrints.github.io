import { getBucketImageURL, getWorkerImageURL } from "@/common/image";
import { SourceType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

export type PDFImageQuality =
  | "small-thumbnail"
  | "large-thumbnail"
  | "full-resolution";

/** A card whose image couldn't be fetched for a PDF render. */
export interface ImageFetchFailure {
  identifier: string;
  label: string;
}

/**
 * The same card can appear in more than one slot in a render (e.g. as both
 * a front and a back), producing one ImageFetchFailure per failed slot. For
 * a human-facing message ("which cards will be blank?") that's noise - the
 * user needs to know which cards, not how many slots - so callers building
 * a message from a raw failures list should dedupe by identifier first.
 */
export const dedupeFailuresByIdentifier = (
  failures: Array<ImageFetchFailure>
): Array<ImageFetchFailure> => {
  const seen = new Set<string>();
  return failures.filter((failure) => {
    if (seen.has(failure.identifier)) {
      return false;
    }
    seen.add(failure.identifier);
    return true;
  });
};

/**
 * Fetch a URL's body and hand it back as a Blob. Unlike passing the plain
 * remote URL straight to @react-pdf/renderer's <Image> (which fetches it
 * internally and silently skips the image on failure, with no way for
 * calling code to observe that), fetching it ourselves lets a failure
 * surface as a real rejection the caller can catch and report.
 */
const fetchAsBlob = async (url: string): Promise<Blob> => {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`request for ${url} failed with status ${response.status}`);
  }
  return response.blob();
};

/**
 * Small/large thumbnails: try the R2 bucket domain first (no Worker compute
 * on a cache hit), falling back to the Worker on a miss (which also
 * populates the cache for next time). Mirrors Card.tsx's bucket-first /
 * worker-fallback behaviour. Both legs are validated by actually fetching
 * the image body (not just a HEAD check on the bucket leg) so a genuine
 * fetch failure on either domain propagates as a rejection instead of
 * being silently swallowed later.
 */
const getThumbnailURL = async (
  cardDocument: CardDocument,
  size: "small" | "large",
  jpgQuality: number
): Promise<string> => {
  const bucketURL = getBucketImageURL(cardDocument, size);
  if (bucketURL !== undefined) {
    try {
      return URL.createObjectURL(await fetchAsBlob(bucketURL));
    } catch {
      // bucket miss or network error - fall through to the worker
    }
  }
  const workerURL = getWorkerImageURL(
    cardDocument,
    size,
    undefined,
    jpgQuality
  );
  if (workerURL === undefined) {
    throw new Error(
      `no image source configured for card ${cardDocument.identifier}`
    );
  }
  return URL.createObjectURL(await fetchAsBlob(workerURL));
};

/**
 * Resolve the image source for a card in a PDF, honouring the requested quality
 * tier and the card's source (Google Drive image worker, or a local file).
 * Shared by the standard PDF render path and the SCM render path. Rejects
 * (rather than resolving to a URL that might later fail to load) when the
 * image genuinely couldn't be fetched - see ImageFetchFailure/callers of
 * this function for how that's surfaced to the user.
 */
export const getPDFImageURL = async (
  cardDocument: CardDocument,
  imageQuality: PDFImageQuality,
  dpi: number | undefined,
  jpgQuality: number,
  fileHandles: { [identifier: string]: FileSystemFileHandle }
): Promise<string> => {
  switch (cardDocument.sourceType) {
    case SourceType.GoogleDrive:
      switch (imageQuality) {
        case "small-thumbnail":
          return getThumbnailURL(cardDocument, "small", jpgQuality);
        case "large-thumbnail":
          return getThumbnailURL(cardDocument, "large", jpgQuality);
        case "full-resolution": {
          const workerURL = getWorkerImageURL(
            cardDocument,
            "full",
            dpi,
            jpgQuality
          );
          if (workerURL === undefined) {
            throw new Error(
              `no image source configured for card ${cardDocument.identifier}`
            );
          }
          return URL.createObjectURL(await fetchAsBlob(workerURL));
        }
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

/**
 * Resolves the raw image Blob for a card's full-resolution PDF source (Google Drive image
 * worker, or a local file) - the entry point Proposal B's bleed normalization
 * (bleedExtension.ts's normalizeCardBleed, called from PDF.tsx's PDFCardImage) needs a decodable
 * Blob from, not yet a blob: URL. Deliberately separate from getPDFImageURL above (rather than
 * one calling the other) so each keeps its own simple, independently-tested error contract -
 * only covers the two sources full-resolution bleed normalization actually applies to; thumbnail
 * tiers are out of scope (see the proposal doc) and keep using getPDFImageURL directly.
 */
export const getPDFImageBlob = async (
  cardDocument: CardDocument,
  dpi: number | undefined,
  jpgQuality: number,
  fileHandles: { [identifier: string]: FileSystemFileHandle }
): Promise<Blob> => {
  switch (cardDocument.sourceType) {
    case SourceType.GoogleDrive: {
      const workerURL = getWorkerImageURL(
        cardDocument,
        "full",
        dpi,
        jpgQuality
      );
      if (workerURL === undefined) {
        throw new Error(
          `no image source configured for card ${cardDocument.identifier}`
        );
      }
      return fetchAsBlob(workerURL);
    }
    case SourceType.LocalFile: {
      const handle = fileHandles[cardDocument.identifier];
      if (handle === undefined) {
        throw new Error(
          `could not get handle for file ${cardDocument.identifier}`
        );
      }
      return handle.getFile();
    }
    default:
      throw new Error(
        `cannot get PDF image blob for card ${cardDocument.identifier}`
      );
  }
};
