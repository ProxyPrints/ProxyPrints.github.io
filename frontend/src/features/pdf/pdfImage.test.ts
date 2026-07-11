import { cardDocument1 } from "@/common/test-constants";
import { getPDFImageURL } from "@/features/pdf/pdfImage";

// getImageWorkerURL/getImageBucketURL read these directly from process.env,
// which is how the real app configures them (baked in at build time).
const OLD_ENV = process.env;
beforeEach(() => {
  process.env = {
    ...OLD_ENV,
    NEXT_PUBLIC_IMAGE_WORKER_URL: "https://cdn.example.com",
    NEXT_PUBLIC_IMAGE_BUCKET_URL: "https://bucket.example.com",
  };
});
afterEach(() => {
  process.env = OLD_ENV;
});

test.each(["small-thumbnail", "large-thumbnail", "full-resolution"] as const)(
  "routes %s through the image worker rather than the bucket",
  async (imageQuality) => {
    const url = await getPDFImageURL(
      cardDocument1,
      imageQuality,
      undefined,
      100,
      {}
    );

    expect(url).toEqual(expect.stringContaining("cdn.example.com"));
    expect(url).not.toEqual(expect.stringContaining("bucket.example.com"));
  }
);
