import { chromium } from "@playwright/test";
import { mkdirSync } from "fs";

const STORAGE_STATE_PATH = "playwright/.auth/cookies.json";

// The route warm-up this file used to run (ROUTES_TO_WARM = ["/print"], serial pre-warming of
// Next dev's on-demand compilation) was retired with the /print page itself - /print was its
// only entry, and DisplayPage.spec.ts's own describe.configure already documents the first-hit
// compile cost for /editor's now-sole heavy route.

/**
 * Historically this opted out of the analytics cookie-consent toast so
 * individual tests didn't have to dismiss it. That toast (and analytics
 * entirely) has since been removed from the app, so this now just produces
 * an empty storage state for tests to reuse.
 */
async function globalSetup() {
  mkdirSync("playwright/.auth", { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext();
  await context.storageState({ path: STORAGE_STATE_PATH });
  await browser.close();
}

export default globalSetup;
