"""
Unit + real-repo tests for constant_rename_equivalence.py.

The tool proves a constant-renaming refactor changed no behaviour, by
normalising each module at two revisions (inline matching constants,
delete their declarations/imports/`__all__` entries, delete docstrings,
constant-fold) and comparing `ast.dump()` trees. See that script's
module docstring for the #567/#568 incident that motivated it.

Fixture tests build a throwaway git repo per case with `_repo(...)`:
two commits, `base` and `head`, each a {path: source} dict. The tool is
then invoked through `main()` with `--repo` pointed at it, exactly as a
human would run it. Every rule gets a passing AND a failing case —
INCLUDING cases where a genuine BEHAVIOUR change (not a rename) must be
caught, because a checker that only ever says "identical" is worthless.

Real-repo tests assert the committed tree resolves cleanly and pin the
#567 regression: the real rename commit still normalises identical
across the modules it touched.

Run: python3 .github/scripts/tests/test_constant_rename_equivalence.py
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import constant_rename_equivalence as cre  # noqa: E402

# The real rename commit (PR #567) and its parent. Used by the regression
# tests below; skipped rather than failed if history is unavailable (a
# shallow CI clone, a fork without master's history).
PR_567 = "bc7ad4163fbdefd4b155772fc0cf6e3c5297c1d7"


@contextlib.contextmanager
def _repo(base: dict, head: dict):
    """A two-commit git repo. `base` and `head` are {relative path: source};
    a path present in `base` and absent from `head` is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

        def run(*args):
            subprocess.run(["git", *env, *args], cwd=root, check=True, capture_output=True)

        def write_all(files):
            for existing in root.rglob("*.py"):
                existing.unlink()
            for rel, text in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)

        run("init", "-q", "-b", "master")
        write_all(base)
        run("add", "-A")
        run("commit", "-q", "--no-verify", "-m", "base")
        write_all(head)
        run("add", "-A")
        run("commit", "-q", "--allow-empty", "--no-verify", "-m", "head")
        yield root


