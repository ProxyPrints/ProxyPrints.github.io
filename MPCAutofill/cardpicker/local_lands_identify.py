"""
Part 4 (docs/features/catalog-completion-plan.md "Part 4 - LANDS"): artist-decomposed
identification for names whose candidate count blocks the normal phash engine outright.

WHY THIS EXISTS: `run_phash_for_card` (local_identify_printing_tags.py) refuses to run at all
once a name's candidate count exceeds PHASH_MAX_CANDIDATES (12) - "too-many-candidates", checked
before any hash is even fetched. Basic lands are the extreme case (hundreds of printings per
name across sets), but any sufficiently-reprinted name can cross the same cap. Collector-line OCR
has NO such cap (confirmed: run_ocr_for_card iterates local_ocr.validate_against_candidates
unconditionally, no len(candidates) check anywhere) - so a card still sitting UNRESOLVED and in
this pool has already had a real, uncapped OCR attempt fail (illegible/missing collector line),
not a capped one. This module's actual new contribution is narrowing the over-cap candidate set
by ARTIST before ever attempting phash, so phash becomes feasible again on the reduced set.

PIPELINE per card:
  1. Collector-line OCR, exactly as the normal pass runs it (run_ocr_for_card) - a fresh attempt,
     not a replay of pass-1's result, since this module fetches its own image. If this alone
     resolves the card, cast a normal OCR vote (same confidence constants pass-1 uses) and stop -
     nothing land-specific about a card that OCR can already handle on its own.
  2. Where OCR still fails: artist OCR, reusing local_fallback.detect_illus_anchor/extract_artist_
     name/match_artist verbatim (already exist, already used for pass-2 candidate NARROWING,
     confirmed never previously used to cast a vote of their own - this module is the first
     caller that votes on their output directly). match_artist fuzzes ONLY against this card's
     OWN candidates' artists (never the full CanonicalArtist table).
  3. Where match_artist returns a surviving candidate-pk set: phash within that set (reusing
     local_phash.get_or_compute_canonical_hash + find_best_match - identical mechanism to
     local_residual_classify.recover_frame_mismatch_printing_via_phash's phash step, just over a
     different candidate subset). Two distinct confidence tiers depending on how much work the
     artist match alone already did (owner-clarified 2026-07-18, since the plan doc's "artist+art
     agree" vs "art-within-artist" phrasing was genuinely ambiguous from the spec text alone):
       - SINGLETON (0.85): the artist match alone already narrowed to exactly ONE candidate, and
         phash on that singleton clears the standard find_best_match acceptance distance. Two
         channels (artist, art) independently arrive at the same answer - a bad-distance
         singleton does NOT get this confidence, it ambiguous-skips like any other phash miss.
       - TIEBREAK (0.8): the artist match narrowed to MULTIPLE candidates (the same artist
         illustrated more than one printing of this name), and phash breaks the tie among just
         those with the standard unique-winner margin. One deciding channel (art, scoped by
         artist) rather than two independent ones - weaker, per the plan doc's own framing.
     Any phash failure/ambiguity in either case (no-hashable-candidates, no-clear-winner) is a
     skip, counted in the census - never trusted as a coin-flip.

dry_run=True (the default - HOLD #B): computes and counts everything above, including real image
fetches up to fetch_budget (bounded - shares the same CDN Worker rate limiter as everything else
fetching images; see image-cdn/wrangler.toml's IMAGE_FULL_TIER_RATE_LIMITER and this repo's own
docs/lessons.md for why an unbounded pilot fetch loop is a real, previously-hit problem), WITHOUT
writing any CardPrintingTag row. sample_size (default 300, per the plan doc's own "300-card
sample" HOLD #B ask) scopes both the fetch-costing pipeline steps and the reported artist-
extraction rate / post-filter candidate-count distribution to a deterministic pk-ordered prefix
of the pool, not the whole thing - pass sample_size=None for a full-pool pass once HOLD #B is
cleared and a real run is authorized. land_pool_size and the pre-filter per-name candidate counts
are always computed over the FULL pool regardless of sample_size (both are free DB-only queries,
no reason to sample them).

EVIDENCE-FIRST DATA SOURCE (issue #359, Phase 1 of the post-2026-07-23 sequencing): before this
patch, EVERY selected card paid a real fetch + fresh OCR (step 1) even though Stage C's
harvest-calculate pipeline (`image_evidence.py`) has, as of 2026-07-23, already extracted and
persisted the exact same underlying signals (`ImageEvidence.collector_line_*`/`artist_ocr_*`) for
the overwhelming majority of this pool (1,603/1,609 = 99.6% of the unresolved basic-land cohort
specifically, per the issue's live sizing) - re-paying that cost is pure waste. This is a DATA-
SOURCE swap only, never a logic change: steps 2-3 (`identify_land_printing`) are completely
untouched, and step 1's outcome is reproduced via the SAME `local_ocr.validate_against_candidates`
call `run_ocr_for_card` itself makes, just fed a `local_ocr.OcrParseResult` reconstructed from
already-persisted fields instead of a freshly-OCR'd one - the identical technique
`local_calculate_verdicts.calculate_join_key_verdict` already established for Stage D's own
join-key calculator (see that function's own docstring: "reconstructs an OcrParseResult from
Stage C's already-persisted fields... calls the EXISTING, unmodified validate_against_candidates").

CURRENCY (same convention every other Stage C consumer in this codebase uses - see
`local_calculate_verdicts.run_join_key_calculator`/`run_fallback_calculator`/
`run_slow_path_calculator`, all three): an `ImageEvidence` row is CURRENT for a card only when its
`content_hash` matches that card's own LIVE `content_phash` (an evidence row computed against a
prior image upload is never trusted for a card whose upload has since changed) AND its
`extractor_versions` carries both `collector_line_ocr` and `artist_ocr` keys (the two extractor
groups this module actually consumes - both are always written together by
`image_evidence.extract_card_evidence`'s single OCR-group block, so in practice checking either
key alone would suffice, but both are checked so this stays correct even under a future partial-
extractor-manifest write). See `_current_evidence_for_card`.

Per-card branching (`run_lands_identify`'s own loop): a card WITH current evidence never touches
`fetch_card_image`/`fetch_budget` at all - `_ocr_result_from_evidence` replaces `run_ocr_for_card`
and `evidence.artist_ocr_name` (already `local_fallback.extract_artist_name`'s own tolerant parse,
computed once by Stage C) replaces `detect_illus_anchor`, so zero network cost and zero tesseract
calls are spent per evidence-backed card. A card WITHOUT current evidence falls back to the
pre-existing live fetch + `run_ocr_for_card` + `detect_illus_anchor` path, unchanged, still gated
by `fetch_budget`. `LandsIdentifyResult.evidence_backed` counts the former population separately
from `fetch_attempted` (the latter counts only real network fetches, exactly as before this patch)
so a report can show how much of a run's cost this patch actually avoided.
"""

