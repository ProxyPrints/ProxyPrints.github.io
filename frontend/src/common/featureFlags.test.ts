import { isUnifiedDisplayPageEnabled } from "@/common/featureFlags";

describe("isUnifiedDisplayPageEnabled", () => {
  const ORIGINAL_ENV = process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED;

  afterEach(() => {
    process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED = ORIGINAL_ENV;
  });

  it("is false when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED;
    expect(isUnifiedDisplayPageEnabled()).toBe(false);
  });

  it("is false for any value other than the exact string 'true'", () => {
    process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED = "1";
    expect(isUnifiedDisplayPageEnabled()).toBe(false);
    process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED = "True";
    expect(isUnifiedDisplayPageEnabled()).toBe(false);
  });

  it("is true only when set to exactly 'true'", () => {
    process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED = "true";
    expect(isUnifiedDisplayPageEnabled()).toBe(true);
  });
});
