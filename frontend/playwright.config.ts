import { defineConfig, devices } from "@playwright/test";
import { execFileSync } from "child_process";

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */
// import dotenv from 'dotenv';
// import path from 'path';
// dotenv.config({ path: path.resolve(__dirname, '.env') });

/**
 * The port this run's `next dev` server binds, and the port every `baseURL` in it points at.
 *
 * This used to be a hardcoded 3000 in both `use.baseURL` and `webServer.url`, which made two
 * concurrent E2E runs on one machine collide - the same bug class #571 fixed for the Python
 * test harness's Docker containers. Locally (`reuseExistingServer: !process.env.CI`) the second
 * run silently attached to the FIRST run's dev server, so it tested the first worktree's code
 * and then died mid-run when that server was torn down; the failures pointed at whatever change
 * happened to be under test rather than at the port.
 *
 * Resolution order:
 *   1. `PLAYWRIGHT_PORT`, if set. Set it to 3000 to get the old behaviour back - i.e. to reuse a
 *      `npm run dev` you already have running, skipping the dev-server boot. Pin it to distinct
 *      values if you want deterministic ports for two runs you are deliberately overlapping.
 *   2. Otherwise a free port from the kernel (bind :: port 0, read the assignment back, release),
 *      exported into the environment so Playwright's worker processes - which re-load this file
 *      in their own process - inherit the SAME port instead of each drawing a new one.
 *
 * Honest limit, deliberately not papered over: the kernel's assignment is released before
 * `next dev` binds it, so a foreign process can take the port inside that window (~seconds,
 * since it spans `npm run dev` + Next's boot). Playwright's `webServer.url` has no port-0
 * read-back equivalent, so unlike #571 there is nothing holding the binding across that gap.
 * What the window CANNOT produce is a wrong-but-passing run: `next dev` is now given an explicit
 * `--port`, and Next only auto-increments away from a busy port when it picked the port itself.
 * Given one explicitly it fails hard with `EADDRINUSE`, so losing the race aborts the run
 * loudly at webServer startup rather than quietly serving somebody else's app. See
 * `docs/troubleshooting.md`'s "Two concurrent frontend E2E runs" entry.
 */
function resolvePort(): string {
  const pinned = process.env.PLAYWRIGHT_PORT;
  if (pinned) {
    return pinned;
  }
  // Playwright configs are loaded synchronously, and `net`'s bind is not - so the probe runs in a
  // throwaway `node -e` child, whose exit is the synchronisation point. Bound without a host, to
  // match the dual-stack `::` bind `next dev` itself does (a port free only on 127.0.0.1 is not
  // good enough). While two concurrent probes are open the kernel cannot hand both the same port.
  const port = execFileSync(
    process.execPath,
    [
      "-e",
      "const s = require('net').createServer(); s.listen(0, () => { process.stdout.write(String(s.address().port)); s.close(); });",
    ],
    { encoding: "utf8" }
  ).trim();
  process.env.PLAYWRIGHT_PORT = port;
  return port;
}

const PORT = resolvePort();
const BASE_URL = `http://localhost:${PORT}`;

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: "./tests",
  // frontend/tests/perf/ holds a manually-run scroll/virtualization benchmark
  // (playwright.perf.config.ts), not a CI-gated correctness test - excluded here so neither a
  // plain `npx playwright test` nor CI's sharded run ever picks it up; run it explicitly via
  // `npx playwright test --config=playwright.perf.config.ts` instead.
  testIgnore: "**/tests/perf/**",
  globalSetup: "./tests/global-setup",
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Always run tests in parallel. Default is to not parallelise in CI, this seems nuts to me. */
  workers: undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: process.env.CI ? "blob" : "html",
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('')`. */
    baseURL: BASE_URL,

    /* Reuse the opted-out cookie consent state so tests don't have to dismiss the toast. */
    storageState: "playwright/.auth/cookies.json",

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        contextOptions: {
          reducedMotion: "reduce",
          viewport: { height: 600, width: 800 },
        },
      },
    },

    /* Test against mobile viewports. */
    // {
    //   name: 'Mobile Chrome',
    //   use: { ...devices['Pixel 5'] },
    // },
    // {
    //   name: 'Mobile Safari',
    //   use: { ...devices['iPhone 12'] },
    // },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: {
    // Explicit `--port`, not the `next dev` default: Next only walks to the next free port when
    // it chose the port itself, so passing it explicitly turns a lost port race into an
    // immediate `EADDRINUSE` exit instead of a server quietly listening somewhere this run's
    // `baseURL` does not point (see `resolvePort` above).
    command: `npm run dev -- --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_PUBLIC_IMAGE_WORKER_URL: "https://cdn.proxyprints.ca",
      NEXT_PUBLIC_IMAGE_BUCKET_URL: "https://img.proxyprints.ca",
      // Proposal H (docs/proposals/proposal-h-unified-display-page.md) - /display stays behind
      // this flag in real deployments; enabling it for the whole test run is the established
      // pattern this config already uses for other NEXT_PUBLIC_* flags above.
      NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED: "true",
    },
  },
});