from dataclasses import dataclass, field
from typing import Optional

from cardpicker import local_ocr, local_phash
from cardpicker.image_cdn_fetch import fetch_card_image
from cardpicker.local_fallback import detect_illus_anchor, match_artist
from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
    OCR_CONFIDENCE_BOTH,
    OCR_CONFIDENCE_COLLECTOR_ONLY,
    PHASH_MAX_CANDIDATES,
    CandidateNameIndex,
    CandidatePrinting,
    EngineVote,
    OcrCardResult,
    SelectedCard,
    _eligible_base_queryset,
    generate_run_id,
    run_ocr_for_card,
)
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    ImageEvidence,
    LandsAmbiguousResidue,
    VoteSource,
)

# "=s800" tier addendum (task #130's tier-routing idea, applied here first): OCR only needs to
# read small collector-line/artist-credit text, not print resolution - fetching at the normal
# DEFAULT_FETCH_DPI=250 (~925px tall, image-cdn/src/url.ts's height = dpi * 1110 / 300) spends
# real bandwidth against the shared CDN rate limiter for detail OCR never uses. 800px is the
# target; solving the same formula for dpi (dpi = height * 300 / 1110) gives ~216, rounded up to
# the nearest 10 (the Worker's own hard requirement - see get_worker_image_url's docstring) to
# 220 so the actual fetched height (814px) clears 800 rather than falling just short. Also stays
# comfortably above RESOLUTION_FLOOR_DPI (200, local_identify_printing_tags.py) - the empirically
# -validated floor below which OCR yield measurably degrades - so this is a real bandwidth saving,
# not a yield regression. phash needs no fetch tier at all here: this module's phash step matches
# against already-ingested content_phash/image_hash, never re-fetching an image for it.
OCR_FETCH_DPI = 220

