#!/usr/bin/env python3
"""
Mechanical lint over docs/: internal link resolution + backtick-quoted
repo-path existence. Never fixes anything — only reports, via GitHub
Actions ::error:: annotations so failures show up inline on the PR diff.

KNOWN LIMITATIONS (see docs/documentation-process.md's "docs-lint" section
for the full writeup):
  - This can only tell you a link/path is BROKEN, never that a doc's
    STATUS CLAIM is stale ("not yet built" for something now shipped,
    etc.) — that class of rot needs a human/judgment coherence pass
    (quarterly, see docs/documentation-process.md), not a linter.
  - The path-existence check is a heuristic over backtick-quoted spans
    that look path-shaped (contains "/", ends in a known code extension).
    It will have false positives on intentionally-illustrative or
    historical example paths that never existed on disk — if this ever
    flags one, add it to the ALLOWLIST below with a one-line reason
    rather than loosening the general heuristic.
  - Fenced code blocks are skipped entirely (their contents are pseudocode
    / literal examples, not prose claims about the repo).

Exit code is the number of findings (0 = clean), so CI fails on anything
found.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"

# Backtick-quoted spans that look path-shaped but are known-intentional
# non-paths (globs, illustrative examples, etc.) — add here with a reason,
# never by loosening the heuristic below.
ALLOWLIST = {
    "frontend/src/features/printingTags/PrintingTagQueue.tsx": (
        "deleted in the 'Queue redesign frontend' commit (9d71851) — "
        "docs/lessons.md and docs/reports/level1-scryfall-reference-"
        "regression.md cite it deliberately as git archaeology, not a "
        "live reference"
    ),
    "frontend/scripts/generate-docs-site.js": (
        "docs/proposals/proposal-i-docs-as-site-source.md's 'Shipped vs. "
        "not yet built' section cites this deliberately as history — PR-I-1's "
        "first pass built it (a JS reimplementation of link-rewrite logic), "
        "the owner's restructure deleted it in favor of the single-transform "
        "architecture (publish_wiki.py/publish_site.py) — not a live "
        "reference, not a forward-reference to something not yet built"
    ),
}

PATH_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".css",
    ".toml",
    ".txt",
    ".csv",
    ".conf",
    ".sh",
)

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(r"`([\w./\-]+/[\w./\-]+)`")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _blank(match: re.Match) -> str:
    # Same length, same newline positions as the original match — every
    # subsequent offset stays valid against the *original* file text, so
    # line_of() always reports correctly even when a fence/inline-code span
    # precedes the thing being checked (a naive "collapse to bare newlines"
    # replacement would shift every later offset and misreport line numbers).
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def strip_fenced_code(text: str) -> str:
    return FENCE_RE.sub(_blank, text)


def strip_inline_code(text: str) -> str:
    """
    For link-checking only (never for the backtick-path check, which needs
    the backticks intact). Inline code often contains illustrative link
    syntax — e.g. this file's own docstring mentions `[text](path)` as an
    example, which is not a real link — so link regexes must not see
    inside single-backtick spans.
    """
    return INLINE_CODE_RE.sub(_blank, text)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def is_gitignored(candidate: str) -> bool:
    """
    Several docs correctly reference files that are gitignored by design
    (drives.csv, docker/.env, docker/django/env.txt, client_secrets.json —
    see CLAUDE.md's "Never commit" list) and only ever exist on a live
    deployment's disk, never in the repo itself. A missing gitignored path
    is expected, not a doc bug — don't flag it.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", candidate],
            cwd=REPO_ROOT,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def check_file(path: Path) -> list[str]:
    findings = []
    raw = path.read_text()
    text = strip_fenced_code(raw)
    link_text = strip_inline_code(text)
    doc_dir = path.parent

    for m in WIKILINK_RE.finditer(link_text):
        target = m.group(1)
        if not (target.endswith(".md") or "/" in target):
            continue  # e.g. `[[routes]]` — a literal TOML table, not a doc link
        resolved = (doc_dir / target).resolve()
        if not resolved.is_file():
            findings.append(
                f"::error file={path.relative_to(REPO_ROOT)},line={line_of(raw, m.start())}::"
                f"broken wiki-link target: [[{target}]] does not resolve to a real file"
            )

    for m in MD_LINK_RE.finditer(link_text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target_path = target.split("#")[0]
        if not target_path:
            continue
        resolved = (doc_dir / target_path).resolve()
        if not resolved.is_file():
            findings.append(
                f"::error file={path.relative_to(REPO_ROOT)},line={line_of(raw, m.start())}::"
                f"broken markdown link target: ({target}) does not resolve to a real file"
            )

    for m in BACKTICK_PATH_RE.finditer(text):
        candidate = m.group(1)
        if candidate in ALLOWLIST:
            continue
        if not candidate.endswith(PATH_EXTENSIONS):
            continue
        if candidate.startswith(("http://", "https://")):
            continue
        # Only check candidates that look like real repo paths (start from
        # a known top-level dir) to keep false positives low.
        top = candidate.split("/", 1)[0]
        known_tops = {
            "docs",
            "frontend",
            "MPCAutofill",
            "image-cdn",
            "desktop-tool",
            "cloudflare-static-site",
            "github-release-reverse-proxy",
            "docker",
            ".github",
        }
        if top not in known_tops and not candidate.startswith(("../", "./")):
            continue
        resolved = (REPO_ROOT / candidate).resolve()
        if not resolved.exists():
            resolved_relative = (doc_dir / candidate).resolve()
            if resolved_relative.exists():
                continue
            if is_gitignored(candidate):
                continue
            findings.append(
                f"::error file={path.relative_to(REPO_ROOT)},line={line_of(raw, m.start())}::"
                f"referenced path `{candidate}` does not exist in the repo"
            )

    return findings


EXTRACTABLE_PRIMITIVES_DOC = DOCS_DIR / "upstreaming" / "extractable-primitives.md"

# The fork-only-module allowlist for check_extractable_primitives_tether().
# Kept here, not duplicated in extractable-primitives.md, so there's one
# place this can go stale, not two. Add to these sets whenever a new
# fork-only module is added to the vote system / CanonicalPrinting-consensus
# / auth surface — an omission here is a silent CI blind spot, not a safe
# default, so prefer over-including a borderline module.
FORK_ONLY_PY_MODULES = {
    # vote system
    "cardpicker.vote_consensus",
    "cardpicker.printing_consensus",
    "cardpicker.artist_consensus",
    "cardpicker.tag_consensus",
    "cardpicker.moderation",
    "cardpicker.question_feed",
    "cardpicker.deductive_backfill",
    "cardpicker.local_identify_printing_tags",
    "cardpicker.local_residual_classify",
    "cardpicker.local_lands_identify",
    "cardpicker.local_fallback",
    # CanonicalPrinting / consensus
    "cardpicker.printing_candidates",
    "cardpicker.printing_metadata_import",
    # auth / Discord OAuth / Moderators gate
    "cardpicker.security",
    "cardpicker.sensitive_tags",
    "accounts.adapter",
}
# `from cardpicker.models import X` / `from cardpicker.schema_types import X`
# — models.py and schema_types.py are shared files extended by the fork, so
# they can't be allowlisted wholesale; these are the fork-only symbols
# within them.
FORK_ONLY_PY_MODEL_SYMBOLS = {
    "AbstractWeightedVote",
    "CardPrintingTag",
    "CardArtistVote",
    "CardTagVote",
    "VoteSource",
    "VotePolarity",
    "PrintingTagStatus",
    "ArtistVoteStatus",
    "TagVoteStatus",
    "TagModerationClass",
    "Tag",
    "CanonicalCard",
    "CanonicalArtist",
    "CanonicalExpansion",
    "CanonicalPrintingMetadata",
}
FORK_ONLY_TS_PATH_PREFIXES = (
    "@/features/questionFeed/",
    "@/features/attributeVoting/",
    "@/features/printingTags/",
    "@/features/attributeChips/",
    "@/features/moderation/",
    "@/features/reporting/",
    "@/features/filters/CanonicalCardFilter",
    "@/features/filters/MatureContentFilter",
    "@/pages/whatsthat",
    "@/pages/printingQueue",
)
# Named imports from shared files (store/api.ts, common/schema_types.ts)
# that are fork-only even though the file they're imported from isn't.
FORK_ONLY_TS_SYMBOLS = {
    "APIGetTagConsensus",
    "APIGetPrintingConsensus",
    "APIGetVoteQueue",
    "APISubmitPrintingTag",
    "APISubmitArtistVote",
    "APISubmitTagVote",
    "APIGetPrintingCandidates",
    "useGetWhoamiQuery",
    "APIReportCard",
    "APIGetModerationQueue",
    "APIGetModerationDrives",
    "APIGetModerationDriveCards",
    "APIRemoveModerationCard",
    "APIRemoveModerationDrive",
    "CanonicalArtistClass",
    "CanonicalCardClass",
    "PrintingCandidate",
    "WhoamiResponse",
    "ModerationQueueResponse",
    "ModerationDrivesResponse",
    "ModerationDriveCardsResponse",
    "ReportCardResponse",
}

TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
BACKTICK_RE = re.compile(r"`([^`]+)`")
TYPE_CHECKING_BLOCK_RE = re.compile(r"if TYPE_CHECKING:\n((?:[ \t]+.*\n?)+)")
PY_IMPORT_RE = re.compile(
    # `[^)]*` (not `.*`) so this also matches multi-line parenthesized
    # imports (`from x import (\n    a,\n    b,\n)`) without needing DOTALL.
    r"^\s*(?:from\s+([\w.]+)\s+import\s+(\([^)]*\)|[^\n#]+)|import\s+([\w.]+))",
    re.MULTILINE,
)
TS_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:type\s+)?(?:\{([^}]*)\}|(\w+))?\s*(?:,\s*\{([^}]*)\})?\s*from\s+["\']([^"\']+)["\']',
    re.MULTILINE,
)


