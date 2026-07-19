import {
  isChunkLoadError,
  isRecoveryReloadInFlight,
  shouldAttemptReload,
} from "@/common/chunkErrorRecovery";

describe("isChunkLoadError", () => {
  test("recognises Next.js's own ChunkLoadError by name", () => {
    const error = new Error("some message");
    error.name = "ChunkLoadError";
    expect(isChunkLoadError(error)).toBe(true);
  });

  test("recognises webpack's underlying 'Loading chunk N failed' message", () => {
    expect(isChunkLoadError(new Error("Loading chunk 42 failed."))).toBe(true);
  });

  test("recognises a 'Loading CSS chunk' message", () => {
    expect(isChunkLoadError(new Error("Loading CSS chunk 7 failed."))).toBe(
      true
    );
  });

  test("recognises a plain string reason (e.g. from an unhandledrejection event)", () => {
    expect(isChunkLoadError("Loading chunk 3 failed.")).toBe(true);
  });

  test("returns false for an unrelated error", () => {
    expect(isChunkLoadError(new Error("Network request failed"))).toBe(false);
  });

  test("returns false for null/undefined", () => {
    expect(isChunkLoadError(null)).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });
});

describe("shouldAttemptReload", () => {
  test("allows the first attempt (no prior attempt recorded)", () => {
    expect(shouldAttemptReload(null, 1_000_000)).toBe(true);
  });

  test("blocks a second attempt within the guard window", () => {
    expect(shouldAttemptReload(1_000_000, 1_005_000)).toBe(false);
  });

  test("allows another attempt once the guard window has elapsed", () => {
    expect(shouldAttemptReload(1_000_000, 1_015_000)).toBe(true);
  });
});

// Priority bug fix (ProjectEditor.tsx's unsaved-work guard must not intercept this reload as if
// it were a genuine user exit) - see isRecoveryReloadInFlight's own doc comment for the full
// diagnosis. Only the default-value case is covered here, deliberately - the flag flips to true
// inside reloadOnceForChunkError(), immediately before its own window.location.reload() call,
// and this repo's jsdom (jest-fixed-jsdom) makes window.location.reload non-configurable at
// every level (window.location itself, and location.reload directly both throw "Cannot redefine
// property" from Object.defineProperty) - which is exactly why this file's own
// reloadOnceForChunkError has never had a unit test either, only its pure shouldAttemptReload
// helper above. The flag-flip itself is exercised at the integration level instead - see
// UnsavedWorkGuard.spec.ts's diagnosis comment for the full reasoning.
describe("isRecoveryReloadInFlight", () => {
  test("is false by default (before any recovery reload has been triggered)", () => {
    expect(isRecoveryReloadInFlight()).toBe(false);
  });
});
