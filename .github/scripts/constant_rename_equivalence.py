#!/usr/bin/env python3
"""
Constant-rename equivalence check — prove a constant-renaming refactor
changed no behaviour, and catch the merge that silently broke it.

WHY THIS EXISTS (the motivating incident, 2026-07-29, PRs #567 + #568)
---------------------------------------------------------------------
PR #567 renamed `SLOW_PATH_TO_REVIEW_REASON` to
`SLOW_PATH_TO_REVIEW_SKIP_REASON` in local_calculate_verdicts.py.
Concurrently, PR #568 added BRAND NEW code in catalog_stats.py that
imported and used the OLD name. Git auto-merged the two with no
conflict — #568 only ADDED lines, #567 only touched a nearby docstring,
so the rename and the new references never textually collided. Nothing
caught it: not git, not the full backend test suite, not mypy. The
merged result would have raised, at IMPORT time,

    ImportError: cannot import name 'SLOW_PATH_TO_REVIEW_REASON'

in a module imported by the catalog-stats view AND by the hourly
`warm_catalog_stats` job. Thirteen reference sites needed fixing.

The defect class is general: any constant-extraction or constant-rename
refactor (`*_SKIP_REASON`, `*_ANONYMOUS_ID`, `*_EXTRACTOR_VERSION`,
weights, thresholds) landing concurrently with new code that uses the
old name. Textual merge cannot see it; only the resolved name graph can.

WHAT IT DOES
------------
Two independent checks, in increasing order of strength:

1. REFERENCES (single revision, no false positives, always safe to run):
   every `from x import NAME` whose NAME matches the pattern must
   actually be declared in x, and every matching ALL-CAPS name a module
   reads must resolve to a declaration somewhere. This alone is what
   the #567/#568 merge would have tripped, at HEAD, with no second
   revision needed.

2. EQUIVALENCE (two revisions): for each module in scope, parse it at
   both revisions and NORMALISE both sides by
     - inlining every module-level constant whose name matches the
       pattern, with the constant map built across the WHOLE tree at
       each revision, so cross-module `from x import Y_SKIP_REASON`
       resolves;
     - deleting those declarations, their `__all__` entries, and the
       imports that pulled them in;
     - deleting every docstring (prose is expected to change in a
       rename PR — that is usually the whole diff);
     - constant-folding f-strings and string `+` concatenation;
   then comparing `ast.dump()` trees. Identical trees mean every
   expression that used to evaluate to a given value still evaluates to
   the SAME value, under a different name.

   `LANDS_PHASH_SKIP_REASON_PREFIX` is why the f-string folder exists
   and why matching is `re.search` on the name rather than a suffix
   test: it ends in `_PREFIX`, not `_REASON`, and its value is composed
   at runtime as `f"{PREFIX}{reason}"`.

SCOPE AND HONEST LIMITS
-----------------------
* The equivalence check is a proof about PURE renames. A PR that
  renames a constant AND changes behaviour in the same modules WILL be
  reported — that is correct, not a false positive: the check cannot
  tell you the behaviour change was intended, only that the refactor
  was not behaviour-preserving. Split the PR, or review the reported
  node and land it knowingly.
* A matching constant that is declared but never referenced is deleted
  from both sides by normalisation, so a change to ITS value alone is
  invisible to the tree comparison. Such changes are surfaced
  separately as an informational `note:` line (not a failure, because a
  legitimate constant-EXTRACTION refactor also moves that multiset).
* Declarations whose right-hand side is not a static expression
  (a function call outside the container allowlist, a comprehension)
  are not inlined; they are listed as `note:` so you know what the
  proof did NOT cover.

USAGE
-----
    # default: HEAD vs its merge-base with origin/master
    python3 .github/scripts/constant_rename_equivalence.py

    # explicit revisions, custom constant family
    python3 .github/scripts/constant_rename_equivalence.py \
        --base origin/master --head HEAD --pattern 'ANONYMOUS_ID'

    # every module that mentions the pattern, not just the renamed names
    python3 .github/scripts/constant_rename_equivalence.py --all

    # name-resolution check only, one revision, no diff needed
    python3 .github/scripts/constant_rename_equivalence.py --check-references

Exit code is the number of findings (0 = clean), matching
check_protected_core_license.py's and docs_lint.py's convention.
Stdlib only — reads source text via `git cat-file`, never imports or
executes it, so no Django/third-party deps are needed to run it.
"""