# Separate from every other engine's anonymous_id (OCR_ANONYMOUS_ID, PHASH_ANONYMOUS_ID,
# RESIDUAL_CLASSIFY_ANONYMOUS_ID, ART_HASH_ARTIST_ANONYMOUS_ID) - this is a genuinely distinct
# evidence source (artist-narrowed phash, never attempted by any other engine) and must be
# independently purgeable/re-runnable/resumable, same reasoning as every prior engine split.
LANDS_ANONYMOUS_ID = "lands-artist-decomp-v1"

# The plan doc's literal target-pool definition, part 1: "unresolved basic lands (Plains/Island/
# Swamp/Mountain/Forest/Wastes + Snow-Covered)". No existing constant for this anywhere in the
# codebase (checked). Card.name is the real printed/catalog name (not a normalized/searchable
# form), matching Scryfall's own naming convention for snow-covered basics - 5 basics + Wastes +
# 5 snow-covered variants = 11 literal names. If any of these strings don't match real Card.name
# values, that will show up directly as land_pool_size=0 for that name in the volume-check
# report (see run_lands_identify) rather than silently - not assumed correct without checking
# against real data.
BASIC_LAND_NAMES = frozenset(
    {
        "Plains",
        "Island",
        "Swamp",
        "Mountain",
        "Forest",
        "Wastes",
        "Snow-Covered Plains",
        "Snow-Covered Island",
        "Snow-Covered Swamp",
        "Snow-Covered Mountain",
        "Snow-Covered Forest",
    }
)

# Confidence values per docs/features/catalog-completion-plan.md's Part 4 spec, owner-clarified
# 2026-07-18 (see module docstring's PIPELINE step 3 for the full reasoning). NOTE: confidence is
# stored for audit/display only - resolve_weighted_consensus's actual vote WEIGHT comes from
# `source` alone (VoteSource.OCR -> settings.PRINTING_TAG_MACHINE_WEIGHT), not from this field,
# matching every other machine-cast vote in this codebase.
LANDS_SINGLETON_CONFIDENCE = 0.85
LANDS_TIEBREAK_CONFIDENCE = 0.8


def is_lands_target(card_name: str, candidate_count: int) -> bool:
    """The plan doc's target-pool membership test: a basic land by name, OR any name whose
    candidate count exceeds PHASH_MAX_CANDIDATES (the normal phash engine's own cap - see module
    docstring). A card can satisfy this for either reason independently."""
    return card_name in BASIC_LAND_NAMES or candidate_count > PHASH_MAX_CANDIDATES


@dataclass(frozen=True)
class LandIdentifyOutcome:
    card_id: int
    card_name: str
    candidate_count: int
    fetched: bool = False
    # True when this card's outcome was produced entirely from a stored, current ImageEvidence
    # row (issue #359's evidence-first data source) rather than a real fetch - mutually exclusive
    # with `fetched` (never both True: an evidence-backed card never touches fetch_card_image).
    evidence_backed: bool = False
    ocr_resolved_pk: Optional[int] = None
    artist_extracted: bool = False
    artist_matched_pks: Optional[frozenset[int]] = None
    printing_pk: Optional[int] = None
    confidence: Optional[float] = None
    skip_reason: str = ""

    def __str__(self) -> str:
        if self.ocr_resolved_pk is not None:
            return f"card={self.card_id} name={self.card_name!r} ocr_resolved printing={self.ocr_resolved_pk}"
        if self.printing_pk is not None:
            return (
                f"card={self.card_id} name={self.card_name!r} printing={self.printing_pk} "
                f"confidence={self.confidence}"
            )
        return f"card={self.card_id} name={self.card_name!r} skip={self.skip_reason or 'not-sampled'}"


