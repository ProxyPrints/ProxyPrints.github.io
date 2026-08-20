"""
Filename-declaration caster: proxy uploaders name their own renders, and those names routinely
declare the frame treatment ("Snapcaster Mage Extended.png", "Forest (Borderless Kozyndan).png").
Those declarations map 1:1 onto attribute chips that already exist
(`cardpicker.attribute_tags.ATTRIBUTE_CHIP_TAG_NAMES`), and are cast here as an independent
evidence channel that opens no socket and inspects no pixel - the parser reads only `Card.name`,
already in the database from ingest.

Measured against production (235,912 cards, 2026-08-19): 20,629 distinct cards across 109 distinct
sources declare a treatment this way, three chips (Full Art, Etched, Future Frame) with no other
machine coverage at all. Corroboration that the signal is real: on the Extended chip, the stored
`ImageEvidence.art_edge_class` pixel classifier independently reads `extended` on 90.7% of the
cards whose filename declares it, holding across a dozen sources individually - two channels
sharing no inputs agreeing that often is what makes the filename channel worth casting.

`source=VoteSource.DEDUCTION`, NOT `OCR`. The enum's own docstring draws the line at image
inspection: DEDUCTION is "pure logical inference from already-trusted structured data ... zero
image inspection", OCR "covers everything ... that actually looks at the card image". Filename
parsing inspects no pixels - it reads the same `Card.name` field a card's `canonical_card` is
already inferred from at ingest by parsing collector number and set code out of that same
filename. Both sources carry the identical `PRINTING_TAG_MACHINE_WEIGHT`
(`vote_consensus._SOURCE_WEIGHTS`), so this is a mechanism label, not an influence decision.

POSITIVE DECLARATIONS ONLY. Every match casts `VotePolarity.APPLY`; an absent keyword is never
read as a claim that the treatment does NOT apply (silence is not a negation). The one exception
measured in production - a filename literally saying "No Black Border" - is a genuine negative
CLAIM, not mere silence, and is guarded against explicitly (`_is_negated`) rather than cast as a
false positive.

NO SHORT-CIRCUITING. This channel never gates, skips, or suppresses any pixel-based calculator,
and is never itself made conditional on one - see `stage_e_dispatch._run_attribute_chip_casters`'
own docstring for why chip casters are wired independently of each other. The two channels'
DISAGREEMENT is the valuable signal (90.7% agreement on Extended means the remaining 9.3% is
exactly the population worth routing to a human); a design where either silenced the other would
spend that signal to save compute instead.

KEYWORD VOCABULARY, refined against real names (read-only production queries, 2026-08-19) rather
than shipped as originally specified:

  - "Etched" collides with three real card names that begin with the word ("Etched Champion",
    "Etched Oracle", "Etched Monstrosity" - Scars of Mirrodin block) - 21+ rows. The keyword
    itself is otherwise safe (`\\betched\\b` does not fire inside "Wretched", which has no word
    boundary before its embedded "etched"), so the fix is a negative lookahead on those three
    words rather than dropping the keyword.
  - "future sight" was measured as ambiguous rather than refined away cleanly: of 24 rows
    containing that phrase, only one ("...(Future Sight Frame)") was an actual treatment
    declaration - the rest are the SET's own name in an uploader's parenthetical annotation
    ("(Future Sight)", "(Future Sight CMM Art)"), which says nothing about this specific card's
    border. Also measured: 132 cards carry a bare "[Future]"/"[Future2]" set-annotation bracket,
    confirming the set-name reading is the common case, not the exception. DROPPED entirely - the
    false-positive rate this specific phrase would introduce (roughly 5x the true signal) is
    exactly the "material false rate, drop it" case. "future frame" (0 hits today, kept as a
    forward-compatible pattern) and "future shift(ed)" (19 genuine rows, all suffixed
    "(Futureshifted)") are unambiguous and kept.
  - "Modern Border" has deliberately no keyword: "modern" is the unmarked default frame, so a
    filename has nothing distinguishing to declare for it. Kept as an explicit `None` entry in
    `FILENAME_DECLARATION_PATTERNS` (not simply omitted) so a test can assert every
    `ATTRIBUTE_CHIP_TAG_NAMES` member is accounted for - the "cannot silently go unsupported"
    requirement covers "we looked at this chip and decided against it" as much as "we forgot it".
  - "full art"/"full-art" alone measured only 209 of the 804-row population: 638 rows spell it
    "Fullart", no separator at all. Widened to an OPTIONAL separator (matching "Future Frame"'s
    own "Futureshifted" shape) rather than left as two rigid phrasings - the fix moved the count
    from 209 to exactly 804, confirming no other spelling remains uncounted.
  - No other measured collision was found for Extended/Showcase/Full Art/Borderless/the three
    border-colour keywords/Old Border - word-boundary matching alone (`\\bextended\\b` etc.)
    already excludes the concatenated-identifier and compound-word near-misses found in
    production ("AltExtended", "Retrofitter Foundry", "ArtShowcase", "Gold Borderless").

MUTUALLY-EXCLUSIVE AXIS: Black Border/White Border/Silver Border/Borderless
(`BORDER_COLOR_AXIS_TAG_NAMES`) are one card's border colour and cannot all be true at once. A
filename matching two or more is self-contradictory - abstain on the WHOLE axis for that card
(cast none of them) and record `BORDER_AXIS_CONTRADICTION_SKIP_REASON`, rather than guessing which
one the uploader meant. Zero such contradictions were found in production at measurement time;
the guard exists for the case that does turn up. Treatment chips (Extended/Showcase/Full
Art/Etched) and the frame-era chips (Old Border/Future Frame) are NOT mutually exclusive with
each other or with the border-colour axis - a card can genuinely be several at once (e.g. an
Extended, Borderless card is a real combination), so every non-axis match is cast independently.

MULTI-VOTE SHAPE: unlike `local_layout_class_cast`/`local_attribute_chip_cast` (at most one tag
per card per identity), this caster can cast several tags for the same card in the same pass. The
eligibility query still only needs "has this identity touched this card at all" (any existing
`tag_votes__anonymous_id` row, or any `CardScanLog` row from this identity) to be correct: a card
that already has SOME votes from a prior pass is never revisited to look for more, because
`Card.name` never changes after ingest - there is nothing a later pass could find that this one
did not already see.

NEVER RESOLVES ALONE: same discipline as every other machine caster in this codebase - a single
`VoteSource.DEDUCTION` vote can never itself resolve a tag
(`vote_consensus.resolve_weighted_consensus`'s human-backed hard gate). This module only ever
suggests.
"""

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import QuerySet

