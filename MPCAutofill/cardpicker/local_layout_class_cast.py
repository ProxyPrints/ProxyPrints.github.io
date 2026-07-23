"""
Layout-class caster (public issue #369, "the Hidden Courtyard should register as borderless") -
a Stage D-style calculator (see `cardpicker.local_calculate_verdicts`'s module docstring for the
shared "harvest-calculate pipeline" framing this extends, and `cardpicker.local_detect_ai_art`'s
own near-identical shape, which this module mirrors structurally) that reads Stage C's already-
persisted `ImageEvidence.layout_class` (issue #148's geometry-group extractor,
`local_fallback.classify_border_color` under the hood) and casts the matching border-attribute
`CardTagVote` through the EXISTING, unmodified vote-consensus machinery
(`cardpicker.tag_consensus`/`cardpicker.vote_consensus`, both PROTECTED CORE per
`docs/upstreaming/license-provenance.md` SS2 - imported and called, never re-derived). No image
fetch, no pixel sampling here - this is a pure read over already-stored evidence, closing the gap
the issue names directly: Stage C has ALWAYS computed `layout_class` for every card with a fetched
image (issue #148), but nothing ever converted that stored reading into a vote unless the SAME
card also happened to pass through the live pilot/fallback engine's own in-flight
`local_fallback.cast_border_attribute_vote` call site (`local_identify_printing_tags.py`) in the
same run - a card processed before the geometry-group extractor existed, or one whose fallback
pass never ran for an unrelated reason (e.g. its printing already resolved via OCR/phash before
reaching the fallback stage), never got a border-attribute vote cast for it at all, even with a
perfectly confident `layout_class` sitting right there in storage.

MAPPING (this module's own chosen taxonomy decision, per the task's own request to state it
explicitly): `local_fallback.classify_border_color`'s value space is closed and already fully
enumerated by that module's own `BORDER_COLOR_TO_TAG` - "black"/"white"/"silver"/"borderless" map
1:1 onto the "Black Border"/"White Border"/"Silver Border"/"Borderless" attribute-chip tags
(`cardpicker.attribute_tags`), reused here verbatim (imported, not duplicated) rather than a
second copy of the same table that could quietly drift from it. The blank-string sentinel ("" -
`image_evidence.py`'s own "ambiguous or not yet run" convention for this field) is the ONE value
deliberately NOT cast: `classify_border_color` already collapsed every ambiguous/out-of-taxonomy
sample (a non-uniform border, or a genuine color outside this v1 taxonomy such as gold/yellow -
see that function's own docstring) down to `None` before `image_evidence.py` ever stored it as
"" - there is no further judgment call left for this caster to make beyond "cast the one
already-confident value, skip the rest," which is the conservative posture the task asks for.
A defensive `unmapped-layout-class` skip reason exists purely as a future-proofing guard should
that closed value space ever widen without a matching `BORDER_COLOR_TO_TAG` update - unreachable
against the current taxonomy, exercised directly in tests via a synthetic evidence value.

OWN ANONYMOUS_ID, NOT A REUSE OF `local_fallback.FALLBACK_ANONYMOUS_ID`: this module builds its
own `CardTagVote` rather than calling `local_fallback.cast_border_attribute_vote` directly (that
function's own mapping/confidence-tier CONSTANTS - `BORDER_COLOR_TO_TAG`,
`BORDER_ATTRIBUTE_VOTE_CONFIDENCE` - are reused verbatim; only its hardcoded
`anonymous_id=FALLBACK_ANONYMOUS_ID` construction is not reused as-is). Same precedent
`local_residual_classify.py` already established for its own related-but-distinct
frame-mismatch-recovery CardTagVote casts (`RESIDUAL_CLASSIFY_ANONYMOUS_ID`, distinct from
`FALLBACK_ANONYMOUS_ID` even though both vote on border/frame-adjacent attribute chips) - a
genuinely separate casting MECHANISM (reads stored Stage C evidence in bulk, independent of
whether the live pilot/fallback pass ever ran for a given card) earns its own identity so it is
independently purgeable/re-runnable via the existing `purge_machine_votes --run-id` mechanism,
and so the `(card, tag, anonymous_id)` uniqueness constraint on `CardTagVote` is what makes "skip
a card already voted by THIS identity" a plain query rather than bespoke bookkeeping (the same
reasoning `local_identify_printing_tags.py`'s own `OCR_ANONYMOUS_ID`/`PHASH_ANONYMOUS_ID` comment
gives for why each engine gets its own).

CONFIDENCE TIER: always `BORDER_ATTRIBUTE_VOTE_CONFIDENCE` (the heuristic tier) - never
`GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE`. The ground-truth-preferred override that constant backs
(`local_identify_printing_tags.py`'s write loop) only applies once a specific printing has been
CONFIRMED for the card this same run, so the matched printing's own Scryfall `border_color` can
be substituted for the pixel estimate - this calculator does no candidate/printing matching at
all (same "metadata only, no candidate matching" scope every other Stage C/D reader in this
codebase draws - see `image_evidence.py`'s own module docstring), so it never has a ground-truth
value to prefer, and always votes at the heuristic tier `classify_border_color` itself carries.

NON-HUMAN-BACKED, NEVER RESOLVES ALONE: same discipline as every other machine engine in this
codebase (`local_detect_ai_art.py`'s own docstring makes the identical point) - a single
`VoteSource.OCR` vote can never itself resolve a tag (`resolve_weighted_consensus`'s human-backed
hard gate, `vote_consensus.py`); this calculator only ever suggests, never resolves. Verified
empirically after every write via `purge_machine_votes.verify_no_machine_only_resolutions`,
reused directly rather than re-derived - see this module's own management command.

ZERO IMAGE FETCHES: every input (`ImageEvidence.layout_class`, already computed and persisted by
Stage C) is already in the database - no network call, no `fetch_card_image`, anywhere in this
module.
"""

