"""
Unit + real-repo tests for docs_lint.py's interconnection rules.

Model (post-2026-07-23, PR #357): decisions live written-out in prose in
their subject doc; the D-number decision-label convention is abolished
(structural enumerations like funnel steps F, requirements R, test
scenarios T, editor items E, file-change rows XF are a DIFFERENT, kept
convention and are not decision labels). The lint enforces: no new
D-number decision labels, index-chain reachability, supersession pointers
(anywhere in the marker's paragraph), and same-subject proposal
cross-references.

Fixture tests point the module's DOCS_DIR / REPO_ROOT globals at a temp
tree and exercise each rule's passing AND failing case. Real-repo tests
assert the merged corpus is fully clean (both soft and strict) — the
de-lettering sweep has landed.

Run: python3 .github/scripts/tests/test_docs_lint.py
"""

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import docs_lint  # noqa: E402


@contextlib.contextmanager
def temp_docs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        docs = root / "docs"
        docs.mkdir()
        saved = (docs_lint.REPO_ROOT, docs_lint.DOCS_DIR)
        docs_lint.REPO_ROOT = root
        docs_lint.DOCS_DIR = docs
        try:
            yield docs
        finally:
            (docs_lint.REPO_ROOT, docs_lint.DOCS_DIR) = saved


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def msgs(findings):
    return " || ".join(m for _f, _l, m in findings)


class TestNoDNumberLabels(unittest.TestCase):
    def test_bold_d_number_label_is_flagged(self):
        with temp_docs() as docs:
            write(docs / "a.md", "- **D25 — a brand new decision** we just made.\n")
            out = msgs(docs_lint.check_no_letter_labels())
            self.assertIn("D-number decision label `D25`", out)

    def test_decision_word_form_is_flagged(self):
        with temp_docs() as docs:
            write(docs / "a.md", "This follows decision D5 from before.\n")
            self.assertIn("`D5`", msgs(docs_lint.check_no_letter_labels()))

    def test_vw_decision_label_is_flagged(self):
        with temp_docs() as docs:
            write(docs / "a.md", "See **VW-3** in the vote-weight matrix.\n")
            self.assertIn("`VW-3`", msgs(docs_lint.check_no_letter_labels()))

    def test_kept_enumeration_labels_not_flagged(self):
        # Funnel steps / requirements / scenarios / editor items / file rows
        # are a separate, KEPT convention — never decision labels.
        with temp_docs() as docs:
            write(
                docs / "a.md",
                "- **F5 — funnel step**\n- **R3 requirement**\n"
                "- **T1 scenario**\n- **E9 editor item**\n- **XF2 file row**\n",
            )
            self.assertEqual(docs_lint.check_no_letter_labels(), [])

    def test_license_and_pr_tokens_not_flagged(self):
        with temp_docs() as docs:
            write(docs / "a.md", "Licensed **GPL-3.0**; shipped in **PR-5** last week.\n")
            self.assertEqual(docs_lint.check_no_letter_labels(), [])

    def test_historical_aside_is_allowed(self):
        with temp_docs() as docs:
            write(docs / "a.md", "The landscape default (formerly **D1**) is written out below.\n")
            self.assertEqual(docs_lint.check_no_letter_labels(), [])

    def test_plain_prose_without_labels_is_clean(self):
        with temp_docs() as docs:
            write(docs / "a.md", "We landed on landscape as the default and wrote it up here.\n")
            self.assertEqual(docs_lint.check_no_letter_labels(), [])

    def test_reports_archive_is_exempt(self):
        with temp_docs() as docs:
            write(docs / "reports" / "r.md", "- **D14 — old decision** as it stood then.\n")
            self.assertEqual(docs_lint.check_no_letter_labels(), [])

    def test_verbatim_decision_record_doc_is_exempt(self):
        with temp_docs() as docs:
            write(docs / "reference" / "funnel-spec.md", "- **D20 — implicit support** ...\n")
            self.assertEqual(docs_lint.check_no_letter_labels(), [])