from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.vote_write import purge_and_write_votes

FILENAME_DECLARATION_CAST_ANONYMOUS_ID = "filename-declaration-cast-v1"

# Heuristic tier, matching local_fallback.BORDER_ATTRIBUTE_VOTE_CONFIDENCE's own reasoning: a
# direct claim by the person who made the upload about their own upload, corroborated at 90.7%
# by an independent pixel channel on the one chip that has one - not the ground-truth tier
# (that one is reserved for a matched printing's own Scryfall metadata, which this module never
# has access to; see local_fallback.py's own GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE docstring),
# but no weaker than the module docstring's other heuristic casters.
FILENAME_DECLARATION_VOTE_CONFIDENCE = 0.75

# One card's border colour is a single fact - these four are mutually exclusive with each other
# (module docstring's MUTUALLY-EXCLUSIVE AXIS section). Not exclusive with anything outside this
# set.
BORDER_COLOR_AXIS_TAG_NAMES: frozenset[str] = frozenset({"Black Border", "White Border", "Silver Border", "Borderless"})

# A keyword immediately preceded by one of these words is a NEGATIVE claim ("No Black Border"),
# not a declaration - measured once in production (module docstring's KEYWORD VOCABULARY
# section). Checked against every keyword uniformly, not just the border-colour axis, since the
# "positive declarations only" principle is general.
_NEGATION_PREFIX = re.compile(r"\b(?:no|not|without)\s*$", re.IGNORECASE)

