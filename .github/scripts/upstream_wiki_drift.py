#!/usr/bin/env python3
"""
Compare chilli-axe/mpc-autofill's wiki against the last-seen state recorded
in docs/upstreaming/upstream-wiki-drift.md, and update that doc's table
in place. DETECTION ONLY — never reads a page's own body content into
this doc, never writes upstream wiki prose anywhere in this repo. Wiki
content has no clear license; the doc this script writes is explicit that
any real adoption is a human decision (link + attributed adaptation).

Usage: upstream_wiki_drift.py <repo_root> <upstream_wiki_clone_dir>
"""
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DOC_REL = "docs/upstreaming/upstream-wiki-drift.md"
UPSTREAM_WIKI_URL = "https://github.com/chilli-axe/mpc-autofill/wiki"
SHA_RE = re.compile(r"<!-- last-seen-sha: ([0-9a-f]+) -->")
ROW_RE = re.compile(r"^\| \[([^\]]+)\]\([^)]+\) \| ([^|]+) \| `([0-9a-f]+)` \|$", re.MULTILINE)
LAST_CHECKED_RE = re.compile(r"^Last checked: .*$", re.MULTILINE)


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def page_name(filename: str) -> str:
    return filename[: -len(".md")]


def latest_commit_info(wiki_dir: Path, filename: str) -> tuple[str, str]:
    """Returns (date, short_sha) of the latest commit touching filename, at current HEAD."""
    out = git(["log", "-1", "--format=%ad|%h", "--date=short", "--", filename], wiki_dir)
    if not out:
        return ("unknown", "unknown")
    d, sha = out.split("|")
    return d, sha


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve()
    wiki_dir = Path(sys.argv[2]).resolve()
    doc_path = repo_root / DOC_REL

    doc_text = doc_path.read_text()
    sha_match = SHA_RE.search(doc_text)
    if not sha_match:
        print(f"::error::{DOC_REL} has no <!-- last-seen-sha: ... --> marker; cannot proceed")
        return 1
    last_seen_sha = sha_match.group(1)

    current_head = git(["rev-parse", "HEAD"], wiki_dir)

    pages = sorted(p.name for p in wiki_dir.glob("*.md"))
    rows: dict[str, tuple[str, str]] = {}
    for m in ROW_RE.finditer(doc_text):
        rows[m.group(1)] = (m.group(2).strip(), m.group(3))

    if current_head == last_seen_sha:
        print("No change upstream since last check.")
        changed_count = 0
    else:
        changed = set(git(["diff", "--name-only", last_seen_sha, current_head], wiki_dir).splitlines())
        changed = {f for f in changed if f.endswith(".md")}
        changed_count = len(changed)
        print(f"{changed_count} page(s) changed upstream since last check: {sorted(changed)}")

    # Always refresh every current page's row to the latest commit touching
    # it (cheap — this is a handful of `git log` calls, not a heavy diff),
    # so the table is a true snapshot of "as of current_head", not just a
    # log of this run's delta.
    for filename in pages:
        d, sha = latest_commit_info(wiki_dir, filename)
        rows[page_name(filename)] = (d, sha)

    # Pages that no longer exist upstream: keep their row (real signal —
    # "removed upstream" is worth knowing), tag it explicitly.
    current_names = {page_name(f) for f in pages}
    for name in list(rows):
        if name not in current_names and "(removed upstream)" not in rows[name][0]:
            d, sha = rows[name]
            rows[name] = (f"{d} (removed upstream)", sha)

    table_lines = ["| Page | Last changed upstream | Commit |", "|---|---|---|"]
    for name in sorted(rows):
        d, sha = rows[name]
        table_lines.append(f"| [{name}]({UPSTREAM_WIKI_URL}/{quote(name)}) | {d} | `{sha}` |")
    new_table = "\n".join(table_lines)

    new_doc = SHA_RE.sub(f"<!-- last-seen-sha: {current_head} -->", doc_text)
    old_table_block = re.search(
        r"\| Page \| Last changed upstream \| Commit \|\n\|---\|---\|---\|\n(?:\|.*\n?)*",
        new_doc,
    )
    if old_table_block:
        new_doc = new_doc[: old_table_block.start()] + new_table + "\n" + new_doc[old_table_block.end() :]
    else:
        new_doc = new_doc.rstrip() + "\n\n" + new_table + "\n"

    today = datetime.now(timezone.utc).date().isoformat()
    if LAST_CHECKED_RE.search(new_doc):
        new_doc = LAST_CHECKED_RE.sub(f"Last checked: {today}", new_doc)
    else:
        new_doc = new_doc.rstrip() + f"\n\nLast checked: {today}\n"

    doc_path.write_text(new_doc)
    print(
        f"Updated {DOC_REL}: last-seen-sha {last_seen_sha[:8]} -> {current_head[:8]}, "
        f"{changed_count} page(s) refreshed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
