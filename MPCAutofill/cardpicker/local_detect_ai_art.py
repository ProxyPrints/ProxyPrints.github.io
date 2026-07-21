"""
AI-art marker detector (public issue #261) - a Stage D-style calculator (see
`cardpicker.local_calculate_verdicts`'s module docstring for the shared "harvest-calculate
pipeline" framing this extends) that scans Stage C's already-persisted `ImageEvidence` OCR
fields (`artist_ocr_name`, `legal_line_raw_text`, `collector_line_raw_text`) for known AI-image-
generator marker strings and casts `CardTagVote` votes for the pre-existing "AI-Generated" tag
(`cardpicker.default_tags.DEFAULT_TAGS`) through the EXISTING, unmodified vote-consensus
machinery (`cardpicker.tag_consensus`/`cardpicker.vote_consensus`, both PROTECTED CORE per
`docs/upstreaming/license-provenance.md` SS2 - imported and called, never re-derived). No image
fetch, no OCR run here - this is a pure read over already-stored evidence, the same "reuse
Stage C's persisted signals" discipline `local_calculate_verdicts.py`'s join-key calculator
already established.

Same "funnel to human review, never resolve alone" discipline as every other machine engine in
this codebase: a single vote at `VoteSource.OCR` weight can never itself resolve a tag
(`resolve_weighted_consensus`'s own human-backed hard gate, `vote_consensus.py` - no volume of
non-human-backed votes can ever resolve consensus on their own, checked BEFORE any privileged-
gate logic even applies). See `run_ai_art_detector`'s own docstring for how this module verifies
that gate empirically after every write, reusing `purge_machine_votes.verify_no_machine_only_
resolutions` rather than re-deriving an equivalent check.

SENSITIVE-TAG DECISION (issue #261's own open question, resolved in PR #263, THEN REVERSED by
owner decision 2026-07-21): "AI-Generated" briefly carried an additional `TagModerationClass.
SENSITIVE` marking (see `cardpicker.sensitive_tags`) - a second, independent gate requiring a
privileged (moderator) co-sign before ANY crowd consensus on this tag could resolve at all,
mirroring `sensitive_tags.py`'s own `"appropriate-bleed"` entry. The owner reverted that one
aspect (verbatim: "ordinary human votes is fine for AI I think. or at least not moderator eyes.
they will go contested if there is not an immediate human consensus that is the system working
as intended") - so this tag is now plain `TagModerationClass.STANDARD` again, exactly as it was
seeded (as the model default) via `cardpicker.default_tags.DEFAULT_TAGS`'s pre-existing
`("AI-Generated", ["Midjourney"], None)` entry, which exists for a DIFFERENT, orthogonal purpose
- `cardpicker.tags.Tags`' filename-bracket matcher (e.g. a source file literally named
`"... [Midjourney].png"`) applies it directly to `Card.tags` at import time, bypassing the vote
system entirely, untouched by any of this. The shared human-backed gate below (a lone machine
vote can never resolve ANY tag alone, regardless of moderation_class) is unaffected and remains
the only gate on this tag: an ordinary confident crowd consensus now resolves it same as any
other STANDARD tag, and a genuinely contested crowd stays CONTESTED/UNRESOLVED rather than
silently resolving wrong - the system working as intended, per the owner's own framing above.
A future privileged-co-sign requirement for this specific tag is tracked as a possible follow-up,
not built here - see `docs/features/moderation.md`'s AI-Generated paragraph. `sensitive_tags.
FORMERLY_SENSITIVE_TAG_NAMES` lets `seed_sensitive_tags` sync this downgrade on any instance that
already ran the #263-era seed and has the row stuck at SENSITIVE.

OWNER AMENDMENT (2026-07-21, issue #261): generator-SITE URLs (e.g. CardConjurer.com) are
EXCLUDED from the marker list - they identify a rendering/compositing TOOL usable with ordinary
human-drawn art, not AI provenance. Including them would false-flag any human artist whose proxy
happened to be built with one of these tools, which is exactly the false-positive failure mode
this feature has to guard hardest against. Markers below are restricted to actual generator/
model NAMES and explicit AI-attribution phrases only - see `AI_GENERATOR_MARKERS`'s own comment
for the one further judgment call made within that constraint.

POSITIVE-DETECTION ONLY (this module's own scope decision, matching the issue's own framing):
a marker absence proves nothing (many genuine AI customs carry no marker at all, and plenty of
genuine human art crops OCR badly) - so this calculator only ever casts an APPLY vote on a real
marker hit; it never casts a `NOT_APPLICABLE` vote or an `is_no_match`-style negative conclusion.
A non-hit is recorded as a `CardScanLog(skip_reason="no-marker-hit")` row purely so the same
card's identical stored evidence isn't re-scanned by every future invocation (the same
resume/idempotence mechanism `local_identify_printing_tags.RESCANNABLE_SKIP_REASONS`/
`local_calculate_verdicts.JOIN_KEY_RESCANNABLE_SKIP_REASONS` already establish) - it carries no
"this card's art is human" assertion whatsoever.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from django.db.models import QuerySet

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

# Own anonymous_id (distinct from every other engine's - see local_identify_printing_tags.py's
# OCR_ANONYMOUS_ID/PHASH_ANONYMOUS_ID comment for why each engine gets its own: independently
# purgeable/re-runnable via the existing purge_machine_votes --run-id mechanism, and the
# (card, tag, anonymous_id) uniqueness constraint on CardTagVote is what makes "skip a card
# already voted by this identity" a plain query rather than bespoke bookkeeping).
AI_ART_ANONYMOUS_ID = "ai-art-detector-v1"

# The pre-existing tag name (cardpicker.default_tags.DEFAULT_TAGS) this calculator votes on -
# duplicated as a literal (not imported from default_tags.py) matching DEDUCTIVE_BACKFILL_
# ANONYMOUS_ID's own "avoid a hard import-time dependency between sibling modules over one
# constant string" precedent in local_identify_printing_tags.py.
AI_GENERATED_TAG_NAME = "AI-Generated"

# The three ImageEvidence OCR fields this calculator scans (issue #261's own spec) - every one
# already a plain OCR-extracted TextField/CharField, no candidate-matching semantics, no crop
# pixels (CLAUDE.md's "Governing premise" - this module never touches an image, only text
# Stage C already extracted and persisted).
AI_ART_EVIDENCE_FIELDS: tuple[str, ...] = (
    "artist_ocr_name",
    "legal_line_raw_text",
    "collector_line_raw_text",
)

# The extractor_versions keys that must ALL be present before a "no-marker-hit" conclusion is
# trusted as genuine (see run_ai_art_detector's own "incomplete-evidence" handling below) - one
# per AI_ART_EVIDENCE_FIELDS entry (collector_line_ocr populates collector_line_raw_text,
# artist_ocr populates artist_ocr_name, legal_line populates legal_line_raw_text - see
# image_evidence.py's own extractor_versions[...] = ... call sites). Requiring all three (not
# just "the evidence row exists at all") matters because ImageEvidence rows are populated
# incrementally, field-group by field-group, across separate extraction passes over the SAME
# (card, content_hash) row (its own "computed-once-forever" design) - scanning a row before every
# relevant extractor has run risks a permanent, wrong "no-marker-hit" conclusion for a field that
# simply hadn't been written yet, not one that was written and found clean.
REQUIRED_EXTRACTOR_KEYS: tuple[str, ...] = ("collector_line_ocr", "artist_ocr", "legal_line")

# Skip reasons that stay eligible for re-selection on a future invocation (same convention as
# local_identify_printing_tags.RESCANNABLE_SKIP_REASONS/local_calculate_verdicts.JOIN_KEY_
# RESCANNABLE_SKIP_REASONS) - both describe a transient "nothing to look at YET" state, not a
# genuine conclusion against the card's actual stored evidence. "no-marker-hit" is deliberately
# NOT here: it's evidence looked at and found clean AGAINST THE CURRENT MARKER LIST - a genuine,
# repeatable conclusion for this content_hash, same "permanent unless the marker list itself
# changes" reasoning "ambiguous"/"no-text" get elsewhere. A future marker-list update naturally
# gets a fresh look by simply purging/re-running against the updated list (curated-list ownership
# is issue #261's own still-open scoping question, not resolved here).
AI_ART_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence", "incomplete-evidence"})

# The minimum normalized marker length (see normalize_ocr_text) this module tolerates a single-
# character OCR substitution for (module docstring's "OCR-tolerant matching" requirement) - a
# shorter marker (e.g. "sdxl", "gemini", "imagen") tolerating even one substitution risks matching
# too much incidental text to be trustworthy; longer markers have enough length that one flipped
# character is real OCR noise, not a coincidence. Applied per-marker (see find_marker_hits), not
# globally - `AI_GENERATOR_MARKERS`'s own comment lists which markers this applies to.
FUZZY_MIN_MARKER_LENGTH = 8

# Confidence tiers (informational only - resolve_weighted_consensus/resolve_tag both weight
# strictly by `source`, never `confidence`; see JOIN_KEY_CONFIDENCE_BOTH's own comment in
# local_calculate_verdicts.py for the same point made there). A hit corroborated across more than
# one of the three evidence fields (e.g. the same run's artist line AND legal line both carrying
# a marker) is stronger evidence than a single field alone, mirroring local_identify_printing_
# tags.py's FALLBACK_CONFIDENCE_SINGLE_EVIDENCE/MULTI_EVIDENCE two-tier precedent.
AI_ART_CONFIDENCE_SINGLE_FIELD = 0.6
AI_ART_CONFIDENCE_MULTI_FIELD = 0.75

# The curated marker list (issue #261's own open scoping question on ownership/updates - NOT
# resolved here, this is the initial seed only). Restricted to actual generator/model names and
# explicit AI-attribution phrases per the OWNER AMENDMENT above - no generator-SITE/tool name
# appears here (CardConjurer or otherwise).
#
# ONE further judgment call made within the owner's own list (2026-07-21, this PR): "Firefly" is
# seeded here as "Adobe Firefly" rather than the bare word - the same false-positive reasoning the
# owner already applied to generator-site exclusion applies equally to a bare, common English
# word/plausible human-artist pseudonym appearing incidentally in the artist-credit OCR line;
# "Adobe Firefly" is the generator's actual product name and carries the same detection power
# with materially less collision risk. Flagged explicitly in the PR description for the owner to
# override if a bare "Firefly" is genuinely wanted. "Leonardo AI" (not bare "Leonardo", a common
# human given name) was already disambiguated this same way in the owner's own list - this is the
# same principle applied consistently to the one remaining ambiguous entry.
AI_GENERATOR_MARKERS: tuple[str, ...] = (
    "Midjourney",
    "DALL-E",
    "Stable Diffusion",
    "SDXL",
    "Gemini",
    "Imagen",
    "Adobe Firefly",
    "Leonardo AI",
    "NightCafe",
    "Bing Image Creator",
    "AI art",
    "AI generated",
)


def normalize_ocr_text(text: str) -> str:
    """Lowercase, then strip everything that isn't a-z/0-9 - the same normalization applied to
    both the OCR'd evidence text and every marker string before comparison, so punctuation/
    whitespace noise (an OCR-dropped space, a stray period) never prevents an otherwise-real
    match. Deliberately simple (no unicode folding/accent-stripping) - every marker string here
    is plain ASCII, and over-normalizing raw OCR text beyond this risks collapsing genuinely
    different words together."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _fuzzy_substring_match(haystack: str, needle: str, max_substitutions: int = 1) -> bool:
    """Sliding-window substring match tolerant of up to `max_substitutions` single-character
    OCR misreads (e.g. a 'o' misread as '0', an 'l' misread as '1') - SUBSTITUTIONS only, not
    insertions/deletions, which would need a real edit-distance (Levenshtein) scan across every
    window instead of a fixed-width compare. Documented limitation, not attempted here: a cheap,
    fixed-width sliding compare is O(len(haystack) * len(needle)) per marker, trivially cheap
    against the short OCR crops this module reads (a legal line, a collector line, an artist
    credit - never a full page of text); a true edit-distance scan would cost more for a case
    real observed OCR noise (tonight's own fixture strings) doesn't actually need."""
    haystack_len, needle_len = len(haystack), len(needle)
    if needle_len > haystack_len:
        return False
    for start in range(haystack_len - needle_len + 1):
        mismatches = 0
        window = haystack[start : start + needle_len]
        for a, b in zip(window, needle):
            if a != b:
                mismatches += 1
                if mismatches > max_substitutions:
                    break
        if mismatches <= max_substitutions:
            return True
    return False