# tag_name -> compiled pattern, or None for a chip this module deliberately never casts
# ("Modern Border" - see module docstring's KEYWORD VOCABULARY section for why it is `None`
# rather than simply absent). Keys are checked against `attribute_tags.ATTRIBUTE_CHIP_TAG_NAMES`
# by test, not by a module-level assert (assertions can be stripped by `-O`), so a new chip added
# to that list without a corresponding entry here fails loudly in CI rather than silently.
FILENAME_DECLARATION_PATTERNS: dict[str, Optional["re.Pattern[str]"]] = {
    # Separator is optional - "Fullart" (638 of the 804 production rows) has none, same shape
    # as Future Frame's "Futureshifted" below.
    "Full Art": re.compile(r"\bfull[\s-]?art\b", re.IGNORECASE),
    "Borderless": re.compile(r"\bborderless\b", re.IGNORECASE),
    "Showcase": re.compile(r"\bshowcase\b", re.IGNORECASE),
    "Extended": re.compile(r"\bextended\b", re.IGNORECASE),
    # Negative lookahead excludes the three real Scars-of-Mirrodin card names that begin with
    # this word (module docstring's KEYWORD VOCABULARY section) without dropping the keyword.
    "Etched": re.compile(r"\betched\b(?!\s+(?:champion|oracle|monstrosity)\b)", re.IGNORECASE),
    # "Bordered" (past participle - "Classic Black Bordered") is as common in production as
    # "Border", so both are matched.
    "Black Border": re.compile(r"\bblack[\s-]border(?:ed)?\b", re.IGNORECASE),
    "White Border": re.compile(r"\bwhite[\s-]border(?:ed)?\b", re.IGNORECASE),
    "Silver Border": re.compile(r"\bsilver[\s-]border(?:ed)?\b", re.IGNORECASE),
    "Old Border": re.compile(r"\b(?:retro|old[\s-](?:frame|border(?:ed)?))\b", re.IGNORECASE),
    # Deliberately unsupported - "modern" is the unmarked default frame, nothing to key on.
    "Modern Border": None,
    # "future sight" dropped (module docstring's KEYWORD VOCABULARY section) - it reads the SET
    # name far more often than the treatment. "future frame" kept for forward compatibility
    # despite zero production hits at measurement time; it can only ever help, never collide.
    # The separator is optional - "Futureshifted" (all 19 measured production rows) has none.
    "Future Frame": re.compile(r"\bfuture[\s-]?(?:shift(?:ed)?|frame)\b", re.IGNORECASE),
}

NO_DECLARATION_SKIP_REASON = "no-declaration"
BORDER_AXIS_CONTRADICTION_SKIP_REASON = "border-axis-contradiction"

# `Card.name` is immutable after ingest, so every skip this module writes is a genuine, permanent
# conclusion about that name - never "nothing to look at yet". Empty rather than omitted, for
# interface parity with the sibling casters' own `*_RESCANNABLE_SKIP_REASONS`.
FILENAME_DECLARATION_RESCANNABLE_SKIP_REASONS: frozenset[str] = frozenset()


def _is_negated(name: str, match: "re.Match[str]") -> bool:
    """True when the text immediately before `match` ends in "no"/"not"/"without" - see the
    module docstring's KEYWORD VOCABULARY section and `_NEGATION_PREFIX`'s own comment."""
    return _NEGATION_PREFIX.search(name[: match.start()]) is not None


@dataclass(frozen=True)
class FilenameDeclarationVerdict:
    """Pure result of parsing one card's `name` - no DB write has happened yet (mirrors every
    other calculator's own compute/persist split). `cast_tag_names` already excludes the whole
    border-colour axis when `axis_contradiction` is True - callers never need to re-apply that
    rule themselves."""

    card_id: int
    cast_tag_names: frozenset[str] = frozenset()
    axis_contradiction: bool = False


def calculate_filename_declaration_verdict(card_id: int, name: str) -> FilenameDeclarationVerdict:
    """The parser. Pure function: no DB write, no image fetch, no network - reads only the `name`
    string passed in. Every keyword is checked independently (a card can match several); the only
    interaction between keywords is the border-colour axis exclusivity check (module docstring's
    MUTUALLY-EXCLUSIVE AXIS section)."""
    matched: dict[str, "re.Match[str]"] = {}
    for tag_name, pattern in FILENAME_DECLARATION_PATTERNS.items():
        if pattern is None:
            continue
        match = pattern.search(name)
        if match is not None and not _is_negated(name, match):
            matched[tag_name] = match

    axis_matches = set(matched) & BORDER_COLOR_AXIS_TAG_NAMES
    axis_contradiction = len(axis_matches) > 1
    cast_tag_names = frozenset(matched) - (BORDER_COLOR_AXIS_TAG_NAMES if axis_contradiction else frozenset())

    return FilenameDeclarationVerdict(
        card_id=card_id, cast_tag_names=cast_tag_names, axis_contradiction=axis_contradiction
    )


