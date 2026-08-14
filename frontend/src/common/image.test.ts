import { getSheetImageURL } from "@/common/image";
import { cardDocument1 } from "@/common/test-constants";

describe("getSheetImageURL", () => {
  const originalBucketURL = process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL;
  const originalWorkerURL = process.env.NEXT_PUBLIC_IMAGE_WORKER_URL;

  afterEach(() => {
    if (originalBucketURL === undefined) {
      delete process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL;
    } else {
      process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL = originalBucketURL;
    }
    if (originalWorkerURL === undefined) {
      delete process.env.NEXT_PUBLIC_IMAGE_WORKER_URL;
    } else {
      process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = originalWorkerURL;
    }
  });

  it("resolves a Google Drive card's sheet slot image through the CDN bucket, not a raw Drive URL", () => {
    process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL = "https://img.proxyprints.ca";
    process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = "https://cdn.proxyprints.ca";

    const url = getSheetImageURL(cardDocument1);

    expect(url).toBeDefined();
    expect(url).not.toContain("drive.google.com");
    expect(url).toMatch(/^https:\/\/img\.proxyprints\.ca\//);
  });

  it("falls back to the worker URL when the bucket is unset", () => {
    delete process.env.NEXT_PUBLIC_IMAGE_BUCKET_URL;
    process.env.NEXT_PUBLIC_IMAGE_WORKER_URL = "https://cdn.proxyprints.ca";

    const url = getSheetImageURL(cardDocument1);

    expect(url).toBeDefined();
    expect(url).not.toContain("drive.google.com");
    expect(url).toMatch(/^https:\/\/cdn\.proxyprints\.ca\//);
  });
});
