"""
Unit tests for check_worker_agent_model.py — issue #180.

Proves the lint actually catches a dropped/altered `model:` line (not
just "passes against the real repo, trust us"), via fixture text, and
separately confirms the real repo's four worker-*.md files are clean
today — the property the worker-agent-model-lint workflow enforces on
every PR touching .claude/agents/**.

Run: python3 .github/scripts/tests/test_check_worker_agent_model.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import check_worker_agent_model as lint  # noqa: E402


class TestExtractFrontmatter(unittest.TestCase):
    def test_extracts_span_between_delimiters(self) -> None:
        text = "---\nname: worker-x\nmodel: sonnet\n---\nbody text\n"
        self.assertEqual(lint.extract_frontmatter(text), "name: worker-x\nmodel: sonnet")

    def test_no_leading_delimiter_returns_none(self) -> None:
        self.assertIsNone(lint.extract_frontmatter("name: worker-x\nmodel: sonnet\n"))

    def test_unterminated_frontmatter_returns_none(self) -> None:
        self.assertIsNone(lint.extract_frontmatter("---\nname: worker-x\nmodel: sonnet\n"))


class TestFrontmatterModel(unittest.TestCase):
    def test_finds_model_key(self) -> None:
        self.assertEqual(lint.frontmatter_model("name: x\nmodel: sonnet\ntools: Bash"), "sonnet")

    def test_tolerates_extra_whitespace(self) -> None:
        self.assertEqual(lint.frontmatter_model("model:   sonnet  "), "sonnet")

    def test_missing_key_returns_none(self) -> None:
        self.assertIsNone(lint.frontmatter_model("name: x\ntools: Bash"))

    def test_commented_out_line_does_not_count(self) -> None:
        self.assertIsNone(lint.frontmatter_model("name: x\n# model: sonnet\ntools: Bash"))

    def test_different_model_value_is_captured_not_ignored(self) -> None:
        self.assertEqual(lint.frontmatter_model("model: opus"), "opus")


class TestCheckFile(unittest.TestCase):
    def _write(self, tmp: str, name: str, text: str) -> Path:
        path = Path(tmp) / name
        path.write_text(text)
        return path

    def test_clean_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "worker-x.md", "---\nname: worker-x\nmodel: sonnet\n---\nbody\n")
            # check_file() computes rel = path.relative_to(REPO_ROOT); swap
            # REPO_ROOT briefly so the fixture (outside the repo tree)
            # resolves without raising ValueError.
            orig_root = lint.REPO_ROOT
            lint.REPO_ROOT = Path(tmp)
            try:
                self.assertEqual(lint.check_file(path), [])
            finally:
                lint.REPO_ROOT = orig_root

    def test_missing_model_key_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "worker-x.md", "---\nname: worker-x\ntools: Bash\n---\nbody\n")
            orig_root = lint.REPO_ROOT
            lint.REPO_ROOT = Path(tmp)
            try:
                findings = lint.check_file(path)
            finally:
                lint.REPO_ROOT = orig_root
            self.assertEqual(len(findings), 1)
            self.assertIn("no `model:` key", findings[0])

    def test_wrong_model_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "worker-x.md", "---\nname: worker-x\nmodel: opus\n---\nbody\n")
            orig_root = lint.REPO_ROOT
            lint.REPO_ROOT = Path(tmp)
            try:
                findings = lint.check_file(path)
            finally:
                lint.REPO_ROOT = orig_root
            self.assertEqual(len(findings), 1)
            self.assertIn("model: opus", findings[0])

    def test_no_frontmatter_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "worker-x.md", "just some text, no frontmatter\n")
            orig_root = lint.REPO_ROOT
            lint.REPO_ROOT = Path(tmp)
            try:
                findings = lint.check_file(path)
            finally:
                lint.REPO_ROOT = orig_root
            self.assertEqual(len(findings), 1)
            self.assertIn("no YAML frontmatter", findings[0])


class TestRealRepoIsClean(unittest.TestCase):
    def test_real_worker_files_pass(self) -> None:
        self.assertEqual(lint.main(), 0)


if __name__ == "__main__":
    unittest.main()
