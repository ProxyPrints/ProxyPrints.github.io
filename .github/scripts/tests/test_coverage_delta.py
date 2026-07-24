"""
Unit + integration tests for coverage_delta.py (issue #415).

Fixture tests exercise the static parser directly against snippet strings
(no filesystem/git needed). Integration tests build a real scratch git repo
with two commits and drive coverage_delta.run() end to end - this is also
where the two "prove it" synthetic cases from the issue (a removed title,
a new skip) live as permanent regression coverage, not just a one-off local
demo.

Run: python3 .github/scripts/tests/test_coverage_delta.py
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import coverage_delta as cd  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parents[1]


def entries(source: str, file_rel: str = "frontend/tests/Fixture.spec.ts"):
    return cd.parse_file(source, file_rel)


def by_title(source: str, title: str, file_rel: str = "frontend/tests/Fixture.spec.ts"):
    for e in entries(source, file_rel):
        if e.title == title:
            return e
    raise AssertionError(
        f"no entry titled {title!r} in parsed source; got {[e.title for e in entries(source, file_rel)]}"
    )


class TestMaskSource(unittest.TestCase):
    def test_same_length_and_newline_positions(self):
        text = 'const a = "x{y}";\n// comment {\nconst b = `t${1}` /* block {}\nspans lines */;\n'
        masked = cd.mask_source(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(text.count("\n"), masked.count("\n"))
        self.assertEqual([i for i, c in enumerate(text) if c == "\n"], [i for i, c in enumerate(masked) if c == "\n"])

    def test_string_content_is_blanked(self):
        masked = cd.mask_source('test("has { and ( inside", () => {});')
        self.assertNotIn("{", masked.split("(", 1)[1].split(")", 1)[0])


class TestBasicParsing(unittest.TestCase):
    def test_flat_test_is_active(self):
        e = by_title('test("a plain test", async ({ page }) => {\n  await page.click("x");\n});', "a plain test")
        self.assertFalse(e.skip)
        self.assertIsNone(e.reason)

    def test_describe_nesting_builds_full_title(self):
        src = """
test.describe("outer", () => {
  test.describe("inner", () => {
    test("leaf", async () => {});
  });
});
"""
        e = by_title(src, "outer > inner > leaf")
        self.assertFalse(e.skip)

    def test_dynamic_template_title_is_source_stable(self):
        src = "for (const x of [1,2]) {\n  test(`case ${x}`, async () => {});\n}"
        e = by_title(src, "case ${x}")
        self.assertFalse(e.skip)


class TestSkipDetection(unittest.TestCase):
    def test_file_level_before_each_skips_every_test(self):
        # The #389 incident pattern: a top-level test.beforeEach(testInfo.skip(true, "...")),
        # applied before any test.describe - every test in the file is skipped.
        src = """
test.beforeEach(async ({}, testInfo) => {
  testInfo.skip(true, "route swap - see issue #272");
});

test.describe("group", () => {
  test("a", async () => {});
  test("b", async () => {});
});
"""
        for title in ("group > a", "group > b"):
            e = by_title(src, title)
            self.assertTrue(e.skip, title)
            self.assertIn("issue #272", e.reason)

    def test_describe_scoped_before_each_skips_only_that_describe(self):
        src = """
test.describe("skipped group", () => {
  test.beforeEach(async ({}, testInfo) => {
    testInfo.skip(true, "scoped reason");
  });
  test("a", async () => {});
});
test.describe("active group", () => {
  test("b", async () => {});
});
"""
        self.assertTrue(by_title(src, "skipped group > a").skip)
        self.assertFalse(by_title(src, "active group > b").skip)

    def test_describe_skip_propagates(self):
        src = 'test.describe.skip("group", () => {\n  test("a", async () => {});\n});'
        e = by_title(src, "group > a")
        self.assertTrue(e.skip)

    def test_test_skip_is_individually_skipped(self):
        src = 'test.describe("group", () => {\n  test.skip("a", async () => {});\n  test("b", async () => {});\n});'
        self.assertTrue(by_title(src, "group > a").skip)
        self.assertFalse(by_title(src, "group > b").skip)

    def test_inline_testinfo_skip_in_test_body(self):
        src = """
test("conditional", async ({}, testInfo) => {
  testInfo.skip(true, "inline reason");
});
"""
        e = by_title(src, "conditional")
        self.assertTrue(e.skip)
        self.assertEqual(e.reason, "inline reason")

    def test_unrelated_sibling_test_not_skipped_by_inline_skip(self):
        src = """