def _strip_type_checking_blocks(text: str) -> str:
    return TYPE_CHECKING_BLOCK_RE.sub(lambda m: _blank(m), text)


def _py_file_entanglement(text: str) -> list[str]:
    text = _strip_type_checking_blocks(text)
    findings = []
    for m in PY_IMPORT_RE.finditer(text):
        module = m.group(1) or m.group(3)
        names = m.group(2) or ""
        if module and any(module == fo or module.startswith(fo + ".") for fo in FORK_ONLY_PY_MODULES):
            findings.append(f"imports fork-only module `{module}`")
        if module in {"cardpicker.models", "cardpicker.schema_types"}:
            imported = {n.strip().split(" as ")[0] for n in names.split(",") if n.strip()}
            hit = imported & FORK_ONLY_PY_MODEL_SYMBOLS
            if hit:
                findings.append(f"imports fork-only symbol(s) {sorted(hit)} from `{module}`")
    return findings


def _ts_file_entanglement(text: str) -> list[str]:
    findings = []
    for m in TS_IMPORT_RE.finditer(text):
        names = ", ".join(g for g in (m.group(1), m.group(2), m.group(3)) if g)
        target = m.group(4)
        if any(target.startswith(prefix) for prefix in FORK_ONLY_TS_PATH_PREFIXES):
            findings.append(f"imports fork-only path `{target}`")
        imported = {n.strip().split(" as ")[0] for n in names.split(",") if n.strip()}
        hit = imported & FORK_ONLY_TS_SYMBOLS
        if hit:
            findings.append(f"imports fork-only symbol(s) {sorted(hit)} from `{target}`")
    return findings


