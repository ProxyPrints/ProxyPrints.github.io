"""
Shared evidence-recovery module (docs/features/catalog-completion-plan.md's Part 3). Built as
ONE code path deliberately reusable by Part 5 (residual classification - existing tags only,
altered-frame/custom-art) later: `recover_frame_mismatch_printing_via_phash`/`_via_ocr_refetch`
are the reusable single-card recovery primitives - a future Part 5 pass should call these
directly rather than re-deriving frame-mismatch recovery from scratch.

DESIGN QUESTION (item 2c) - answered by directly reading local_identify_printing_tags.py's
frame-mismatch block (~lines 1040-1065): the matched-but-withheld printing P IS computed
in-memory during the original pilot run (`candidate_vote.printing_pk`) and appended to
`attributes.frame_mismatches` - but that list is explicitly capped ("up to 10, for the report")
and is a report-only value, never persisted. The durable `CardScanLog` row for a frame-mismatch
skip only stores (card, anonymous_id, run_id, skip_reason="frame-mismatch") - WHICH ENGINE
flagged it, never which printing it matched. P must be recomputed, not read back.

Recovery is priced very differently by engine (live census, 2026-07-18: 5,178 OCR-flagged /
980 phash-flagged / 595 fallback-flagged distinct cards, some overlap possible across engines):

- PHASH-flagged rows (anonymous_id=local-phash-v1): FREE. `local_phash.
  compute_content_phash_for_card`'s own docstring confirms it calls the exact same
  `compute_card_art_hash` function the live phash engine (`run_phash_for_card`) uses - so
  `Card.content_phash` (backfilled catalog-wide, Part 2) IS the same hash the engine would
  recompute live. Recovering P is pure DB + arithmetic: compare the stored hash against each
  current candidate's cached `CanonicalCard.image_hash` via `local_phash.find_best_match` -
  zero image fetch.

- OCR-flagged rows (anonymous_id=local-ocr-v1): NOT free. OCR's matched collector-number/
  set-code text is never persisted anywhere, so recovery means one real CDN image fetch + a
  fresh `run_ocr_for_card` pass per card.

- FALLBACK-flagged rows (anonymous_id=local-fallback-v1, ~9% of the census): NOT free, same
  shape as OCR. CORRECTION (caught on a second read of local_fallback.py before this module
  first shipped): `local_fallback.run_fallback_for_card` IS a standalone, single-card-callable
  function (an initial claim that it was "inline in _compute_card's whole-pipeline flow, not
  reusable" was wrong - it lives at local_fallback.py's own top level, exported in `__all__`).
  Recovery means one real CDN image fetch + a fresh `run_fallback_for_card` pass (border+
  artist+symbol evidence-combination, same as the live engine) per card - reuses
  `ocr_raw_texts=[]` (no cached pass-1 OCR text to reuse in a recovery pass) and
  `bleed_class=None`, the same simplification the OCR-refetch path makes.

HOLD #P3 (docs/features/catalog-completion-plan.md): both `run_frame_mismatch_recovery` and
`run_d0_sibling_artist_propagation` accept `dry_run` and compute+count everything (including
real OCR-refetch network calls, which are data collection, not a vote write) without writing
any `CardArtistVote`/`CardTagVote` row when `dry_run=True`. The management command built on top
of this module defaults to dry-run and requires an explicit `--write` flag to actually cast
votes - a deliberate deviation from `purge_machine_votes`'s opt-out convention, justified by the
explicit "write pass runs only after my go" instruction this module was built under.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import Q, QuerySet

from cardpicker import local_phash
from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.image_cdn_fetch import fetch_card_image

# Issue #533's third blocking prerequisite. A PLAIN MODULE-LEVEL IMPORT, not the function-local
# one `local_illustration` uses for the same helper: that module needs a deferred import because
# `management/commands/local_calculate_verdicts.py` imports `local_illustration`, so a hard
# import back would close a cycle. Nothing on `local_calculate_verdicts`' own import closure
# (`image_evidence`, `local_fallback`, `local_identify_printing_tags`, `local_ocr`, `models`,
# `printing_consensus`, `printing_metadata_import`, `utils`, `vote_write`) reaches this module, so
# there is no cycle to defer around here - the same reason `management/commands/ocr_engine_ab.py`
# and `management/commands/rejudge_fallback_channel.py` already import this helper at module level.
# The helper is NOT extracted to a leaf module (the `vote_write.py` move PR #534 made for the
# purge/write primitive) precisely because no cycle forces it, and a second home for the cache
# would risk a second module-level cache instance - the exact "silently rebuilds every time"
# failure this change exists to remove.
from cardpicker.local_calculate_verdicts import _get_cached_candidate_name_index
from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID, run_fallback_for_card
from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
    PHASH_ANONYMOUS_ID,
    CandidateNameIndex,
    CandidatePrinting,
    SelectedCard,
    generate_run_id,
    run_ocr_for_card,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CanonicalCard,
    Card,
    CardArtistVote,
    CardScanLog,
    CardTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.vote_consensus import is_human_backed_source
from cardpicker.vote_write import purge_and_write_votes

# Part 3's own anonymous_id (17 chars, well under max_length=40) for the frame-mismatch dual
# yield - distinct from OCR_ANONYMOUS_ID/PHASH_ANONYMOUS_ID/FALLBACK_ANONYMOUS_ID since this
# pass casts votes on a DIFFERENT card population (frame-mismatch-flagged, not fresh candidates)
# and must never be excluded/resumed against as if it were one of those three engines.
RESIDUAL_CLASSIFY_ANONYMOUS_ID = "residual-classify-v1"

# Part 3's own anonymous_id for d=0 sibling artist propagation - separate from the above since
# this is a completely different evidence source (identical-image entailment, not a recovered
# frame-mismatch match) and must be independently purgeable/re-runnable.
ART_HASH_ARTIST_ANONYMOUS_ID = "art-hash-artist-v1"

ALTERED_FRAME_TAG_NAME = "altered-frame"

# Confidence values per docs/features/catalog-completion-plan.md's Part 3 spec. NOTE: confidence
# is stored for audit/display only - resolve_weighted_consensus's actual vote WEIGHT comes from
# `source` alone (VoteSource.OCR -> settings.PRINTING_TAG_MACHINE_WEIGHT, currently 0.5), not from
# this field, matching every other machine-cast vote in this codebase.
FRAME_MISMATCH_ARTIST_CONFIDENCE = 0.8
FRAME_MISMATCH_TAG_CONFIDENCE = 0.7
D0_SIBLING_ARTIST_CONFIDENCE = 0.9


def _frame_mismatch_scan_log_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[CardScanLog]":
    """`run_frame_mismatch_recovery`'s own eligibility source: every durable frame-mismatch
    `CardScanLog` row, whichever engine wrote it. Split out of that function as a named seam so
    the batch scoping below is assertable against the COMPILED SQL (issue #533's first blocking
    prerequisite requires exactly that - a result-set assertion cannot distinguish "scoped in
    SQL" from "materialised catalog-wide and filtered in Python afterwards", which is the whole
    defect class).

    BATCH SCOPING (`card_ids`): this queryset is the one catalog-scale read on the frame-mismatch
    path - `CardScanLog` is 2,093,147 rows live, append-only and growing, and its caller
    materialises the result into Python `set`s. Unscoped, that is a full-table pass plus a
    catalog-scale Python structure inside every 25-card micro-batch. Pushing `card_ids` in HERE
    (rather than intersecting the materialised sets afterwards) is what makes the read itself
    O(batch). Purely a cost narrowing: a row outside `card_ids` could only ever have produced a
    card the caller would then have dropped anyway. `card_ids=None` (BULK mode - the management
    command's only calling shape) leaves this byte-identical to before."""
    queryset = CardScanLog.objects.filter(skip_reason="frame-mismatch")
    if card_ids is not None:
        queryset = queryset.filter(card_id__in=card_ids)
    return queryset


def _art_hash_artist_voted_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[CardArtistVote]":
    """`run_d0_sibling_artist_propagation`'s own idempotence source: every `CardArtistVote` this
    calculator's identity has already cast. Split out as a named seam for the same
    compiled-SQL-assertability reason as `_frame_mismatch_scan_log_queryset` above.

    BATCH SCOPING (`card_ids`): the caller materialises this into a Python `set` for its
    `.exclude(pk__in=...)`, so unscoped it is both a catalog-wide read of `CardArtistVote`
    filtered by `anonymous_id` alone AND a catalog-scale in-memory set, per micro-batch. Purely
    a cost narrowing - an already-voted card outside `card_ids` could never appear in the scoped
    target queryset it excludes from. `card_ids=None` is byte-identical to before."""
    queryset = CardArtistVote.objects.filter(anonymous_id=ART_HASH_ARTIST_ANONYMOUS_ID)
    if card_ids is not None:
        queryset = queryset.filter(card_id__in=card_ids)
    return queryset


def recover_frame_mismatch_printing_via_phash(card: Card, index: CandidateNameIndex) -> Optional[int]:
    """Zero-fetch recovery (see module docstring) - re-derives the match against the card's
    CURRENT candidates (never assumes the original run's candidate set is still accurate; a
    data-quality fix since could have changed it). Returns the recovered CanonicalCard pk, or
    None if unrecoverable (e.g. content_phash still unset, or no clear winner today)."""
    if card.content_phash is None:
        return None
    candidates = index.candidates_for(card.name)
    if not candidates:
        return None
    canonicals_by_pk = {c.pk: c for c in CanonicalCard.objects.filter(pk__in=[c.pk for c in candidates])}
    candidates_with_hashes: list[tuple[CandidatePrinting, int]] = []
    for candidate in candidates:
        canonical = canonicals_by_pk.get(candidate.pk)
        if canonical is None:
            continue
        candidate_hash = local_phash.get_or_compute_canonical_hash(canonical)
        if candidate_hash is not None:
            candidates_with_hashes.append((candidate, candidate_hash))
    match, _reason = local_phash.find_best_match(card.content_phash, candidates_with_hashes)
    return match.candidate.pk if match is not None else None


def recover_frame_mismatch_printing_via_ocr_refetch(
    card: Card, index: CandidateNameIndex
) -> tuple[Optional[int], bool]:
    """NOT free (see module docstring) - one real CDN fetch + a fresh OCR pass per call. Returns
    (recovered_printing_pk, fetch_attempted) so callers can track real network spend distinctly
    from a `None` caused by having no candidates at all (never reaches the network). Uses
    bleed_class=None (a no-op crop remap per run_ocr_for_card's own docstring) rather than
    re-deriving the original run's bleed classification - a deliberate simplification for a
    recovery pass, not a full pipeline replay."""
    candidates = index.candidates_for(card.name)
    if not candidates:
        return None, False
    selected = SelectedCard(card=card, candidates=candidates)
    image = fetch_card_image(card)
    result = run_ocr_for_card(selected, image)
    return (result.vote.printing_pk if result.vote is not None else None), True


def recover_frame_mismatch_printing_via_fallback_refetch(
    card: Card, index: CandidateNameIndex
) -> tuple[Optional[int], bool]:
    """NOT free (see module docstring) - one real CDN fetch + a fresh run_fallback_for_card pass
    per call (border+artist+symbol evidence-combination, same as the live engine). Returns
    (recovered_printing_pk, fetch_attempted). Uses ocr_raw_texts=[] (no cached pass-1 OCR text
    to reuse in a recovery pass) and bleed_class=None - the same simplification the OCR-refetch
    path makes, not a full pipeline replay."""
    candidates = index.candidates_for(card.name)
    if not candidates:
        return None, False
    selected = SelectedCard(card=card, candidates=candidates)
    image = fetch_card_image(card)
    if image is None:
        return None, True
    outcome = run_fallback_for_card(selected, image, ocr_raw_texts=[])
    return outcome.printing_pk, True


@dataclass
class FrameMismatchRecoveryOutcome:
    card_id: int
    recovered_printing_pk: Optional[int] = None
    recovery_method: str = ""  # "phash" | "ocr-refetch" | "*-unrecovered"
    artist_pk: Optional[int] = None
    artist_vote_would_cast: bool = False
    tag_vote_would_cast: bool = False


@dataclass
class FrameMismatchRecoveryResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    phash_recovered: int = 0
    ocr_refetch_attempted: int = 0
    ocr_refetch_recovered: int = 0
    fallback_refetch_attempted: int = 0
    fallback_refetch_recovered: int = 0
    unrecovered: int = 0
    artist_votes_written: int = 0
    tag_votes_written: int = 0
    # capped audit sample, not the full outcome set - mirrors PilotResult's own "up to 10/N, for
    # the report" convention elsewhere in this codebase.
    outcomes: list[FrameMismatchRecoveryOutcome] = field(default_factory=list)


def run_frame_mismatch_recovery(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    ocr_refetch_budget: int = 0,
    fallback_refetch_budget: int = 0,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> FrameMismatchRecoveryResult:
    """Part 3's dual-yield recovery pass. For every distinct card with a durable frame-mismatch
    CardScanLog row (RESCANNABLE_SKIP_REASONS deliberately keeps these eligible - see that
    constant's own docstring in local_identify_printing_tags.py: "Part 3's own dual-yield design
    needs to revisit these cards"), recover the matched-but-withheld printing P (phash: free;
    OCR/fallback: cost one refetch each, bounded by their own budgets - see module docstring)
    and, where recovered, would cast:
      (a) CardArtistVote for P's artist, confidence 0.8
      (b) CardTagVote(altered-frame, APPLY), confidence 0.7
    both under anonymous_id=RESIDUAL_CLASSIFY_ANONYMOUS_ID + run_id, source=VoteSource.OCR
    (the umbrella machine-vision source - see VoteSource's own docstring), vote_surface=None
    (machine-cast, never a real UI surface - matches every other engine vote in this codebase).

    dry_run=True (the default - HOLD #P3): computes and counts everything above WITHOUT writing
    any CardArtistVote/CardTagVote row. OCR/fallback-refetch network calls still happen up to
    their own budgets even in dry-run mode (real data collection to size expected yield, not a
    vote write) - pass budget=0 to skip a path entirely and get free-path-only numbers.

    A card flagged by more than one engine only needs recovering once - phash (free) takes
    priority over OCR/fallback (both cost a fetch) when more than one flagged the same card.

    BATCH SCOPING (`card_ids`, issue #533's first blocking prerequisite): when given, restricts
    this whole pass to that set of card pks, pushed INTO `_frame_mismatch_scan_log_queryset` (see
    that function's own docstring) - i.e. into the `CardScanLog` read itself, before anything is
    materialised into Python - rather than intersected against the catalog-wide sets afterwards.
    `card_ids=None` (the management command's only calling shape) is byte-identical to before.

    FETCH BUDGETS ARE A SEPARATE DECISION FROM SCOPING (issue #533, and the reason this note
    exists): `ocr_refetch_budget`/`fallback_refetch_budget` still admit real CDN image fetches +
    fresh OCR/fallback passes, delegated into `local_identify_printing_tags`' helpers via
    `recover_frame_mismatch_printing_via_ocr_refetch`/`_via_fallback_refetch`. Making this
    function scopeable does NOT make per-batch fetching safe - both budgets are per-INVOCATION,
    so a per-batch caller invoking this once per micro-batch multiplies the effective fetch
    ceiling by the number of batches against a shared, rate-limited CDN. A per-batch caller must
    therefore consider the budgets EXPLICITLY: pass 0 (the default, and the only value that
    guarantees zero network cost - the phash path is genuinely free) unless #533's own separate
    fetch decision has authorised otherwise. No default budget is changed by this scoping work.

    CATALOG-SCALE INDEX, LAZY AND PROCESS-CACHED (issue #533's THIRD blocking prerequisite,
    2026-07-29 - this docstring previously recorded it as the outstanding follow-up): the
    `CandidateNameIndex` this pass needs is an in-memory index over CanonicalCard's 113k+ rows
    (measured 1.48s). It is keyed by card NAME over a different table entirely, so `card_ids`
    cannot narrow it, and a per-batch caller invoking this once per 25-card micro-batch over a
    ~135,000-row queue would rebuild it ~5,400 times. It is therefore resolved through
    `local_calculate_verdicts._get_cached_candidate_name_index()` - the SAME per-worker-process,
    version-stamped cache `run_join_key_calculator`/`run_fallback_calculator`/
    `run_illustration_calculator` use, not a second implementation - and resolved LAZILY, on the
    first card this pass actually has to recover, so an invocation whose `card_ids` scope turns up
    no frame-mismatch scan logs pays neither the build nor the version-stamp check.
    """
    run_id = run_id or generate_run_id()
    altered_frame_tag = Tag.objects.filter(name=ALTERED_FRAME_TAG_NAME).first()
    # Resolved on first real need in the three recovery loops below - see this function's own
    # docstring. `Optional` rather than an eager call so an empty scope costs nothing at all.
    index: Optional[CandidateNameIndex] = None

    card_ids_by_engine: dict[str, set[int]] = {
        OCR_ANONYMOUS_ID: set(),
        PHASH_ANONYMOUS_ID: set(),
        FALLBACK_ANONYMOUS_ID: set(),
    }
    for anonymous_id, card_id in (
        _frame_mismatch_scan_log_queryset(card_ids).values_list("anonymous_id", "card_id").distinct()
    ):
        if anonymous_id in card_ids_by_engine:
            card_ids_by_engine[anonymous_id].add(card_id)

    phash_card_ids = card_ids_by_engine[PHASH_ANONYMOUS_ID]
    ocr_only_card_ids = card_ids_by_engine[OCR_ANONYMOUS_ID] - phash_card_ids
    fallback_only_card_ids = (
        card_ids_by_engine[FALLBACK_ANONYMOUS_ID] - phash_card_ids - card_ids_by_engine[OCR_ANONYMOUS_ID]
    )

    result = FrameMismatchRecoveryResult(dry_run=dry_run, run_id=run_id)
    artist_votes_batch: list[CardArtistVote] = []
    tag_votes_batch: list[CardTagVote] = []
    touched_card_ids: set[int] = set()

    def cast(card: Card, printing_pk: int, method: str) -> FrameMismatchRecoveryOutcome:
        canonical = CanonicalCard.objects.filter(pk=printing_pk).only("pk", "artist_id").first()
        outcome = FrameMismatchRecoveryOutcome(
            card_id=card.pk, recovered_printing_pk=printing_pk, recovery_method=method
        )
        if canonical is None:
            return outcome
        outcome.artist_pk = canonical.artist_id
        outcome.artist_vote_would_cast = True
        touched_card_ids.add(card.pk)
        if not dry_run:
            artist_votes_batch.append(
                CardArtistVote(
                    card=card,
                    artist_id=canonical.artist_id,
                    is_unknown=False,
                    anonymous_id=RESIDUAL_CLASSIFY_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=FRAME_MISMATCH_ARTIST_CONFIDENCE,
                    run_id=run_id,
                    vote_surface=None,
                )
            )
        if altered_frame_tag is not None:
            outcome.tag_vote_would_cast = True
            if not dry_run:
                tag_votes_batch.append(
                    CardTagVote(
                        card=card,
                        tag=altered_frame_tag,
                        polarity=VotePolarity.APPLY,
                        anonymous_id=RESIDUAL_CLASSIFY_ANONYMOUS_ID,
                        source=VoteSource.OCR,
                        confidence=FRAME_MISMATCH_TAG_CONFIDENCE,
                        run_id=run_id,
                        vote_surface=None,
                    )
                )
        return outcome

    for card in Card.objects.filter(pk__in=phash_card_ids):
        result.cards_considered += 1
        index = index or _get_cached_candidate_name_index()
        printing_pk = recover_frame_mismatch_printing_via_phash(card, index)
        if printing_pk is not None:
            result.phash_recovered += 1
            outcome = cast(card, printing_pk, "phash")
        else:
            result.unrecovered += 1
            outcome = FrameMismatchRecoveryOutcome(card_id=card.pk, recovery_method="phash-unrecovered")
        if len(result.outcomes) < audit_sample_size:
            result.outcomes.append(outcome)

    ocr_budget_remaining = ocr_refetch_budget
    for card in Card.objects.filter(pk__in=ocr_only_card_ids):
        result.cards_considered += 1
        if ocr_budget_remaining <= 0:
            result.unrecovered += 1
            continue
        ocr_budget_remaining -= 1
        result.ocr_refetch_attempted += 1
        index = index or _get_cached_candidate_name_index()
        printing_pk, _fetched = recover_frame_mismatch_printing_via_ocr_refetch(card, index)
        if printing_pk is not None:
            result.ocr_refetch_recovered += 1
            outcome = cast(card, printing_pk, "ocr-refetch")
        else:
            result.unrecovered += 1
            outcome = FrameMismatchRecoveryOutcome(card_id=card.pk, recovery_method="ocr-refetch-unrecovered")
        if len(result.outcomes) < audit_sample_size:
            result.outcomes.append(outcome)

    fallback_budget_remaining = fallback_refetch_budget
    for card in Card.objects.filter(pk__in=fallback_only_card_ids):
        result.cards_considered += 1
        if fallback_budget_remaining <= 0:
            result.unrecovered += 1
            continue
        fallback_budget_remaining -= 1
        result.fallback_refetch_attempted += 1
        index = index or _get_cached_candidate_name_index()
        printing_pk, _fetched = recover_frame_mismatch_printing_via_fallback_refetch(card, index)
        if printing_pk is not None:
            result.fallback_refetch_recovered += 1
            outcome = cast(card, printing_pk, "fallback-refetch")
        else:
            result.unrecovered += 1
            outcome = FrameMismatchRecoveryOutcome(card_id=card.pk, recovery_method="fallback-refetch-unrecovered")
        if len(result.outcomes) < audit_sample_size:
            result.outcomes.append(outcome)

    if not dry_run:
        # CANCEL-SAFETY (2026-07-28): each purge is a DELETE and its insert a separate statement,
        # so a run killed between them left the affected cards with their previous vote deleted
        # and nothing written back. `vote_write.purge_and_write_votes` runs each pair inside one
        # `transaction.atomic()`, scoped to exactly the rows it inserts - see that module's
        # docstring. The two models are two independent atomic pairs, not one: they are separate
        # tables with separate purges, and a kill landing between them leaves the artist votes
        # committed and the tag votes not written at all - which is the same partial-progress
        # outcome a kill one statement earlier already produced, and is safe because neither
        # write depends on the other (`resolve_and_persist_artist`/`resolve_and_persist_tag_votes`
        # below each read only their own model).
        # `ignore_conflicts` stays OFF at both sites, exactly as before: unlike the AI-art/
        # layout-class engines this module has no belt-and-suspenders conflict expectation, and
        # turning it on would silently swallow a real constraint violation.
        purge_and_write_votes(
            CardArtistVote,
            artist_votes_batch,
            anonymous_id=RESIDUAL_CLASSIFY_ANONYMOUS_ID,
            target_field="card_id",
        )
        purge_and_write_votes(
            CardTagVote,
            tag_votes_batch,
            anonymous_id=RESIDUAL_CLASSIFY_ANONYMOUS_ID,
            target_field="card_id",
        )
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_artist(card)
            resolve_and_persist_tag_votes(card)

    result.artist_votes_written = len(artist_votes_batch)
    result.tag_votes_written = len(tag_votes_batch)
    return result


def _resolved_artist_id(card: Card) -> Optional[int]:
    """Same precedence chain as Card.serialise() (models.py) - replicated as a lightweight
    id-only lookup rather than constructing a full SerialisedCard for every candidate row."""
    if card.canonical_artist_id is not None:
        return card.canonical_artist_id
    if card.canonical_card is not None:
        return card.canonical_card.artist_id
    if card.inferred_canonical_card is not None:
        return card.inferred_canonical_card.artist_id
    if card.inferred_canonical_artist_id is not None:
        return card.inferred_canonical_artist_id
    return None


@dataclass
class D0SiblingPropagationResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0


def run_d0_sibling_artist_propagation(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 2000,
    card_ids: Optional[Iterable[int]] = None,
) -> D0SiblingPropagationResult:
    """Part 3's d=0 sibling propagation - identical-image entailment: if card A and card B share
    the exact same content_phash (d=0, byte-identical art crop hash) and B has a resolved artist
    (via the same precedence chain Card.serialise() uses) while A doesn't, cast a CardArtistVote
    for A: B's artist, confidence 0.9, anonymous_id=ART_HASH_ARTIST_ANONYMOUS_ID, run_id,
    vote_surface=None. Idempotent (excludes cards that already have a vote from this
    anonymous_id, same convention as _eligible_base_queryset's engine exclusion) and safely
    RE-RUNNABLE as a plain command flag - expected near-zero yield today (the volume check found
    only 3 cards catalog-wide currently have any resolved artist at all - see
    docs/features/catalog-completion-plan.md's Status section), but grows for free as real
    confirmations accumulate; cheap to re-invoke, no reason to gate re-runs behind anything.

    BATCH SCOPING (`card_ids`, issue #533's first blocking prerequisite): when given, the TARGET
    population (the cards this pass would vote on) is that set of card pks, and the narrowing is
    pushed into every read this function makes rather than applied after the fact:

      1. `already_voted_ids` - `_art_hash_artist_voted_queryset(card_ids)`, so the `CardArtistVote`
         read filtered by this identity's `anonymous_id` is bounded too, not just the outer query
         it feeds. See that function's own docstring.
      2. `target_cards` - `.filter(pk__in=card_ids)` applied INSIDE this function, on the
         queryset, so the scope reaches the compiled SQL rather than a Python-side filter over a
         catalog-scale iteration.
      3. the `phash_to_artist_id` SOURCE index - narrowed by a SUBQUERY over the batch's own
         `content_phash` values (`Card.objects.filter(pk__in=card_ids, ...)`, kept lazy so it
         compiles as `IN (SELECT ...)` and is never materialised). Without this the index is
         built by iterating every artist-resolved card in the catalog, which is exactly the
         "looks scoped, is not" failure this work exists to prevent: the outer target query would
         be O(batch) while the pass as a whole stayed O(catalog).
         RESULT-EQUIVALENT, not an approximation: a source card whose `content_phash` no target
         card shares contributes a dict key nothing ever looks up, and narrowing by phash removes
         only such keys - it never changes which source card wins a phash the batch DOES contain,
         since the first-wins iteration order within any surviving phash group is untouched.

    `card_ids=None` (the management command's only calling shape) leaves all three reads exactly
    as they were - byte-identical to before. This function performs no image fetch on any path,
    so a per-batch caller has no fetch-budget decision to make here."""
    run_id = run_id or generate_run_id()

    resolved_source_cards = (
        Card.objects.filter(content_phash__isnull=False)
        .filter(
            Q(canonical_artist__isnull=False)
            | Q(canonical_card__artist__isnull=False)
            | Q(inferred_canonical_card__artist__isnull=False)
            | Q(inferred_canonical_artist__isnull=False)
        )
        .select_related(
            "canonical_artist", "canonical_card__artist", "inferred_canonical_card__artist", "inferred_canonical_artist"
        )
        .only(
            "pk",
            "content_phash",
            "canonical_artist",
            "canonical_card",
            "canonical_card__artist",
            "inferred_canonical_card",
            "inferred_canonical_card__artist",
            "inferred_canonical_artist",
        )
    )
    if card_ids is not None:
        # Item 3 of the BATCH SCOPING note above - a lazy queryset, deliberately NOT a
        # materialised set, so this compiles into the source query as `content_phash IN
        # (SELECT ...)` instead of pulling the batch's hashes through Python first.
        batch_content_phashes = Card.objects.filter(pk__in=card_ids, content_phash__isnull=False).values_list(
            "content_phash", flat=True
        )
        resolved_source_cards = resolved_source_cards.filter(content_phash__in=batch_content_phashes)
    phash_to_artist_id: dict[int, int] = {}
    for card in resolved_source_cards.iterator(chunk_size=chunk_size):
        # content_phash is guaranteed non-null here by the filter() above; mypy can't see
        # through the queryset filter, so this is a narrowing assert, not a real runtime risk.
        assert card.content_phash is not None
        artist_id = _resolved_artist_id(card)
        if artist_id is not None and card.content_phash not in phash_to_artist_id:
            phash_to_artist_id[card.content_phash] = artist_id

    result = D0SiblingPropagationResult(dry_run=dry_run, run_id=run_id)
    if not phash_to_artist_id:
        return result

    already_voted_ids = set(_art_hash_artist_voted_queryset(card_ids).values_list("card_id", flat=True))
    target_cards = (
        Card.objects.filter(content_phash__in=phash_to_artist_id.keys())
        .exclude(pk__in=already_voted_ids)
        .select_related(
            "canonical_artist", "canonical_card__artist", "inferred_canonical_card__artist", "inferred_canonical_artist"
        )
    )
    if card_ids is not None:
        target_cards = target_cards.filter(pk__in=card_ids)

    votes_batch: list[CardArtistVote] = []
    touched_card_ids: list[int] = []
    for card in target_cards.iterator(chunk_size=chunk_size):
        if _resolved_artist_id(card) is not None:
            continue  # already has its own resolved artist via the same chain - propagation adds nothing
        # content_phash is guaranteed non-null here (target_cards is filtered from
        # phash_to_artist_id's own keys, all real int hashes) - a narrowing assert for mypy.
        assert card.content_phash is not None
        artist_id = phash_to_artist_id[card.content_phash]
        result.cards_considered += 1
        result.votes_would_cast += 1
        if not dry_run:
            votes_batch.append(
                CardArtistVote(
                    card=card,
                    artist_id=artist_id,
                    is_unknown=False,
                    anonymous_id=ART_HASH_ARTIST_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=D0_SIBLING_ARTIST_CONFIDENCE,
                    run_id=run_id,
                    vote_surface=None,
                )
            )
            touched_card_ids.append(card.pk)

    if not dry_run:
        # CANCEL-SAFETY (2026-07-28) - same reasoning as run_frame_mismatch_recovery's own write
        # above and `vote_write.purge_and_write_votes`' docstring: purge and insert are one
        # atomic pair, scoped to exactly the rows written.
        purge_and_write_votes(
            CardArtistVote,
            votes_batch,
            anonymous_id=ART_HASH_ARTIST_ANONYMOUS_ID,
            target_field="card_id",
        )
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_artist(card)

    result.votes_written = len(votes_batch)
    return result


def verify_no_single_machine_vote_resolutions(card_ids: list[int]) -> list[int]:
    """Zero-resolution-style rail (item 2e - mirrors local_identify_printing_tags.
    verify_zero_resolutions / purge_machine_votes.verify_no_machine_only_resolutions'
    "structurally impossible but verify against real data" pattern): a card whose
    artist_vote_status is RESOLVED after this pass must have at least one HUMAN-backed vote
    behind that specific outcome - resolve_weighted_consensus's own human-backed gate
    (cardpicker.artist_consensus shares it with cardpicker.printing_consensus; see
    test_artist_votes.py::TestResolveArtist::test_ai_only_insufficient for the existing template
    asserting AI-only votes alone can never resolve) should make an all-machine resolution
    structurally impossible. Returns violating card pks (empty means clean)."""
    violations: list[int] = []
    for card in Card.objects.filter(pk__in=card_ids).prefetch_related("artist_votes"):
        if card.artist_vote_status != ArtistVoteStatus.RESOLVED:
            continue
        survivors = card.artist_votes.filter(artist_id=card.inferred_canonical_artist_id, is_unknown=False)
        if not any(is_human_backed_source(v.source) for v in survivors):
            violations.append(card.pk)
    return violations


__all__ = [
    "RESIDUAL_CLASSIFY_ANONYMOUS_ID",
    "ART_HASH_ARTIST_ANONYMOUS_ID",
    "ALTERED_FRAME_TAG_NAME",
    "FRAME_MISMATCH_ARTIST_CONFIDENCE",
    "FRAME_MISMATCH_TAG_CONFIDENCE",
    "D0_SIBLING_ARTIST_CONFIDENCE",
    "recover_frame_mismatch_printing_via_phash",
    "recover_frame_mismatch_printing_via_ocr_refetch",
    "recover_frame_mismatch_printing_via_fallback_refetch",
    "FrameMismatchRecoveryOutcome",
    "FrameMismatchRecoveryResult",
    "run_frame_mismatch_recovery",
    "D0SiblingPropagationResult",
    "run_d0_sibling_artist_propagation",
    "verify_no_single_machine_vote_resolutions",
]