def find_marker_hits(raw_text: str) -> list[str]:
    """Returns every marker (original, non-normalized string, for readable audit output) found in
    `raw_text` - an exact normalized-substring match first (cheap, and already sufficient for
    every real OCR sample observed so far - e.g. "mtgenbmidjourney" contains "midjourney" as an
    exact substring once normalized), falling back to `_fuzzy_substring_match` ONLY for markers at
    least `FUZZY_MIN_MARKER_LENGTH` characters long that didn't already match exactly."""
    if not raw_text:
        return []
    normalized_text = normalize_ocr_text(raw_text)
    if not normalized_text:
        return []
    hits = []
    for marker in AI_GENERATOR_MARKERS:
        normalized_marker = normalize_ocr_text(marker)
        if not normalized_marker:
            continue
        if normalized_marker in normalized_text:
            hits.append(marker)
        elif len(normalized_marker) >= FUZZY_MIN_MARKER_LENGTH and _fuzzy_substring_match(
            normalized_text, normalized_marker
        ):
            hits.append(marker)
    return hits


@dataclass(frozen=True)
class AiArtVerdict:
    """Pure result of scanning one card's current ImageEvidence for AI-generator markers - no DB
    write has happened yet (mirrors JoinKeyVerdict's own compute/persist split). `matched_markers`
    maps each evidence field that produced a hit to the marker(s) found in it; empty means no hit
    at all (see `is_hit`)."""

    card_id: int
    matched_markers: dict[str, list[str]] = field(default_factory=dict)
    confidence: Optional[float] = None
    detail: str = ""

    @property
    def is_hit(self) -> bool:
        return bool(self.matched_markers)


