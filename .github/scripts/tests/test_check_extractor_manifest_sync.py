"""
Unit + real-repo tests for check_extractor_manifest_sync.py — the
code-to-code tether between `image_evidence.py`'s `*_EXTRACTOR_VERSION`
constants and `run_image_evidence_cohort.py`'s `MANIFEST_EXTRACTOR_KEYS`
/ `MANIFEST_EXTRACTOR_CURRENT_VERSIONS`.

Conventions follow test_docs_lint.py: fixture tests build a miniature
repo under a redirected REPO_ROOT and exercise each rule's passing AND
failing case; real-repo tests assert the committed tree is clean and,
separately, that the DERIVATION still sees the real constants — the
guard against a tether that passes because it compares nothing to
nothing.

Run: python3 .github/scripts/tests/test_check_extractor_manifest_sync.py
"""

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import check_extractor_manifest_sync as lint  # noqa: E402

SOURCE_OK = '''
"""fixture image_evidence"""
FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v2"
LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"


def compute_card_evidence(card):
    extractor_versions: dict[str, str] = {}
    extractor_versions["fetch_health"] = FETCH_HEALTH_EXTRACTOR_VERSION
    extractor_versions["legal_line"] = LEGAL_LINE_EXTRACTOR_VERSION
    return extractor_versions
'''

COHORT_OK = """
MANIFEST_EXTRACTOR_KEYS = frozenset({"fetch_health", "legal_line"})
MANIFEST_EXTRACTOR_CURRENT_VERSIONS: dict[str, str] = {
    "fetch_health": "fetch-health-v2",
    "legal_line": "legal-line-v1",
}
"""


@contextlib.contextmanager
def fixture_repo(source: str = SOURCE_OK, cohort: str = COHORT_OK):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in ((lint.SOURCE_REL, source), (lint.COHORT_REL, cohort)):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        saved = lint.REPO_ROOT
        lint.REPO_ROOT = root
        try:
            yield root
        finally:
            lint.REPO_ROOT = saved


def joined(findings) -> str:
    return " || ".join(findings)


class TestDerivation(unittest.TestCase):
    def test_derives_key_to_version_map(self):
        with fixture_repo():
            manifest, findings = lint.derive_expected_manifest()
            self.assertEqual(findings, [])
            self.assertEqual(manifest, {"fetch_health": "fetch-health-v2", "legal_line": "legal-line-v1"})

    def test_annotated_assignment_is_read(self):
        # `MANIFEST_EXTRACTOR_CURRENT_VERSIONS: dict[str, str] = {...}` is
        # written with an annotation; an Assign-only walk read it as
        # "missing" and could not check it at all.
        with fixture_repo():
            self.assertEqual(lint.check(), [])

    def test_indented_rebinding_is_not_a_declaration(self):
        source = SOURCE_OK + '\ndef f():\n    OTHER_EXTRACTOR_VERSION = "other-v1"\n'
        with fixture_repo(source=source):
            manifest, findings = lint.derive_expected_manifest()
            self.assertEqual(findings, [])
            self.assertNotIn("other-v1", manifest.values())

    def test_version_shaped_string_in_a_comment_is_not_a_declaration(self):
        # Three retired version strings live in real comments in the source
        # file; a text scan would sweep them in as current values.
        source = SOURCE_OK.replace(
            'FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v2"',
            '# bumped from "fetch-health-v1" on 2026-01-01\nFETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v2"',
        )
        with fixture_repo(source=source):
            self.assertEqual(lint.check(), [])

    def test_empty_derivation_is_a_finding_not_a_pass(self):
        with fixture_repo(source='"""no constants, no assignments"""\n'):
            findings = lint.derive_expected_manifest()[1]
            self.assertEqual(len(findings), 2)
            self.assertIn("vacuously", joined(findings))

    def test_manifest_assigned_from_a_non_constant_is_a_finding(self):
        source = SOURCE_OK.replace(
            'extractor_versions["legal_line"] = LEGAL_LINE_EXTRACTOR_VERSION',
            'extractor_versions["legal_line"] = SOMETHING_ELSE',
        )
        with fixture_repo(source=source):
            self.assertIn("not a module-level", joined(lint.check()))

    def test_declared_but_unmanifested_constant_is_a_finding(self):
        source = SOURCE_OK.replace(
            'LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"',
            'LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"\nORPHAN_EXTRACTOR_VERSION = "orphan-v1"',
        )
        with fixture_repo(source=source):
            out = joined(lint.check())
            self.assertIn("ORPHAN_EXTRACTOR_VERSION", out)
            self.assertIn("never written into", out)

    def test_allowlisted_unmanifested_constant_is_exempt(self):
        source = SOURCE_OK.replace(
            'LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"',
            'LEGAL_LINE_EXTRACTOR_VERSION = "legal-line-v1"\nORPHAN_EXTRACTOR_VERSION = "orphan-v1"',
        )
        saved = lint.UNMANIFESTED_CONSTANT_ALLOWLIST
        lint.UNMANIFESTED_CONSTANT_ALLOWLIST = {"ORPHAN_EXTRACTOR_VERSION": "fixture reason"}
        try:
            with fixture_repo(source=source):
                self.assertEqual(lint.check(), [])
        finally:
            lint.UNMANIFESTED_CONSTANT_ALLOWLIST = saved


