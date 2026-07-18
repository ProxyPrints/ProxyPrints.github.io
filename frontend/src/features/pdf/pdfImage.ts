import { getBucketImageURL, getWorkerImageURL } from "@/common/image";
import { SourceType } from "@/common/schema_types";
import { Semaphore } from "@/common/semaphore";
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

// The image-CDN Worker's full-resolution tier bypasses its R2 cache entirely and shares one
// GLOBAL 3-req/s rate limiter with every other full-tier caller (live bulk download, the
// backend's own backfill pilot - see docs/features/image-cdn.md), enforced server-side via a
// Cloudflare rate limiter binding with its own internal retry/backoff (image-cdn/src/utils.ts's
// fetchWithRateLimit, MAX_RATE_LIMIT_RETRIES=5). That server-side pacing only protects the
// UPSTREAM Google endpoint - it does nothing to stop THIS client from firing many concurrent
// requests at the Worker in the first place. @react-pdf/renderer resolves every card's <Image
// src={async () => ...}> callback with its own internal concurrency, entirely outside this
// codebase's control (see the proposal doc's implementation notes) - a large export can trigger
// dozens of simultaneous full-resolution fetches with zero client-side pacing, each one
// independently exhausting its own server-side retry budget under that contention and coming
// back as a permanent per-card failure. Root-caused via a real incident: 104/~104 full-resolution
// images failed on one large export (see docs/reports/export-image-rate-limit-fix.md).
// CALIBRATION CAVEAT: matches the server's own limit exactly rather than being empirically tuned
// against real network conditions - if the server-side limit ever changes, this should move with
// it.
export const FULL_RESOLUTION_FETCH_CONCURRENCY = 3;
// Retries only genuinely transient failures (429 rate-limited, or a 5xx from the Worker/Google
// itself) - a 4xx other than 429 (404 for a real dead link, 400 for a malformed request) is
// retried zero times, since nothing about waiting and asking again would fix it, and burning a
// retry budget on it just delays every other card queued behind this concurrency gate.
export const FULL_RESOLUTION_FETCH_MAX_RETRIES = 3;
const fullResolutionFetchSemaphore = new Semaphore(
  FULL_RESOLUTION_FETCH_CONCURRENCY
);

const isRetryableStatus = (status: number): boolean =>
  status === 429 || status >= 500;

const delay = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Like fetchAsBlob, but paced to the image-CDN Worker's shared full-resolution concurrency
 * ceiling and tolerant of transient (429/5xx) failures via a short retry-with-backoff - see the
 * constants above for why. Used for every full-resolution Google Drive fetch (both
 * getPDFImageURL's and getPDFImageBlob's), since the mass-failure risk applies equally to any
 * full-resolution export, not just bleed-normalized cards.
 */
export const fetchFullResolutionImageAsBlob = async (
  url: string
): Promise<Blob> => {
  const release = await fullResolutionFetchSemaphore.acquire();
  try {
    for (
      let attempt = 0;
      attempt <= FULL_RESOLUTION_FETCH_MAX_RETRIES;
      attempt++
    ) {
      const lastAttempt = attempt === FULL_RESOLUTION_FETCH_MAX_RETRIES;
      let response: Response;
      try {
        response = await fetch(url);
      } catch (networkError) {
        // A network-level failure (offline, connection reset) - always worth one more try,
        // same as a retryable HTTP status below.
        if (lastAttempt) {
          throw networkError;
        }
        await delay(2 ** attempt * 250 + Math.random() * 250);
        continue;
      }
      if (response.ok) {
        return await response.blob();
      }
      // A non-retryable status (a real 404 dead link, a malformed request) fails immediately,
      // outside any retry - waiting and asking again wouldn't fix it, and burning a retry
      // budget on it just delays every other card queued behind this concurrency gate.
      if (!isRetryableStatus(response.status) || lastAttempt) {
        throw new Error(
          `request for ${url} failed with status ${response.status}`
        );
      }
      // Exponential backoff with jitter, same shape as the Worker's own
      // fetchWithRateLimit - gives the shared rate limiter time to free up a slot rather than
      // hammering it again immediately.
      await delay(2 ** attempt * 250 + Math.random() * 250);
    }
    // Unreachable - the loop above always either returns or throws on its last iteration.
    throw new Error(`request for ${url} failed after retries`);
  } finally {
    release();
  }
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
          return URL.createObjectURL(
            await fetchFullResolutionImageAsBlob(workerURL)
          );
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
      return fetchFullResolutionImageAsBlob(workerURL);
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
