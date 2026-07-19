import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

import { readGeneratedPage, readManifest, renderMarkdown } from "./docsSite";

// Smoke test, not a parity/unit test: runs the REAL
// .github/scripts/publish_site.py against the REAL repo (into a scratch
// temp directory, never frontend/generated-docs/ itself) and confirms the
// artifacts it emits actually exist and actually render - the one Jest
// check this repo keeps on the site-page mechanism now that all
// link-rewrite logic lives in Python (see
// .github/scripts/tests/test_publish_wiki_link_rewrite.py for the real
// fixture coverage of that logic itself).

const repoRoot = path.resolve(__dirname, "..", "..", "..", "..");

describe("publish_site.py emits pages docsSite.ts can read and render", () => {
  let scratchDir: string;

  beforeAll(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "docs-site-smoke-"));
    execFileSync(
      "python3",
      [
        path.join(repoRoot, ".github", "scripts", "publish_site.py"),
        repoRoot,
        scratchDir,
      ],
      { stdio: "pipe" }
    );
  });

  afterAll(() => {
    fs.rmSync(scratchDir, { recursive: true, force: true });
  });

  it("emits a non-empty manifest", () => {
    const manifest = readManifest(scratchDir);
    expect(manifest.length).toBeGreaterThan(0);
  });

  it("emits a readable page for every manifest entry, and it renders to real HTML", () => {
    const manifest = readManifest(scratchDir);
    for (const entry of manifest) {
      const page = readGeneratedPage(entry.slug, scratchDir);
      expect(page).not.toBeNull();
      expect(page?.sourcePath).toBe(entry.sourcePath);
      expect(page?.title.length).toBeGreaterThan(0);

      const html = renderMarkdown(page?.markdown ?? "");
      expect(html).toMatch(/<h1[^>]*>/);
      expect(html.length).toBeGreaterThan(0);
    }
  });

  it("readManifest warns and returns [] rather than crashing when the dir doesn't exist", () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const manifest = readManifest(path.join(scratchDir, "does-not-exist"));
    expect(manifest).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});
