"""
The pipeline's channel roster, DERIVED FROM CODE.

WHAT A "CHANNEL" IS, AND WHY IT IS NOT AN IDENTITY
--------------------------------------------------
A channel is one thing this pipeline is supposed to produce. The unit is
NOT the `anonymous_id`: `local-fallback-v1` casts border-colour chips,
frame-style chips and bleed-edge chips under that ONE identity, and the
2026-07-29 composition audit (`docs/reports/2026-07-29-pipeline-coverage-
composition-audit.md`) found border chips healthy while frame-style and
bleed-edge sat at ZERO under it. An identity-level count reports that
identity as fine while two thirds of it is dead. So a `CardTagVote`
channel is keyed `(model, identity, TAG)`, and the tag is derived, not
assumed.

Three roster families are derived here:

  * VOTE channels  - `(vote model, anonymous_id, tag)`, from the actual
    vote-construction sites in the tree.
  * EXTRACTOR channels - `(extractor key, version)`, from
    `image_evidence.py`'s `extractor_versions["<key>"] = <CONST>` stores.
  * SKIP-REASON channels - from module-level `*_SKIP_REASON` declarations.

WHY DERIVED AND NEVER HAND-WRITTEN
-----------------------------------
`.github/scripts/docs_lint.py` already derives calculator identities from
`*_ANONYMOUS_ID` and skip reasons from `*_SKIP_REASON` for exactly this
reason, and states it: "a second hand-maintained list inside the linter
would reproduce exactly the drift this rule exists to prevent - it would
just move the stale list from the doc into the check." Same here. A
hand-written channel list is a list of the channels somebody REMEMBERED,
and the one it forgets is precisely the dormant one a coverage report
exists to find.

THE SCAN IS RECURSIVE, DELIBERATELY (PR #588)
----------------------------------------------
Both docs_lint roster tethers originally globbed `*.py` NON-recursively.
That was not a scoping decision, it was an accident with a live
consequence: `management/commands/` was never scanned, so a real
vote-casting identity declared there was invisible to the derivation -
absent from the derived set, absent from the docs, absent from the
allowlist, and dormant in production with nothing anywhere that would say
so. `roster_source_files()` below uses `rglob` and excludes `tests/` ON
PURPOSE (fixture modules declare identity-shaped literals that are not
production roster members) and INCLUDES `migrations/` on purpose (a
migration that pins an identity is operating on real rows keyed by it).
Do not reintroduce a non-recursive scan.

READING, NEVER IMPORTING
-------------------------
Everything is read with `ast`. Nothing here imports Django or executes
application code, so the roster can be derived in CI, in a test, or from a
checkout with no database - the same discipline
`.github/scripts/check_extractor_manifest_sync.py` adopted for the
extractor manifest, and for the same reason.

AN EMPTY DERIVATION IS ITSELF A FINDING
-----------------------------------------
Every `derive_*` function returns `(members, findings)` and reports a hard
finding when it derives NOTHING. A roster that comes back empty compares
nothing to nothing and would let the report print "all clear" for a
pipeline it never looked at. That is the exact defect class this repo has
spent a week removing, so the empty case is loud rather than silent. See
`check_extractor_manifest_sync.derive_expected_manifest` for the same rule
stated the same way.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

CARDPICKER_DIR = Path(__file__).resolve().parent

# Directory names excluded from the roster scan. Everything else under
# `cardpicker/` is scanned RECURSIVELY - see the module docstring.
ROSTER_SCAN_EXCLUDED_DIRS = frozenset({"tests", "__pycache__"})

# The four vote models a machine channel can write. `PrintingTagVote` is NOT
# here and must not be re-added: it was RETIRED with its table in PR #615
# (migration 0101, owner ruling) - 0 rows, no consensus resolver, no reader
# outside the admin, and its one machine writer never ran.
VOTE_MODEL_NAMES: tuple[str, ...] = (
    "CardPrintingTag",
    "CardTagVote",
    "CardArtistVote",
    "CardIllustrationVote",
)

# The model whose rows carry a per-tag grain, and therefore the only one whose
# channels are split by tag.
TAG_GRAINED_MODEL = "CardTagVote"

# Manager methods that persist. `bulk_create` is included because the batch
# pattern (`votes_batch.append(CardTagVote(...))` then one `bulk_create`) is
# how most calculators in this tree write, and the CONSTRUCTOR call is what
# carries the `anonymous_id=` kwarg - so constructor calls are collected too.
WRITE_MANAGER_METHODS = frozenset({"create", "update_or_create", "get_or_create", "bulk_create"})

IDENTITY_KWARG = "anonymous_id"
TAG_KWARG = "tag"

# The `extractor_versions["<key>"] = <CONST>` manifest, same derivation shape
# as `.github/scripts/check_extractor_manifest_sync.py` (which is the CI
# tether over the SAME facts). Deliberately the same constants, read the same
# way, so the two can never disagree about what the manifest is.
MANIFEST_DICT_NAME = "extractor_versions"
EXTRACTOR_VERSION_SUFFIX = "_EXTRACTOR_VERSION"

SKIP_REASON_SUFFIX = "_SKIP_REASON"
ANONYMOUS_ID_SUFFIX = "_ANONYMOUS_ID"

# Identities that write NO vote rows of any kind, so a "this channel produced
# zero votes" reading of them is meaningless rather than alarming. Kept here
# with per-entry reasons, the same convention as docs_lint.py's
# CALCULATOR_ROSTER_ALLOWLIST - an exclusion has to be a visible decision.
# These are excluded from the VOTE roster only; nothing here suppresses a
# skip-reason or extractor channel.
NON_VOTING_IDENTITIES: dict[str, str] = {
    "evidence-transfer-v1": (
        "not a vote channel - cardpicker/evidence_transfer.py copies existing evidence "
        "between cards and casts NO votes of any kind (its only DB footprint is a "
        "CardScanLog skip row), so it has no vote population to count."
    ),
    "question-feed-hypothetical-vote": (
        "not a vote channel - cardpicker/question_feed.py uses this identity to model what "
        "a vote WOULD weigh if the user cast it, so the UI can preview the effect. Nothing "
        "is ever persisted under it."
    ),
}


# ---------------------------------------------------------------------------
# Source scanning
# ---------------------------------------------------------------------------


def roster_source_files(src_dir: Optional[Path] = None) -> list[Path]:
    """
    Every Python file whose module-level constants participate in a roster,
    RECURSIVELY, excluding `tests/`.

    This is `docs_lint._roster_source_files` deliberately reproduced on the
    application side rather than imported: `.github/scripts/` is not an
    importable package from Django, and the alternative - a non-recursive
    scan - is the specific hole PR #588 closed. See the module docstring.
    """
    src_dir = src_dir or CARDPICKER_DIR
    if not src_dir.is_dir():
        return []
    return sorted(
        py for py in src_dir.rglob("*.py") if not (ROSTER_SCAN_EXCLUDED_DIRS & set(py.relative_to(src_dir).parts[:-1]))
    )


def _parse_tree(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _module_level_bindings(tree: ast.Module) -> Iterable[tuple[str, ast.expr]]:
    """(name, value_node) for every module-level `NAME = ...`, plain or annotated.

    The annotated form is not a stylistic variant to skip:
    `ATTRIBUTE_CHIP_TAG_NAMES: list[str] = [...]` is written that way, and an
    Assign-only walk reads it as missing.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            yield node.target.id, node.value


