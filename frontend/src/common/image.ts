import { CardDocument } from "./types";

export const getImageKey = (
  cardDocument: CardDocument,
  size: "small" | "large"
): string => {
  return `${cardDocument.identifier}-${size}-${cardDocument.sourceType
    ?.toLowerCase()
    .replace(" ", "_")}`;
};

export const getImageBucketURL = () => process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL;
export const getImageWorkerURL = () => process.env.NEXT_PUBLIC_IMAGE_WORKER_URL;

const attachHttpsPrefix = (url: string): string =>
  url.startsWith("http://") || url.startsWith("https://")
    ? url
    : `https://${url}`;

export const getBucketImageURL = (
  cardDocument: CardDocument,
  size: "small" | "large" | "full"
) => {
  if (size === "full") {
    throw new Error(
      "Cannot get full-res image through bucket, fetch through worker instead"
    );
  }
  const imageBucketURL = getImageBucketURL();
  // TODO: support other source types through CDN here
  const imageBucketURLValid =
    imageBucketURL != null && !!(cardDocument.sourceType === "Google Drive");
  return imageBucketURLValid
    ? new URL(
        getImageKey(cardDocument, size),
        attachHttpsPrefix(imageBucketURL)
      ).toString()
    : undefined;
};

export const getWorkerImageURL = (
  cardDocument: CardDocument,
  size: "small" | "large" | "full",
  dpi: number | undefined = undefined,
  jpgQuality: number = 100
) => {
  const imageWorkerURL = getImageWorkerURL();
  const imageWorkerURLValid =
    imageWorkerURL != null && !!(cardDocument?.sourceType === "Google Drive");
  const params = new URLSearchParams({
    ...(dpi !== undefined && size === "full" ? { dpi: dpi.toString() } : {}),
    jpgQuality: jpgQuality.toString(),
  });
  return imageWorkerURLValid
    ? new URL(
        `/images/google_drive/${size}/${cardDocument?.identifier}.jpg?${params}`,
        attachHttpsPrefix(imageWorkerURL)
      ).toString()
    : undefined;
};

// Sheet slots render far below native card resolution, so `small` suffices here.
//
// `getBucketImageURL` only checks that the bucket is *configured*, never that the object
// actually exists there - most Google Drive cards resolve to a bucket URL, but any card whose
// image isn't actually in the bucket yields a URL that 404s. Unlike `useImageSrc` (Card.tsx),
// this module has no React state to step through candidates on load failure, so it exposes the
// full ordered chain instead of picking one URL and hoping it loads - callers with a recovery
// path (PagePreview's sheet slots) can fall through it the same way Card.tsx's own `onError`
// handler falls through bucket -> worker -> thumbnail.
export const getSheetImageURLs = (
  cardDocument: CardDocument
): Array<string> => {
  const urls: Array<string> = [];
  const bucketURL = getBucketImageURL(cardDocument, "small");
  if (bucketURL != null) {
    urls.push(bucketURL);
  }
  const workerURL = getWorkerImageURL(cardDocument, "small");
  if (workerURL != null) {
    urls.push(workerURL);
  }
  if (cardDocument.mediumThumbnailUrl != null) {
    urls.push(cardDocument.mediumThumbnailUrl);
  }
  return urls;
};

export const getSheetImageURL = (
  cardDocument: CardDocument
): string | undefined => getSheetImageURLs(cardDocument)[0];
