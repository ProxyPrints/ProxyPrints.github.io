"""
The skip-reason roster's own tests (2026-07-29 declaration-convention sweep).

Two jobs, both of which exist because the roster was previously impossible to
enumerate — see docs/reference/skip-reasons.md's "Why this doc exists":

1. PIN EVERY STRING VALUE. The sweep that introduced the `*_SKIP_REASON`
   convention was a pure refactor: a `CardScanLog` row written after it must
   carry byte-identical text to one written before. `CardScanLog.skip_reason`
   is a plain, unconstrained CharField with ~2.7M live rows keyed on these
   exact strings and no foreign key or choices list protecting them, so a
   future rename of a constant's VALUE would silently orphan historical data
   and change what every dashboard, review-queue filter and rescan query
   selects. EXPECTED_SKIP_REASONS below is written out by hand on purpose:
   deriving it from the same constants it is meant to guard would assert
   nothing at all.

2. KEEP THE ROSTER STATICALLY ENUMERABLE. The whole point of the convention
   is that scanning module-level declarations yields the complete set. These
   tests re-run the linter's own derivation and check it against the same
   hand-written set, so a value reintroduced as a bare inline literal (which
   the derivation cannot see) fails here even if nothing else notices.
"""
import ast
import re
from pathlib import Path

import pytest

