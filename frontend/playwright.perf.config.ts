import { defineConfig } from "@playwright/test";

import baseConfig from "./playwright.config";

/**
 * Config for the manual scroll/virtualization benchmark under tests/perf/ (Proposal H, item 3 -
 * docs/proposals/proposal-h-unified-display-page.md's flat-scroll amendment). NOT part of CI -
 * the main playwright.config.ts explicitly testIgnores tests/perf/, so a plain
 * `npx playwright test` (locally or in CI's sharded run) never touches this. Run it with:
 *
 *   npx playwright test --config=playwright.perf.config.ts
 *
 * Reuses the base config's webServer/use/projects wholesale (same flag-on dev server, same
 * browser/viewport) - only testDir differs, so there's exactly one place browser/server settings
 * are defined, not two configs drifting apart over time.
 */
export default defineConfig({
  ...baseConfig,
  testDir: "./tests/perf",
  testIgnore: undefined,
});
