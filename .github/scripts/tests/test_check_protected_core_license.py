"""
Unit tests for check_protected_core_license.py, per
docs/upstreaming/license-provenance.md §2. Proves the lint actually
catches a violation (not just "passes with zero findings against the
real repo, trust us") via a real fixture case in a scratch directory,
and separately confirms the real repo's own PROTECTED_CORE_FILES list is
clean today - the property docs-lint.yml's protected-core-license job
enforces on every PR.

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


class TestAgplMarkerDetection(unittest.TestCase):
    def test_detects_agpl_provenance_marker(self) -> None:
        self.assertTrue(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, AGPL-3.0\n"))

    def test_gpl_marker_is_not_agpl(self) -> None:
        self.assertFalse(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, GPL-3.0\n"))

    def test_mit_marker_is_not_agpl(self) -> None:
        self.assertFalse(lint.is_agpl_marked("# PROVENANCE: some/repo, v1.2.3, MIT\n"))

    def test_no_marker_at_all(self) -> None:
        self.assertFalse(lint.is_agpl_marked("import os\nimport sys\n"))


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


class TestRealRepoIsClean(unittest.TestCase):
    def test_real_protected_core_files_are_clean(self) -> None:
        all_findings = []
        for rel_path in lint.PROTECTED_CORE_FILES:
            all_findings.extend(lint.check_file(rel_path))
        self.assertEqual(all_findings, [], f"real repo PROTECTED_CORE_FILES has findings: {all_findings}")

    def test_every_protected_core_file_exists(self) -> None:
        for rel_path in lint.PROTECTED_CORE_FILES:
            self.assertTrue((REPO_ROOT / rel_path).is_file(), f"{rel_path} does not exist")


if __name__ == "__main__":
    unittest.main()