class TestOrphanCheck(unittest.TestCase):
    def _index(self, docs, body):
        write(docs / "README.md", body)
        write(docs / "MANIFEST.md", "# routing map\n")

    def test_unreachable_doc_is_flagged(self):
        with temp_docs() as docs:
            self._index(docs, "See [a](a.md).\n")
            write(docs / "a.md", "reachable\n")
            write(docs / "b.md", "orphan\n")
            out = msgs(docs_lint.check_orphans())
            self.assertIn("orphan doc: b.md", out)
            self.assertNotIn("orphan doc: a.md", out)

    def test_transitive_reachability(self):
        with temp_docs() as docs:
            self._index(docs, "See [a](a.md).\n")
            write(docs / "a.md", "onward to [b](b.md)\n")
            write(docs / "b.md", "reached via a\n")
            self.assertNotIn("orphan doc: b.md", msgs(docs_lint.check_orphans()))

    def test_backtick_path_counts_as_reachability_edge(self):
        with temp_docs() as docs:
            write(docs / "README.md", "nothing linked here\n")
            write(docs / "MANIFEST.md", "row: `feat/x.md` governs stuff\n")
            write(docs / "feat" / "x.md", "reached via MANIFEST backtick path\n")
            self.assertNotIn("orphan doc: feat/x.md", msgs(docs_lint.check_orphans()))

    def test_archive_buckets_excluded(self):
        with temp_docs() as docs:
            self._index(docs, "nothing\n")
            write(docs / "reports" / "r.md", "dated report, own convention\n")
            write(docs / "data" / "d.md", "data record\n")
            self.assertEqual(docs_lint.check_orphans(), [])


