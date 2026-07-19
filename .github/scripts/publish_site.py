#!/usr/bin/env python3
"""
Emit pre-transformed markdown for the site's "site"-targeted docs/ pages,
per the curated mapping in .github/wiki-publish-map.json - the Python half
of docs/proposals/proposal-i-docs-as-site-source.md's single-transform
architecture.

Usage: publish_site.py <repo_root> <output_dir>

This script owns NO link-rewrite logic of its own - it imports
publish_wiki.py's transform_links() (in site-emit mode: see that module's
own header for what that mode changes) rather than reimplementing
anything. frontend/scripts/generate-docs-site.js does not exist;
frontend/src/pages/guide/[[...slug]].tsx reads this script's JSON output
directly and renders markdown to HTML (a rendering concern, not a
transform concern) via a JS markdown library at Next.js build time.

Writes <output_dir>/<slug>.json per site page:
    {"sourcePath": "docs/overview.md", "sitePath": "/guide",
     "title": "Overview", "markdown": "<link-rewritten markdown>"}
plus <output_dir>/manifest.json, a flat list of
    {"sitePath", "slug", "title", "sourcePath"}
for every emitted page. Idempotent: rerunning with no doc changes
produces byte-identical output (clears <output_dir> of *.json first,
then rewrites exactly what the current mapping calls for).

Fails (non-zero exit, ::error:: annotated) on the same class of problem
publish_wiki.py fails on: a mapped source file that doesn't exist, a
"site" target with no sitePath, or any link that resolves to neither a
site/wiki page nor a real file in the repo.

Data extracts (docs/proposals/proposal-i-docs-as-site-source.md §1(b)/§3,
marked-region JSON) are NOT built here yet - this script only emits
transformed markdown per page. They're a real, deliberately deferred
next step (PR-I-2+), not silently dropped; when built, they'll extend
this same script rather than a separate one, keeping the "one Python
owner" property this restructure exists for.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_wiki import (  # noqa: E402
    build_repo_to_site_map,
    build_repo_to_wiki_map,
    load_mapping,
    transform_links,
)


def derive_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def slug_from_site_path(site_path: str) -> str:
    trimmed = site_path.removeprefix("/guide").strip("/")
    return trimmed.replace("/", "__") if trimmed else "index"


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    mapping = load_mapping(repo_root)
    repo_to_wiki = build_repo_to_wiki_map(mapping)
    repo_to_site = build_repo_to_site_map(mapping)
    errors: list[str] = []
    manifest: list[dict] = []

    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("*.json"):
        existing.unlink()

    for group in mapping["groups"]:
        for page in group["pages"]:
            if "site" not in page.get("targets", []):
                continue
            source_rel = page["source"]
            site_path = page.get("sitePath")
            if not site_path:
                errors.append(f'{source_rel}: targets includes "site" but no sitePath is set')
                continue
            source_path = repo_root / source_rel
            if not source_path.is_file():
                errors.append(f"wiki-publish-map.json references missing source {source_rel}")
                continue

            raw = source_path.read_text()
            title = derive_title(raw, page.get("wiki") or source_rel)
            transformed = transform_links(repo_root, source_rel, raw, repo_to_wiki, errors, repo_to_site=repo_to_site)
            slug = slug_from_site_path(site_path)

            (output_dir / f"{slug}.json").write_text(
                json.dumps(
                    {"sourcePath": source_rel, "sitePath": site_path, "title": title, "markdown": transformed},
                    indent=2,
                )
                + "\n"
            )
            manifest.append({"sitePath": site_path, "slug": slug, "title": title, "sourcePath": source_rel})
            print(f"wrote {slug}.json <- {source_rel} ({site_path})")

    if errors:
        for err in errors:
            print(f"::error::{err}")
        print(
            f"\n{len(errors)} error(s) emitting site docs - failing the build. Fix the source link "
            f"or the wiki-publish-map.json entry rather than shipping a page with a broken link."
        )
        return 1

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote manifest.json ({len(manifest)} page(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
