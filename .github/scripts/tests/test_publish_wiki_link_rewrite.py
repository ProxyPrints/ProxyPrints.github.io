"""
Parity fixture test for publish_wiki.py's transform_links() - the SINGLE
link-rewrite implementation in this repo (docs/proposals/proposal-i-docs-
as-site-source.md's single-transform architecture: publish_wiki.py owns
this logic for both the wiki (repo_to_site=None) and the site
(publish_site.py, repo_to_site=a real map), and no reimplementation of any
of it exists anywhere else - frontend/ has none).

Runs the shared fixture set in .github/scripts/testdata/link_rewrite/
against BOTH modes of the same function: wiki-publish mode
(repo_to_site=None) and site-emit mode (repo_to_site=the fixture map's
site pages). See that directory's cases.json for the shared-contract
rationale and exactly which cases are expected to diverge between the two
modes (by design - a wiki-only target's link format legitimately differs
depending on whether the reader ends up ON the wiki or on the site) versus
genuinely identical.

Any edge-case fix to transform_links()/rewrite_link() should update
cases.json, so a future silent behavior change becomes a failing test
here instead - the mechanical tether docs/lessons.md's federation-hash-
tool parity entry already established the precedent for.

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


def load_mapping() -> dict:
    with open(FIXTURE_DIR / "map.json") as f:
        return json.load(f)


class TestLinkRewriteParity(unittest.TestCase):
    def _run_case(self, case: dict, repo_to_wiki: dict, repo_to_site: dict | None, mode_key: str) -> None:
        errors: list[str] = []
        actual = publish_wiki.transform_links(
            FIXTURE_REPO_ROOT,
            case["sourcePath"],
            case["input"],
            repo_to_wiki,
            errors,
            repo_to_site=repo_to_site,
        )
        expected = case.get("expected", case.get(mode_key))
        self.assertIsNotNone(
            expected,
            f"case {case['name']!r} has neither 'expected' nor {mode_key!r} - fixture data is malformed",
        )
        self.assertEqual(actual, expected, f"case: {case['name']} ({mode_key})")

        if case.get("expectError"):
            self.assertTrue(
                errors, f"case {case['name']!r} ({mode_key}) is marked expectError but no error was recorded"
            )
        else:
            self.assertFalse(errors, f"case {case['name']!r} ({mode_key}) recorded unexpected error(s): {errors}")

    def test_every_fixture_case_in_wiki_mode(self) -> None:
        mapping = load_mapping()
        repo_to_wiki = publish_wiki.build_repo_to_wiki_map(mapping)
        cases = load_cases()
        self.assertGreater(len(cases), 0, "fixture set is empty - nothing to test")
        for case in cases:
            with self.subTest(case=case["name"], mode="wiki"):
                self._run_case(case, repo_to_wiki, repo_to_site=None, mode_key="wikiModeExpected")

    def test_every_fixture_case_in_site_mode(self) -> None:
        mapping = load_mapping()
        repo_to_wiki = publish_wiki.build_repo_to_wiki_map(mapping)
        repo_to_site = publish_wiki.build_repo_to_site_map(mapping)
        cases = load_cases()
        self.assertGreater(len(cases), 0, "fixture set is empty - nothing to test")
        for case in cases:
            with self.subTest(case=case["name"], mode="site"):
                self._run_case(case, repo_to_wiki, repo_to_site=repo_to_site, mode_key="siteModeExpected")

    def test_site_only_page_does_not_crash_the_wiki_map_build(self) -> None:
        """
        Regression guard for the bug this fixture set found while being
        built: build_repo_to_wiki_map used to do page["wiki"] unconditionally,
        which KeyErrors the moment any page in the mapping is site-only (no
        "wiki" key at all) - map.json's docs/site-only-doc.md entry exercises
        exactly this. If this test fails, the fix in build_repo_to_wiki_map
        (page.get("wiki") + filtering falsy values) has regressed.
        """
        mapping = load_mapping()
        repo_to_wiki = publish_wiki.build_repo_to_wiki_map(mapping)
        self.assertNotIn("docs/site-only-doc.md", repo_to_wiki)

    def test_site_only_page_appears_in_the_site_map(self) -> None:
        mapping = load_mapping()
        repo_to_site = publish_wiki.build_repo_to_site_map(mapping)
        self.assertEqual(repo_to_site.get("docs/site-only-doc.md"), "/guide/site-only")


if __name__ == "__main__":
    unittest.main()
