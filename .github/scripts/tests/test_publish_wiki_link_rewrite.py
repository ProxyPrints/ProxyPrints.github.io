"""
Parity fixture test: publish_wiki.py's transform_links against the shared
link-rewrite fixture set in .github/scripts/testdata/link_rewrite/.

See that directory's cases.json for the shared-contract rationale (what's
genuinely identical between publish_wiki.py's wiki-only resolution and
generate-docs-site.js's wiki/site/blob 3-way resolution, and what's
expected to diverge, e.g. a wiki-only target's link format) and
frontend/scripts/generate-docs-site.test.js for the JS counterpart running
the SAME cases against the SAME fixture repo. Any edge-case fix to either
implementation's link parsing/resolution should update cases.json, so a
future silent divergence between the two becomes a failing test here
instead - the mechanical tether docs/lessons.md's federation-hash-tool
parity entry already established the precedent for.

Run: python3 .github/scripts/tests/test_publish_wiki_link_rewrite.py
"""

import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import publish_wiki  # noqa: E402

FIXTURE_DIR = SCRIPTS_DIR / "testdata" / "link_rewrite"
FIXTURE_REPO_ROOT = FIXTURE_DIR / "fixture_repo"


def load_cases() -> list[dict]:
    with open(FIXTURE_DIR / "cases.json") as f:
        return json.load(f)["cases"]


def load_repo_to_wiki() -> dict:
    with open(FIXTURE_DIR / "map.json") as f:
        mapping = json.load(f)
    return publish_wiki.build_repo_to_wiki_map(mapping)


class TestLinkRewriteParity(unittest.TestCase):
    def test_every_fixture_case(self) -> None:
        repo_to_wiki = load_repo_to_wiki()
        cases = load_cases()
        self.assertGreater(len(cases), 0, "fixture set is empty - nothing to test")

        for case in cases:
            with self.subTest(case=case["name"]):
                errors: list[str] = []
                actual = publish_wiki.transform_links(
                    FIXTURE_REPO_ROOT,
                    case["sourcePath"],
                    case["input"],
                    repo_to_wiki,
                    errors,
                )
                expected = case.get("expected", case.get("pythonExpected"))
                self.assertIsNotNone(
                    expected,
                    f"case {case['name']!r} has neither 'expected' nor 'pythonExpected' - " "fixture data is malformed",
                )
                self.assertEqual(actual, expected, f"case: {case['name']}")

                if case.get("expectError"):
                    self.assertTrue(
                        errors,
                        f"case {case['name']!r} is marked expectError but no error was recorded",
                    )
                else:
                    self.assertFalse(
                        errors,
                        f"case {case['name']!r} recorded unexpected error(s): {errors}",
                    )

    def test_site_only_page_does_not_crash_the_wiki_map_build(self) -> None:
        """
        Regression guard for the bug this fixture set found while being
        built: build_repo_to_wiki_map used to do page["wiki"] unconditionally,
        which KeyErrors the moment any page in the mapping is site-only (no
        "wiki" key at all) - map.json's docs/site-only-doc.md entry exercises
        exactly this. If this test fails, the fix in build_repo_to_wiki_map
        (page.get("wiki") + filtering falsy values) has regressed.
        """
        with open(FIXTURE_DIR / "map.json") as f:
            mapping = json.load(f)
        repo_to_wiki = publish_wiki.build_repo_to_wiki_map(mapping)
        self.assertNotIn("docs/site-only-doc.md", repo_to_wiki)


if __name__ == "__main__":
    unittest.main()
