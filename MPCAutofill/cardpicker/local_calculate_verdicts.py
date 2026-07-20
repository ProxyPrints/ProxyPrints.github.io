"""
Stage D's calculator layer (docs/features/catalog-completion-plan.md's "Harvest-calculate
pipeline", public issue #152, "Stage D: calculators D1-D6") - the deduction step that consumes
Stage C's `ImageEvidence` rows (pure extracted signals) plus the on-disk Scryfall bulk data and
casts real votes via the EXISTING, unchanged vote-consensus machinery
(`cardpicker.printing_consensus`/`cardpicker.vote_consensus`, both PROTECTED CORE - imported and
called, never re-derived or modified, per docs/upstreaming/license-provenance.md SS2). Nothing
here writes a verdict directly onto a `Card` - every calculator casts a `CardPrintingTag` (or
skips with a `CardScanLog` row) exactly the way the live pilot's OCR/phash/fallback engines
already do, and `resolve_and_persist_printing` (printing_consensus.py) decides the actual
outcome from the accumulated votes. This is a funnel to human review, not an auto-committing
pipeline: a single calculator's vote at `VoteSource.OCR` weight
(`settings.PRINTING_TAG_MACHINE_WEIGHT`, currently 0.5) can never alone resolve a card - the
same human-backed gate every other machine engine in this codebase is subject to.

ISSUE #152's OWN TITLE ("calculators D1-D6") NAMES SIX CALCULATORS BUT NO NUMBERED SPEC EXISTS
ANYWHERE (checked: the issue body/comments, this doc's own "Stages C-F" section, the private
orchestration orientation doc) - confirmed before building, not assumed. What DOES exist and is
binding: the design frame in the dispatching directive (funnel-to-review, fast/slow path split,
collector-line-OCR-plus-set-symbol as ONE near-unique join key, the pipeline-fidelity gate's
"call the existing shipped identification code paths, don't re-derive"), `docs/theory.md`'s
candidate-constrained-decoding model, and the Governing posture section. Per the directive's own
SCOPE MGMT clause, this PR builds the calculator FRAMEWORK plus ONE coherent first slice - the
join-key calculator - and defers the rest, enumerated at the bottom of this docstring, to
follow-up PRs. Building six speculative calculators against an unwritten spec would be inventing
the spec, which the directive explicitly forbids.

THE JOIN-KEY CALCULATOR (this PR's only calculator): collector-line OCR + set-symbol phash are
ONE near-unique join key into Scryfall data, not two separate calculators run in sequence - see
the design frame's own "set+collector# = near-unique Scryfall key" framing. Concretely: a
pre-M15 card's collector line never printed a set code, so `local_ocr.validate_against_candidates`
can only match on collector number alone - when that number is shared across more than one of
the card's own candidates (different expansions, since (expansion, collector_number) is unique
per `CanonicalCard`), the result is `"ambiguous"`, not a match, even though a genuine printing
identity exists. Stage C's `symbol_phash` (issue #160) is exactly the second half of the same key
that resolves this: the card's actual set symbol, hashed, is compared against each ambiguous
candidate's own expansion glyph (`local_fallback.render_set_symbol`, PROTECTED CORE, called not
modified) via plain Hamming-distance arithmetic on the stored hash ints - the same
"reimplement the arithmetic, don't reach into the protected module's private decision logic"
pattern `local_identify_printing_tags._classify_no_clear_winner` already established for phash
distance re-derivation. Both halves of the join key are therefore inside ONE calculator
function (`calculate_join_key_verdict`), not split across D1/D2 - reconciled here after an
advisor review flagged the initial draft's D1/D2 split as contradicting the design frame's own
"one join key" framing (2026-07-20).

THE MODERATOR-FLAG VETO (the design frame's own explicit ask): `legal_line_proxy_marker_detected`
(issue #151/#212's real motivating case - a "NOT FOR SALE"/proxy watermark that misparses as a
plausible-looking collector line) is checked ONLY at the moment a join-key match would otherwise
be trusted - not before, and not against a genuine no-match/ambiguous outcome. A proxy marker
doesn't mean "this card definitely isn't printing P" (P might still be right); it means "this
specific OCR reading is untrustworthy as evidence for P", which is exactly the false-accept risk
`docs/theory.md`'s candidate-constrained-decoding model is built to bound. A vetoed match is
therefore a named SKIP (`"proxy-marker-veto"`, a genuine, non-rescannable, evidence-gathered
conclusion - not a `CardPrintingTag(is_no_match=True)` vote, since a vetoed reading is not
evidence against every one of the card's other candidates either).

AGREEMENT/CORROBORATION LAYER (this PR, built on top of the join-key calculator above - public
issue #152 continuation, "Stage D calculators D2-D5"): four cross-checks that strengthen the
join-key verdict by comparing the card's own extracted signals against the Scryfall-looked-up
printing, per `docs/theory.md`'s "verify what Scryfall asserts" soundness framing - each is a RAW
CROSS-CHECK feeding the existing verdict, not a second classifier casting its own independent
vote. All four are folded directly into `calculate_join_key_verdict`'s/`run_join_key_calculator`'s
existing control flow (no new eligible-card population, no new `anonymous_id`, no new vote type):

  - Back-face-aware candidate selection (issue #199/#213): `_resolve_candidates_for_card` tries
    the card's own name first (unchanged fast path for the ~all-front-face-or-single-faced common
    case), and only when that finds nothing AND `printing_metadata_import.is_back_face` confirms
    the name IS a known DFC back face, reconstructs the combined `"{front} // {back}"` name Scryfall
    itself uses for `CanonicalCard.name` (via the already-shipped `DFCPair` table's `back=name`
    lookup) and retries. Pre-match, not a cross-check against a found printing - it fixes candidate
    SELECTION for a cohort (back-face-named DFC uploads) that would otherwise structurally never
    match at all, since `CanonicalCard.name` for these rows is the combined Scryfall name, never
    the bare back-face name a split-image upload is named after.
  - Geometry/border agreement + frame agreement (issue #148/#149's `layout_class`/OCR-derived
    frame reading vs. the matched printing's own `CanonicalPrintingMetadata.border_color`/`frame`):
    a genuine disagreement WITHHOLDS the match entirely (`border-mismatch`/`frame-mismatch` named
    skips), mirroring `local_identify_printing_tags`'s existing frame-mismatch-withholding logic
    exactly (same `local_fallback.classify_frame_style`/`frame_style_is_consistent`, PROTECTED
    CORE, called not modified) - a join-key match landing on a printing whose real border/frame
    contradicts what's actually visible on the card face means the image most likely doesn't
    faithfully depict that specific printing, the same reasoning that precedent already
    established. `bleed_class` is NOT cross-checked here - there is no Scryfall field it could
    ever agree or disagree with (bleed is a proxy-sheet-formatting property, not a printing
    property), so despite this PR's own earlier deferred-item wording naming it, it's correctly
    out of scope for an AGREEMENT check specifically (nothing to agree or disagree WITH).
  - Artist-OCR corroboration (issue #149's `artist_ocr_name` vs. the matched printing's own
    `CanonicalCard.artist`, via `local_fallback.match_artist`, PROTECTED CORE, called not modified):
    a disagreement WEAKENS confidence (`JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT`) rather than
    vetoing - per the dispatching directive's own framing, and consistent with `match_artist`'s
    own softer, tie-tolerant design (a single fuzzy ratio below threshold is real but weaker
    evidence against a match than a hard frame/border contradiction, not proof the match is wrong).
  - Quality/integrity gating (issue #150's `image_is_truncated`): a hard veto
    (`truncated-image` named skip) - a genuinely truncated download's partial pixel data makes any
    OCR/phash reading over it untrustworthy as evidence for anything, the same "checked before
    trusting anything else" ordering `image_evidence.py`'s own extraction pass already applies.
    `blur_variance`/`image_entropy` are deliberately NOT thresholded here: both fields' own
    docstrings in `local_image_quality.py` explicitly defer "what counts as too blurry/too flat"
    to a calibrated Stage D threshold, and PR #218's real golden-set gather run explicitly did NOT
    hard-pin either value ("deliberately NOT hard-pinned" - no calibrated cutoff exists yet, only
    real numbers that haven't been turned into a threshold). Inventing an arbitrary cutoff here
    would violate this project's own "config values land only from measurement, not automatically"
    rule (image_evidence.py's own quality_signals docstring); until a calibrated number exists,
    only the binary integrity signal is acted on, and the deferred list below carries the rest
    forward explicitly rather than guessing.

A deliberate deviation from `local_identify_printing_tags`'s own precedent: `border-mismatch`/
`frame-mismatch`/`truncated-image` are NOT added to `JOIN_KEY_RESCANNABLE_SKIP_REASONS`. That
module's own "frame-mismatch" IS rescannable because a future invocation re-fetches the image and
may genuinely read it differently; Stage D's join-key calculator instead reads an already-
persisted, content-hash-keyed `ImageEvidence` row - re-selecting the same card against the exact
same stored evidence would deterministically recompute the identical mismatch forever, the same
"genuine, repeatable negative conclusion against the same deterministic image/candidates" category
`RESCANNABLE_SKIP_REASONS`'s own comment already carves out for "no-text"/"ambiguous" (permanent)
as opposed to "unfetchable-image" (transient). A future extractor VERSION bump that changes
`layout_class`/`illus_anchor_fired` would naturally produce a NEW `ImageEvidence` row only if the
card's `content_hash` also changes (this model's own "computed-once-forever" design) - re-running
the same evidence forward gains nothing.

STILL DEFERRED (explicitly out of scope, tracked as its own follow-up, NOT invented/stubbed here):
  - Visual/phash slow-path candidate matching: explicitly NOT bulk server-side phash - issue
    #150's own 2026-07-20 re-spec dropped that half in favor of user-submitted phash (task #203,
    a distinct, not-yet-designed mechanism). A slow-path calculator here would need to be
    redesigned against whatever #203 actually ships, not against the original bulk-phash idea.
  - A calibrated `blur_variance`/`image_entropy` trust-modifier threshold (see quality/integrity
    gating above) - needs real measurement against production data first, per this project's own
    "config values land only from measurement, not automatically" rule; not guessed at here.

Golden-gated the same way the join-key calculator itself was (synthetic `ImageEvidence`/`Card`/
`CanonicalCard`/`CanonicalPrintingMetadata`/`DFCPair` DB fixtures, not a live fetch - Stage D
consumes stored evidence + Scryfall-backed models, it never touches a live image, so Stage C's
golden-set convention of a real network fetch over 30 pinned cards doesn't apply here).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import imagehash

from django.db.models import QuerySet

from cardpicker.local_fallback import (
    SYMBOL_DISTANCE_THRESHOLD,
    SYMBOL_MARGIN,
    classify_frame_style,
    frame_style_is_consistent,
    match_artist,
    render_set_symbol,
)
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    CandidatePrinting,
    generate_run_id,
)
from cardpicker.local_ocr import (
    OcrParseResult,
    find_matching_candidates,
    validate_against_candidates,
)
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    DFCPair,
    ImageEvidence,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.printing_metadata_import import is_back_face
from cardpicker.utils import twos_complement

logger = logging.getLogger(__name__)

# Own anonymous_id (distinct from OCR_ANONYMOUS_ID/PHASH_ANONYMOUS_ID/FALLBACK_ANONYMOUS_ID -
# this calculator votes on a DIFFERENT population, cards with a CURRENT ImageEvidence row, not
# a fresh per-run fetch, and must be independently purgeable/re-runnable via the same
# purge_machine_votes --run-id mechanism every other engine already uses).
JOIN_KEY_ANONYMOUS_ID = "stage-d-join-key-v1"

# Same two-tier split OCR_CONFIDENCE_BOTH/OCR_CONFIDENCE_COLLECTOR_ONLY already use in
# local_identify_printing_tags.py (set+number both matched vs. collector-number-only pre-M15
# match) - duplicated as literals rather than imported, matching DEDUCTIVE_BACKFILL_ANONYMOUS_ID's
# own "avoid a hard import-time dependency between sibling engines over one constant" precedent
# in that same module. Purely informational (resolve_weighted_consensus weights by `source`
# alone, never `confidence` - see GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE's own comment for the
# same point made elsewhere in this codebase).
JOIN_KEY_CONFIDENCE_BOTH = 0.85
JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY = 0.75
# Symbol-phash tie-break resolves the ambiguous pre-M15 case using a SECOND, independent signal
# (the card's own rendered set symbol) rather than trusting the collector-number-only match
# alone - between the two tiers above: stronger than a bare unresolved ambiguity, weaker than a
# genuine set-code-in-text match (the symbol crop/threshold has its own known noise floor - see
# local_fallback.py's own SYMBOL_DISTANCE_THRESHOLD comment).
JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK = 0.75
# issue #207's precedent (OCR_NO_MATCH_CONFIDENCE/FALLBACK_NO_MATCH_CONFIDENCE, both 0.6) -
# a validated non-match is real but weaker evidence than a validated match (the parse could
# still be a misread of a candidate that does exist), duplicated as a literal for the same
# import-independence reason as the confidences above.
JOIN_KEY_NO_MATCH_CONFIDENCE = 0.6
# Artist-OCR corroboration's own weaker tier (module docstring's "agreement/corroboration
# layer"): a disagreement between `artist_ocr_name` and the matched printing's real artist
# WEAKENS an otherwise-confident join-key hit rather than vetoing it (unlike the hard
# border/frame/proxy-marker/truncated-image vetoes below, all of which withhold the match
# entirely) - `local_fallback.match_artist`'s own fuzzy-ratio threshold leaves real room for a
# false negative (an OCR misread, an unusual name spelling), so a single disagreeing signal is
# real but softer evidence against the match than a hard geometric contradiction. Placed above
# JOIN_KEY_NO_MATCH_CONFIDENCE (0.6, a genuine non-match) since this IS still a real positive
# match assertion, just a weaker one - not a calibrated number, a reasoned ordering between the
# two already-established tiers immediately above and below it.
JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT = 0.65

# A degenerate/skip outcome that stays eligible for re-selection on a future invocation, same
# convention as local_identify_printing_tags.RESCANNABLE_SKIP_REASONS - "no-evidence" here
# because ImageEvidence simply hadn't been extracted yet for this card at selection time is a
# transient state (a future extraction run may still land it), not a permanent conclusion.
JOIN_KEY_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence"})

_SYMBOL_HASH_BITS = 64


@dataclass(frozen=True)
class JoinKeyVerdict:
    """
    Pure result of one card's join-key calculation - no DB write has happened yet (mirrors
    `image_evidence.ExtractionResult`'s own compute/persist split). Exactly one of three shapes:
    a positive match (`printing_pk` set), a genuine no-match (`is_no_match=True`), or a named
    skip (`skip_reason` set, `printing_pk` is None and `is_no_match` is False) - never more than
    one of these three at once.
    """

    card_id: int
    printing_pk: Optional[int] = None
    is_no_match: bool = False
    confidence: Optional[float] = None
    detail: str = ""
    skip_reason: str = ""


def _hamming_distance(a: int, b: int, bits: int = _SYMBOL_HASH_BITS) -> int:
    """Popcount of XOR between two `bits`-wide two's-complement ints - the same pure-arithmetic
    pattern `local_identify_printing_tags._classify_no_clear_winner` already uses to re-derive a
    phash distance ranking without reaching into `local_phash.py`'s own PROTECTED CORE private
    helpers. Duplicated here (not imported - that helper is private, leading-underscore, to its
    own module) rather than shared, matching this module's own "duplicate the arithmetic,
    reimplement nothing decision-shaped" convention for confidence constants above."""
    mask = (1 << bits) - 1
    return bin((a & mask) ^ (b & mask)).count("1")


