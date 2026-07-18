import { Semaphore } from "@/common/semaphore";

describe("Semaphore", () => {
  it("allows up to `concurrency` acquisitions without blocking", async () => {
    const semaphore = new Semaphore(3);
    const releases = await Promise.all([
      semaphore.acquire(),
      semaphore.acquire(),
      semaphore.acquire(),
    ]);
    expect(releases).toHaveLength(3);
  });

  it("blocks a caller beyond the concurrency limit until a slot is released", async () => {
    const semaphore = new Semaphore(1);
    const release1 = await semaphore.acquire();

    let acquiredSecond = false;
    const secondAcquire = semaphore.acquire().then((release) => {
      acquiredSecond = true;
      return release;
    });

    // Give the pending acquire a chance to (incorrectly) resolve early.
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(acquiredSecond).toBe(false);

    release1();
    const release2 = await secondAcquire;
    expect(acquiredSecond).toBe(true);
    release2();
  });

  it("never lets more than `concurrency` holders run at once under real contention", async () => {
    const semaphore = new Semaphore(2);
    let active = 0;
    let maxActive = 0;

    const task = async () => {
      const release = await semaphore.acquire();
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active--;
      release();
    };

    await Promise.all(Array.from({ length: 8 }, () => task()));
    expect(maxActive).toBeLessThanOrEqual(2);
  });

  it("processes queued acquisitions in FIFO order", async () => {
    const semaphore = new Semaphore(1);
    const release1 = await semaphore.acquire();
    const order: number[] = [];

    const p2 = semaphore.acquire().then((release) => {
      order.push(2);
      release();
    });
    const p3 = semaphore.acquire().then((release) => {
      order.push(3);
      release();
    });

    release1();
    await Promise.all([p2, p3]);
    expect(order).toEqual([2, 3]);
  });
});