def check_extractable_primitives_tether() -> list[str]:
    """
    For every row in extractable-primitives.md's tables marked CLEAN in its
    Entanglement column, verify the row's own File(s) column imports nothing
    from the fork-only vote-system/CanonicalPrinting-consensus/auth modules
    above. One level deep only (see the doc's own "mechanical tether"
    section for why) — this is a backstop against direct-import drift, not
    a transitive import-graph analysis.
    """
    findings = []
    if not EXTRACTABLE_PRIMITIVES_DOC.is_file():
        return findings
    raw = EXTRACTABLE_PRIMITIVES_DOC.read_text()
    doc_rel = EXTRACTABLE_PRIMITIVES_DOC.relative_to(REPO_ROOT)

    for m in TABLE_ROW_RE.finditer(raw):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 5:
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue  # header separator row
        files_cell, entanglement_cell = cells[1], cells[4]
        if not entanglement_cell.startswith("CLEAN"):
            continue
        for fm in BACKTICK_RE.finditer(files_cell):
            rel_path = fm.group(1)
            file_path = REPO_ROOT / rel_path
            if not file_path.is_file():
                continue  # already reported by the generic path-existence check
            file_text = file_path.read_text()
            if rel_path.endswith(".py"):
                hits = _py_file_entanglement(file_text)
            elif rel_path.endswith((".ts", ".tsx")):
                hits = _ts_file_entanglement(file_text)
            else:
                continue
            for hit in hits:
                findings.append(
                    f"::error file={doc_rel},line={line_of(raw, m.start())}::"
                    f"extractable-primitives row claims CLEAN but `{rel_path}` {hit}"
                )
    return findings


