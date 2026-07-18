import { mapWithConcurrencyLimit } from "@/common/concurrencyLimit";

describe("mapWithConcurrencyLimit", () => {
  it("returns results in item order regardless of completion order", async () => {
    const delays = [30, 10, 20, 0];
    const results = await mapWithConcurrencyLimit(
      delays,
      4,
      (delayMs, index) =>
        new Promise<number>((resolve) =>
          setTimeout(() => resolve(index), delayMs)
        )
    );
    expect(results).toEqual([0, 1, 2, 3]);
  });

  it("never exceeds the concurrency limit at any point in time", async () => {
    let active = 0;
    let maxActive = 0;
    const items = Array.from({ length: 10 }, (_, i) => i);
    await mapWithConcurrencyLimit(items, 3, async () => {
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active--;
    });
    expect(maxActive).toBeLessThanOrEqual(3);
    expect(maxActive).toBeGreaterThan(1); // confirms it's genuinely concurrent, not serialized
  });

  it("processes every item exactly once", async () => {
    const items = Array.from({ length: 25 }, (_, i) => i);
    const seen: number[] = [];
    await mapWithConcurrencyLimit(items, 4, async (item) => {
      seen.push(item);
    });
    expect(seen.slice().sort((a, b) => a - b)).toEqual(items);
  });

  it("handles an empty input without hanging", async () => {
    const results = await mapWithConcurrencyLimit(
      [],
      4,
      async () => "unreachable"
    );
    expect(results).toEqual([]);
  });

  it("handles a concurrency limit larger than the item count", async () => {
    const results = await mapWithConcurrencyLimit(
      [1, 2],
      10,
      async (item) => item * 2
    );
    expect(results).toEqual([2, 4]);
  });

  it("propagates a rejection from fn (no built-in per-item error tolerance)", async () => {
    await expect(
      mapWithConcurrencyLimit([1, 2, 3], 2, async (item) => {
        if (item === 2) throw new Error("boom");
        return item;
      })
    ).rejects.toThrow("boom");
  });
});