def _symbol_phash_tiebreak(
    symbol_phash: Optional[int], ambiguous_candidates: list[CandidatePrinting]
) -> Optional[CandidatePrinting]:
    """
    The second half of the join key (see module docstring): compares the card's own stored
    `symbol_phash` against each ambiguous candidate's DISTINCT expansion's rendered keyrune
    glyph (`local_fallback.render_set_symbol`, PROTECTED CORE - called, not modified), using the
    SAME threshold/margin constants (`SYMBOL_DISTANCE_THRESHOLD`/`SYMBOL_MARGIN`) that module's
    own `find_symbol_matches` applies to a live image scan - reimplemented as pure Hamming-
    distance arithmetic over the already-computed hash ints (no image, no re-fetch), the same
    "reimplement the arithmetic, don't touch the protected decision logic" pattern
    `_classify_no_clear_winner` already established for phash. Returns the unique winning
    candidate, or `None` if no glyph could be rendered, the best distance exceeds the threshold,
    or a runner-up sits within the margin (an unresolved tie, same as `find_symbol_matches`'s
    own `None` return).
    """
    if symbol_phash is None:
        return None

    distances: list[tuple[CandidatePrinting, int]] = []
    seen_expansions: set[str] = set()
    for candidate in ambiguous_candidates:
        if candidate.expansion_code in seen_expansions:
            continue  # distinct expansions only - see find_symbol_matches's own precedent
        seen_expansions.add(candidate.expansion_code)
        reference = render_set_symbol(candidate.expansion_code)
        if reference is None:
            continue
        reference_hash_int = twos_complement(str(imagehash.phash(reference)), _SYMBOL_HASH_BITS)
        distances.append((candidate, _hamming_distance(symbol_phash, reference_hash_int)))

    if not distances:
        return None

    distances.sort(key=lambda pair: pair[1])
    best_candidate, best_distance = distances[0]
    if best_distance > SYMBOL_DISTANCE_THRESHOLD:
        return None
    if len(distances) > 1 and (distances[1][1] - best_distance) <= SYMBOL_MARGIN:
        return None
    # the winning candidate's OWN expansion may still have more than one candidate sharing it
    # (e.g. two different collector numbers on the exact same ambiguous ballot - shouldn't
    # happen given find_matching_candidates already filtered to one shared number, but resolved
    # defensively rather than assumed): every ambiguous candidate on the winning expansion.
    return next(c for c in ambiguous_candidates if c.expansion_code == best_candidate.expansion_code)