# Every value any module under MPCAutofill/cardpicker/ declares as a
# `*_SKIP_REASON` constant, mapped to the constant name(s) that declare it.
# ONE VALUE MAPS TO MANY CONSTANTS on purpose: "no-evidence", "ambiguous",
# "no-text" and "frame-mismatch" are each emitted by several calculators under
# different `anonymous_id`s with genuinely different meanings, so each
# calculator declares its own prefixed constant.
#
# Editing this dict is how you change the roster. If a change here is NOT
# accompanied by a deliberate decision about ~2.7M existing production rows,
# it is a bug — see this module's docstring.
EXPECTED_SKIP_REASONS = {
    # Stage C extractors — image_evidence.py
    "fetch_failed": {"EXTRACTOR_FETCH_FAILED_SKIP_REASON"},
    # OCR/phash engines — local_identify_printing_tags.py
    "disagreement-with-other-engine": {"DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON"},
    "parsed-but-no-match": {"PARSED_BUT_NO_MATCH_SKIP_REASON"},
    "too-many-candidates": {"PHASH_TOO_MANY_CANDIDATES_SKIP_REASON"},
    "no-hashable-candidates": {"PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON"},
    "no-clear-winner": {"PHASH_NO_CLEAR_WINNER_SKIP_REASON"},
    "no-clear-winner-distance": {"PHASH_NO_CLEAR_WINNER_DISTANCE_SKIP_REASON"},
    "no-clear-winner-margin": {"PHASH_NO_CLEAR_WINNER_MARGIN_SKIP_REASON"},
    # Stage D join-key calculator — local_calculate_verdicts.py
    "unknown-set-code": {"JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON", "OCR_UNKNOWN_SET_CODE_SKIP_REASON"},
    "artist-mismatch": {"JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON"},
    "border-mismatch": {"JOIN_KEY_BORDER_MISMATCH_SKIP_REASON"},
    "truncated-image": {"JOIN_KEY_TRUNCATED_IMAGE_SKIP_REASON"},
    "copyright-year-mismatch": {"JOIN_KEY_COPYRIGHT_YEAR_MISMATCH_SKIP_REASON"},
    "proxy-marker-veto": {"JOIN_KEY_PROXY_MARKER_VETO_SKIP_REASON"},
    "transferred-interim-guard": {"TRANSFERRED_INTERIM_GUARD_SKIP_REASON"},
    # Stage D fallback calculator — local_calculate_verdicts.py
    "no-sub-check-evidence": {"FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON"},
    # Stage D slow path — local_calculate_verdicts.py
    "to-review": {"SLOW_PATH_TO_REVIEW_SKIP_REASON"},
    # Illustration calculator — local_illustration.py
    "no-artist-ocr": {"NO_ARTIST_OCR_SKIP_REASON"},
    # NOT LISTED, deliberately: `"multi-faced-v1"` / `SINGLE_FACED_ONLY_SKIP_REASON`. #565 deleted
    # the border-colour "multi-faced" gate outright and declined to replace the constant (see
    # `local_illustration.py`'s own "DELETED, DELIBERATELY NOT REPLACED" comment), so there is no
    # declaration left for this map to pin - and this map pins DECLARATIONS, not history. The
    # ~3,409 production `CardScanLog` rows carrying the value are not going anywhere, so the value
    # keeps its row in `docs/reference/skip-reasons.md`, marked Retired: that is where a value
    # which outlived its constant belongs. Re-adding it here would fail this suite by design.
    "no-candidate-match": {"NO_CANDIDATE_MATCH_SKIP_REASON"},
    "no-illustration-index-entry": {"NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON"},
    "multiple-illustrations": {"MULTIPLE_ILLUSTRATIONS_SKIP_REASON"},
    "multiple-printings-one-illustration": {"MULTIPLE_PRINTINGS_SKIP_REASON"},
    # AI-art detector — local_detect_ai_art.py
    "no-marker-hit": {"AI_ART_NO_MARKER_HIT_SKIP_REASON"},
    # Layout-class cast — local_layout_class_cast.py
    "unmapped-layout-class": {"LAYOUT_CLASS_UNMAPPED_SKIP_REASON"},
    # Evidence transfer — evidence_transfer.py
    "transfer-sha256-mismatch": {"EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON"},
    "transfer-content-hash-mismatch": {"EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON"},
    # Lands artist decomposition — local_lands_identify.py (REPORT-ONLY,
    # never written to CardScanLog; see the doc's own section)
    "no-artist-extracted": {"LANDS_NO_ARTIST_EXTRACTED_SKIP_REASON"},
    "artist-no-match": {"LANDS_ARTIST_NO_MATCH_SKIP_REASON"},
    "no-content-phash": {"LANDS_NO_CONTENT_PHASH_SKIP_REASON"},
    "fetch-budget-exhausted": {"LANDS_FETCH_BUDGET_EXHAUSTED_SKIP_REASON"},
    # Values emitted by MORE THAN ONE calculator, each with its own constant.
    # The `LOCAL_FALLBACK_*` three belong to the `local-fallback-v1` pilot engine
    # (`local_fallback.py`, PROTECTED CORE — declared there under the 2026-07-29
    # exception, license-provenance.md section 2.1). They are LATENT: nothing
    # persists that engine's outcome today. The `FALLBACK_*` three next to them are
    # the SEPARATE Stage D `stage-d-fallback-v1` calculator's own vocabulary in
    # `local_calculate_verdicts.py`, which is live. Two calculators, two constants,
    # one value — the same shape as "no-evidence" already had five times over.
    "no-evidence": {
        "JOIN_KEY_NO_EVIDENCE_SKIP_REASON",
        "FALLBACK_NO_EVIDENCE_SKIP_REASON",
        "LOCAL_FALLBACK_NO_EVIDENCE_SKIP_REASON",
        "AI_ART_NO_EVIDENCE_SKIP_REASON",
        "NO_EVIDENCE_SKIP_REASON",
        "LAYOUT_CLASS_NO_EVIDENCE_SKIP_REASON",
        "CHIP_NO_EVIDENCE_SKIP_REASON",
        "BLEED_CALC_NO_EVIDENCE_SKIP_REASON",
    },
    "eliminated": {
        "FALLBACK_ELIMINATED_SKIP_REASON",
        "LOCAL_FALLBACK_ELIMINATED_SKIP_REASON",
    },
    "ambiguous": {
        "EXTRACTOR_AMBIGUOUS_SKIP_REASON",
        "JOIN_KEY_AMBIGUOUS_SKIP_REASON",
        "FALLBACK_AMBIGUOUS_SKIP_REASON",
        "LOCAL_FALLBACK_AMBIGUOUS_SKIP_REASON",
        "OCR_AMBIGUOUS_SKIP_REASON",
        "LAYOUT_CLASS_AMBIGUOUS_SKIP_REASON",
        "CHIP_ABSTAINED_SKIP_REASON",
        "BLEED_CALC_AMBIGUOUS_SKIP_REASON",
    },
    "no-text": {
        "EXTRACTOR_NO_TEXT_SKIP_REASON",
        "JOIN_KEY_NO_TEXT_SKIP_REASON",
        "OCR_NO_TEXT_SKIP_REASON",
    },
    "frame-mismatch": {
        "JOIN_KEY_FRAME_MISMATCH_SKIP_REASON",
        "FRAME_MISMATCH_SKIP_REASON",
    },
    "unfetchable-image": {
        "UNFETCHABLE_IMAGE_SKIP_REASON",
        "LANDS_UNFETCHABLE_IMAGE_SKIP_REASON",
    },
    "incomplete-evidence": {
        "AI_ART_INCOMPLETE_EVIDENCE_SKIP_REASON",
        "LAYOUT_CLASS_INCOMPLETE_EVIDENCE_SKIP_REASON",
        "CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON",
        "BLEED_CALC_INCOMPLETE_EVIDENCE_SKIP_REASON",
    },
    # Attribute-chip cast — local_attribute_chip_cast.py (frame-style-cast-v1, 2026-07-30).
    # ONE vocabulary written from a single identity: the bleed half of this module
    # (bleed-edge-cast-v1) is RETIRED, so the `CHIP_` prefix now names the frame family alone.
    # Its three shared values are registered against the multi-calculator entries above; only
    # this one is new.
    #
    # APPENDED AT THE END, not filed next to the layout-class caster where it reads better.
    # `.github/scripts/constant_rename_equivalence.py` inlines this dict into every assert that
    # references it and compares the resulting trees POSITIONALLY, so inserting a key mid-dict
    # shifts every later key and reports as a behaviour divergence. A trailing addition shifts
    # nothing. Keep new entries here.
    "unmapped-frame-class": {"CHIP_UNMAPPED_SKIP_REASON"},
    # Bleed calculator — local_bleed_calculator.py (bleed-calculator-cast-v1, cross-checked
    # appropriate-bleed caster). Two values genuinely new to the roster: the abstain-gate outcome
    # itself, and the "value computed but this card isn't trimmed" outcome (the ordinary, ~97.5%
    # case). Appended at the end, same positional-stability reasoning as the CHIP entry above.
    "method-disagreement": {"BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON"},
    "not-trimmed": {"BLEED_CALC_NOT_TRIMMED_SKIP_REASON"},
}

