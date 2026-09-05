"""
Weighted filename-candidate narrowing (issue #946).

`Tags.match_canonical_card` (cardpicker/tags.py) is binary: a filename's tags either resolve to
exactly one `CanonicalCard` composite key, or nothing happens - the `len(matched_tags) > 1`
branch discards a real result. Measured against the live catalogue (pipeline-artifacts/
filename-signal-sizing/): 75.87% of unlinked cards carry a name match that resolves to more than
one candidate. That narrowing is most of the identification work, and today it is indistinguishable
from having learned nothing.

OWNER RULING THIS IMPLEMENTS: harvest every field the filename and folder path carry; where
signals resolve to more than one candidate, keep the candidates and weigh them rather than
collapsing to no-match; abstain only on genuine CONTRADICTION between signals, not on the
ordinary case of a signal that merely fails to be unique.

THIS IS NOT A NEW PARALLEL MECHANISM. `generate_candidates_for_card` starts from the same
production name index (`local_identify_printing_tags.CandidateNameIndex`, shared with
`deductive_backfill`'s own D1/D2 tiers via `local_calculate_verdicts._get_cached_candidate_name_
index()`), and every candidate this module concludes is emitted as an ordinary `VoteSource.
DEDUCTION` `CardPrintingTag` row through the existing `vote_write.purge_and_write_votes`
primitive - the same evidence channel `deductive_backfill.py` already writes to. Multiple
candidate rows for one card, all under this module's ONE `anonymous_id`, is safe by construction:
`vote_consensus.resolve_weighted_consensus` groups votes by `outcome_key` (the printing pk), so N
weighted guesses about the SAME card land in N *different* outcome groups and can never inflate
any single group's weight, and DEDUCTION votes can never satisfy the human-backed gate regardless
of volume (see that function's own docstring) - this module cannot resolve a card by itself, at
any candidate-set size, exactly like every other machine channel in this pipeline.

SCOPE: only the residual `deductive_backfill` D1/D2 leave behind. `_eligible_base_queryset`
excludes any card `deductive_backfill.DEDUCTIVE_BACKFILL_ANONYMOUS_ID` already voted on - D1/D2
are provably exact where they apply (a unique name match, or an explicit set-code hint narrowing
to exactly one), so this module never competes with or duplicates that result; it only runs where
D1/D2 gave up because more than one candidate remained.

SIGNALS CONSULTED, AND WHY "FOLDER PATH" HAS NO SEPARATE CODE PATH HERE: name (via
`CandidateNameIndex.candidates_for` - the production path), `Card.expansion_hint` (a lone
set-code bracket token), `Card.canonical_artist_id` (an explicit artist-tag bracket match), and
treatment tags (`Card.tags` compared against a candidate's own border/frame/full-art metadata).
Folder path is already folded into every one of those three non-name signals BEFORE this module
ever sees the card: `Tags.extract()`'s `Folder.get_tags` unions each image's own tags with every
ancestor folder's tags (cardpicker/sources/api.py's `Folder.unpack_name`/`get_tags`), so a
set-code or artist name or treatment token that lives in the FOLDER name rather than the file
name is already merged into `card.tags`/`expansion_hint`/`canonical_artist_id` by the time a
`Card` row exists. A separate folder-path-scanning signal here would be re-parsing information
this module's own inputs already carry.

OBSERVED FRAME ERA (issue #967's sibling channel, frame era only): the treatment signal above
compared `card.tags` - filename/folder tokens - against a candidate's OWN metadata, but never
what pixel/OCR evidence actually observed about the fetched image. `generate_candidates_for_card`
now also accepts `observed_frame_era_tag`, the same "Old Border"/"Modern Border" tag name
`local_attribute_chip_cast.calculate_attribute_chip_verdict` derives from a card's stored
`ImageEvidence` (via `local_fallback.classify_frame_style` - PROTECTED CORE, called unmodified) -
`select_candidates` computes it per card and passes it in, so this module stays DB-free. It is
UNIONED into `card_tag_set` rather than treated as its own signal (owner-ruled default (a) over a
fourth `observed_treatment` signal (b)): an observed reading can only ADD a match, never trigger
this module's contradiction rule, and an observed tag that already agrees with a filename tag
collapses into the same set entry rather than double-counting. Measured on the only population
where both readings exist today (13 cards ever carry a filename frame-era tag; 10 also have a
current observed reading): 6/10 disagree - re-skinning an old printing into a modern-style proxy
render is the common case here too (see `local_fallback.py`'s own "three questions about a card's
frame" note), which is precisely why (b) is not implemented: a fourth signal would turn most of
that population into contradiction-abstentions over a difference that is normal, not evidence of
a wrong printing match. Border colour and art-edge remain out of scope for this channel - see
`_candidate_treatment_tags`'s own docstring.

CONTRADICTION, DEFINED NARROWLY (the owner's "cannot both be true" test, not "failed to agree"):
a single signal that agrees with none of the name-matched candidates is NOT a contradiction - it
is discarded (no boost, no narrowing) and the rest of the candidate generation proceeds
unaffected, since the likelier explanation is an incomplete catalogue (the true printing simply
isn't among our candidates) rather than an impossible card. A contradiction fires only when TWO
OR MORE signals each independently agree with at least one base candidate, but their agreeing
subsets share NO candidate at all - i.e. the filename asserts two facts about the same physical
card (e.g. "this printing is from set X" and "this printing was illustrated by artist Y") that no
single row in our own catalogue satisfies together. That is the narrow case where corroboration
becomes impossible rather than merely absent, and it is the only case this module abstains on
rather than weighing.

CAPPING THE EMITTED SET (issue #946 follow-up, "cap the candidate set before it can be written"):
a bounded production dry-run found ~14.6% of eligible cards (basic lands and other staple
reprints) carrying 900+ name-matched candidates each, and since signal matching only WEIGHTS
`base_candidates` rather than filtering it, every one of those hundreds was being emitted as a
vote. Two changes fix this without touching the signals themselves: (1) a card whose base
candidate set exceeds `TOO_MANY_CANDIDATES_THRESHOLD` abstains outright (reason
"too-many-candidates") rather than emitting a handful of specific printings an evidence set that
large cannot actually support; (2) a card that clears that bar still emits at most
`MAX_EMITTED_CANDIDATES`, the top candidates by confidence.
"""

