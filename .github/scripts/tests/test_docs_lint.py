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


class TestRosterScanRecursion(unittest.TestCase):
    """
    `_roster_source_files()` — the scan BOTH roster tethers derive from.

    Until 2026-07-29 both tethers globbed `cardpicker/*.py` non-recursively,
    which silently excluded `management/commands/` and with it
    `scryfall-tagger-v1`, a real vote-casting identity. These tests pin the
    two halves that must BOTH hold: the scan reaches subdirectories, and it
    still excludes `tests/` — which the old glob achieved by accident and
    which now has to hold on purpose.
    """

    @contextlib.contextmanager
    def _repo(self, sources: dict, doc_text: str = "", skip_doc_text: str = ""):
        with temp_docs() as docs:
            src = docs_lint.REPO_ROOT / "MPCAutofill" / "cardpicker"
            src.mkdir(parents=True)
            for name, text in sources.items():
                write(src / name, text)  # `name` may be a nested path
            write(docs / docs_lint.FIDELITY_GATE_DOC_REL, doc_text)
            write(docs / docs_lint.SKIP_REASON_DOC_REL, skip_doc_text)
            yield docs

    def test_identity_in_management_commands_is_found(self):
        # The exact live miss: a management command declaring a real
        # vote-casting identity.
        with self._repo(
            {"management/commands/import_thing.py": 'THING_ANONYMOUS_ID = "thing-importer-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertIn("thing-importer-v1", docs_lint._declared_calculator_identities())
            out = " || ".join(docs_lint.check_calculator_roster_tether())
            self.assertIn("`thing-importer-v1`", out)
            self.assertIn("management/commands/import_thing.py:1", out)

    def test_identity_in_migrations_is_found(self):
        # Deliberately INCLUDED: a migration pinning an identity is
        # operating on real rows keyed by it.
        with self._repo(
            {"migrations/0099_freeze.py": 'COHORT_ANONYMOUS_ID = "frozen-engine-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertIn("frozen-engine-v1", docs_lint._declared_calculator_identities())

    def test_identity_in_tests_is_excluded(self):
        # Deliberately EXCLUDED: fixtures declare identity-shaped literals
        # that are not production roster members. A rule that demanded doc
        # entries for test fixtures would fire on honest content.
        with self._repo(
            {"tests/test_fixtures.py": 'FIXTURE_ANONYMOUS_ID = "some-other-engine-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertEqual(docs_lint._declared_calculator_identities(), {})
            self.assertEqual(docs_lint.check_calculator_roster_tether(), [])

    def test_identity_in_a_nested_tests_dir_is_excluded(self):
        with self._repo(
            {"management/commands/tests/test_cmd.py": 'FIXTURE_ANONYMOUS_ID = "some-other-engine-v1"\n'},
            "this doc mentions no identities at all\n",
        ):
            self.assertEqual(docs_lint._declared_calculator_identities(), {})

    def test_skip_reason_in_a_subdirectory_is_found(self):
        # No `*_SKIP_REASON` lives outside the top level today; this pins
        # the widened scan so the hole stays closed when one does.
        with self._repo(
            {"management/commands/run_thing.py": 'THING_SKIP_REASON = "thing-unavailable"\n'},
            skip_doc_text="this doc documents no reasons\n",
        ):
            self.assertIn("thing-unavailable", docs_lint._declared_skip_reasons())
            out = " || ".join(docs_lint.check_skip_reason_roster_tether())
            self.assertIn("`thing-unavailable`", out)

    def test_skip_reason_in_tests_is_excluded(self):
        with self._repo(
            {"tests/test_thing.py": 'FIXTURE_SKIP_REASON = "fixture-only"\n'},
            skip_doc_text="this doc documents no reasons\n",
        ):
            self.assertEqual(docs_lint._declared_skip_reasons(), {})

    def test_scan_is_recursive_but_bounded(self):
        with self._repo(
            {
                "top.py": "",
                "management/commands/deep.py": "",
                "tests/excluded.py": "",
                "__pycache__/excluded.py": "",
            }
        ):
            src = docs_lint.REPO_ROOT / "MPCAutofill" / "cardpicker"
            names = [str(p.relative_to(src)) for p in docs_lint._roster_source_files(src)]
            self.assertEqual(names, ["management/commands/deep.py", "top.py"])

    def test_missing_source_dir_returns_empty(self):
        with temp_docs():
            self.assertEqual(docs_lint._roster_source_files(docs_lint.REPO_ROOT / "nope"), [])


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
            # `scryfall-tagger-v1` stood here from 2026-07-29 as the one
            # identity declared under `management/commands/` — the subtree the
            # pre-2026-07-29 non-recursive glob never read. It retired together
            # with `PrintingTagVote` on 2026-07-30, and no live identity is
            # declared under `management/commands/` any more, so this list
            # cannot carry a real-repo witness for the recursion. The recursion
            # itself stays covered — on fixtures rather than on the real tree —
            # by `test_scan_is_recursive_but_bounded`, which is the assertion
            # that fails if the scan ever narrows again. If an identity is ever
            # declared under `management/commands/` again, add it here and this
            # list becomes a real-repo witness once more.
        ):
            self.assertIn(identity, found)

    def test_fixture_identities_stay_out_of_the_real_roster(self):
        # The other half of the recursion change: widening the scan must
        # not sweep `cardpicker/tests/` fixture literals into the roster.
        found = docs_lint._declared_calculator_identities()
        for fixture in ("some-other-engine-v1", "unrelated-family-v1", "brand-new-engine-v1"):
            self.assertNotIn(fixture, found)

    def test_merged_corpus_is_fully_clean(self):
        # Sweep landed: no D-number labels, no orphans, no dangling
        # supersessions, no cross-ref gaps. Soft AND strict both exit 0.
        self.assertEqual(docs_lint.main([]), 0)
        self.assertEqual(docs_lint.main(["--strict"]), 0)


if __name__ == "__main__":
    unittest.main()