@dataclass
class FilenameDeclarationCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    cards_with_declarations: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    votes_by_tag: dict[str, int] = field(default_factory=dict)
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Cards this identity has neither voted on (any tag - module docstring's MULTI-VOTE SHAPE
    section explains why a single unqualified exclude is still correct here) nor recorded a
    `CardScanLog` row for. Same idempotence pattern and same `card_ids`-pushed-into-both-the-
    outer-query-and-the-subquery shape as `local_layout_class_cast`/`local_attribute_chip_cast`
    (issue #469/#533's UNCORRELATED-vs-CORRELATED subquery cost distinction - see either
    module's own docstring for the full reasoning).

    Deliberately unrestricted by `card_type`/`printing_tag_status`/`content_phash` - a card's
    filename is present and immutable from the moment it is created, independent of whether it
    has ever been fetched, processed by Stage C, or had its printing resolved. This is the one
    channel in this family that needs no `ImageEvidence` row at all.
    """
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(
        anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID
    ).exclude(skip_reason__in=FILENAME_DECLARATION_RESCANNABLE_SKIP_REASONS)
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    queryset = (
        Card.objects.exclude(tag_votes__anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True))
        .distinct()
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def run_filename_declaration_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> FilenameDeclarationCastResult:
    """
    Batch runner over every currently-eligible card. `dry_run=True` is the default, matching
    every other Stage 3+ command's own opt-in-to-write convention. No `ImageEvidence` lookup, no
    `content_phash` check, no image fetch anywhere in this function - the only input is
    `Card.name`, already in the database for every card regardless of fetch/processing status.

    GATE VERIFICATION lives in the management command, not here (matching every sibling
    caster's own split - the batch computation stays pure and testable).
    """
    run_id = run_id or generate_run_id()
    result = FilenameDeclarationCastResult(dry_run=dry_run, run_id=run_id)

    required_tag_names = {name for name, pattern in FILENAME_DECLARATION_PATTERNS.items() if pattern is not None}
    tag_by_name = {t.name: t for t in Tag.objects.filter(name__in=required_tag_names)}
    missing_tags = sorted(required_tag_names - tag_by_name.keys())
    if missing_tags:
        raise RuntimeError(
            f"Tag(s) {missing_tags} do not exist yet - run `seed_attribute_tags`/`seed_default_tags` "
            "before this calculator."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    def _skip(card_id: int, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card_id,
                    anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID,
                    run_id=run_id,
                    skip_reason=reason,
                )
            )

    for card in _eligible_cards_queryset(card_ids=card_ids).iterator(chunk_size=chunk_size):
        result.cards_considered += 1
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)

        if verdict.axis_contradiction:
            # Recorded even when other, non-axis tags are ALSO cast below - an audit trail of the
            # contradiction, not just an idempotence marker (a CardTagVote row from the non-axis
            # matches would already make the card ineligible on its own).
            _skip(card.pk, BORDER_AXIS_CONTRADICTION_SKIP_REASON)

        if verdict.cast_tag_names:
            result.cards_with_declarations += 1
            for tag_name in sorted(verdict.cast_tag_names):
                result.votes_would_cast += 1
                result.votes_by_tag[tag_name] = result.votes_by_tag.get(tag_name, 0) + 1
                if len(result.audit) < audit_sample_size:
                    result.audit.append({"card_id": card.pk, "name": card.name, "tag": tag_name})
                if not dry_run:
                    votes_batch.append(
                        CardTagVote(
                            card_id=card.pk,
                            tag=tag_by_name[tag_name],
                            polarity=VotePolarity.APPLY,
                            anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID,
                            source=VoteSource.DEDUCTION,
                            confidence=FILENAME_DECLARATION_VOTE_CONFIDENCE,
                            run_id=run_id,
                        )
                    )
        elif not verdict.axis_contradiction:
            _skip(card.pk, NO_DECLARATION_SKIP_REASON)

    if not dry_run:
        purge_and_write_votes(
            CardTagVote,
            votes_batch,
            anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID,
            target_field="card_id",
            ignore_conflicts=True,
        )
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.votes_written = len(votes_batch)

        touched_card_ids = {vote.card_id for vote in votes_batch}
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_tag_votes(card)

    return result


__all__ = [
    "FILENAME_DECLARATION_CAST_ANONYMOUS_ID",
    "FILENAME_DECLARATION_VOTE_CONFIDENCE",
    "BORDER_COLOR_AXIS_TAG_NAMES",
    "FILENAME_DECLARATION_PATTERNS",
    "NO_DECLARATION_SKIP_REASON",
    "BORDER_AXIS_CONTRADICTION_SKIP_REASON",
    "FILENAME_DECLARATION_RESCANNABLE_SKIP_REASONS",
    "FilenameDeclarationVerdict",
    "calculate_filename_declaration_verdict",
    "FilenameDeclarationCastResult",
    "run_filename_declaration_cast",
]