class TestManifestCoverage(unittest.TestCase):
    """
    MANIFEST.md coverage. Distinct from the orphan rule on purpose: the
    orphan rule asks "is this doc REACHABLE", and every doc in the corpus
    is, because docs cross-link freely. A doc reachable only through a
    see-also link in a sibling is reachable and unroutable at the same
    time, which is why the orphan rule passed on all eight real docs that
    had no MANIFEST row.
    """

    TABLE = "| path | purpose | surface | authority |\n| --- | --- | --- | --- |\n"

    def _manifest(self, docs, rows: str):
        write(docs / "MANIFEST.md", self.TABLE + rows)
        write(docs / "README.md", "index\n")

    def test_doc_without_a_row_is_flagged(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `a.md` | does a | a-work | BINDING |\n")
            write(docs / "a.md", "covered\n")
            write(docs / "b.md", "not covered\n")
            out = msgs(docs_lint.check_manifest_coverage())
            self.assertIn("MANIFEST.md coverage gap: b.md", out)
            self.assertNotIn("coverage gap: a.md", out)

    def test_nested_doc_without_a_row_is_flagged(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `a.md` | does a | a-work | BINDING |\n")
            write(docs / "features" / "deep.md", "no row\n")
            self.assertIn("coverage gap: features/deep.md", msgs(docs_lint.check_manifest_coverage()))

    def test_directory_row_covers_everything_beneath_it(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `reports/` | dated records | none | historical |\n")
            write(docs / "reports" / "r.md", "covered by the directory row\n")
            write(docs / "reports" / "nested" / "deep.md", "also covered\n")
            self.assertEqual(docs_lint.check_manifest_coverage(), [])

    def test_directory_row_does_not_cover_a_sibling_prefix(self):
        # `report/` must not be satisfied by a `reports/` row, and vice
        # versa — a prefix match on the raw string without the trailing
        # slash would conflate them.
        with temp_docs() as docs:
            self._manifest(docs, "| `reports/` | dated records | none | historical |\n")
            write(docs / "reports-archive" / "r.md", "different directory\n")
            self.assertIn("coverage gap: reports-archive/r.md", msgs(docs_lint.check_manifest_coverage()))

    def test_row_pointing_at_a_deleted_file_is_flagged(self):
        # NOT covered by the generic backtick-path check, which skips any
        # candidate without a "/" — so a top-level row was never verified.
        with temp_docs() as docs:
            self._manifest(docs, "| `gone.md` | deleted last month | nothing | BINDING |\n")
            out = msgs(docs_lint.check_manifest_coverage())
            self.assertIn("row `gone.md` does not resolve", out)
            self.assertIn("file", out)

    def test_row_pointing_at_a_deleted_directory_is_flagged(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `gone/` | deleted bucket | nothing | historical |\n")
            self.assertIn("does not resolve to a real directory", msgs(docs_lint.check_manifest_coverage()))

    def test_index_roots_are_allowlisted(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `a.md` | does a | a-work | BINDING |\n")
            write(docs / "a.md", "covered\n")
            out = msgs(docs_lint.check_manifest_coverage())
            self.assertNotIn("README.md", out)
            self.assertNotIn("coverage gap: MANIFEST.md", out)

    def test_allowlisted_doc_is_exempt(self):
        saved = docs_lint.MANIFEST_COVERAGE_ALLOWLIST
        docs_lint.MANIFEST_COVERAGE_ALLOWLIST = {**saved, "b.md": "fixture reason"}
        try:
            with temp_docs() as docs:
                self._manifest(docs, "| `a.md` | does a | a-work | BINDING |\n")
                write(docs / "a.md", "covered\n")
                write(docs / "b.md", "allowlisted\n")
                self.assertEqual(docs_lint.check_manifest_coverage(), [])
        finally:
            docs_lint.MANIFEST_COVERAGE_ALLOWLIST = saved

    def test_header_separator_row_is_not_a_path(self):
        with temp_docs() as docs:
            self._manifest(docs, "| `a.md` | does a | a-work | BINDING |\n")
            write(docs / "a.md", "covered\n")
            self.assertEqual(docs_lint.check_manifest_coverage(), [])

    def test_row_in_a_fenced_block_is_not_a_row(self):
        with temp_docs() as docs:
            write(docs / "README.md", "index\n")
            write(
                docs / "MANIFEST.md",
                self.TABLE
                + "| `a.md` | does a | a-work | BINDING |\n\n"
                + "```\n| `illustrative.md` | example only | none | BINDING |\n```\n",
            )
            write(docs / "a.md", "covered\n")
            # `illustrative.md` does not exist; if the fenced example were
            # read as a row this would report an unresolvable row.
            self.assertEqual(docs_lint.check_manifest_coverage(), [])

    def test_unparseable_manifest_is_a_finding_not_a_pass(self):
        with temp_docs() as docs:
            write(docs / "MANIFEST.md", "# routing map\n\nno table at all\n")
            write(docs / "README.md", "index\n")
            write(docs / "a.md", "would be uncovered\n")
            out = msgs(docs_lint.check_manifest_coverage())
            self.assertIn("no readable table rows", out)

    def test_missing_manifest_is_not_a_finding(self):
        # Same defensive shape as the tether rules: a missing doc is the
        # path-existence check's business, not this rule's.
        with temp_docs() as docs:
            write(docs / "a.md", "no manifest exists\n")
            self.assertEqual(docs_lint.check_manifest_coverage(), [])


class TestSupersession(unittest.TestCase):
    def test_marker_without_pointer_is_flagged(self):
        with temp_docs() as docs:
            write(docs / "a.md", "This section is SUPERSEDED.\nJust more prose here.\n")
            self.assertIn("SUPERSEDED marker without a pointer", msgs(docs_lint.check_supersession()))

    def test_marker_with_link_is_clean(self):
        with temp_docs() as docs:
            write(docs / "a.md", "SUPERSEDED by [the new spec](new.md).\n")
            self.assertEqual(docs_lint.check_supersession(), [])

    def test_pointer_elsewhere_in_same_paragraph_is_clean(self):
        # A multi-line HISTORICAL banner: the marker is on line 1, the
        # pointer link a few lines down in the SAME paragraph/blockquote.
        with temp_docs() as docs:
            write(
                docs / "a.md",
                "> **HISTORICAL — SUPERSEDED.** This was the original draft.\n"
                "> The content predates the newer layout, and\n"
                "> [`new-spec.md`](new-spec.md) is the living spec now.\n",
            )
            self.assertEqual(docs_lint.check_supersession(), [])

    def test_pointer_in_next_paragraph_is_clean(self):
        with temp_docs() as docs:
            write(docs / "a.md", "### 4.4 switch — SUPERSEDED\n\nSuperseded by §4.4 below.\n")
            self.assertEqual(docs_lint.check_supersession(), [])

    def test_compound_status_is_self_pointing(self):
        with temp_docs() as docs:
            write(docs / "a.md", "task closed SUPERSEDED-BY-POSTURE, no R2.\n")
            self.assertEqual(docs_lint.check_supersession(), [])

    def test_allowlisted_backreference_is_ignored(self):
        with temp_docs() as docs:
            write(docs / "a.md", 'see the two "SUPERSEDED" notes above for context.\n')
            self.assertEqual(docs_lint.check_supersession(), [])


class TestProposalCrossrefs(unittest.TestCase):
    def test_same_subject_without_crossref_warns(self):
        with temp_docs() as docs:
            write(docs / "proposals" / "proposal-h-one.md", "spec one\n")
            write(docs / "proposals" / "proposal-h-two.md", "spec two\n")
            self.assertIn("both cover subject 'proposal-h'", msgs(docs_lint.check_proposal_crossrefs()))

    def test_one_directional_reference_is_enough(self):
        with temp_docs() as docs:
            write(docs / "proposals" / "proposal-h-one.md", "see proposal-h-two.md\n")
            write(docs / "proposals" / "proposal-h-two.md", "spec two\n")
            self.assertEqual(docs_lint.check_proposal_crossrefs(), [])

    def test_different_subjects_are_independent(self):
        with temp_docs() as docs:
            write(docs / "proposals" / "proposal-h-one.md", "spec\n")
            write(docs / "proposals" / "proposal-g-two.md", "spec\n")
            self.assertEqual(docs_lint.check_proposal_crossrefs(), [])


class TestCalculatorRosterTether(unittest.TestCase):
    """
    The roster tether: every `*_ANONYMOUS_ID` declared in
    MPCAutofill/cardpicker/*.py must have an entry in
    docs/pipeline-fidelity-gate.md. Fixture tests build a miniature
    repo (a cardpicker source dir + the doc) under temp_docs()'s
    redirected REPO_ROOT/DOCS_DIR.
    """

    @contextlib.contextmanager
    def _repo(self, sources: dict, doc_text: str):
        """sources: {filename: python source}; doc_text: fidelity-gate doc body."""
        with temp_docs() as docs:
            src = docs_lint.REPO_ROOT / "MPCAutofill" / "cardpicker"
            src.mkdir(parents=True)
            for name, text in sources.items():
                write(src / name, text)
            write(docs / docs_lint.FIDELITY_GATE_DOC_REL, doc_text)
            yield docs

    def test_undocumented_identity_is_flagged(self):
        with self._repo(
            {"local_thing.py": 'THING_ANONYMOUS_ID = "local-thing-v1"\n'},
            "| `local-other-v1` | 5 |\n",
        ):
            out = " || ".join(docs_lint.check_calculator_roster_tether())
            self.assertIn("calculator roster drift", out)
            self.assertIn("`local-thing-v1`", out)
            self.assertIn("local_thing.py:1", out)

    def test_documented_identity_is_clean(self):
        with self._repo(
            {"local_thing.py": 'THING_ANONYMOUS_ID = "local-thing-v1"\n'},
            "- **`local-thing-v1`** (5 rows) — does a thing. DORMANT.\n",
        ):
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_roster_is_derived_from_code_not_hardcoded(self):
        # A brand-new calculator nobody has documented yet must fail on the
        # day it's declared — that is the whole point of deriving the list.
        with self._repo(
            {"local_new.py": 'BRAND_NEW_ANONYMOUS_ID = "brand-new-engine-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertIn("`brand-new-engine-v1`", " || ".join(docs_lint.check_calculator_roster_tether()))

    def test_allowlisted_non_calculator_is_exempt(self):
        with self._repo(
            {"evidence_transfer.py": 'EVIDENCE_TRANSFER_ANONYMOUS_ID = "evidence-transfer-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_version_bump_is_not_satisfied_by_the_old_entry(self):
        # calculator_family strips `-vN`; the tether deliberately does NOT.
        # A v1 entry must not silently cover a v2 identity.
        with self._repo(
            {"local_thing.py": 'THING_ANONYMOUS_ID = "local-thing-v2"\n'},
            "- **`local-thing-v1`** — the old engine.\n",
        ):
            self.assertIn("`local-thing-v2`", " || ".join(docs_lint.check_calculator_roster_tether()))

    def test_substring_of_another_identity_does_not_satisfy_the_check(self):
        with self._repo(
            {"local_thing.py": 'FALLBACK_ANONYMOUS_ID = "local-fallback-v1"\n'},
            "- **`stage-d-fallback-v1`** — a different engine entirely.\n",
        ):
            self.assertIn("`local-fallback-v1`", " || ".join(docs_lint.check_calculator_roster_tether()))

    def test_version_key_and_fixture_literals_are_not_roster_members(self):
        # Extractor version keys and test-fixture engine names share the
        # `<name>-vN` shape but are not declared as `*_ANONYMOUS_ID`
        # constants — keying on the constant name is what excludes them.
        with self._repo(
            {
                "image_evidence.py": (
                    'COLLECTOR_LINE_VERSION = "collector-line-ocr-v2"\n'
                    'LEGAL_LINE_VERSION = "legal-line-v2"\n'
                    'ARTIST_OCR_VERSION = "artist-ocr-v1"\n'
                    'OTHER_ENGINE = "some-other-engine-v1"\n'
                    'FAMILY = "unrelated-family-v1"\n'
                ),
            },
            "this doc mentions no identities at all\n",
        ):
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_indented_rebinding_is_not_a_declaration(self):
        with self._repo(
            {
                "local_thing.py": (
                    'THING_ANONYMOUS_ID = "local-thing-v1"\n'
                    "def f():\n"
                    '    LOCAL_ANONYMOUS_ID = "not-a-declaration-v1"\n'
                ),
            },
            "- **`local-thing-v1`** — documented.\n",
        ):
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_identity_only_inside_a_fenced_block_is_not_an_entry(self):
        with self._repo(
            {"local_thing.py": 'THING_ANONYMOUS_ID = "local-thing-v1"\n'},
            "some prose\n\n```\nanonymous_id='local-thing-v1'\n```\n",
        ):
            self.assertIn("`local-thing-v1`", " || ".join(docs_lint.check_calculator_roster_tether()))

    def test_missing_doc_is_not_a_finding(self):
        # Same defensive shape as check_extractable_primitives_tether():
        # a missing doc is the path-existence check's business, not this
        # rule's, and must not make the rule explode.
        with temp_docs():
            src = docs_lint.REPO_ROOT / "MPCAutofill" / "cardpicker"
            src.mkdir(parents=True)
            write(src / "local_thing.py", 'THING_ANONYMOUS_ID = "local-thing-v1"\n')
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])


class TestAgainstRealRepo(unittest.TestCase):
    """Invariants against the committed docs/ tree, post de-lettering sweep."""

    def test_no_central_register_file(self):
        self.assertFalse((docs_lint.DOCS_DIR / "decisions-register.md").exists())

    def test_search_operator_syntax_is_not_orphan(self):
        orphans = [m for _f, _l, m in docs_lint.check_orphans()]
        self.assertFalse(any("search-operator-syntax.md" in m for m in orphans), orphans)

    def test_proposal_crossrefs_clean(self):
        self.assertEqual(docs_lint.check_proposal_crossrefs(), [])

    def test_calculator_roster_tether_is_clean(self):
        self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_roster_derivation_sees_the_real_calculators(self):
        # Guards the derivation itself: if the discovery ever silently
        # stopped finding declarations, the tether would pass vacuously —
        # a lint rule that cannot fail. These four include the three
        # identities the fidelity-gate doc omitted until 2026-07-29.
        found = docs_lint._declared_calculator_identities()
        for identity in (
            "local-ocr-v1",
            "stage-d-slow-path-v1",
            # `-v2` since 2026-07-29 (the border-colour gate fix); the roster
            # tether is keyed on the CURRENT identity, version suffix included.
            "stage-d-illustration-v2",
            "local-name-frequency-v1",
        ):
            self.assertIn(identity, found)

    def test_merged_corpus_is_fully_clean(self):
        # Sweep landed: no D-number labels, no orphans, no dangling
        # supersessions, no cross-ref gaps. Soft AND strict both exit 0.
        self.assertEqual(docs_lint.main([]), 0)
        self.assertEqual(docs_lint.main(["--strict"]), 0)


if __name__ == "__main__":
    unittest.main()