# The same regex `.github/scripts/docs_lint.py`'s roster tether uses. Kept as a
# literal copy rather than imported: `.github/scripts/` is not an importable
# package from the Django test suite, and a copy that drifts is caught by
# `test_declared_roster_matches_docs_lint_derivation` below, which re-derives
# through the linter's own module.
SKIP_REASON_DECL_RE = re.compile(r'^(_?[A-Z][A-Z0-9_]*_SKIP_REASON)\s*=\s*"([^"]+)"', re.MULTILINE)

CARDPICKER_DIR = Path(__file__).resolve().parents[1]


def _declared() -> dict[str, set[str]]:
    """Derive {value: {constant names}} from module-level declarations.

    Non-recursive on purpose, matching the linter: this directory
    (`cardpicker/tests/`) declares fixture values that are not production
    roster members.
    """
    found: dict[str, set[str]] = {}
    for py in sorted(CARDPICKER_DIR.glob("*.py")):
        for m in SKIP_REASON_DECL_RE.finditer(py.read_text()):
            found.setdefault(m.group(2), set()).add(m.group(1))
    return found


def test_every_declared_skip_reason_value_is_unchanged():
    """THE BYTE-IDENTICAL GUARANTEE.

    Values only — this is what a `CardScanLog` row actually stores. A failure
    here means production data semantics changed, not that a name moved.

    STRICTLY SUBSUMED by `test_every_declared_constant_name_is_accounted_for`
    below (dict equality implies key-set equality), and kept anyway as a
    DIAGNOSTIC rather than as independent coverage: when a value changes, this
    one's failure output is the two value sets, which names the changed
    production string directly, where the dict comparison buries it in a
    value-to-name-set diff. It adds no mutation coverage of its own — do not
    count it as a second check.
    """
    assert set(_declared()) == set(EXPECTED_SKIP_REASONS)