def run_tool(root: Path, *args: str) -> tuple[int, str]:
    """Invoke main() the way a human or CI would; return (exit code, stdout)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cre.main(["--repo", str(root), *args])
    return code, buffer.getvalue()


def compare(root: Path, *args: str) -> tuple[int, str]:
    return run_tool(root, "--base", "HEAD~1", "--head", "HEAD", *args)


class TestPureRenameIsProvenEquivalent(unittest.TestCase):
    def test_single_module_rename_is_clean(self):
        base = {"m.py": 'A_SKIP_REASON = "ambiguous"\n\n\ndef f(x):\n    return A_SKIP_REASON if x else ""\n'}
        head = {"m.py": 'A_SKIP_REASON_V2 = "ambiguous"\n\n\ndef f(x):\n    return A_SKIP_REASON_V2 if x else ""\n'}
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)
            self.assertIn("normalise IDENTICALLY", out)

    def test_docstring_rewrite_alone_is_clean(self):
        base = {
            "m.py": '"""Old prose."""\nA_SKIP_REASON = "x"\n\n\ndef f():\n    """Old."""\n    return A_SKIP_REASON\n'
        }
        head = {
            "m.py": '"""Completely rewritten prose, several paragraphs."""\n'
            'B_SKIP_REASON = "x"\n\n\ndef f():\n    """New, longer, different."""\n    return B_SKIP_REASON\n'
        }
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_cross_module_import_rename_is_clean(self):
        base = {
            "a.py": 'TO_REVIEW_REASON = "to-review"\n',
            "b.py": "from a import TO_REVIEW_REASON\n\n\ndef f():\n    return TO_REVIEW_REASON\n",
        }
        head = {
            "a.py": 'TO_REVIEW_SKIP_REASON = "to-review"\n',
            "b.py": "from a import TO_REVIEW_SKIP_REASON\n\n\ndef f():\n    return TO_REVIEW_SKIP_REASON\n",
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)

    def test_all_entry_rename_is_clean(self):
        base = {
            "m.py": 'A_SKIP_REASON = "x"\n__all__ = ["A_SKIP_REASON", "f"]\n\n\ndef f():\n    return A_SKIP_REASON\n'
        }
        head = {
            "m.py": 'B_SKIP_REASON = "x"\n__all__ = ["B_SKIP_REASON", "f"]\n\n\ndef f():\n    return B_SKIP_REASON\n'
        }
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_literal_extracted_into_a_constant_is_clean(self):
        # The constant-EXTRACTION half of the defect class: a bare literal
        # becomes a named constant, with no behaviour change.
        base = {"m.py": 'def f(x):\n    return "no-evidence" if x else ""\n'}
        head = {
            "m.py": 'NO_EVIDENCE_SKIP_REASON = "no-evidence"\n\n\ndef f(x):\n    return NO_EVIDENCE_SKIP_REASON if x else ""\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)


class TestFolding(unittest.TestCase):
    """LANDS_PHASH_SKIP_REASON_PREFIX is why these exist: it ends in
    `_PREFIX`, not `_REASON`, and its value is composed at runtime as
    `f"{PREFIX}{reason}"` — so matching is a search over the whole name, and
    an f-string folder that also folds a SINGLE interpolated constant back
    into the surrounding literal is required."""

    def test_fstring_prefix_extraction_is_clean(self):
        base = {"m.py": 'def f(reason):\n    return f"phash-{reason}"\n'}
        head = {
            "m.py": 'PHASH_SKIP_REASON_PREFIX = "phash-"\n\n\ndef f(reason):\n    return f"{PHASH_SKIP_REASON_PREFIX}{reason}"\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)

    def test_fstring_prefix_change_is_caught(self):
        base = {"m.py": 'def f(reason):\n    return f"phash-{reason}"\n'}
        head = {
            "m.py": 'PHASH_SKIP_REASON_PREFIX = "phash2-"\n\n\ndef f(reason):\n    return f"{PHASH_SKIP_REASON_PREFIX}{reason}"\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 1, out)
            self.assertIn("m.py", out)

    def test_string_concatenation_is_folded(self):
        base = {"m.py": 'def f():\n    return "phash-" + "miss"\n'}
        head = {"m.py": 'PHASH_MISS_SKIP_REASON = "phash-miss"\n\n\ndef f():\n    return PHASH_MISS_SKIP_REASON\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_frozenset_membership_set_rename_is_clean(self):
        base = {
            "m.py": 'A_SKIP_REASON = "a"\nB_SKIP_REASON = "b"\n'
            "RESCANNABLE_SKIP_REASONS = frozenset({A_SKIP_REASON, B_SKIP_REASON})\n\n\n"
            "def f(x):\n    return x in RESCANNABLE_SKIP_REASONS\n"
        }
        head = {
            "m.py": 'A2_SKIP_REASON = "a"\nB2_SKIP_REASON = "b"\n'
            "RESCANNABLE_SET_SKIP_REASONS = frozenset({A2_SKIP_REASON, B2_SKIP_REASON})\n\n\n"
            "def f(x):\n    return x in RESCANNABLE_SET_SKIP_REASONS\n"
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)

    def test_frozenset_membership_change_is_caught(self):
        base = {
            "m.py": 'A_SKIP_REASON = "a"\nB_SKIP_REASON = "b"\n'
            "RESCANNABLE_SKIP_REASONS = frozenset({A_SKIP_REASON, B_SKIP_REASON})\n\n\n"
            "def f(x):\n    return x in RESCANNABLE_SKIP_REASONS\n"
        }
        head = {
            "m.py": 'A2_SKIP_REASON = "a"\nB2_SKIP_REASON = "b"\n'
            "RESCANNABLE_SET_SKIP_REASONS = frozenset({A2_SKIP_REASON})\n\n\n"
            "def f(x):\n    return x in RESCANNABLE_SET_SKIP_REASONS\n"
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 1, out)


class TestBehaviourChangesAreCaught(unittest.TestCase):
    """A tool that only ever reports 'identical' proves nothing."""

    def test_renamed_constant_whose_value_also_changed_is_caught(self):
        base = {"m.py": 'A_SKIP_REASON = "to-review"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        head = {"m.py": 'A_SKIP_REASON_V2 = "to-review-v2"\n\n\ndef f():\n    return A_SKIP_REASON_V2\n'}
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 1, out)
            self.assertIn("m.py", out)
            self.assertIn("'to-review'", out)
            self.assertIn("'to-review-v2'", out)

    def test_failure_names_the_module_and_the_differing_node(self):
        base = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f(v):\n    return A_SKIP_REASON if v > 3 else ""\n'}
        head = {"m.py": 'B_SKIP_REASON = "x"\n\n\ndef f(v):\n    return B_SKIP_REASON if v > 4 else ""\n'}
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 1, out)
            self.assertIn("normalised trees differ at Module.body[", out)
            self.assertIn("m.py", out)

    def test_logic_change_alongside_a_rename_is_caught(self):
        base = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f(a, b):\n    return A_SKIP_REASON if a and b else ""\n'}
        head = {"m.py": 'B_SKIP_REASON = "x"\n\n\ndef f(a, b):\n    return B_SKIP_REASON if a or b else ""\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 1)

    def test_a_rename_outside_the_pattern_is_not_normalised_away(self):
        # Guards against the tool passing vacuously: only names matching the
        # pattern may be inlined. A rename of anything else is a real diff.
        base = {
            "m.py": 'A_SKIP_REASON = "x"\nUNRELATED_LIMIT = 5\n\n\ndef f():\n    return A_SKIP_REASON, UNRELATED_LIMIT\n'
        }
        head = {
            "m.py": 'B_SKIP_REASON = "x"\nUNRELATED_CAP = 5\n\n\ndef f():\n    return B_SKIP_REASON, UNRELATED_CAP\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 1, out)
            self.assertIn("UNRELATED", out)

    def test_untouched_module_referencing_the_old_name_is_still_compared(self):
        # THE #567/#568 SHAPE. The rename lands in a.py; b.py is not touched
        # by the diff at all, so a changed-files-only scope would miss it.
        base = {
            "a.py": 'TO_REVIEW_REASON = "to-review"\n',
            "b.py": "from a import TO_REVIEW_REASON\n\n\ndef f():\n    return TO_REVIEW_REASON\n",
        }
        head = {
            "a.py": 'TO_REVIEW_SKIP_REASON = "to-review"\n',
            "b.py": "from a import TO_REVIEW_REASON\n\n\ndef f():\n    return TO_REVIEW_REASON\n",
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertGreaterEqual(code, 2, out)
            self.assertIn("b.py", out)
            self.assertIn("ImportError at module-import time", out)


class TestReferenceCheck(unittest.TestCase):
    """Single-revision, no diff needed, and no false positives: a matching
    constant imported from, or read in, a module where nothing declares it."""

    def test_broken_from_import_is_reported(self):
        files = {"a.py": 'PRESENT_SKIP_REASON = "x"\n', "b.py": "from a import MISSING_SKIP_REASON\n"}
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 1, out)
            self.assertIn("a.py declares no `MISSING_SKIP_REASON`", out)

    def test_undeclared_bare_name_is_reported(self):
        files = {"b.py": "def f():\n    return GHOST_SKIP_REASON\n"}
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 1, out)
            self.assertIn("GHOST_SKIP_REASON", out)
            self.assertIn("NameError", out)

    def test_resolvable_references_are_clean(self):
        files = {
            "a.py": 'PRESENT_SKIP_REASON = "x"\n',
            "b.py": "from a import PRESENT_SKIP_REASON\n\n\ndef f():\n    return PRESENT_SKIP_REASON\n",
        }
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 0, out)
            self.assertIn("all resolve at", out)

    def test_local_variable_is_not_mistaken_for_a_missing_constant(self):
        files = {"b.py": 'def f():\n    LOCAL_SKIP_REASON = "x"\n    return LOCAL_SKIP_REASON\n'}
        with _repo(files, files) as root:
            self.assertEqual(run_tool(root, "--check-references")[0], 0)

    def test_third_party_import_is_not_resolved_or_flagged(self):
        files = {
            "b.py": "from some.external.package import EXTERNAL_SKIP_REASON\n\n\ndef f():\n    return EXTERNAL_SKIP_REASON\n"
        }
        with _repo(files, files) as root:
            self.assertEqual(run_tool(root, "--check-references")[0], 0)

    def test_a_clean_run_reports_how_many_references_it_resolved(self):
        # A green log has to be evidence, not silence: if the scan ever
        # silently stopped finding references, "clean" would be
        # indistinguishable from "checked nothing".
        files = {
            "a.py": 'PRESENT_SKIP_REASON = "x"\n',
            "b.py": "from a import PRESENT_SKIP_REASON\n\n\ndef f():\n    return PRESENT_SKIP_REASON\n",
        }
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 0, out)
            self.assertRegex(out, r"\d+ reference\(s\) to constants matching")

    def test_a_tree_with_no_matching_references_says_nothing_to_check(self):
        files = {"a.py": "def f():\n    return 1\n"}
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 0, out)
            self.assertIn("nothing to check", out)


class TestScanCoverage(unittest.TestCase):
    """The scan is whole-tree and recursive ON PURPOSE.

    A 2026-07-29 audit found both roster tethers in docs_lint.py using a
    non-recursive `src_dir.glob("*.py")`, so
    `MPCAutofill/cardpicker/management/commands/` was never scanned and
    `scryfall-tagger-v1` — which writes real PrintingTagVote rows — was
    invisible to them. These tests pin that this tool does not share the
    defect, and that including tests/ here is a decision, not an accident.
    """

    def test_nested_management_command_is_scanned(self):
        files = {
            "MPCAutofill/cardpicker/verdicts.py": 'TO_REVIEW_SKIP_REASON = "to-review"\n',
            "MPCAutofill/cardpicker/management/commands/retag.py": (
                "from cardpicker.verdicts import TO_REVIEW_REASON\n\n\ndef run():\n    return TO_REVIEW_REASON\n"
            ),
        }
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 1, out)
            self.assertIn("management/commands/retag.py", out)

    def test_test_modules_are_scanned_deliberately(self):
        # Four of the six modules broken by the #567/#568 merge were test
        # modules. The roster tethers exclude tests/ because their question
        # is "is this value documented?"; this tool's question is "does the
        # reference still resolve?", and an ImportError in a test module is
        # just as real.
        files = {
            "MPCAutofill/cardpicker/verdicts.py": 'TO_REVIEW_SKIP_REASON = "to-review"\n',
            "MPCAutofill/cardpicker/tests/test_verdicts.py": (
                "from cardpicker.verdicts import TO_REVIEW_REASON\n\n\ndef test_x():\n    assert TO_REVIEW_REASON\n"
            ),
        }
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references")
            self.assertEqual(code, 1, out)
            self.assertIn("tests/test_verdicts.py", out)

    def test_real_repo_scan_reaches_management_commands_and_tests(self):
        # Derivation guard against the real tree: if the listing ever stopped
        # recursing, every real-repo assertion here would pass vacuously.
        index = cre.RevisionIndex(
            "HEAD", cre.read_python_tree("HEAD", cwd=REPO_ROOT), cre.re.compile(cre.DEFAULT_PATTERN)
        )
        scanned = set(index.modules)
        self.assertIn("MPCAutofill/cardpicker/management/commands/reparse_collector_evidence.py", scanned)
        self.assertIn("MPCAutofill/cardpicker/tests/test_catalog_stats.py", scanned)


class TestChangedSinceGate(unittest.TestCase):
    """The cheap no-op path that makes `references` safe to mark required."""

    @staticmethod
    def _commit(root: Path, message: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--no-verify", "-m", message],
            cwd=root,
            check=True,
            capture_output=True,
        )

    def test_no_python_change_skips_with_an_explicit_message(self):
        files = {"a.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        with _repo(files, files) as root:
            (root / "docs.md").write_text("docs only\n")
            self._commit(root, "docs only")
            code, out = run_tool(root, "--check-references", "--changed-since", "HEAD~1")
            self.assertEqual(code, 0, out)
            self.assertIn("nothing to check", out)
            self.assertIn("no *.py file changed", out)

    def test_a_python_change_still_runs_the_check(self):
        base = {"a.py": 'PRESENT_SKIP_REASON = "x"\n'}
        head = {"a.py": 'PRESENT_SKIP_REASON = "x"\n', "b.py": "from a import MISSING_SKIP_REASON\n"}
        with _repo(base, head) as root:
            code, out = run_tool(root, "--check-references", "--changed-since", "HEAD~1")
            self.assertEqual(code, 1, out)
            self.assertIn("MISSING_SKIP_REASON", out)

    def test_unresolvable_base_runs_the_check_instead_of_failing(self):
        # A required status check must never wedge because a shallow clone
        # lacks the base commit. Degrade to running it, and say so.
        files = {"a.py": 'PRESENT_SKIP_REASON = "x"\n', "b.py": "from a import MISSING_SKIP_REASON\n"}
        with _repo(files, files) as root:
            code, out = run_tool(root, "--check-references", "--changed-since", "0" * 40)
            self.assertIn("could not be resolved in this clone", out)
            self.assertEqual(code, 1, out)


class TestPatternIsAParameter(unittest.TestCase):
    def test_default_pattern_covers_anonymous_id(self):
        base = {"m.py": 'OCR_ANONYMOUS_ID = "local-ocr-v1"\n\n\ndef f():\n    return OCR_ANONYMOUS_ID\n'}
        head = {"m.py": 'LOCAL_OCR_ANONYMOUS_ID = "local-ocr-v1"\n\n\ndef f():\n    return LOCAL_OCR_ANONYMOUS_ID\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_default_pattern_covers_thresholds_and_weights(self):
        base = {
            "m.py": "PHASH_THRESHOLD = 12\nAI_WEIGHT = 0.5\n\n\ndef f(d):\n    return d < PHASH_THRESHOLD, AI_WEIGHT\n"
        }
        head = {
            "m.py": "PHASH_DISTANCE_THRESHOLD = 12\nAI_ART_WEIGHT = 0.5\n\n\ndef f(d):\n    return d < PHASH_DISTANCE_THRESHOLD, AI_ART_WEIGHT\n"
        }
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_custom_family_needs_an_explicit_pattern(self):
        base = {"m.py": 'OLD_FLAVOUR_TOKEN = "t"\n\n\ndef f():\n    return OLD_FLAVOUR_TOKEN\n'}
        head = {"m.py": 'NEW_FLAVOUR_TOKEN = "t"\n\n\ndef f():\n    return NEW_FLAVOUR_TOKEN\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root, "--pattern", "FLAVOUR_TOKEN")[0], 0)
            # ...and without it, the default pattern does not match, so the
            # rename is (correctly) reported as an unexplained difference.
            self.assertEqual(compare(root, "--all")[0], 0)  # nothing in scope at all

    def test_dot_pattern_inlines_every_screaming_snake_constant(self):
        base = {"m.py": 'OLD_TOKEN = "t"\n\n\ndef f():\n    return OLD_TOKEN\n'}
        head = {"m.py": 'NEW_TOKEN = "t"\n\n\ndef f():\n    return NEW_TOKEN\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root, "--pattern", ".")[0], 0)


class TestScopeAndNotes(unittest.TestCase):
    def test_no_rename_means_nothing_to_prove(self):
        base = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        head = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON, 1\n'}
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)
            self.assertIn("nothing to prove", out)

    def test_all_widens_the_scope_to_every_matching_module(self):
        # Same diff as above; --all opts into comparing it anyway, and the
        # added expression is then reported.
        base = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        head = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON, 1\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root, "--all")[0], 1)

    def test_non_static_declaration_is_noted_not_silently_inlined(self):
        base = {
            "m.py": 'DERIVED_SKIP_REASON = compute()\nA_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'
        }
        head = {
            "m.py": 'DERIVED_SKIP_REASON = compute()\nB_SKIP_REASON = "x"\n\n\ndef f():\n    return B_SKIP_REASON\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)
            self.assertIn("has a non-static value and was NOT inlined", out)

    def test_unreferenced_value_change_is_a_note_not_a_failure(self):
        base = {"m.py": 'UNUSED_SKIP_REASON = "old"\nA_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        head = {
            "m.py": 'UNUSED_RENAMED_SKIP_REASON = "new"\nA_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'
        }
        with _repo(base, head) as root:
            code, out = compare(root)
            self.assertEqual(code, 0, out)
            self.assertIn("declared constant value", out)
            self.assertIn("'new'", out)

    def test_paths_narrows_the_comparison(self):
        base = {
            "a.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n',
            "b.py": 'B_SKIP_REASON = "y"\n\n\ndef g(v):\n    return B_SKIP_REASON if v > 1 else ""\n',
        }
        head = {
            "a.py": 'A2_SKIP_REASON = "x"\n\n\ndef f():\n    return A2_SKIP_REASON\n',
            "b.py": 'B2_SKIP_REASON = "y"\n\n\ndef g(v):\n    return B2_SKIP_REASON if v > 2 else ""\n',
        }
        with _repo(base, head) as root:
            self.assertEqual(compare(root, "--paths", "b.py")[0], 1)
            self.assertEqual(compare(root, "--paths", "a.py")[0], 0)

    def test_added_and_deleted_modules_do_not_crash(self):
        base = {"a.py": 'A_SKIP_REASON = "x"\n', "gone.py": 'GONE_SKIP_REASON = "g"\n'}
        head = {"a.py": 'A2_SKIP_REASON = "x"\n', "fresh.py": 'FRESH_SKIP_REASON = "f"\n'}
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_syntax_error_in_an_unrelated_module_does_not_crash(self):
        base = {"a.py": 'A_SKIP_REASON = "x"\n', "broken.py": "def (:\n"}
        head = {"a.py": 'A2_SKIP_REASON = "x"\n', "broken.py": "def (:\n"}
        with _repo(base, head) as root:
            self.assertEqual(compare(root)[0], 0)

    def test_default_base_falls_back_when_there_is_no_origin(self):
        base = {"m.py": 'A_SKIP_REASON = "x"\n\n\ndef f():\n    return A_SKIP_REASON\n'}
        head = {"m.py": 'B_SKIP_REASON = "x"\n\n\ndef f():\n    return B_SKIP_REASON\n'}
        with _repo(base, head) as root:
            # No --base: with no origin/master and no local master ancestor
            # other than HEAD~1, default_base() must still find something.
            code, out = run_tool(root, "--head", "HEAD")
            self.assertEqual(code, 0, out)


class TestNormaliserUnits(unittest.TestCase):
    def test_first_difference_locates_a_node_path(self):
        import ast

        left = ast.parse("def f():\n    return 1 + 2\n")
        right = ast.parse("def f():\n    return 1 + 3\n")
        diff = cre.first_difference(left, right)
        self.assertIsNotNone(diff)
        path, before, after = diff
        self.assertTrue(path.startswith("Module.body[0]"), path)
        self.assertIn("2", before)
        self.assertIn("3", after)

    def test_matches_requires_screaming_snake_case(self):
        index = cre.RevisionIndex("rev", {}, cre.re.compile(cre.DEFAULT_PATTERN))
        self.assertTrue(index.matches("SOME_SKIP_REASON"))
        self.assertTrue(index.matches("LANDS_PHASH_SKIP_REASON_PREFIX"))
        self.assertFalse(index.matches("skip_reason"))
        self.assertFalse(index.matches("SomeSkipReasonThing"))


class TestAgainstRealRepo(unittest.TestCase):
    @staticmethod
    def _have(rev: str) -> bool:
        return (
            subprocess.run(
                ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
                cwd=REPO_ROOT,
                capture_output=True,
            ).returncode
            == 0
        )

    def test_committed_tree_resolves_every_matching_reference(self):
        # The invariant the #567/#568 merge would have broken: no matching
        # constant is imported from, or read in, a module that has none.
        code, out = run_tool(REPO_ROOT, "--check-references")
        self.assertEqual(code, 0, out)

    def test_pr_567_rename_is_still_proven_equivalent(self):
        # Regression pin for the incident itself. #567 renamed 55 skip-reason
        # constants across the pipeline; every module it touched must
        # normalise identically against its parent. docs_lint.py is excluded
        # by --paths: that same PR legitimately ADDED 129 lines of new lint
        # code to it, which is a real behaviour change and correctly reported.
        if not self._have(PR_567):
            self.skipTest("PR #567 not in this clone's history")
        pipeline_modules = [
            "MPCAutofill/cardpicker/catalog_stats.py",
            "MPCAutofill/cardpicker/image_evidence.py",
            "MPCAutofill/cardpicker/local_calculate_verdicts.py",
            "MPCAutofill/cardpicker/local_detect_ai_art.py",
            "MPCAutofill/cardpicker/local_identify_printing_tags.py",
            "MPCAutofill/cardpicker/local_illustration.py",
            "MPCAutofill/cardpicker/local_lands_identify.py",
            "MPCAutofill/cardpicker/local_layout_class_cast.py",
            "MPCAutofill/cardpicker/local_residual_classify.py",
            "MPCAutofill/cardpicker/models.py",
            "MPCAutofill/cardpicker/question_feed.py",
            "MPCAutofill/cardpicker/review_clusters.py",
        ]
        code, out = run_tool(
            REPO_ROOT, "--base", f"{PR_567}^", "--head", PR_567, "--quiet-notes", "--paths", *pipeline_modules
        )
        self.assertEqual(code, 0, out)

    def test_pr_567_rename_was_actually_detected_as_a_rename(self):
        # Guards the scoping: if the rename detection silently stopped
        # working, every equivalence test above would pass vacuously.
        if not self._have(PR_567):
            self.skipTest("PR #567 not in this clone's history")
        _code, out = run_tool(REPO_ROOT, "--base", f"{PR_567}^", "--head", PR_567, "--quiet-notes")
        self.assertIn("SLOW_PATH_TO_REVIEW_REASON", out)
        self.assertIn("SLOW_PATH_TO_REVIEW_SKIP_REASON", out)


if __name__ == "__main__":
    unittest.main()