@dataclass
class LandsIdentifyResult:
    dry_run: bool = True
    run_id: str = ""
    land_pool_size: int = 0
    sample_size: int = 0
    sampled: int = 0
    fetch_budget: int = 0
    fetch_attempted: int = 0
    # Cards resolved via a stored, current ImageEvidence row (issue #359) - paid zero fetch/OCR
    # cost, distinct from fetch_attempted (real network fetches only, unchanged meaning). Not
    # bounded by fetch_budget - a DB-only read, same "free" category as land_pool_size/
    # per_name_candidate_counts.
    evidence_backed: int = 0
    ocr_resolved: int = 0
    artist_extracted: int = 0
    artist_extraction_failed: int = 0
    singleton_votes: int = 0
    tiebreak_votes: int = 0
    ambiguous_phash: int = 0
    votes_written: int = 0
    # LandsAmbiguousResidue rows written (routing data, not votes) - counted separately from
    # votes_written since it's a distinct table with distinct semantics; see that model's
    # docstring. Always 0 in dry_run, same convention as votes_written.
    residue_written: int = 0
    # name -> pre-artist-filter candidate count, over the FULL pool (free, not sample-scoped).
    per_name_candidate_counts: dict[str, int] = field(default_factory=dict)
    # name -> list of post-artist-filter candidate-set sizes seen in the sample (one entry per
    # sampled card of that name where artist extraction succeeded) - a distribution, not a
    # single number, since the same name can appear many times in the sample with different
    # per-card OCR/image outcomes.
    per_name_post_filter_candidate_counts: dict[str, list[int]] = field(default_factory=dict)
    outcomes: list[LandIdentifyOutcome] = field(default_factory=list)


def _land_pool_selected_cards(index: CandidateNameIndex, sample_size: Optional[int]) -> list[SelectedCard]:
    """Mirrors select_candidates' own base-queryset + candidate-lookup shape, but against
    LANDS_ANONYMOUS_ID's own idempotence/exclusion state (never OCR_ANONYMOUS_ID/PHASH_
    ANONYMOUS_ID's) and filtered to is_lands_target rather than select_candidates' engine-
    specific dpi-floor-only filter. Deterministic pk order so sample_size is reproducible."""
    selected: list[SelectedCard] = []
    queryset = (
        _eligible_base_queryset(LANDS_ANONYMOUS_ID)
        .only("pk", "name", "identifier", "source_id", "content_phash")
        .order_by("pk")
    )
    for card in queryset.iterator(chunk_size=5000):
        candidates = index.candidates_for(card.name)
        if not candidates:
            continue
        if not is_lands_target(card.name, len(candidates)):
            continue
        selected.append(SelectedCard(card=card, candidates=candidates))
        if sample_size is not None and len(selected) >= sample_size:
            # Pool size itself is still reported over the full queryset below (this early-out
            # only bounds how many cards get the expensive fetch/OCR/artist/phash pipeline) -
            # callers that want land_pool_size independent of sample_size call this twice isn't
            # needed; run_lands_identify computes pool size via a separate cheap pass instead of
            # relying on this method's own early-out, see its own docstring.
            break
    return selected


def identify_land_printing(
    selected: SelectedCard,
    artist_name: Optional[str],
) -> tuple[Optional[int], Optional[float], str, Optional[frozenset[int]], Optional[dict[int, int]]]:
    """Pure (no fetch, no DB write): steps 2-3 of the module docstring's pipeline, given an
    already-extracted artist_name (or None if extraction failed). Returns (printing_pk,
    confidence, skip_reason, artist_matched_pks, phash_distances) - exactly one of (printing_pk,
    skip_reason) is populated; artist_matched_pks is always populated once match_artist itself
    returns a reading (even on a later phash failure), so callers get the artist-filter
    distribution without a second match_artist call. phash_distances ({candidate_pk: hamming
    distance from the card's own content_phash}) is populated whenever a phash comparison was
    actually attempted (i.e. content_phash existed) - None on every earlier skip path, since
    there's nothing to report a distance against yet. Ambiguous-residue capture (docs/features/
    catalog-completion-plan.md's Part 4 addendum, 2026-07-19) reuses this instead of
    recomputing distances a second time - find_best_match itself only returns the WINNING
    distance on success and nothing on failure, so this computes the full per-candidate spread
    directly rather than extending that shared helper's own return shape for every other caller.
    Split out from run_lands_identify's orchestrator so it's directly unit-testable without a
    real fetch or DB access."""
    if artist_name is None:
        return None, None, "no-artist-extracted", None, None

    candidate_pks = {c.pk for c in selected.candidates}
    canonicals = {c.pk: c for c in CanonicalCard.objects.select_related("artist").filter(pk__in=candidate_pks)}
    artist_by_pk = {pk: c.artist.name for pk, c in canonicals.items()}

    matched_pks = match_artist(artist_name, selected.candidates, artist_by_pk)
    if matched_pks is None:
        return None, None, "artist-no-match", None, None
    frozen_matched_pks = frozenset(matched_pks)

    filtered_candidates = [c for c in selected.candidates if c.pk in frozen_matched_pks]
    candidates_with_hashes: list[tuple[CandidatePrinting, int]] = []
    for candidate in filtered_candidates:
        canonical = canonicals.get(candidate.pk)
        if canonical is None:
            continue
        candidate_hash = local_phash.get_or_compute_canonical_hash(canonical)
        if candidate_hash is not None:
            candidates_with_hashes.append((candidate, candidate_hash))

    if selected.card.content_phash is None:
        return None, None, "no-content-phash", frozen_matched_pks, None

    phash_distances = {
        candidate.pk: local_phash._int_to_hash(selected.card.content_phash) - local_phash._int_to_hash(candidate_hash)
        for candidate, candidate_hash in candidates_with_hashes
    }

    match, reason = local_phash.find_best_match(selected.card.content_phash, candidates_with_hashes)
    if match is None:
        return None, None, f"phash-{reason}", frozen_matched_pks, phash_distances

    confidence = LANDS_SINGLETON_CONFIDENCE if len(frozen_matched_pks) == 1 else LANDS_TIEBREAK_CONFIDENCE
    return match.candidate.pk, confidence, "", frozen_matched_pks, phash_distances


