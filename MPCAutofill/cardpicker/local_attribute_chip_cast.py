"""
Attribute-chip caster for the FRAME-STYLE chip (2026-07-30, closing the hole
`docs/reports/2026-07-29-pipeline-coverage-composition-audit.md` §1 Q1 items 1-2 measured). The
BLEED-EDGE half this module used to cast is RETIRED - superseded by `local_bleed_calculator`
(identity `bleed-calculator-cast-v1`), which is now the sole machine channel for
`appropriate-bleed`. See the RETIRED BLEED-EDGE section below.

WHAT WAS BROKEN. `local_fallback.cast_frame_style_vote` and `local_fallback.cast_bleed_edge_vote`
were reachable from exactly two call sites: `local_identify_printing_tags.run_pilot` (the
live-FETCH pilot, one completed run in its entire history, 2026-07-16) and
`image_evidence.extract_card_evidence` (which has ZERO production callers - both engines call
`compute_card_evidence` + `persist_evidence` directly and skip it). So neither pipeline engine has
ever been able to cast either chip. After the 2026-07-29 purge that left `Old Border`,
`Modern Border` and `appropriate-bleed` at **zero machine rows with no substitute**, and nothing in
the codebase able to produce one.

Border colour survived the same purge only by accident: it was being computed TWICE from the same
classifier, and the second copy (`local_layout_class_cast`, identity `layout-class-cast-v1`) reads
stored evidence and is still live at 216,476 rows. This module is that same shape, applied to the
frame-style chip that had no such accidental twin. It deliberately does NOT cast border - that
would be a THIRD border channel, and the duplication is the audit's §6 cull recommendation, not a
pattern to extend. `local_layout_class_cast` remains the border caster.

RETIRED BLEED-EDGE. This module's original bleed branch (`BLEED_EDGE_CAST_ANONYMOUS_ID`,
`bleed-edge-cast-v1`) voted on `bleed_class == "trimmed"` alone. `local_bleed_calculator` derives
the same verdict from a cross-checked pair of methods and WITHHOLDS its vote where the per-edge
pinline measurement contradicts the `trimmed` reading past a 2mm gate - the abstention is the whole
point of the calculator. Running both casters would double-count one signal (every card the
calculator votes on already got an old-caster vote from the same underlying `bleed_class`), and the
old caster's unconditional vote would land on exactly the cards the calculator deliberately
abstains on, defeating the abstention entirely. So the bleed branch is RETIRED, not kept alongside:
no code path writes a NEW `CardTagVote`/`CardScanLog` row under `bleed-edge-cast-v1` anymore. The
identity constant stays declared and exported, and the frame-style pass never reuses it, purely so
HISTORICAL rows (retractable via `purge_machine_votes --run-id`) still read sensibly and still
route correctly - the same retired-not-removed treatment `TRANSFERRED_INTERIM_GUARD_SKIP_REASON`
and `JOIN_KEY_PROXY_MARKER_VETO_SKIP_REASON` received in `local_calculate_verdicts`.

ZERO IMAGE FETCHES. Every input is already in the database. `classify_frame_style`'s two arguments
are `bool(ImageEvidence.collector_line_collector_number)` and `ImageEvidence.illus_anchor_fired`.
Nothing here opens a socket or touches PIL. This matters because the only pre-existing path to this
chip was the live-fetch pilot, so re-deriving it through there would have meant re-fetching
~220,000 images to recompute facts already sitting in storage. Measured derivable population
against production (2026-07-29, read-only): `Modern Border` 133,627, `Old Border` 9,006.

CONSTANTS REUSED, VOTE CONSTRUCTION NOT. `classify_frame_style`, `FRAME_STYLE_TO_TAG` and
`FRAME_VOTE_CONFIDENCE` are imported from `local_fallback` verbatim, never re-derived, so this
module and the pilot cannot drift on what a frame class IS or what it is worth. Only the caster's
own hardcoded `anonymous_id=FALLBACK_ANONYMOUS_ID` construction is not reused - exactly the split
`local_layout_class_cast` already established for the border chip, and for the same reason.

REQUIRED_EXTRACTOR_KEYS. `collector_line_ocr` and `artist_ocr` are both required for a frame
reading, and a card missing either is skipped (`incomplete-evidence`), not dropped. This is the
discipline `local_detect_ai_art`/`local_lands_identify`/`local_layout_class_cast` already follow
and the one `local_calculate_verdicts`' four Stage D readers do not; the frame chip is precisely
where getting it wrong bites, because `illus_anchor_fired` missing reads as `False`, which makes
`classify_frame_style` answer "modern" for a card it has no anchor evidence about at all. Gating on
`artist_ocr` is what stops this module manufacturing 9,006 false `Modern Border` votes.

NON-HUMAN-BACKED, NEVER RESOLVES ALONE: a single `VoteSource.OCR` vote can never itself resolve a
tag (`vote_consensus.resolve_weighted_consensus`'s human-backed hard gate). This calculator only
ever suggests. Verified empirically after every write by the management command via
`purge_machine_votes.verify_no_machine_only_resolutions`, reused rather than re-derived.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import QuerySet

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_fallback import (
    FRAME_STYLE_TO_TAG,
    FRAME_VOTE_CONFIDENCE,
    classify_frame_style,
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
from cardpicker.vote_write import purge_and_write_votes

FRAME_STYLE_CAST_ANONYMOUS_ID = "frame-style-cast-v1"
# RETIRED, do not resurrect (module docstring's "RETIRED BLEED-EDGE" section): the bleed branch this
# identity used to cast was superseded by `local_bleed_calculator` (bleed-calculator-cast-v1), the
# sole machine channel for `appropriate-bleed`. Kept declared and exported purely so HISTORICAL
# `CardTagVote`/`CardScanLog` rows under `bleed-edge-cast-v1` still read sensibly and still route
# correctly (retractable via `purge_machine_votes --run-id`). No code path writes a NEW row under it.
BLEED_EDGE_CAST_ANONYMOUS_ID = "bleed-edge-cast-v1"

# `collector_line_ocr` stores `collector_line_collector_number`; `artist_ocr` stores
# `illus_anchor_fired`. BOTH are required for a frame reading - see the module docstring's
# REQUIRED_EXTRACTOR_KEYS section for why a missing `artist_ocr` is the dangerous one.
FRAME_REQUIRED_EXTRACTOR_KEYS: tuple[str, ...] = ("collector_line_ocr", "artist_ocr")

# THIS CALCULATOR'S OWN SKIP VOCABULARY (the 2026-07-29 declaration convention,
# docs/reference/skip-reasons.md): every string written to `CardScanLog.skip_reason` is a
# module-level `*_SKIP_REASON` constant so the roster tether can enumerate it statically. Values
# are reused from the shared vocabulary; the prefix is deliberate, since the same strings are
# emitted by other calculators under a different `anonymous_id` and one shared constant would
# falsely imply one shared concept.
CHIP_NO_EVIDENCE_SKIP_REASON = "no-evidence"
CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON = "incomplete-evidence"
# Frame: neither signal fired (no collector number parsed AND no "Illus." anchor) - a genuine
# abstention, `classify_frame_style` returning None. (`ambiguous` used to also cover the bleed
# chip's "reading was not `trimmed`" case; that half of this module is retired - see the module
# docstring's "RETIRED BLEED-EDGE" section.)
CHIP_ABSTAINED_SKIP_REASON = "ambiguous"
# Defensive only: a frame class outside FRAME_STYLE_TO_TAG. `classify_frame_style`'s value space is
# closed ("old"/"modern"/None) so this is unreachable against the current taxonomy - exercised in
# tests via a monkeypatched classifier, kept for the same future-proofing reason
# `local_layout_class_cast.LAYOUT_CLASS_UNMAPPED_SKIP_REASON` is.
CHIP_UNMAPPED_SKIP_REASON = "unmapped-frame-class"

# Same convention as `LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS`/`AI_ART_RESCANNABLE_SKIP_REASONS`:
# both describe a transient "nothing to look at YET" state that a later Stage C pass can change.
# `ambiguous` and `unmapped-frame-class` are deliberately NOT here - both are genuine, repeatable
# conclusions about this content_hash's own stored evidence.
CHIP_RESCANNABLE_SKIP_REASONS = frozenset({CHIP_NO_EVIDENCE_SKIP_REASON, CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON})


@dataclass(frozen=True)
class AttributeChipVerdict:
    """Pure result of reading one card's current `ImageEvidence` - no DB write has happened yet
    (mirrors `LayoutClassVerdict`/`AiArtVerdict`'s own compute/persist split). The frame family
    either produces a `(tag_name, confidence)` pair or a skip reason; `None` on both sides means
    the frame chip was not attempted for this card at all (the bleed half this verdict used to
    carry is retired - see the module docstring's "RETIRED BLEED-EDGE" section)."""

    card_id: int
    frame_class: Optional[str] = None
    frame_tag_name: Optional[str] = None
    frame_skip_reason: Optional[str] = None
    normal_frame: Optional[bool] = None


def calculate_attribute_chip_verdict(card_id: int, evidence: ImageEvidence) -> AttributeChipVerdict:
    """
    The chip calculator. Pure function: no DB write, no image fetch, no re-classification beyond
    calling `local_fallback.classify_frame_style` on two already-stored fields.

    FRAME. `parsed_a_collector_number` is `bool(evidence.collector_line_collector_number)` - the
    field's `""` default is `image_evidence.py`'s own "ambiguous or not yet run" sentinel, and the
    `collector_line_ocr` gate above is what distinguishes it from "the extractor never ran".
    `illus_anchor_fired` is nullable; it is passed as `bool(...)` only AFTER the `artist_ocr` gate
    has confirmed the extractor ran, so a `None` reaching here means the extractor ran and found no
    anchor - a real negative, not an absence.

    NORMAL. A derived reading - whether the render is a normal modern frame (art edge is `framed`,
    not borderless full-art), computed at cast time from three already-stored signals rather than
    persisted: `classify_frame_style`'s era reading + `art_edge_class` + `layout_class`. True when
    `frame_class == "modern"` AND `art_edge_class == "framed"` AND `layout_class != "borderless"`;
    False when the era reads modern but the frame is extended-art or borderless; None when the era
    reading is not modern (an old frame is a different axis, not a non-normal one) or the frame
    chip was not attempted (skip reason set). The `layout_class == ""` sentinel excludes a
    not-yet-computed border reading from the `borderless` branch, so a missing layout never reads
    False.
    """
    frame_class: Optional[str] = None
    frame_tag_name: Optional[str] = None
    frame_skip_reason: Optional[str] = None
    normal_frame: Optional[bool] = None
    if any(key not in evidence.extractor_versions for key in FRAME_REQUIRED_EXTRACTOR_KEYS):
        frame_skip_reason = CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON
    else:
        frame_class = classify_frame_style(
            parsed_a_collector_number=bool(evidence.collector_line_collector_number),
            illus_anchor_fired=bool(evidence.illus_anchor_fired),
        )
        if frame_class is None:
            frame_skip_reason = CHIP_ABSTAINED_SKIP_REASON
        else:
            frame_tag_name = FRAME_STYLE_TO_TAG.get(frame_class)
            if frame_tag_name is None:
                frame_skip_reason = CHIP_UNMAPPED_SKIP_REASON

    if frame_class == "modern" and not frame_skip_reason:
        normal_frame = evidence.art_edge_class == "framed" and evidence.layout_class != "borderless"

    return AttributeChipVerdict(
        card_id=card_id,
        frame_class=frame_class,
        frame_tag_name=frame_tag_name,
        frame_skip_reason=frame_skip_reason,
        normal_frame=normal_frame,
    )


@dataclass
class AttributeChipCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    frame_votes_would_cast: int = 0
    frame_votes_written: int = 0
    votes_by_tag: dict[str, int] = field(default_factory=dict)
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, object]] = field(default_factory=list)

    # The bleed counters this result used to carry are gone with the retired bleed half (module
    # docstring's "RETIRED BLEED-EDGE" section); `votes_*` are the frame counts alone.
    @property
    def votes_would_cast(self) -> int:
        return self.frame_votes_would_cast

    @property
    def votes_written(self) -> int:
        return self.frame_votes_written


