import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchWithRateLimit } from "../src/utils";

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchWithRateLimit", () => {
  it("fetches immediately when the limiter allows the first attempt", async () => {
    const limit = vi.fn(async () => ({ success: true }));
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await fetchWithRateLimit({ limit } as unknown as RateLimit, "test-key", "https://example.com/image.jpg");

    expect(await response.text()).toBe("ok");
    expect(limit).toHaveBeenCalledTimes(1);
    expect(limit).toHaveBeenCalledWith({ key: "test-key" });
    expect(fetchMock).toHaveBeenCalledWith("https://example.com/image.jpg");
  });

  it("backs off and retries when the limiter denies an attempt", async () => {
    const limit = vi.fn().mockResolvedValueOnce({ success: false }).mockResolvedValueOnce({ success: true });
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(global, "setTimeout").mockImplementation(((cb: () => void) => {
      cb();
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout);

    const response = await fetchWithRateLimit({ limit } as unknown as RateLimit, "test-key", "https://example.com/image.jpg");

    expect(await response.text()).toBe("ok");
    expect(limit).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries an upstream 429 before returning a successful response", async () => {
    const limit = vi.fn(async () => ({ success: true }));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("too many", { status: 429 }))
      .mockResolvedValueOnce(new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(global, "setTimeout").mockImplementation(((cb: () => void) => {
      cb();
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout);

    const response = await fetchWithRateLimit({ limit } as unknown as RateLimit, "test-key", "https://example.com/image.jpg");

    expect(await response.text()).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws after every attempt is rate limited", async () => {
    const limit = vi.fn(async () => ({ success: false }));
    vi.spyOn(global, "setTimeout").mockImplementation(((cb: () => void) => {
      cb();
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout);

    await expect(fetchWithRateLimit({ limit } as unknown as RateLimit, "test-key", "https://example.com/image.jpg")).rejects.toThrow(
      'Rate limit exceeded for key "test-key" after 5 retries'
    );
    expect(limit).toHaveBeenCalledTimes(6);
  });
});
