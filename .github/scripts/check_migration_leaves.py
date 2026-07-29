#!/usr/bin/env python3
"""
MIGRATION-GRAPH LEAF GUARD: one leaf per Django app, evaluated against the
MERGE RESULT rather than against the PR branch in isolation.

WHY THIS EXISTS (it is not a tidiness rule)
-------------------------------------------
Two branches can each add `0098_<something>.py` depending on `0097`. The
filenames differ, so git reports no textual conflict and GitHub reports the
second PR MERGEABLE/CLEAN. Nothing is wrong with either branch on its own.
The moment the second one merges, `cardpicker` has TWO leaf nodes, and
`pytest-django` builds its test database by running `migrate` - so the fork
errors at test-database SETUP on EVERY branch in the repo, not just the
branch that introduced it. The whole repo's CI goes red at once.

This has now happened twice:

  - at 0096 (#568's `0096_card_scan_log_anon_skip_idx` vs #570's freeze
    migration), repaired by #576 renumbering the second to 0097;
  - at 0098 (#573's `0098_card_illustration_consensus_fields` vs #601's
    `0098_rename_printings_count_catalogued`), caught before merge and
    renumbered to 0099 in the same change that added this script.

#576 repaired the first fork but prevented nothing, which is why the second
one arrived within days. This is the prevention.

WHY CHECKING THE BRANCH ALONE IS NOT ENOUGH
-------------------------------------------
#601's own CI was 10/10 GREEN with the collision already live on master.
Every signal we normally trust said it was safe:

  - no textual conflict (different filenames);
  - `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`;
  - green checks - because they had run against master BEFORE #573 merged,
    and GitHub does not re-run a PR's checks when its base moves.

A check that looks only at the files on the PR branch reproduces exactly
that blindness: on #601's branch alone the graph has one leaf and is
perfectly valid. The fork exists only in the MERGE of the two. So this
script unions the PR's migrations with the ones on the base ref (honouring
any the PR deletes) and evaluates the graph that merging would actually
produce.

STALENESS, STATED PLAINLY
-------------------------
`--base origin/<base_ref>` is resolved when the job RUNS, so a re-run always
sees the current base. But a check run that PASSED days ago stays green in
GitHub's UI even after the base moves underneath it - that is a property of
GitHub, not of this script, and no CI job can fix it from the inside. The
complete fix is branch protection's "Require branches to be up to date
before merging", which forces a re-run against the new base. This script
makes that re-run meaningful; it cannot force it to happen.

HOW IT DECIDES (no database, no Django, no imports)
---------------------------------------------------
Everything is read statically with `ast` - migration files are never
imported or executed, so this needs no settings module, no installed apps,
no postgres, and no `pip install -r requirements.txt`. It runs in seconds on
a bare `actions/setup-python`.

Per Django app (any directory named `migrations/` containing `__init__.py`):

  1. every `NNNN_name.py` is a node;
  2. each node's `dependencies = [...]` class attribute is parsed for
     two-string-literal tuples; only SAME-APP entries become edges, which
     mirrors `MigrationLoader.graph.leaf_nodes(app)` - a node is a leaf for
     an app when nothing else IN THAT APP depends on it;
  3. entries that are not literal 2-tuples (`migrations.swappable_dependency(
     settings.AUTH_USER_MODEL)`, present in seven of this repo's migrations)
     are cross-app by construction and are skipped, not guessed at;
  4. `run_before` is read the same way and contributes reversed edges;
  5. a squash migration's `replaces` list removes the replaced nodes, so a
     squash is not miscounted as a second leaf. The repo has no squashes
     today; this is here so the first one does not produce a false positive.

FINDINGS
--------
  - MULTIPLE LEAVES for an app - the failure this exists to prevent.
  - DUPLICATE NUMBER PREFIX within an app. Usually the same defect one step
    earlier, and it is the actionable instruction ("renumber to NNNN+1")
    even when the leaves happen to still be linear. Reported separately so
    the message says which of the two problems you have.
  - A dependency naming a migration that does not exist in the app.

Exit code is the number of findings (0 = clean), matching docs_lint.py's,
check_protected_core_license.py's and check_extractor_manifest_sync.py's
convention.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that never contain first-party Django apps but are expensive to
# walk (and, in the case of site-packages, full of third-party migrations).
SKIP_DIRS = {
    ".git",
    ".claude",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
    "staticfiles",
    "dist",
    "build",
}

MIGRATION_NAME_RE = re.compile(r"^(\d{4})_[A-Za-z0-9_]*\.py$")


class Finding:
    def __init__(self, app: str, message: str, path: str | None = None) -> None:
        self.app = app
        self.message = message
        self.path = path

    def render(self) -> str:
        where = self.path or f"app {self.app}"
        return f"{where}: {self.message}"

    def annotation(self) -> str:
        if self.path:
            return f"::error file={self.path}::{self.message}"
        return f"::error::[{self.app}] {self.message}"


# --------------------------------------------------------------------------
# static parsing
# --------------------------------------------------------------------------


def _string_pairs(node: ast.AST) -> list[tuple[str, str]]:
    """Literal ("app", "migration") 2-tuples inside a list/tuple literal.

    Anything else - a call like `migrations.swappable_dependency(...)`, a
    name, a starred expression - is skipped rather than guessed at. Those are
    cross-app by construction and cannot affect a same-app leaf count.
    """
    pairs: list[tuple[str, str]] = []
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return pairs
    for element in node.elts:
        if not isinstance(element, (ast.Tuple, ast.List)) or len(element.elts) != 2:
            continue
        first, second = element.elts
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and isinstance(second, ast.Constant)
            and isinstance(second.value, str)
        ):
            pairs.append((first.value, second.value))
    return pairs


def _string_list(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return []
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


class MigrationFacts:
    def __init__(self) -> None:
        self.dependencies: list[tuple[str, str]] = []
        self.run_before: list[tuple[str, str]] = []
        self.replaces: list[tuple[str, str]] = []


def parse_migration(source: str) -> MigrationFacts:
    """Read one migration module's graph-relevant class attributes.

    Reads the `Migration` class body if there is one, and otherwise any class
    in the module - a migration file always defines exactly one.
    """
    facts = MigrationFacts()
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    target = next((c for c in classes if c.name == "Migration"), classes[0] if classes else None)
    if target is None:
        return facts
    for statement in target.body:
        if not isinstance(statement, ast.Assign):
            continue
        names = {t.id for t in statement.targets if isinstance(t, ast.Name)}
        if "dependencies" in names:
            facts.dependencies = _string_pairs(statement.value)
        elif "run_before" in names:
            facts.run_before = _string_pairs(statement.value)
        elif "replaces" in names:
            facts.replaces = _string_pairs(statement.value)
    return facts


# --------------------------------------------------------------------------
# collecting the migration set: worktree, base ref, and the merge of the two
# --------------------------------------------------------------------------


def find_migration_dirs(root: Path) -> list[Path]:
    """Every `migrations/` package directory under `root`, as repo-relative paths."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        current = Path(dirpath)
        if current.name == "migrations" and "__init__.py" in filenames:
            found.append(current.relative_to(root))
    return sorted(found)


