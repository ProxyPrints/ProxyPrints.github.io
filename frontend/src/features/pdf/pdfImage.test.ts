import { getBucketImageURL, getWorkerImageURL } from "@/common/image";
import { SourceType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";
import { LayoutEdgeBleed } from "@/features/pdf/layout";

import {
  computeBleedCropMM,
  computeBleedCropWindowPx,
  computeRenderedBleedMM,
  createTrackedObjectURL,
  fetchFullResolutionImageAsBlob,
  FULL_RESOLUTION_FETCH_CONCURRENCY,
  FULL_RESOLUTION_FETCH_MAX_RETRIES,
  getPDFImageBlob,
  getPDFImageURL,
  resetImageBlobCache,
  revokeTrackedObjectURLs,
} from "./pdfImage";

jest.mock("../../common/image", () => ({
  getBucketImageURL: jest.fn(),
  getWorkerImageURL: jest.fn(),
}));

const mockGetBucketImageURL = getBucketImageURL as jest.Mock;
const mockGetWorkerImageURL = getWorkerImageURL as jest.Mock;

const googleDriveCard = (identifier = "card-1"): CardDocument =>
  ({
    identifier,
    name: `Test Card ${identifier}`,
    sourceType: SourceType.GoogleDrive,
  } as CardDocument);

const okResponse = () =>
  ({ ok: true, status: 200, blob: async () => new Blob() } as Response);
const errorResponse = (status = 500) =>
  ({ ok: false, status, blob: async () => new Blob() } as Response);

describe("getPDFImageURL", () => {
  beforeEach(() => {
    // getCachedImageBlob's cache is module-level and several tests below reuse the same
    // identifier ("card-1") - reset it so one test's fetch never silently satisfies a later
    // test's assertions on fetch call counts.
    resetImageBlobCache();
    jest.spyOn(global, "fetch").mockReset();
    jest
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => "blob:mock-object-url");
    mockGetBucketImageURL.mockReset();
    mockGetWorkerImageURL.mockReset();
  });

  it("returns a blob URL fetched from the bucket domain on a bucket hit", async () => {
    mockGetBucketImageURL.mockReturnValue("https://bucket.test/card-1-small");
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-small");
    jest.spyOn(global, "fetch").mockResolvedValue(okResponse());

    const url = await getPDFImageURL(
      googleDriveCard(),
      "small-thumbnail",
      undefined,
      100,
      {}
    );

    expect(url).toBe("blob:mock-object-url");
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(
      "https://bucket.test/card-1-small"
    );
  });

  it("falls back to the worker domain when the bucket fetch fails", async () => {
    mockGetBucketImageURL.mockReturnValue("https://bucket.test/card-1-small");
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-small");
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(errorResponse(404))
      .mockResolvedValueOnce(okResponse());

    const url = await getPDFImageURL(
      googleDriveCard(),
      "small-thumbnail",
      undefined,
      100,
      {}
    );

    expect(url).toBe("blob:mock-object-url");
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      "https://worker.test/card-1-small"
    );
  });

  it("rejects when both the bucket and worker fetches fail", async () => {
    mockGetBucketImageURL.mockReturnValue("https://bucket.test/card-1-small");
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-small");
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(500));

    await expect(
      getPDFImageURL(googleDriveCard(), "small-thumbnail", undefined, 100, {})
    ).rejects.toThrow();
  });

  it("rejects a failed full-resolution fetch instead of resolving to an unvalidated URL", async () => {
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-full");
    // 404 (not 429/5xx) - a non-retryable status, so this asserts the plain fail-fast path
    // without needing fake timers for the retry backoff. See the "retry" describe block below
    // for 429/5xx-specific coverage.
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(404));

    await expect(
      getPDFImageURL(googleDriveCard(), "full-resolution", 300, 100, {})
    ).rejects.toThrow(/404/);
  });

  it("rejects full-resolution when no worker URL is configured", async () => {
    mockGetWorkerImageURL.mockReturnValue(undefined);

    await expect(
      getPDFImageURL(googleDriveCard(), "full-resolution", 300, 100, {})
    ).rejects.toThrow(/no image source configured/);
  });

  it("resolves a local file card via its file handle", async () => {
    const file = new File(["contents"], "card.png");
    const getFile = jest.fn().mockResolvedValue(file);
    const card = {
      identifier: "local-1",
      name: "Local Card",
      sourceType: SourceType.LocalFile,
    } as CardDocument;

    const url = await getPDFImageURL(card, "full-resolution", undefined, 100, {
      "local-1": { getFile } as unknown as FileSystemFileHandle,
    });

    expect(url).toBe("blob:mock-object-url");
    expect(getFile).toHaveBeenCalledTimes(1);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects a local file card with no matching file handle", async () => {
    const card = {
      identifier: "local-missing",
      name: "Missing Local Card",
      sourceType: SourceType.LocalFile,
    } as CardDocument;

    await expect(
      getPDFImageURL(card, "full-resolution", undefined, 100, {})
    ).rejects.toThrow(/could not get handle/);
  });

  it("rejects an unsupported source type", async () => {
    const card = {
      identifier: "s3-1",
      name: "S3 Card",
      sourceType: SourceType.AwsS3,
    } as CardDocument;

    await expect(
      getPDFImageURL(card, "full-resolution", undefined, 100, {})
    ).rejects.toThrow(/cannot get PDF thumbnail URL/);
  });
});