def test_every_declared_constant_name_is_accounted_for():
    """The other direction: a NEW constant, or a constant renamed without
    updating this file, fails here rather than silently joining the roster."""
    assert _declared() == EXPECTED_SKIP_REASONS


@pytest.mark.parametrize("value", sorted(_declared()))
def test_no_declared_value_is_empty_or_whitespace(value):
    """`CardScanLog.skip_reason` uses `""` as its own "not a skip" sentinel
    (`local_illustration`/`local_calculate_verdicts` both branch on
    `if verdict.skip_reason:`), so an empty or whitespace-only reason would be
    invisible to every consumer of the column.

    Parametrised over `_declared()` — the values actually read out of the
    production modules — NOT over `EXPECTED_SKIP_REASONS`. Over the hand-written
    dict this test was unfalsifiable: it asserted that literals typed into this
    file are non-empty and stripped, which no implementation change can make
    false. `test_declared_roster_is_not_empty` below covers the other way this
    shape goes vacuous (a derivation that finds nothing yields zero params and
    passes silently).
    """
    assert value == value.strip()
    assert value


def test_declared_roster_is_not_empty():
    """Guards the parametrised test above from going vacuous. If `_declared()`
    ever returns `{}` — a moved `cardpicker/` directory, a regex that stops
    matching, a glob that finds no modules — pytest generates zero cases for it
    and the suite stays green while checking nothing. The roster is dozens of
    entries; a couple of dozen is a floor no legitimate change crosses."""
    declared = _declared()
    assert len(declared) >= 20, f"skip-reason derivation found only {len(declared)} values — it is probably broken"


def test_declared_roster_matches_docs_lint_derivation():
    """The linter's own derivation must see exactly the same roster this file
    pins. This is what makes the doc tether meaningful: if the two derivations
    ever disagree, the tether is checking the doc against a different set than
    the one this suite guards."""
    import importlib.util

    lint_path = CARDPICKER_DIR.parents[1] / ".github" / "scripts" / "docs_lint.py"
    if not lint_path.is_file():  # pragma: no cover - not present in a sdist/deploy tree
        pytest.skip(f"{lint_path} not present in this checkout")
    spec = importlib.util.spec_from_file_location("_docs_lint_for_test", lint_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert set(module._declared_skip_reasons()) == set(EXPECTED_SKIP_REASONS)


def test_docs_roster_tether_is_clean():
    """docs/reference/skip-reasons.md documents every declared reason.

    Runs the real lint rule rather than re-implementing it, so this test fails
    for exactly the reason CI would.
    """
    import importlib.util

    lint_path = CARDPICKER_DIR.parents[1] / ".github" / "scripts" / "docs_lint.py"
    if not lint_path.is_file():  # pragma: no cover
        pytest.skip(f"{lint_path} not present in this checkout")
    spec = importlib.util.spec_from_file_location("_docs_lint_for_test", lint_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.check_skip_reason_roster_tether() == []


# ---------------------------------------------------------------------------
# The protected-core exception's own guard rails (2026-07-29,
# docs/upstreaming/license-provenance.md section 2.1).
#
# `local_phash.find_best_match` produces two roster values. Until the owner
# granted a narrow exception, that file could not be edited, so the constants
# were MIRRORED in `local_identify_printing_tags.py` — which meant a NEW bare
# literal returned from `find_best_match` reached `CardScanLog` with nothing to
# catch it, because the roster tether cannot enumerate literals it cannot see.
#
# The exception was granted to close exactly that hole, and these two tests are
# what keep it closed. They fail if the mirror comes back (two declarations that
# can drift) or if a bare literal is reintroduced at the origin (a roster member
# no derivation can find). Neither failure mode is visible to the tether itself,
# which is the whole reason they are pinned here.
# ---------------------------------------------------------------------------

PHASH_ORIGIN_SKIP_REASONS = {
    "PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON": "no-hashable-candidates",
    "PHASH_NO_CLEAR_WINNER_SKIP_REASON": "no-clear-winner",
}


def _module_level_str_constants(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text())
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def test_phash_skip_reasons_are_declared_at_their_origin_and_nowhere_else():
    """One declaration per value, in the module that produces it."""
    declared_in_phash = _module_level_str_constants(CARDPICKER_DIR / "local_phash.py")
    for name, value in PHASH_ORIGIN_SKIP_REASONS.items():
        assert declared_in_phash.get(name) == value, (
            f"{name} must be declared in local_phash.py, where find_best_match produces it, "
            f"with the value {value!r} — see license-provenance.md section 2.1."
        )

    for py in sorted(CARDPICKER_DIR.glob("*.py")):
        if py.name == "local_phash.py":
            continue
        for name, value in _module_level_str_constants(py).items():
            assert value not in set(PHASH_ORIGIN_SKIP_REASONS.values()), (
                f"{py.name} re-declares a local_phash skip reason as {name}={value!r}. "
                f"That mirror was removed on purpose: two declarations of one value can drift. "
                f"Import it from cardpicker.local_phash instead."
            )


def test_find_best_match_returns_no_bare_skip_reason_literal():
    """Every skip reason `find_best_match` returns must be a NAME bound to one of
    its module's own constants. A bare literal here is invisible to the roster
    derivation and would reach `CardScanLog` unnoticed — the exact defect the
    protected-core exception was granted to fix."""
    path = CARDPICKER_DIR / "local_phash.py"
    tree = ast.parse(path.read_text())
    constants = _module_level_str_constants(path)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "find_best_match")

    returned = [n.value.elts[1] for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)]
    assert returned, "find_best_match no longer returns a (match, skip_reason) tuple"
    for node in returned:
        if isinstance(node, ast.Constant) and node.value == "":
            continue  # the "matched, not a skip" sentinel, not a roster member
        assert isinstance(node, ast.Name), (
            f"line {node.lineno}: find_best_match returns a bare skip-reason literal. "
            f"Declare it as a module-level *_SKIP_REASON constant and document it in "
            f"docs/reference/skip-reasons.md."
        )
        assert node.id in constants, f"line {node.lineno}: {node.id} is not a module-level string constant"