def calculate_ai_art_verdict(card_id: int, evidence: ImageEvidence) -> AiArtVerdict:
    """The AI-art marker calculator. Pure function, no DB write, no image fetch, no re-OCR -
    reads only the three already-persisted `AI_ART_EVIDENCE_FIELDS` off `evidence`. Positive-
    detection only (module docstring): returns a no-hit `AiArtVerdict` (empty `matched_markers`)
    whenever nothing matches, never a negative/no-match conclusion of any kind."""
    matched: dict[str, list[str]] = {}
    for field_name in AI_ART_EVIDENCE_FIELDS:
        raw_text = getattr(evidence, field_name, "") or ""
        hits = find_marker_hits(raw_text)
        if hits:
            matched[field_name] = hits

    if not matched:
        return AiArtVerdict(card_id=card_id)

    confidence = AI_ART_CONFIDENCE_MULTI_FIELD if len(matched) >= 2 else AI_ART_CONFIDENCE_SINGLE_FIELD
    detail = "; ".join(f"{field_name}={','.join(markers)}" for field_name, markers in matched.items())
    return AiArtVerdict(card_id=card_id, matched_markers=matched, confidence=confidence, detail=detail)


@dataclass
class AiArtDetectorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, mirroring JoinKeyCalculatorResult/PilotResult's own "up to N, for the
    # report" convention elsewhere in this codebase.
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(tag: Tag) -> "QuerySet[Card]":
    """Every card NOT already voted on by this calculator's own anonymous_id for the AI-Generated
    tag specifically (the (card, tag, anonymous_id) uniqueness constraint on CardTagVote is what
    makes this a plain exclude - a single filter() call with both conditions applies to the SAME
    related row, unlike the multi-call Q-negation pitfall local_identify_printing_tags.py's own
    _eligible_base_queryset docstring warns about), and not already carrying a non-rescannable
    scan-log row from a prior invocation (same idempotence pattern as every other engine).

    Deliberately unrestricted by `card_type`/`printing_tag_status` - AI-art detection is
    orthogonal to printing identification (a token or an unresolved card's art can be just as
    plausibly AI-generated as any other card's), unlike local_identify_printing_tags.py's own
    eligibility, which specifically needs an unresolved printing to vote on."""
    non_rescannable_scanned_card_ids = (
        CardScanLog.objects.filter(anonymous_id=AI_ART_ANONYMOUS_ID)
        .exclude(skip_reason__in=AI_ART_RESCANNABLE_SKIP_REASONS)
        .values_list("card_id", flat=True)
    )
    return (
        Card.objects.exclude(tag_votes__anonymous_id=AI_ART_ANONYMOUS_ID, tag_votes__tag=tag)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
    )


