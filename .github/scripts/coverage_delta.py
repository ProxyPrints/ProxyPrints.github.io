#!/usr/bin/env python3
"""
Playwright coverage-delta gate.

Issue #415, incident #389: the /editor route swap (PR #389, 2026-07-23)
skipped ~190 Playwright tests in one commit and CI stayed green, because
nothing checks *test inventory* across a diff - only whether the tests
that still run still pass. This script is a static parser (no browser,
no `npm ci`, no Playwright runtime) over frontend/tests/**/*.spec.ts that:

  1. inventories every test() title (full describe-chain-qualified) and
     its skip state (test.skip, test.describe.skip, or a `testInfo.skip(...)`
     call reachable from a beforeEach/the test body itself),
  2. does the same parse against the base ref's merge-base file contents
     via `git show` (no checkout juggling - see build_manifest_from_ref),
  3. fails when a title present at base is absent at head, or was active
     at base and is skipped at head - UNLESS the PR's diff carries an ack
     token: a "coverage-ack: <test id or glob> - <reason>" line appended to
     .github/coverage-acks.txt (same tether discipline as docs_lint.py's
     ALLOWLIST: mechanical check, human-written escape hatch, one line per
     exception, reason required).

New tests and un-skipping are always fine and never flagged.

KNOWN LIMITATIONS (docs_lint.py convention: state them plainly rather than
let them get discovered as a false-positive surprise later):
  - This is a static-source parser, not a JS/TS AST. It masks string/
    template-literal/comment contents (same length, so line numbers stay
    correct - see mask_source()) and then does bracket-matching over what's
    left. Regex literals (`/foo/`) are NOT masked; if one is ever
    introduced containing an unbalanced `(`/`)`/`{`/`}` inside the pattern
    itself, the scanner's bracket matching for that scope would get
    confused. None exist in frontend/tests/ today (checked at write time);
    if this ever misparses a file for that reason, mask regex literals too
    rather than special-casing the one file.
  - `testInfo.skip(<expr>, "reason")` is treated as an unconditional skip
    of its enclosing scope regardless of what <expr> is (this repo's own
    convention is always `testInfo.skip(true, "...")` in a top-level
    beforeEach - see the #389 file-level skip pattern). A parser can't
    evaluate an arbitrary runtime condition anyway; erring toward "treat
    it as skipped" is the safe direction for a gate whose whole purpose is
    catching skips, not toward silently trusting a condition might be false.
  - Dynamic test titles built from a template literal
    (`` test(`...${x}...`, ...) ``) are identified by their literal SOURCE
    text (placeholders kept as `${x}`, not evaluated) - stable across a
    diff, which is what the gate needs, but not the same string Playwright
    itself reports at runtime for each loop iteration.

Run standalone: python3 .github/scripts/coverage_delta.py --base <ref-or-sha>
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR_REL = "frontend/tests"
ACKS_FILE_REL = ".github/coverage-acks.txt"

# frontend/tests/perf/ is excluded from CI-gated correctness runs by
# playwright.config.ts's own testIgnore ("**/tests/perf/**") - mirror that
# exclusion here so a perf benchmark's title changes never trip this gate.
EXCLUDED_DIR_PARTS = ("perf",)


# ---------------------------------------------------------------------------
# Source masking (docs_lint.py's `_blank` trick: same length, same newline
# positions, so every later offset/line-number stays valid against the
# ORIGINAL text even though string/comment contents are blanked out here).
# ---------------------------------------------------------------------------


def _blank_range(chars: list, start: int, end: int) -> None:
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = " "


def mask_source(text: str) -> str:
    """
    Returns a same-length copy of `text` with line-comment, block-comment,
    string-literal, and template-literal CONTENTS blanked out (quotes/
    delimiters included) so that bracket-matching over the result never
    trips on a `{`/`}`/`(`/`)` that only appears inside a string or a
    comment. Positions in the result line up 1:1 with the original.
    """
    chars = list(text)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            _blank_range(chars, i, j)
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            end = n if j == -1 else j + 2
            _blank_range(chars, i, end)
            i = end
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    j += 1
                    break
                j += 1
            _blank_range(chars, i, min(j, n))
            i = j
            continue
        if c == "`":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "`":
                    j += 1
                    break
                j += 1
            _blank_range(chars, i, min(j, n))
            i = j
            continue
        i += 1
    return "".join(chars)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def find_matching(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    """Index of the bracket matching text[open_idx] (which must be open_ch),
    scanning on `text` (expected to be mask_source()'d already so brackets
    inside strings/comments can't throw the count off). Falls back to
    len(text) - 1 if unbalanced (malformed/edge-case source - never crash
    the gate over a parse wobble, just under-scope that one call site)."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def extract_literal(original: str, pos: int) -> Optional[str]:
    """
    Given `pos` pointing at (or just before, modulo whitespace) a string/
    template literal in the ORIGINAL (unmasked) text, return its content
    (quotes stripped, common escapes unescaped). Returns None if `pos`
    isn't a string/template literal at all (e.g. a dynamic/variable title -
    none exist in frontend/tests/ today, checked at write time).
    """
    n = len(original)
    while pos < n and original[pos] in " \t\r\n":
        pos += 1
    if pos >= n or original[pos] not in ("'", '"', "`"):
        return None
    quote = original[pos]
    j = pos + 1
    while j < n:
        if original[j] == "\\":
            j += 2
            continue
        if original[j] == quote:
            break
        j += 1
    content = original[pos + 1 : min(j, n)]
    if quote != "`":
        content = content.replace(f"\\{quote}", quote).replace("\\\\", "\\")
    return content


HEAD_RE = re.compile(r"\btest(\.describe\.skip|\.describe\.only|\.describe|\.skip|\.beforeEach|\.only)?\s*\(")


def _classify(group1: Optional[str]) -> str:
    return {
        None: "test",
        ".describe.skip": "describe_skip",
        ".describe.only": "describe",
        ".describe": "describe",
        ".skip": "test_skip",
        ".beforeEach": "before_each",
        ".only": "test",
    }[group1]


@dataclass
class _Child:
    kind: str
    head_start: int
    paren_start: int
    call_end: int
    body_start: Optional[int]
    body_end: Optional[int]


def _scan_children(masked: str, pos: int, end: int) -> list:
    children = []
    i = pos
    while i < end:
        m = HEAD_RE.search(masked, i, end)
        if not m:
            break
        kind = _classify(m.group(1))
        paren_start = m.end() - 1
        call_end = find_matching(masked, paren_start, "(", ")")
        if call_end >= end:
            call_end = end - 1
        arrow_idx = masked.find("=>", paren_start, call_end)
        body_start = body_end = None
        if arrow_idx != -1:
            j = arrow_idx + 2
            while j < call_end and masked[j] in " \t\r\n":
                j += 1
            if j < call_end and masked[j] == "{":
                body_start, body_end = j + 1, find_matching(masked, j, "{", "}")
            elif j < call_end:
                body_start, body_end = j, call_end
        children.append(_Child(kind, m.start(), paren_start, call_end, body_start, body_end))
        i = call_end + 1
    return children


SKIP_CALL_RE = re.compile(r"\btestInfo\.skip\s*\(")


def _skip_reason(original: str, masked: str, body_start: int, body_end: int) -> Optional[str]:
    m = SKIP_CALL_RE.search(masked, body_start, body_end)
    if not m:
        return None
    paren_start = m.end() - 1
    call_end = find_matching(masked, paren_start, "(", ")")
    comma = masked.find(",", paren_start, call_end)
    if comma == -1:
        return None
    return extract_literal(original, comma + 1)


@dataclass
class TestEntry:
    file: str
    title: str
    skip: bool
    reason: Optional[str]
    line: int

    @property
    def test_id(self) -> str:
        return f"{self.file}::{self.title}"


def _parse_scope(
    original: str,
    masked: str,
    pos: int,
    end: int,
    file_rel: str,
    describe_stack: list,
    inherited_skip: bool,
    inherited_reason: Optional[str],
) -> list:
    results: list = []
    children = _scan_children(masked, pos, end)

    scope_skip = False
    scope_reason = None
    for c in children:
        if c.kind == "before_each" and c.body_start is not None:
            reason = _skip_reason(original, masked, c.body_start, c.body_end)
            if reason is not None or SKIP_CALL_RE.search(masked, c.body_start, c.body_end):
                scope_skip = True
                scope_reason = scope_reason or reason

    for c in children:
        if c.kind in ("describe", "describe_skip"):
            title = extract_literal(original, c.paren_start + 1)
            if title is None:
                title = f"<dynamic-describe-title-at-line-{line_of(original, c.head_start)}>"
            sub_skip = inherited_skip or scope_skip or (c.kind == "describe_skip")
            sub_reason = (
                inherited_reason or scope_reason or ("test.describe.skip" if c.kind == "describe_skip" else None)
            )
            if c.body_start is not None:
                results.extend(
                    _parse_scope(
                        original,
                        masked,
                        c.body_start,
                        c.body_end,
                        file_rel,
                        describe_stack + [title],
                        sub_skip,
                        sub_reason,
                    )
                )
        elif c.kind in ("test", "test_skip"):
            title = extract_literal(original, c.paren_start + 1)
            if title is None:
                title = f"<dynamic-test-title-at-line-{line_of(original, c.head_start)}>"
            own_reason = None
            own_skip = c.kind == "test_skip"
            if c.body_start is not None:
                own_reason = _skip_reason(original, masked, c.body_start, c.body_end)
                if own_reason is not None or SKIP_CALL_RE.search(masked, c.body_start, c.body_end):
                    own_skip = True
            skip = inherited_skip or scope_skip or own_skip
            reason = own_reason or scope_reason or inherited_reason
            if skip and reason is None and c.kind == "test_skip":
                reason = "test.skip"
            results.append(
                TestEntry(
                    file=file_rel,
                    title=" > ".join(describe_stack + [title]),
                    skip=skip,
                    reason=reason,
                    line=line_of(original, c.head_start),
                )
            )
        # kind == "before_each": already folded into scope_skip above.
    return results


def parse_file(source: str, file_rel: str) -> list:
    masked = mask_source(source)
    return _parse_scope(source, masked, 0, len(masked), file_rel, [], False, None)


# ---------------------------------------------------------------------------
# Manifest building
# ---------------------------------------------------------------------------


def _is_excluded(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    return any(p in EXCLUDED_DIR_PARTS for p in parts)


def build_manifest_from_worktree(repo_root: Path, tests_dir_rel: str = TESTS_DIR_REL) -> dict:
    manifest: dict = {}
    tests_dir = repo_root / tests_dir_rel
    if not tests_dir.is_dir():
        return manifest
    for path in sorted(tests_dir.rglob("*.spec.ts")):
        rel = path.relative_to(repo_root).as_posix()
        if _is_excluded(path.relative_to(tests_dir).as_posix()):
            continue
        source = path.read_text()
        for entry in parse_file(source, rel):
            manifest[entry.test_id] = entry
    return manifest


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def build_manifest_from_ref(repo_root: Path, ref: str, tests_dir_rel: str = TESTS_DIR_REL) -> dict:
    """
    Parses frontend/tests/**/*.spec.ts as they existed at `ref` (a commit-
    ish, normally a merge-base sha) using `git show`/`git ls-tree` only -
    no `git checkout`, so the caller's actual working tree is never
    touched.
    """
    manifest: dict = {}
    try:
        listing = _git(repo_root, "ls-tree", "-r", "--name-only", ref, "--", tests_dir_rel)
    except RuntimeError:
        return manifest
    for rel in listing.splitlines():
        rel = rel.strip()
        if not rel or not rel.endswith(".spec.ts"):
            continue
        if _is_excluded(Path(rel).relative_to(tests_dir_rel).as_posix()):
            continue
        try:
            source = _git(repo_root, "show", f"{ref}:{rel}")
        except RuntimeError:
            continue
        for entry in parse_file(source, rel):
            manifest[entry.test_id] = entry
    return manifest


def merge_base(repo_root: Path, base_ref: str) -> str:
    return _git(repo_root, "merge-base", "HEAD", base_ref).strip()


# ---------------------------------------------------------------------------
# Ack tokens
# ---------------------------------------------------------------------------

ACK_LINE_RE = re.compile(r"^coverage-ack:\s*(.+?)\s*—\s*(.+?)\s*$")


def load_acks(repo_root: Path, acks_file_rel: str = ACKS_FILE_REL) -> list:
    """Returns a list of (pattern, reason, line_no) tuples. Non-matching /
    blank / `#`-comment lines are ignored. `pattern` is matched against a
    test_id (`<file>::<full title>`) with fnmatch - a plain string with no
    wildcard is an exact match, `*`/`?`/`[...]` work as globs."""
    path = repo_root / acks_file_rel
    if not path.is_file():
        return []
    acks = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = ACK_LINE_RE.match(stripped)
        if m:
            acks.append((m.group(1), m.group(2), i))
    return acks


def is_acked(test_id: str, acks: list) -> Optional[tuple]:
    for pattern, reason, line_no in acks:
        if fnmatch.fnmatchcase(test_id, pattern):
            return (pattern, reason, line_no)
    return None


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    test_id: str
    kind: str  # "removed" | "newly_skipped"
    detail: str


def diff_manifests(base_manifest: dict, head_manifest: dict) -> list:
    violations = []
    for test_id, base_entry in sorted(base_manifest.items()):
        head_entry = head_manifest.get(test_id)
        if head_entry is None:
            violations.append(
                Violation(
                    test_id,
                    "removed",
                    f"present at base (file={base_entry.file}, line={base_entry.line}), " f"absent at head",
                )
            )
            continue
        if (not base_entry.skip) and head_entry.skip:
            violations.append(
                Violation(
                    test_id,
                    "newly_skipped",
                    f"active at base, skipped at head (file={head_entry.file}, "
                    f"line={head_entry.line}, reason={head_entry.reason or 'none given'})",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(repo_root: Path, base_ref: str, acks_file_rel: str = ACKS_FILE_REL) -> tuple:
    """Returns (unacked_violations, acked_violations, base_sha)."""
    base_sha = merge_base(repo_root, base_ref)
    base_manifest = build_manifest_from_ref(repo_root, base_sha)
    head_manifest = build_manifest_from_worktree(repo_root)
    violations = diff_manifests(base_manifest, head_manifest)
    acks = load_acks(repo_root, acks_file_rel)

    unacked, acked = [], []
    for v in violations:
        hit = is_acked(v.test_id, acks)
        if hit:
            acked.append((v, hit))
        else:
            unacked.append(v)
    return unacked, acked, base_sha


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("COVERAGE_DELTA_BASE", "origin/master"),
        help="Base ref/sha to diff against (default: $COVERAGE_DELTA_BASE or origin/master)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repo root (default: this script's repo)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    try:
        unacked, acked, base_sha = run(repo_root, args.base)
    except RuntimeError as exc:
        print(f"::error::coverage_delta.py could not compute a diff: {exc}")
        return 1

    print(f"coverage-delta: base={args.base} (merge-base {base_sha[:12]})")

    for v, (pattern, reason, line_no) in acked:
        print(
            f"coverage-delta: ACKED [{v.kind}] {v.test_id} - {v.detail} "
            f"(.github/coverage-acks.txt:{line_no} pattern=`{pattern}` reason: {reason})"
        )

    for v in unacked:
        print(
            f"::error::coverage-delta [{v.kind}] {v.test_id} - {v.detail}. "
            f"If this is intentional, add a line to .github/coverage-acks.txt: "
            f'"coverage-ack: {v.test_id} — <reason>" (a glob over file/title also works).'
        )

    if unacked:
        print(
            f"\n{len(unacked)} unacked coverage regression(s) " f"({len(acked)} acked). See issue #415 / incident #389."
        )
    else:
        extra = f" ({len(acked)} acked)" if acked else ""
        print(f"\ncoverage-delta: clean{extra}.")

    return len(unacked)


if __name__ == "__main__":
    raise SystemExit(main())