def _eligible_cards_queryset(anonymous_id: str, card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Cards this identity has neither voted on nor recorded a non-rescannable `CardScanLog` row
    for - the same idempotence pattern as `local_layout_class_cast._eligible_cards_queryset` and
    `local_detect_ai_art._eligible_cards_queryset`, parameterised by identity because the frame
    identity and the retired `BLEED_EDGE_CAST_ANONYMOUS_ID` (kept declared for historical rows,
    never written anymore - module docstring's "RETIRED BLEED-EDGE" section) share this helper.
    At most one tag is ever cast per card per identity, so a single `tag_votes__anonymous_id`
    exclude with no per-tag qualifier correctly covers "already handled".

    Deliberately unrestricted by `card_type`/`printing_tag_status` - a card's frame style is
    orthogonal to whether its printing has been identified, the same reasoning
    `local_layout_class_cast`/`local_detect_ai_art` give for their own chips.

    `card_ids` is pushed INTO the `CardScanLog` subquery as well as onto the outer query, per
    issue #469/#533: Django compiles `.filter(pk__in=<values_list qs>)` as an UNCORRELATED
    `IN (SELECT ...)`, so leaving it unscoped is a full pass over a 2.6M-row append-only table on
    every micro-batch. The `tag_votes__anonymous_id` exclusion needs no such push - Django compiles
    that one as a CORRELATED `NOT EXISTS`, which the outer scope bounds for free. Purely a cost
    narrowing: a scan-log row found outside `card_ids` could never survive the outer
    `.filter(pk__in=card_ids)` regardless."""
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(anonymous_id=anonymous_id).exclude(
        skip_reason__in=CHIP_RESCANNABLE_SKIP_REASONS
    )
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    queryset = (
        Card.objects.exclude(tag_votes__anonymous_id=anonymous_id)
        .exclude(pk__in=non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True))
        .distinct()
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def run_attribute_chip_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> AttributeChipCastResult:
    """
    Batch runner over every card with a CURRENT `ImageEvidence` row (`content_hash` matching the
    card's own live `content_phash` - `image_evidence.current_evidence_queryset`, the shared
    definition, never an inline copy). `dry_run=True` is the default, matching every other Stage 3+
    command's opt-in-to-write convention.

    ONE IDENTITY, ONE PASS. The frame-style pass runs under `FRAME_STYLE_CAST_ANONYMOUS_ID` alone.
    The module's second identity, `BLEED_EDGE_CAST_ANONYMOUS_ID`, is retired - its bleed branch
    used to be selected independently and unioned into this pass, and now no code path writes under
    it at all (module docstring's "RETIRED BLEED-EDGE" section); `bleed-calculator-cast-v1` in
    `local_bleed_calculator` is the sole machine channel for `appropriate-bleed`.

    GATE VERIFICATION lives in the management command, not here (matching `run_layout_class_cast`/
    `run_ai_art_detector`'s own split - the batch computation stays pure and testable).
    """
    run_id = run_id or generate_run_id()
    result = AttributeChipCastResult(dry_run=dry_run, run_id=run_id)

    required_tag_names = set(FRAME_STYLE_TO_TAG.values())
    tag_by_name = {t.name: t for t in Tag.objects.filter(name__in=required_tag_names)}
    missing_tags = sorted(required_tag_names - tag_by_name.keys())
    if missing_tags:
        raise RuntimeError(
            f"Tag(s) {missing_tags} do not exist yet - run `seed_attribute_tags`/`seed_default_tags` "
            "before this calculator."
        )

    frame_eligible_ids = set(
        _eligible_cards_queryset(FRAME_STYLE_CAST_ANONYMOUS_ID, card_ids=card_ids).values_list("pk", flat=True)
    )

    frame_votes: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    def _skip(card_id: int, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card_id, anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID, run_id=run_id, skip_reason=reason
                )
            )

    for card in Card.objects.filter(pk__in=frame_eligible_ids).distinct().iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = current_evidence_queryset(card).order_by("-updated_at").first()
        if evidence is None:
            _skip(card.pk, CHIP_NO_EVIDENCE_SKIP_REASON)
            continue

        result.cards_considered += 1
        verdict = calculate_attribute_chip_verdict(card.pk, evidence)

        if verdict.frame_tag_name is not None:
            result.frame_votes_would_cast += 1
            result.votes_by_tag[verdict.frame_tag_name] = result.votes_by_tag.get(verdict.frame_tag_name, 0) + 1
            if len(result.audit) < audit_sample_size:
                result.audit.append(
                    {"card_id": card.pk, "frame_class": verdict.frame_class, "tag": verdict.frame_tag_name}
                )
            if not dry_run:
                frame_votes.append(
                    CardTagVote(
                        card_id=card.pk,
                        tag=tag_by_name[verdict.frame_tag_name],
                        polarity=VotePolarity.APPLY,
                        anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID,
                        source=VoteSource.OCR,
                        confidence=FRAME_VOTE_CONFIDENCE,
                        run_id=run_id,
                    )
                )
        else:
            assert verdict.frame_skip_reason is not None
            _skip(card.pk, verdict.frame_skip_reason)

    if not dry_run:
        # `purge_and_write_votes` scopes its purge by `anonymous_id`; this pass writes one
        # identity, so one call is correct (the retired bleed identity is never written here).
        # `ignore_conflicts` is belt-and-suspenders against the (card, tag, anonymous_id)
        # constraint - the eligibility query is this module's real idempotence, so a conflict could
        # only come from two concurrent invocations racing (the same `_run_stage_d` concurrency
        # `local_calculate_verdicts`' `_split_new_printing_tag_votes` docstring documents).
        purge_and_write_votes(
            CardTagVote,
            frame_votes,
            anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID,
            target_field="card_id",
            ignore_conflicts=True,
        )
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.frame_votes_written = len(frame_votes)

        touched_card_ids = {vote.card_id for vote in frame_votes}
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_tag_votes(card)

    return result


__all__ = [
    "FRAME_STYLE_CAST_ANONYMOUS_ID",
    # Retired, not deleted: no code writes under it anymore, but keeping it declared keeps
    # HISTORICAL rows addressable and keeps the identity on the docs_lint calculator roster.
    "BLEED_EDGE_CAST_ANONYMOUS_ID",
    "FRAME_REQUIRED_EXTRACTOR_KEYS",
    "CHIP_RESCANNABLE_SKIP_REASONS",
    "CHIP_NO_EVIDENCE_SKIP_REASON",
    "CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON",
    "CHIP_ABSTAINED_SKIP_REASON",
    "CHIP_UNMAPPED_SKIP_REASON",
    "AttributeChipVerdict",
    "calculate_attribute_chip_verdict",
    "AttributeChipCastResult",
    "run_attribute_chip_cast",
]