import collections
import itertools
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from django.db.models import QuerySet
from django.utils import timezone

from cardpicker.deductive_backfill import (
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    verify_zero_resolutions,
)
from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_attribute_chip_cast import calculate_attribute_chip_verdict
from cardpicker.local_calculate_verdicts import _get_cached_candidate_name_index
from cardpicker.local_identify_printing_tags import (
    PHASH_MAX_CANDIDATES,
    CandidateNameIndex,
    CandidatePrinting,
)
from cardpicker.models import (
    CanonicalArtist,
    Card,
    CardPrintingTag,
    CardTypes,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.vote_write import purge_and_write_votes

FILENAME_CANDIDATES_ANONYMOUS_ID = "filename-candidates-v1"

# Confidence is informational only - see vote_consensus.resolve_vote_weight's own docstring
# ("CONFIDENCE IS NOT A PARAMETER of consensus weight"). Every row this module writes still
# resolves to the ordinary settings.PRINTING_TAG_MACHINE_WEIGHT like any other DEDUCTION vote;
# these constants only shape what a HUMAN reviewer (question_feed, the /editor suggestion chip)
# sees as this module's own confidence in a given candidate.
#
# Deliberately BELOW deductive_backfill's D1 (0.95) and D2 (0.90): those are exact matches (a
# unique name, or a hint narrowing to exactly one) with nothing left to corroborate. Every
# candidate this module emits, even one that agrees with every available signal, is still drawn
# from a set that stayed ambiguous after D1/D2 - corroboration across soft signals narrows
# likelihood, it does not manufacture the certainty an exact match already has.
NAME_ONLY_CONFIDENCE = 0.5
SIGNAL_CONFIDENCE_BONUS = 0.2
MAX_CANDIDATE_CONFIDENCE = 0.85

# Cap on how many candidates a single card's result actually EMITS as votes (issue #946 follow-
# up: "cap the candidate set before it can be written"). Owner ruling: a ranked shortlist, top N
# by weight, fewer when a signal already makes the guess more decisive. Distinct from
# TOO_MANY_CANDIDATES_THRESHOLD below - that governs whether this module has anything informative
# to assert AT ALL; this governs how many assertions it makes once it does. Measured against the
# live catalogue's own candidate-size distribution for cards that clear that threshold (2
# candidates: 644 cards; 3: 522; 4: 486; 5: 361 - pipeline-artifacts/filename-signal-sizing/), a
# cap of 5 leaves the emitted set UNTRUNCATED for the large majority of cards that reach this
# point; only the long tail above 5 gets narrowed.
MAX_EMITTED_CANDIDATES = 5

# Reuse local_identify_printing_tags.PHASH_MAX_CANDIDATES (12) as the "candidate set this large
# asserts nothing a consumer can act on" line, rather than inventing a second, unrelated number:
# that constant already encodes this exact judgment call against the same underlying data (a name
# match too broad to be useful - basic lands/staple commons with hundreds of printings), just
# reached via a different caller (local_identify_printing_tags' phash engine skips per-candidate
# hashing work above this same line, for the identical reason - see that constant's own comment).
# A truncated top-5 out of a base set numbering in the hundreds would assert five specific
# printings the evidence never supported; abstaining is the honest output instead.
TOO_MANY_CANDIDATES_THRESHOLD = PHASH_MAX_CANDIDATES

CandidateSignal = Literal["expansion_hint", "artist", "treatment"]
AbstainReason = Literal["no-name-match", "contradiction", "too-many-candidates"]


@dataclass(frozen=True)
class WeightedCandidate:
    printing_id: int
    confidence: float
    matched_signals: frozenset[CandidateSignal]


@dataclass(frozen=True)
class CardCandidateResult:
    card_id: int
    candidates: tuple[WeightedCandidate, ...] = ()
    abstain_reason: Optional[AbstainReason] = None
    # Human-readable detail for a "contradiction" abstention - which signals disagreed and over
    # which candidate pks - surfaced by the management command's dry-run report, never persisted.
    contradiction_detail: Optional[str] = None


# The border-color/frame-era attribute tags this module knows how to corroborate against
# CanonicalPrintingMetadata (cardpicker.attribute_tags.ATTRIBUTE_TAGS' border-color and
# frame-era groups, plus DEFAULT_TAGS' "Full Art"). Scryfall's own frame values ("1993"/"1997"
# = pre-8th-edition "old" border era, "2003"/"2015" = "modern") - duplicated as a literal here
# rather than imported from local_fallback.py (PROTECTED CORE - see docs/upstreaming/
# license-provenance.md §2), matching this codebase's own established "duplicate a small mapping
# as a literal rather than import across an unrelated module boundary" convention (e.g.
# DEDUCTIVE_BACKFILL_ANONYMOUS_ID's own duplication comment in local_identify_printing_tags.py).
_FRAME_ERA_TAGS: dict[str, str] = {
    "1993": "Old Border",
    "1997": "Old Border",
    "2003": "Modern Border",
    "2015": "Modern Border",
}
_BORDER_COLOR_TAGS: dict[str, str] = {
    "black": "Black Border",
    "white": "White Border",
    "silver": "Silver Border",
}


def _candidate_treatment_tags(candidate: CandidatePrinting) -> frozenset[str]:
    """The Tag names a human would expect on a card that truly depicts `candidate`, derived from
    its own CanonicalPrintingMetadata fields - compared against `Card.tags` (the filename/folder
    tags actually matched at ingest) by `generate_candidates_for_card`'s treatment signal."""
    tags: set[str] = set()
    if candidate.full_art:
        tags.add("Full Art")
    border_tag = _BORDER_COLOR_TAGS.get(candidate.border_color)
    if border_tag:
        tags.add(border_tag)
    era_tag = _FRAME_ERA_TAGS.get(candidate.frame)
    if era_tag:
        tags.add(era_tag)
    return frozenset(tags)


def generate_candidates_for_card(
    card: Card,
    index: CandidateNameIndex,
    artist_name_by_pk: dict[int, str],
    observed_frame_era_tag: Optional[str] = None,
) -> CardCandidateResult:
    """The candidate generator itself - pure and DB-free beyond what `index`/`artist_name_by_pk`/
    `observed_frame_era_tag` already carry, so it's directly unit-testable against hand-built
    `CandidatePrinting`s. See this module's own docstring for the signal list, the confidence
    formula, and the contradiction rule.

    `observed_frame_era_tag`: the "Old Border"/"Modern Border" tag `select_candidates` derived
    from this card's own stored `ImageEvidence` (see module docstring's "OBSERVED FRAME ERA"
    section) - `None` when no observation is available, which leaves the treatment signal exactly
    as it was before this parameter existed."""
    base_candidates = index.candidates_for(card.name)
    if not base_candidates:
        return CardCandidateResult(card_id=card.pk, abstain_reason="no-name-match")
    if len(base_candidates) > TOO_MANY_CANDIDATES_THRESHOLD:
        return CardCandidateResult(card_id=card.pk, abstain_reason="too-many-candidates")

    signal_matches: dict[CandidateSignal, list[CandidatePrinting]] = {}

    if card.expansion_hint:
        matches = [c for c in base_candidates if c.expansion_code == card.expansion_hint]
        if matches:
            signal_matches["expansion_hint"] = matches

    if card.canonical_artist_id:
        artist_name = artist_name_by_pk.get(card.canonical_artist_id)
        if artist_name:
            matches = [c for c in base_candidates if c.artist_name == artist_name]
            if matches:
                signal_matches["artist"] = matches

    card_tag_set = set(card.tags)
    if observed_frame_era_tag:
        card_tag_set.add(observed_frame_era_tag)
    if card_tag_set:
        matches = [c for c in base_candidates if _candidate_treatment_tags(c) & card_tag_set]
        if matches:
            signal_matches["treatment"] = matches

    if len(signal_matches) >= 2:
        pk_sets = [{c.pk for c in matches} for matches in signal_matches.values()]
        if not set.intersection(*pk_sets):
            detail = ", ".join(f"{signal}={sorted(pks)}" for signal, pks in zip(signal_matches.keys(), pk_sets))
            return CardCandidateResult(card_id=card.pk, abstain_reason="contradiction", contradiction_detail=detail)

    matched_signal_counts: dict[int, set[CandidateSignal]] = collections.defaultdict(set)
    for signal, matches in signal_matches.items():
        for c in matches:
            matched_signal_counts[c.pk].add(signal)

    all_weighted = [
        WeightedCandidate(
            printing_id=c.pk,
            confidence=min(
                NAME_ONLY_CONFIDENCE + SIGNAL_CONFIDENCE_BONUS * len(matched_signal_counts.get(c.pk, ())),
                MAX_CANDIDATE_CONFIDENCE,
            ),
            matched_signals=frozenset(matched_signal_counts.get(c.pk, ())),
        )
        for c in base_candidates
    ]
    all_weighted.sort(key=lambda wc: (-wc.confidence, wc.printing_id))
    weighted = tuple(all_weighted[:MAX_EMITTED_CANDIDATES])
    return CardCandidateResult(card_id=card.pk, candidates=weighted)


def _eligible_base_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Unresolved, no confirmed indexing match, `card_type=CARD` only (tokens' collector lines
    read their PARENT set's code - the same structural mismatch `local_identify_printing_tags._
    eligible_base_queryset`'s own docstring documents), English-language only (name-matching is
    against `CanonicalCard.name`, Scryfall's English oracle name), no resolved "Custom" tag (the
    PRINCIPLE's precondition - an authentic depiction of a real printing - already false), no
    existing `deductive_backfill` vote (D1/D2 are exact where they apply - see module docstring's
    SCOPE section), and no existing vote from THIS module's own anonymous_id (idempotence: a
    re-invocation resumes onto cards it hasn't already decided, rather than re-processing them)."""
    queryset = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
            language__iexact="en",
        )
        .exclude(tags__contains=["Custom"])
        .exclude(printing_tags__anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
        .exclude(printing_tags__anonymous_id=FILENAME_CANDIDATES_ANONYMOUS_ID)
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def _observed_frame_era_tag_for_card(card: Card) -> Optional[str]:
    """The per-card DB lookup `generate_candidates_for_card` itself never does (see module
    docstring's "OBSERVED FRAME ERA" section) - `None` whenever there's no stable hash yet, no
    CURRENT `ImageEvidence` row (`image_evidence.current_evidence_queryset`, the shared currency
    definition), or the frame chip calculator itself abstains (missing extractors, or neither
    signal fired). `local_attribute_chip_cast.calculate_attribute_chip_verdict` is called
    unmodified - it already gates on `FRAME_REQUIRED_EXTRACTOR_KEYS` and maps to the exact
    "Old Border"/"Modern Border" tag names this module's own `_FRAME_ERA_TAGS` uses."""
    if card.content_phash is None:
        return None
    evidence = current_evidence_queryset(card).order_by("-updated_at").first()
    if evidence is None:
        return None
    return calculate_attribute_chip_verdict(card.pk, evidence).frame_tag_name


def select_candidates(
    index: "CandidateNameIndex | None" = None, card_ids: Optional[Iterable[int]] = None
) -> Iterable[CardCandidateResult]:
    """Yields one `CardCandidateResult` per eligible card - including abstentions, so a caller
    can tally them (`run_filename_candidate_narrowing` does exactly that). Same shared,
    process-cached `CandidateNameIndex` as `deductive_backfill.select_candidates` - see that
    function's own docstring."""
    index = index or _get_cached_candidate_name_index()
    artist_name_by_pk = dict(CanonicalArtist.objects.values_list("pk", "name"))
    for card in (
        _eligible_base_queryset(card_ids=card_ids)
        .only("pk", "name", "expansion_hint", "canonical_artist_id", "tags", "content_phash", "md5_checksum")
        .iterator(chunk_size=2000)
    ):
        observed_frame_era_tag = _observed_frame_era_tag_for_card(card)
        yield generate_candidates_for_card(card, index, artist_name_by_pk, observed_frame_era_tag)


def generate_run_id() -> str:
    """Fresh per-invocation run_id - same shape as `local_identify_printing_tags.generate_run_id`
    (a UTC-timestamp prefix for scannability plus a short random suffix so two invocations in the
    same second can't collide), prefixed with this calculator's own anonymous_id so a run stamp
    names its calculator on sight, matching `deductive_backfill.generate_run_id`'s convention."""
    return f"{FILENAME_CANDIDATES_ANONYMOUS_ID}/{timezone.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass
class RunResult:
    dry_run: bool = False
    cards_considered: int = 0
    cards_with_candidates: int = 0
    cards_abstained_no_name_match: int = 0
    cards_abstained_too_many_candidates: int = 0
    cards_abstained_contradiction: int = 0
    votes_written: int = 0
    # candidate-set size -> number of cards that produced a set of exactly that size (the "size
    # distribution" the task's own report requirement asks for).
    candidate_set_size_histogram: dict[int, int] = field(default_factory=lambda: collections.defaultdict(int))
    contradiction_examples: list[str] = field(default_factory=list)
    gate_violations: list[int] = field(default_factory=list)


# Cap on how many contradiction examples RunResult keeps for the dry-run report - a card-by-card
# reason for every contradiction would be unreadable at scale; a bounded sample is enough to spot-
# check the rule's own behaviour, matching the "[:50]" truncation convention every other
# management command's own reporting output already uses.
_CONTRADICTION_EXAMPLES_LIMIT = 20


def run_filename_candidate_narrowing(
    limit: Optional[int] = None,
    dry_run: bool = True,
    batch_size: int = 500,
    card_ids: Optional[Iterable[int]] = None,
) -> RunResult:
    """Selects candidates, writes them in `batch_size` chunks (so an interrupted run keeps
    whatever it already committed - `_eligible_base_queryset` excludes any card this module has
    already voted on, so a plain re-invocation resumes correctly), then - unless `dry_run` - runs
    the live gate check over every card just written to. `dry_run=True` is the default: every
    caller (the management command) must pass `dry_run=False` explicitly to write anything."""
    results = select_candidates(card_ids=card_ids)
    if limit is not None:
        results = itertools.islice(results, limit)

    run_id = generate_run_id()
    result = RunResult(dry_run=dry_run)
    written_card_ids: list[int] = []
    batch: list[CardPrintingTag] = []

    def flush(pending: list[CardPrintingTag]) -> None:
        if not pending:
            return
        if not dry_run:
            purge_and_write_votes(
                CardPrintingTag, pending, anonymous_id=FILENAME_CANDIDATES_ANONYMOUS_ID, target_field="card_id"
            )
        result.votes_written += len(pending)
        written_card_ids.extend({row.card_id for row in pending})

    for card_result in results:
        result.cards_considered += 1
        if card_result.abstain_reason == "no-name-match":
            result.cards_abstained_no_name_match += 1
            continue
        if card_result.abstain_reason == "too-many-candidates":
            result.cards_abstained_too_many_candidates += 1
            continue
        if card_result.abstain_reason == "contradiction":
            result.cards_abstained_contradiction += 1
            if len(result.contradiction_examples) < _CONTRADICTION_EXAMPLES_LIMIT:
                result.contradiction_examples.append(f"card={card_result.card_id}: {card_result.contradiction_detail}")
            continue

        result.cards_with_candidates += 1
        result.candidate_set_size_histogram[len(card_result.candidates)] += 1
        for candidate in card_result.candidates:
            batch.append(
                CardPrintingTag(
                    card_id=card_result.card_id,
                    printing_id=candidate.printing_id,
                    is_no_match=False,
                    anonymous_id=FILENAME_CANDIDATES_ANONYMOUS_ID,
                    source=VoteSource.DEDUCTION,
                    confidence=candidate.confidence,
                    run_id=run_id,
                )
            )
        if len(batch) >= batch_size:
            flush(batch)
            batch = []
    flush(batch)

    if not dry_run and written_card_ids:
        result.gate_violations = verify_zero_resolutions(written_card_ids)

    return result


__all__ = [
    "FILENAME_CANDIDATES_ANONYMOUS_ID",
    "NAME_ONLY_CONFIDENCE",
    "SIGNAL_CONFIDENCE_BONUS",
    "MAX_CANDIDATE_CONFIDENCE",
    "MAX_EMITTED_CANDIDATES",
    "TOO_MANY_CANDIDATES_THRESHOLD",
    "WeightedCandidate",
    "CardCandidateResult",
    "generate_candidates_for_card",
    "select_candidates",
    "generate_run_id",
    "RunResult",
    "run_filename_candidate_narrowing",
]
