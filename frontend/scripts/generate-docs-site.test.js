// Parity fixture test: generate-docs-site.js's transformLinks against the
// shared link-rewrite fixture set in
// .github/scripts/testdata/link_rewrite/.
//
// See that directory's cases.json for the shared-contract rationale (what's
// genuinely identical between generate-docs-site.js's wiki/site/blob 3-way
// resolution and publish_wiki.py's wiki-only resolution, and what's
// expected to diverge, e.g. a wiki-only target's link format) and
// .github/scripts/tests/test_publish_wiki_link_rewrite.py for the Python
// counterpart running the SAME cases against the SAME fixture repo. Any
// edge-case fix to either implementation's link parsing/resolution should
// update cases.json, so a future silent divergence between the two becomes
// a failing test here instead.
//
// A plain .js test file (not .test.ts) deliberately: generate-docs-site.js
// itself is plain JS (matching its sibling build scripts,
// generate-keyrune-assets.js/copy-pdf-worker.js), and tsconfig.json's
// allowJs: false means a .ts test importing it would fail type-checking
// during `next build`. jest.config.mjs's testMatch is extended to pick up
// **/*.test.js for exactly this file.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import { buildTargetMaps, transformLinks } from "./generate-docs-site.js";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const fixtureDir = path.resolve(
  dirname,
  "..",
  "..",
  ".github",
  "scripts",
  "testdata",
  "link_rewrite"
);
const fixtureRepoRoot = path.join(fixtureDir, "fixture_repo");

function loadJson(relPath) {
  return JSON.parse(fs.readFileSync(path.join(fixtureDir, relPath), "utf-8"));
}

describe("generate-docs-site.js transformLinks parity fixtures", () => {
  const mapping = loadJson("map.json");
  const maps = buildTargetMaps(mapping);
  const cases = loadJson("cases.json").cases;

  test("fixture set is non-empty", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  test.each(cases.map((c) => [c.name, c]))("%s", (_name, testCase) => {
    const errors = [];
    const actual = transformLinks(
      fixtureRepoRoot,
      testCase.sourcePath,
      testCase.input,
      maps,
      errors
    );
    const expected = testCase.expected ?? testCase.jsExpected;
    expect(expected).toBeDefined();
    expect(actual).toBe(expected);

    if (testCase.expectError) {
      expect(errors.length).toBeGreaterThan(0);
    } else {
      expect(errors).toEqual([]);
    }
  });

  test("a site-only page (no wiki key at all) resolves via repoToSite, not repoToWiki", () => {
    expect(maps.repoToWiki.has("docs/site-only-doc.md")).toBe(false);
    expect(maps.repoToSite.get("docs/site-only-doc.md")).toBe(
      "/guide/site-only"
    );
  });
});