def _apply_agreement_checks(
    card_id: int, matched: CandidatePrinting, base_confidence: float, detail: str, evidence: ImageEvidence
) -> JoinKeyVerdict:
    """
    The agreement/corroboration layer (module docstring) - runs once a join-key match candidate
    has been found (direct match OR symbol-phash tie-break, both call sites in
    `calculate_join_key_verdict` route through here rather than duplicating these checks), never
    on an `ambiguous`/`parsed-but-no-match`/`no-text` outcome, matching the existing moderator-flag
    veto's own "only checked at the moment a match would otherwise be trusted" scoping.

    Ordering is cost-first (cheapest, no-DB-query checks before the one query this function
    needs), mirroring `local_fallback.py`'s own 2c "border-color sample - nearly free, applied
    before 2a/2b" cost-ordering precedent:
      1. moderator-flag veto (existing, no query)
      2. truncated-image veto (new, no query)
      3. border/frame agreement (new, one `CanonicalCard` query, shared with #4)
      4. artist-OCR corroboration (new, same query's `artist` field)

    A missing `CanonicalCard` row for `matched.pk` (unit tests exercise `calculate_join_key_verdict`
    directly against hand-built `CandidatePrinting`s with no backing DB row) or a missing
    `CanonicalPrintingMetadata` sidecar degrades gracefully to "nothing to compare" (agree),
    the same semantics `local_fallback.frame_style_is_consistent` already documents for its own
    `printing_frame_value=None` case - never an error and never a spurious mismatch.
    """
    if evidence.legal_line_proxy_marker_detected:
        # THE MODERATOR-FLAG VETO (module docstring) - a would-be match is rejected as
        # untrustworthy, not accepted and not converted into is_no_match evidence either.
        return JoinKeyVerdict(card_id=card_id, skip_reason="proxy-marker-veto", detail=detail)

    if evidence.image_is_truncated:
        # THE QUALITY/INTEGRITY VETO (module docstring) - a genuinely truncated download's
        # partial pixel data makes any OCR/symbol-phash reading over it untrustworthy as
        # evidence for anything, the same reasoning image_evidence.py's own extraction pass
        # already applies by checking this BEFORE computing blur/entropy/color stats.
        return JoinKeyVerdict(card_id=card_id, skip_reason="truncated-image", detail=detail)

    canonical = CanonicalCard.objects.filter(pk=matched.pk).select_related("printing_metadata", "artist").first()
    metadata = getattr(canonical, "printing_metadata", None) if canonical is not None else None

    if metadata is not None:
        if evidence.layout_class and metadata.border_color and evidence.layout_class != metadata.border_color:
            # THE BORDER AGREEMENT VETO (module docstring) - layout_class mirrors
            # local_fallback.classify_border_color's own return convention ("black"/"white"/
            # "silver"/"borderless"), the SAME value space Scryfall's own border_color field uses
            # (confirmed via BORDER_COLOR_TO_TAG's own key set), so a direct string comparison is
            # correct - no value-to-class remapping needed, unlike frame below.
            return JoinKeyVerdict(card_id=card_id, skip_reason="border-mismatch", detail=detail)

        # frame_class is re-derived here (not read from a stored ImageEvidence field - no such
        # field exists) via the SAME two OCR-derived inputs local_identify_printing_tags.py's own
        # live-pilot pass already uses to compute it: whether a collector NUMBER was parsed
        # (post-2003 templates print one; pre-M15 templates never do) and whether the "Illus."
        # anchor fired (artist_ocr's own byproduct). PROTECTED CORE call, not a reimplementation.
        frame_class = classify_frame_style(
            parsed_a_collector_number=bool(evidence.collector_line_collector_number),
            illus_anchor_fired=bool(evidence.illus_anchor_fired),
        )
        if not frame_style_is_consistent(frame_class, metadata.frame):
            # THE FRAME AGREEMENT VETO (module docstring) - mirrors
            # local_identify_printing_tags.py's own frame-mismatch-withholding exactly.
            return JoinKeyVerdict(card_id=card_id, skip_reason="frame-mismatch", detail=detail)

    confidence = base_confidence
    if evidence.artist_ocr_name and canonical is not None:
        # ARTIST-OCR CORROBORATION (module docstring) - match_artist returns None (no surviving
        # candidate cleared its own fuzzy-ratio threshold) on a genuine disagreement; a set
        # containing matched.pk (the only candidate passed in) means agreement, left at base
        # confidence rather than boosted (the directive only asks for a disagreement to weaken
        # a hit, not for agreement to strengthen one beyond its own join-key-derived tier).
        surviving = match_artist(evidence.artist_ocr_name, [matched], {matched.pk: canonical.artist.name})
        if surviving is None:
            confidence = JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT

    return JoinKeyVerdict(card_id=card_id, printing_pk=matched.pk, confidence=confidence, detail=detail)