def _literal(node: ast.expr) -> object:
    """`ast.literal_eval` with `frozenset(...)`/`set(...)` wrappers unwrapped, else None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"frozenset", "set"}:
        if not node.args:
            return set()
        node = node.args[0]
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _strings_from(value: object) -> tuple[str, ...]:
    """Every string reachable one level into a literal - a bare string, a
    list/tuple/set of strings, or a dict's VALUES (`BORDER_COLOR_TO_TAG`
    maps a layout class to a tag NAME, so the tag names are its values)."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(v for v in value.values() if isinstance(v, str))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(v for v in value if isinstance(v, str))
    return ()


@dataclass
class SourceIndex:
    """Every module-level constant in the scanned tree, parsed once.

    Names are indexed TREE-WIDE as well as per-module because constants cross
    module boundaries by import (`local_layout_class_cast` imports
    `BORDER_COLOR_TO_TAG` from `local_fallback`), and following import
    statements exactly would mean resolving relative/aliased imports for no
    gain: a constant NAME in this tree is effectively unique, and where it is
    not (`DEDUCTIVE_BACKFILL_ANONYMOUS_ID` is declared in four modules) every
    declaration carries the SAME literal. `ambiguous` records any name that
    genuinely resolves to two different values, so a collision is reported
    rather than silently resolved to whichever was parsed last.
    """

    #: the directory that was scanned - site strings are relative to it, so a
    #: caller scanning a different tree (a test, a mutation proof) gets paths
    #: inside THAT tree rather than a crash or a path from the real one.
    root: Path = CARDPICKER_DIR
    trees: dict[Path, ast.Module] = field(default_factory=dict)
    #: constant name -> every distinct literal string set it is bound to
    strings: dict[str, set[str]] = field(default_factory=dict)
    #: constant name -> declaration sites
    sites: dict[str, list[str]] = field(default_factory=dict)
    ambiguous: dict[str, set[str]] = field(default_factory=dict)

    def resolve(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(self.strings.get(name, ())))


