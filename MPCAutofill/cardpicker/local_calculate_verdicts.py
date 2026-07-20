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

THREE CHEAP ADDITIONS ON TOP OF THE FRAMEWORK (this PR, public issue #152, following #219/#221 -
per the owner's issue #220 decision, sequenced newest-last since the copyright-year check changes
the outcome space the slow-path routing calculator needs to sweep over):

1. **Slow-path routing (`calculate_slow_path_verdict`/`run_slow_path_calculator`)**: issue #220's
   owner-settled answer for the ~83% of cards the join-key calculator alone can't confidently
   resolve. Explicitly option (b) from that issue, not (a) or (c): no bulk server-side phash (the
   165k-run analysis found that costs ~84h to resolve only 2.6% - exactly why issue #203 already
   moved phash to user-submitted instead), and not user-submitted phash itself (issue #203, a
   distinct, separately-designed mechanism, deliberately not built here). This is a ROUTING step,
   not a matching engine: any card the join-key calculator concluded has no confident hit (a real
   `is_no_match` vote, or a genuine non-rescannable skip - `"ambiguous"`, `"no-text"`,
   `"proxy-marker-veto"`, or the new `"copyright-year-mismatch"` below) gets a `SlowPathVerdict`
   carrying its already-persisted `ImageEvidence` signals (collector/legal-line OCR text, layout/
   bleed class, symbol phash, quality signals) verbatim, and a `CardScanLog(anonymous_id=
   "stage-d-slow-path-v1", skip_reason="to-review")` durable routing marker. No new storage: the
   signals themselves already live in `ImageEvidence` (Stage C's job) - this calculator's own
   `SlowPathVerdict.raw_signals` is an in-memory packaging of that same data for whatever consumes
   it next (a review-queue view, an audit/report), not a second copy. Casts no `CardPrintingTag`
   at all - it has no printing to vote for - so it can never touch `resolve_and_persist_printing`'s
   own resolution logic.

2. **Copyright-year era check (`_withhold_reason_for_match`)**: the legal-line's parsed copyright
   year (`ImageEvidence.legal_line_copyright_year`, issue #151/#159) is cross-checked against the
   matched candidate's own Scryfall release date (`CanonicalPrintingMetadata.released_at`, now
   threaded onto `CandidatePrinting.released_at` alongside its existing `edhrec_rank` precedent) -
   a cheap, independent agreement signal, same shape as the moderator-flag veto below but checking
   a different disagreement. Only a LARGE gap withholds the vote - specifically the copyright year
   sitting more than `COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS` years BEFORE the candidate's own
   release year (the design frame's own "© year predating the set's release by years" framing) - a
   small/plausible gap (a print run landing near a calendar-year boundary, an older copyright
   legend surviving into a reprint) is deliberately NOT vetoed. Withheld, not confidence-adjusted:
   confirmed by reading `vote_consensus.py` directly (no `confidence` reference anywhere in it) -
   `resolve_weighted_consensus` weights strictly by `source`, so tweaking the `confidence` float
   here would be pure decoration with zero effect on resolution, the same point
   `JOIN_KEY_CONFIDENCE_BOTH`'s own comment already makes. A withheld match is a named, non-
   rescannable skip (`"copyright-year-mismatch"`) - same "the vote IS the record" shape as
   `"proxy-marker-veto"`, not added to `JOIN_KEY_RESCANNABLE_SKIP_REASONS` since both source facts
   (the OCR read, the Scryfall release date) are static once extracted/imported, unlike
   `"frame-mismatch"`'s own rescannable case in `local_identify_printing_tags` (that one is
   re-scannable for a reason specific to Part 3's dual-yield artist-extraction design, which
   doesn't apply here).

3. **Collector-number-only ambiguity guard (hardening, not new logic)**: the ~472 pre-M15 cards
   where OCR parsed a collector NUMBER but no set code (globally ambiguous on their own - ~15.7%
   of collector-number values appear in >=2 sets, per the run analysis motivating issue #220) are
   ALREADY structurally safe: `calculate_join_key_verdict` only ever receives `candidates` already
   narrowed to the card's own name (`CandidateNameIndex.candidates_for(card.name)` -
   `run_join_key_calculator`'s own call site), and `CandidatePrinting` carries no `name` field at
   all for a global re-query to even be expressible here. This item makes that invariant EXPLICIT
   (docstring + a dedicated regression test, `TestCollectorNumberOnlyStaysNameScoped`, pinning
   that two different card names sharing a collector number across different sets never cross-
   contaminate) rather than adding new matching logic - the guard already existed, per the
   directive's own "RETAIN" wording.

DEFERRED (still out of scope, tracked as follow-up - NOT invented/stubbed here):
  - Geometry/border agreement calculator: cross-check `layout_class`/`bleed_class` against a
    join-key match's own `CanonicalPrintingMetadata.border_color`/`frame` and withhold (mirroring
    the live pilot's existing frame-mismatch-withholding logic in `local_identify_printing_tags`)
    when they disagree, operating over stored `ImageEvidence` instead of a live re-fetch.
  - Artist-OCR corroboration calculator: `artist_ocr_name` cross-checked via
    `local_fallback.match_artist` (PROTECTED CORE, call not modify) against a join-key match's
    candidate artist, or used LANDS-style to narrow candidates on the slow path.
  - Back-face-aware lookup: fold `printing_metadata_import.is_back_face`
    (issue #199/#213, name-based, no `ImageEvidence` field) into join-key candidate selection for
    double-faced cards.
  - Quality/integrity gating: `image_is_truncated`/`blur_variance`/`image_entropy` as a
    trust modifier for the FAST path (the slow-path routing calculator above already carries them
    as raw signals for human review - that's not the same as a machine trust modifier).
  - User-submitted phash (issue #203) enhancing slow-path-routed cards post-hoc - the ongoing
    enhancement half of issue #220's decision, a distinct, not-yet-designed mechanism.

None of the above is built or stubbed in this PR - each is its own follow-up calculator PR,
golden-gated (synthetic `ImageEvidence`/`Card`/`CanonicalCard` DB fixtures, not a live fetch -
Stage D consumes stored evidence + Scryfall-backed models, it never touches a live image, so
Stage C's golden-set convention of a real network fetch over 30 pinned cards doesn't apply here)
per docs/features/catalog-completion-plan.md's Stage C-established "one PR per unit, tested
before merge" discipline, applied to calculators instead of extractors.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import imagehash

from django.db.models import Q, QuerySet

from cardpicker.local_fallback import (
    SYMBOL_DISTANCE_THRESHOLD,
    SYMBOL_MARGIN,
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
    Card,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    ImageEvidence,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
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

# A degenerate/skip outcome that stays eligible for re-selection on a future invocation, same
# convention as local_identify_printing_tags.RESCANNABLE_SKIP_REASONS - "no-evidence" here
# because ImageEvidence simply hadn't been extracted yet for this card at selection time is a
# transient state (a future extraction run may still land it), not a permanent conclusion.
JOIN_KEY_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence"})

# The copyright-year era check (module docstring, item 2): a gap this large or larger between the
# legal line's parsed copyright year and the matched candidate's own Scryfall release year
# withholds the match. Deliberately small and one-directional (only "copyright predates release
# by more than this many years" - the design frame's own stated failure mode; a copyright year
# AFTER release isn't the case being guarded against here and isn't checked). Picked as a genuine,
# but not exhaustively calibrated, judgment call - a small gap (a print run landing near a
# calendar-year boundary, an older copyright legend surviving into a reprint) is real and
# shouldn't veto an otherwise-good join-key hit; anything past this is implausible enough to
# distrust the reading rather than the match.
COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS = 2

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


def _withhold_reason_for_match(evidence: ImageEvidence, candidate: CandidatePrinting) -> Optional[str]:
    """
    Given a join-key match that would otherwise be trusted, returns a named skip_reason if THIS
    specific reading should be withheld rather than cast, or `None` if it's clean - factored out
    of `calculate_join_key_verdict` so both the direct-match and symbol-tiebreak branches share one
    check rather than duplicating it (an initial draft had this inline in both places). Checked
    ONLY at the moment a match would be trusted (same placement the module docstring's original
    moderator-flag veto already used) - never against a genuine no-match/ambiguous outcome, since
    neither condition here says "printing P is wrong": a proxy marker means "this reading isn't
    trustworthy evidence FOR P", and a copyright-year mismatch means "this reading disagrees with
    P's own known release era" - both are about the READING's trustworthiness, not P's identity.

    Checks, in order:
      1. THE MODERATOR-FLAG VETO (issue #151/#212's real motivating case - a "NOT FOR SALE"/proxy
         watermark misparsing as a plausible collector line): `"proxy-marker-veto"`.
      2. THE COPYRIGHT-YEAR ERA CHECK (module docstring, item 2): `"copyright-year-mismatch"` if
         the legal line's parsed copyright year sits more than
         `COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS` years BEFORE the candidate's own Scryfall
         release year. Silently skipped (no check performed, not a "no mismatch" finding) whenever
         either side of the comparison is missing - `evidence.legal_line_copyright_year` empty (no
         legal-line OCR text was parseable) or `candidate.released_at` unset (no
         `CanonicalPrintingMetadata` sidecar row yet) - an absent signal must never manufacture a
         withhold, matching this codebase's existing "missing data is not evidence" convention
         (see e.g. `_NO_DEMAND_RANK`'s own comment in local_identify_printing_tags.py). A
         non-numeric parsed year (shouldn't happen - `_COPYRIGHT_YEAR_RE`/`_BARE_YEAR_RE` only
         ever capture digit runs - but not assumed) is treated the same way: skipped, not vetoed.
    """
    if evidence.legal_line_proxy_marker_detected:
        return "proxy-marker-veto"

    if evidence.legal_line_copyright_year and candidate.released_at is not None:
        try:
            copyright_year = int(evidence.legal_line_copyright_year)
        except ValueError:
            copyright_year = None
        if copyright_year is not None:
            years_before_release = candidate.released_at.year - copyright_year
            if years_before_release > COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS:
                return "copyright-year-mismatch"

    return None


def calculate_join_key_verdict(
    card_id: int, evidence: ImageEvidence, candidates: list[CandidatePrinting]
) -> JoinKeyVerdict:
    """
    The join-key calculator (this Stage's first calculator - see module docstring). Pure function,
    no DB write - reconstructs an `OcrParseResult` from Stage C's already-persisted
    `collector_line_set_code`/`collector_line_collector_number` fields (no re-OCR, no re-fetch)
    and calls the EXISTING, unmodified `local_ocr.validate_against_candidates` - the pipeline-
    fidelity gate's own "call the existing shipped identification code paths, don't re-derive"
    requirement, satisfied by direct reuse rather than a parallel implementation.

    INVARIANT (module docstring, item 3 - the collector-number-only ambiguity guard): `candidates`
    MUST already be narrowed to this card's own name - the only correct way to produce it is
    `CandidateNameIndex.candidates_for(card.name)` (see `run_join_key_calculator`'s own call site).
    When `evidence.collector_line_set_code` is empty (the pre-M15 case - no set code was ever
    printed on the collector line), `find_matching_candidates`/`validate_against_candidates` match
    on collector number ALONE - safe here ONLY because that matching happens exclusively within
    THIS already-name-scoped list, never a fresh, global `CanonicalCard` query. A collector number
    alone is globally ambiguous across the full catalog (~15.7% of collector-number values appear
    in >=2 sets, per the run analysis motivating issue #220's slow-path decision) - this function
    has no way to enforce the invariant at runtime (`CandidatePrinting` carries no `name` field for
    a defensive re-check), so it is a caller contract, not a runtime guard: never call this with a
    `candidates` list that mixes more than one card's own name-narrowed set.
    """
    parsed = OcrParseResult(
        raw_text=evidence.collector_line_raw_text,
        set_code=evidence.collector_line_set_code or None,
        collector_number=evidence.collector_line_collector_number or None,
    )
    matched, reason = validate_against_candidates(parsed, candidates)

    if matched is not None:
        withhold_reason = _withhold_reason_for_match(evidence, matched)
        if withhold_reason is not None:
            return JoinKeyVerdict(card_id=card_id, skip_reason=withhold_reason, detail=parsed.raw_text)
        confidence = JOIN_KEY_CONFIDENCE_BOTH if parsed.set_code is not None else JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY
        return JoinKeyVerdict(card_id=card_id, printing_pk=matched.pk, confidence=confidence, detail=parsed.raw_text)

    if reason == "ambiguous":
        ambiguous_candidates = find_matching_candidates(parsed, candidates)
        tie_broken = _symbol_phash_tiebreak(evidence.symbol_phash, ambiguous_candidates)
        if tie_broken is not None:
            withhold_reason = _withhold_reason_for_match(evidence, tie_broken)
            if withhold_reason is not None:
                return JoinKeyVerdict(card_id=card_id, skip_reason=withhold_reason, detail=parsed.raw_text)
            return JoinKeyVerdict(
                card_id=card_id,
                printing_pk=tie_broken.pk,
                confidence=JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
                detail=f"{parsed.raw_text} + symbol_phash tiebreak",
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
    run_id: Optional[str] = None, dry_run: bool = True, chunk_size: int = 500, audit_sample_size: int = 20
) -> JoinKeyCalculatorResult:
    """
    Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row (its
    `content_hash` matching the card's own live `content_phash` - an evidence row from a prior
    image version is never trusted for a card whose upload has since changed) that ran the
    `collector_line_ocr`/`symbol_region` extractors. `dry_run=True` (the default, matching every
    other Stage 3+ command's own opt-in-to-write convention) computes and counts everything
    without writing any `CardPrintingTag`/`CardScanLog` row.
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
        candidates = index.candidates_for(card.name)
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


# Slow-path routing (module docstring, item 1; owner decision, public issue #220): own
# anonymous_id, same rationale as JOIN_KEY_ANONYMOUS_ID's own comment - a distinct, independently
# purgeable/re-runnable population from every other engine's. This calculator never casts a
# CardPrintingTag (it has no printing to vote for), so its only DB footprint is a CardScanLog row.
SLOW_PATH_ANONYMOUS_ID = "stage-d-slow-path-v1"

# The routing marker itself - not a genuine abstention reason in the sense CardScanLog's other
# skip_reason values are (this ISN'T "this engine looked and found nothing"), but reusing the
# same field/model rather than inventing new storage: a durable, queryable "this card was routed
# to human review, carrying partial evidence" fact, matching this pipeline's own "don't invent a
# separate vocabulary/table for a concept an existing field can hold" convention (see
# image_evidence.py's own remarks about reusing skip-reason strings rather than growing a new
# taxonomy).
SLOW_PATH_TO_REVIEW_REASON = "to-review"

# The join-key calculator's own non-match outcomes that qualify a card for slow-path routing: a
# real is_no_match vote (handled separately, via CardPrintingTag), or any of these named,
# non-rescannable CardScanLog skip_reason values it can produce. Deliberately excludes
# JOIN_KEY_RESCANNABLE_SKIP_REASONS ("no-evidence") - a card the join-key calculator never
# actually got to look at yet has nothing to route on, and will naturally become eligible once
# a future join-key pass runs.
JOIN_KEY_NO_HIT_SKIP_REASONS = frozenset({"ambiguous", "no-text", "proxy-marker-veto", "copyright-year-mismatch"})

# The ImageEvidence fields packaged into a SlowPathVerdict's raw_signals for human review - every
# extracted signal a reviewer might use to disambiguate a card with no confident join-key hit,
# EXCLUDING candidate-matching fields (collector_line_set_code/collector_line_collector_number are
# included as the OCR's own raw parse, not a verdict) and excluding anything crop-pixel/geometry-
# coordinate-only (not useful without the image itself, which this module never re-fetches -
# "we index, we do not store images", CLAUDE.md's Governing premise). No new storage: every one
# of these fields already lives in ImageEvidence (Stage C's job) - this is a read-time packaging,
# not a second copy.
SLOW_PATH_RAW_SIGNAL_FIELDS: tuple[str, ...] = (
    "collector_line_raw_text",
    "collector_line_set_code",
    "collector_line_collector_number",
    "artist_ocr_name",
    "legal_line_raw_text",
    "legal_line_copyright_year",
    "legal_line_proxy_marker_detected",
    "layout_class",
    "bleed_class",
    "symbol_phash",
    "image_is_truncated",
    "blur_variance",
    "image_entropy",
)


@dataclass(frozen=True)
class SlowPathVerdict:
    """
    Pure result of routing one card to the human review queue (module docstring, item 1) - NOT a
    match, NOT a vote; `raw_signals` is an in-memory packaging of that card's own already-persisted
    `ImageEvidence` fields (see `SLOW_PATH_RAW_SIGNAL_FIELDS`), for whatever consumes this next (a
    review-queue view, a report) - it is not written anywhere new.
    """

    card_id: int
    reason: str  # the join-key outcome that routed this card here - see JOIN_KEY_NO_HIT_SKIP_REASONS
    raw_signals: dict[str, object] = field(default_factory=dict)


def calculate_slow_path_verdict(card_id: int, reason: str, evidence: ImageEvidence) -> SlowPathVerdict:
    """
    The slow-path routing calculator (module docstring, item 1; owner decision, public issue
    #220's option (b) - "send no-hit cards straight to the human review queue with their partial
    extracted signals"). Pure function, no DB write - packages `SLOW_PATH_RAW_SIGNAL_FIELDS` off
    the SAME `ImageEvidence` row the join-key calculator already looked at (no re-fetch, no
    re-OCR) alongside `reason` (why the join-key calculator found no confident hit). NOT a
    phash-matching engine and never will be one here - issue #220's own decision explicitly
    rejected bulk server-side phash (option (a)) in favor of this routing step plus user-submitted
    phash (issue #203, option (c), a distinct, not-yet-built enhancement) as the two real answers.
    """
    raw_signals = {field_name: getattr(evidence, field_name) for field_name in SLOW_PATH_RAW_SIGNAL_FIELDS}
    return SlowPathVerdict(card_id=card_id, reason=reason, raw_signals=raw_signals)


@dataclass
class SlowPathCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    routed_would_cast: int = 0
    routed_written: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, same convention as JoinKeyCalculatorResult.audit - includes raw_signals
    # so a reader can confirm this calculator really is carrying evidence, not just a bare route.
    audit: list[dict[str, object]] = field(default_factory=list)


def _slow_path_eligible_cards_queryset() -> "QuerySet[Card]":
    """
    Cards the join-key calculator (JOIN_KEY_ANONYMOUS_ID) already concluded have no confident
    hit - either a real `is_no_match` vote, or a non-rescannable skip in
    JOIN_KEY_NO_HIT_SKIP_REASONS - and that this calculator's own SLOW_PATH_ANONYMOUS_ID hasn't
    already routed (its own idempotence/resume mechanism, same shape as every other engine's).
    A card the join-key calculator hasn't looked at yet at all (no vote, no scan-log row) is
    simply not yet in scope - this calculator only ever consumes the join-key calculator's own
    output, it never runs independently of it.
    """
    join_key_no_match_card_ids = CardPrintingTag.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
    ).values_list("card_id", flat=True)
    join_key_no_hit_scanned_card_ids = CardScanLog.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS
    ).values_list("card_id", flat=True)
    already_routed_card_ids = CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID).values_list(
        "card_id", flat=True
    )
    return (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .filter(Q(pk__in=join_key_no_match_card_ids) | Q(pk__in=join_key_no_hit_scanned_card_ids))
        .exclude(pk__in=already_routed_card_ids)
        .distinct()
        .select_related("source")
    )


def run_slow_path_calculator(
    run_id: Optional[str] = None, dry_run: bool = True, chunk_size: int = 500, audit_sample_size: int = 20
) -> SlowPathCalculatorResult:
    """
    Batch runner over every card the join-key calculator already routed to no-hit (see
    `_slow_path_eligible_cards_queryset`) - re-reads that same card's CURRENT `ImageEvidence` row
    (same content-hash-freshness check `run_join_key_calculator` uses; a card whose evidence has
    gone stale since the join-key pass is skipped here too, rather than routing stale signals to
    a reviewer) and writes a `CardScanLog(anonymous_id=SLOW_PATH_ANONYMOUS_ID,
    skip_reason=SLOW_PATH_TO_REVIEW_REASON)` durable routing marker. `dry_run=True` (the default,
    matching `run_join_key_calculator`'s own convention) computes and counts everything without
    writing.
    """
    run_id = run_id or generate_run_id()
    result = SlowPathCalculatorResult(dry_run=dry_run, run_id=run_id)

    scan_log_batch: list[CardScanLog] = []

    for card in _slow_path_eligible_cards_queryset().iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = (
            ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )
        if evidence is None:
            continue  # the join-key evidence has since gone stale - nothing current to route

        no_match_vote = CardPrintingTag.objects.filter(
            card_id=card.pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
        ).exists()
        if no_match_vote:
            reason = "parsed-but-no-match"
        else:
            scan_log = (
                CardScanLog.objects.filter(
                    card_id=card.pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS
                )
                .order_by("-scanned_at")
                .first()
            )
            # unreachable given _slow_path_eligible_cards_queryset's own filter, guarded rather
            # than assumed - see that function's own docstring for the exact eligibility contract.
            reason = scan_log.skip_reason if scan_log is not None else "unknown"

        result.cards_considered += 1
        verdict = calculate_slow_path_verdict(card.pk, reason, evidence)
        result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1
        result.routed_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "reason": verdict.reason, "raw_signals": verdict.raw_signals})

        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card.pk,
                    anonymous_id=SLOW_PATH_ANONYMOUS_ID,
                    run_id=run_id,
                    skip_reason=SLOW_PATH_TO_REVIEW_REASON,
                )
            )

    if not dry_run:
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.routed_written = len(scan_log_batch)

    return result


__all__ = [
    "JOIN_KEY_ANONYMOUS_ID",
    "JOIN_KEY_CONFIDENCE_BOTH",
    "JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY",
    "JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK",
    "JOIN_KEY_NO_MATCH_CONFIDENCE",
    "JOIN_KEY_RESCANNABLE_SKIP_REASONS",
    "JOIN_KEY_NO_HIT_SKIP_REASONS",
    "COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS",
    "SLOW_PATH_ANONYMOUS_ID",
    "SLOW_PATH_TO_REVIEW_REASON",
    "SLOW_PATH_RAW_SIGNAL_FIELDS",
    "JoinKeyVerdict",
    "calculate_join_key_verdict",
    "JoinKeyCalculatorResult",
    "run_join_key_calculator",
    "SlowPathVerdict",
    "calculate_slow_path_verdict",
    "SlowPathCalculatorResult",
    "run_slow_path_calculator",
]
