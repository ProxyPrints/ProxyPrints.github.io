import { chromium, FullConfig } from "@playwright/test";
import { mkdirSync } from "fs";

const STORAGE_STATE_PATH = "playwright/.auth/cookies.json";

// Routes with a heavy webpack dependency chain that Next dev only compiles on first request
// (on-demand compilation, static export's own build pre-compiles everything so this class of
// cost is dev-only) - warmed up here, serially, before the parallel test-worker pool starts
// hitting them. Observed directly (2026-07-23, Proposal H route swap verification): several
// spec files' first real navigation to `/print` (FinishedMyProject -> PDFGenerator ->
// @react-pdf/renderer) raced across parallel workers/files on a cold dev server and produced
// `net::ERR_ABORTED`/timeout failures that a serial warm-up here reliably avoids - the same class
// of cost DisplayPage.spec.ts's own describe.configure documents for /display's (now /editor's)
// first hit, just with more than one file able to race for it.
const ROUTES_TO_WARM = ["/print"];

/**
 * Historically this opted out of the analytics cookie-consent toast so
 * individual tests didn't have to dismiss it. That toast (and analytics
 * entirely) has since been removed from the app, so this now just produces
 * an empty storage state for tests to reuse.
 */
async function globalSetup(config: FullConfig) {
  mkdirSync("playwright/.auth", { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext();
  await context.storageState({ path: STORAGE_STATE_PATH });

  const baseURL = config.projects[0]?.use?.baseURL ?? "http://localhost:3000";
  const page = await context.newPage();
  for (const route of ROUTES_TO_WARM) {
    try {
      await page.goto(`${baseURL}${route}`, {
        waitUntil: "load",
        timeout: 60_000,
      });
    } catch {
      // Best-effort warm-up only - a failure here just means the first real test to hit this
      // route pays the compile cost itself, exactly like before this warm-up existed.
    }
  }
  await page.close();

  await browser.close();
}

export default globalSetup;
