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


class TestAgainstRealRepo(unittest.TestCase):
    """Invariants against the committed docs/ tree, post de-lettering sweep."""

    def test_no_central_register_file(self):
        self.assertFalse((docs_lint.DOCS_DIR / "decisions-register.md").exists())

    def test_search_operator_syntax_is_not_orphan(self):
        orphans = [m for _f, _l, m in docs_lint.check_orphans()]
        self.assertFalse(any("search-operator-syntax.md" in m for m in orphans), orphans)

    def test_proposal_crossrefs_clean(self):
        self.assertEqual(docs_lint.check_proposal_crossrefs(), [])

    def test_merged_corpus_is_fully_clean(self):
        # Sweep landed: no D-number labels, no orphans, no dangling
        # supersessions, no cross-ref gaps. Soft AND strict both exit 0.
        self.assertEqual(docs_lint.main([]), 0)
        self.assertEqual(docs_lint.main(["--strict"]), 0)


if __name__ == "__main__":
    unittest.main()
