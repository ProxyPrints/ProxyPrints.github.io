#!/usr/bin/env python3
"""
Worker agent model lint — issue #180.

Every `.claude/agents/worker-*.md` file must declare `model: sonnet` in
its YAML frontmatter. That line is what actually pins a spawned worker
to the mid-tier model; nothing else in the harness enforces it, so
dropping the line silently would make a worker inherit the parent
session's (more expensive) model. This lint turns that guarantee into a
hard CI failure instead of a check-and-hope convention.

Parsing approach, deliberately conservative:
  - Only the YAML frontmatter (the span between the first two `---`
    lines) is scanned — a `model: sonnet` mention in prose later in the
    file does not count.
  - Within that span, only a line matching `^model:\\s*(\\S+)\\s*$` (after
    stripping) is treated as the frontmatter key. This means a
    commented-out line (`# model: sonnet`) or a line where `model:` is
    not the key at line-start does not match, and irregular whitespace
    (`model:  sonnet`) does match.
  - The captured value is compared for exact equality against "sonnet",
    not substring-matched, so `model: sonnet-preview` or `model: opus`
    are correctly treated as failures rather than false-passing.

Exit code is the number of findings (0 = clean), matching this repo's
existing check_protected_core_license.py / docs_lint.py convention.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

REQUIRED_MODEL = "sonnet"

MODEL_LINE_RE = re.compile(r"^model:\s*(\S+)\s*$")


def extract_frontmatter(text: str) -> str | None:
    """Returns the text between the first two `---` delimiter lines, or
    None if the file doesn't open with a `---` frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    return None


def frontmatter_model(frontmatter: str) -> str | None:
    """Returns the value of the frontmatter's `model:` key, or None if
    absent. Matches only a line-anchored `model:` key, so a commented-out
    line or an unrelated line mentioning "model:" mid-sentence doesn't
    count."""
    for line in frontmatter.splitlines():
        m = MODEL_LINE_RE.match(line.strip())
        if m:
            return m.group(1)
    return None


def check_file(path: Path) -> list[str]:
    rel = path.relative_to(REPO_ROOT)
    text = path.read_text()

    frontmatter = extract_frontmatter(text)
    if frontmatter is None:
        return [f"::error file={rel}::no YAML frontmatter block found (expected a leading `---` ... `---` span)"]

    model = frontmatter_model(frontmatter)
    if model is None:
        return [f"::error file={rel}::frontmatter has no `model:` key"]

    if model != REQUIRED_MODEL:
        return [f"::error file={rel}::frontmatter declares `model: {model}`, expected `model: {REQUIRED_MODEL}`"]

    return []


def main() -> int:
    worker_files = sorted(AGENTS_DIR.glob("worker-*.md"))

    if not worker_files:
        print(f"::error::no .claude/agents/worker-*.md files found under {AGENTS_DIR}")
        return 1

    all_findings = []
    for path in worker_files:
        all_findings.extend(check_file(path))

    for finding in all_findings:
        print(finding)

    if all_findings:
        print(f"\n{len(all_findings)} worker agent model violation(s) found.")
    else:
        print(f"worker-agent-model: clean ({len(worker_files)} files checked).")

    return len(all_findings)


if __name__ == "__main__":
    raise SystemExit(main())