# ---------------------------------------------------------------------------
# Interconnection rules (2026-07-23 owner ruling: "kill the lettering
# convention all together ... each subject should have one document or they
# should at least reference each other"). Decisions now live written-out in
# prose in their subject doc — there is NO central register and NO
# letter/number decision-label grammar. These rules enforce that model:
#   1. no NEW letter-number decision labels introduced in docs/
#   2. every doc reachable from the index chain (README/MANIFEST)
#   3. every SUPERSEDED marker carries a pointer
#   4. same-subject proposals reference each other
#
# All SOFT findings: they print as ::warning:: and do NOT add to the exit
# code, so the corpus can't turn master red before the concurrent
# de-lettering sweep lands. Run with --strict (or DOCS_LINT_STRICT=1) to
# promote them to ::error:: and count them — see
# docs/documentation-process.md's "Interconnection lint" section for the
# flip-to-hard procedure.
# ---------------------------------------------------------------------------

INDEX_ROOT_DOCS = ("README.md", "MANIFEST.md")

# Record/archive buckets that index themselves by their own dated-listing
# convention (docs/README.md's "Records" section, docs/reports/README.md)
# and are frozen history — excluded from the orphan check AND from the
# no-labels guard (old labels there are a historical record, not new use).
ARCHIVE_PREFIXES = ("reports/", "data/", "audits/", "proposals/mockups/")

# --- Rule 1: no new letter-number decision labels ---------------------------
# The abolished convention wrote a decision as a bold marker (**D14**,
# **D14 — Title**) or "decision D5" / "VW-3". Flag those DEFINITION forms
# wherever they're (re)introduced in a living doc. A bare inline mention in
# flowing prose isn't a definition and isn't flagged; the historical aside
# "(formerly 'D14')" and anything under the archive buckets are allowed.
LABEL_DEF_BOLD_RE = re.compile(r"\*\*([A-Z]{1,3}-?[0-9]{1,3})\b")
LABEL_DEF_WORD_RE = re.compile(r"(?i:decision)\s+([A-Z]{1,3}-?[0-9]{1,3})\b")
LABEL_LETTERS_RE = re.compile(r"^[A-Z]+")
# The abolished convention is the D-number DECISION ledger (PR #357 title:
# "kill the D-number decision-label convention"); the sibling vote-weight
# decision stream used the same D-ledger plus VW-style refs. The guard
# targets those DECISION-label prefixes only. Structural enumerations the
# sweep deliberately KEPT — funnel steps (F), requirements (R), test
# scenarios (T), mappings (M/C/S/I/L), editor-spec items (E), file-change
# rows (XF), license/PR tokens (GPL-3.0/PR-5) — are NOT decision labels and
# are not flagged.
DECISION_LABEL_PREFIXES = ("D", "VW")
# Verbatim, point-in-time DECISION RECORDS the sweep intentionally left
# lettered (self-annotated "not a living spec"; a living, de-lettered doc is
# the authority). Exempt like the archive buckets. `vote-weight-matrix.md`
# is the other such record but its D-labels are prose ("D1 ...", not bold or
# "decision D1"), so the definition-style guard never matches them anyway.
NO_LABELS_ARCHIVE_DOCS = ("reference/funnel-spec.md",)

