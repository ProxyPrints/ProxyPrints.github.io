/**
 * Bounded-concurrency map: runs `fn` over every item in `items`, at most `concurrency` calls
 * in flight at once, returning results in the same order as `items` regardless of completion
 * order. A worker-pool-over-an-index-cursor implementation - each of `concurrency` workers
 * repeatedly claims the next unclaimed index until none remain, rather than chunking `items`
 * into fixed-size batches (which would leave workers idle once a batch's slowest call is still
 * running while faster ones in the same batch have already finished).
 *
 * Does not itself catch or retry per-item failures - a rejection from `fn` propagates through
 * Promise.all and fails the whole call, same as a bare Promise.all would. Callers that need "one
 * item's failure shouldn't fail the batch" (e.g. bleedPriorResolution.ts) catch inside their own
 * `fn`, not here - keeps this a general-purpose primitive.
 */
export async function mapWithConcurrencyLimit<T, R>(
  items: readonly T[],
  concurrency: number,
  fn: (item: T, index: number) => Promise<R>
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let nextIndex = 0;

  const worker = async (): Promise<void> => {
    while (nextIndex < items.length) {
      const index = nextIndex++;
      results[index] = await fn(items[index], index);
    }
  };

  const workerCount = Math.max(1, Math.min(concurrency, items.length));
  await Promise.all(Array.from({ length: workerCount }, worker));

  return results;
}