def build_source_index(src_dir: Optional[Path] = None) -> SourceIndex:
    src_dir = src_dir or CARDPICKER_DIR
    index = SourceIndex(root=src_dir)
    for path in roster_source_files(src_dir):
        tree = _parse_tree(path)
        if tree is None:
            continue
        index.trees[path] = tree
        rel = path.relative_to(src_dir)
        for name, value in _module_level_bindings(tree):
            strings = _strings_from(_literal(value))
            if not strings:
                continue
            existing = index.strings.setdefault(name, set())
            if existing and existing != set(strings):
                index.ambiguous.setdefault(name, set()).update(existing | set(strings))
            existing.update(strings)
            index.sites.setdefault(name, []).append(f"{src_dir.name}/{rel}:{value.lineno}")
    return index


# ---------------------------------------------------------------------------
# Channel records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Channel:
    """One thing the pipeline is supposed to produce.

    `key` is the stable identifier used everywhere else (the report, the
    zero-declaration table, the tests). For a tag-grained channel it INCLUDES
    the tag, which is the whole point of this module - see the docstring.
    """

    family: str  # "vote" | "extractor" | "skip_reason"
    key: str
    identity: str
    model: Optional[str] = None
    tag: Optional[str] = None
    version: Optional[str] = None
    sites: tuple[str, ...] = ()
    #: qualified names of the functions that write this channel, for reachability
    writers: tuple[str, ...] = ()
    #: True when the tag could not be resolved statically from the cast site
    tag_unresolved: bool = False
    #: extractor channels only - the `ImageEvidence` fields this extractor populates.
    #: Success for an extractor is a POPULATED FIELD, never a manifest key: all
    #: eleven extractors report 100% key presence while `bleed_diff_mm` is NULL on
    #: 97.9% of rows and `artist_ocr_name` is blank on 206,629. A key-presence
    #: count reports "gap 0" for every one of them.
    fields: tuple[str, ...] = ()
    #: extractor channels only - other extractors sharing this one's field block
    shares_fields_with: tuple[str, ...] = ()

    def label(self) -> str:
        return self.key


def _channel_key(family: str, identity: str, model: Optional[str], tag: Optional[str]) -> str:
    if family == "vote":
        base = f"vote:{model}:{identity}"
        return f"{base}:{tag}" if tag else base
    return f"{family}:{identity}"


# ---------------------------------------------------------------------------
# Vote channels
# ---------------------------------------------------------------------------


def _enclosing_functions(tree: ast.Module) -> dict[int, tuple[str, ast.AST]]:
    """node id -> (qualname, function node) for every statement inside a def.

    Built by walking definitions rather than by line arithmetic so a nested
    def is attributed to itself, not to its parent.
    """
    out: dict[int, tuple[str, ast.AST]] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for inner in ast.walk(child):
                        out.setdefault(id(inner), (qual, child))
                visit(child, qual)
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _is_vote_call(node: ast.Call) -> Optional[str]:
    """The vote model this call persists/constructs, or None.

    Two shapes count: the bare constructor `CardTagVote(...)` (the batch
    pattern - the constructor is where `anonymous_id=` lives) and
    `CardTagVote.objects.<write method>(...)`.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id in VOTE_MODEL_NAMES:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in WRITE_MANAGER_METHODS:
        inner = func.value
        if isinstance(inner, ast.Attribute) and inner.attr == "objects":
            if isinstance(inner.value, ast.Name) and inner.value.id in VOTE_MODEL_NAMES:
                return inner.value.id
    return None


def _kwarg(node: ast.Call, name: str) -> Optional[ast.expr]:
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    # `update_or_create(defaults={...})` keeps the real fields one level down
    for kw in node.keywords:
        if kw.arg == "defaults" and isinstance(kw.value, ast.Dict):
            for k, v in zip(kw.value.keys, kw.value.values):
                if isinstance(k, ast.Constant) and k.value == name:
                    return v
    return None


def _resolve_identity(node: ast.expr, index: SourceIndex) -> tuple[str, ...]:
    """The `anonymous_id=` value(s) of a cast site, or () when it is dynamic.

    A dynamic identity is NOT guessed at. `views.py` passes a request-supplied
    id; `harvest_probe` passes a parameter. Reporting those as "() - dynamic"
    is the honest answer and keeps them out of the machine roster, which is
    what the report is auditing.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return index.resolve(node.id)
    return ()


