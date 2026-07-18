import { getBucketImageURL, getWorkerImageURL } from "@/common/image";
import { SourceType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

import { getPDFImageBlob, getPDFImageURL } from "./pdfImage";

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
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(503));

    await expect(
      getPDFImageURL(googleDriveCard(), "full-resolution", 300, 100, {})
    ).rejects.toThrow(/503/);
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
    jest.spyOn(global, "fetch").mockResolvedValue(errorResponse(503));

    await expect(
      getPDFImageBlob(googleDriveCard(), 300, 100, {})
    ).rejects.toThrow(/503/);
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
