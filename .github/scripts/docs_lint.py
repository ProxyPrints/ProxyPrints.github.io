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
import re
import subprocess
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


def main() -> int:
    all_findings = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        all_findings.extend(check_file(path))
    all_findings.extend(check_extractable_primitives_tether())

    for finding in all_findings:
        print(finding)

    if all_findings:
        print(
            f"\n{len(all_findings)} finding(s). See docs/documentation-process.md's "
            f"known-limitations note if any of these are false positives — add a "
            f"one-line ALLOWLIST entry in .github/scripts/docs_lint.py rather than "
            f"loosening the general heuristic."
        )
    else:
        print("docs-lint: clean.")

    return len(all_findings)


if __name__ == "__main__":
    raise SystemExit(main())
