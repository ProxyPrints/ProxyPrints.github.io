"""
Unit tests for check_protected_core_license.py, per
docs/upstreaming/license-provenance.md §2. Proves the lint actually
catches a violation (not just "passes with zero findings against the
real repo, trust us") via real fixture cases in a scratch directory,
and separately confirms the real repo's own derived roster is clean
today - the property docs-lint.yml's protected-core-license job
enforces on every PR.

Covers three classes of failure, each of which has actually happened or
was structurally possible before 2026-07-29:
  1. an AGPL marker on a protected-core file or one it imports (the
     original purpose);
  2. the DERIVED ROSTER going wrong - missing markers, an empty region, a
     path that does not exist, an unwalkable file type. Each must be a
     hard finding, because the failure mode of a roster check is to check
     nothing and pass;
  3. JS/ESM entries being invisible - before this rewrite the marker
     regex required a `#` leader and the import walk was Python-only, so
     `decrypt-saved-deck-export/decrypt.mjs` (a policy-declared trust
     anchor) would have been "checked" without either rule being able to
     fire on it.

Run: python3 .github/scripts/tests/test_check_protected_core_license.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import check_protected_core_license as lint  # noqa: E402


class _patched_roots:
    """Context manager: temporarily repoint REPO_ROOT/IMPORT_ROOTS at a
    scratch fixture dir, restoring the real repo afterward."""

    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    def __enter__(self) -> None:
        self._real_repo_root = lint.REPO_ROOT
        self._real_import_roots = lint.IMPORT_ROOTS
        lint.REPO_ROOT = self.fixture_root
        lint.IMPORT_ROOTS = [self.fixture_root / "MPCAutofill"]

    def __exit__(self, *exc: object) -> None:
        lint.REPO_ROOT = self._real_repo_root
        lint.IMPORT_ROOTS = self._real_import_roots


class TestAgplMarkerDetection(unittest.TestCase):
    def test_detects_agpl_provenance_marker(self) -> None:
        self.assertTrue(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, AGPL-3.0\n"))

    def test_gpl_marker_is_not_agpl(self) -> None:
        self.assertFalse(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, GPL-3.0\n"))

    def test_mit_marker_is_not_agpl(self) -> None:
        self.assertFalse(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, MIT\n"))

    def test_no_marker_at_all(self) -> None:
        self.assertFalse(lint.is_agpl_marked("import os\nimport sys\n"))

    # --- JS comment leaders. The `#`-only regex could not see any of these,
    # which left every .mjs roster entry ungated on the self-marker rule.
    def test_detects_agpl_marker_behind_double_slash(self) -> None:
        self.assertTrue(lint.is_agpl_marked('// PROVENANCE: some/repo, v1, AGPL-3.0\nimport x from "y";\n'))

    def test_detects_agpl_marker_inside_block_comment(self) -> None:
        self.assertTrue(lint.is_agpl_marked("/**\n * PROVENANCE: some/repo, v1, AGPL-3.0\n */\n"))

    def test_mit_marker_behind_double_slash_is_not_agpl(self) -> None:
        self.assertFalse(lint.is_agpl_marked("// PROVENANCE: some/repo, v1, MIT\n"))


class TestJsImportExtraction(unittest.TestCase):
    def test_extracts_every_specifier_form(self) -> None:
        src = (
            'import { a } from "node:crypto";\n'
            "import b from './b.mjs';\n"
            'import "./side-effect.mjs";\n'
            'export { c } from "../c.mjs";\n'
            'const d = await import("./d.mjs");\n'
            'const e = require("./e.cjs");\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.mjs"
            f.write_text(src)
            self.assertEqual(
                lint.js_imports(f),
                ["node:crypto", "./b.mjs", "./side-effect.mjs", "../c.mjs", "./d.mjs", "./e.cjs"],
            )

    def test_bare_specifier_does_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.mjs"
            f.write_text("")
            self.assertIsNone(lint.resolve_js_import("node:crypto", f))
            self.assertIsNone(lint.resolve_js_import("some-npm-package", f))

    def test_relative_specifier_resolves_to_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "dep.mjs").write_text("export const x = 1;\n")
            (root / "tests").mkdir()
            importer = root / "tests" / "t.mjs"
            importer.write_text('import { x } from "../dep.mjs";\n')
            with _patched_roots(root):
                self.assertEqual(lint.resolve_js_import("../dep.mjs", importer), root / "dep.mjs")

    def test_extensionless_relative_specifier_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "dep.mjs").write_text("export const x = 1;\n")
            importer = root / "t.mjs"
            importer.write_text("")
            with _patched_roots(root):
                self.assertEqual(lint.resolve_js_import("./dep", importer), root / "dep.mjs")


class TestCheckFileAgainstFixtures(unittest.TestCase):
    def _fixture_repo(self, tmp: str, clean_module_body: str, protected_body: str) -> None:
        root = Path(tmp)
        (root / "MPCAutofill" / "cardpicker").mkdir(parents=True)
        (root / "MPCAutofill" / "cardpicker" / "clean_dep.py").write_text(clean_module_body)
        (root / "MPCAutofill" / "cardpicker" / "protected.py").write_text(protected_body)

    def test_clean_protected_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._fixture_repo(
                tmp,
                clean_module_body="# PROVENANCE: some/repo, v1, MIT\ndef helper(): pass\n",
                protected_body="from cardpicker.clean_dep import helper\n",
            )
            with _patched_roots(Path(tmp)):
                findings = lint.check_file("MPCAutofill/cardpicker/protected.py")
            self.assertEqual(findings, [])

    def test_protected_file_importing_agpl_marked_local_module_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._fixture_repo(
                tmp,
                clean_module_body="# PROVENANCE: some/repo, v1, AGPL-3.0\ndef helper(): pass\n",
                protected_body="from cardpicker.clean_dep import helper\n",
            )
            with _patched_roots(Path(tmp)):
                findings = lint.check_file("MPCAutofill/cardpicker/protected.py")
            self.assertEqual(len(findings), 1)
            self.assertIn("AGPL", findings[0])

    def test_protected_file_self_marked_agpl_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._fixture_repo(
                tmp,
                clean_module_body="def helper(): pass\n",
                protected_body="# PROVENANCE: some/repo, v1, AGPL-3.0\ndef x(): pass\n",
            )
            with _patched_roots(Path(tmp)):
                findings = lint.check_file("MPCAutofill/cardpicker/protected.py")
            self.assertEqual(len(findings), 1)
            self.assertIn("itself carries", findings[0])

    def test_missing_protected_core_file_is_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patched_roots(Path(tmp)):
                findings = lint.check_file("MPCAutofill/cardpicker/does_not_exist.py")
            self.assertEqual(len(findings), 1)
            self.assertIn("does not exist", findings[0])

    def test_unwalkable_roster_entry_is_a_finding_not_a_silent_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tool").mkdir()
            (root / "tool" / "thing.rs").write_text("fn main() {}\n")
            with _patched_roots(root):
                findings = lint.check_file("tool/thing.rs")
            self.assertEqual(len(findings), 1)
            self.assertIn("unsupported suffix", findings[0])


class TestCheckFileJsFixtures(unittest.TestCase):
    """The .mjs half of the roster, which had no working rule at all before."""

    def _js_fixture(self, tmp: str, dep_body: str, tool_body: str) -> Path:
        root = Path(tmp).resolve()
        (root / "tool" / "tests").mkdir(parents=True)
        (root / "tool" / "dep.mjs").write_text(dep_body)
        (root / "tool" / "tests" / "tool.test.mjs").write_text(tool_body)
        return root

    def test_clean_js_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._js_fixture(
                tmp,
                dep_body="// PROVENANCE: some/repo, v1, MIT\nexport const x = 1;\n",
                tool_body='import { x } from "../dep.mjs";\n',
            )
            with _patched_roots(root):
                self.assertEqual(lint.check_file("tool/tests/tool.test.mjs"), [])

    def test_js_file_importing_agpl_marked_local_module_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._js_fixture(
                tmp,
                dep_body="// PROVENANCE: some/repo, v1, AGPL-3.0\nexport const x = 1;\n",
                tool_body='import { x } from "../dep.mjs";\n',
            )
            with _patched_roots(root):
                findings = lint.check_file("tool/tests/tool.test.mjs")
            self.assertEqual(len(findings), 1)
            self.assertIn("AGPL", findings[0])
            self.assertIn("tool/dep.mjs", findings[0])

    def test_js_file_self_marked_agpl_in_block_comment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._js_fixture(
                tmp,
                dep_body="export const x = 1;\n",
                tool_body='/**\n * PROVENANCE: some/repo, v1, AGPL-3.0\n */\nimport { x } from "../dep.mjs";\n',
            )
            with _patched_roots(root):
                findings = lint.check_file("tool/tests/tool.test.mjs")
            self.assertEqual(len(findings), 1)
            self.assertIn("itself carries", findings[0])

    def test_bare_npm_specifier_is_not_walked(self) -> None:
        """A bare specifier is out of scope by design (module docstring) —
        asserted explicitly so a future 'helpful' resolver change that
        starts walking node_modules trips this test."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._js_fixture(
                tmp,
                dep_body="export const x = 1;\n",
                tool_body='import { webcrypto } from "node:crypto";\n',
            )
            with _patched_roots(root):
                self.assertEqual(lint.check_file("tool/tests/tool.test.mjs"), [])