from dataclasses import dataclass, field
from typing import Optional

from django.db.models import QuerySet

from cardpicker.local_fallback import (
    BORDER_ATTRIBUTE_VOTE_CONFIDENCE,
    BORDER_COLOR_TO_TAG,
)
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTagVote,
    ImageEvidence,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes

# Own anonymous_id (distinct from local_fallback.FALLBACK_ANONYMOUS_ID and every other engine's -
# see module docstring's "OWN ANONYMOUS_ID" section for the full reasoning).
LAYOUT_CLASS_CAST_ANONYMOUS_ID = "layout-class-cast-v1"

# The one ImageEvidence extractor_versions key this calculator needs - layout_class is the
# geometry-group extractor's own field (issue #148), computed alongside width/height/bleed_class
# in the same extract_card_evidence() pass but versioned independently (image_evidence.py).
REQUIRED_EXTRACTOR_KEYS: tuple[str, ...] = ("layout_class",)

# Skip reasons that stay eligible for re-selection on a future invocation (same convention as
# local_detect_ai_art.AI_ART_RESCANNABLE_SKIP_REASONS) - both describe a transient "nothing to
# look at YET" state, not a genuine conclusion against the card's actual stored evidence.
# "ambiguous" (a confident classify_border_color reading never materialized for this
# content_hash) and "unmapped-layout-class" (module docstring) are deliberately NOT here - both
# are genuine, repeatable conclusions for this content_hash's own stored evidence, same
# "permanent unless the taxonomy/extractor itself changes" reasoning local_detect_ai_art.py's
# "no-marker-hit" gets.
LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence", "incomplete-evidence"})


@dataclass(frozen=True)
class LayoutClassVerdict:
    """Pure result of reading one card's current ImageEvidence.layout_class - no DB write has
    happened yet (mirrors AiArtVerdict's own compute/persist split). `layout_class` is the raw
    stored value ("" for no confident reading); `tag_name`/`confidence` are populated only when
    it maps onto a known attribute-chip tag (see `is_hit`)."""

    card_id: int
    layout_class: str = ""
    tag_name: Optional[str] = None
    confidence: Optional[float] = None

    @property
    def is_hit(self) -> bool:
        return self.tag_name is not None


def calculate_layout_class_verdict(card_id: int, evidence: ImageEvidence) -> LayoutClassVerdict:
    """The layout-class mapping calculator. Pure function, no DB write, no image fetch, no
    re-classification - reads only the already-persisted `layout_class` field off `evidence` and
    looks it up in `local_fallback.BORDER_COLOR_TO_TAG` (module docstring's MAPPING section)."""
    layout_class = evidence.layout_class or ""
    if not layout_class:
        return LayoutClassVerdict(card_id=card_id, layout_class="")
    tag_name = BORDER_COLOR_TO_TAG.get(layout_class)
    if tag_name is None:
        # Defensive only - classify_border_color's own closed value space (module docstring)
        # never actually produces a string outside BORDER_COLOR_TO_TAG's four keys today.
        return LayoutClassVerdict(card_id=card_id, layout_class=layout_class)
    return LayoutClassVerdict(
        card_id=card_id,
        layout_class=layout_class,
        tag_name=tag_name,
        confidence=BORDER_ATTRIBUTE_VOTE_CONFIDENCE,
    )


