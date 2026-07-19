#!/usr/bin/env python3
"""
Assemble readme.md (repo root) from marked source regions in docs/, per
the `readme` emit mode described in
docs/proposals/proposal-i-readme-pipeline.md.

Usage: publish_readme.py <repo_root>

Unlike publish_wiki.py/publish_site.py's per-page transform, this mode
assembles ONE output file from a handful of small, hand-authored regions
scattered across docs/ — marked with README-REGION comments. This is a
DIFFERENT marker from DATA-EXTRACT: DATA-EXTRACT's contract
(proposal-i-docs-as-site-source.md §3) is table-only; these regions are
prose, so reusing that name would misdescribe what gets parsed.

Region content is copied verbatim, never link-rewritten: readme.md lives
at the repo root, not in docs/, so a region's own relative-link
resolution — correct if the region were linted in place, in docs/ — would
silently mean something different once copied into the root file. Rather
than teach this script a second, output-relative link-resolution mode,
every region author uses absolute GitHub URLs for any file reference
(see docs/readme-sections.md's own header note) and this script performs
no link rewriting at all.

Generated AND COMMITTED — readme.md is rendered directly by GitHub from
the default branch with no build step in between, so regenerating means
running this script and committing its output, same as editing any other
file by hand. docs-lint.yml's readme-parity job fails the PR if the
committed file has drifted from what a fresh run of this script would
produce.
"""

import sys
from pathlib import Path

REGION_START = "<!-- README-REGION: {name} -->"
REGION_END = "<!-- END README-REGION -->"

GENERATED_MARKER = "<!-- GENERATED FILE"

# (source doc, region name) pairs feeding readme.md. Hand-maintained, same
# discipline as .github/wiki-publish-map.json and publish_wiki.py's
# build_home_and_sidebar — a small, fixed set of sections, not worth a
# JSON map for three entries.
IDENTITY_SOURCE = "docs/wiki-home-intro.md"
SECTIONS_SOURCE = "docs/readme-sections.md"

WEB_CI_BADGE = "![web-ci](https://github.com/ProxyPrints/ProxyPrints.github.io/actions/workflows/web-ci.yml/badge.svg)"
WORKERS_CI_BADGE = (
    "![cloudflare-workers-ci]"
    "(https://github.com/ProxyPrints/ProxyPrints.github.io/actions/workflows/cloudflare-workers-ci.yml/badge.svg)"
)


def generated_header() -> str:
    return (
        f"{GENERATED_MARKER} — do not edit directly.\n"
        f"     Assembled from marked regions in docs/ (see\n"
        f"     docs/proposals/proposal-i-readme-pipeline.md) by\n"
        f"     .github/scripts/publish_readme.py — edit the source region,\n"
        f"     then rerun that script and commit the result.\n"
        f"     GitHub hides this comment when rendering the file. -->\n"
    )


def extract_region(repo_root: Path, source_rel: str, name: str) -> str:
    path = repo_root / source_rel
    if not path.is_file():
        print(f"::error::publish_readme.py: missing source file {source_rel} (region {name!r})")
        raise SystemExit(1)
    text = path.read_text()
    start = REGION_START.format(name=name)
    start_idx = text.find(start)
    if start_idx == -1:
        print(f"::error::publish_readme.py: region {name!r} not found in {source_rel} (expected `{start}`)")
        raise SystemExit(1)
    content_start = start_idx + len(start)
    end_idx = text.find(REGION_END, content_start)
    if end_idx == -1:
        print(f"::error::publish_readme.py: region {name!r} in {source_rel} has no matching `{REGION_END}`")
        raise SystemExit(1)
    return text[content_start:end_idx].strip()


def build_readme(repo_root: Path) -> str:
    identity = extract_region(repo_root, IDENTITY_SOURCE, "identity")
    desktop_tool = extract_region(repo_root, SECTIONS_SOURCE, "desktop-tool-pointer")
    license_notice = extract_region(repo_root, SECTIONS_SOURCE, "license")
    documentation = extract_region(repo_root, SECTIONS_SOURCE, "documentation-pointer")

    parts = [
        generated_header(),
        identity,
        "",
        "---",
        "",
        WEB_CI_BADGE,
        WORKERS_CI_BADGE,
        "",
        desktop_tool,
        "",
        "## License",
        "",
        license_notice,
        "",
        "## Documentation",
        "",
        documentation,
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve()
    output = build_readme(repo_root)
    (repo_root / "readme.md").write_text(output)
    print("wrote readme.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