# --- Rule 3: supersession pointer -------------------------------------------
# SUPERSEDED lines that REFERENCE other superseded notes rather than
# DECLARING a supersession carry no pointer by nature — allowlisted (same
# "add here with a reason" convention as ALLOWLIST above).
SUPERSEDE_ALLOWLIST = (
    '"SUPERSEDED" notes above',  # printing-tags.md — back-reference to earlier notes
    "SUPERSEDED bullets",  # printing-tags.md — back-reference to earlier bullets
)
SUPERSEDE_MARKER_RE = re.compile(r"SUPERSEDE[SD]")
# A pointer that resolves a supersession: a label, a markdown/wiki link, a
# backtick path, a §section ref, an issue/PR #ref, or a self-describing
# compound status ("SUPERSEDED-BY-POSTURE"/"-BY-ARCHITECTURE").
SUPERSEDE_POINTER_RE = re.compile(
    r"\b[A-Z]{1,3}-?[0-9]{1,3}\b|\]\([^)]+\)|\[\[[^\]]+\]\]|`[\w./\-]+`|§|#[0-9]+|SUPERSEDE[SD]-BY-"
)

# --- Rule 4: same-subject proposal cross-references -------------------------
PROPOSAL_SUBJECT_RE = re.compile(r"^(proposal-[a-z]+)-")


def _rel(path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _under(p, root) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def check_no_letter_labels() -> list:
    # Returns (relpath, line, message) tuples.
    findings = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR).as_posix()
        if rel.startswith(ARCHIVE_PREFIXES) or rel in NO_LABELS_ARCHIVE_DOCS:
            continue
        raw = path.read_text()
        lines = strip_fenced_code(raw).splitlines()
        for i, line in enumerate(lines):
            for rx in (LABEL_DEF_BOLD_RE, LABEL_DEF_WORD_RE):
                for m in rx.finditer(line):
                    label = m.group(1)
                    prefix = LABEL_LETTERS_RE.match(label).group(0)
                    if prefix not in DECISION_LABEL_PREFIXES:
                        continue
                    tail = line[m.end() : m.end() + 2]
                    if tail[:1] == "." and tail[1:2].isdigit():
                        continue  # a dotted version like GPL-3.0, not a label
                    if "formerly" in line[: m.start()].lower():
                        continue  # historical aside: (formerly 'D14')
                    findings.append(
                        (
                            _rel(path),
                            i + 1,
                            f"D-number decision label `{label}` — the D-number "
                            f"decision-label convention is abolished (owner ruling "
                            f"2026-07-23, PR #357). Write the decision out in prose in "
                            f"its subject doc; a label is allowed only as a historical "
                            f"aside \"(formerly '{label}')\", inside docs/reports/ "
                            f"archives, or in a verbatim decision-record doc.",
                        )
                    )
    return findings


def _doc_link_targets(path) -> set:
    raw = path.read_text()
    link_text = strip_inline_code(strip_fenced_code(raw))
    targets = set()
    for m in MD_LINK_RE.finditer(link_text):
        targets.add(m.group(1).strip().split("#")[0])
    for m in WIKILINK_RE.finditer(link_text):
        targets.add(m.group(1).strip().split("#")[0])
    # Backtick docs-relative .md paths — MANIFEST.md indexes docs this way.
    for m in re.finditer(r"`([\w./\-]+\.md)`", strip_fenced_code(raw)):
        targets.add(m.group(1))
    resolved = set()
    for t in targets:
        if not t or t.startswith(("http://", "https://", "mailto:")):
            continue
        for base in (path.parent, DOCS_DIR):
            cand = (base / t).resolve()
            if cand.is_file() and cand.suffix == ".md" and _under(cand, DOCS_DIR.resolve()):
                resolved.add(cand)
    return resolved


def check_orphans() -> list:
    findings = []
    roots = [(DOCS_DIR / r).resolve() for r in INDEX_ROOT_DOCS if (DOCS_DIR / r).is_file()]
    reachable = set(roots)
    stack = list(roots)
    while stack:
        cur = stack.pop()
        for nxt in _doc_link_targets(cur):
            if nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR).as_posix()
        if rel in INDEX_ROOT_DOCS:
            continue
        if rel.startswith(ARCHIVE_PREFIXES):
            continue
        if path.resolve() not in reachable:
            findings.append(
                (
                    _rel(path),
                    None,
                    f"orphan doc: {rel} is not reachable from docs/README.md or docs/MANIFEST.md via any link or backtick-path reference",
                )
            )
    return findings