from __future__ import annotations

import argparse
import ast
import copy
import re
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The constant families this repo has actually refactored, plus the generic
# shapes the same defect applies to. Deliberately `re.search`, not a suffix
# match: LANDS_PHASH_SKIP_REASON_PREFIX is a real declaration that does not
# END in any of these. Pass `--pattern '.'` to inline every ALL-CAPS
# module-level constant (the strongest, slowest setting).
DEFAULT_PATTERN = r"SKIP_REASON|ANONYMOUS_ID|_VERSION|_WEIGHT|_THRESHOLD|_PREFIX|_REASON"

# Dotted import prefixes resolve against these directory roots, mirroring how
# MPCAutofill/manage.py makes MPCAutofill/ (not the repo root) the resolution
# root for `cardpicker.*`. "" is the repo root itself.
IMPORT_ROOTS = ("MPCAutofill", "federation-hash-tool", "")

SCREAMING_SNAKE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")

# Calls allowed inside an inlinable right-hand side. `frozenset({A, B})` is
# the single most common shape in this repo's skip-reason declarations.
ALLOWED_CALLS = {"frozenset", "set", "tuple", "list", "dict", "str", "int", "float", "bool"}

STATIC_NODES = (
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Tuple,
    ast.List,
    ast.Set,
    ast.Dict,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.BinOp,
    ast.Add,
    ast.Mult,
    ast.Sub,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
    ast.Starred,
    ast.Attribute,
    ast.keyword,
)


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def default_base(head: str, cwd: Path | None = None) -> str:
    """Merge-base of head with origin/master, falling back to a local master
    and finally to `head~1` — so the tool works in a fresh clone, in a
    worktree with no remote, and in the fixture repos its tests build."""
    for ref in ("origin/master", "origin/main", "master", "main"):
        try:
            return git("merge-base", head, ref, cwd=cwd).strip()
        except subprocess.CalledProcessError:
            continue
    return git("rev-parse", f"{head}~1", cwd=cwd).strip()


def read_python_tree(rev: str, cwd: Path | None = None) -> dict[str, str]:
    """Every *.py file at `rev`, as {repo-relative path: source text}. One
    `git cat-file --batch` subprocess for the whole tree."""
    listing = git("ls-tree", "-r", "--name-only", rev, cwd=cwd)
    paths = [p for p in listing.splitlines() if p.endswith(".py")]
    if not paths:
        return {}

    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=str(cwd or REPO_ROOT),
        input="\n".join(f"{rev}:{p}" for p in paths).encode(),
        check=True,
        capture_output=True,
    )
    out = proc.stdout
    sources: dict[str, str] = {}
    offset = 0
    for path in paths:
        newline = out.index(b"\n", offset)
        header = out[offset:newline].decode()
        offset = newline + 1
        parts = header.split()
        if len(parts) < 3:  # "missing" / "ambiguous" — file unreadable at rev
            continue
        size = int(parts[2])
        sources[path] = out[offset : offset + size].decode("utf-8", "replace")
        offset += size + 1  # trailing newline cat-file appends
    return sources


# --------------------------------------------------------------------------
# per-revision index
# --------------------------------------------------------------------------