def _local_string_bindings(fn: ast.AST, index: SourceIndex) -> dict[str, tuple[str, ...]]:
    """Local names inside `fn` that provably hold tag-name strings.

    THREE shapes, all of them present in this tree, none of them guessed at:

        tag_name = "appropriate-bleed"          # literal
        tag_name = BLEED_EDGE_TAG_NAME          # module constant
        tag_name = BORDER_COLOR_TO_TAG.get(x)   # a mapping's VALUES

    The third is why this function has to exist at all.
    `local_fallback.cast_border_attribute_vote` and `cast_frame_style_vote`
    both do `Tag.objects.filter(name=tag_name)` where `tag_name` came from
    `BORDER_COLOR_TO_TAG` / `FRAME_STYLE_TO_TAG` one line earlier. Without
    this, BOTH resolve to nothing, fall through to the module-wide scope, and
    collapse into whichever chip family DID resolve - which is precisely the
    identity-level merge this whole module exists to prevent: border, frame
    and bleed chips are three channels under ONE `anonymous_id`, and the
    audit found two of the three at zero while the third was healthy.
    """
    out: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if value is None:
            continue
        # `D.get(...)` / `D[...]` -> the mapping's values
        source: Optional[ast.expr] = None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get":
            source = value.func.value
        elif isinstance(value, ast.Subscript):
            source = value.value
        else:
            source = value

        names: tuple[str, ...] = ()
        if isinstance(source, ast.Constant) and isinstance(source.value, str):
            names = (source.value,)
        elif isinstance(source, ast.Name):
            names = index.resolve(source.id)
        if not names:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out.setdefault(target.id, ())
                out[target.id] = tuple(sorted(set(out[target.id]) | set(names)))
    return out


def _tag_names_in_scope(fn: ast.AST, index: SourceIndex) -> tuple[str, ...]:
    """Tag names a `Tag.objects` lookup inside `fn` narrows to.

    THE RESOLUTION RULE, and why it is this one. Every `CardTagVote` write
    site in this tree reaches its `Tag` row through a `Tag.objects` lookup
    keyed by NAME - `Tag.objects.filter(name=BLEED_EDGE_TAG_NAME)`,
    `Tag.objects.filter(name=tag_name)` where `tag_name` came from
    `BORDER_COLOR_TO_TAG`, or `Tag.objects.filter(name__in=set(
    BORDER_COLOR_TO_TAG.values()))`. So the tag set of a cast site is the
    set of names its enclosing function looks up. That is a fact about the
    code, not a mapping anybody maintains, which is the requirement.

    Chasing the `tag=` expression backwards instead would have to model
    `tag_by_name[verdict.tag_name]` and `BORDER_COLOR_TO_TAG.get(...)` - a
    dataflow engine's job, and one that fails open (an unmodelled expression
    silently yields no tag, i.e. a channel that vanishes from the roster).
    Collecting the lookups fails CLOSED instead: an unrecognised lookup
    yields no names and the channel is reported `tag_unresolved`, which the
    report surfaces rather than swallows.
    """
    names: set[str] = set()
    local = _local_string_bindings(fn, index)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        inner = func.value
        if not (isinstance(inner, ast.Attribute) and inner.attr == "objects"):
            continue
        if not (isinstance(inner.value, ast.Name) and inner.value.id == "Tag"):
            continue
        for kw in node.keywords:
            if kw.arg not in {"name", "name__in"}:
                continue
            value = kw.value
            # `set(D.values())` / `D.values()` -> the dict's values
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in {"set", "list", "tuple", "frozenset"}
            ):
                value = value.args[0] if value.args else value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "values":
                value = value.func.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
            elif isinstance(value, ast.Name):
                # Module constant first, then a local bound to one - see
                # `_local_string_bindings` for why the local case is load-bearing.
                names.update(index.resolve(value.id) or local.get(value.id, ()))
            else:
                literal = _strings_from(_literal(value))
                names.update(literal)
    return tuple(sorted(names))


