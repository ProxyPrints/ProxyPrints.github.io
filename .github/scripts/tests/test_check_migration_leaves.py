"""
Unit + integration tests for check_migration_leaves.py.

Fixture tests drive `check()` directly against in-memory migration sources
(no filesystem, no git, no Django, no database). Integration tests build a
real scratch git repo with a `master` branch and a feature branch and drive
`collect_merged()` end to end - which is where the "prove it can fail"
reconstruction of the live 0098 collision lives as permanent regression
coverage rather than a one-off local demo:

  master  : 0098_card_illustration_consensus_fields  -> depends on 0097
  feature : 0098_rename_printings_count_catalogued   -> depends on 0097

Both branches are individually valid and pass a branch-only check; the merge
has two leaves. `test_reconstructed_0098_collision_*` asserts exactly that,
and its renumbered-to-0099 twin asserts the fix goes green.

Run: python3 .github/scripts/tests/test_check_migration_leaves.py
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import check_migration_leaves as cml  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parents[1]

APP = "MPCAutofill/cardpicker/migrations"


def migration(deps, extra="") -> str:
    rendered = ", ".join(f'("{a}", "{b}")' for a, b in deps)
    return (
        "from django.db import migrations\n\n\n"
        "class Migration(migrations.Migration):\n"
        f"    dependencies = [{rendered}]\n"
        f"{extra}"
        "    operations = []\n"
    )


def linear(count: int, app: str = APP) -> dict:
    """A valid chain 0001 -> 0002 -> ... -> {count}."""
    sources = {f"{app}/0001_initial.py": migration([])}
    for number in range(2, count + 1):
        sources[f"{app}/{number:04d}_step.py"] = migration(
            [("cardpicker", f"{number - 1:04d}_" + ("initial" if number == 2 else "step"))]
        )
    return sources


class FixtureRules(unittest.TestCase):
    def test_linear_chain_is_clean(self):
        self.assertEqual(cml.check(linear(5)), [])

    def test_two_migrations_on_the_same_parent_are_two_leaves(self):
        sources = linear(3)
        sources[f"{APP}/0004_a.py"] = migration([("cardpicker", "0003_step")])
        sources[f"{APP}/0004_b.py"] = migration([("cardpicker", "0003_step")])
        messages = [f.message for f in cml.check(sources)]
        self.assertTrue(any("2 leaf nodes" in m for m in messages), messages)
        self.assertTrue(any("share the number prefix 0004" in m for m in messages), messages)

    def test_renumbering_the_second_one_clears_it(self):
        sources = linear(3)
        sources[f"{APP}/0004_a.py"] = migration([("cardpicker", "0003_step")])
        sources[f"{APP}/0005_b.py"] = migration([("cardpicker", "0004_a")])
        self.assertEqual(cml.check(sources), [])

    def test_failure_message_names_the_next_free_number(self):
        sources = linear(3)
        sources[f"{APP}/0004_a.py"] = migration([("cardpicker", "0003_step")])
        sources[f"{APP}/0004_b.py"] = migration([("cardpicker", "0003_step")])
        leaf_finding = next(f for f in cml.check(sources) if "leaf nodes" in f.message)
        self.assertIn("renumber the leaf your PR adds to 0005_", leaf_finding.message)

    def test_cross_app_dependency_is_not_an_intra_app_edge(self):
        # An accounts migration depending on a cardpicker one must not make
        # that cardpicker migration a non-leaf, nor invent an accounts node.
        sources = linear(3)
        sources["MPCAutofill/accounts/migrations/0001_initial.py"] = migration([("cardpicker", "0003_step")])
        self.assertEqual(cml.check(sources), [])

    def test_swappable_dependency_call_is_skipped_not_guessed(self):
        sources = linear(2)
        sources[f"{APP}/0003_user.py"] = (
            "from django.conf import settings\n"
            "from django.db import migrations\n\n\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [\n"
            "        migrations.swappable_dependency(settings.AUTH_USER_MODEL),\n"
            '        ("cardpicker", "0002_step"),\n'
            "    ]\n"
            "    operations = []\n"
        )
        self.assertEqual(cml.check(sources), [])

    def test_squash_does_not_count_as_an_extra_leaf(self):
        sources = linear(3)
        sources[f"{APP}/0001_0003_squashed.py"] = migration(
            [],
            extra='    replaces = [("cardpicker", "0001_initial"), ("cardpicker", "0002_step"), '
            '("cardpicker", "0003_step")]\n',
        )
        self.assertEqual(cml.check(sources), [])

    def test_dependency_on_a_migration_that_does_not_exist_is_reported(self):
        sources = linear(2)
        sources[f"{APP}/0003_step.py"] = migration([("cardpicker", "0002_typo")])
        messages = [f.message for f in cml.check(sources)]
        self.assertTrue(any("does not exist" in m for m in messages), messages)

    def test_run_before_edge_is_honoured(self):
        # 0004_a declares it must run BEFORE 0004_b, which linearises what
        # would otherwise look like two leaves.
        sources = linear(3)
        sources[f"{APP}/0004_a.py"] = migration(
            [("cardpicker", "0003_step")],
            extra='    run_before = [("cardpicker", "0004_b")]\n',
        )
        sources[f"{APP}/0004_b.py"] = migration([("cardpicker", "0003_step")])
        messages = [f.message for f in cml.check(sources)]
        self.assertFalse(any("leaf nodes" in m for m in messages), messages)
        # The duplicate number is still called out - it is confusing even when
        # run_before happens to keep the graph linear.
        self.assertTrue(any("share the number prefix 0004" in m for m in messages), messages)


class ScratchRepo:
    """A throwaway git repo with a master branch and a feature branch."""

    def __init__(self, tmp: Path) -> None:
        self.root = tmp
        self._git("init", "-q", "-b", "master")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    def checkout(self, *args: str) -> None:
        self._git("checkout", "-q", *args)


class MergeResultIntegration(unittest.TestCase):
    """The reconstruction: master's 0098 vs a branch's 0098, both on 0097."""

    def build(self, tmp: Path, feature_name: str, feature_dep: str) -> ScratchRepo:
        repo = ScratchRepo(tmp)
        repo.write(f"{APP}/__init__.py", "")
        repo.write(f"{APP}/0097_freeze.py", migration([]))
        repo.commit("shared history at 0097")
        repo.checkout("-b", "feature")
        repo.write(f"{APP}/{feature_name}", migration([("cardpicker", feature_dep)]))
        repo.commit("feature adds its migration")
        repo.checkout("master")
        repo.write(
            f"{APP}/0098_card_illustration_consensus_fields.py",
            migration([("cardpicker", "0097_freeze")]),
        )
        repo.commit("master adds 0098")
        repo.checkout("feature")
        return repo

    def test_reconstructed_0098_collision_is_invisible_on_the_branch_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.build(Path(tmp), "0098_rename_printings_count_catalogued.py", "0097_freeze")
            self.assertEqual(cml.check(cml.collect_worktree(repo.root)), [])

    def test_reconstructed_0098_collision_is_red_against_the_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.build(Path(tmp), "0098_rename_printings_count_catalogued.py", "0097_freeze")
            sources, from_base = cml.collect_merged(repo.root, "master")
            self.assertEqual(from_base, 1)
            messages = [f.message for f in cml.check(sources)]
            self.assertTrue(any("2 leaf nodes" in m for m in messages), messages)
            self.assertTrue(any("0098_card_illustration" in m for m in messages), messages)
            self.assertTrue(any("0098_rename_printings" in m for m in messages), messages)

    def test_renumbering_to_0099_is_green_against_the_same_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.build(
                Path(tmp),
                "0099_rename_printings_count_catalogued.py",
                "0098_card_illustration_consensus_fields",
            )
            sources, _ = cml.collect_merged(repo.root, "master")
            self.assertEqual(cml.check(sources), [])

    def test_a_branch_touching_no_migrations_is_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = ScratchRepo(root)
            repo.write(f"{APP}/__init__.py", "")
            repo.write(f"{APP}/0097_freeze.py", migration([]))
            repo.commit("shared history at 0097")
            repo.checkout("-b", "docs-only")
            repo.write("docs/thing.md", "hello\n")
            repo.commit("docs only")
            repo.checkout("master")
            repo.write(f"{APP}/0098_master.py", migration([("cardpicker", "0097_freeze")]))
            repo.commit("master adds 0098")
            repo.checkout("docs-only")
            sources, _ = cml.collect_merged(root, "master")
            self.assertEqual(cml.check(sources), [])

    def test_a_migration_the_pr_deletes_is_not_resurrected_from_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = ScratchRepo(root)
            repo.write(f"{APP}/__init__.py", "")
            repo.write(f"{APP}/0097_freeze.py", migration([]))
            repo.write(f"{APP}/0098_doomed.py", migration([("cardpicker", "0097_freeze")]))
            repo.commit("master with 0098")
            repo.checkout("-b", "feature")
            (root / APP / "0098_doomed.py").unlink()
            repo.write(f"{APP}/0098_replacement.py", migration([("cardpicker", "0097_freeze")]))
            repo.commit("swap 0098 for a different one")
            sources, _ = cml.collect_merged(root, "master")
            self.assertNotIn(f"{APP}/0098_doomed.py", sources)
            self.assertEqual(cml.check(sources), [])


class RealRepo(unittest.TestCase):
    def test_this_repository_has_one_leaf_per_app(self):
        findings = cml.check(cml.collect_worktree(REPO_ROOT))
        self.assertEqual(findings, [], [f.render() for f in findings])


if __name__ == "__main__":
    unittest.main(verbosity=2)
