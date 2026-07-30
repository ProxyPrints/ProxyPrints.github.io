#!/usr/bin/env python3
"""
CODE-TO-CODE tether: the Stage C extractor manifest.

`MPCAutofill/cardpicker/image_evidence.py` declares eleven
`*_EXTRACTOR_VERSION` constants and writes them into each card's
`ImageEvidence.extractor_versions` manifest under a fixed key
(`extractor_versions["collector_line_ocr"] = COLLECTOR_LINE_OCR_EXTRACTOR_VERSION`).

`MPCAutofill/cardpicker/management/commands/run_image_evidence_cohort.py`
then RE-TYPES that same information as two module-level literals —
`MANIFEST_EXTRACTOR_KEYS` (the key set) and
`MANIFEST_EXTRACTOR_CURRENT_VERSIONS` (key -> current version string).
Nothing imports the version constants; the values are typed out again by
hand. The only thing holding the two files together is prose:

    # ... matches image_evidence.extract_card_evidence's own
    # extractor_versions keys exactly. Keep this set in sync with that
    # function whenever a new extractor group lands

That is the same defect this repo's roster tethers exist to close, in its
code-to-code form. This script is its tether: `image_evidence.py` is the
SOURCE OF TRUTH, the cohort constants are the thing checked.

WHY IT MATTERS (not a tidiness rule)
------------------------------------
`MANIFEST_EXTRACTOR_CURRENT_VERSIONS` is the resume filter. `handle()`
skips a card when `MANIFEST_EXTRACTOR_CURRENT_VERSIONS.items() <=
extractor_versions.items()`, so:

  - a version this file still lists at the OLD value silently marks stale
    rows "already done" and they are never re-extracted;
  - a version listed at a value nothing ever writes marks every row
    incomplete and re-pays fetch+OCR across ~220k cards.

`image_evidence.py`'s own comments say as much ("...and forcing a ~220k-card
re-extraction"). Both failure modes are silent at runtime: no exception,
no log line, just the wrong cohort.

`MANIFEST_EXTRACTOR_KEYS` has the same exposure through
`evidence_transfer.py`'s `.filter(extractor_versions__has_keys=...)` and
`stage_e_dispatch.py`'s dispatch filters.

WHAT IS DERIVED, AND WHY IT IS SAFE TO DERIVE
---------------------------------------------
Everything is read with `ast`, never by importing or executing (no Django
needed in CI). Three facts come out of `image_evidence.py`:

  1. module-level `<NAME>_EXTRACTOR_VERSION = "<literal>"` declarations;
  2. every `extractor_versions[<literal key>] = <NAME>` subscript store,
     anywhere in the module;
  3. the resulting {key: version} manifest.

Deliberately NOT keyed on the enclosing function name. The sync comment in
the cohort file names `extract_card_evidence`, but the assignments actually
live in `compute_card_evidence` — the prose was already wrong about that,
which is itself an argument against trusting a hand-written anchor. Any
subscript store into a local named `extractor_versions` counts.

Deliberately NOT a regex over string literals: three version-shaped strings
("fetch-health-v1", "collector-line-ocr-v1") appear in COMMENTS explaining
retired versions, and a text scan would sweep those in as current.

Exit code is the number of findings (0 = clean), matching docs_lint.py's
and check_protected_core_license.py's convention.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_REL = "MPCAutofill/cardpicker/image_evidence.py"
COHORT_REL = "MPCAutofill/cardpicker/management/commands/run_image_evidence_cohort.py"

VERSION_CONST_SUFFIX = "_EXTRACTOR_VERSION"
MANIFEST_DICT_NAME = "extractor_versions"
KEYS_CONST = "MANIFEST_EXTRACTOR_KEYS"
VERSIONS_CONST = "MANIFEST_EXTRACTOR_CURRENT_VERSIONS"

# `*_EXTRACTOR_VERSION` constants that legitimately do NOT appear in the
# manifest. EXPLICIT and per-entry-justified, following
# docs_lint.py's CALCULATOR_ROSTER_ALLOWLIST / SKIP_REASON_ROSTER_ALLOWLIST:
# an exclusion must be a visible decision, never a silent gap. Nothing goes
# here merely because it currently fails the check.
#
# EMPTY TODAY, deliberately — all eleven declared constants are written into
# the manifest. A constant declared and never written is far more likely to
# be a forgotten `extractor_versions[...] = ...` line than a deliberate
# exception, and that is exactly the mistake worth failing on.
UNMANIFESTED_CONSTANT_ALLOWLIST: dict = {}


def _module_level_bindings(tree: ast.Module):
    """Yield (name, value_node) for every module-level `NAME = ...`.

    Both `ast.Assign` and `ast.AnnAssign` — the annotated form is not a
    stylistic variant to skip: `MANIFEST_EXTRACTOR_CURRENT_VERSIONS:
    dict[str, str] = {...}` is written that way, and an Assign-only walk
    read it as "missing", which would have made this tether unable to check
    the more consequential of the two constants.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            yield node.target.id, node.value