describe("getPDFImageBlob", () => {
  beforeEach(() => {
    resetImageBlobCache();
    jest.spyOn(global, "fetch").mockReset();
    mockGetWorkerImageURL.mockReset();
  });

  it("resolves the raw Blob for a Google Drive card's full-resolution worker URL", async () => {
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-full");
    jest.spyOn(global, "fetch").mockResolvedValue(okResponse());

    const blob = await getPDFImageBlob(googleDriveCard(), 300, 100, {});

    expect(blob).toBeInstanceOf(Blob);
    expect(global.fetch).toHaveBeenCalledWith(
      "https://worker.test/card-1-full"
    );
  });

  it("rejects a failed fetch instead of resolving to an unvalidated Blob", async () => {
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-full");
    // 404 (not 429/5xx) - a non-retryable status; see the "retry" describe block below for
    // 429/5xx-specific coverage.
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(404));

    await expect(
      getPDFImageBlob(googleDriveCard(), 300, 100, {})
    ).rejects.toThrow(/404/);
  });

  it("resolves a local file card's Blob directly via its file handle, without fetching", async () => {
    const file = new File(["contents"], "card.png");
    const getFile = jest.fn().mockResolvedValue(file);
    const card = {
      identifier: "local-1",
      name: "Local Card",
      sourceType: SourceType.LocalFile,
    } as CardDocument;

    const blob = await getPDFImageBlob(card, undefined, 100, {
      "local-1": { getFile } as unknown as FileSystemFileHandle,
    });

    expect(blob).toBe(file);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects an unsupported source type", async () => {
    const card = {
      identifier: "s3-1",
      name: "S3 Card",
      sourceType: SourceType.AwsS3,
    } as CardDocument;

    await expect(getPDFImageBlob(card, undefined, 100, {})).rejects.toThrow(
      /cannot get PDF image blob/
    );
  });
});