def _current_evidence_for_card(card: Card) -> Optional[ImageEvidence]:
    """The module docstring's CURRENCY check - identical shape to `local_calculate_verdicts`'s
    three own eligible-cards loops (`run_join_key_calculator`/`run_fallback_calculator`/
    `run_slow_path_calculator`, all filter `ImageEvidence.objects.filter(card_id=..., content_hash
    =card.content_phash)`): a row is only trusted for this card if its `content_hash` matches the
    card's own LIVE `content_phash` (an evidence row from a prior image upload is never reused for
    a card whose upload has since changed) and it actually carries both extractor groups this
    module consumes. `card.content_phash is None` (no stable hash yet) always misses - same "no
    stable hash yet to key a CURRENT ImageEvidence lookup against" case those three callers each
    skip early for their own reasons. `.order_by("-updated_at").first()` picks the most recently
    written row on the rare chance more than one somehow exists for the same (card, content_hash)
    pair (the model's own unique constraint means this is normally exactly one or zero)."""
    if card.content_phash is None:
        return None
    return (
        ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
        .filter(extractor_versions__has_key="collector_line_ocr")
        .filter(extractor_versions__has_key="artist_ocr")
        .order_by("-updated_at")
        .first()
    )


def _ocr_result_from_evidence(evidence: ImageEvidence, selected: SelectedCard) -> OcrCardResult:
    """Step 1's evidence-first replacement for `run_ocr_for_card` (module docstring's "EVIDENCE-
    FIRST DATA SOURCE" section) - reconstructs a `local_ocr.OcrParseResult` from Stage C's
    already-persisted, already-parsed `collector_line_set_code`/`collector_line_collector_number`
    fields (no re-fetch, no re-OCR) and calls the EXISTING, unmodified
    `local_ocr.validate_against_candidates` - the same technique
    `local_calculate_verdicts.calculate_join_key_verdict` already established for Stage D's own
    join-key calculator. `raw_texts` is populated with the stored collector-line text alone (a
    single already-selected reading, not every preprocessing variant a live pass would try) so a
    caller falling through to the artist step still gets a real `raw_texts` list shape to work
    with, though this module's own evidence-backed artist step never actually reads it (it reads
    `evidence.artist_ocr_name` directly instead - see `run_lands_identify`)."""
    parsed = local_ocr.OcrParseResult(
        raw_text=evidence.collector_line_raw_text,
        set_code=evidence.collector_line_set_code or None,
        collector_number=evidence.collector_line_collector_number or None,
    )
    matched, reason = local_ocr.validate_against_candidates(parsed, selected.candidates)
    if matched is not None:
        confidence = OCR_CONFIDENCE_BOTH if parsed.set_code is not None else OCR_CONFIDENCE_COLLECTOR_ONLY
        return OcrCardResult(
            vote=EngineVote(
                engine="ocr", printing_pk=matched.pk, confidence=confidence, detail=parsed.raw_text.strip()
            ),
            raw_texts=[evidence.collector_line_raw_text],
            parsed_a_collector_number=parsed.collector_number is not None,
        )
    return OcrCardResult(
        skip_reason=reason,
        raw_texts=[evidence.collector_line_raw_text],
        parsed_a_collector_number=parsed.collector_number is not None,
    )