# ---------------------------------------------------------------------------
# The SECOND protected-core exception's guard rails (2026-07-29,
# docs/upstreaming/license-provenance.md section 2.1, second entry).
#
# `local_fallback.run_fallback_for_card` returns three roster values on
# `FallbackOutcome.skip_reason`. They were bare inline literals in a PROTECTED
# CORE file, so the roster tether could not see them — and a NEW literal added
# beside them would have been just as invisible. The defect was LATENT rather
# than live (the module's own write branch was retired 2026-07-29, and its one
# non-test caller, `local_residual_classify.
# recover_frame_mismatch_printing_via_fallback_refetch`, reads `printing_pk`
# and discards `skip_reason`), which is precisely why it had to be closed
# BEFORE something persists the outcome rather than after.
#
# These three tests are what keep it closed. Two of them guard the regressions
# the tether is structurally blind to — the value being MIRRORED back into
# another module, and a bare literal returning at the origin — and the third
# pins the name/value pairs to this file.
# ---------------------------------------------------------------------------

LOCAL_FALLBACK_ORIGIN_SKIP_REASONS = {
    "LOCAL_FALLBACK_NO_EVIDENCE_SKIP_REASON": "no-evidence",
    "LOCAL_FALLBACK_ELIMINATED_SKIP_REASON": "eliminated",
    "LOCAL_FALLBACK_AMBIGUOUS_SKIP_REASON": "ambiguous",
}


def test_local_fallback_skip_reasons_are_declared_at_their_origin():
    """Declared in the module that produces them, with the exact production values."""
    declared = _module_level_str_constants(CARDPICKER_DIR / "local_fallback.py")
    for name, value in LOCAL_FALLBACK_ORIGIN_SKIP_REASONS.items():
        assert declared.get(name) == value, (
            f"{name} must be declared in local_fallback.py, where run_fallback_for_card "
            f"produces it, with the value {value!r} — see license-provenance.md section 2.1."
        )