def calculate_join_key_verdict(
    card_id: int, evidence: ImageEvidence, candidates: list[CandidatePrinting]
) -> JoinKeyVerdict:
    """
    The join-key calculator. Pure function, no DB write (aside from `_apply_agreement_checks`'s
    own single, read-only `CanonicalCard` lookup) - reconstructs an `OcrParseResult` from Stage
    C's already-persisted `collector_line_set_code`/`collector_line_collector_number` fields (no
    re-OCR, no re-fetch) and calls the EXISTING, unmodified `local_ocr.validate_against_candidates`
    - the pipeline-fidelity gate's own "call the existing shipped identification code paths, don't
    re-derive" requirement, satisfied by direct reuse rather than a parallel implementation. Every
    would-be match (direct OR symbol-phash tie-broken) is routed through
    `_apply_agreement_checks` (module docstring's "agreement/corroboration layer") before being
    returned, rather than accepted outright.
    """
    parsed = OcrParseResult(
        raw_text=evidence.collector_line_raw_text,
        set_code=evidence.collector_line_set_code or None,
        collector_number=evidence.collector_line_collector_number or None,
    )
    matched, reason = validate_against_candidates(parsed, candidates)

    if matched is not None:
        confidence = JOIN_KEY_CONFIDENCE_BOTH if parsed.set_code is not None else JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY
        return _apply_agreement_checks(card_id, matched, confidence, parsed.raw_text, evidence)

    if reason == "ambiguous":
        ambiguous_candidates = find_matching_candidates(parsed, candidates)
        tie_broken = _symbol_phash_tiebreak(evidence.symbol_phash, ambiguous_candidates)
        if tie_broken is not None:
            return _apply_agreement_checks(
                card_id,
                tie_broken,
                JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
                f"{parsed.raw_text} + symbol_phash tiebreak",
                evidence,
            )
        return JoinKeyVerdict(card_id=card_id, skip_reason="ambiguous", detail=parsed.raw_text)

    if reason == "parsed-but-no-match":
        # genuine whole-candidate-set negative evidence - same issue #207 "the vote IS the
        # record" convention every other engine's real is_no_match cast already follows.
        return JoinKeyVerdict(
            card_id=card_id,
            is_no_match=True,
            confidence=JOIN_KEY_NO_MATCH_CONFIDENCE,
            detail=parsed.raw_text,
        )

    # reason == "no-text": nothing was parsed at all - a genuine, non-rescannable abstention
    # (an already-extracted ImageEvidence row with no collector_number found is a real, repeat-
    # able negative outcome, not a transient one - see JOIN_KEY_RESCANNABLE_SKIP_REASONS's own
    # comment for the one skip reason that IS treated as transient).
    return JoinKeyVerdict(card_id=card_id, skip_reason="no-text")