test("a", async ({}, testInfo) => {
  testInfo.skip(true, "only a");
});
test("b", async () => {});
"""
        self.assertTrue(by_title(src, "a").skip)
        self.assertFalse(by_title(src, "b").skip)


class TestAcks(unittest.TestCase):
    def test_load_and_exact_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github").mkdir()
            (root / ".github" / "coverage-acks.txt").write_text(
                "# comment line, ignored\n" "coverage-ack: frontend/tests/Foo.spec.ts::a title — reason text\n"
            )
            acks = cd.load_acks(root)
            self.assertEqual(len(acks), 1)
            self.assertIsNotNone(cd.is_acked("frontend/tests/Foo.spec.ts::a title", acks))
            self.assertIsNone(cd.is_acked("frontend/tests/Foo.spec.ts::other title", acks))

    def test_glob_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github").mkdir()
            (root / ".github" / "coverage-acks.txt").write_text(
                "coverage-ack: frontend/tests/Foo.spec.ts::* — whole file swept\n"
            )
            acks = cd.load_acks(root)
            self.assertIsNotNone(cd.is_acked("frontend/tests/Foo.spec.ts::group > leaf", acks))
            self.assertIsNone(cd.is_acked("frontend/tests/Bar.spec.ts::group > leaf", acks))

    def test_malformed_line_is_ignored_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github").mkdir()
            (root / ".github" / "coverage-acks.txt").write_text("coverage-ack: missing the dash reason\n")
            self.assertEqual(cd.load_acks(root), [])


class TestDiffManifests(unittest.TestCase):
    def _entry(self, file, title, skip):
        return cd.TestEntry(file=file, title=title, skip=skip, reason=None, line=1)

    def test_removed_test_is_a_violation(self):
        base = {"f::a": self._entry("f", "a", False)}
        head = {}
        v = cd.diff_manifests(base, head)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].kind, "removed")

    def test_newly_skipped_is_a_violation(self):
        base = {"f::a": self._entry("f", "a", False)}
        head = {"f::a": self._entry("f", "a", True)}
        v = cd.diff_manifests(base, head)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].kind, "newly_skipped")

    def test_new_test_is_fine(self):
        base = {}
        head = {"f::a": self._entry("f", "a", False)}
        self.assertEqual(cd.diff_manifests(base, head), [])

    def test_unskip_is_fine(self):
        base = {"f::a": self._entry("f", "a", True)}
        head = {"f::a": self._entry("f", "a", False)}
        self.assertEqual(cd.diff_manifests(base, head), [])

    def test_unchanged_skip_state_is_fine(self):
        base = {"f::a": self._entry("f", "a", True)}
        head = {"f::a": self._entry("f", "a", True)}
        self.assertEqual(cd.diff_manifests(base, head), [])


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestEndToEndGitIntegration(unittest.TestCase):
    """
    Builds a real scratch git repo (two commits: base, head) and runs
    coverage_delta.run() against it exactly as CI would. This is the
    permanent regression home for the issue's two synthetic proof cases.
    """

    def _init_repo(self, tmp: Path) -> None:
        _git(tmp, "init", "-q")
        _git(tmp, "config", "user.email", "test@example.com")
        _git(tmp, "config", "user.name", "Test")
        _write(
            tmp / "frontend" / "tests" / "Sample.spec.ts",
            'test.describe("group", () => {\n'
            '  test("stays active", async () => {});\n'
            '  test("will be removed", async () => {});\n'
            '  test("will be skipped", async () => {});\n'
            "});\n",
        )
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "base")
        _git(tmp, "branch", "-q", "base-branch")

    def test_clean_when_nothing_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._init_repo(tmp)
            unacked, acked, base_sha = cd.run(tmp, "base-branch")
            self.assertEqual(unacked, [])
            self.assertEqual(acked, [])

    def test_synthetic_case_removed_title_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._init_repo(tmp)
            _write(
                tmp / "frontend" / "tests" / "Sample.spec.ts",
                'test.describe("group", () => {\n'
                '  test("stays active", async () => {});\n'
                '  test("will be skipped", async () => {});\n'
                "});\n",
            )
            unacked, acked, _ = cd.run(tmp, "base-branch")
            kinds = {v.test_id: v.kind for v in unacked}
            self.assertIn("frontend/tests/Sample.spec.ts::group > will be removed", kinds)
            self.assertEqual(kinds["frontend/tests/Sample.spec.ts::group > will be removed"], "removed")

    def test_synthetic_case_new_skip_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._init_repo(tmp)
            _write(
                tmp / "frontend" / "tests" / "Sample.spec.ts",
                'test.describe("group", () => {\n'
                '  test("stays active", async () => {});\n'
                '  test("will be removed", async () => {});\n'
                '  test.skip("will be skipped", async () => {});\n'
                "});\n",
            )
            unacked, acked, _ = cd.run(tmp, "base-branch")
            kinds = {v.test_id: v.kind for v in unacked}
            self.assertEqual(
                kinds["frontend/tests/Sample.spec.ts::group > will be skipped"],
                "newly_skipped",
            )

    def test_ack_token_excuses_both_synthetic_violations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self._init_repo(tmp)
            _write(
                tmp / "frontend" / "tests" / "Sample.spec.ts",
                'test.describe("group", () => {\n'
                '  test("stays active", async () => {});\n'
                '  test.skip("will be skipped", async () => {});\n'
                "});\n",
            )
            _write(
                tmp / ".github" / "coverage-acks.txt",
                "coverage-ack: frontend/tests/Sample.spec.ts::* — synthetic test-file cleanup, see PR #999\n",
            )
            unacked, acked, _ = cd.run(tmp, "base-branch")
            self.assertEqual(unacked, [])
            self.assertEqual(len(acked), 2)  # removed title + newly-skipped title, both acked


class TestRealRepoSmoke(unittest.TestCase):
    """Sanity checks against this repo's own frontend/tests/ - not a diff
    (no base ref assumed reachable in every CI checkout), just confirms the
    parser produces a sane, non-empty manifest with the #389/#272 skip
    pattern actually detected."""

    def test_real_manifest_is_non_empty_and_has_known_skips(self):
        manifest = cd.build_manifest_from_worktree(REPO_ROOT)
        self.assertGreater(len(manifest), 100)
        skipped_files = {e.file for e in manifest.values() if e.skip}
        # PDFGenerator.spec.ts/PagePreview.spec.ts/PostExportContributionPrompt.spec.ts were
        # un-skipped by the 2026-07-24 parked-spec port wave (issue #272) - CardImageStates.spec.ts
        # is still fully skipped pending its own port, so it's the fixture here now.
        self.assertIn("frontend/tests/CardImageStates.spec.ts", skipped_files)

    def test_perf_dir_is_excluded(self):
        manifest = cd.build_manifest_from_worktree(REPO_ROOT)
        self.assertFalse(any("/perf/" in e.file for e in manifest.values()))


if __name__ == "__main__":
    unittest.main()