def parse(text: str, filename: str) -> ast.Module:
    """`ast.parse` without the DeprecationWarning spray. Some modules in this
    tree contain invalid escape sequences inside string literals; that is a
    real (separate) lint concern, not this tool's, and the warnings would
    otherwise drown its own output."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(text, filename=filename)


@dataclass
class ModuleIndex:
    rel: str
    tree: ast.Module | None
    decls: dict[str, ast.expr] = field(default_factory=dict)
    """Module-level `NAME = <expr>` assignments (any name), name -> RHS."""
    module_bound: set[str] = field(default_factory=set)
    """Every name bound at module level, by any means."""
    any_bound: set[str] = field(default_factory=set)
    """Every name bound anywhere in the module (locals, args, comprehensions)."""
    from_imports: dict[str, tuple[str | None, str, str]] = field(default_factory=dict)
    """local alias -> (defining module rel path or None, original name, raw module text)."""
    parse_error: str | None = None


def _module_level_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    decls: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    decls[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            decls[stmt.target.id] = stmt.value
    return decls


def _bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            names.update(child.names)
    return names


def resolve_module_path(importer_rel: str, module: str | None, level: int, files: set[str]) -> str | None:
    """Resolve an import target to a repo-relative .py path, or None if it is
    not an in-repo module (stdlib, third-party, or a namespace we don't own)."""
    parts = module.split(".") if module else []
    if level > 0:
        base = Path(importer_rel).parent
        # `from . import x` inside pkg/__init__.py is relative to pkg itself.
        if Path(importer_rel).name == "__init__.py":
            level -= 1
        for _ in range(level):
            base = base.parent
        candidates = [base.joinpath(*parts)] if parts or level >= 0 else []
    else:
        candidates = [Path(root).joinpath(*parts) if root else Path(*parts) for root in IMPORT_ROOTS]
    for candidate in candidates:
        as_module = str(candidate.with_suffix(".py")).lstrip("./")
        as_package = str(candidate / "__init__.py").lstrip("./")
        if as_module in files:
            return as_module
        if as_package in files:
            return as_package
    return None


class RevisionIndex:
    """Every .py module at one revision, parsed, with a resolver that inlines
    matching constants across module boundaries."""

    def __init__(self, rev: str, sources: dict[str, str], pattern: re.Pattern[str]):
        self.rev = rev
        self.sources = sources
        self.pattern = pattern
        self.files = set(sources)
        self.modules: dict[str, ModuleIndex] = {}
        self.notes: list[str] = []
        self._cache: dict[tuple[str, str], ast.expr | None] = {}
        self._global_decls: dict[str, list[str]] = {}

        for rel, text in sources.items():
            self.modules[rel] = self._index_module(rel, text)

        for rel, idx in self.modules.items():
            for name in idx.decls:
                if self.matches(name):
                    self._global_decls.setdefault(name, []).append(rel)

    # -- construction ------------------------------------------------------

    def _index_module(self, rel: str, text: str) -> ModuleIndex:
        try:
            tree = parse(text, rel)
        except SyntaxError as exc:
            return ModuleIndex(rel=rel, tree=None, parse_error=str(exc))

        idx = ModuleIndex(rel=rel, tree=tree)
        idx.decls = _module_level_assignments(tree)
        idx.module_bound = _bound_names(ast.Module(body=tree.body, type_ignores=[]))
        # module_bound over the whole tree would include nested scopes; recompute
        # from top-level statements only.
        idx.module_bound = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                idx.module_bound.add(stmt.name)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    idx.module_bound.add(alias.asname or alias.name.split(".")[0])
            else:
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        idx.module_bound.add(child.id)
        idx.any_bound = _bound_names(tree)

        for stmt in ast.walk(tree):
            if not isinstance(stmt, ast.ImportFrom):
                continue
            src = resolve_module_path(rel, stmt.module, stmt.level, self.files)
            raw = ("." * stmt.level) + (stmt.module or "")
            for alias in stmt.names:
                local = alias.asname or alias.name
                idx.from_imports[local] = (src, alias.name, raw)
        return idx

    # -- helpers -----------------------------------------------------------

    def matches(self, name: str) -> bool:
        return bool(SCREAMING_SNAKE.match(name) and self.pattern.search(name))

    def declared_matching(self) -> dict[str, str]:
        """{constant name: declaring module} for every matching module-level
        constant in the tree. Used to detect that a rename happened at all."""
        return {name: rels[0] for name, rels in self._global_decls.items()}

    # -- resolution --------------------------------------------------------

    def resolve(self, name: str, rel: str, stack: tuple[str, ...] = ()) -> ast.expr | None:
        key = (rel, name)
        if key in self._cache:
            return self._cache[key]
        if key in stack:  # circular definition; refuse rather than recurse
            return None
        self._cache[key] = None  # provisional, prevents runaway recursion
        result = self._resolve_uncached(name, rel, stack + (key,))
        self._cache[key] = result
        return result

    def _resolve_uncached(self, name: str, rel: str, stack: tuple[str, ...]) -> ast.expr | None:
        idx = self.modules.get(rel)
        if idx is None or idx.tree is None:
            return None

        if name in idx.decls:
            rhs = idx.decls[name]
            if not is_static_expr(rhs):
                return None
            return self.substitute(rhs, rel, stack)

        if name in idx.from_imports:
            src, original, _raw = idx.from_imports[name]
            if src is None:
                return None
            return self.resolve(original, src, stack)

        # Whole-tree fallback: the name is used here but declared elsewhere and
        # reached by something this index cannot see (a star import, a re-export
        # chain). Accept it only when every declaration in the tree agrees.
        candidates = self._global_decls.get(name, [])
        resolved = [self.resolve(name, other, stack) for other in candidates if other != rel]
        dumps = {ast.dump(expr) for expr in resolved if expr is not None}
        if len(dumps) == 1:
            return next(expr for expr in resolved if expr is not None)
        return None

    def substitute(self, node: ast.expr, rel: str, stack: tuple[str, ...] = ()) -> ast.expr:
        """Copy `node`, replacing every matching resolvable Name with its value,
        then constant-fold."""
        return fold(_Substituter(self, rel, stack).visit(copy_tree(node)))


def is_static_expr(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if not (isinstance(child.func, ast.Name) and child.func.id in ALLOWED_CALLS):
                return False
            continue
        if isinstance(child, STATIC_NODES):
            continue
        return False
    return True


def copy_tree(node: ast.AST) -> ast.AST:
    """Inlining puts the same declaration's RHS at many use sites; each needs
    its own node objects or the transformer would rewrite shared state."""
    return copy.deepcopy(node)


class _Substituter(ast.NodeTransformer):
    def __init__(self, index: RevisionIndex, rel: str, stack: tuple[str, ...]):
        self.index = index
        self.rel = rel
        self.stack = stack

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, ast.Load) and self.index.matches(node.id):
            value = self.index.resolve(node.id, self.rel, self.stack)
            if value is not None:
                return copy_tree(value)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        # `some_module.NAME_SKIP_REASON` — resolve through the module alias.
        if isinstance(node.ctx, ast.Load) and self.index.matches(node.attr) and isinstance(node.value, ast.Name):
            idx = self.index.modules.get(self.rel)
            src = None
            if idx is not None and node.value.id in idx.from_imports:
                src = idx.from_imports[node.value.id][0]
                if src is not None and Path(src).stem != node.value.id:
                    # `from x import y` where y is a module: from_imports stored
                    # the file it resolved to only if it really is one.
                    src = None if Path(src).stem != node.value.id else src
            if src is None:
                candidates = self.index._global_decls.get(node.attr, [])
                matching = [c for c in candidates if Path(c).stem == node.value.id]
                src = matching[0] if len(matching) == 1 else None
            if src is not None:
                value = self.index.resolve(node.attr, src, self.stack)
                if value is not None:
                    return copy_tree(value)
        return node


# --------------------------------------------------------------------------
# constant folding
# --------------------------------------------------------------------------


def _literal_text(value: ast.expr) -> str | None:
    """The string a JoinedStr element contributes, if it is statically known.

    Both halves matter. `f"phash-{reason}"` contributes a plain `Constant`;
    `f"{LANDS_PHASH_SKIP_REASON_PREFIX}{reason}"` — the same expression after
    the constant was extracted — contributes a `FormattedValue` wrapping the
    inlined `Constant`. Folding only whole f-strings would leave those two
    shapes structurally different at `values[0]` while their runtime values
    are identical, which is precisely the false positive this handles.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if (
        isinstance(value, ast.FormattedValue)
        and value.conversion in (-1, None)
        and (
            value.format_spec is None or (isinstance(value.format_spec, ast.JoinedStr) and not value.format_spec.values)
        )
        and isinstance(value.value, ast.Constant)
        and isinstance(value.value.value, (str, int, float, bool, type(None)))
    ):
        return str(value.value.value)
    return None


class _Folder(ast.NodeTransformer):
    changed = False

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        self.generic_visit(node)

        # Canonicalise element by element, merging runs of statically known
        # text, so a partially-foldable f-string still reaches one shape.
        merged: list[ast.expr] = []
        for value in node.values:
            text = _literal_text(value)
            if text is None:
                merged.append(value)
                continue
            if merged and isinstance(merged[-1], ast.Constant) and isinstance(merged[-1].value, str):
                merged[-1] = ast.Constant(value=merged[-1].value + text)
            else:
                merged.append(ast.Constant(value=text))

        if len(merged) == 1 and isinstance(merged[0], ast.Constant):
            self.changed = True
            return merged[0]
        if not merged:
            self.changed = True
            return ast.Constant(value="")
        if [ast.dump(v) for v in merged] != [ast.dump(v) for v in node.values]:
            self.changed = True
            node.values = merged
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.op, ast.Add)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.left.value, str)
            and isinstance(node.right.value, str)
        ):
            self.changed = True
            return ast.Constant(value=node.left.value + node.right.value)
        return node


def fold(node: ast.AST) -> ast.AST:
    for _ in range(10):  # fixpoint; nesting deeper than this is not real code
        folder = _Folder()
        folder.changed = False
        node = folder.visit(node)
        if not folder.changed:
            break
    return node


# --------------------------------------------------------------------------
# module normalisation
# --------------------------------------------------------------------------


class _Normaliser(ast.NodeTransformer):
    """Delete docstrings; delete matching constant declarations, their
    `__all__` entries, and the imports that pulled them in; inline every
    remaining matching reference; constant-fold."""

    def __init__(self, index: RevisionIndex, rel: str):
        self.index = index
        self.rel = rel

    def _strip_docstring(self, node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            del body[0]
            if not body:
                body.append(ast.Pass())

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self._strip_docstring(node)
        node.body = [s for s in node.body if not self._is_dropped_statement(s)]
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):  # noqa: N802
        self._strip_docstring(node)
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def _is_dropped_statement(self, stmt: ast.stmt) -> bool:
        if isinstance(stmt, ast.Assign):
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if targets and all(self.index.matches(t) for t in targets):
                return all(self.index.resolve(t, self.rel) is not None for t in targets)
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if self.index.matches(stmt.target.id):
                return self.index.resolve(stmt.target.id, self.rel) is not None
        return False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        kept = [a for a in node.names if not self.index.matches(a.asname or a.name)]
        if not kept:
            return None
        node.names = kept
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        # `__all__ = [...]`: drop the matching names, they no longer exist.
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets) and isinstance(
            node.value, (ast.List, ast.Tuple, ast.Set)
        ):
            node.value.elts = [
                e
                for e in node.value.elts
                if not (isinstance(e, ast.Constant) and isinstance(e.value, str) and self.index.matches(e.value))
            ]
            return node
        self.generic_visit(node)
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, ast.Load) and self.index.matches(node.id):
            value = self.index.resolve(node.id, self.rel)
            if value is not None:
                return copy_tree(value)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        return _Substituter(self.index, self.rel, ()).visit_Attribute(node)


def normalised_dump(index: RevisionIndex, rel: str) -> str | None:
    idx = index.modules.get(rel)
    if idx is None or idx.tree is None:
        return None
    tree = parse(index.sources[rel], rel)
    tree = _Normaliser(index, rel).visit(tree)
    tree = fold(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree)


def normalised_tree(index: RevisionIndex, rel: str) -> ast.AST | None:
    idx = index.modules.get(rel)
    if idx is None or idx.tree is None:
        return None
    tree = parse(index.sources[rel], rel)
    tree = _Normaliser(index, rel).visit(tree)
    tree = fold(tree)
    ast.fix_missing_locations(tree)
    return tree


# --------------------------------------------------------------------------
# first-difference reporting
# --------------------------------------------------------------------------


def first_difference(a: ast.AST | None, b: ast.AST | None, path: str = "Module") -> tuple[str, str, str] | None:
    """Deepest-first structural walk. Returns (path, base-side, head-side) with
    each side rendered as source, so a failure names a node and not a file."""
    if type(a) is not type(b):
        return (path, render(a), render(b))
    if not isinstance(a, ast.AST):
        return None if a == b else (path, repr(a), repr(b))

    for fieldname in a._fields:
        left = getattr(a, fieldname, None)
        right = getattr(b, fieldname, None)
        if isinstance(left, list) and isinstance(right, list):
            for i in range(max(len(left), len(right))):
                if i >= len(left) or i >= len(right):
                    return (
                        f"{path}.{fieldname}[{i}]",
                        render(left[i]) if i < len(left) else "<absent>",
                        render(right[i]) if i < len(right) else "<absent>",
                    )
                deeper = first_difference(left[i], right[i], f"{path}.{fieldname}[{i}]")
                if deeper:
                    return deeper
        elif isinstance(left, ast.AST) or isinstance(right, ast.AST):
            deeper = first_difference(left, right, f"{path}.{fieldname}")
            if deeper:
                return deeper
        elif left != right:
            return (f"{path}.{fieldname}", repr(left), repr(right))
    return None


def render(node: object, limit: int = 220) -> str:
    if node is None:
        return "<absent>"
    if isinstance(node, ast.AST):
        try:
            text = ast.unparse(node)
        except Exception:  # pragma: no cover - unparse is total for valid trees
            text = ast.dump(node)
        line = getattr(node, "lineno", None)
        prefix = f"(normalised line {line}) " if line else ""
        text = " ".join(text.split())
        if len(text) > limit:
            text = text[:limit] + " ..."
        return prefix + text
    return repr(node)


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check_references(index: RevisionIndex, label: str) -> list[str]:
    """The #567/#568 signature, needing only ONE revision: a matching constant
    that is imported from, or read in, a module where nothing declares it."""
    findings: list[str] = []
    for rel in sorted(index.modules):
        idx = index.modules[rel]
        if idx.tree is None:
            continue

        for local, (src, original, raw) in sorted(idx.from_imports.items()):
            if not index.matches(original) or src is None:
                continue
            target = index.modules.get(src)
            if target is None or target.tree is None:
                continue
            if original not in target.module_bound and original not in target.decls:
                findings.append(
                    f"::error file={rel}::at {label}: `from {raw} import {original}` — "
                    f"{src} declares no `{original}`. This is an ImportError at module-import time."
                )

        for node in ast.walk(idx.tree):
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            if not index.matches(node.id):
                continue
            if node.id in idx.any_bound or node.id in idx.from_imports:
                continue
            if index.resolve(node.id, rel) is not None or node.id in index._global_decls:
                continue
            findings.append(
                f"::error file={rel},line={node.lineno}::at {label}: `{node.id}` is read here but "
                f"declared nowhere in the tree. NameError at runtime."
            )
    return findings


def scope_modules(base: RevisionIndex, head: RevisionIndex, everything: bool) -> tuple[list[str], dict[str, str]]:
    """Modules to compare, plus the renamed/removed constants that put them
    there. Scope is deliberately narrow: the modules that touch a constant
    whose DECLARED NAME changed between the two revisions. `--all` widens it
    to every module mentioning the pattern."""
    base_names = base.declared_matching()
    head_names = head.declared_matching()
    moved = {n: base_names.get(n) or head_names.get(n) or "?" for n in set(base_names) ^ set(head_names)}

    shared = sorted(set(base.sources) & set(head.sources))
    if everything:
        return [
            rel for rel in shared if base.pattern.search(base.sources[rel]) or head.pattern.search(head.sources[rel])
        ], moved

    if not moved:
        return [], moved

    targets = []
    for rel in shared:
        texts = (base.sources[rel], head.sources[rel])
        if any(re.search(rf"\b{re.escape(name)}\b", text) for name in moved for text in texts):
            targets.append(rel)
    return targets, moved


def check_equivalence(base: RevisionIndex, head: RevisionIndex, targets: list[str]) -> list[str]:
    findings: list[str] = []
    for rel in targets:
        left = normalised_dump(base, rel)
        right = normalised_dump(head, rel)
        if left is None or right is None:
            continue
        if left == right:
            continue
        diff = first_difference(normalised_tree(base, rel), normalised_tree(head, rel))
        if diff is None:  # pragma: no cover - dumps differ but walk agrees
            findings.append(f"::error file={rel}::normalised trees differ (no node-level difference located)")
            continue
        path, before, after = diff
        findings.append(
            f"::error file={rel}::normalised trees differ at {path}\n"
            f"        {base.rev}: {before}\n"
            f"        {head.rev}: {after}"
        )
    return findings


def declaration_value_notes(base: RevisionIndex, head: RevisionIndex, targets: list[str]) -> list[str]:
    """Informational, never fatal: a matching constant whose VALUE changed but
    which nothing references is deleted from both sides by normalisation, so
    the tree comparison cannot see it. A legitimate constant-EXTRACTION
    refactor also moves this multiset, which is why it is not a failure."""
    notes: list[str] = []

    def values(index: RevisionIndex, rel: str) -> dict[str, ast.expr]:
        idx = index.modules.get(rel)
        if idx is None or idx.tree is None:
            return {}
        out: dict[str, ast.expr] = {}
        for name, rhs in idx.decls.items():
            if index.matches(name) and is_static_expr(rhs):
                folded = index.substitute(rhs, rel)
                out[ast.dump(folded)] = folded
        return out

    for rel in targets:
        left = values(base, rel)
        right = values(head, rel)
        for dump in sorted(set(left) - set(right)):
            notes.append(f"note: {rel}: declared constant value {render(left[dump], 120)} exists only at {base.rev}")
        for dump in sorted(set(right) - set(left)):
            notes.append(f"note: {rel}: declared constant value {render(right[dump], 120)} exists only at {head.rev}")
    return notes


def unresolvable_notes(index: RevisionIndex, targets: list[str], label: str) -> list[str]:
    notes: list[str] = []
    for rel in targets:
        idx = index.modules.get(rel)
        if idx is None or idx.tree is None:
            continue
        for name, rhs in sorted(idx.decls.items()):
            if index.matches(name) and not is_static_expr(rhs):
                notes.append(
                    f"note: {rel}: `{name}` at {label} has a non-static value and was NOT inlined — "
                    f"the equivalence proof does not cover it"
                )
    return notes


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--head", default="HEAD", help="revision under test (default: HEAD)")
    parser.add_argument(
        "--base",
        default=None,
        help="revision to compare against (default: merge-base of --head with origin/master)",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"regex searched against ALL-CAPS module-level constant names (default: {DEFAULT_PATTERN!r})",
    )
    parser.add_argument("--all", action="store_true", help="compare every module mentioning the pattern")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=None,
        metavar="PATH",
        help="compare exactly these repo-relative modules instead of the derived scope",
    )
    parser.add_argument(
        "--check-references",
        action="store_true",
        help="run only the single-revision name-resolution check against --head",
    )
    parser.add_argument("--repo", default=None, help="repository to run in (default: this checkout)")
    parser.add_argument("--quiet-notes", action="store_true", help="suppress informational note: lines")
    args = parser.parse_args(argv)

    cwd = Path(args.repo).resolve() if args.repo else REPO_ROOT
    pattern = re.compile(args.pattern)

    head_rev = git("rev-parse", "--short", args.head, cwd=cwd).strip()
    head = RevisionIndex(head_rev, read_python_tree(args.head, cwd=cwd), pattern)

    findings = check_references(head, f"{args.head} ({head_rev})")
    notes: list[str] = []

    if args.check_references:
        _emit(findings, notes, args)
        if not findings:
            print(
                f"constant-rename-equivalence: references clean at {args.head} ({head_rev}), "
                f"{len(head.modules)} modules."
            )
        return len(findings)

    base_ref = args.base or default_base(args.head, cwd=cwd)
    base_rev = git("rev-parse", "--short", base_ref, cwd=cwd).strip()
    base = RevisionIndex(base_rev, read_python_tree(base_ref, cwd=cwd), pattern)

    findings += check_references(base, f"{base_ref} ({base_rev})")

    targets, moved = scope_modules(base, head, args.all)
    if args.paths:
        targets = [p for p in args.paths if p in base.sources and p in head.sources]
    elif not moved and not args.all:
        _emit(findings, notes, args)
        print(
            f"constant-rename-equivalence: no constant matching /{args.pattern}/ was renamed or "
            f"removed between {base_rev} and {head_rev} — nothing to prove. "
            f"(References checked: {len(head.modules)} modules.)"
        )
        return len(findings)

    if moved:
        print(f"Constants whose declared name changed between {base_rev} and {head_rev}:")
        for name in sorted(moved):
            side = "base only" if name in base.declared_matching() else "head only"
            print(f"  - {name}  ({side}, {moved[name]})")
        print()

    findings += check_equivalence(base, head, targets)
    notes += unresolvable_notes(head, targets, f"{args.head}")
    notes += declaration_value_notes(base, head, targets)

    _emit(findings, notes, args)
    if findings:
        print(
            f"\n{len(findings)} constant-rename equivalence violation(s) across " f"{len(targets)} module(s) compared."
        )
    else:
        print(
            f"constant-rename-equivalence: {len(targets)} module(s) normalise IDENTICALLY "
            f"between {base_rev} and {head_rev} — the rename is behaviour-preserving."
        )
    return len(findings)


def _emit(findings: list[str], notes: list[str], args: argparse.Namespace) -> None:
    for finding in findings:
        print(finding)
    if not args.quiet_notes:
        for note in notes:
            print(note)


if __name__ == "__main__":
    raise SystemExit(main())