describe("getPDFImageURL / getPDFImageBlob - per-batch fetch dedup by identifier", () => {
  beforeEach(() => {
    resetImageBlobCache();
    // Drains URLs any earlier test in this file registered but never revoked - see the
    // "createTrackedObjectURL / revokeTrackedObjectURLs" describe block's own comment.
    revokeTrackedObjectURLs();
    jest.spyOn(global, "fetch").mockReset();
    jest
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => `blob:${Math.random()}`);
    mockGetWorkerImageURL.mockImplementation(
      (card: CardDocument) => `https://worker.test/${card.identifier}-full`
    );
  });

  it("concurrent full-resolution requests for the same identifier share ONE fetch, not one per slot", async () => {
    let resolveFetch: (value: Response) => void = () => undefined;
    const pendingFetch = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    const fetchSpy = jest.spyOn(global, "fetch").mockReturnValue(pendingFetch);

    const card = googleDriveCard("dup-card");
    const slotCount = 4;
    const results = Promise.all(
      Array.from({ length: slotCount }, () =>
        getPDFImageURL(card, "full-resolution", 300, 100, {})
      )
    );
    // Let every slot's call register against the shared in-flight promise before it resolves -
    // this is what proves it's a shared in-flight promise, not just a cache populated after the
    // first slot's fetch has already completed.
    await Promise.resolve();
    await Promise.resolve();
    resolveFetch(okResponse());
    const urls = await results;

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(urls).toHaveLength(slotCount);
  });

  it("a duplicate-heavy deck fetches once per DISTINCT identifier, not once per slot", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(okResponse());

    // 4 copies of card-a, 2 of card-b, 1 of card-c: 7 slots, 3 distinct identifiers.
    const slots = [
      googleDriveCard("card-a"),
      googleDriveCard("card-a"),
      googleDriveCard("card-a"),
      googleDriveCard("card-a"),
      googleDriveCard("card-b"),
      googleDriveCard("card-b"),
      googleDriveCard("card-c"),
    ];

    await Promise.all(
      slots.map((card) => getPDFImageURL(card, "full-resolution", 300, 100, {}))
    );

    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("subsequent (non-concurrent) requests for the same identifier also reuse the cached fetch", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(okResponse());
    const card = googleDriveCard("dup-card-sequential");

    await getPDFImageURL(card, "full-resolution", 300, 100, {});
    await getPDFImageURL(card, "full-resolution", 300, 100, {});
    await getPDFImageURL(card, "full-resolution", 300, 100, {});

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("resetImageBlobCache (the per-batch boundary) makes a later batch refetch the same identifier", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(okResponse());
    const card = googleDriveCard("dup-card-batch-boundary");

    await getPDFImageURL(card, "full-resolution", 300, 100, {});
    resetImageBlobCache();
    await getPDFImageURL(card, "full-resolution", 300, 100, {});

    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("two slots sharing one deduped fetch each get their OWN object URL - both remain independently revocable", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(okResponse());
    let urlCounter = 0;
    jest
      .spyOn(URL, "createObjectURL")
      .mockImplementation(() => `blob:tracked-${urlCounter++}`);
    const revokeSpy = jest
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const card = googleDriveCard("dup-card-url-lifecycle");

    const urlA = await getPDFImageURL(card, "full-resolution", 300, 100, {});
    const urlB = await getPDFImageURL(card, "full-resolution", 300, 100, {});

    expect(urlA).not.toBe(urlB);

    revokeTrackedObjectURLs();

    expect(revokeSpy).toHaveBeenCalledWith(urlA);
    expect(revokeSpy).toHaveBeenCalledWith(urlB);
    expect(revokeSpy).toHaveBeenCalledTimes(2);
  });

  it("a rejected fetch is shared too - every slot for the failed identifier rejects, without a second fetch attempt", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(errorResponse(404));
    const card = googleDriveCard("dup-card-failure");

    await expect(
      getPDFImageURL(card, "full-resolution", 300, 100, {})
    ).rejects.toThrow(/404/);
    await expect(
      getPDFImageURL(card, "full-resolution", 300, 100, {})
    ).rejects.toThrow(/404/);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("getPDFImageBlob (the bleed-normalization path) also dedupes by identifier", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(okResponse());
    const card = googleDriveCard("dup-card-blob-path");

    await getPDFImageBlob(card, 300, 100, {});
    await getPDFImageBlob(card, 300, 100, {});

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

describe("fetchFullResolutionImageAsBlob - shared pacing and retry (export-image-rate-limit-fix)", () => {
  beforeEach(() => {
    jest.spyOn(global, "fetch").mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("retries a 429 and succeeds once the shared rate limiter frees up", async () => {
    jest.useFakeTimers();
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(errorResponse(429))
      .mockResolvedValueOnce(okResponse());

    const promise = fetchFullResolutionImageAsBlob("https://worker.test/full");
    await jest.advanceTimersByTimeAsync(5_000);
    const blob = await promise;

    expect(blob).toBeInstanceOf(Blob);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("retries a 5xx (Worker/Google transient failure) and succeeds", async () => {
    jest.useFakeTimers();
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(okResponse());

    const promise = fetchFullResolutionImageAsBlob("https://worker.test/full");
    await jest.advanceTimersByTimeAsync(5_000);
    const blob = await promise;

    expect(blob).toBeInstanceOf(Blob);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("retries a network-level fetch rejection, not just a bad HTTP status", async () => {
    jest.useFakeTimers();
    jest
      .spyOn(global, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(okResponse());

    const promise = fetchFullResolutionImageAsBlob("https://worker.test/full");
    await jest.advanceTimersByTimeAsync(5_000);
    const blob = await promise;

    expect(blob).toBeInstanceOf(Blob);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("does NOT retry a non-retryable 4xx (a real dead link) - fails on the first attempt", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(404));

    await expect(
      fetchFullResolutionImageAsBlob("https://worker.test/dead-link")
    ).rejects.toThrow(/404/);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("gives up after exhausting all retries on a persistently rate-limited endpoint", async () => {
    jest.useFakeTimers();
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(429));

    const promise = fetchFullResolutionImageAsBlob("https://worker.test/full");
    // Swallow the eventual rejection so it doesn't surface as an unhandled rejection while
    // timers are still being advanced below.
    const assertion = expect(promise).rejects.toThrow(/429/);
    await jest.advanceTimersByTimeAsync(30_000);
    await assertion;

    expect(global.fetch).toHaveBeenCalledTimes(
      FULL_RESOLUTION_FETCH_MAX_RETRIES + 1
    );
  });

  it("never exceeds FULL_RESOLUTION_FETCH_CONCURRENCY simultaneous requests under real contention", async () => {
    let active = 0;
    let maxActive = 0;
    jest.spyOn(global, "fetch").mockImplementation(async () => {
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 10));
      active--;
      return okResponse();
    });

    await Promise.all(
      Array.from({ length: FULL_RESOLUTION_FETCH_CONCURRENCY * 3 }, (_, i) =>
        fetchFullResolutionImageAsBlob(`https://worker.test/full-${i}`)
      )
    );

    expect(maxActive).toBeLessThanOrEqual(FULL_RESOLUTION_FETCH_CONCURRENCY);
    expect(maxActive).toBeGreaterThan(1); // confirms it's genuinely concurrent, not serialized
  });
});

const uniformBleed = (mm: number): LayoutEdgeBleed => ({
  top: mm,
  bottom: mm,
  left: mm,
  right: mm,
});

describe("computeBleedCropMM (#301)", () => {
  it("crops the deficit when a card carries more bleed than the layout can afford", () => {
    const carried = uniformBleed(3.175);
    const available: LayoutEdgeBleed = {
      top: 3.175,
      bottom: 3.175,
      left: 1.5,
      right: 1.5,
    };
    const crop = computeBleedCropMM(carried, available);
    expect(crop.top).toBe(0);
    expect(crop.bottom).toBe(0);
    expect(crop.left).toBeCloseTo(1.675, 9);
    expect(crop.right).toBeCloseTo(1.675, 9);
  });

  it("a card whose plan carries no bleed at all (a trimmed source) never computes a negative crop", () => {
    const carried = uniformBleed(0);
    const available = uniformBleed(3.175);
    expect(computeBleedCropMM(carried, available)).toEqual(uniformBleed(0));
  });

  it("a source carrying LESS than what's available crops nothing (never pads via a negative crop)", () => {
    const carried = uniformBleed(1);
    const available = uniformBleed(3.175);
    expect(computeBleedCropMM(carried, available)).toEqual(uniformBleed(0));
  });

  it("is genuinely per-edge: one side crops while the opposite side doesn't", () => {
    const carried = uniformBleed(3.175);
    const available: LayoutEdgeBleed = {
      top: 3.175,
      bottom: 0.5,
      left: 3.175,
      right: 3.175,
    };
    const crop = computeBleedCropMM(carried, available);
    expect(crop.top).toBe(0);
    expect(crop.bottom).toBeCloseTo(2.675, 9);
    expect(crop.left).toBe(0);
    expect(crop.right).toBe(0);
  });
});

describe("computeRenderedBleedMM (#301)", () => {
  it("is min(carried, available) per edge", () => {
    const carried: LayoutEdgeBleed = {
      top: 3.175,
      bottom: 0,
      left: 3.175,
      right: 1,
    };
    const available = uniformBleed(1.5);
    expect(computeRenderedBleedMM(carried, available)).toEqual({
      top: 1.5,
      bottom: 0,
      left: 1.5,
      right: 1,
    });
  });
});

describe("computeBleedCropWindowPx (#301)", () => {
  it("converts the mm crop to a pixel window at the source's own dpi, never non-positive", () => {
    const dpi = 300;
    const targetBleedMM = 3.175;
    const cardWidthPx = Math.round((63 / 25.4) * dpi);
    const cardHeightPx = Math.round((88 / 25.4) * dpi);
    const bleedPx = Math.round((targetBleedMM / 25.4) * dpi);
    const sourceWidthPx = cardWidthPx + 2 * bleedPx;
    const sourceHeightPx = cardHeightPx + 2 * bleedPx;

    const carried = uniformBleed(targetBleedMM);
    const available = uniformBleed(1.5); // less than carried - forces a real crop

    const window = computeBleedCropWindowPx(
      sourceWidthPx,
      sourceHeightPx,
      carried,
      available,
      dpi
    );

    expect(window.croppedWidthPx).toBeGreaterThanOrEqual(cardWidthPx);
    expect(window.croppedHeightPx).toBeGreaterThanOrEqual(cardHeightPx);
    expect(window.croppedWidthPx).toBeLessThan(sourceWidthPx);
    expect(window.croppedHeightPx).toBeLessThan(sourceHeightPx);
    expect(window.cropLeftPx).toBeGreaterThan(0);
    expect(window.cropTopPx).toBeGreaterThan(0);
  });

  it("a fully-available (uncropped) card yields the untouched source window", () => {
    const dpi = 300;
    const carried = uniformBleed(3.175);
    const available = uniformBleed(3.175);
    const window = computeBleedCropWindowPx(
      1000,
      1400,
      carried,
      available,
      dpi
    );
    expect(window.cropLeftPx).toBe(0);
    expect(window.cropTopPx).toBe(0);
    expect(window.croppedWidthPx).toBe(1000);
    expect(window.croppedHeightPx).toBe(1400);
  });
});

describe("createTrackedObjectURL / revokeTrackedObjectURLs - pdf.worker.ts's per-batch release", () => {
  let revokeSpy: jest.SpyInstance;

  beforeEach(() => {
    // The module-level registry is shared across tests in this file; the getPDFImageURL tests
    // above register URLs they never revoke, so drain before asserting on revocations.
    revokeTrackedObjectURLs();
    resetImageBlobCache();
    revokeSpy = jest
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
  });

  it("registers every created URL and revokes them all on demand", () => {
    jest
      .spyOn(URL, "createObjectURL")
      .mockReturnValueOnce("blob:tracked-1")
      .mockReturnValueOnce("blob:tracked-2");
    const first = createTrackedObjectURL(new Blob());
    const second = createTrackedObjectURL(new Blob());
    expect(first).toBe("blob:tracked-1");
    expect(second).toBe("blob:tracked-2");
    revokeTrackedObjectURLs();
    expect(revokeSpy).toHaveBeenCalledWith("blob:tracked-1");
    expect(revokeSpy).toHaveBeenCalledWith("blob:tracked-2");
    expect(revokeSpy).toHaveBeenCalledTimes(2);
  });

  it("drains the registry: a second revoke call is a no-op", () => {
    jest.spyOn(URL, "createObjectURL").mockReturnValueOnce("blob:only");
    createTrackedObjectURL(new Blob());
    revokeTrackedObjectURLs();
    revokeTrackedObjectURLs();
    expect(revokeSpy).toHaveBeenCalledTimes(1);
  });

  it("the URL getPDFImageURL returns is the tracked URL the worker revokes per batch", async () => {
    mockGetBucketImageURL.mockReturnValue("https://bucket.test/card-1-small");
    mockGetWorkerImageURL.mockReturnValue("https://worker.test/card-1-small");
    jest.spyOn(global, "fetch").mockResolvedValue(okResponse());
    jest.spyOn(URL, "createObjectURL").mockReturnValue("blob:getpdfimageurl");

    const url = await getPDFImageURL(
      googleDriveCard(),
      "small-thumbnail",
      undefined,
      100,
      {}
    );
    expect(url).toBe("blob:getpdfimageurl");
    revokeTrackedObjectURLs();
    expect(revokeSpy).toHaveBeenCalledWith("blob:getpdfimageurl");
  });
});
