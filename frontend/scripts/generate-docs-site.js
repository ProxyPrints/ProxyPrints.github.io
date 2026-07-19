// Build-time site page generation from docs/, per the extended
// .github/wiki-publish-map.json (entries whose "targets" includes "site")
// — see docs/proposals/proposal-i-docs-as-site-source.md §1(a).
//
// Mirrors .github/scripts/publish_wiki.py's own link-rewrite philosophy (a
// link inside a rendered doc must resolve to something real — another site
// page's route, a wiki page's external URL, or a GitHub blob URL — never a
// raw docs/ filename) but reimplemented here in JS rather than shared
// across languages: this runs inside the Next.js/Node build while
// publish_wiki.py runs as a separate Python step over the wiki's own git
// clone. Same language-duplication tradeoff docs/lessons.md already
// documents for the frontend's own hand-maintained copy of backend
// sanitisation logic — not a new pattern this script introduces.
//
// The link-rewrite CONTRACT the two implementations share (which link
// forms get touched vs. skipped, how a relative path resolves, when a
// broken link is an error) is pinned by a shared fixture set — see
// .github/scripts/testdata/link_rewrite/, exercised here by
// generate-docs-site.test.js and on the Python side by
// .github/scripts/tests/test_publish_wiki_link_rewrite.py. Any edge-case
// fix to either implementation's parsing/resolution logic should update
// that fixture set, so a silent divergence between the two becomes a red
// build instead.
//
// Runs as an npm "prebuild" step (see package.json) — NOT postinstall,
// since docs/ changes have nothing to do with npm install. Fails the whole
// build (non-zero exit) on any unresolvable link, a missing mapped source
// file, or a "site" target with no sitePath — same fail-fast philosophy as
// publish_wiki.py's own link-resolution errors: never ship a page with a
// broken link silently.
//
// Output: frontend/src/common/generated/docsSite/<slug>.json per site
// page, plus a manifest.json listing every generated page — gitignored,
// regenerated every build, never hand-edited (same convention as
// generate-keyrune-assets.js's keyruneCodepoints.json).

import fs from "fs";
import { marked } from "marked";
import path from "path";
import { fileURLToPath } from "url";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const defaultRepoRoot = path.resolve(dirname, "..", "..");
export const GITHUB_WIKI_BASE =
  "https://github.com/ProxyPrints/ProxyPrints.github.io/wiki/";
export const GITHUB_BLOB_BASE =
  "https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/";
const outDir = path.join(
  dirname,
  "..",
  "src",
  "common",
  "generated",
  "docsSite"
);

// Fence/inline must be tried before the link alternatives so code content
// is never rewritten (mirrors publish_wiki.py's LINK_TOKEN_RE exactly).
// Capture groups, in order: (1) fenced block, (2) inline code, (3) wikilink
// body, (4) markdown link text, (5) markdown link path.
export const LINK_TOKEN_RE =
  /(```[\s\S]*?```)|(`[^`\n]+`)|\[\[([^\]]+)\]\]|(?<!!)\[([^\]]*)\]\(([^)]+)\)/g;

export function loadMapping(mappingPath) {
  return JSON.parse(fs.readFileSync(mappingPath, "utf-8"));
}

export function buildTargetMaps(mapping) {
  const repoToSite = new Map();
  const repoToWiki = new Map();
  for (const group of mapping.groups) {
    for (const page of group.pages) {
      if (page.wiki) repoToWiki.set(page.source, page.wiki);
      if ((page.targets ?? []).includes("site") && page.sitePath) {
        repoToSite.set(page.source, page.sitePath);
      }
    }
  }
  return { repoToSite, repoToWiki };
}

// Mirrors publish_wiki.py's resolve_repo_relative: resolves a link target
// against the source doc's own directory, returns a repo-relative posix
// path, or null if it isn't a local-file reference at all.
export function resolveRepoRelative(repoRoot, sourceRel, target) {
  if (/^(https?:|mailto:)/.test(target) || target.startsWith("#")) return null;
  const pathPart = target.split("#")[0];
  if (!pathPart) return null;
  const sourceDir = path.dirname(path.join(repoRoot, sourceRel));
  const resolved = path.resolve(sourceDir, pathPart);
  const rel = path.relative(repoRoot, resolved);
  if (rel.startsWith("..")) return null; // escaped repo root - not our problem
  return rel.split(path.sep).join("/");
}

export function rewriteLink(
  repoRoot,
  sourceRel,
  target,
  displayText,
  maps,
  errors
) {
  const resolvedRel = resolveRepoRelative(repoRoot, sourceRel, target);
  if (resolvedRel === null) return null; // not a local path - leave untouched

  if (maps.repoToSite.has(resolvedRel)) {
    const sitePath = maps.repoToSite.get(resolvedRel);
    return `[${displayText || sitePath}](${sitePath})`;
  }
  if (maps.repoToWiki.has(resolvedRel)) {
    const wikiName = maps.repoToWiki.get(resolvedRel);
    return `[${displayText || wikiName}](${GITHUB_WIKI_BASE}${wikiName})`;
  }
  if (fs.existsSync(path.join(repoRoot, resolvedRel))) {
    const text = displayText || resolvedRel.split("/").pop();
    return `[${text}](${GITHUB_BLOB_BASE}${resolvedRel})`;
  }
  errors.push(
    `in ${sourceRel}: link to \`${target}\` resolves to \`${resolvedRel}\`, which is neither ` +
      `a mapped page (site or wiki) nor a real file in the repo`
  );
  return null;
}