class TestSyncFindings(unittest.TestCase):
    def test_in_sync_is_clean(self):
        with fixture_repo():
            self.assertEqual(lint.check(), [])

    def test_stale_version_value_is_flagged(self):
        # The live failure this exists for: the source bumps a version and
        # the resume filter still carries the old string, so stale rows are
        # marked "already done" and never re-extracted.
        cohort = COHORT_OK.replace('"fetch_health": "fetch-health-v2"', '"fetch_health": "fetch-health-v1"')
        with fixture_repo(cohort=cohort):
            out = joined(lint.check())
            self.assertIn("MANIFEST_EXTRACTOR_CURRENT_VERSIONS['fetch_health']", out)
            self.assertIn("'fetch-health-v1'", out)
            self.assertIn("'fetch-health-v2'", out)

    def test_new_extractor_missing_from_keys_is_flagged(self):
        cohort = COHORT_OK.replace('frozenset({"fetch_health", "legal_line"})', 'frozenset({"fetch_health"})')
        with fixture_repo(cohort=cohort):
            out = joined(lint.check())
            self.assertIn("missing manifest key `legal_line`", out)

    def test_key_the_source_never_writes_is_flagged(self):
        cohort = COHORT_OK.replace(
            'frozenset({"fetch_health", "legal_line"})',
            'frozenset({"fetch_health", "legal_line", "color_profile"})',
        )
        with fixture_repo(cohort=cohort):
            out = joined(lint.check())
            self.assertIn("lists manifest key `color_profile`, which", out)
            self.assertIn("never writes", out)

    def test_version_missing_from_the_versions_map_is_flagged(self):
        cohort = COHORT_OK.replace('    "legal_line": "legal-line-v1",\n', "")
        with fixture_repo(cohort=cohort):
            out = joined(lint.check())
            self.assertIn("no entry for", out)
            self.assertIn("legal_line", out)

    def test_the_two_cohort_constants_disagreeing_is_flagged(self):
        # They are consumed by different call sites, so disagreement
        # between them is a live bug independent of the source file.
        cohort = COHORT_OK.replace(
            '    "legal_line": "legal-line-v1",\n',
            '    "legal_line": "legal-line-v1",\n    "ghost": "ghost-v1",\n',
        )
        with fixture_repo(cohort=cohort):
            out = joined(lint.check())
            self.assertIn("disagree with each other", out)

    def test_missing_keys_constant_is_a_finding(self):
        cohort = COHORT_OK.replace("MANIFEST_EXTRACTOR_KEYS", "SOMETHING_ELSE")
        with fixture_repo(cohort=cohort):
            self.assertIn("MANIFEST_EXTRACTOR_KEYS` is missing", joined(lint.check()))

    def test_missing_versions_constant_is_a_finding(self):
        cohort = COHORT_OK.replace("MANIFEST_EXTRACTOR_CURRENT_VERSIONS", "SOMETHING_ELSE")
        with fixture_repo(cohort=cohort):
            self.assertIn("MANIFEST_EXTRACTOR_CURRENT_VERSIONS` is missing", joined(lint.check()))

    def test_missing_source_file_is_a_finding(self):
        with fixture_repo() as root:
            (root / lint.SOURCE_REL).unlink()
            self.assertIn("not found", joined(lint.check()))

    def test_missing_cohort_file_is_a_finding(self):
        with fixture_repo() as root:
            (root / lint.COHORT_REL).unlink()
            self.assertIn("not found", joined(lint.check()))


class TestAgainstRealRepo(unittest.TestCase):
    def test_real_repo_is_in_sync(self):
        self.assertEqual(lint.check(), [], "extractor manifest is out of sync")

    def test_derivation_sees_the_real_extractors(self):
        # The anti-vacuous guard: if the AST walk ever silently stopped
        # matching, check() would compare {} to {} and pass forever.
        manifest, findings = lint.derive_expected_manifest()
        self.assertEqual(findings, [])
        for key in (
            "fetch_health",
            "geometry_bleed",
            "layout_class",
            "crop_coordinates",
            "collector_line_ocr",
            "artist_ocr",
            "collector_line_tsv",
            "artbox_phash",
            "symbol_region",
            "legal_line",
            "quality_signals",
        ):
            self.assertIn(key, manifest)

    def test_every_derived_version_is_version_shaped(self):
        manifest, _ = lint.derive_expected_manifest()
        for key, value in manifest.items():
            self.assertRegex(value, r"^[a-z0-9-]+-v\d+$", f"{key} -> {value!r}")

    def test_main_exits_zero(self):
        self.assertEqual(lint.main(), 0)


if __name__ == "__main__":
    unittest.main()