def test_local_fallback_skip_reasons_are_not_re_mirrored_elsewhere():
    """No NEW declaration of one of these three values may appear in another module.

    This cannot be the flat "declared nowhere else" check the `local_phash` pair
    gets, and the difference is not a weakening. `no-evidence`, `eliminated` and
    `ambiguous` are SHARED VOCABULARY: several calculators legitimately emit each
    of them under different `anonymous_id`s with different meanings, and the
    roster's whole design is one prefixed constant per calculator per value. A
    value-identity ban would forbid the design.

    So the check is against the pinned co-tenants instead — the exact set of
    constant names EXPECTED_SKIP_REASONS already declares for each of these three
    values, minus this module's own. Any declaration outside that set fails here.
    Adding a mirror therefore cannot be done quietly: it must be written into
    EXPECTED_SKIP_REASONS above, which this file's own docstring designates as the
    deliberate-decision gate for the roster, AND it must survive the prefix check
    below, which rejects the `LOCAL_FALLBACK_` family being re-declared anywhere
    else regardless of value.

    Scanned names are filtered to the `*_SKIP_REASON` convention this whole file is
    built on (the same boundary `_declared()`/`SKIP_REASON_DECL_RE` above use to
    define "a declared skip reason" in the first place, and the one
    `EXPECTED_SKIP_REASONS` itself is held to by `test_every_declared_constant_name_
    is_accounted_for`). Without that filter, an unrelated module's own constant that
    happens to share one of these three short, common English words as its STRING
    VALUE - `local_pinline_inset.VERDICT_AMBIGUOUS`, a whole-image verdict that
    never reaches `CardScanLog` at all - would trip
    this check, and adding either to `EXPECTED_SKIP_REASONS` to silence it would
    fail that OTHER test, which asserts the dict contains only `_SKIP_REASON`
    declarations. The two tests must therefore agree on what counts as "declared"
    here; this filter is that agreement, not a narrowing of what a mirror is.
    """
    tracked = set(LOCAL_FALLBACK_ORIGIN_SKIP_REASONS.values())
    allowed_cotenants = {
        value: EXPECTED_SKIP_REASONS[value] - set(LOCAL_FALLBACK_ORIGIN_SKIP_REASONS) for value in tracked
    }

    for py in sorted(CARDPICKER_DIR.glob("*.py")):
        for name, value in _module_level_str_constants(py).items():
            if py.name != "local_fallback.py" and name.startswith("LOCAL_FALLBACK_"):
                raise AssertionError(
                    f"{py.name} declares {name}={value!r}. The `LOCAL_FALLBACK_` skip-reason "
                    f"family is declared in local_fallback.py, where run_fallback_for_card "
                    f"produces it. Import it from cardpicker.local_fallback instead — two "
                    f"declarations of one value can drift."
                )
            if py.name == "local_fallback.py" or value not in tracked or not name.endswith("_SKIP_REASON"):
                continue
            assert name in allowed_cotenants[value], (
                f"{py.name} declares {name}={value!r}, which is not one of the calculators "
                f"already pinned for that value ({sorted(allowed_cotenants[value])}). If this is "
                f"a genuinely different calculator's own vocabulary, add it to "
                f"EXPECTED_SKIP_REASONS above as a deliberate decision. If it is a mirror of "
                f"local_fallback's constant, delete it and import the original."
            )


def test_run_fallback_for_card_sets_no_bare_skip_reason_literal():
    """Every `skip_reason=` this function passes must be a NAME bound to one of its
    module's own constants. A bare literal here is invisible to the roster
    derivation and would reach `CardScanLog` unnoticed the moment anything persists
    the outcome — the exact defect the protected-core exception was granted to fix."""
    path = CARDPICKER_DIR / "local_fallback.py"
    tree = ast.parse(path.read_text())
    constants = _module_level_str_constants(path)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_fallback_for_card")

    passed = [kw.value for kw in ast.walk(fn) if isinstance(kw, ast.keyword) and kw.arg == "skip_reason"]
    assert passed, "run_fallback_for_card no longer sets FallbackOutcome.skip_reason"
    for node in passed:
        if isinstance(node, ast.Constant) and node.value == "":
            continue  # the "matched, not a skip" sentinel, not a roster member
        assert isinstance(node, ast.Name), (
            f"line {node.lineno}: run_fallback_for_card sets a bare skip-reason literal. "
            f"Declare it as a module-level *_SKIP_REASON constant and document it in "
            f"docs/reference/skip-reasons.md."
        )
        assert node.id in constants, f"line {node.lineno}: {node.id} is not a module-level string constant"