def _process_land_card(
    selected: SelectedCard,
    ocr_result: OcrCardResult,
    artist_name: Optional[str],
    *,
    evidence_backed: bool,
    fetched: bool,
    dry_run: bool,
    run_id: str,
    result: LandsIdentifyResult,
    votes_batch: list[CardPrintingTag],
    residue_batch: list[LandsAmbiguousResidue],
) -> None:
    """Steps 1 (already resolved via `ocr_result`) through 3 of the module docstring's pipeline,
    given an already-computed `ocr_result`/`artist_name` pair - shared by BOTH the evidence-backed
    and live-fetch-fallback branches of `run_lands_identify`'s own loop so the two data sources
    are guaranteed to produce IDENTICAL outcomes for identical (ocr_result, artist_name) inputs
    (issue #359's "behavior-neutral data-source swap" requirement) - this function has no idea
    which branch called it. `evidence_backed`/`fetched` are purely descriptive (recorded onto the
    outcome for reporting), never branched on internally."""
    card = selected.card
    if ocr_result.vote is not None:
        result.ocr_resolved += 1
        if not dry_run:
            votes_batch.append(
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=ocr_result.vote.printing_pk,
                    is_no_match=False,
                    anonymous_id=OCR_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=ocr_result.vote.confidence,
                    run_id=run_id,
                )
            )
        result.outcomes.append(
            LandIdentifyOutcome(
                card_id=card.pk,
                card_name=card.name,
                candidate_count=len(selected.candidates),
                fetched=fetched,
                evidence_backed=evidence_backed,
                ocr_resolved_pk=ocr_result.vote.printing_pk,
            )
        )
        return

    if artist_name is not None:
        result.artist_extracted += 1
    else:
        result.artist_extraction_failed += 1

    printing_pk, confidence, skip_reason, artist_matched_pks, phash_distances = identify_land_printing(
        selected, artist_name
    )

    if printing_pk is not None:
        if confidence == LANDS_SINGLETON_CONFIDENCE:
            result.singleton_votes += 1
        else:
            result.tiebreak_votes += 1
        if not dry_run:
            votes_batch.append(
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=printing_pk,
                    is_no_match=False,
                    anonymous_id=LANDS_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=confidence,
                    run_id=run_id,
                )
            )
    elif skip_reason.startswith("phash-"):
        result.ambiguous_phash += 1
        # Routing data, not a vote (see LandsAmbiguousResidue's own docstring) - the artist
        # match already paid the real narrowing cost; persist it so a future funnel surface
        # can serve "which of these N?" instead of recomputing from the name's full pool.
        if not dry_run and artist_name is not None and artist_matched_pks and phash_distances is not None:
            residue_batch.append(
                LandsAmbiguousResidue(
                    card_id=card.pk,
                    run_id=run_id,
                    artist_name=artist_name,
                    candidate_pks=sorted(artist_matched_pks),
                    phash_distances={str(pk): distance for pk, distance in phash_distances.items()},
                )
            )

    if artist_matched_pks is not None:
        result.per_name_post_filter_candidate_counts.setdefault(card.name, []).append(len(artist_matched_pks))

    result.outcomes.append(
        LandIdentifyOutcome(
            card_id=card.pk,
            card_name=card.name,
            candidate_count=len(selected.candidates),
            fetched=fetched,
            evidence_backed=evidence_backed,
            artist_extracted=artist_name is not None,
            artist_matched_pks=artist_matched_pks,
            printing_pk=printing_pk,
            confidence=confidence,
            skip_reason=skip_reason,
        )
    )