def _module_level_string_constants(tree: ast.Module, suffix: str) -> dict:
    """{CONST_NAME: literal value} for column-0 `NAME = "literal"` bindings.

    Module level only, string literal only — the same discipline as
    docs_lint.py's roster regexes. An indented rebinding declares nothing,
    and an alias (`X = OTHER`) re-declares nothing.
    """
    out = {}
    for name, value in _module_level_bindings(tree):
        if not name.endswith(suffix):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[name] = value.value
    return out


def _manifest_assignments(tree: ast.Module) -> dict:
    """{manifest key: constant name} for `extractor_versions["k"] = CONST`.

    Walked over the WHOLE module rather than one named function — see the
    module docstring on why the hand-written function anchor is not
    trustworthy. Only a literal-string subscript with a bare Name value
    counts; anything computed is not a static declaration and is reported
    as unreadable rather than guessed at.
    """
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if not (isinstance(target.value, ast.Name) and target.value.id == MANIFEST_DICT_NAME):
                continue
            if not (isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
                continue
            if isinstance(node.value, ast.Name):
                out[target.slice.value] = node.value.id
    return out


def _module_level_literal(tree: ast.Module, name: str):
    """The literal value of a module-level `NAME = <literal>` binding, or None."""
    for bound_name, value in _module_level_bindings(tree):
        if bound_name != name:
            continue
        # `frozenset({...})` / `set({...})` wrappers around a literal.
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"frozenset", "set"}:
            if not value.args:
                return set()
            value = value.args[0]
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None
    return None