def derive_vote_channels(index: Optional[SourceIndex] = None) -> tuple[list[Channel], list[str]]:
    """
    DERIVE `(vote model, anonymous_id, tag)` channels from the cast sites.

    Returns (channels, findings). Findings are non-empty when the derivation
    itself failed - see the module docstring on why that must be loud.
    """
    index = index or build_source_index()
    findings: list[str] = []
    # key -> (model, identity, tag, sites, writers, tag_unresolved)
    collected: dict[str, dict[str, Any]] = {}

    for path, tree in index.trees.items():
        mod_rel = str(path.relative_to(index.root))
        rel = f"{index.root.name}/{mod_rel}"
        enclosing = _enclosing_functions(tree)
        # A tag lookup may live in a different function from the cast site
        # (`local_detect_ai_art` resolves its Tag row in the caller and passes
        # it in), so the module is the fallback scope. Function scope is
        # preferred because `local_fallback` casts THREE different chip
        # families from one module and a module-wide read would merge them.
        module_tags = _tag_names_in_scope(tree, index)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            model = _is_vote_call(node)
            if model is None:
                continue
            identity_node = _kwarg(node, IDENTITY_KWARG)
            if identity_node is None:
                continue
            identities = _resolve_identity(identity_node, index)
            if not identities:
                continue  # dynamic (human/parameterised) - not a machine channel
            qual, fn = enclosing.get(id(node), ("<module>", tree))
            site = f"{rel}:{node.lineno} ({qual})"

            if model == TAG_GRAINED_MODEL:
                tags = _tag_names_in_scope(fn, index) or module_tags
            else:
                tags = ()

            for identity in identities:
                if identity in NON_VOTING_IDENTITIES:
                    continue
                targets = tags if (model == TAG_GRAINED_MODEL and tags) else (None,)
                for tag in targets:
                    key = _channel_key("vote", identity, model, tag)
                    entry = collected.setdefault(
                        key,
                        {
                            "model": model,
                            "identity": identity,
                            "tag": tag,
                            "sites": [],
                            "writers": set(),
                            "unresolved": model == TAG_GRAINED_MODEL and tag is None,
                        },
                    )
                    entry["sites"].append(site)
                    entry["writers"].add(f"{mod_rel}::{qual}")

    channels = [
        Channel(
            family="vote",
            key=key,
            identity=e["identity"],
            model=e["model"],
            tag=e["tag"],
            sites=tuple(sorted(e["sites"])),
            writers=tuple(sorted(e["writers"])),
            tag_unresolved=bool(e["unresolved"]),
        )
        for key, e in sorted(collected.items())
    ]

    if not channels:
        findings.append(
            "channel roster derivation FAILED: no vote channels derived from "
            f"{CARDPICKER_DIR}. This report gates on per-channel row counts, so an empty "
            "vote roster would compare nothing to nothing and print a clean result for a "
            "pipeline it never inspected. The empty derivation is the finding."
        )
    for name, values in sorted(index.ambiguous.items()):
        if name.endswith(ANONYMOUS_ID_SUFFIX):
            findings.append(
                f"channel roster derivation AMBIGUOUS: constant `{name}` resolves to more than "
                f"one literal ({', '.join(sorted(values))}) across the tree, so a cast site "
                f"using it cannot be attributed to one identity. Rename one of them."
            )
    return channels, findings


# ---------------------------------------------------------------------------
# Extractor channels
# ---------------------------------------------------------------------------


FIELDS_DICT_NAME = "fields"