@dataclass
class LayoutClassCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    votes_by_class: dict[str, int] = field(default_factory=dict)
    skip_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, mirroring AiArtDetectorResult/JoinKeyCalculatorResult's own "up to N,
    # for the report" convention elsewhere in this codebase.
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset() -> "QuerySet[Card]":
    """Every card NOT already voted on by this calculator's own anonymous_id (at most one tag is
    ever cast per card by this identity - a card has exactly one `layout_class` reading - so a
    single `tag_votes__anonymous_id` exclude, with no per-tag qualifier needed, correctly covers
    "already handled" regardless of which of the four border tags it landed on), and not already
    carrying a non-rescannable `CardScanLog` row from a prior invocation (same idempotence
    pattern as `local_detect_ai_art._eligible_cards_queryset`).

    Deliberately unrestricted by `card_type`/`printing_tag_status` - border-color classification
    is orthogonal to printing identification (a token or an unresolved card's border is just as
    plausibly black/white/silver/borderless as any other card's), same reasoning
    `local_detect_ai_art._eligible_cards_queryset`'s own docstring gives for AI-art detection."""
    non_rescannable_scanned_card_ids = (
        CardScanLog.objects.filter(anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID)
        .exclude(skip_reason__in=LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS)
        .values_list("card_id", flat=True)
    )
    return (
        Card.objects.exclude(tag_votes__anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
    )


def run_layout_class_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
) -> LayoutClassCastResult:
    """Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row (its
    `content_hash` matching the card's own live `content_phash` - an evidence row from a prior
    image version is never trusted for a card whose upload has since changed, same convention as
    `local_calculate_verdicts.run_join_key_calculator`/`local_detect_ai_art.run_ai_art_detector`)
    that has completed the geometry-group extractor (`REQUIRED_EXTRACTOR_KEYS`). `dry_run=True`
    (the default, matching every other Stage 3+ command's own opt-in-to-write convention)
    computes and counts everything without writing any `CardTagVote`/`CardScanLog` row.

    GATE VERIFICATION: this function itself casts no gate check (matching `run_ai_art_detector`'s
    own split - the batch computation stays pure/testable, the management command layers the
    gate check + `CommandError` on top, reusing
    `cardpicker.management.commands.purge_machine_votes.verify_no_machine_only_resolutions`
    rather than re-deriving an equivalent check).
    """
    run_id = run_id or generate_run_id()
    result = LayoutClassCastResult(dry_run=dry_run, run_id=run_id)

    tag_by_name = {t.name: t for t in Tag.objects.filter(name__in=set(BORDER_COLOR_TO_TAG.values()))}
    missing_tags = sorted(set(BORDER_COLOR_TO_TAG.values()) - tag_by_name.keys())
    if missing_tags:
        raise RuntimeError(
            f"Tag(s) {missing_tags} do not exist yet - run `seed_attribute_tags`/`seed_default_tags` "
            "before this calculator."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    for card in _eligible_cards_queryset().iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = (
            ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
            .order_by("-updated_at")
            .first()
        )
        if evidence is None:
            result.skip_counts["no-evidence"] = result.skip_counts.get("no-evidence", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason="no-evidence",
                    )
                )
            continue

        if any(key not in evidence.extractor_versions for key in REQUIRED_EXTRACTOR_KEYS):
            result.skip_counts["incomplete-evidence"] = result.skip_counts.get("incomplete-evidence", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason="incomplete-evidence",
                    )
                )
            continue

        result.cards_considered += 1
        verdict = calculate_layout_class_verdict(card.pk, evidence)

        if not verdict.is_hit:
            skip_reason = "ambiguous" if not verdict.layout_class else "unmapped-layout-class"
            result.skip_counts[skip_reason] = result.skip_counts.get(skip_reason, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=skip_reason,
                    )
                )
            continue

        result.votes_would_cast += 1
        result.votes_by_class[verdict.layout_class] = result.votes_by_class.get(verdict.layout_class, 0) + 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "layout_class": verdict.layout_class, "tag": verdict.tag_name})

        if not dry_run:
            assert verdict.tag_name is not None  # is_hit already checked this
            votes_batch.append(
                CardTagVote(
                    card_id=card.pk,
                    tag=tag_by_name[verdict.tag_name],
                    polarity=VotePolarity.APPLY,
                    anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=verdict.confidence,
                    run_id=run_id,
                )
            )

    if not dry_run:
        # ignore_conflicts=True: belt-and-suspenders against the (card, tag, anonymous_id)
        # uniqueness constraint - the eligibility query above already excludes any card this
        # identity has voted on, so a conflict here would only ever come from two concurrent
        # invocations racing, not from this invocation's own logic.
        CardTagVote.objects.bulk_create(votes_batch, ignore_conflicts=True)
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.votes_written = len(votes_batch)

        touched_card_ids = [vote.card_id for vote in votes_batch]
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_tag_votes(card)

    return result


__all__ = [
    "LAYOUT_CLASS_CAST_ANONYMOUS_ID",
    "REQUIRED_EXTRACTOR_KEYS",
    "LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS",
    "LayoutClassVerdict",
    "calculate_layout_class_verdict",
    "LayoutClassCastResult",
    "run_layout_class_cast",
]
