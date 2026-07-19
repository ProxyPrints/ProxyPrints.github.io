import fs from "fs";
import { marked } from "marked";
import path from "path";

// Build-time-only reads of .github/scripts/publish_site.py's output (see
// docs/proposals/proposal-i-docs-as-site-source.md's single-transform
// architecture) - used exclusively from
// src/pages/guide/[[...slug]].tsx's getStaticPaths/getStaticProps. This
// lives in its OWN module, not inline in the page file: a page file's
// exports get bundled for the client by Next.js's Pages Router, and `fs`
// has no browser polyfill - keeping these fs-touching functions out of
// the page module (and only ever called from inside
// getStaticPaths/getStaticProps, which Next strips from the client
// bundle) is what keeps the build from trying to resolve `fs` for the
// browser.

export interface ManifestEntry {
  sitePath: string;
  slug: string;
  title: string;
  sourcePath: string;
}

export interface GeneratedPage {
  sourcePath: string;
  sitePath: string;
  title: string;
  markdown: string;
}

const defaultGeneratedDocsDir = path.join(process.cwd(), "generated-docs");

export function readManifest(
  generatedDocsDir: string = defaultGeneratedDocsDir
): ManifestEntry[] {
  const manifestPath = path.join(generatedDocsDir, "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    // Graceful skip, not a crash: `npm run docs:generate` (which shells to
    // .github/scripts/publish_site.py) hasn't run yet - e.g. a fresh
    // `npm run dev` checkout, or a `next build` in an environment that
    // skipped the deploy-frontend.yml emit step. /guide simply has no
    // pages until it has.
    console.warn(
      `[guide] ${manifestPath} not found - run \`npm run docs:generate\` ` +
        `(or the equivalent CI step) first. /guide will have no pages ` +
        `this build.`
    );
    return [];
  }
  return JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
}

export function readGeneratedPage(
  slug: string,
  generatedDocsDir: string = defaultGeneratedDocsDir
): GeneratedPage | null {
  const entryPath = path.join(generatedDocsDir, `${slug}.json`);
  if (!fs.existsSync(entryPath)) return null;
  return JSON.parse(fs.readFileSync(entryPath, "utf-8"));
}

export function renderMarkdown(markdown: string): string {
  return marked.parse(markdown) as string;
}
