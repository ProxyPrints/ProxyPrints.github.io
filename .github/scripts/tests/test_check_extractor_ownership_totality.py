"""
Unit + real-repo tests for check_extractor_ownership_totality.py — the
code-to-code tether between `image_evidence.py`'s reachable-from-
`compute_card_evidence` call graph and the hand-declared `EXTRACTOR_OWNERSHIP`
map.

Conventions follow test_check_extractor_manifest_sync.py: fixture tests
build a miniature `image_evidence.py` under a redirected REPO_ROOT and
exercise each rule's passing AND failing case; real-repo tests assert the
committed tree is clean and, separately, that the derivation still sees the
real contributors — the guard against a tether that passes because it
compares nothing to nothing.

Run: python3 .github/scripts/tests/test_check_extractor_ownership_totality.py
"""

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import check_extractor_manifest_sync as manifest_sync  # noqa: E402
import check_extractor_ownership_totality as lint  # noqa: E402

# A minimal fixture `image_evidence.py`: one module-private helper
# (`_helper_one`) called from `compute_card_evidence`, one scoped-external
# import (`external_thing`, standing in for e.g. `recover_artist_from_card_text`)
# also called from there, one excluded-ladder helper (`_collector_line_ocr_attempts`)
# whose own internal call (`preprocess_fallback_variants`-analogue,
# `ladder_only_thing`) must NOT be required, and the manifest wiring
# `check_extractor_manifest_sync`'s own derivation needs to find real keys.
SOURCE_OK = '''
"""fixture image_evidence"""
from cardpicker.collector_line_artist import external_thing
from cardpicker.local_ocr import ladder_only_thing

FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v2"
LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"


def _helper_one(x):
    return x


def _collector_line_ocr_attempts(cropped):
    yield ladder_only_thing(cropped)


def compute_card_evidence(card):
    extractor_versions: dict[str, str] = {}
    extractor_versions["fetch_health"] = FETCH_HEALTH_EXTRACTOR_VERSION
    extractor_versions["legal_line"] = LEGAL_LINE_EXTRACTOR_VERSION
    _helper_one(card)
    external_thing(card)
    for _ in _collector_line_ocr_attempts(card):
        pass
    return extractor_versions
'''

COHORT_OK = """
MANIFEST_EXTRACTOR_KEYS = frozenset({"fetch_health", "legal_line"})
MANIFEST_EXTRACTOR_CURRENT_VERSIONS: dict[str, str] = {
    "fetch_health": "fetch-health-v2",
    "legal_line": "legal-line-v1",
}
"""

OWNERSHIP_OK = {
    "_helper_one": frozenset({"fetch_health"}),
    "external_thing": frozenset({"legal_line"}),
}