def check_supersession() -> list:
    findings = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        raw = path.read_text()
        rawlines = raw.splitlines()
        codelines = strip_fenced_code(raw).splitlines()
        for i, line in enumerate(codelines):
            if not SUPERSEDE_MARKER_RE.search(line):
                continue
            if any(sig in rawlines[i] for sig in SUPERSEDE_ALLOWLIST):
                continue
            # The pointer may sit anywhere in the marker's own paragraph
            # (a multi-line "HISTORICAL — SUPERSEDED" banner names its
            # superseder several lines down or up) OR, for the
            # "heading / blank / explanation" shape, in the next paragraph.
            # Search the whole containing paragraph plus the following one.
            s = i
            while s - 1 >= 0 and codelines[s - 1].strip():
                s -= 1
            e = i
            while e + 1 < len(codelines) and codelines[e + 1].strip():
                e += 1
            k = e + 1
            while k < len(codelines) and not codelines[k].strip():
                k += 1
            while k < len(codelines) and codelines[k].strip():
                e = k
                k += 1
            window = "\n".join(codelines[s : e + 1])
            if not SUPERSEDE_POINTER_RE.search(window):
                findings.append(
                    (
                        _rel(path),
                        i + 1,
                        "SUPERSEDED marker without a pointer (a link, a `path`, a §section, or a #ref) anywhere in its paragraph",
                    )
                )
    return findings


def check_proposal_crossrefs() -> list:
    # Same-subject proposals (proposal-<letter>-*) must reference each other
    # — at least one direction, so a reader can navigate between them. The
    # anti-fragmentation replacement for the old shared-D-number heuristic.
    findings = []
    prop_dir = DOCS_DIR / "proposals"
    if not prop_dir.is_dir():
        return findings
    groups = {}
    for path in sorted(prop_dir.glob("*.md")):
        m = PROPOSAL_SUBJECT_RE.match(path.name)
        if m:
            groups.setdefault(m.group(1), []).append(path)
    for subject, paths in groups.items():
        if len(paths) < 2:
            continue
        texts = {p: p.read_text() for p in paths}
        for ai in range(len(paths)):
            for bi in range(ai + 1, len(paths)):
                a, b = paths[ai], paths[bi]
                if b.name in texts[a] or a.name in texts[b]:
                    continue
                findings.append(
                    (
                        _rel(a),
                        None,
                        f"{a.name} and {b.name} both cover subject '{subject}' but neither references the other — same-subject docs must link (owner ruling 2026-07-23: one doc per subject, or they reference each other)",
                    )
                )
    return findings


SOFT_CHECKS = (
    ("no-letter-labels", check_no_letter_labels),
    ("orphan", check_orphans),
    ("supersession", check_supersession),
    ("proposal-crossref", check_proposal_crossrefs),
)


def _strict_mode(argv) -> bool:
    if "--strict" in argv:
        return True
    return os.environ.get("DOCS_LINT_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = _strict_mode(argv)

    # Hard findings: the original link/path/tether checks — always counted,
    # always ::error::, CI behavior unchanged.
    hard_findings = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        hard_findings.extend(check_file(path))
    hard_findings.extend(check_extractable_primitives_tether())

    # Soft findings: the interconnection rules. Emitted as ::warning:: and
    # NOT counted unless --strict / DOCS_LINT_STRICT.
    soft_findings = []
    for _name, fn in SOFT_CHECKS:
        soft_findings.extend(fn())

    for finding in hard_findings:
        print(finding)

    severity = "error" if strict else "warning"
    for rel, line, msg in soft_findings:
        loc = f"file={rel}" + (f",line={line}" if line else "")
        print(f"::{severity} {loc}::{msg}")

    if hard_findings:
        print(
            f"\n{len(hard_findings)} hard finding(s) (link/path/tether). See "
            f"docs/documentation-process.md's known-limitations note if any are "
            f"false positives — add a one-line ALLOWLIST entry in "
            f".github/scripts/docs_lint.py rather than loosening the heuristic."
        )
    if soft_findings:
        mode = "counted (strict)" if strict else "soft — NOT counted toward exit code"
        print(
            f"\n{len(soft_findings)} interconnection finding(s) [{mode}]. See "
            f"docs/documentation-process.md's 'Interconnection lint' section. These "
            f"stay soft until the de-lettering sweep lands; flip to hard-fail with "
            f"--strict (or DOCS_LINT_STRICT=1) after it does."
        )
    if not hard_findings and not soft_findings:
        print("docs-lint: clean.")

    return len(hard_findings) + (len(soft_findings) if strict else 0)


if __name__ == "__main__":
    raise SystemExit(main())
