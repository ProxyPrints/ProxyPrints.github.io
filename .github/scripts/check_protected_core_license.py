#!/usr/bin/env python3
"""
PROTECTED CORE license lint, per docs/upstreaming/license-provenance.md §2.

Fails if any PROTECTED_CORE_FILES entry (a) carries an AGPL provenance
marker on itself, or (b) locally imports another in-repo module that
does. The real invariant this enforces is "no AGPL-derived code in
protected core" — NOT "everything here must be GPL-3.0": one entry
(federation-hash-tool/hash_my_cards.py) is deliberately MIT-licensed
(docs/federation/public-export-v1.md §5), and AGPL would poison either
license, not just GPL-3.0.

Provenance marker convention (docs/upstreaming/license-provenance.md
§3's absorption protocol): a `# PROVENANCE: <repo>, <commit/tag>,
<license>` comment near the top of a vendored file. This lint only looks
for the substring "AGPL" in that line - it does not attempt to scan
transitive PyPI/npm dependency license metadata (a separate, much larger
problem; tools like `pip-licenses` exist for that). Nothing in this repo
is AGPL-marked as of this writing - this lint passes with zero findings
today, correctly, and exists to catch the day that stops being true.

Exit code is the number of findings (0 = clean), matching docs_lint.py's
own convention.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The exact PROTECTED CORE file list - docs/upstreaming/license-provenance.md
# §2 is the source of truth; keep these in sync in the same PR.
PROTECTED_CORE_FILES = [
    "MPCAutofill/cardpicker/vote_consensus.py",
    "MPCAutofill/cardpicker/printing_consensus.py",
    "MPCAutofill/cardpicker/tag_consensus.py",
    "MPCAutofill/cardpicker/artist_consensus.py",
    "MPCAutofill/cardpicker/local_phash.py",
    "MPCAutofill/cardpicker/local_fallback.py",
    "federation-hash-tool/hash_my_cards.py",
    "federation-hash-tool/tests/test_hash_my_cards.py",
    "MPCAutofill/cardpicker/tests/test_federation_hash_tool_parity.py",
]

# Local import roots: a dotted import prefix maps to a directory that acts
# as its own package root, mirroring how MPCAutofill/manage.py makes
# MPCAutofill/ (not the repo root) the resolution root for `cardpicker.*`,
# and federation-hash-tool/ is its own standalone, dependency-free root.
IMPORT_ROOTS = [
    REPO_ROOT / "MPCAutofill",
    REPO_ROOT / "federation-hash-tool",
]

PROVENANCE_RE = re.compile(r"#\s*PROVENANCE:.*", re.IGNORECASE)


def is_agpl_marked(text: str) -> bool:
    for m in PROVENANCE_RE.finditer(text):
        if "AGPL" in m.group(0).upper():
            return True
    return False


def resolve_local_import(module: str) -> Path | None:
    """module is a dotted path like 'cardpicker.models' - resolve it against
    each import root, trying both '<module_path>.py' and
    '<module_path>/__init__.py'. Returns None for anything that doesn't
    resolve locally (a real third-party/stdlib import, which this lint
    doesn't scan - see the module docstring)."""
    parts = module.split(".")
    for root in IMPORT_ROOTS:
        candidate = root.joinpath(*parts).with_suffix(".py")
        if candidate.is_file():
            return candidate
        candidate_pkg = root.joinpath(*parts, "__init__.py")
        if candidate_pkg.is_file():
            return candidate_pkg
    return None


def local_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


def check_file(rel_path: str) -> list[str]:
    findings = []
    path = REPO_ROOT / rel_path
    if not path.is_file():
        return [f"::error::check_protected_core_license.py: PROTECTED_CORE_FILES entry {rel_path!r} does not exist"]

    text = path.read_text()
    if is_agpl_marked(text):
        findings.append(f"::error file={rel_path}::PROTECTED CORE file itself carries an AGPL provenance marker")

    for module in local_imports(path):
        resolved = resolve_local_import(module)
        if resolved is None:
            continue
        imported_text = resolved.read_text()
        if is_agpl_marked(imported_text):
            findings.append(
                f"::error file={rel_path}::imports {module!r} "
                f"({resolved.relative_to(REPO_ROOT)}), which carries an AGPL provenance marker"
            )

    return findings


def main() -> int:
    all_findings = []
    for rel_path in PROTECTED_CORE_FILES:
        all_findings.extend(check_file(rel_path))

    for finding in all_findings:
        print(finding)

    if all_findings:
        print(f"\n{len(all_findings)} PROTECTED CORE license violation(s) found.")
    else:
        print(f"protected-core-license: clean ({len(PROTECTED_CORE_FILES)} files checked).")

    return len(all_findings)


if __name__ == "__main__":
    raise SystemExit(main())