def run_lands_identify(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    sample_size: Optional[int] = 300,
    fetch_budget: int = 0,
    audit_sample_size: int = 20,
) -> LandsIdentifyResult:
    """Orchestrator. See module docstring for the full pipeline, dry_run/sample_size semantics,
    and the evidence-first data source (issue #359). fetch_budget bounds real image fetches
    (shared CDN rate limiter) independent of sample_size - pass fetch_budget=0 to get
    land_pool_size + per_name_candidate_counts (both free) with zero network cost, useful for a
    first, instant read of pool shape before spending any fetch budget on the artist-extraction-
    rate sample. fetch_budget only bounds the LIVE-FETCH FALLBACK branch - a card with current
    stored evidence never touches it, regardless of how small fetch_budget is."""
    run_id = run_id or generate_run_id()
    index = CandidateNameIndex()

    result = LandsIdentifyResult(
        dry_run=dry_run, run_id=run_id, sample_size=sample_size or 0, fetch_budget=fetch_budget
    )

    # land_pool_size + per_name_candidate_counts: full pool, no sampling, no fetches - always
    # computed regardless of sample_size/fetch_budget (see module docstring).
    full_selected = _land_pool_selected_cards(index, sample_size=None)
    result.land_pool_size = len(full_selected)
    for selected in full_selected:
        result.per_name_candidate_counts[selected.card.name] = len(selected.candidates)

    sampled_selected = full_selected[:sample_size] if sample_size is not None else full_selected
    result.sampled = len(sampled_selected)

    votes_batch: list[CardPrintingTag] = []
    residue_batch: list[LandsAmbiguousResidue] = []
    for selected in sampled_selected:
        card = selected.card

        # EVIDENCE-FIRST (module docstring, issue #359): a card with a CURRENT ImageEvidence row
        # never touches fetch_card_image/run_ocr_for_card/detect_illus_anchor at all - steps 1-2's
        # signals are read straight off the already-persisted row instead.
        evidence = _current_evidence_for_card(card)
        if evidence is not None:
            result.evidence_backed += 1
            ocr_result = _ocr_result_from_evidence(evidence, selected)
            artist_name = None if ocr_result.vote is not None else (evidence.artist_ocr_name or None)
            _process_land_card(
                selected,
                ocr_result,
                artist_name,
                evidence_backed=True,
                fetched=False,
                dry_run=dry_run,
                run_id=run_id,
                result=result,
                votes_batch=votes_batch,
                residue_batch=residue_batch,
            )
            continue

        # LIVE-FETCH FALLBACK (unchanged from before issue #359, except gated by fetch_budget
        # only for cards actually reaching this branch - an evidence-backed card above never
        # counts against it).
        if result.fetch_attempted >= fetch_budget:
            result.outcomes.append(
                LandIdentifyOutcome(
                    card_id=card.pk,
                    card_name=card.name,
                    candidate_count=len(selected.candidates),
                    skip_reason="fetch-budget-exhausted",
                )
            )
            continue

        result.fetch_attempted += 1
        image = fetch_card_image(card, dpi=OCR_FETCH_DPI)
        if image is None:
            result.outcomes.append(
                LandIdentifyOutcome(
                    card_id=card.pk,
                    card_name=card.name,
                    candidate_count=len(selected.candidates),
                    fetched=False,
                    skip_reason="unfetchable-image",
                )
            )
            continue

        ocr_result = run_ocr_for_card(selected, image)
        artist_name = None
        if ocr_result.vote is None:
            _illus_anchor_fired, artist_name = detect_illus_anchor(image, ocr_result.raw_texts)

        _process_land_card(
            selected,
            ocr_result,
            artist_name,
            evidence_backed=False,
            fetched=True,
            dry_run=dry_run,
            run_id=run_id,
            result=result,
            votes_batch=votes_batch,
            residue_batch=residue_batch,
        )

    if not dry_run and votes_batch:
        CardPrintingTag.objects.bulk_create(votes_batch)
        result.votes_written = len(votes_batch)

    if not dry_run and residue_batch:
        LandsAmbiguousResidue.objects.bulk_create(residue_batch)
        result.residue_written = len(residue_batch)

    result.outcomes = result.outcomes[:audit_sample_size]
    return result


__all__ = [
    "OCR_FETCH_DPI",
    "LANDS_ANONYMOUS_ID",
    "BASIC_LAND_NAMES",
    "LANDS_SINGLETON_CONFIDENCE",
    "LANDS_TIEBREAK_CONFIDENCE",
    "is_lands_target",
    "LandIdentifyOutcome",
    "LandsIdentifyResult",
    "identify_land_printing",
    "run_lands_identify",
]