def _resolve_candidates_for_card(
    name: str, index: CandidateNameIndex, default_cards_path: Optional[Path] = None
) -> list[CandidatePrinting]:
    """
    Back-face-aware candidate selection (module docstring, issue #199/#213) - tries the card's
    own name first (the unchanged fast path for the common case: a front-face or single-faced
    upload, where `Card.name` already matches a `CanonicalCard.name` directly). Only when that
    finds NOTHING does this fall back to checking whether `name` is a known DFC back face at all
    (`printing_metadata_import.is_back_face`) - most names simply aren't, and skipping the
    DFCPair lookup for them keeps this a single extra query only for the cohort that actually
    needs it, not every card.

    `CanonicalCard.name` for a genuine double-faced card is Scryfall's own combined
    `"{front} // {back}"` string (this codebase's existing `CanonicalCard` import path stores
    Scryfall's top-level `name` field verbatim - see `integrations/game/mtg.py`'s
    `row_to_canonical_card`/`CardRow.name` - which Scryfall itself always sets to the combined
    form for a real front/back pair, never the bare back-face name alone). A back-face-named
    upload (e.g. an MPC source that split a DFC into two separate image files, one per face) can
    therefore never match `CandidateNameIndex.candidates_for(name)` directly, structurally, no
    matter how good the OCR/symbol reading is - this is a candidate-selection gap, not a
    calculator confidence problem, which is why it's fixed here rather than downstream.

    The already-shipped `DFCPair` table (`front`/`back` name pairs, populated by
    `dfc_pairs.import_dfc_pairs` from the live Scryfall API - see that module) is reused to look
    up the matching front name for `name`, then the combined name is retried against the SAME
    index. Returns whatever the direct lookup found (usually empty, that's why we're here) if
    `name` isn't a known back face, or if no `DFCPair` row exists yet for it (a real, honestly-
    reported gap - not every back face is guaranteed to have a synced `DFCPair` row at any given
    moment - rather than raising or guessing a combined name some other way).
    """
    direct = index.candidates_for(name)
    if direct:
        return direct
    if not is_back_face(name, default_cards_path=default_cards_path):
        return direct
    front_name = DFCPair.objects.filter(back=name).values_list("front", flat=True).first()
    if front_name is None:
        return direct
    return index.candidates_for(f"{front_name} // {name}")


