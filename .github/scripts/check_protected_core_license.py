#!/usr/bin/env python3
"""
PROTECTED CORE license lint, per docs/upstreaming/license-provenance.md §2.

Fails if any protected-core file (a) carries an AGPL provenance marker on
itself, (b) locally imports another in-repo module that does, or (c) is
listed in the policy but does not exist on disk.

The real invariant this enforces is "no AGPL-derived code in protected
core" — NOT "everything here must be GPL-3.0": two entries
(federation-hash-tool/hash_my_cards.py and decrypt-saved-deck-export/
decrypt.mjs, plus their tests) are deliberately MIT-licensed
(docs/federation/public-export-v1.md §5; PR #242), and AGPL would poison
either license, not just GPL-3.0.

THE ROSTER IS DERIVED FROM THE POLICY DOC, NOT RESTATED HERE
------------------------------------------------------------
This script holds no file list. It parses the marker-bounded region in
docs/upstreaming/license-provenance.md §2 and treats every backtick-quoted
repo path inside it as a protected-core file.

That is a deliberate correction of a real, dated failure. §2 declared
`decrypt-saved-deck-export/decrypt.mjs` and its test part of the trust
anchor, and instructed that they be added to this script's hand-maintained
`PROTECTED_CORE_FILES` "in the PR that merges #242 (or immediately
after)". #242 merged (`5ddf109c`), both files landed on master, and the
list was never updated — so two files the policy calls a trust anchor
carried no gate at all until 2026-07-29. Two hand-maintained lists kept in
sync by a prose convention is the defect; adding a third entry to the
second list would only have deferred it. With the roster derived, the doc
and the check cannot disagree, because there is only one list.

If the marker region is missing or yields no paths, that is a HARD
FINDING, not a quiet pass — a roster check that silently checks nothing is
worse than no check.

PROVENANCE MARKER CONVENTION (docs/upstreaming/license-provenance.md §3's
absorption protocol): a `PROVENANCE: <repo>, <commit/tag>, <license>`
comment near the top of a vendored file. The comment leader may be `#`
(Python/shell), `//` (JS) or `*` (inside a JS block comment) — the roster
spans two languages, and a regex that only recognised `#` would have let a
`// PROVENANCE: ..., AGPL-3.0` line in a `.mjs` roster file pass unseen.
This lint only looks for the substring "AGPL" in that line; it does not
attempt to scan transitive PyPI/npm dependency license metadata (a
separate, much larger problem; tools like `pip-licenses` exist for that).
Nothing in this repo is AGPL-marked as of this writing - this lint passes
with zero findings today, correctly, and exists to catch the day that
stops being true.

Exit code is the number of findings (0 = clean), matching docs_lint.py's
own convention.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# docs/upstreaming/license-provenance.md §2 is the source of truth for the
# protected-core roster, and this script READS it (see the module docstring)
# rather than restating it. These three constants are the entire contract
# with the doc: the markers bound the region, and every backtick-quoted
# path inside it is a roster entry.
POLICY_DOC_REL = "docs/upstreaming/license-provenance.md"
ROSTER_BEGIN_MARKER = "<!-- PROTECTED-CORE-ROSTER:BEGIN -->"
ROSTER_END_MARKER = "<!-- PROTECTED-CORE-ROSTER:END -->"

# A backtick span is a roster path if it contains "/" and ends in one of
# these. Prose inside the region routinely backticks non-paths (constant
# names, PR refs); requiring both a separator and a known source extension
# keeps those out without needing a second allowlist.
ROSTER_PATH_EXTENSIONS = (".py", ".mjs", ".cjs", ".js", ".ts", ".tsx")
ROSTER_PATH_RE = re.compile(r"`([\w./\-]+/[\w./\-]+)`")

# Local import roots: a dotted import prefix maps to a directory that acts
# as its own package root, mirroring how MPCAutofill/manage.py makes
# MPCAutofill/ (not the repo root) the resolution root for `cardpicker.*`,
# and federation-hash-tool/ is its own standalone, dependency-free root.
IMPORT_ROOTS = [
    REPO_ROOT / "MPCAutofill",
    REPO_ROOT / "federation-hash-tool",
]

# Accepts `#`, `//` and `*` comment leaders — see the module docstring's
# marker-convention note for why the `#`-only form was a real hole.
PROVENANCE_RE = re.compile(r"(?:#|//|\*)\s*PROVENANCE:.*", re.IGNORECASE)

PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".mjs", ".cjs", ".js")

# ES-module / CommonJS specifier extraction. Deliberately regex, not a JS
# parser: the roster's JS entries are by policy zero-dependency, single-file
# tools, and this repo's stated "narrow v1, no heavyweight library"
# philosophy (docs_lint.py's own limitation note) applies. The cost is that
# an exotic construct could be missed; the alternative is vendoring a JS
# parser into CI to check two files.
JS_IMPORT_RE = re.compile(
    r"""(?:
          \bimport\s+[^;'"]*?\bfrom\s*["']([^"']+)["']   # import x from "y"
        | \bexport\s+[^;'"]*?\bfrom\s*["']([^"']+)["']   # export * from "y"
        | \bimport\s*["']([^"']+)["']                    # import "y" (side effect)
        | \bimport\s*\(\s*["']([^"']+)["']               # dynamic import("y")
        | \brequire\s*\(\s*["']([^"']+)["']              # require("y")
    )""",
    re.VERBOSE,
)


def is_agpl_marked(text: str) -> bool:
    for m in PROVENANCE_RE.finditer(text):
        if "AGPL" in m.group(0).upper():
            return True
    return False


def protected_core_files() -> tuple[list[str], list[str]]:
    """
    DERIVE the protected-core roster from the policy doc. Returns
    (paths, findings) — findings is non-empty when the region itself is
    broken, which must fail loudly rather than yield an empty roster.

    Order is preserved and duplicates collapsed, so a path that appears
    twice in the prose is checked once.
    """
    doc = REPO_ROOT / POLICY_DOC_REL
    if not doc.is_file():
        return [], [
            f"::error::check_protected_core_license.py: policy doc {POLICY_DOC_REL} "
            f"is missing — the protected-core roster is derived from its §2 marker "
            f"region and cannot be built without it"
        ]

    text = doc.read_text()
    start = text.find(ROSTER_BEGIN_MARKER)
    end = text.find(ROSTER_END_MARKER)
    if start == -1 or end == -1 or end < start:
        return [], [
            f"::error file={POLICY_DOC_REL}::protected-core roster markers "
            f"{ROSTER_BEGIN_MARKER} / {ROSTER_END_MARKER} not found (or out of "
            f"order) in §2. This script derives its file list from that region; "
            f"without the markers it would check NOTHING and pass, so the missing "
            f"markers are themselves the finding."
        ]

    region = text[start + len(ROSTER_BEGIN_MARKER) : end]
    paths: list[str] = []
    for m in ROSTER_PATH_RE.finditer(region):
        candidate = m.group(1)
        if not candidate.endswith(ROSTER_PATH_EXTENSIONS):
            continue
        if candidate not in paths:
            paths.append(candidate)

    if not paths:
        return [], [
            f"::error file={POLICY_DOC_REL}::protected-core roster region is "
            f"present but contains no backtick-quoted source paths. An empty "
            f"roster means this lint checks nothing; that is the finding."
        ]

    return paths, []


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


def js_imports(path: Path) -> list[str]:
    """Every import/require specifier in a JS/ESM file, in source order."""
    specifiers = []
    for m in JS_IMPORT_RE.finditer(path.read_text()):
        specifiers.append(next(g for g in m.groups() if g is not None))
    return specifiers


def resolve_js_import(specifier: str, importer: Path) -> Path | None:
    """
    Resolve a JS specifier to an in-repo file, or None.

    Only RELATIVE specifiers resolve. A bare specifier is either a `node:`
    builtin or an npm package — the same out-of-scope category as a PyPI
    import on the Python side, and the roster's JS entries are by policy
    dependency-free anyway. Tries the literal path first (ESM requires the
    extension), then the extension-less CommonJS / index forms so a future
    roster addition written in either style still resolves.
    """
    if not specifier.startswith("."):
        return None
    base = (importer.parent / specifier).resolve()
    candidates = [base]
    for ext in JS_SUFFIXES:
        candidates.append(base.with_name(base.name + ext))
        candidates.append(base / ("index" + ext))
    for candidate in candidates:
        if candidate.is_file():
            try:
                candidate.relative_to(REPO_ROOT)
            except ValueError:
                return None  # escaped the repo — not an in-repo module
            return candidate
    return None


def check_file(rel_path: str) -> list[str]:
    findings = []
    path = REPO_ROOT / rel_path
    if not path.is_file():
        return [
            f"::error file={POLICY_DOC_REL}::protected-core roster lists "
            f"{rel_path!r}, which does not exist in the repo"
        ]

    text = path.read_text()
    if is_agpl_marked(text):
        findings.append(f"::error file={rel_path}::PROTECTED CORE file itself carries an AGPL provenance marker")

    if path.suffix in PY_SUFFIXES:
        dependencies = [(module, resolve_local_import(module)) for module in local_imports(path)]
    elif path.suffix in JS_SUFFIXES:
        dependencies = [(spec, resolve_js_import(spec, path)) for spec in js_imports(path)]
    else:
        # A roster entry in a language this lint cannot walk is a hard
        # finding, not a silent skip: it would otherwise be an entry that
        # LOOKS gated and is not — the exact failure this script was
        # rewritten to eliminate.
        findings.append(
            f"::error file={rel_path}::protected-core roster entry has unsupported "
            f"suffix {path.suffix!r} — this lint can only walk imports for "
            f"{list(PY_SUFFIXES + JS_SUFFIXES)}. Extend "
            f"check_protected_core_license.py rather than leaving the entry "
            f"half-checked."
        )
        return findings

    for module, resolved in dependencies:
        if resolved is None:
            continue
        if is_agpl_marked(resolved.read_text()):
            findings.append(
                f"::error file={rel_path}::imports {module!r} "
                f"({resolved.relative_to(REPO_ROOT)}), which carries an AGPL provenance marker"
            )

    return findings


def main() -> int:
    roster, all_findings = protected_core_files()
    for rel_path in roster:
        all_findings.extend(check_file(rel_path))

    for finding in all_findings:
        print(finding)

    if all_findings:
        print(f"\n{len(all_findings)} PROTECTED CORE license violation(s) found.")
    else:
        print(f"protected-core-license: clean ({len(roster)} files checked, derived from {POLICY_DOC_REL} §2).")

    return len(all_findings)


if __name__ == "__main__":
    raise SystemExit(main())
