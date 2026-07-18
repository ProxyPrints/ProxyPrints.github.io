/**
 * A plain counting semaphore - acquire a slot, do work, release it. Unlike
 * `concurrencyLimit.ts`'s `mapWithConcurrencyLimit` (which bounds concurrency over a KNOWN,
 * finite list of items processed in one call), this is for gating an unbounded stream of ad-hoc
 * concurrent calls arriving over time from a caller this codebase doesn't control - e.g.
 * @react-pdf/renderer's own internal scheduler invoking many `<Image src={async () => ...}>`
 * callbacks concurrently across a document, with no hook to pass it a bounded-map function
 * instead. Every caller that needs "no more than N of this specific operation in flight at once,
 * regardless of who's calling it or how many" acquires from the same shared instance.
 */
export class Semaphore {
  private available: number;
  private readonly queue: Array<() => void> = [];

  constructor(concurrency: number) {
    this.available = concurrency;
  }

  /** Resolves once a slot is free, with a release function the caller MUST call exactly once
   * (typically in a `finally` block) to hand the slot back. */
  acquire(): Promise<() => void> {
    if (this.available > 0) {
      this.available--;
      return Promise.resolve(() => this.release());
    }
    return new Promise((resolve) => {
      this.queue.push(() => {
        this.available--;
        resolve(() => this.release());
      });
    });
  }

  private release(): void {
    this.available++;
    const next = this.queue.shift();
    if (next != null) {
      next();
    }
  }
}