def _parse(rel: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    return ast.parse(path.read_text(), filename=str(path))


def derive_expected_manifest() -> tuple[dict, list[str]]:
    """
    DERIVE {manifest key: version string} from image_evidence.py.

    Returns (manifest, findings). Findings are non-empty when the
    derivation itself fails, which must be loud: a tether that derives an
    empty expectation compares nothing to nothing and passes forever.
    """
    tree = _parse(SOURCE_REL)
    if tree is None:
        return {}, [f"::error::check_extractor_manifest_sync.py: {SOURCE_REL} not found"]

    constants = _module_level_string_constants(tree, VERSION_CONST_SUFFIX)
    assignments = _manifest_assignments(tree)

    findings = []
    if not constants:
        findings.append(
            f"::error file={SOURCE_REL}::no module-level `*{VERSION_CONST_SUFFIX}` string "
            f"constants found. This tether derives its expectation from them; finding none "
            f"means it would compare an empty manifest and pass vacuously, so the empty "
            f"derivation is itself the finding."
        )
    if not assignments:
        findings.append(
            f'::error file={SOURCE_REL}::no `{MANIFEST_DICT_NAME}["<key>"] = <CONSTANT>` '
            f"assignments found. Same reason as above: an empty derivation is the finding, "
            f"not a pass."
        )
    if findings:
        return {}, findings

    manifest = {}
    for key, const_name in sorted(assignments.items()):
        if const_name not in constants:
            findings.append(
                f"::error file={SOURCE_REL}::manifest key `{key}` is assigned from "
                f"`{const_name}`, which is not a module-level `*{VERSION_CONST_SUFFIX}` "
                f"string constant in this file. The tether can only read static "
                f"declarations; make it one, or the manifest value is unverifiable."
            )
            continue
        manifest[key] = constants[const_name]

    # A declared version constant that never reaches the manifest is a hole
    # in the opposite direction: the extractor bumped its version and the
    # `extractor_versions[...] = ...` line was forgotten, so nothing records
    # which version produced the row.
    manifested_constants = set(assignments.values())
    for const_name, value in sorted(constants.items()):
        if const_name in manifested_constants:
            continue
        if const_name in UNMANIFESTED_CONSTANT_ALLOWLIST:
            continue
        findings.append(
            f"::error file={SOURCE_REL}::`{const_name}` (= {value!r}) is declared but is "
            f"never written into the `{MANIFEST_DICT_NAME}` manifest, so no row records "
            f"which version of that extractor produced it. Add the "
            f'`{MANIFEST_DICT_NAME}["<key>"] = {const_name}` assignment, or add an entry '
            f"to UNMANIFESTED_CONSTANT_ALLOWLIST in "
            f".github/scripts/check_extractor_manifest_sync.py with a per-entry reason."
        )

    return manifest, findings


def check() -> list[str]:
    expected, findings = derive_expected_manifest()
    if findings:
        return findings

    cohort = _parse(COHORT_REL)
    if cohort is None:
        return [f"::error::check_extractor_manifest_sync.py: {COHORT_REL} not found"]

    declared_keys = _module_level_literal(cohort, KEYS_CONST)
    declared_versions = _module_level_literal(cohort, VERSIONS_CONST)

    if declared_keys is None:
        findings.append(
            f"::error file={COHORT_REL}::`{KEYS_CONST}` is missing, or is not a "
            f"module-level literal this tether can read statically."
        )
    if declared_versions is None:
        findings.append(
            f"::error file={COHORT_REL}::`{VERSIONS_CONST}` is missing, or is not a "
            f"module-level literal this tether can read statically."
        )
    if findings:
        return findings

    declared_keys = set(declared_keys)
    expected_keys = set(expected)

    for key in sorted(expected_keys - declared_keys):
        findings.append(
            f"::error file={COHORT_REL}::`{KEYS_CONST}` is missing manifest key `{key}`, "
            f"which {SOURCE_REL} writes into every row's manifest. Stale here silently "
            f"under-counts 'already done' and re-pays fetch+OCR cost the resume filter "
            f"exists to avoid."
        )
    for key in sorted(declared_keys - expected_keys):
        findings.append(
            f"::error file={COHORT_REL}::`{KEYS_CONST}` lists manifest key `{key}`, which "
            f"{SOURCE_REL} never writes. No row will ever carry it, so every card reads as "
            f"incomplete and is re-processed forever."
        )

    # The two cohort constants must agree with each other as well as with
    # the source — they are consumed by different call sites
    # (evidence_transfer's has_keys filter vs. the version-aware resume
    # filter), so a disagreement between them is its own live bug.
    for key in sorted(declared_keys - set(declared_versions)):
        findings.append(
            f"::error file={COHORT_REL}::`{KEYS_CONST}` lists `{key}` but `{VERSIONS_CONST}` "
            f"has no entry for it — the two constants disagree with each other."
        )
    for key in sorted(set(declared_versions) - declared_keys):
        findings.append(
            f"::error file={COHORT_REL}::`{VERSIONS_CONST}` has an entry for `{key}` but "
            f"`{KEYS_CONST}` does not list it — the two constants disagree with each other."
        )

    for key in sorted(expected_keys & set(declared_versions)):
        if declared_versions[key] != expected[key]:
            findings.append(
                f"::error file={COHORT_REL}::`{VERSIONS_CONST}[{key!r}]` is "
                f"{declared_versions[key]!r} but {SOURCE_REL} currently writes "
                f"{expected[key]!r}. A stale value here marks already-extracted rows as "
                f"current (they are never re-extracted) or marks current rows as stale "
                f"(a full re-extraction). Both are silent at runtime."
            )
    for key in sorted(expected_keys - set(declared_versions)):
        findings.append(
            f"::error file={COHORT_REL}::`{VERSIONS_CONST}` has no entry for manifest key "
            f"`{key}` (expected {expected[key]!r} per {SOURCE_REL})."
        )

    return findings


def main() -> int:
    findings = check()
    for finding in findings:
        print(finding)

    if findings:
        print(f"\n{len(findings)} extractor-manifest sync finding(s).")
    else:
        expected, _ = derive_expected_manifest()
        print(f"extractor-manifest-sync: clean ({len(expected)} manifest keys, derived from {SOURCE_REL}).")

    return len(findings)


if __name__ == "__main__":
    raise SystemExit(main())
