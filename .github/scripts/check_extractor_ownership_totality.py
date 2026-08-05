#!/usr/bin/env python3
"""
CODE-TO-CODE tether: Stage C extractor *ownership* totality (issue #509's own
follow-up — "make every evidence-affecting code path version-visible").

`check_extractor_manifest_sync.py` proves the eleven `*_EXTRACTOR_VERSION`
constants and the cohort's resume-filter map agree. It says nothing about
the code that FEEDS those eleven extractors: `image_evidence.py`'s own
module-private helpers (`_extract_legal_line`, `_parse_artist_is_contradicted`,
`_crop_box_to_pixels`, ...) and the callables it imports from
`collector_line_artist.py`/`local_ocr.py`/`local_image_quality.py`
(`recover_artist_from_card_text`, `preprocess_variants`, ...) all help decide
what `compute_card_evidence` stores, and none of them carry a version of
their own. A change to any of them can silently change a stored field while
`MANIFEST_EXTRACTOR_CURRENT_VERSIONS` stays put, so the resume filter marks
the row "already done" and it is never re-extracted — the exact failure mode
`check_extractor_manifest_sync.py` exists to catch, one level lower, where
that script's own AST derivation cannot see it (it only reads
`*_EXTRACTOR_VERSION` constants and `extractor_versions[...]` assignments,
neither of which this code touches).

This script is the tether for THAT layer. `EXTRACTOR_OWNERSHIP` below is the
SOURCE OF TRUTH — a hand-declared, per-entry-justified map from a
contributor's name to the `MANIFEST_EXTRACTOR_KEYS` member(s) whose stored
fields it helps determine, exactly the judgement call
docs/features/catalog-completion-plan.md's "Stage C extractor ownership"
section describes: it either gets its own `*_v1` extractor (not something
this script can decide) or it is declared here as a component of an
existing one. What THIS script derives and checks is TOTALITY: every
contributor `image_evidence.py`'s own source actually reaches from
`compute_card_evidence` must have an entry here, and every entry here must
still point at a real `MANIFEST_EXTRACTOR_KEYS` member. Neither direction
is a hand-listed set trusted on its own — the reachable-contributor set is
derived by AST from the real module, matching `check_extractor_manifest_sync.py`'s
own "never regex/hand-list, always derive" discipline.

WHAT COUNTS AS A "CONTRIBUTOR" (the reachable set)
---------------------------------------------------
Two kinds, both read via `ast`, never by importing/executing:

  1. Every module-level `def _name(...)` in `image_evidence.py` itself —
     its own private helpers — EXCEPT `EXCLUDED_HELPERS` (see below).
  2. Every name imported at module level from one of `SCOPED_EXTERNAL_MODULES`
     that is actually CALLED somewhere in `image_evidence.py` (an `ast.Call`
     whose `func` is that bare `ast.Name` — an import that is only ever used
     as a type hint or a bare constant, e.g. `ArtistLexicon`/`DEFAULT_CROP_BOX`,
     is not a callable code path and is correctly not required to have an
     entry; see the module's own docstring for why constants are out of this
     script's scope).

DELIBERATE EXCLUSIONS, and why they are not silent
----------------------------------------------------
The OCR attempt-tier ladder (`_collector_line_ocr_attempts`, issue #259) was
excluded here (`EXCLUDED_HELPERS = {"_collector_line_ocr_attempts"}`) while a
parallel branch was actively restructuring it — that branch was issue #677
("collapse the Stage C OCR attempt ladder"), which has now landed, so the
exclusion is LIFTED (`EXCLUDED_HELPERS = frozenset()`): the ladder function
and everything reachable only through it (`preprocess_fallback_variants`)
now carry real `EXTRACTOR_OWNERSHIP` entries like every other contributor.

`local_fallback.py`'s own exported helpers (`classify_bleed_edge`,
`classify_border_color`, `classify_frame_style`, `compute_bleed_diff_mm`,
`normalize_crop_box`, `extract_artist_name`) are out of `SCOPED_EXTERNAL_MODULES`
entirely, same reason and same brief citation — that whole file is being
worked on in parallel. They are also PROTECTED CORE
(`docs/upstreaming/license-provenance.md` §2), each already the direct,
named mechanism of an existing versioned extractor
(`geometry_bleed`/`layout_class`/`artbox_phash`), so their omission here is
not a coverage gap for THIS PR's own inventory — it is a decision to let the
parallel branch own that declaration when it lands.

WHY NOT A REGEX/HAND-LIST OVER CALL SITES
-------------------------------------------
Same reasoning `check_extractor_manifest_sync.py`'s own module docstring
gives: a hand-listed reachable set is the exact invisible-drift problem one
level up from what this script exists to close. AST derivation means a
newly-added module-private helper, or a newly-called import, is caught the
moment it is written — not the next time someone remembers to update a list.

Exit code is the number of findings (0 = clean), matching
`check_extractor_manifest_sync.py`'s own convention.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_REL = "MPCAutofill/cardpicker/image_evidence.py"

# No excluded helpers - the OCR attempt-tier ladder exclusion (issue #259) was lifted by issue
# #677. See module docstring's "DELIBERATE EXCLUSIONS".
EXCLUDED_HELPERS = frozenset()

# Modules whose imported-and-called names are in this script's scope.
# `cardpicker.local_fallback` and `cardpicker.local_phash` are deliberately
# NOT here — see module docstring.
SCOPED_EXTERNAL_MODULES = frozenset(
    {
        "cardpicker.collector_line_artist",
        "cardpicker.local_ocr",
        "cardpicker.local_image_quality",
    }
)

# THE OWNERSHIP MAP — hand-declared, per-entry judgement call (see module
# docstring). {contributor name: frozenset of MANIFEST_EXTRACTOR_KEYS
# members whose stored field(s) it helps determine}. A contributor that
# feeds more than one key (e.g. the artist-contradiction gate governs
# whether `collector_line_ocr`'s own escalation loop keeps running, which
# also changes what `collector_line_tsv`'s word boxes and `artist_ocr`'s
# raw-text reuse see) is declared under every key it actually reaches — the
# convention this enforces is "bump every listed key together", not "pick
# one owner and hope the others notice".
EXTRACTOR_OWNERSHIP: dict = {
    # --- image_evidence.py's own private helpers ---
    # Shared crop-box-to-pixel remap (normalize_crop_box + scale) behind
    # every `*_crop_px` field except collector/artist (those two are
    # computed inline in the crop_coordinates block itself, not through
    # this helper).
    "_crop_box_to_pixels": frozenset({"crop_coordinates", "artbox_phash", "symbol_region", "legal_line"}),
    # Shared crop-then-phash helper behind both region-hash extractors.
    "_compute_region_phash": frozenset({"artbox_phash", "symbol_region"}),
    # STAGE_C_NO_SHORTCIRCUIT env resolution — controls whether the
    # pre-classification short-circuit fires, which governs how many OCR
    # attempts run and therefore what collector_line_ocr/collector_line_tsv
    # store and what raw texts are available for artist_ocr's reuse pass.
    "_short_circuit_enabled_by_env": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # The short-circuit gate's own digit-scan primitive — same reach as
    # `_confidently_digit_free`, which is built entirely on top of it.
    "_contains_digit": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # SET-CODE LEXICON GATE (issue #370): gates the escalation loop's
    # acceptance criterion for collector_line_ocr's own selected parse,
    # which is what collector_line_tsv's word boxes are selected against
    # and what artist_ocr's collector-raw-text reuse pass sees.
    "_parse_is_lexicon_valid": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # legal_line's own compute, hoisted ahead of the OCR group but still
    # exclusively legal_line's own fields (legal_line_raw_text/
    # legal_line_copyright_year/legal_line_proxy_marker_detected/
    # legal_line_crop_px). Its OUTPUT is consumed elsewhere (the artist
    # gate, the artist_ocr_name recovery fallback) as an already-computed
    # value, not by this function itself changing behavior for those keys.
    "_extract_legal_line": frozenset({"legal_line"}),
    # COLLECTOR-LINE ARTIST GATE (2026-07-29): same reach as the lexicon
    # gate above, for the same reason (governs escalation continuation).
    "_parse_artist_is_contradicted": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # Pre-classification short-circuit's own acceptance predicate — same
    # reach as `_short_circuit_enabled_by_env`/`_contains_digit` above.
    "_confidently_digit_free": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # The OCR attempt-tier ladder itself (issue #259, collapsed to 2 tiers by issue #677) — the
    # ordered (variant, config, tier) sequence collector_line_ocr's own loop consumes, which
    # therefore governs collector_line_tsv's word-box source and artist_ocr's raw-text-reuse
    # population too. Was `EXCLUDED_HELPERS` while #677 was in flight; that exclusion is now
    # lifted (see module docstring).
    "_collector_line_ocr_attempts": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # --- cardpicker.collector_line_artist ---
    # Called from both `_parse_artist_is_contradicted` (gates
    # collector_line_ocr/collector_line_tsv/artist_ocr's raw-text-reuse
    # reach, as above) AND directly as the `artist_ocr_name` storage
    # fallback when the "Illus." anchor found nothing — the second call
    # site is artist_ocr's own field, already covered by the first site's
    # broader set.
    "recover_artist_from_card_text": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # --- cardpicker.local_image_quality --- (each wholly owned by
    # quality_signals; no other extractor calls any of these)
    "compute_blur_variance": frozenset({"quality_signals"}),
    "compute_entropy": frozenset({"quality_signals"}),
    "is_image_truncated": frozenset({"quality_signals"}),
    # --- cardpicker.local_ocr ---
    # Determines collector_line_set_code/collector_line_collector_number
    # (collector_line_ocr) and which winning variant's word boxes get
    # stored (collector_line_tsv) - called both inside the OCR loop and in
    # the no-attempts-parsed fallback.
    "parse_collector_line": frozenset({"collector_line_ocr", "collector_line_tsv"}),
    # legal_line's own tolerant parse - called only from `_extract_legal_line`.
    "parse_legal_line": frozenset({"legal_line"}),
    # Called from `_extract_legal_line`, the artist_ocr crop+OCR fallback loop, AND (since #677
    # lifted the ladder exclusion) `_collector_line_ocr_attempts`' own tier-1 yield - all three
    # reaches declared together.
    "preprocess_variants": frozenset({"legal_line", "artist_ocr", "collector_line_ocr", "collector_line_tsv"}),
    # Tier 2's own heavier-preprocessed variants (issue #259) - reachable exclusively through
    # `_collector_line_ocr_attempts`, same reach as the ladder function itself.
    "preprocess_fallback_variants": frozenset({"collector_line_ocr", "collector_line_tsv", "artist_ocr"}),
    # Same two in-scope call sites as `preprocess_variants` above (legal_line's
    # OCR pass, artist_ocr's crop+OCR fallback).
    "run_tesseract": frozenset({"legal_line", "artist_ocr"}),
    # Called directly inside compute_card_evidence's own OCR loop (the
    # `_collector_line_ocr_attempts` generator only yields preprocessed
    # variants + config + tier; the actual tesseract call, and therefore
    # this function's own reach, is in the loop body).
    "run_tesseract_text_and_words": frozenset({"collector_line_ocr", "collector_line_tsv"}),
}


def _parse(rel: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    return ast.parse(path.read_text(), filename=str(path))


def _module_private_helper_names(tree: ast.Module) -> set:
    """Every top-level `def _name(...)` in the module, minus EXCLUDED_HELPERS."""
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_")
        and node.name not in EXCLUDED_HELPERS
    }


def _excluded_node_ids(tree: ast.Module) -> set:
    """Object ids of every AST node inside an EXCLUDED_HELPERS function body.

    Same node OBJECTS as the whole-module walk (this is one parse, not two),
    so `id()` equality correctly identifies "found while walking the excluded
    subtree" versus "found elsewhere in the module".
    """
    excluded = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in EXCLUDED_HELPERS:
            excluded.update(id(n) for n in ast.walk(node))
    return excluded


def _scoped_external_imports(tree: ast.Module) -> set:
    """Names imported at module level from SCOPED_EXTERNAL_MODULES."""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in SCOPED_EXTERNAL_MODULES:
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _called_names(tree: ast.Module, candidates: set, skip_node_ids: set) -> set:
    """Subset of `candidates` that appear as a bare-name `ast.Call` func,
    outside of `skip_node_ids` (the excluded helper's own subtree)."""
    called = set()
    for node in ast.walk(tree):
        if id(node) in skip_node_ids:
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in candidates:
            called.add(node.func.id)
    return called


def derive_reachable_contributors() -> tuple:
    """
    DERIVE the set of contributor names this script requires an
    EXTRACTOR_OWNERSHIP entry for, from `image_evidence.py` itself.

    Returns (contributors, findings). Findings are non-empty only when the
    derivation itself fails - same anti-vacuous-pass discipline
    `check_extractor_manifest_sync.py`'s own `derive_expected_manifest`
    uses: a derivation that silently finds nothing would compare an empty
    set to an empty allowance and pass forever.
    """
    tree = _parse(SOURCE_REL)
    if tree is None:
        return set(), [f"::error::check_extractor_ownership_totality.py: {SOURCE_REL} not found"]

    helpers = _module_private_helper_names(tree)
    skip_ids = _excluded_node_ids(tree)
    external_imports = _scoped_external_imports(tree)
    called_externals = _called_names(tree, external_imports, skip_ids)

    contributors = helpers | called_externals

    findings = []
    if not contributors:
        findings.append(
            f"::error file={SOURCE_REL}::derived zero reachable contributors (module-private "
            f"helpers + called scoped-external imports). This tether derives its expectation "
            f"from the real module; finding none means it would compare an empty set forever, "
            f"so the empty derivation is itself the finding."
        )
    return contributors, findings


def check() -> list:
    contributors, findings = derive_reachable_contributors()
    if findings:
        return findings

    declared = set(EXTRACTOR_OWNERSHIP)

    for name in sorted(contributors - declared):
        findings.append(
            f"::error file={SOURCE_REL}::`{name}` is reachable from `compute_card_evidence`'s "
            f"own call graph (a module-private helper, or a scoped-external import it calls) "
            f"but has no entry in EXTRACTOR_OWNERSHIP "
            f"(.github/scripts/check_extractor_ownership_totality.py). A code path that helps "
            f"determine a stored ImageEvidence field must be either its own versioned extractor "
            f"or declared here as a component of an existing one - see this script's own module "
            f"docstring."
        )

    for name in sorted(declared - contributors):
        findings.append(
            f"::error file={SOURCE_REL}::EXTRACTOR_OWNERSHIP declares `{name}` "
            f"(.github/scripts/check_extractor_ownership_totality.py) but it is not reachable "
            f"from `compute_card_evidence`'s own call graph in {SOURCE_REL} - a stale entry, "
            f"most likely a rename or removal that was not reflected here."
        )

    # Cross-check: every declared owning key must be a real manifest key -
    # imported rather than re-derived, so the two scripts can never
    # disagree about what a "real" MANIFEST_EXTRACTOR_KEYS member is.
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_extractor_manifest_sync as manifest_sync

    manifest_sync.REPO_ROOT = REPO_ROOT
    expected_manifest, manifest_findings = manifest_sync.derive_expected_manifest()
    if manifest_findings:
        findings.extend(manifest_findings)
        return findings
    real_keys = set(expected_manifest)

    for name, owning_keys in sorted(EXTRACTOR_OWNERSHIP.items()):
        for key in sorted(owning_keys - real_keys):
            findings.append(
                f"::error file=.github/scripts/check_extractor_ownership_totality.py::"
                f"EXTRACTOR_OWNERSHIP[{name!r}] names `{key}`, which is not a real manifest key "
                f"derived from {SOURCE_REL} ({sorted(real_keys)}). A stale or mistyped owning "
                f"key silently exempts this contributor from ever being tied to a real extractor "
                f"version."
            )

    return findings


def main() -> int:
    findings = check()
    for finding in findings:
        print(finding)

    if findings:
        print(f"\n{len(findings)} extractor-ownership-totality finding(s).")
    else:
        contributors, _ = derive_reachable_contributors()
        print(f"extractor-ownership-totality: clean ({len(contributors)} declared contributors).")

    return len(findings)


if __name__ == "__main__":
    raise SystemExit(main())