@dataclass
class JoinKeyCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    no_match_votes_would_cast: int = 0
    votes_written: int = 0
    no_match_votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, mirroring PilotResult/FrameMismatchRecoveryResult's own "up to N, for
    # the report" convention elsewhere in this codebase.
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(anonymous_id: str) -> "QuerySet[Card]":
    """
    Mirrors `local_identify_printing_tags._eligible_base_queryset`'s shape (unresolved, no
    confirmed indexing match, card_type=CARD only, no existing vote from this calculator's own
    anonymous_id, no non-rescannable scan-log row for it) - a fresh, independent eligibility
    query rather than a call into that function directly, since this calculator's resume/skip
    population (cards with a CURRENT `ImageEvidence` row) is a genuinely different concept from
    the live pilot's own per-run candidate selection, not a variant of it.
    """
    non_rescannable_scanned_card_ids = (
        CardScanLog.objects.filter(anonymous_id=anonymous_id)
        .exclude(skip_reason__in=JOIN_KEY_RESCANNABLE_SKIP_REASONS)
        .values_list("card_id", flat=True)
    )
    return (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
        .select_related("source")
    )


def run_join_key_calculator(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    default_cards_path: Optional[Path] = None,
) -> JoinKeyCalculatorResult:
    """
    Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row (its
    `content_hash` matching the card's own live `content_phash` - an evidence row from a prior
    image version is never trusted for a card whose upload has since changed) that ran the
    `collector_line_ocr`/`symbol_region` extractors. `dry_run=True` (the default, matching every
    other Stage 3+ command's own opt-in-to-write convention) computes and counts everything
    without writing any `CardPrintingTag`/`CardScanLog` row. `default_cards_path` is passed
    straight through to `_resolve_candidates_for_card`'s own `is_back_face` call - `None` (the
    default, used in production) resolves to the real on-disk Scryfall cache; only ever overridden
    by a test.
    """
    run_id = run_id or generate_run_id()
    index = CandidateNameIndex()
    result = JoinKeyCalculatorResult(dry_run=dry_run, run_id=run_id)

    votes_batch: list[CardPrintingTag] = []
    scan_log_batch: list[CardScanLog] = []
    touched_card_ids: list[int] = []

    for card in _eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = (
            ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )
        if evidence is None:
            result.skip_counts["no-evidence"] = result.skip_counts.get("no-evidence", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=run_id, skip_reason="no-evidence"
                    )
                )
            continue

        result.cards_considered += 1
        candidates = _resolve_candidates_for_card(card.name, index, default_cards_path=default_cards_path)
        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        if verdict.skip_reason:
            result.skip_counts[verdict.skip_reason] = result.skip_counts.get(verdict.skip_reason, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=verdict.skip_reason,
                    )
                )
            continue

        if verdict.is_no_match:
            result.no_match_votes_would_cast += 1
        else:
            result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "detail": verdict.detail, "is_no_match": verdict.is_no_match})

        if not dry_run:
            votes_batch.append(
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=verdict.printing_pk,
                    is_no_match=verdict.is_no_match,
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=verdict.confidence,
                    run_id=run_id,
                )
            )
            touched_card_ids.append(card.pk)

    if not dry_run:
        CardPrintingTag.objects.bulk_create(votes_batch)
        CardScanLog.objects.bulk_create(scan_log_batch)
        for touched_card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_printing(touched_card)

        result.votes_written = sum(1 for v in votes_batch if not v.is_no_match)
        result.no_match_votes_written = sum(1 for v in votes_batch if v.is_no_match)

    return result


__all__ = [
    "JOIN_KEY_ANONYMOUS_ID",
    "JOIN_KEY_CONFIDENCE_BOTH",
    "JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY",
    "JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK",
    "JOIN_KEY_NO_MATCH_CONFIDENCE",
    "JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT",
    "JOIN_KEY_RESCANNABLE_SKIP_REASONS",
    "JoinKeyVerdict",
    "calculate_join_key_verdict",
    "JoinKeyCalculatorResult",
    "run_join_key_calculator",
]