@contextlib.contextmanager
def fixture_repo(source: str = SOURCE_OK, cohort: str = COHORT_OK, ownership: dict = None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in ((lint.SOURCE_REL, source), (manifest_sync.COHORT_REL, cohort)):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        saved_lint_root = lint.REPO_ROOT
        saved_manifest_root = manifest_sync.REPO_ROOT
        saved_ownership = lint.EXTRACTOR_OWNERSHIP
        lint.REPO_ROOT = root
        manifest_sync.REPO_ROOT = root
        lint.EXTRACTOR_OWNERSHIP = OWNERSHIP_OK if ownership is None else ownership
        try:
            yield root
        finally:
            lint.REPO_ROOT = saved_lint_root
            manifest_sync.REPO_ROOT = saved_manifest_root
            lint.EXTRACTOR_OWNERSHIP = saved_ownership


def joined(findings) -> str:
    return " || ".join(findings)


class TestDerivation(unittest.TestCase):
    def test_derives_private_helper_and_called_external_import(self):
        with fixture_repo():
            contributors, findings = lint.derive_reachable_contributors()
            self.assertEqual(findings, [])
            self.assertEqual(contributors, {"_helper_one", "external_thing"})

    def test_excluded_ladder_function_itself_is_not_a_contributor(self):
        # _collector_line_ocr_attempts is in EXCLUDED_HELPERS by name - it
        # must never itself require an entry.
        with fixture_repo():
            contributors, _ = lint.derive_reachable_contributors()
            self.assertNotIn("_collector_line_ocr_attempts", contributors)

    def test_name_called_only_inside_the_excluded_ladder_is_not_a_contributor(self):
        # ladder_only_thing is a scoped-external import, but its one call
        # site is inside _collector_line_ocr_attempts's own body - excluded
        # per this PR's own brief (that ladder is being worked on in
        # parallel by another branch).
        with fixture_repo():
            contributors, _ = lint.derive_reachable_contributors()
            self.assertNotIn("ladder_only_thing", contributors)

    def test_import_used_only_as_a_type_hint_is_not_a_contributor(self):
        source = SOURCE_OK.replace(
            "from cardpicker.collector_line_artist import external_thing",
            "from cardpicker.collector_line_artist import ArtistLexicon, external_thing",
        ).replace(
            "def compute_card_evidence(card):",
            'def compute_card_evidence(card, lexicon: "ArtistLexicon" = None):',
        )
        with fixture_repo(source=source):
            contributors, _ = lint.derive_reachable_contributors()
            self.assertNotIn("ArtistLexicon", contributors)

    def test_empty_derivation_is_a_finding_not_a_pass(self):
        with fixture_repo(source='"""no helpers, no calls"""\n'):
            contributors, findings = lint.derive_reachable_contributors()
            self.assertEqual(contributors, set())
            self.assertEqual(len(findings), 1)
            self.assertIn("empty derivation is itself the finding", joined(findings))

    def test_missing_source_file_is_a_finding(self):
        with fixture_repo() as root:
            (root / lint.SOURCE_REL).unlink()
            _, findings = lint.derive_reachable_contributors()
            self.assertIn("not found", joined(findings))


class TestTotality(unittest.TestCase):
    def test_fully_declared_is_clean(self):
        with fixture_repo():
            self.assertEqual(lint.check(), [])

    def test_undeclared_new_contributor_fails(self):
        # THE case the brief requires: a newly-added, newly-called
        # module-private helper with no EXTRACTOR_OWNERSHIP entry must fail
        # CI, not merge silently invisible the way the eleven
        # *_EXTRACTOR_VERSION constants used to be able to.
        source = SOURCE_OK.replace(
            "def _helper_one(x):\n    return x\n",
            "def _helper_one(x):\n    return x\n\n\ndef _helper_two_undeclared(x):\n    return x\n",
        ).replace(
            "    _helper_one(card)\n",
            "    _helper_one(card)\n    _helper_two_undeclared(card)\n",
        )
        with fixture_repo(source=source):
            out = joined(lint.check())
            self.assertIn("_helper_two_undeclared", out)
            self.assertIn("no entry in EXTRACTOR_OWNERSHIP", out)

    def test_undeclared_new_external_call_fails(self):
        source = SOURCE_OK.replace(
            "from cardpicker.local_ocr import ladder_only_thing",
            "from cardpicker.local_ocr import ladder_only_thing, undeclared_external",
        ).replace(
            "    external_thing(card)\n",
            "    external_thing(card)\n    undeclared_external(card)\n",
        )
        with fixture_repo(source=source):
            out = joined(lint.check())
            self.assertIn("undeclared_external", out)
            self.assertIn("no entry in EXTRACTOR_OWNERSHIP", out)

    def test_stale_ownership_entry_for_a_removed_contributor_fails(self):
        ownership = dict(OWNERSHIP_OK)
        ownership["_removed_long_ago"] = frozenset({"fetch_health"})
        with fixture_repo(ownership=ownership):
            out = joined(lint.check())
            self.assertIn("_removed_long_ago", out)
            self.assertIn("not reachable", out)

    def test_ownership_entry_naming_a_fake_manifest_key_fails(self):
        ownership = dict(OWNERSHIP_OK)
        ownership["_helper_one"] = frozenset({"not_a_real_key"})
        with fixture_repo(ownership=ownership):
            out = joined(lint.check())
            self.assertIn("not_a_real_key", out)
            self.assertIn("not a real manifest key", out)

    def test_manifest_derivation_failure_propagates(self):
        # If the sibling manifest-sync script's own derivation fails (e.g.
        # no `extractor_versions[...]` assignments in image_evidence.py),
        # that failure must surface here too rather than being swallowed -
        # the owning-key cross-check below it must not run against an
        # empty/unreliable manifest.
        source = SOURCE_OK.replace(
            '    extractor_versions["fetch_health"] = FETCH_HEALTH_EXTRACTOR_VERSION\n'
            '    extractor_versions["legal_line"] = LEGAL_LINE_EXTRACTOR_VERSION\n',
            "",
        )
        with fixture_repo(source=source):
            out = joined(lint.check())
            self.assertIn("no `extractor_versions", out)


class TestAgainstRealRepo(unittest.TestCase):
    def test_real_repo_is_in_sync(self):
        self.assertEqual(lint.check(), [], "extractor ownership map is out of sync")

    def test_derivation_sees_the_real_contributors(self):
        contributors, findings = lint.derive_reachable_contributors()
        self.assertEqual(findings, [])
        for name in (
            "_crop_box_to_pixels",
            "_compute_region_phash",
            "_extract_legal_line",
            "_parse_artist_is_contradicted",
            "_parse_is_lexicon_valid",
            "_confidently_digit_free",
            "recover_artist_from_card_text",
            "compute_blur_variance",
            "compute_entropy",
            "is_image_truncated",
            "parse_collector_line",
            "parse_legal_line",
            "run_tesseract_text_and_words",
        ):
            self.assertIn(name, contributors)

    def test_excluded_ladder_is_really_excluded_in_the_real_module(self):
        contributors, _ = lint.derive_reachable_contributors()
        self.assertNotIn("_collector_line_ocr_attempts", contributors)
        self.assertNotIn("preprocess_fallback_variants", contributors)

    def test_every_declared_owning_key_set_is_non_empty(self):
        for name, keys in lint.EXTRACTOR_OWNERSHIP.items():
            self.assertTrue(keys, f"{name} has an empty owning-key set")

    def test_main_exits_zero(self):
        self.assertEqual(lint.main(), 0)


if __name__ == "__main__":
    unittest.main()
