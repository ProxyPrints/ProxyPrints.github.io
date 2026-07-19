"""
Unit tests for publish_readme.py's region-extraction + assembly logic and
its two hard-error paths (missing source file, missing/unterminated
marker) — same "fail loud, never ship a silently-wrong page" philosophy
publish_wiki.py already uses for broken links.

Also a real-repo integration check: running the script against THIS
repo's actual docs/wiki-home-intro.md + docs/readme-sections.md must
produce output byte-identical to the committed readme.md — the same
parity property docs-lint.yml's readme-parity job enforces on every PR.

Run: python3 .github/scripts/tests/test_publish_readme.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import publish_readme  # noqa: E402


class TestExtractRegion(unittest.TestCase):
    def test_extracts_marked_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text(
                "prose before\n"
                "<!-- README-REGION: greeting -->\n"
                "hello world\n"
                "<!-- END README-REGION -->\n"
                "prose after\n"
            )
            self.assertEqual(publish_readme.extract_region(root, "doc.md", "greeting"), "hello world")

    def test_missing_source_file_is_a_hard_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                publish_readme.extract_region(root, "nope.md", "greeting")

    def test_missing_start_marker_is_a_hard_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text("no markers here\n")
            with self.assertRaises(SystemExit):
                publish_readme.extract_region(root, "doc.md", "greeting")

    def test_unterminated_region_is_a_hard_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text("<!-- README-REGION: greeting -->\nhello\n")
            with self.assertRaises(SystemExit):
                publish_readme.extract_region(root, "doc.md", "greeting")

    def test_unlisted_region_in_same_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text(
                "<!-- README-REGION: wanted -->\nwanted text\n<!-- END README-REGION -->\n"
                "<!-- README-REGION: scratch-example -->\nnever picked up\n<!-- END README-REGION -->\n"
            )
            self.assertEqual(publish_readme.extract_region(root, "doc.md", "wanted"), "wanted text")


class TestBuildReadmeAgainstRealRepo(unittest.TestCase):
    """
    Real docs/wiki-home-intro.md + docs/readme-sections.md, not fixtures —
    this IS the parity check docs-lint.yml's readme-parity job runs.
    """

    def test_build_matches_committed_readme(self) -> None:
        built = publish_readme.build_readme(REPO_ROOT)
        committed = (REPO_ROOT / "readme.md").read_text()
        self.assertEqual(built, committed)

    def test_build_is_idempotent(self) -> None:
        first = publish_readme.build_readme(REPO_ROOT)
        second = publish_readme.build_readme(REPO_ROOT)
        self.assertEqual(first, second)

    def test_no_relative_file_links_in_source_regions(self) -> None:
        """
        Regression guard for the exact bug publish_readme.py's own module
        docstring warns about: a region's relative link would resolve
        correctly if docs_lint.py checked it in place (relative to docs/)
        but silently mean something else once copied verbatim into
        readme.md at the repo root. Every link in a marked region must be
        an absolute http(s) URL.
        """
        for source, names in (
            (publish_readme.IDENTITY_SOURCE, ["identity"]),
            (
                publish_readme.SECTIONS_SOURCE,
                ["license", "license-provenance", "documentation-pointer", "desktop-tool-pointer"],
            ),
        ):
            for name in names:
                region = publish_readme.extract_region(REPO_ROOT, source, name)
                for match in publish_readme_link_targets(region):
                    self.assertTrue(
                        match.startswith(("http://", "https://")),
                        f"region {name!r} in {source} has a non-absolute link target: {match!r}",
                    )


def publish_readme_link_targets(text: str) -> list[str]:
    import re

    return re.findall(r"\]\(([^)]+)\)", text)


if __name__ == "__main__":
    unittest.main()