def run_ai_art_detector(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
) -> AiArtDetectorResult:
    """Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row (its
    `content_hash` matching the card's own live `content_phash` - an evidence row from a prior
    image version is never trusted for a card whose upload has since changed, same convention as
    `local_calculate_verdicts.run_join_key_calculator`) that has completed all of
    `REQUIRED_EXTRACTOR_KEYS`. `dry_run=True` (the default, matching every other Stage 3+
    command's own opt-in-to-write convention) computes and counts everything without writing any
    `CardTagVote`/`CardScanLog` row.

    GATE VERIFICATION: this function itself casts no gate check (matching `run_join_key_
    calculator`'s own split - the batch computation stays pure/testable, the management command
    layers the gate check + `CommandError` on top, reusing `cardpicker.management.commands.
    purge_machine_votes.verify_no_machine_only_resolutions` rather than re-deriving an equivalent
    "is any touched card resolved on machine-only weight" check - see that function's own
    docstring for why "resolved to APPLY with only machine-sourced survivors" is the correct
    invariant, not "never resolves at all"). "AI-Generated" is plain `TagModerationClass.
    STANDARD` (see the module docstring's SENSITIVE-TAG DECISION section) - the shared
    human-backed gate is this tag's only gate, same as any other STANDARD tag.
    """
    run_id = run_id or generate_run_id()
    result = AiArtDetectorResult(dry_run=dry_run, run_id=run_id)

    tag = Tag.objects.filter(name=AI_GENERATED_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(
            f"Tag {AI_GENERATED_TAG_NAME!r} does not exist yet - run `seed_default_tags` " "before this calculator."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    for card in _eligible_cards_queryset(tag).iterator(chunk_size=chunk_size):
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
                        card_id=card.pk, anonymous_id=AI_ART_ANONYMOUS_ID, run_id=run_id, skip_reason="no-evidence"
                    )
                )
            continue

        if any(key not in evidence.extractor_versions for key in REQUIRED_EXTRACTOR_KEYS):
            result.skip_counts["incomplete-evidence"] = result.skip_counts.get("incomplete-evidence", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=AI_ART_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason="incomplete-evidence",
                    )
                )
            continue

        result.cards_considered += 1
        verdict = calculate_ai_art_verdict(card.pk, evidence)

        if not verdict.is_hit:
            result.skip_counts["no-marker-hit"] = result.skip_counts.get("no-marker-hit", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk, anonymous_id=AI_ART_ANONYMOUS_ID, run_id=run_id, skip_reason="no-marker-hit"
                    )
                )
            continue

        result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "detail": verdict.detail, "confidence": verdict.confidence})

        if not dry_run:
            votes_batch.append(
                CardTagVote(
                    card_id=card.pk,
                    tag=tag,
                    polarity=VotePolarity.APPLY,
                    anonymous_id=AI_ART_ANONYMOUS_ID,
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
    "AI_ART_ANONYMOUS_ID",
    "AI_GENERATED_TAG_NAME",
    "AI_ART_EVIDENCE_FIELDS",
    "REQUIRED_EXTRACTOR_KEYS",
    "AI_ART_RESCANNABLE_SKIP_REASONS",
    "FUZZY_MIN_MARKER_LENGTH",
    "AI_ART_CONFIDENCE_SINGLE_FIELD",
    "AI_ART_CONFIDENCE_MULTI_FIELD",
    "AI_GENERATOR_MARKERS",
    "normalize_ocr_text",
    "find_marker_hits",
    "AiArtVerdict",
    "calculate_ai_art_verdict",
    "AiArtDetectorResult",
    "run_ai_art_detector",
]