def _extractor_field_groups(tree: ast.Module) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Attribute each `ImageEvidence` field to the extractor that writes it.

    `compute_card_evidence` is one long linear function laid out as
    "do extractor N's work, then `extractor_versions['N'] = VERSION`". So a
    `fields["x"] = ...` store belongs to the NEXT manifest store at or after
    its line. That is a positional rule, and positional rules deserve
    suspicion, so the one place it is genuinely ambiguous is handled
    explicitly rather than fudged: the OCR group closes with THREE manifest
    stores back to back
    (`collector_line_ocr`/`artist_ocr`/`collector_line_tsv`) over ONE shared
    block of field writes. Splitting that block between them would be an
    invention. Instead the whole run of consecutive stores SHARES the block
    and each records the others in `shares_fields_with`, so the report says
    "these three extractors cannot be told apart by field, here is why"
    rather than silently crediting one and showing the other two at zero
    fields written - which would read exactly like two dead extractors.

    Returns ({extractor key: field names}, {extractor key: sharing group}).
    """
    events: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if not (isinstance(target.value, ast.Name) and isinstance(target.slice, ast.Constant)):
                continue
            if not isinstance(target.slice.value, str):
                continue
            if target.value.id == FIELDS_DICT_NAME:
                events.append((node.lineno, "field", target.slice.value))
            elif target.value.id == MANIFEST_DICT_NAME:
                events.append((node.lineno, "version", target.slice.value))

    events.sort()
    groups: dict[str, set[str]] = {}
    members: dict[str, set[str]] = {}
    pending: set[str] = set()
    index = 0
    while index < len(events):
        _lineno, kind, name = events[index]
        if kind == "field":
            pending.add(name)
            index += 1
            continue
        run = []
        while index < len(events) and events[index][1] == "version":
            run.append(events[index][2])
            index += 1
        for key in run:
            groups.setdefault(key, set()).update(pending)
            members.setdefault(key, set()).update(run)
        pending = set()
    return groups, members


def derive_extractor_channels(index: Optional[SourceIndex] = None) -> tuple[list[Channel], list[str]]:
    """
    DERIVE the Stage C extractor manifest - `{key: version}` - from
    `image_evidence.py`'s own `extractor_versions["<key>"] = <CONST>` stores.

    Same facts and same technique as
    `.github/scripts/check_extractor_manifest_sync.py`, deliberately: that
    script is the CI tether keeping `run_image_evidence_cohort`'s re-typed
    copy honest, and this is the runtime reader. Both read the assignments,
    not the copy, so neither can be fooled by a stale hand-written list.
    """
    index = index or build_source_index()
    findings: list[str] = []
    # Located by NAME within the already-scanned index rather than by an
    # absolute path, so a caller scanning a different tree (a test, a
    # mutation proof) is measuring that tree and not silently reading the
    # real one behind its own back.
    tree = next((t for path, t in index.trees.items() if path.name == "image_evidence.py"), None)
    if tree is None:
        return [], [
            "channel roster derivation FAILED: cardpicker/image_evidence.py could not be "
            "parsed, so the Stage C extractor manifest could not be derived. An unmeasured "
            "manifest must never read as a healthy one."
        ]

    versions = {
        name: next(iter(index.resolve(name)), None) for name in index.strings if name.endswith(EXTRACTOR_VERSION_SUFFIX)
    }

    field_groups, group_members = _extractor_field_groups(tree)

    channels: list[Channel] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if not (isinstance(target.value, ast.Name) and target.value.id == MANIFEST_DICT_NAME):
                continue
            if not (isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            key = target.slice.value
            if key in seen:
                continue
            seen.add(key)
            channels.append(
                Channel(
                    family="extractor",
                    key=_channel_key("extractor", key, None, None),
                    identity=key,
                    version=versions.get(node.value.id),
                    sites=(f"{index.root.name}/image_evidence.py:{node.lineno} ({node.value.id})",),
                    fields=tuple(sorted(field_groups.get(key, ()))),
                    shares_fields_with=tuple(sorted(m for m in group_members.get(key, ()) if m != key)),
                )
            )

    if not channels:
        findings.append(
            'channel roster derivation FAILED: no `extractor_versions["<key>"] = <CONST>` '
            "stores found in cardpicker/image_evidence.py. Stage C coverage would be reported "
            "against an empty manifest, which passes vacuously. The empty derivation is the "
            "finding."
        )
    return sorted(channels, key=lambda c: c.key), findings


# ---------------------------------------------------------------------------
# Abstention channels
# ---------------------------------------------------------------------------


def derive_abstention_channels(index: Optional[SourceIndex] = None) -> tuple[list[Channel], list[str]]:
    """
    DERIVE the identities that write `CardScanLog` rows - the ABSTENTION
    channels.

    An abstention is a CONCLUSION, not an absence (owner, 2026-07-30): the
    channel looked, could not decide, and SAID WHY. Some channels produce
    nothing else by design - `stage-d-slow-path-v1` is a router that writes
    `to-review` scan-log rows and casts no votes at all - so a roster built
    only from vote-cast sites would show it as a permanently-zero vote
    channel and report a working router as dead. That is the same
    misclassification, one table over, that this whole module exists to stop.

    The skip REASON is deliberately not fixed here. Most write sites pass it
    dynamically (`skip_reason=outcome.skip_reason`, `skip_reason=verdict.
    skip_reason`) precisely because one identity emits several; the reason
    breakdown is read from the rows at report time, against the derived
    skip-reason roster.
    """
    index = index or build_source_index()
    collected: dict[str, dict[str, Any]] = {}

    for path, tree in index.trees.items():
        mod_rel = str(path.relative_to(index.root))
        rel = f"{index.root.name}/{mod_rel}"
        enclosing = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_scanlog = (isinstance(func, ast.Name) and func.id == "CardScanLog") or (
                isinstance(func, ast.Attribute)
                and func.attr in WRITE_MANAGER_METHODS
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "objects"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "CardScanLog"
            )
            if not is_scanlog:
                continue
            identity_node = _kwarg(node, IDENTITY_KWARG)
            if identity_node is None:
                continue
            identities = _resolve_identity(identity_node, index)
            if not identities:
                continue  # dynamic - e.g. persist_evidence's per-extractor rows
            qual, _fn = enclosing.get(id(node), ("<module>", tree))
            for identity in identities:
                entry = collected.setdefault(identity, {"sites": [], "writers": set()})
                entry["sites"].append(f"{rel}:{node.lineno} ({qual})")
                entry["writers"].add(f"{mod_rel}::{qual}")

    channels = [
        Channel(
            family="abstention",
            key=_channel_key("abstention", identity, None, None),
            identity=identity,
            sites=tuple(sorted(e["sites"])),
            writers=tuple(sorted(e["writers"])),
        )
        for identity, e in sorted(collected.items())
    ]
    findings: list[str] = []
    if not channels:
        findings.append(
            "channel roster derivation FAILED: no `CardScanLog` write sites with a statically "
            "resolvable `anonymous_id` found under cardpicker/. Abstention coverage would be "
            "reported against an empty roster. The empty derivation is the finding."
        )
    return channels, findings


# ---------------------------------------------------------------------------
# Skip-reason channels
# ---------------------------------------------------------------------------


def derive_skip_reason_channels(index: Optional[SourceIndex] = None) -> tuple[list[Channel], list[str]]:
    """
    DERIVE the `CardScanLog.skip_reason` roster from module-level
    `*_SKIP_REASON = "<literal>"` declarations.

    Identical source of truth to `docs_lint._declared_skip_reasons` - the
    2026-07-29 declaration-convention sweep exists precisely so this roster
    IS derivable, and both readers depend on that convention holding.
    """
    index = index or build_source_index()
    channels = [
        Channel(
            family="skip_reason",
            key=_channel_key("skip_reason", value, None, None),
            identity=value,
            sites=tuple(index.sites.get(name, ())),
        )
        for name in sorted(index.strings)
        if name.endswith(SKIP_REASON_SUFFIX)
        for value in sorted(index.strings[name])
    ]
    # One value can be declared by several calculators under different
    # prefixed constants ("no-evidence", "ambiguous", "frame-mismatch"), so
    # collapse to one channel per VALUE - the value is what the column holds.
    merged: dict[str, Channel] = {}
    for channel in channels:
        existing = merged.get(channel.key)
        if existing is None:
            merged[channel.key] = channel
        else:
            merged[channel.key] = Channel(
                family="skip_reason",
                key=existing.key,
                identity=existing.identity,
                sites=tuple(sorted(set(existing.sites) | set(channel.sites))),
            )

    findings: list[str] = []
    if not merged:
        findings.append(
            "channel roster derivation FAILED: no module-level `*_SKIP_REASON` declarations "
            "found under cardpicker/. Skip-reason coverage would be reported against an empty "
            "roster. The empty derivation is the finding."
        )
    return [merged[k] for k in sorted(merged)], findings


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------

#: Modules whose functions are pipeline ENTRY POINTS - something outside the
#: application calls them. A channel reachable from none of these is
#: unreachable: no amount of running the pipeline will ever produce it.
ENTRYPOINT_MODULE_PREFIXES = ("management/commands/", "views.py", "stage_e_dispatch.py")


@dataclass(frozen=True)
class Reachability:
    """What the static call graph could and could not establish.

    NAME-BASED, and honest about it. Edges are resolved by called NAME across
    the whole tree, ignoring which module defines it, because resolving every
    import/alias/attribute call precisely is a whole-program analysis. That
    over-approximates: two unrelated functions sharing a name merge. The
    over-approximation runs in the SAFE direction for the finding that
    matters - a channel reported UNREACHABLE is one that nothing anywhere
    calls under any name, which is a strong claim; a channel reported
    reachable may not truly be, which is why reachability is REPORTED and
    never used to excuse a zero.
    """

    reachable: frozenset[str]
    entrypoints_by_function: dict[str, frozenset[str]]
    findings: tuple[str, ...] = ()


def _module_rel_from_dotted(dotted: str) -> str:
    """`cardpicker.local_fallback` -> `local_fallback.py`; `cardpicker` -> `""`."""
    parts = dotted.split(".")
    if parts and parts[0] == "cardpicker":
        parts = parts[1:]
    return "/".join(parts) + ".py" if parts else ""


def _import_bindings(tree: ast.Module, module_rel: str) -> tuple[dict[str, str], dict[str, str]]:
    """(imported name -> defining module, module alias -> module) for one file.

    Resolving imports is what makes an edge QUALIFIED. Without it, a call to
    `run_pilot` is just the string "run_pilot" and merges with every other
    `run_pilot` in the tree - which is how a name-based graph reported nearly
    every channel as reachable from one unrelated backfill command.
    """
    names: dict[str, str] = {}
    modules: dict[str, str] = {}
    package = module_rel.rsplit("/", 1)[0] if "/" in module_rel else ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.module is None:
                base = package
            elif node.level:
                base = f"{package}/{(node.module or '').replace('.', '/')}".strip("/")
            else:
                base = _module_rel_from_dotted(node.module or "")[:-3] if node.module else ""
            for alias in node.names:
                target = f"{base}/{alias.name}.py".lstrip("/") if base else f"{alias.name}.py"
                local = alias.asname or alias.name
                # `from cardpicker import local_fallback` binds a MODULE;
                # `from cardpicker.local_fallback import f` binds a FUNCTION.
                modules[local] = target
                names[local] = f"{base}.py" if base else target
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = _module_rel_from_dotted(alias.name)
    return names, modules


def build_reachability(index: Optional[SourceIndex] = None) -> Reachability:
    index = index or build_source_index()
    known_modules = {str(p.relative_to(index.root)) for p in index.trees}

    # "<module rel>::<qualname>" -> the set of node ids it calls
    calls: dict[str, set[str]] = {}
    entry_owner: dict[str, str] = {}
    #: module -> qualnames it defines
    defined: dict[str, set[str]] = {}

    parsed: list[tuple[str, ast.Module, dict[int, tuple[str, ast.AST]]]] = []
    for path, tree in index.trees.items():
        rel = str(path.relative_to(index.root))
        enclosing = _enclosing_functions(tree)
        parsed.append((rel, tree, enclosing))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = enclosing.get(id(node.body[0]), (node.name, node))[0] if node.body else node.name
                defined.setdefault(rel, set()).update({node.name, qual})

    for rel, tree, enclosing in parsed:
        is_entry_module = any(rel.startswith(p) or rel == p for p in ENTRYPOINT_MODULE_PREFIXES)
        import_names, import_modules = _import_bindings(tree, rel)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qual = enclosing.get(id(node.body[0]), (node.name, node))[0] if node.body else node.name
            node_id = f"{rel}::{qual}"
            called: set[str] = set()
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                if isinstance(func, ast.Name):
                    name = func.id
                    if name in defined.get(rel, ()):
                        called.add(f"{rel}::{name}")
                    elif name in import_names and import_names[name] in known_modules:
                        called.add(f"{import_names[name]}::{name}")
                elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    owner = func.value.id
                    if owner == "self":
                        # a sibling method - approximated to the same module,
                        # which is exact for this tree's single-class modules
                        called.add(f"{rel}::{func.attr}")
                        if "." in qual:
                            called.add(f"{rel}::{qual.rsplit('.', 1)[0]}.{func.attr}")
                    elif owner in import_modules and import_modules[owner] in known_modules:
                        called.add(f"{import_modules[owner]}::{func.attr}")
            calls.setdefault(node_id, set()).update(called)
            if is_entry_module:
                entry_owner.setdefault(node_id, rel)

    entrypoints_by_function: dict[str, set[str]] = {}
    for entry, owner in entry_owner.items():
        stack = [entry]
        seen = {entry}
        while stack:
            current = stack.pop()
            entrypoints_by_function.setdefault(current, set()).add(owner)
            for callee in calls.get(current, ()):
                if callee not in seen:
                    seen.add(callee)
                    stack.append(callee)

    findings: list[str] = []
    if not entry_owner:
        findings.append(
            "reachability derivation FAILED: no entry-point functions found under "
            f"{ENTRYPOINT_MODULE_PREFIXES}. Every channel would read as unreachable, which is "
            "as useless as every channel reading as reachable. The empty derivation is the "
            "finding."
        )
    return Reachability(
        reachable=frozenset(entrypoints_by_function),
        entrypoints_by_function={k: frozenset(v) for k, v in entrypoints_by_function.items()},
        findings=tuple(findings),
    )


# ---------------------------------------------------------------------------
# The whole roster
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Roster:
    vote: tuple[Channel, ...]
    extractor: tuple[Channel, ...]
    abstention: tuple[Channel, ...]
    skip_reason: tuple[Channel, ...]
    reachability: Reachability
    findings: tuple[str, ...]

    def all_channels(self) -> tuple[Channel, ...]:
        return self.vote + self.extractor + self.abstention + self.skip_reason

    def is_empty(self) -> bool:
        return not self.all_channels()


def derive_roster(src_dir: Optional[Path] = None) -> Roster:
    """The whole derived roster, plus every derivation finding.

    A caller MUST treat a non-empty `findings` as a hard failure. The report
    command exits with its own distinct code for it (INSUFFICIENT-DATA, not
    FAIL) because "the instrument could not be built" and "the pipeline is
    broken" send an operator to different places.
    """
    index = build_source_index(src_dir)
    vote, vote_findings = derive_vote_channels(index)
    extractor, extractor_findings = derive_extractor_channels(index)
    abstention, abstention_findings = derive_abstention_channels(index)
    skip, skip_findings = derive_skip_reason_channels(index)
    reach = build_reachability(index)
    return Roster(
        vote=tuple(vote),
        extractor=tuple(extractor),
        abstention=tuple(abstention),
        skip_reason=tuple(skip),
        reachability=reach,
        findings=tuple(vote_findings + extractor_findings + abstention_findings + skip_findings + list(reach.findings)),
    )


__all__ = [
    "Channel",
    "Roster",
    "Reachability",
    "SourceIndex",
    "ROSTER_SCAN_EXCLUDED_DIRS",
    "VOTE_MODEL_NAMES",
    "NON_VOTING_IDENTITIES",
    "roster_source_files",
    "build_source_index",
    "build_reachability",
    "derive_vote_channels",
    "derive_extractor_channels",
    "derive_abstention_channels",
    "derive_skip_reason_channels",
    "derive_roster",
]