export function transformLinks(repoRoot, sourceRel, text, maps, errors) {
  return text.replace(
    LINK_TOKEN_RE,
    (whole, fence, inline, wikilink, mdtext, mdpath) => {
      if (fence !== undefined || inline !== undefined) return whole;
      if (wikilink !== undefined) {
        if (!wikilink.endsWith(".md") && !wikilink.includes("/")) return whole; // e.g. [[routes]] - a literal, not a doc link
        return (
          rewriteLink(repoRoot, sourceRel, wikilink, null, maps, errors) ??
          whole
        );
      }
      return (
        rewriteLink(
          repoRoot,
          sourceRel,
          mdpath,
          mdtext || null,
          maps,
          errors
        ) ?? whole
      );
    }
  );
}

export function deriveTitle(markdown, fallback) {
  const match = markdown.match(/^#\s+(.+)$/m);
  return match ? match[1].trim() : fallback;
}

export function slugFromSitePath(sitePath) {
  const trimmed = sitePath.replace(/^\/guide\/?/, "");
  return trimmed.length === 0 ? "index" : trimmed.replace(/\//g, "__");
}

function main() {
  const repoRoot = defaultRepoRoot;
  const mapping = loadMapping(
    path.join(repoRoot, ".github", "wiki-publish-map.json")
  );
  const maps = buildTargetMaps(mapping);
  const errors = [];
  const manifest = [];

  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  for (const group of mapping.groups) {
    for (const page of group.pages) {
      if (!(page.targets ?? []).includes("site")) continue;
      if (!page.sitePath) {
        errors.push(
          `${page.source}: targets includes "site" but no sitePath is set`
        );
        continue;
      }
      const sourceAbs = path.join(repoRoot, page.source);
      if (!fs.existsSync(sourceAbs)) {
        errors.push(
          `wiki-publish-map.json references missing source ${page.source}`
        );
        continue;
      }
      const raw = fs.readFileSync(sourceAbs, "utf-8");
      const title = deriveTitle(raw, page.wiki ?? page.source);
      const transformed = transformLinks(
        repoRoot,
        page.source,
        raw,
        maps,
        errors
      );
      const html = marked.parse(transformed);
      const slug = slugFromSitePath(page.sitePath);
      fs.writeFileSync(
        path.join(outDir, `${slug}.json`),
        JSON.stringify(
          { sourcePath: page.source, sitePath: page.sitePath, title, html },
          null,
          2
        )
      );
      manifest.push({
        sitePath: page.sitePath,
        slug,
        title,
        sourcePath: page.source,
      });
      console.log(
        `wrote docsSite/${slug}.json <- ${page.source} (${page.sitePath})`
      );
    }
  }

  if (errors.length > 0) {
    for (const err of errors) console.error(`::error::${err}`);
    console.error(
      `\n${errors.length} error(s) generating site docs - failing the build. Fix the ` +
        `source link or the map entry rather than shipping a page with a broken link.`
    );
    process.exit(1);
  }

  fs.writeFileSync(
    path.join(outDir, "manifest.json"),
    JSON.stringify(manifest, null, 2)
  );
  console.log(`wrote docsSite/manifest.json (${manifest.length} page(s))`);
}

// Only run when executed directly (`node generate-docs-site.js`), not when
// imported for testing (generate-docs-site.test.js imports the exported
// functions above without wanting main()'s filesystem side effects).
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main();
}
