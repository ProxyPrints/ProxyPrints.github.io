import { chromium, FullConfig } from "@playwright/test";
import { mkdirSync } from "fs";

const STORAGE_STATE_PATH = "playwright/.auth/cookies.json";

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
  await browser.close();
}

export default globalSetup;