def _git(args: list[str], root: Path) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def collect_worktree(root: Path) -> dict[str, str]:
    """{repo-relative path -> source} for every numbered migration on disk."""
    sources: dict[str, str] = {}
    for migrations_dir in find_migration_dirs(root):
        for entry in sorted((root / migrations_dir).iterdir()):
            if entry.is_file() and MIGRATION_NAME_RE.match(entry.name):
                sources[str(migrations_dir / entry.name)] = entry.read_text(encoding="utf-8")
    return sources


def collect_merged(root: Path, base_ref: str) -> tuple[dict[str, str], int]:
    """Worktree migrations unioned with the base ref's, minus any the PR deletes.

    This is the set a merge into `base_ref` would produce, for the two things
    that can change a leaf count: files added on either side, and files the PR
    removes. Where both sides have a file, the PR's version wins - which is
    what a merge yields for a branch based on (or rebased onto) the base, and
    what git would raise as a conflict otherwise.

    Returns (sources, number of migrations contributed by the base alone).
    """
    sources = collect_worktree(root)

    listing = _git(["ls-tree", "-r", "--name-only", base_ref], root).splitlines()
    base_paths = [p for p in listing if "/migrations/" in p and MIGRATION_NAME_RE.match(p.rsplit("/", 1)[-1])]

    # Honour deletions: `base...HEAD` diffs from the merge base, so this is
    # what the PR itself removed, not what the base happens to lack.
    #
    # `--no-renames` is load-bearing, not stylistic. Renumbering a migration is
    # exactly a delete+add of near-identical content, so git's rename detection
    # reports it as `R` and it never appears under `--diff-filter=D` - the old
    # number would be resurrected from the base and the PR failed for a
    # collision it had already fixed. Turning rename detection off makes the
    # renumber read as the delete plus add that it is on disk.
    try:
        deleted = set(
            _git(
                [
                    "diff",
                    "--no-renames",
                    "--name-only",
                    "--diff-filter=D",
                    f"{base_ref}...HEAD",
                ],
                root,
            ).splitlines()
        )
    except subprocess.CalledProcessError:
        # No common ancestor (shallow clone without enough history). Union
        # everything - conservative, and it says so rather than silently
        # narrowing what is checked.
        print(
            f"note: no merge base between HEAD and {base_ref}; " "unioning without honouring deletions",
            file=sys.stderr,
        )
        deleted = set()

    added_from_base = 0
    for path in base_paths:
        if path in sources or path in deleted:
            continue
        sources[path] = _git(["show", f"{base_ref}:{path}"], root)
        added_from_base += 1
    return sources, added_from_base


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------


