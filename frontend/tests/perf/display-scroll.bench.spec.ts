/**
 * Manual scroll/virtualization benchmark for /display (Proposal H, item 3 - flat-scroll
 * amendment, docs/proposals/proposal-h-unified-display-page.md). NOT part of CI - see
 * playwright.perf.config.ts's own comment for why, and how to actually run this:
 *
 *   npx playwright test --config=playwright.perf.config.ts
 *
 * Imports a large deck, throttles the CPU to approximate a mid-range device, then scrolls
 * through the whole sheet stack in steps (so RenderIfVisible has to mount/unmount sheets
 * repeatedly, not just once) while sampling frame time, peak JS heap, the max number of
 * simultaneously-mounted <img> tags, and any long tasks (>50ms). This is what item 3's
 * benchmark-gated virtualization decision was measured with (see PR #115's own description and
 * docs/reports/2026-07-19-proposal-h-item3-flat-scroll-and-select-version-spec.md for the
 * results that decided sheet-level virtualization was sufficient, no row-granular fallback
 * needed) - committed here so a future PR touching this surface (the owner's own flagged
 * concern: the upcoming pane migration restructures this exact region) can re-run the same
 * measurement and compare numbers instead of eyeballing whether scrolling "feels" slower.
 *
 * Caveat carried over from the original measurement: this runs against the flag-on Next DEV
 * server (same webServer this whole test suite already uses), not a literal production build -
 * dev mode's unminified bundle + React dev overhead means these numbers are a conservative
 * (pessimistic) reading, not an optimistic one. A real production build would only improve on
 * them.
 */
import { expect } from "@playwright/test";

import {
  cardDocumentsThreeResults,
  defaultHandlers,
  searchResultsThreeResults,
  sourceDocumentsOneResult,
} from "@/mocks/handlers";

import { test } from "../../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "../test-utils";

const threeCardHandlers = [
  cardDocumentsThreeResults,
  sourceDocumentsOneResult,
  searchResultsThreeResults,
  ...defaultHandlers,
];

// Owner's original gate (owner's hands-on review, flat-scroll amendment): ~60fps, no long
// tasks, bounded image-mount count regardless of deck size. Informational here, not asserted as
// a hard pass/fail threshold - this file reports numbers for a human to compare run-over-run,
// it doesn't gate CI.
const TARGET_FPS = 60;
const CPU_THROTTLE_RATE = 4; // Emulation.setCPUThrottlingRate - approximates a mid-range device.
const CARD_COUNT = Number(process.env.DISPLAY_BENCH_CARD_COUNT ?? 120);

test.describe.configure({ timeout: 180_000 });

test(`Item 3 benchmark: ${CARD_COUNT}-card deck scroll fps/heap/jank under ${CPU_THROTTLE_RATE}x CPU throttle`, async ({
  page,
  network,
}) => {
  network.use(...threeCardHandlers);
  await loadPageWithDefaultBackend(page);
  await importText(page, `${CARD_COUNT}x my search query`);
  await page.getByRole("link", { name: "Display (beta)" }).click();
  await expect(page.getByTestId("display-page")).toBeVisible();

  const sheetWrappers = page.getByTestId("display-sheet-wrapper");
  const sheetCount = await sheetWrappers.count();
  console.log(`BENCH: sheetCount=${sheetCount}`);

  const client = await page.context().newCDPSession(page);
  await client.send("Emulation.setCPUThrottlingRate", { rate: CPU_THROTTLE_RATE });

  // Peak JS heap + max simultaneously-mounted <img> tags (the actual anti-crash metric - real
  // decoded image memory, not just DOM node count) sampled throughout the scroll.
  await page.evaluate(() => {
    (window as any).__bench = { maxHeap: 0, maxImgs: 0, frameTimes: [] as number[] };
    let last = performance.now();
    const sample = () => {
      const now = performance.now();
      (window as any).__bench.frameTimes.push(now - last);
      last = now;
      const heap = (performance as any).memory?.usedJSHeapSize ?? 0;
      (window as any).__bench.maxHeap = Math.max((window as any).__bench.maxHeap, heap);
      const imgs = document.querySelectorAll(
        '[data-testid="display-sheet-region"] img'
      ).length;
      (window as any).__bench.maxImgs = Math.max((window as any).__bench.maxImgs, imgs);
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });

  await page.evaluate(() => {
    (window as any).__longTasks = [];
    const obs = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        (window as any).__longTasks.push({
          start: entry.startTime,
          duration: entry.duration,
        });
      }
    });
    obs.observe({ entryTypes: ["longtask"] });
  });

  const lastWrapper = sheetWrappers.last();
  const scrollStart = Date.now();
  // Step-scroll through the whole deck in increments (rather than one jump) so virtualization
  // has to mount/unmount sheets repeatedly, which is the actual stress case for jank at sheet
  // boundaries - a single scrollIntoView jump wouldn't exercise that at all.
  const stepCount = Math.max(sheetCount * 3, 10);
  for (let i = 0; i <= stepCount; i++) {
    await page.evaluate(
      ({ i, stepCount }) => {
        let node: HTMLElement | null = document.querySelector(
          '[data-testid="display-sheet-region"]'
        );
        let scroller: HTMLElement = document.documentElement;
        while (node != null) {
          const overflowY = getComputedStyle(node).overflowY;
          if (overflowY === "scroll" || overflowY === "auto") {
            scroller = node;
            break;
          }
          node = node.parentElement;
        }
        const max = scroller.scrollHeight - scroller.clientHeight;
        scroller.scrollTop = Math.round((max * i) / stepCount);
      },
      { i, stepCount }
    );
    await page.waitForTimeout(80);
  }
  await lastWrapper.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  const scrollDurationMs = Date.now() - scrollStart;

  const bench = await page.evaluate(() => (window as any).__bench);
  const longTasksResult = await page.evaluate(() => (window as any).__longTasks);

  const frameTimes: number[] = bench.frameTimes.slice(5); // drop warm-up frames
  const avgFrameMs =
    frameTimes.reduce((a: number, b: number) => a + b, 0) / frameTimes.length;
  const fps = 1000 / avgFrameMs;
  const p95FrameMs = [...frameTimes].sort((a, b) => a - b)[
    Math.floor(frameTimes.length * 0.95)
  ];

  console.log(
    `BENCH RESULTS (${CPU_THROTTLE_RATE}x CPU throttle, ${sheetCount} sheets, ${scrollDurationMs}ms scroll):`
  );
  console.log(`  avg fps: ${fps.toFixed(1)} (target: ~${TARGET_FPS})`);
  console.log(`  p95 frame time: ${p95FrameMs.toFixed(1)}ms`);
  console.log(`  peak JS heap: ${(bench.maxHeap / 1024 / 1024).toFixed(1)} MB`);
  console.log(
    `  max simultaneously-mounted <img> tags: ${bench.maxImgs} (of ${CARD_COUNT} total cards)`
  );
  console.log(`  long tasks (>50ms) during scroll: ${longTasksResult.length}`);
  if (longTasksResult.length > 0) {
    const durations = longTasksResult.map((t: any) => t.duration);
    console.log(`  longest task: ${Math.max(...durations).toFixed(1)}ms`);
  }
});
