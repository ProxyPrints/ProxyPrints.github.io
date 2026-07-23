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

AGREEMENT/CORROBORATION LAYER (built on top of the join-key calculator above - public issue #152
continuation, "Stage D calculators D2-D5"): five cross-checks that strengthen the join-key
verdict by comparing the card's own extracted signals against the Scryfall-looked-up printing,
per `docs/theory.md`'s "verify what Scryfall asserts" soundness framing - each is a RAW CROSS-CHECK
feeding the existing verdict, not a second classifier casting its own independent vote. All five
are folded directly into `calculate_join_key_verdict`'s/`run_join_key_calculator`'s existing
control flow (no new eligible-card population, no new `anonymous_id`, no new vote type):

  - THE MODERATOR-FLAG SIGNAL (2026-07-21 correction - was "THE MODERATOR-FLAG VETO" through
    2026-07-21, the design frame's own original explicit ask): `legal_line_proxy_marker_detected`
    (issue #151/#212's real motivating case - a "NOT FOR SALE"/proxy watermark that misparses as a
    plausible-looking collector line) used to withhold a would-be-trusted join-key match entirely
    (named SKIP `"proxy-marker-veto"`). Corrected per owner ruling
    (docs/features/catalog-completion-plan.md's "Recovery-arc lessons" item 1's own verbatim
    encoding: the catalog REQUIRES proxy/NOT-FOR-SALE marking on every genuine upload, real
    printings' proxies included) after a live read-only trace (2026-07-21) found the veto
    discarding 1,552 already-validated candidate matches, 99.4% with a real, DB-matching
    set/number parse. A catalog-required field that's true across nearly the whole eligible
    population carries no discriminating power over whether ANY SPECIFIC match is right or wrong,
    so it no longer withholds OR weakens a match - see `_apply_agreement_checks`'s own inline
    comment at this check's exact former location for the full reasoning (including why NOT
    downgrading to a softer confidence tier, unlike artist-OCR disagreement below, is the correct
    read of the same owner ruling).
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
  - Copyright-year era check: the legal line's parsed copyright year
    (`ImageEvidence.legal_line_copyright_year`, issue #151/#159) cross-checked against the matched
    printing's own Scryfall release date (`CanonicalPrintingMetadata.released_at`) - reusing the
    SAME `CanonicalCard`/`CanonicalPrintingMetadata` query the border/frame checks just above
    already perform, no second lookup. Only a LARGE gap withholds the match entirely - specifically
    the copyright year sitting more than `COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS` years BEFORE the
    printing's own release year (copyright *predating* release - the one direction this check
    guards against; a copyright year AFTER release isn't the failure mode being checked for here).
    A small/plausible gap (a print run landing near a calendar-year boundary, an older copyright
    legend surviving into a reprint) is deliberately NOT vetoed. Withheld as a new named,
    non-rescannable skip (`"copyright-year-mismatch"`) - same "the vote IS the record" shape as
    `"border-mismatch"`/`"frame-mismatch"` above, not a confidence-field
    tweak: confirmed by reading `vote_consensus.py` directly (no `confidence` reference anywhere in
    it) - `resolve_weighted_consensus` weights strictly by `source`, so adjusting `confidence` here
    would be pure decoration with zero effect on resolution, the same point this module's own
    `JOIN_KEY_CONFIDENCE_BOTH` comment already makes elsewhere.
  - Artist-OCR corroboration (issue #149's `artist_ocr_name` vs. the matched printing's own
    `CanonicalCard.artist`, via `local_fallback.match_artist`, PROTECTED CORE, called not modified):
    a disagreement WEAKENS confidence (`JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT`) rather than
    vetoing - per the dispatching directive's own framing, and consistent with `match_artist`'s
    own softer, tie-tolerant design (a single fuzzy ratio below threshold is real but weaker
    evidence against a match than a hard frame/border/era contradiction, not proof the match is
    wrong).
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

All checks above (the moderator-flag signal, border/frame agreement, copyright-year era check,
artist-OCR corroboration, quality/integrity gating) live in ONE function, `_apply_agreement_
checks`, called from both of `calculate_join_key_verdict`'s match-producing branches (direct
match, symbol-phash tie-break) rather than duplicated across them.

A deliberate deviation from `local_identify_printing_tags`'s own precedent: `border-mismatch`/
`frame-mismatch`/`truncated-image`/`copyright-year-mismatch` are NOT added to `JOIN_KEY_
RESCANNABLE_SKIP_REASONS`. That module's own "frame-mismatch" IS rescannable because a future
invocation re-fetches the image and may genuinely read it differently; Stage D's join-key
calculator instead reads an already-persisted, content-hash-keyed `ImageEvidence` row -
re-selecting the same card against the exact same stored evidence would deterministically
recompute the identical mismatch forever, the same "genuine, repeatable negative conclusion
against the same deterministic image/candidates" category `RESCANNABLE_SKIP_REASONS`'s own
comment already carves out for "no-text"/"ambiguous" (permanent) as opposed to "unfetchable-image"
(transient). A future extractor VERSION bump that changes `layout_class`/`illus_anchor_fired`
would naturally produce a NEW `ImageEvidence` row only if the card's `content_hash` also changes
(this model's own "computed-once-forever" design) - re-running the same evidence forward gains
nothing.

TWO FURTHER CHEAP ADDITIONS (this PR, built 2026-07-20, owner decision on issue #220):

1. **Slow-path routing** (`calculate_slow_path_verdict`/`run_slow_path_calculator`, own
   `anonymous_id="stage-d-slow-path-v1"`): issue #220's owner-settled answer for the ~83% of cards
   the join-key calculator alone can't confidently resolve. Explicitly option (b) from that issue,
   not (a) bulk server-side phash (the 165k-run analysis found that costs ~84h to resolve only
   2.6% - exactly why #203 already moved phash to user-submitted instead) and not (c)
   user-submitted phash itself (issue #203, a distinct, separately-designed, not-yet-built
   mechanism, deliberately not built here). This is a ROUTING step, not a matching engine: any
   card the join-key calculator concluded has no confident hit (a real `is_no_match` vote, or a
   non-rescannable skip - `"ambiguous"`, `"no-text"`, `"border-mismatch"`, `"frame-mismatch"`,
   `"truncated-image"`, `"copyright-year-mismatch"` - NOT `"proxy-marker-veto"`, retired 2026-07-21
   per the moderator-flag signal correction above; a stale pre-2026-07-21 row carrying that value
   may still exist until `reparse_collector_evidence --selector proxy-marker-veto` retracts it)
   gets a `SlowPathVerdict`
   carrying its already-persisted `ImageEvidence` signals verbatim, and a
   `CardScanLog(anonymous_id="stage-d-slow-path-v1", skip_reason="to-review")` durable routing
   marker. No new storage: the signals themselves already live in `ImageEvidence` (Stage C's job)
   - this calculator's own `SlowPathVerdict.raw_signals` is an in-memory packaging of that same
   data for whatever consumes it next (a review-queue view, an audit/report), not a second copy.
   Casts no `CardPrintingTag` at all - it has no printing to vote for - so it can never touch
   `resolve_and_persist_printing`'s own resolution logic.
2. **Collector-number-only ambiguity guard** (hardening, not new logic): the ~472 pre-M15 cards
   where OCR parsed a collector NUMBER but no set code (globally ambiguous on their own - ~15.7%
   of collector-number values appear in >=2 sets, per the run analysis motivating issue #220's
   slow-path decision) are already structurally safe: `calculate_join_key_verdict` only ever
   receives `candidates` already narrowed to the card's own name (via `_resolve_candidates_for_
   card`, which always starts from `CandidateNameIndex.candidates_for(card.name)` and only ever
   widens to the DFC-combined name for a confirmed back face - never a global re-query), and
   `CandidatePrinting` carries no `name` field for a global re-match to even be expressible here.
   This item makes that invariant EXPLICIT (docstring + a dedicated regression test,
   `TestCollectorNumberOnlyStaysNameScoped`, pinning that two different card names sharing a
   collector number across different sets never cross-contaminate, including a defense-in-depth
   case proving a misscoped candidate list degrades to `"ambiguous"`, never a silent
   wrong-printing match) rather than adding new matching logic - the guard already existed, per
   the directive's own "RETAIN" wording.

STILL DEFERRED (explicitly out of scope, tracked as its own follow-up, NOT invented/stubbed here):
  - Visual/phash SLOW-PATH MATCHING (distinct from the slow-path ROUTING calculator built above -
    routing sends a no-hit card to a human with its raw signals; matching would use those signals
    to narrow candidates automatically): explicitly NOT bulk server-side phash - issue #150's own
    2026-07-20 re-spec dropped that half in favor of user-submitted phash (task #203, a distinct,
    not-yet-designed mechanism). A slow-path MATCHING calculator here would need to be redesigned
    against whatever #203 actually ships, not against the original bulk-phash idea.
  - A calibrated `blur_variance`/`image_entropy` trust-modifier threshold (see quality/integrity
    gating above) - needs real measurement against production data first, per this project's own
    "config values land only from measurement, not automatically" rule; not guessed at here. The
    slow-path routing calculator already carries both as raw signals for human review, which is
    not the same as a machine trust modifier.

Golden-gated the same way the join-key calculator itself was (synthetic `ImageEvidence`/`Card`/
`CanonicalCard`/`CanonicalPrintingMetadata`/`DFCPair` DB fixtures, not a live fetch - Stage D
consumes stored evidence + Scryfall-backed models, it never touches a live image, so Stage C's
golden-set convention of a real network fetch over 30 pinned cards doesn't apply here).

PRE-FIRE PREP (this PR, owner-bundled ahead of the full-catalog Stage D fire - two pieces, both
code-only, neither runs any prod extraction/write):

PIECE 1 - THE FALLBACK CHANNEL CALCULATOR (`calculate_fallback_verdict`/`run_fallback_calculator`,
own `anonymous_id="stage-d-fallback-v1"`): Stage D's own port of `local_fallback.py`'s pilot
"Pass 2" evidence-combination model (that module's own docstring: "fires only when pass 1
(OCR/phash) yields no accepted vote for a card") - here, "pass 1" is the join-key calculator
above, and this calculator is Stage D's own pass 2, run over exactly the cards the join-key
calculator already concluded have no confident hit (the SAME population
`run_slow_path_calculator` already routes to human review - `_fallback_eligible_cards_queryset`
reuses that exact eligibility shape). Unlike the pilot's own `run_fallback_for_card` (which crops
and phash-scans a LIVE `PIL.Image`), this calculator operates ENTIRELY off already-persisted
`ImageEvidence` fields - it never re-fetches an image (this file never has - "we index, we do not
store images", CLAUDE.md's Governing premise):

  - border sub-check: `evidence.layout_class` (Stage C's own `classify_border_color` output,
    PROTECTED CORE, already computed) fed straight into `local_fallback.filter_by_border_color`
    (PROTECTED CORE, called not modified) - identical to the pilot's own border filter, just fed a
    pre-computed reading instead of a fresh pixel sample.
  - artist sub-check: `evidence.artist_ocr_name` (Stage C's own `artist_ocr` extractor, which
    itself calls `local_fallback.extract_artist_name` - the SAME "Illus. <name>" extraction the
    pilot's own `detect_illus_anchor` performs, confirmed by reading `image_evidence.py`'s own
    `artist_ocr` section) fed straight into `local_fallback.match_artist` (PROTECTED CORE, called
    not modified).
  - symbol sub-check (`_filter_by_symbol_phash`): the pilot's own `find_symbol_matches` scans a
    live crop against a rendered keyrune glyph via phash; here, `evidence.symbol_phash` (Stage C's
    own precomputed region hash) is compared to each candidate's DISTINCT expansion's rendered
    glyph (`local_fallback.render_set_symbol`, PROTECTED CORE, called not modified) via the SAME
    pure-Hamming-distance-arithmetic reimplementation `_symbol_phash_tiebreak` above already
    established for the join-key calculator's own symbol tie-break (`SYMBOL_DISTANCE_THRESHOLD`/
    `SYMBOL_MARGIN`, PROTECTED CORE constants, reused verbatim) - duplicated rather than shared
    with `_symbol_phash_tiebreak` (this module's own "duplicate the arithmetic, reimplement
    nothing decision-shaped" convention, same reasoning `JOIN_KEY_CONFIDENCE_BOTH`'s own comment
    already gives) because the two return different shapes: `_symbol_phash_tiebreak` returns one
    winning `CandidatePrinting` for its own tie-break call site, `_filter_by_symbol_phash` returns
    the FULL SET of surviving candidate pks, mirroring `find_symbol_matches`'s own return
    convention and this calculator's own filter-intersection model.

  A vote is cast ONLY when the intersection across every sub-check that DID produce a reading
  narrows to EXACTLY ONE candidate - `local_fallback.py`'s own documented rule, reproduced exactly,
  never loosened. No agreement/corroboration layer (frame/copyright-year/truncated-image) is
  applied here, unlike the join-key calculator above - the task scope is a FAITHFUL port of
  `local_fallback.py`'s own decision model, not an augmented one; `local_fallback.py` itself never
  performed those checks, so adding them here would not be "reproducing local-fallback-v1's
  decision" as scoped. `FALLBACK_CONFIDENCE_MULTI_EVIDENCE`/`FALLBACK_CONFIDENCE_SINGLE_EVIDENCE`
  (imported from `local_fallback`, not duplicated - these ARE the pilot's own exact values, not a
  new Stage-D-specific tier) are used verbatim, unlike the join-key calculator's own brand-new
  confidence constants.

  `source=VoteSource.OCR` (not `VoteSource.DEDUCTION`): `VoteSource`'s own docstring in
  `models.py` explicitly names "the border/artist/symbol evidence-combination fallback" as part of
  OCR's own umbrella definition ("everything in `cardpicker.local_identify_printing_tags`/
  `local_fallback` that actually looks at the card image") - this calculator inspects image-derived
  evidence (border/artist/symbol readings), it does not perform `deductive_backfill.py`'s own
  "pure logical inference from already-trusted structured data, zero image inspection." Machine
  weight (`PRINTING_TAG_MACHINE_WEIGHT`) either way - the human-backed consensus gate in
  `vote_consensus.resolve_weighted_consensus` (PROTECTED CORE, unmodified) applies identically
  regardless of which `VoteSource` value is used, so this is a naming-precision choice, not a
  soundness one.

  Wired into `run_slow_path_calculator`'s own eligibility query
  (`_slow_path_eligible_cards_queryset`): a card this calculator successfully votes on is excluded
  from slow-path routing (an additional exclusion alongside its own pre-existing ones) - otherwise,
  within the SAME invocation, slow-path would route a card to human review that this calculator
  resolves moments later, since the management command runs join-key -> fallback -> slow-path in
  that order. A card this calculator merely SCANNED but abstained on (no-evidence/eliminated/
  ambiguous) is NOT excluded - it still has no confident automated hit and belongs in the review
  queue exactly as before.

CONSTANT #3 - INTENTIONALLY NOT RESTORED (owner ruling, 2026-07-22, superseding an earlier draft
of this PR that DID add a `.exclude(printing_tags__source=VoteSource.DEDUCTION)` clause here):
`docs/pipeline-fidelity-gate.md` SS3 item 3 / `docs/reports/2026-07-22-knowledge-inventory.md`'s
former MISSING item 3 flagged that the pilot never re-voted a card
`deductive_backfill.py`'s own `DEDUCTIVE_BACKFILL_ANONYMOUS_ID="deductive-backfill-v1"` pass had
already voted for (28,112 live production votes, `run_id=None`, per the gate page's SS6). A
read-only backfill investigation found this exclusion would be a net-negative single-cohort
carve-out, not a restoration worth making: that 2026-07-14 backfill is pure name/metadata
deduction (never phash/OCR - zero image inspection, see `deductive_backfill.py`'s own module
docstring), its votes are sound (a 15-card sample checked all correct), and excluding those cards
from Stage D would strand ~27,819 sound-but-UNRESOLVED cards outside the new pipeline for no
protective benefit. Re-evaluating them is safe: the human-backed consensus gate
(`vote_consensus.resolve_weighted_consensus`, PROTECTED CORE, unmodified) still prevents any
machine-only vote accumulation from resolving a card by itself regardless of how many engines
vote on it, agreement between the backfill's vote and a fresh Stage D vote simply dedups (no harm
done), and a disagreement surfaces the card to human review (a genuine corroboration signal, not
noise). The pilot's own exclusion was a PERFORMANCE optimization (skip a card its own weaker
engines couldn't add anything to), not a soundness mechanism - restoring it here would trade real
coverage for a protection Stage D's vote-consensus layer already provides independently.
`_eligible_cards_queryset`'s pre-existing per-calculator stable-`anonymous_id` exclusion (its own
long-standing idempotence mechanism, entirely independent of this constant) is unaffected and
unchanged by this decision - see that function's own docstring.

Constants #1 (`RESOLUTION_FLOOR_DPI`) and #2 (`EXCLUDED_RESOLVED_TAGS`) were ruled
must-fix-before-fire the same day (owner ruling, 2026-07-22) and are applied in
`_eligible_cards_queryset` below (see that function's own docstring and the two constants'
definitions immediately above it) - unaffected by, and independent of, the ruling on #3 above.

This PR is CODE ONLY: it does not run the full-catalog Stage D fire, the targeted re-extraction of
issue #340's 373-card cohort, or any other prod extraction/write - both remain separate,
owner-gated prod steps.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import imagehash

from django.db.models import Q, QuerySet

from cardpicker.local_fallback import (
    FALLBACK_CONFIDENCE_MULTI_EVIDENCE,
    FALLBACK_CONFIDENCE_SINGLE_EVIDENCE,
    SYMBOL_DISTANCE_THRESHOLD,
    SYMBOL_MARGIN,
    classify_frame_style,
    filter_by_border_color,
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
# border/frame/proxy-marker/truncated-image/copyright-year vetoes, all of which withhold the
# match entirely) - `local_fallback.match_artist`'s own fuzzy-ratio threshold leaves real room for
# a false negative (an OCR misread, an unusual name spelling), so a single disagreeing signal is
# real but softer evidence against the match than a hard geometric/era contradiction. Placed above
# JOIN_KEY_NO_MATCH_CONFIDENCE (0.6, a genuine non-match) since this IS still a real positive
# match assertion, just a weaker one - not a calibrated number, a reasoned ordering between the
# two already-established tiers immediately above and below it.
JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT = 0.65

# A degenerate/skip outcome that stays eligible for re-selection on a future invocation, same
# convention as local_identify_printing_tags.RESCANNABLE_SKIP_REASONS - "no-evidence" here
# because ImageEvidence simply hadn't been extracted yet for this card at selection time is a
# transient state (a future extraction run may still land it), not a permanent conclusion.
JOIN_KEY_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence"})

# The copyright-year era check (module docstring): a gap this large or larger between the legal
# line's parsed copyright year and the matched printing's own Scryfall release year withholds the
# match. Deliberately small and one-directional (only "copyright predates release by more than
# this many years" - the design frame's own stated failure mode; a copyright year AFTER release
# isn't the case being guarded against here and isn't checked). Picked as a genuine, but not
# exhaustively calibrated, judgment call - a small gap (a print run landing near a calendar-year
# boundary, an older copyright legend surviving into a reprint) is real and shouldn't veto an
# otherwise-good join-key hit; anything past this is implausible enough to distrust the reading
# rather than the match.
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


def _apply_agreement_checks(
    card_id: int, matched: CandidatePrinting, base_confidence: float, detail: str, evidence: ImageEvidence
) -> JoinKeyVerdict:
    """
    The agreement/corroboration layer (module docstring) - runs once a join-key match candidate
    has been found (direct match OR symbol-phash tie-break, both call sites in
    `calculate_join_key_verdict` route through here rather than duplicating these checks), never
    on an `ambiguous`/`parsed-but-no-match`/`no-text` outcome, matching the moderator-flag signal's
    own "only checked at the moment a match would otherwise be trusted" scoping (still true even
    though, as of 2026-07-21, that check no longer withholds or weakens anything - see its own
    inline comment below).

    Ordering is cost-first (cheapest, no-DB-query checks before the one query this function
    needs), mirroring `local_fallback.py`'s own 2c "border-color sample - nearly free, applied
    before 2a/2b" cost-ordering precedent:
      1. moderator-flag signal (no query, no-op as of 2026-07-21 - see its own inline comment)
      2. truncated-image veto (no query)
      3. border agreement (one `CanonicalCard` query, shared with 4/5/6)
      4. frame agreement (same query)
      5. copyright-year era check (same query's `released_at` field)
      6. artist-OCR corroboration (same query's `artist` field)

    A missing `CanonicalCard` row for `matched.pk` (unit tests exercise `calculate_join_key_verdict`
    directly against hand-built `CandidatePrinting`s with no backing DB row) or a missing
    `CanonicalPrintingMetadata` sidecar degrades gracefully to "nothing to compare" (agree),
    the same semantics `local_fallback.frame_style_is_consistent` already documents for its own
    `printing_frame_value=None` case - never an error and never a spurious mismatch. The
    copyright-year check applies this same "missing data is not evidence" rule independently: an
    absent `legal_line_copyright_year` OR an absent `released_at` skips the check entirely, never
    manufacturing a withhold from silence.
    """
    # THE MODERATOR-FLAG SIGNAL (module docstring - was "THE MODERATOR-FLAG VETO" through
    # 2026-07-21; owner-ruled correction, verified against docs/features/catalog-completion-
    # plan.md's "Recovery-arc lessons" item 4, encoded verbatim there: "all cards in the catalog
    # should show proxy/not for sale somewhere even if they are an actual printing. that is a
    # catalog requirement"). `legal_line_proxy_marker_detected` used to withhold an otherwise-good
    # join-key match outright (named skip `"proxy-marker-veto"`) - a live read-only trace
    # (2026-07-21) found this discarded 1,552 already-validated candidate matches, 99.4% of which
    # had a real, DB-matching set/number parse. The premise the veto was built on ("a detected
    # marker makes THIS match untrustworthy") doesn't hold once the marker is catalog-REQUIRED on
    # every genuine upload here, proxies of real printings included: its presence is closer to a
    # near-constant across the whole eligible population than a signal that covaries with whether
    # a SPECIFIC join-key match is right or wrong, which is exactly what a confidence-weakening
    # signal (see JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT immediately below, a genuine covarying
    # cross-check) requires to mean anything.
    #
    # Deliberately NOT downgraded to a weaker confidence tier either (unlike the artist-OCR
    # disagreement case) - a signal this non-discriminating gives no principled basis for picking
    # a specific weaker number; inventing one anyway would repeat exactly the "a threshold invented
    # without measurement" mistake this module's own quality/integrity gating note above already
    # declines to make for blur_variance/image_entropy. The match therefore proceeds at its
    # already-computed base_confidence, completely unaffected by this field - detection is neither
    # a withhold NOR a weakening signal here, matching the corrected owner framing exactly. (The
    # OPPOSITE case - a genuinely ABSENT marker, `legal_line_proxy_marker_detected=False` - is a
    # separate, real, and still-unbuilt catalog-compliance gap, tracked as its own owner-gated item
    # in that same doc section, not something this function is the right place to act on: matching
    # is this function's only job, and marker ABSENCE says nothing about whether a match is right.)

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

        # THE COPYRIGHT-YEAR ERA CHECK (module docstring) - reuses the SAME metadata row the
        # border/frame checks above already fetched, no second query. Skipped entirely (not a
        # "no mismatch" finding) whenever either side of the comparison is missing.
        if evidence.legal_line_copyright_year and metadata.released_at is not None:
            try:
                copyright_year = int(evidence.legal_line_copyright_year)
            except ValueError:
                copyright_year = None
            if copyright_year is not None:
                years_before_release = metadata.released_at.year - copyright_year
                if years_before_release > COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS:
                    return JoinKeyVerdict(card_id=card_id, skip_reason="copyright-year-mismatch", detail=detail)

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

    INVARIANT (module docstring's collector-number-only ambiguity guard): `candidates` MUST
    already be narrowed to this card's own name - the only correct way to produce it is
    `_resolve_candidates_for_card(card.name, index, ...)` (see `run_join_key_calculator`'s own
    call site), which itself only ever starts from `CandidateNameIndex.candidates_for(card.name)`
    and widens to a DFC-combined name for a confirmed back face, never a global query. When
    `evidence.collector_line_set_code` is empty (the pre-M15 case - no set code was ever printed
    on the collector line), `find_matching_candidates`/`validate_against_candidates` match on
    collector number ALONE - safe here ONLY because that matching happens exclusively within THIS
    already-name-scoped list, never a fresh, global `CanonicalCard` query. A collector number alone
    is globally ambiguous across the full catalog (~15.7% of collector-number values appear in
    >=2 sets, per the run analysis motivating issue #220's slow-path decision) - this function has
    no way to enforce the invariant at runtime (`CandidatePrinting` carries no `name` field for a
    defensive re-check), so it is a caller contract, not a runtime guard: never call this with a
    `candidates` list that mixes more than one card's own name-narrowed set.
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

    NAME-SCOPING NOTE (module docstring's collector-number-only ambiguity guard): both branches
    here return a list scoped to a SINGLE name (either `name` itself, or the one combined DFC
    name) - never a union of more than one name's candidates, which is exactly what
    `calculate_join_key_verdict`'s own docstring requires of its `candidates` argument.
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


# Knowledge-inventory constants #1/#2 (module docstring's "CONSTANT #3" section; full finding:
# `docs/pipeline-fidelity-gate.md` SS3, `docs/reports/2026-07-22-knowledge-inventory.md`) - the
# two remaining MISSING pilot-era constants the sweep found absent from Stage D, ruled
# must-fix-before-fire by the owner (2026-07-22), unlike constant #3 (the deductive-backfill
# exclusion) which was ruled the opposite way the same day and must NOT be reintroduced here (see
# `_eligible_cards_queryset`'s own docstring below). Duplicated as literals rather than imported
# from `local_identify_printing_tags` - same "avoid a hard import-time dependency between sibling
# engines over one constant" precedent `JOIN_KEY_CONFIDENCE_BOTH`'s own comment above already
# establishes for this module, not a fresh decision.

# Constant #1: the empirically-validated resolution floor (dpi<=150 measurably degrades OCR
# yield - see `local_identify_printing_tags.RESOLUTION_FLOOR_DPI`'s own sweep comment for the
# full 6-way dpi sweep this number comes from) - the pilot never fetched, let alone voted on, a
# card whose source image sits below it. Same value as that sibling module's own constant.
RESOLUTION_FLOOR_DPI = 200

# Constant #2: a card already tagged custom-art/non-english has its printing-identification
# precondition (an authentic depiction of a real printing) already falsified, so the pilot
# excluded it from selection entirely - same exclusion rationale, same tag names, as
# `local_identify_printing_tags.EXCLUDED_RESOLVED_TAGS`.
EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]


def _eligible_cards_queryset(
    anonymous_id: str, rescannable_skip_reasons: frozenset[str] = JOIN_KEY_RESCANNABLE_SKIP_REASONS
) -> "QuerySet[Card]":
    """
    Mirrors `local_identify_printing_tags._eligible_base_queryset`'s shape (unresolved, no
    confirmed indexing match, card_type=CARD only, no existing vote from this calculator's own
    anonymous_id, no non-rescannable scan-log row for it) - a fresh, independent eligibility
    query rather than a call into that function directly, since this calculator's resume/skip
    population (cards with a CURRENT `ImageEvidence` row) is a genuinely different concept from
    the live pilot's own per-run candidate selection, not a variant of it. `rescannable_skip_reasons`
    defaults to `JOIN_KEY_RESCANNABLE_SKIP_REASONS` (this function's original, only caller for a
    long time); `run_fallback_calculator` passes its own `FALLBACK_RESCANNABLE_SKIP_REASONS`
    instead, since the two calculators' own skip vocabularies mean different things by the same
    "transient, re-selectable" concept.

    Idempotence for a repeated multi-pass Stage D fire comes entirely from the stable, per-
    calculator `anonymous_id` exclusion above (`.exclude(printing_tags__anonymous_id=anonymous_id)`)
    - deliberately the ONLY vote-population exclusion here. An earlier draft of this module also
    excluded any card already carrying a `VoteSource.DEDUCTION` printing vote (the pilot's own
    "don't re-vote a card the deductive backfill already covered" behavior, `docs/pipeline-
    fidelity-gate.md` SS3 item 3) - owner-ruled OUT (2026-07-22, see module docstring's own
    "CONSTANT #3" section for the full reasoning): that exclusion would strand ~27,819
    sound-but-UNRESOLVED cards outside Stage D for no protective benefit, since the human-backed
    consensus gate already makes re-evaluating them safe. Do not re-add it without a fresh ruling.

    Applies the two remaining MISSING knowledge-inventory constants (owner-ruled must-fix,
    2026-07-22 - see `RESOLUTION_FLOOR_DPI`/`EXCLUDED_RESOLVED_TAGS`'s own comments above):

    1. `RESOLUTION_FLOOR_DPI` - excluded via `.exclude(Q(dpi__lt=...) & Q(dpi__isnull=False))`
       rather than the pilot's own bare `.exclude(dpi__lt=RESOLUTION_FLOOR_DPI)`
       (`local_identify_printing_tags.select_candidates`'s own usage): a bare `dpi__lt` exclude is
       NOT null-safe. SQL's three-valued logic means `NOT (dpi < 200)` evaluates to NULL, not
       TRUE, for a NULL `dpi`, so a plain `.exclude(dpi__lt=...)` would silently drop a null-dpi
       card from the eligible pool too, not just a genuinely-low-dpi one - confirmed directly
       against this project's own Postgres (`str(Card.objects.exclude(dpi__lt=200).query)`
       compiles to exactly `WHERE NOT ("dpi" < 200)`, no `IS NULL` branch). `Card.dpi` is a
       DB-level NOT NULL column today (confirmed live: 0 nulls in production), so this never bites
       in practice yet - guarded anyway since the floor's own justification (a source image too
       coarse to trust) says nothing about a row where dpi was never computed at all, and this is
       cheaper than trusting a constraint that could someday move.
    2. `EXCLUDED_RESOLVED_TAGS` - same `tags__contains` mechanism the pilot's own
       `_eligible_base_queryset` already uses, one `.exclude(...)` per tag. `Card.tags` is a
       Postgres `ArrayField`; `__contains` here is Django's array-containment lookup (`tags @>
       ARRAY[...]`), not the JSONField `contains` operator - same lookup name, different
       semantics, matching the pilot's own established usage.
    """
    non_rescannable_scanned_card_ids = (
        CardScanLog.objects.filter(anonymous_id=anonymous_id)
        .exclude(skip_reason__in=rescannable_skip_reasons)
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
        .exclude(Q(dpi__lt=RESOLUTION_FLOOR_DPI) & Q(dpi__isnull=False))
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
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


# ---------------------------------------------------------------------------------------------
# PIECE 1: the fallback channel calculator (module docstring) - Stage D's own port of
# local_fallback.py's pilot "Pass 2" evidence-combination model. Own anonymous_id, same rationale
# as JOIN_KEY_ANONYMOUS_ID's own comment - a distinct, independently purgeable/re-runnable
# population, kept separate from the pilot's own "local-fallback-v1" identity (that identity
# belongs to the live legacy engine, which continues to run against a fresh per-invocation fetch;
# this calculator consumes stored ImageEvidence instead, a genuinely different population).
# ---------------------------------------------------------------------------------------------

STAGE_D_FALLBACK_ANONYMOUS_ID = "stage-d-fallback-v1"

# This calculator's own skip vocabulary. Deliberately NOT "no-evidence" for the
# no-sub-check-produced-a-reading case (unlike local_fallback.FallbackOutcome's own literal
# "no-evidence" naming for the identical concept) - "no-evidence" is already Stage D's own
# established name (see JOIN_KEY_RESCANNABLE_SKIP_REASONS above) for a DIFFERENT concept ("this
# card's ImageEvidence row itself doesn't exist yet") - reusing it here for a different meaning,
# even scoped to a different anonymous_id, would be a needless collision in a reader's head for
# no benefit. "eliminated"/"ambiguous" ARE kept verbatim from the pilot's own vocabulary - those
# two carry the same meaning here as there, no rename needed.
FALLBACK_NO_EVIDENCE_SKIP_REASON = "no-evidence"  # this calculator's own ImageEvidence-row-missing case, same meaning as JOIN_KEY's own identical string, different anonymous_id scope
FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON = "no-sub-check-evidence"  # local_fallback.FallbackOutcome's own "no-evidence" concept, renamed to avoid colliding with the line above
FALLBACK_RESCANNABLE_SKIP_REASONS = frozenset({FALLBACK_NO_EVIDENCE_SKIP_REASON})


@dataclass(frozen=True)
class FallbackVerdict:
    """
    Pure result of one card's fallback-calculator run (module docstring's PIECE 1) - no DB write
    has happened yet, mirrors `JoinKeyVerdict`'s own compute/persist split. Exactly one of two
    shapes: a positive match (`printing_pk` set, `is_no_match` always False - this calculator, like
    the pilot's own fallback pass, never casts a genuine no-match vote, only a match or an
    abstention) or a named skip (`skip_reason` set, `printing_pk` is None).
    """

    card_id: int
    printing_pk: Optional[int] = None
    confidence: Optional[float] = None
    detail: str = ""
    skip_reason: str = ""
    evidence_types_used: tuple[str, ...] = ()


def _filter_by_symbol_phash(symbol_phash: Optional[int], candidates: list[CandidatePrinting]) -> Optional[set[int]]:
    """
    The fallback calculator's own symbol sub-check (module docstring's PIECE 1) - the SAME
    pure-Hamming-distance-arithmetic reimplementation `_symbol_phash_tiebreak` above already
    established (`render_set_symbol`, PROTECTED CORE, called not modified; `SYMBOL_DISTANCE_THRESHOLD`/
    `SYMBOL_MARGIN`, PROTECTED CORE constants, reused verbatim), duplicated rather than shared with
    `_symbol_phash_tiebreak` (this module's own "duplicate the arithmetic, reimplement nothing
    decision-shaped" convention - see `JOIN_KEY_CONFIDENCE_BOTH`'s own comment for the same
    reasoning applied to a constant rather than a function) because the two return different
    shapes: `_symbol_phash_tiebreak` returns one winning `CandidatePrinting` for the join-key
    calculator's own tie-break call site (only ever called against an already-narrowed "ambiguous"
    subset), while this returns the FULL SET of surviving candidate pks across the WHOLE candidate
    list passed in - mirroring `local_fallback.find_symbol_matches`'s own return convention exactly,
    which is what this calculator's border/artist/symbol INTERSECTION model needs to compose with
    `filter_by_border_color`/`match_artist`'s own `Optional[set[int]]` shape.

    Returns `None` (no reading - filters nothing) if `symbol_phash` is `None`, no candidate's
    expansion glyph could be rendered, the best distance exceeds `SYMBOL_DISTANCE_THRESHOLD`, or a
    runner-up sits within `SYMBOL_MARGIN` of the best (an unresolved tie) - the same four
    abstention cases `find_symbol_matches`'s own docstring documents for its live-image-scan
    version.
    """
    if symbol_phash is None:
        return None

    distances: list[tuple[str, int]] = []
    seen_expansions: set[str] = set()
    for candidate in candidates:
        if candidate.expansion_code in seen_expansions:
            continue
        seen_expansions.add(candidate.expansion_code)
        reference = render_set_symbol(candidate.expansion_code)
        if reference is None:
            continue
        reference_hash_int = twos_complement(str(imagehash.phash(reference)), _SYMBOL_HASH_BITS)
        distances.append((candidate.expansion_code, _hamming_distance(symbol_phash, reference_hash_int)))

    if not distances:
        return None

    distances.sort(key=lambda pair: pair[1])
    best_expansion, best_distance = distances[0]
    if best_distance > SYMBOL_DISTANCE_THRESHOLD:
        return None
    if len(distances) > 1 and (distances[1][1] - best_distance) <= SYMBOL_MARGIN:
        return None

    return {c.pk for c in candidates if c.expansion_code == best_expansion}


def calculate_fallback_verdict(
    card_id: int, evidence: ImageEvidence, candidates: list[CandidatePrinting]
) -> FallbackVerdict:
    """
    The fallback channel calculator (module docstring's PIECE 1) - Stage D's own port of
    `local_fallback.run_fallback_for_card`'s evidence-combination model, operating ENTIRELY off
    already-persisted `ImageEvidence` fields (never a live image/re-OCR - this file never
    re-fetches). Each sub-check is either a DIRECT CALL into `local_fallback`'s own pure decision
    function (`filter_by_border_color`, `match_artist` - both PROTECTED CORE, neither touches a raw
    image, both accept already-extracted strings - called, never reimplemented, the same
    "import helpers, call don't reimplement" pattern `_apply_agreement_checks` above already
    established) or, for the symbol sub-check, `_filter_by_symbol_phash`'s own reimplemented
    arithmetic (see that function's own docstring).

    Conservative by design, reproducing `local_fallback.py`'s own documented rule exactly (that
    module's own docstring: "A vote is written only when the intersection across every sub-check
    that DID produce a reading narrows to EXACTLY ONE candidate") - never loosened, never extended
    with the join-key calculator's own agreement/corroboration layer (frame/copyright-year/
    truncated-image checks do not exist in `local_fallback.py` and are deliberately NOT added
    here - this is a faithful port of that module's own decision model, not an augmented one).

    Pure function, no DB write (aside from the one read-only `CanonicalCard` query below, mirroring
    `_apply_agreement_checks`'s own single-query pattern) - callers persist via
    `CardPrintingTag`/`CardScanLog` exactly like the join-key calculator's own
    `run_join_key_calculator`. Same name-scoping caller contract as `calculate_join_key_verdict`:
    `candidates` MUST already be narrowed to this card's own name (`_resolve_candidates_for_card`).
    """
    candidate_pks = {c.pk for c in candidates}
    canonicals = {
        c.pk: c
        for c in CanonicalCard.objects.select_related("artist", "printing_metadata").filter(pk__in=candidate_pks)
    }
    artist_by_pk = {pk: c.artist.name for pk, c in canonicals.items()}
    border_color_by_pk = {
        pk: c.printing_metadata.border_color
        for pk, c in canonicals.items()
        if getattr(c, "printing_metadata", None) is not None and c.printing_metadata.border_color
    }

    border_filtered = filter_by_border_color(evidence.layout_class or None, candidates, border_color_by_pk)
    artist_filtered = (
        match_artist(evidence.artist_ocr_name, candidates, artist_by_pk) if evidence.artist_ocr_name else None
    )
    symbol_filtered = _filter_by_symbol_phash(evidence.symbol_phash, candidates)

    survivors = set(candidate_pks)
    evidence_types_used: list[str] = []
    for name, filtered in (("border", border_filtered), ("artist", artist_filtered), ("symbol", symbol_filtered)):
        if filtered is not None:
            survivors &= filtered
            evidence_types_used.append(name)

    if not evidence_types_used:
        return FallbackVerdict(card_id=card_id, skip_reason=FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON)
    if len(survivors) == 0:
        return FallbackVerdict(
            card_id=card_id, skip_reason="eliminated", evidence_types_used=tuple(evidence_types_used)
        )
    if len(survivors) > 1:
        return FallbackVerdict(card_id=card_id, skip_reason="ambiguous", evidence_types_used=tuple(evidence_types_used))

    confidence = (
        FALLBACK_CONFIDENCE_MULTI_EVIDENCE if len(evidence_types_used) > 1 else FALLBACK_CONFIDENCE_SINGLE_EVIDENCE
    )
    return FallbackVerdict(
        card_id=card_id,
        printing_pk=next(iter(survivors)),
        confidence=confidence,
        evidence_types_used=tuple(evidence_types_used),
    )


@dataclass
class FallbackCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, mirroring JoinKeyCalculatorResult.audit's own convention.
    audit: list[dict[str, object]] = field(default_factory=list)


def _fallback_eligible_cards_queryset() -> "QuerySet[Card]":
    """
    Cards the join-key calculator already concluded have no confident hit - the SAME population
    `_slow_path_eligible_cards_queryset` below selects from (a real `is_no_match` vote, or a
    non-rescannable skip in `JOIN_KEY_NO_HIT_SKIP_REASONS`) - that this calculator's own
    `STAGE_D_FALLBACK_ANONYMOUS_ID` hasn't already processed (scanned OR voted), via the shared
    `_eligible_cards_queryset` helper (idempotence mechanism only - see that function's own
    docstring for why a deduction-vote exclusion was considered and deliberately not added).
    """
    join_key_no_match_card_ids = CardPrintingTag.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
    ).values_list("card_id", flat=True)
    join_key_no_hit_scanned_card_ids = CardScanLog.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS
    ).values_list("card_id", flat=True)
    return _eligible_cards_queryset(
        STAGE_D_FALLBACK_ANONYMOUS_ID, rescannable_skip_reasons=FALLBACK_RESCANNABLE_SKIP_REASONS
    ).filter(Q(pk__in=join_key_no_match_card_ids) | Q(pk__in=join_key_no_hit_scanned_card_ids))


def run_fallback_calculator(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    default_cards_path: Optional[Path] = None,
) -> FallbackCalculatorResult:
    """
    Batch runner for PIECE 1 (module docstring) - mirrors `run_join_key_calculator`'s own shape
    (dry-run default, CardScanLog/CardPrintingTag batching, `resolve_and_persist_printing` called
    per touched card, `PilotRunLedger`/gate-check wiring living in the management command exactly
    like the join-key calculator's own). Only ever considers cards the join-key calculator ALREADY
    concluded have no confident hit (`_fallback_eligible_cards_queryset`) - this calculator is
    Stage D's own "pass 2", the same relationship `local_fallback.py`'s own module docstring
    documents between the pilot's pass 1 (OCR/phash) and pass 2 (fallback). `default_cards_path` is
    threaded through to `_resolve_candidates_for_card` exactly as `run_join_key_calculator`'s own
    parameter is.
    """
    run_id = run_id or generate_run_id()
    index = CandidateNameIndex()
    result = FallbackCalculatorResult(dry_run=dry_run, run_id=run_id)

    votes_batch: list[CardPrintingTag] = []
    scan_log_batch: list[CardScanLog] = []
    touched_card_ids: list[int] = []

    for card in _fallback_eligible_cards_queryset().iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = (
            ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )
        if evidence is None:
            result.skip_counts[FALLBACK_NO_EVIDENCE_SKIP_REASON] = (
                result.skip_counts.get(FALLBACK_NO_EVIDENCE_SKIP_REASON, 0) + 1
            )
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=FALLBACK_NO_EVIDENCE_SKIP_REASON,
                    )
                )
            continue

        result.cards_considered += 1
        candidates = _resolve_candidates_for_card(card.name, index, default_cards_path=default_cards_path)
        verdict = calculate_fallback_verdict(card.pk, evidence, candidates)

        if verdict.skip_reason:
            result.skip_counts[verdict.skip_reason] = result.skip_counts.get(verdict.skip_reason, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=verdict.skip_reason,
                    )
                )
            continue

        result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "card_id": card.pk,
                    "detail": verdict.detail,
                    "evidence_types_used": list(verdict.evidence_types_used),
                }
            )

        if not dry_run:
            votes_batch.append(
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=verdict.printing_pk,
                    is_no_match=False,
                    anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
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

        result.votes_written = len(votes_batch)

    return result


# Slow-path routing (module docstring's "two further cheap additions", item 1; owner decision,
# public issue #220): own anonymous_id, same rationale as JOIN_KEY_ANONYMOUS_ID's own comment - a
# distinct, independently purgeable/re-runnable population from every other engine's. This
# calculator never casts a CardPrintingTag (it has no printing to vote for), so its only DB
# footprint is a CardScanLog row.
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
# non-rescannable CardScanLog skip_reason values it can produce (both the original join-key check -
# "ambiguous"/"no-text" - and the agreement/corroboration layer's own withhold outcomes -
# "border-mismatch"/"frame-mismatch"/"truncated-image"/"copyright-year-mismatch"; artist-OCR
# disagreement is deliberately excluded, since it weakens confidence on a STILL-successful match
# rather than producing a skip). Deliberately excludes JOIN_KEY_RESCANNABLE_SKIP_REASONS
# ("no-evidence") - a card the join-key calculator never actually got to look at yet has nothing
# to route on, and will naturally become eligible once a future join-key pass runs.
#
# "proxy-marker-veto" (2026-07-21 correction, module docstring's moderator-flag signal section):
# the join-key calculator no longer PRODUCES this value going forward - kept HERE, deliberately,
# so a pre-2026-07-21 stale row still carrying it (until `reparse_collector_evidence --selector
# proxy-marker-veto` retracts it) still routes its card to human review rather than silently
# becoming routing-invisible; removing it from this set would be strictly worse than leaving it -
# a dead value in a frozenset costs nothing, an orphaned unrouted card costs a real review-queue
# gap.
JOIN_KEY_NO_HIT_SKIP_REASONS = frozenset(
    {
        "ambiguous",
        "no-text",
        "proxy-marker-veto",
        "border-mismatch",
        "frame-mismatch",
        "truncated-image",
        "copyright-year-mismatch",
    }
)

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
    Pure result of routing one card to the human review queue (module docstring) - NOT a
    match, NOT a vote; `raw_signals` is an in-memory packaging of that card's own already-persisted
    `ImageEvidence` fields (see `SLOW_PATH_RAW_SIGNAL_FIELDS`), for whatever consumes this next (a
    review-queue view, a report) - it is not written anywhere new.
    """

    card_id: int
    reason: str  # the join-key outcome that routed this card here - see JOIN_KEY_NO_HIT_SKIP_REASONS
    raw_signals: dict[str, object] = field(default_factory=dict)


def calculate_slow_path_verdict(card_id: int, reason: str, evidence: ImageEvidence) -> SlowPathVerdict:
    """
    The slow-path routing calculator (module docstring; owner decision, public issue #220's
    option (b) - "send no-hit cards straight to the human review queue with their partial
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

    ALSO excludes any card the fallback calculator (`STAGE_D_FALLBACK_ANONYMOUS_ID`, module
    docstring's PIECE 1) already successfully voted on - a real printing match, not merely a scan
    it abstained on. This is the wiring that makes PIECE 1 actually take effect: the management
    command runs join-key -> fallback -> slow-path in that order, and without this exclusion
    slow-path would route a card to human review that the fallback calculator resolves moments
    earlier in the SAME invocation. A card the fallback calculator merely SCANNED but abstained on
    (`no-evidence-types-used`/`eliminated`/`ambiguous`) is deliberately NOT excluded here - it
    still has no confident automated hit from either calculator and belongs in the review queue
    exactly as before this PR.
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
    fallback_voted_card_ids = CardPrintingTag.objects.filter(
        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID, is_no_match=False
    ).values_list("card_id", flat=True)
    return (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .filter(Q(pk__in=join_key_no_match_card_ids) | Q(pk__in=join_key_no_hit_scanned_card_ids))
        .exclude(pk__in=already_routed_card_ids)
        .exclude(pk__in=fallback_voted_card_ids)
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
    "RESOLUTION_FLOOR_DPI",
    "EXCLUDED_RESOLVED_TAGS",
    "JOIN_KEY_ANONYMOUS_ID",
    "JOIN_KEY_CONFIDENCE_BOTH",
    "JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY",
    "JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK",
    "JOIN_KEY_NO_MATCH_CONFIDENCE",
    "JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT",
    "JOIN_KEY_RESCANNABLE_SKIP_REASONS",
    "JOIN_KEY_NO_HIT_SKIP_REASONS",
    "COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS",
    "STAGE_D_FALLBACK_ANONYMOUS_ID",
    "FALLBACK_NO_EVIDENCE_SKIP_REASON",
    "FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON",
    "FALLBACK_RESCANNABLE_SKIP_REASONS",
    "FallbackVerdict",
    "calculate_fallback_verdict",
    "FallbackCalculatorResult",
    "run_fallback_calculator",
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