class TestRosterDerivation(unittest.TestCase):
    """The roster comes from the doc. These prove the derivation is real —
    that it reads what the doc says, and fails loudly rather than quietly
    checking nothing when the doc's region is broken."""

    def _doc(self, tmp: str, body: str) -> Path:
        root = Path(tmp)
        (root / lint.POLICY_DOC_REL).parent.mkdir(parents=True)
        (root / lint.POLICY_DOC_REL).write_text(body)
        return root

    def test_derives_paths_from_marker_region(self) -> None:
        body = (
            "## 2. Protected core\n\n"
            "prose mentioning `MPCAutofill/cardpicker/models.py` OUTSIDE the region\n\n"
            f"{lint.ROSTER_BEGIN_MARKER}\n\n"
            "- `a/one.py`\n"
            "- `b/two.mjs` (+ its test, `b/tests/two.test.mjs`)\n\n"
            f"{lint.ROSTER_END_MARKER}\n\n"
            "trailing prose with `c/three.py` which must NOT be picked up\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, body)
            with _patched_roots(root):
                paths, findings = lint.protected_core_files()
            self.assertEqual(findings, [])
            self.assertEqual(paths, ["a/one.py", "b/two.mjs", "b/tests/two.test.mjs"])

    def test_non_path_backticks_in_region_are_ignored(self) -> None:
        body = (
            f"{lint.ROSTER_BEGIN_MARKER}\n"
            "- `a/one.py` — see `PROTECTED_CORE_FILES` and PR `#242`, dir `a/b/`\n"
            f"{lint.ROSTER_END_MARKER}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, body)
            with _patched_roots(root):
                paths, findings = lint.protected_core_files()
            self.assertEqual(findings, [])
            self.assertEqual(paths, ["a/one.py"])

    def test_duplicate_path_is_collapsed(self) -> None:
        body = f"{lint.ROSTER_BEGIN_MARKER}\n- `a/one.py`\n- `a/one.py`\n{lint.ROSTER_END_MARKER}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, body)
            with _patched_roots(root):
                paths, _ = lint.protected_core_files()
            self.assertEqual(paths, ["a/one.py"])

    def test_missing_markers_is_a_hard_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, "## 2. Protected core\n\n- `a/one.py`\n")
            with _patched_roots(root):
                paths, findings = lint.protected_core_files()
            self.assertEqual(paths, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("markers", findings[0])

    def test_markers_out_of_order_is_a_hard_finding(self) -> None:
        body = f"{lint.ROSTER_END_MARKER}\n- `a/one.py`\n{lint.ROSTER_BEGIN_MARKER}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, body)
            with _patched_roots(root):
                paths, findings = lint.protected_core_files()
            self.assertEqual(paths, [])
            self.assertEqual(len(findings), 1)

    def test_empty_region_is_a_hard_finding(self) -> None:
        body = f"{lint.ROSTER_BEGIN_MARKER}\n\n(nothing here yet)\n\n{lint.ROSTER_END_MARKER}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._doc(tmp, body)
            with _patched_roots(root):
                paths, findings = lint.protected_core_files()
            self.assertEqual(paths, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("checks nothing", findings[0])

    def test_missing_policy_doc_is_a_hard_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patched_roots(Path(tmp)):
                paths, findings = lint.protected_core_files()
            self.assertEqual(paths, [])
            self.assertEqual(len(findings), 1)
            self.assertIn("policy doc", findings[0])


class TestRealRepoIsClean(unittest.TestCase):
    def test_real_roster_derives_without_findings(self) -> None:
        paths, findings = lint.protected_core_files()
        self.assertEqual(findings, [], f"roster derivation failed: {findings}")
        self.assertTrue(paths)

    def test_real_protected_core_files_are_clean(self) -> None:
        paths, all_findings = lint.protected_core_files()
        for rel_path in paths:
            all_findings.extend(lint.check_file(rel_path))
        self.assertEqual(all_findings, [], f"real repo protected core has findings: {all_findings}")

    def test_every_protected_core_file_exists(self) -> None:
        paths, _ = lint.protected_core_files()
        for rel_path in paths:
            self.assertTrue((REPO_ROOT / rel_path).is_file(), f"{rel_path} does not exist")

    def test_decrypt_tool_is_on_the_real_roster(self) -> None:
        """The specific regression this rewrite closed: both decrypt-tool
        paths are declared protected core by the policy and were absent
        from the CI list for the entire life of PR #242 on master."""
        paths, _ = lint.protected_core_files()
        self.assertIn("decrypt-saved-deck-export/decrypt.mjs", paths)
        self.assertIn("decrypt-saved-deck-export/tests/decrypt.test.mjs", paths)

    def test_federation_hash_tool_test_is_on_the_real_roster(self) -> None:
        """`(+ its test)` used to be a prose parenthetical the machine could
        not read; the doc now spells the path out."""
        paths, _ = lint.protected_core_files()
        self.assertIn("federation-hash-tool/tests/test_hash_my_cards.py", paths)


if __name__ == "__main__":
    unittest.main()