def check(sources: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    by_app: dict[str, dict[str, str]] = {}
    path_of: dict[tuple[str, str], str] = {}
    for path, source in sources.items():
        parts = path.split("/")
        app = parts[parts.index("migrations") - 1]
        name = parts[-1][: -len(".py")]
        by_app.setdefault(app, {})[name] = source
        path_of[(app, name)] = path

    for app in sorted(by_app):
        migrations = by_app[app]
        facts = {name: parse_migration(src) for name, src in migrations.items()}

        # A squash stands in for what it replaces; the replaced nodes are not
        # separate leaves.
        replaced: set[str] = set()
        for name, fact in facts.items():
            for dep_app, dep_name in fact.replaces:
                if dep_app == app:
                    replaced.add(dep_name)
        nodes = {n for n in migrations if n not in replaced}

        # children[x] = nodes in this app that must run after x
        children: dict[str, set[str]] = {n: set() for n in nodes}
        for name in sorted(nodes):
            for dep_app, dep_name in facts[name].dependencies:
                if dep_app != app:
                    continue
                if dep_name in ("__first__", "__latest__"):
                    continue
                if dep_name in replaced:
                    continue
                if dep_name not in nodes:
                    findings.append(
                        Finding(
                            app,
                            f"depends on {app}.{dep_name}, which does not exist",
                            path_of[(app, name)],
                        )
                    )
                    continue
                children[dep_name].add(name)
            for other_app, other_name in facts[name].run_before:
                if other_app == app and other_name in nodes:
                    children[name].add(other_name)

        leaves = sorted(n for n in nodes if not children[n])

        duplicates: dict[str, list[str]] = {}
        for name in sorted(nodes):
            duplicates.setdefault(name[:4], []).append(name)
        collisions = {number: names for number, names in duplicates.items() if len(names) > 1}

        if len(leaves) > 1:
            highest = max(int(n[:4]) for n in nodes)
            listed = "\n".join(f"    - {n}  ({path_of[(app, n)]})" for n in leaves)
            findings.append(
                Finding(
                    app,
                    f"migration graph has {len(leaves)} leaf nodes; Django requires exactly one.\n"
                    f"{listed}\n"
                    f"  `migrate` - and therefore pytest-django's test-database setup on EVERY\n"
                    f"  branch in this repo - fails with 'Conflicting migrations detected;\n"
                    f"  multiple leaf nodes in the migration graph'.\n"
                    f"  Fix: renumber the leaf your PR adds to {highest + 1:04d}_... and repoint\n"
                    f"  its `dependencies` at the other leaf. Update the number wherever the\n"
                    f"  migration's own docstring or comments state it.",
                )
            )

        for number, names in sorted(collisions.items()):
            findings.append(
                Finding(
                    app,
                    f"two migrations share the number prefix {number}: {', '.join(names)}. "
                    f"Renumber the one your PR adds and repoint its `dependencies`.",
                )
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        metavar="REF",
        help=(
            "Git ref of the merge target (e.g. origin/master). The check then runs "
            "against the MERGE of the worktree and that ref, which is the only way "
            "to see a collision that exists in neither side alone. Without it, only "
            "the worktree is checked."
        ),
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Also emit ::error:: workflow-command annotations for GitHub's UI.",
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT),
        metavar="DIR",
        help="Repository root to check (default: this script's repo).",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.base:
        sources, from_base = collect_merged(root, args.base)
        scope = f"merge of the worktree with {args.base} (+{from_base} migration(s) from the base)"
    else:
        sources = collect_worktree(root)
        scope = "worktree only (no --base given; a cross-branch collision CANNOT be seen here)"

    findings = check(sources)

    print(f"check_migration_leaves: {len(sources)} migration(s), scope = {scope}")
    if not findings:
        print("check_migration_leaves: OK - one leaf per app.")
        return 0

    print(f"\ncheck_migration_leaves: {len(findings)} finding(s)\n")
    for finding in findings:
        print(f"  {finding.render()}")
        if args.annotate:
            print(finding.annotation().replace("\n", "%0A"))
    return len(findings)


if __name__ == "__main__":
    sys.exit(main())
