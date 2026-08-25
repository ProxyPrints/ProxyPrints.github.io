"""
Local (zero-API-cost) printing-identification backfill pilot: two independent engines that
vote on a card's printing by actually looking at its image, rather than deducing it from
pre-existing structured data (see cardpicker.deductive_backfill, the sibling this extends).
Same non-negotiable principle: a vote here is always just a vote (VoteSource.OCR), never a
direct resolve - the human-backed gate in vote_consensus.resolve_weighted_consensus still
applies, at any volume. See docs/features/printing-tags.md's Stage 8 section for the full
design writeup (environment, engine details, pilot discipline).

Targets the residual pool deductive backfill's D1/D2 tiers can't reach: names that match MORE
THAN ONE CanonicalCard row (deductive backfill only resolves the exactly-one-match case
directly, or the expansion_hint-narrows-to-one case) - visual disambiguation (a legible
collector line, or a matching art crop) is exactly the signal that's missing there. Selection
also revisits single-candidate names that deductive backfill left unresolved.

THAT LAST SENTENCE USED TO NAME A CAUSE IT COULD NOT HAVE (corrected 2026-07-29). It said those
names were "rejected by deductive backfill's own Scryfall printings_count cross-check". That
cohort is empty and always was: the check in question rejects nothing (it is entailed by the
name-uniqueness test that precedes it - see `deductive_backfill.select_d1_candidates`, and issue
#600), and the column it reads counts our own rows rather than anything Scryfall reports. Single-
candidate names that are still unresolved got that way through the ordinary eligibility filters
- an existing vote, a "Custom" tag, a non-English language, an already-confirmed match - not
through an external cross-check.

PASS-2 FALLBACK PRINTING VOTES ARE RETIRED (owner ruling 2026-07-29, redundancy doctrine -
"anything made redundant is retired", and the test is the EVIDENCE SOURCE, not the vote cast).
This module used to cast a THIRD printing-vote identity, `local_fallback.FALLBACK_ANONYMOUS_ID`
("local-fallback-v1"), from a pass-2 border/artist/symbol evidence combination run over the
cards pass 1 missed. `local_calculate_verdicts.calculate_fallback_verdict`
("stage-d-fallback-v1") is a faithful port of that SAME decision model reading the SAME three
readings out of stored `ImageEvidence` instead of a freshly-fetched image - it calls
`local_fallback.filter_by_border_color`/`match_artist` directly, and duplicates
`find_symbol_matches`' arithmetic against the same PROTECTED CORE thresholds. Two calculators
over one evidence source are one witness counted twice, which inflates apparent corroboration in
`vote_consensus.resolve_weighted_consensus`' weighted quorum without adding information.
Measured over all 179,176 `CardPrintingTag` rows (2026-07-29): the two overlap on 11,825 cards
and agree on 11,825 of them - 100.0%, zero conflicts, zero one-sided abstentions. Stage D's
identity is the one kept (it reads persisted evidence, so it re-runs with no CDN fetch at all);
this module's pass-2 printing channel is gone. Rows already cast under "local-fallback-v1" are
LEFT IN PLACE - history is kept, only future casting stops; removing them is a separate,
owner-authorized `purge_machine_votes` step.

WHAT IS *NOT* RETIRED WITH IT, and must not be swept up by a future "just stop running the
fallback": `local_fallback.py` is also the home of three ATTRIBUTE-chip vote channels that vote
under the very same `local-fallback-v1` identity but on `CardTagVote`, never `CardPrintingTag` -
`cast_border_attribute_vote` (Black/White/Silver/Borderless), `cast_frame_style_vote` (Old/
Modern Border) and `cast_bleed_edge_vote` (the `appropriate-bleed` SENSITIVE tag). Stage D has
no analogue for any of the three, none of them was part of the redundancy measurement (which
counted printing votes only), and all three are still cast below - as is `image_evidence.py`'s
own separate `cast_border_attribute_vote` call under that same identity. Likewise
`local-ocr-v1`/`local-phash-v1` share this module's single management command with the retired
pass (there is no `--engine` value for the fallback: it rode along on whatever pass 1 selected),
so the ruling had to be a code change here, not "stop running the command" - that would have
silently dropped two calculators that are kept.

FILENAME-STYLE DUPLICATE-UPLOAD SUFFIX NORMALIZATION (2026-07-23, `CandidateNameIndex.
candidates_for` - live-proven defect, card_id 7173 "Plaguecrafter (1)"): a source folder's own
auto-dedup naming (two files sharing a name - Google Drive/local-filesystem convention) or the
OS's own duplicate-file convention appends a suffix to `Card.name` that was never part of the
real card name, and `candidates_for` is an EXACT-STRING lookup on `to_searchable(name)` (no
fuzzy/substring matching, unlike `printing_candidates.find_candidates_by_name`'s own
`icontains`-per-word search), so any surviving suffix character produces zero candidates. See
`_strip_filename_duplicate_suffix`'s own docstring immediately below `CandidateNameIndex` for
the exact patterns handled, why (a live catalog survey, not a guess), and what's deliberately
left unhandled.
"""

import collections
import functools
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Optional, cast

from PIL import Image

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from cardpicker import (
    image_cdn_fetch,
    local_clustering,
    local_fallback,
    local_ocr,
    local_phash,
)
from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID
from cardpicker.local_phash import PHASH_NO_CLEAR_WINNER_SKIP_REASON
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    CardScanLog,
    CardTagVote,
    CardTypes,
    PrintingTagStatus,
    VoteSource,
    calculator_family,
)
from cardpicker.search.sanitisation import strip_bracketed_groups, to_searchable
from cardpicker.vote_write import purge_and_write_votes

logger = logging.getLogger(__name__)

OCR_ANONYMOUS_ID = "local-ocr-v1"
PHASH_ANONYMOUS_ID = "local-phash-v1"
# cardpicker.deductive_backfill.DEDUCTIVE_BACKFILL_ANONYMOUS_ID, duplicated as a literal
# rather than imported to avoid a hard import-time dependency between the two backfill
# modules over one constant string.
DEDUCTIVE_BACKFILL_ANONYMOUS_ID = "deductive-backfill-v1"

OCR_CONFIDENCE_BOTH = 0.85  # set code + collector number both parsed and matched
OCR_CONFIDENCE_COLLECTOR_ONLY = 0.75  # pre-M15 cards: no set code printed on the collector line
PHASH_CONFIDENCE = 0.8
# issue #207: confidence for a real is_no_match vote cast from a validated-but-unmatched OCR
# read ("parsed-but-no-match", post-ambiguous-split) - deliberately below the match-tier
# confidences above. Purely informational (vote_consensus weights by `source`, never
# `confidence` - see local_fallback.GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE's own comment for the
# same point made about attribute votes), but an honest record that a validated non-match is a
# somewhat weaker conclusion than a validated match: the parse could still be a misread of a
# candidate that does exist but wasn't captured correctly, whereas a real match's exact-string
# agreement is stronger positive confirmation.
OCR_NO_MATCH_CONFIDENCE = 0.6
# RETIRED 2026-07-29 (module docstring's pass-2 section): the calculator FAMILIES that must
# never appear on a `CardPrintingTag` row this module writes again. Keyed on the versionless
# FAMILY, never on the literal id, for exactly the reason `vote_consensus.
# DEDUCTIVE_BACKFILL_FAMILY`'s own comment gives: a machine calculator's version lives INSIDE
# its `anonymous_id`, so an exact-string check would let an ordinary redeploy to
# "local-fallback-v2" silently un-retire a ratified ruling with no error and no failing test.
# DERIVED via `models.calculator_family`, not written out as a second literal, so the two can
# never drift; the assert makes a rename that took the id outside the machine naming convention
# fail loudly at import time rather than quietly disable the guard in `flush` below.
#
# This is scoped to PRINTING votes only. The same identity still legitimately writes
# `CardTagVote` rows (border/frame/bleed attribute chips - see the module docstring), and
# `purge_stale_machine_votes` still purges the family's HISTORICAL printing rows if a future
# calculator in this family is ever reinstated - retiring the caster does not rewrite history.
RETIRED_PRINTING_VOTE_FAMILIES = frozenset({calculator_family(FALLBACK_ANONYMOUS_ID)})
assert None not in RETIRED_PRINTING_VOTE_FAMILIES, (
    "every retired printing-vote identity must follow the machine calculator naming convention "
    "(<family>-v<N>): the 2026-07-29 redundancy retirement is enforced by family, not by literal."
)
# THIS MODULE'S OWN SKIP VOCABULARY (2026-07-29 declaration-convention sweep - see
# docs/reference/skip-reasons.md). Every value the OCR and phash engines here write to
# `CardScanLog.skip_reason` is declared as a module-level `*_SKIP_REASON` constant so the roster
# is statically enumerable, exactly as `*_ANONYMOUS_ID` already is. These were inline string
# literals at their write sites until this sweep; the STRINGS are unchanged (a row written before
# and after this change is byte-identical) - only their point of declaration moved.
#
# Same-value/different-constant is deliberate where a string is also emitted by another
# calculator under a different `anonymous_id` and a different meaning (e.g. "ambiguous",
# "frame-mismatch", "no-text"); a single shared constant would falsely imply one shared concept.
UNFETCHABLE_IMAGE_SKIP_REASON = "unfetchable-image"
FRAME_MISMATCH_SKIP_REASON = "frame-mismatch"
DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON = "disagreement-with-other-engine"

# The OCR engine's own outcomes (`OcrCardResult.skip_reason`, set in `run_ocr_for_card`).
# PARSED_BUT_NO_MATCH_SKIP_REASON no longer reaches `CardScanLog` at all as of issue #207 - that
# outcome casts a real `is_no_match` CardPrintingTag vote instead - but it is still an
# `OcrCardResult.skip_reason` value the write loop branches on, and HISTORICAL scan-log rows
# carry it, so it is declared here alongside the rest rather than left as a bare literal.
OCR_AMBIGUOUS_SKIP_REASON = "ambiguous"
OCR_NO_TEXT_SKIP_REASON = "no-text"
PARSED_BUT_NO_MATCH_SKIP_REASON = "parsed-but-no-match"
# Duplicated as a literal from `local_calculate_verdicts.JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON`
# rather than imported - the same "avoid a hard import-time dependency between sibling engines
# over one constant" precedent `local_illustration._JOIN_KEY_NO_HIT_SKIP_REASONS` already sets.
# A literal (not an alias) is also what keeps this declaration visible to docs_lint's roster
# tether, which matches `NAME = "<literal>"` only.
OCR_UNKNOWN_SET_CODE_SKIP_REASON = "unknown-set-code"

# The phash engine's own outcomes (`run_phash_for_card`).
PHASH_TOO_MANY_CANDIDATES_SKIP_REASON = "too-many-candidates"
# `no-hashable-candidates` and `no-clear-winner` are NOT declared here. They originate inside
# `local_phash.find_best_match` and, as of the 2026-07-29 protected-core exception
# (docs/upstreaming/license-provenance.md §2), are declared THERE as
# `PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON` / `PHASH_NO_CLEAR_WINNER_SKIP_REASON`. They were
# briefly mirrored here because that file is protected core and could not be edited; the mirror is
# gone, so there is ONE declaration per value and nothing that can drift. This module IMPORTS the
# one it needs (see the import block above) rather than re-declaring it.
#
# The two refinements below ARE this module's own: `_classify_no_clear_winner` splits phash's
# undifferentiated `no-clear-winner` into a threshold miss and a margin miss, so plain
# `no-clear-winner` is never written to `CardScanLog` by this module today - HISTORICAL rows
# predating that refinement still carry it.
PHASH_NO_CLEAR_WINNER_DISTANCE_SKIP_REASON = "no-clear-winner-distance"
PHASH_NO_CLEAR_WINNER_MARGIN_SKIP_REASON = "no-clear-winner-margin"

# Basic lands and staple commons can carry hundreds of printings (Forest alone: 944 in the
# live pilot's own eligible pool, confirmed live 2026-07-15) - and "multi-candidate names
# first" ordering puts exactly those names first, meaning an uncapped pilot run would try to
# fetch+hash hundreds of Scryfall art crops for the very first cards it processes. 25% of the
# eligible pool (43,094/171,878, confirmed live) exceeds this cap - capped, not tuned; a name
# this common needs a different strategy entirely (a name-level index, not per-run fetching),
# out of scope for this pilot.
PHASH_MAX_CANDIDATES = 12

# Checkpointing (Stage 8 pre-scale program item 2, see run_pilot): flush every this many cards
# processed. Deliberately much smaller than deductive_backfill's batch_size=2000 - that pipeline
# is pure DB writes with no per-card network fetch/OCR/phash cost, so losing an un-flushed batch
# to a crash is cheap there; here each card costs a real image fetch plus OCR/phash CPU work, so
# a smaller batch bounds how much re-fetchable-but-not-yet-durable work a kill can waste.
DEFAULT_BATCH_SIZE = 25

# cardpicker.reason_tags.NO_MATCH_REASON_TAGS - a resolved custom-art/non-english tag already
# tells us the PRINCIPLE's precondition (an authentic depiction of a real printing) is false,
# same exclusion rationale as cardpicker.deductive_backfill's "Custom" tag check, just against
# this taxonomy's tag names instead of the filename-inferred one.
EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]

# Part 3 addendum item 3 (docs/features/catalog-completion-plan.md, upgraded from propose-to-
# hold to build 2026-07-16): skip_reason values that stay eligible for re-selection on a future
# invocation instead of permanently excluding the card, same as a vote would. "unfetchable-image"
# is a transient CDN/network condition, not a conclusion about the card - worth retrying later.
# "frame-mismatch" is deliberately re-scannable because Part 3's own dual-yield design needs to
# revisit these cards for artist extraction even though the printing vote stays withheld - a
# permanent skip here would silently starve that future consumer of its own input. Every OTHER
# skip_reason ("no-text", "no-clear-winner-distance"/"no-clear-winner-margin", "ambiguous",
# "no-evidence", "too-many-candidates", etc.) represents a genuine, repeatable negative
# conclusion against the same deterministic image/candidates - re-scanning those would just burn
# CDN budget to re-derive the identical answer. Two of the reasons that USED to live in this
# category ("parsed-but-no-match", "eliminated") no longer appear as a skip_reason at all as of
# issue #207 - they're strong enough negative evidence to cast a real `is_no_match` vote instead,
# which already excludes the card from re-selection via its own anonymous_id (see
# _eligible_base_queryset), no scan-log/rescannability bookkeeping needed for them any more.
RESCANNABLE_SKIP_REASONS = frozenset({UNFETCHABLE_IMAGE_SKIP_REASON, FRAME_MISMATCH_SKIP_REASON})

Engine = Literal["ocr", "phash"]

_NICE_SLEEP_SECONDS = 0.05


@dataclass(frozen=True)
class CandidatePrinting:
    pk: int
    expansion_code: str  # lowercase
    collector_number: str
    # addendum item 3 (2026-07-15): Scryfall's public popularity signal, not user telemetry -
    # explicitly the zero-telemetry-policy-clean substitute for a previously-parked
    # export-popularity-ordering idea. Lower = more popular. None where Scryfall never ranked
    # this specific printing (confirmed live: ~10.7% of CanonicalPrintingMetadata rows,
    # 2026-07-15) - see _demand_rank_for_candidates for how a name's candidates combine this.
    edhrec_rank: Optional[int] = None
    # 2026-07-29 (`collector_line_artist`'s CARD-NAME NARROWING): the `CanonicalArtist.name` of
    # THIS printing, carried so a name-scoped candidate list doubles as the "artists who
    # illustrated a printing of this card's name" set - the narrowing Stage D applies to a
    # collector-line artist reading - at ZERO extra query, since `CandidateNameIndex`'s own
    # single `CanonicalCard` scan can join the row it already reads five other columns off.
    # Empty string where the printing has no artist on record (never guessed), read as "nothing
    # to contribute" by every consumer. Trailing position + default so every existing hand-built
    # `CandidatePrinting(...)` in the test suite keeps constructing unchanged.
    artist_name: str = ""
    # issue #946 (`cardpicker.filename_candidates`' treatment-tag signal): the same
    # `CanonicalPrintingMetadata` row's own `full_art`/`border_color`/`frame` columns, carried at
    # the same zero-extra-query cost as `artist_name` above (`CandidateNameIndex`'s single scan
    # already `select_related`s `printing_metadata`). `""`/`False` where the printing has no
    # metadata row at all (same "nothing to contribute" convention as `artist_name`), not
    # `None` - every consumer compares these against a real card-tag-derived value, never
    # branches on "was metadata present at all". Trailing position + defaults, same rationale as
    # `artist_name`'s own comment.
    border_color: str = ""
    frame: str = ""
    full_art: bool = False


# FILENAME-STYLE DUPLICATE-UPLOAD SUFFIX (module docstring) - stripped from the RAW name BEFORE
# to_searchable normalisation, so an upload carrying this suffix still resolves to the same
# candidate set as the un-suffixed name. Two patterns, both confirmed against a live catalog
# survey (2026-07-23), not guessed:
#   - `\(\d+\)` ("Plaguecrafter (1)", "Mountain (4)" - a source folder's own auto-dedup naming
#     when two uploads share a name): already incidentally covered by `to_searchable`'s own
#     general-purpose bracket-stripping (`re.sub(r"[\(\[].*?[\)\]]", "", ...)` - confirmed live,
#     card_id 7173 "Plaguecrafter (1)" already resolves 8 real candidates under the UNCHANGED
#     `to_searchable` alone) - included here anyway so this index's own matching behavior is
#     explicit and self-contained, not silently dependent on a shared, general-purpose search
#     primitive's own unrelated bracket-stripping (which strips ANY bracketed content for a
#     different reason - general search noise removal - and could change independently of this
#     concern). Zero new collision risk: `to_searchable` already strips ALL bracket content on
#     the STORED (`CanonicalCard.name`) side too, so a real catalog name that happens to end in
#     "(<digits>)" (e.g. "Tom van de Logt Bio (2000)") already collapses to the identical
#     normalised key with or without this pattern - confirmed against the live catalog's 71
#     parenthesis-carrying `CanonicalCard` rows, none of which this pattern changes the outcome
#     for.
#   - `-\s*copy` ("Polluted Delta - Copy" - the OS's own duplicate-file naming convention): a
#     REAL, previously-unhandled gap - `to_searchable` converts the hyphen to a space (its own
#     existing behaviour for compound names) and has no reason to then strip the literal
#     surviving word "Copy". Requires the hyphen specifically (not a bare trailing "copy"): the
#     live catalog carries real `CanonicalCard` rows literally named "Copy" and "Pirated Copy"
#     (40 rows total ending in "copy", live-checked, none hyphen-preceded), so a bare trailing
#     "copy" strip would corrupt an upload of either real card; requiring the hyphen is a safe,
#     non-colliding signal.
# Applied repeatedly, not just once (`_strip_filename_duplicate_suffix` below) - the two patterns
# can stack on a real upload (a duplicate re-downloaded a second time: "Name (1) - Copy").
#
# SURVEYED BUT DELIBERATELY NOT HANDLED (same live survey, 2026-07-23) - both are pre-existing
# `to_searchable` tokenisation/exact-match limitations with a much larger blast radius than a
# suffix strip, out of scope here:
#   - underscore/no-separator duplicate-number suffixes ("Yen_02", "Spirit_Token_3-2") -
#     `to_searchable` treats "_" as punctuation to DELETE, not a separator to convert to a space
#     (unlike "-", which it does convert) - "Spirit_Token_3-2" normalises to "spirittoken", not
#     "spirit token", so it can never match the real candidate "Spirit Token" regardless of any
#     trailing-suffix fix. Changing "_" handling is a change to `to_searchable` itself (shared,
#     general-purpose search infra used far beyond this index), not a targeted suffix strip.
#   - short/partial-name uploads ("Lazav_1" for the real "Lazav, Dimir Mastermind", "Ciri_01"/
#     "Yen_02"/"TreacheryGame_*" for custom Witcher-crossover/game-prop uploads with no real
#     `CanonicalCard` match at all) - `candidates_for` is an EXACT-normalised-string lookup, not
#     fuzzy/substring matching (that's `printing_candidates.find_candidates_by_name`'s own
#     `icontains`-per-word job, a different consumer); recovering these would mean building a
#     fuzzy/nickname matcher here, not stripping a suffix - most of this specific sample turned
#     out to be genuinely custom, non-Magic filenames anyway (zero real candidates IS correct for
#     them), not evidence of a normalisation bug.
_FILENAME_DUPLICATE_SUFFIX_RE = re.compile(r"\s*(?:\(\d+\)|-\s*copy)\s*$", re.IGNORECASE)


def _strip_filename_duplicate_suffix(name: str) -> str:
    """Strips a trailing filename-style duplicate-upload suffix (see `_FILENAME_DUPLICATE_SUFFIX_
    RE`'s own comment for the exact patterns/rationale) - repeatedly, since more than one such
    suffix can stack on a real upload (e.g. a duplicate re-downloaded a second time: "Name (1) -
    Copy"). A name carrying no such suffix is returned byte-identical (`re.sub` is a no-op on a
    non-match), so this is always safe to call unconditionally."""
    previous = None
    stripped = name
    while stripped != previous:
        previous = stripped
        stripped = _FILENAME_DUPLICATE_SUFFIX_RE.sub("", stripped)
    return stripped


def _has_interior_capital(name: str) -> bool:
    """
    issue #372: True if `name` (after stripping any bracketed filename-disambiguation suffix,
    e.g. " (1)"/" (Modern Tomas Giorello)", case preserved otherwise) consists ENTIRELY of
    letters and carries an uppercase one somewhere after its first character - the camelCase
    signature a title-cased multi-word name leaves behind when every space is stripped out of
    it at upload time (e.g. "VazaltheCompleat" for "Vazal, the Compleat": lowercase "the"
    wasn't re-capitalised the way major words were, but the word boundary before "Compleat"
    still shows up as an interior capital "C").

    Used as a conservative trigger gate for CandidateNameIndex's de-concatenation fallback
    below, alongside "the direct lookup already failed" and "the normalised name has no
    spaces": an ordinary single-word name that just doesn't exist in the catalog (rather than
    being a space-stripped multi-word one) essentially never carries an interior capital, so
    gating on this keeps the fallback from being attempted - and potentially guessing wrong -
    against names that were never glued together in the first place.

    The "entirely letters" requirement (not just "has an interior capital somewhere") matters
    for composing correctly with `_strip_filename_duplicate_suffix`'s own, deliberately
    out-of-scope underscore case ("Spirit_Token_3" for "Spirit Token", pinned unmatched by
    `test_underscore_duplicate_suffix_is_deliberately_left_unhandled`): `to_searchable` strips
    "_" as punctuation, so an underscore-separated, title-cased name would otherwise ALSO look
    like camelCase evidence by capitalisation alone - a genuinely glued name like
    "VazaltheCompleat" has NO separator characters of any kind left once its bracketed suffix
    is gone, which is what actually distinguishes it. Confirmed live this doesn't lose any of
    issue #372's own real recoveries - every one of them carries its digit suffix INSIDE a
    "(N)"-style bracket, already gone before this check runs.
    """
    stripped = strip_bracketed_groups(name).strip()
    return stripped.isalpha() and any(char.isupper() for char in stripped[1:])


class CandidateNameIndex:
    """
    In-memory index over every `CanonicalCard`, keyed on `to_searchable` name normalisation and
    carrying (expansion_code, collector_number, edhrec_rank, artist_name) per candidate - both
    engines here need to check a parsed/matched value against a candidate's actual identity, not
    just count how many candidates exist. `cardpicker.deductive_backfill`'s D1/D2 selectors
    (issue #722) also resolve this SAME index, through `local_calculate_verdicts.
    _get_cached_candidate_name_index()`, rather than keeping their own separate one. Built once,
    reused across the whole scan (one query over CanonicalCard's 113k+ rows, not one per card).

    issue #372: also carries a secondary "de-concatenated" index (`_by_concat`) used only as a
    fallback by `candidates_for` when the direct to_searchable lookup misses - see
    `_deconcatenated_candidates`'s docstring for the full matching rule.
    """

    def __init__(self) -> None:
        by_name: dict[str, list[CandidatePrinting]] = collections.defaultdict(list)
        rows = CanonicalCard.objects.select_related("expansion", "printing_metadata", "artist").values_list(
            "pk",
            "name",
            "expansion__code",
            "collector_number",
            "printing_metadata__edhrec_rank",
            "artist__name",
            "printing_metadata__border_color",
            "printing_metadata__frame",
            "printing_metadata__full_art",
        )
        for (
            pk,
            name,
            expansion_code,
            collector_number,
            edhrec_rank,
            artist_name,
            border_color,
            frame,
            full_art,
        ) in rows:
            by_name[to_searchable(name)].append(
                CandidatePrinting(
                    pk=pk,
                    expansion_code=expansion_code.lower(),
                    collector_number=collector_number,
                    edhrec_rank=edhrec_rank,
                    # 2026-07-29: the SAME scan, one more joined column - see `CandidatePrinting.
                    # artist_name`. `artist` is nullable, so a printing with no artist on record
                    # yields None here and is normalised to "" rather than carried as None.
                    artist_name=artist_name or "",
                    # issue #946: same "no metadata row -> normalise the null" treatment as
                    # artist_name above - see CandidatePrinting.border_color/frame/full_art.
                    border_color=border_color or "",
                    frame=frame or "",
                    full_art=bool(full_art),
                )
            )
        self._by_name = dict(by_name)

        # issue #372: group the same normalised names a second time by their fully
        # space-stripped form, so a query that's already had ITS spaces stripped (by whatever
        # tool produced the source filename, not by us) can still be looked up - but only ever
        # returned by candidates_for when exactly one distinct real name collapses to that
        # form (see _deconcatenated_candidates), so an accidental collision between two
        # genuinely different multi-word names never produces a silent wrong-name match.
        by_concat: dict[str, list[str]] = collections.defaultdict(list)
        for normalised_name in self._by_name:
            by_concat[normalised_name.replace(" ", "")].append(normalised_name)
        self._by_concat = dict(by_concat)

    def candidates_for(self, name: str) -> list[CandidatePrinting]:
        """Three tiers, cheapest to costliest, each attempted only after the previous one comes
        up empty:
          1. direct - the common, unsuffixed case (`to_searchable(name)` against `_by_name`);
          2. filename-style duplicate-upload suffix strip (`_strip_filename_duplicate_suffix` -
             "Plaguecrafter (1)"/"Polluted Delta - Copy") - a cheap, safe, idempotent regex
             strip, retried as a second direct lookup - most names carry no such suffix, so
             this keeps the extra regex work scoped to the cohort that actually needs it, the
             same "only pay for what you use" shape `_resolve_candidates_for_card`'s own
             DFC-back-face fallback in `local_calculate_verdicts.py` already established;
          3. de-concatenation (`_deconcatenated_candidates` - "VazaltheCompleat") - the most
             speculative of the three (matches against a name with EVERY space removed, gated
             on an interior-capital camelCase signal and unambiguous-collision-only acceptance
             - see that method's own docstring), so it always runs last, and against whichever
             of `name`/the suffix-stripped form is more normalised - a name carrying BOTH a
             glued multi-word body and a duplicate-upload suffix (e.g. "VazaltheCompleat (2) -
             Copy") still reaches the concat lookup suffix-free, not just space-stripped.
        A card unmatched by all three stays unmatched - never partially or ambiguously guessed
        at by falling through to a weaker tier."""
        normalised = to_searchable(name)
        direct = self._by_name.get(normalised, [])
        if direct:
            return direct

        stripped = _strip_filename_duplicate_suffix(name)
        if stripped != name:
            suffix_stripped = self._by_name.get(to_searchable(stripped), [])
            if suffix_stripped:
                return suffix_stripped

        effective_name = stripped if stripped != name else name
        return self._deconcatenated_candidates(effective_name, to_searchable(effective_name))

    def _deconcatenated_candidates(self, raw_name: str, normalised: str) -> list[CandidatePrinting]:
        """
        issue #372: recovers cards like "VazaltheCompleat (2)" (real card: "Vazal, the
        Compleat") whose source filename had every space stripped out of the card name before
        upload - `to_searchable` has no mechanism to reinsert word boundaries into an
        already-glued string, so the direct by-name lookup in `candidates_for` always misses
        these regardless of the bracketed "(2)"-style suffix (which IS already handled, by
        `to_searchable`'s own bracket-stripping - this fallback is for the separate,
        glued-name problem underneath it).

        Deliberately conservative, per the task's own "wrong-name matches are worse than none":
        only attempted when ALL of the following hold, and returns [] (stays unmatched) the
        moment any of them doesn't -
          - the direct lookup above already missed;
          - `normalised` (the bracket-stripped, punctuation/digit-stripped, lowercased name)
            contains no whitespace at all - a name that DOES still have a space either matched
            directly above already, or is a genuine no-match unrelated to space-stripping, and
            forcing it through a fully-concatenated lookup would risk matching totally
            unrelated words that merely happen to run together;
          - the original name carries an interior capital letter (`_has_interior_capital`) -
            the camelCase evidence that this specific name really was glued together from a
            title-cased multi-word original, not just a single word that doesn't exist;
          - the fully space-stripped form matches EXACTLY ONE distinct real card name in
            `_by_concat` - if it collides with more than one (e.g. two differently-worded real
            names that happen to concatenate to the same string), this returns [] rather than
            guessing between them, exactly like an ambiguous direct multi-candidate match
            would be left for a human to disambiguate elsewhere in this pipeline.
        """
        if " " in normalised or not _has_interior_capital(raw_name):
            return []
        matches = self._by_concat.get(normalised, [])
        if len(matches) != 1:
            return []
        return self._by_name[matches[0]]


@dataclass(frozen=True)
class SelectedCard:
    card: Card
    candidates: list[CandidatePrinting]


# addendum item 4 (2026-07-15): the empirical resolution floor from the 6-way dpi sweep
# (docs/features/printing-tags.md "Resolution floor + payload reduction") - dpi<=150 degrades
# OCR yield below the native-resolution baseline, dpi>=200 matches or exceeds it. This is the
# FLOOR itself (200), not DEFAULT_FETCH_DPI (460 as of 2026-08-14, a safety margin above the
# floor - see that constant's own comment) - applied
# against Card.dpi (computed once at catalog-import time from the source image's own pixel
# height - cardpicker.sources.update_database.transform_image_into_object) so a source image
# that's ALREADY below the floor is never fetched at all: no CDN request, no OCR/phash cost,
# since resizing can't manufacture detail the source never had. Card.size (raw file bytes) is
# deliberately NOT used as a second condition despite the addendum spec's "dpi/size" phrasing -
# it's a compression-dependent proxy with no empirical calibration behind it, unlike dpi's
# direct, validated sweep; an unvalidated byte threshold would violate this pilot's own
# "measure, don't assume" discipline that caught the phash/dpi false hypothesis (item 4 above).
RESOLUTION_FLOOR_DPI = 200


def _eligible_base_queryset(
    anonymous_id: str,
    exclude_source_pks: Optional[Iterable[int]] = None,
    card_ids: Optional[Iterable[int]] = None,
    run_id: Optional[str] = None,
) -> "QuerySet[Card]":
    """
    RUN-SCOPED SELF-SUPPRESSION (`run_id`, OPT-IN, 2026-07-29 owner directive: "prior runs must not
    suppress work in a new run; the CURRENT run's own output must, so a killed run resumes rather
    than redoing completed batches"). When given, the two self-suppressing excludes below - this
    engine's own vote exclude and its own non-rescannable `CardScanLog` exclude - are narrowed to
    rows carrying THIS run's run_id, so an answer this engine gave in an EARLIER run no longer
    removes the card from a new run's pool. `local_calculate_verdicts._eligible_cards_queryset`'s
    docstring carries the full reasoning; this is the same change applied to the pilot's own
    equivalent.

    `run_id=None` (the default) is EXACTLY the pre-2026-07-29 behaviour, and today it is still what
    most callers get. Two callers pass a run_id: `local_lands_identify._land_pool_selected_cards`
    (lands is the one caller of this function named in the Stage D printing-channel directive) and
    `run_name_frequency_elimination` (2026-07-30 - see the SECOND reason below, which is a
    different and stronger argument than the resume one). The remaining callers - `run_pilot`'s
    `select_candidates` and `count_below_resolution_floor` - are the OCR/phash pilot, a different
    workload with its own fetch budgets and its own resume semantics, and flipping them is a
    separate decision with a separate blast radius rather than a free ride on this one. That is a
    deliberate scoping of the change, not an oversight, and it is recorded here so the asymmetry is
    visible from this function rather than only from its callers.

    THE SECOND REASON TO PASS `run_id`, WHICH IS NOT ABOUT RESUMING (2026-07-30). For most callers
    the own-vote exclude is a per-card idempotence checkpoint, and leaving it lifetime only costs
    work that a later run skips. For a caller whose PREDICATE IS A COUNT OVER THE RETURNED
    POPULATION, a lifetime exclude is not a missed vote - it is a source of FRESH WRONG POSITIVES,
    because the calculator is taking a census over a population it is itself permanently shrinking.
    `run_name_frequency_elimination` is exactly that caller: it votes only when a name has exactly
    ONE unresolved eligible card, so every card it votes on leaves the pool forever under a
    lifetime exclude, and a name that correctly ABSTAINED on run 1 (two eligible cards, so
    elimination says nothing about which is which) can pass the gate on run 2 purely because run 1
    removed one of them. Its own docstring calls that count "the difference between a sound
    inference and a coin flip"; a self-depleting pool turns it back into the coin flip. Any FUTURE
    caller whose gate is a count over this queryset must pass `run_id` for the same reason - the
    distinction to apply is the same one the BATCH SCOPING note below draws, and it points the
    opposite way for `run_id` than it does for `card_ids`.

    THE DEDUCTIVE-BACKFILL EXCLUDE BELOW IS NEVER RUN-SCOPED, whatever `run_id` says: it is a
    workload choice about ANOTHER identity's votes ("don't pile a weaker vote onto a card the
    exact-by-construction backfill already covered"), not this engine's own progress, and narrowing
    it to this run would empty it on every run.

    unresolved, no confirmed indexing match, no existing vote from this engine's own
    anonymous_id (the idempotence/checkpoint mechanism - see module docstring and
    cardpicker.deductive_backfill's identical pattern), not already covered by the deductive
    backfill (which is provably exact by construction where it applies - this pilot's engines
    are weaker, lower-confidence signal and shouldn't pile onto a card that already has a
    stronger deduction), no resolved custom-art/non-english tag, and card_type=CARD only.

    Tokens (and cardbacks) are excluded (2026-07-16, diagnosed live): a token's printed
    collector line reads its PARENT set's code (e.g. "MM3"), while its CanonicalCard
    candidates use token-specific set codes (e.g. "tm3c") that never match - a structural
    mismatch, not a fixable parsing bug. Combined with item 1's coverage-gap ordering (generic
    multi-set token names like "Beast" have huge candidate counts and near-zero coverage, so
    they score maximally on "descending uncovered count"), this was front-loading an
    essentially-0%-matchable cohort to the very front of every selection - confirmed live by
    sampling real OCR output against real candidates for the first 8 selected cards in a real
    250-card window, all 8 of which were "Beast" tokens. Future work (not built): a
    token-aware path using Scryfall's own token detection (`layout=token`/similar) to search
    collector info or the set ICON instead of the parent-set text tokens don't reliably print.

    Does NOT apply the resolution floor (see select_candidates/count_below_resolution_floor,
    which layer opposite conditions on top of this shared base so the "how many did the floor
    skip" report metric doesn't duplicate this method's other exclusion rules).

    exclude_source_pks is a purely mechanical, caller-supplied deprioritization knob (no source
    pk is ever hardcoded here) - see select_candidates and the management command's
    --exclude-sources-ocr/--exclude-sources-phash flags.

    Also excludes a card with a scan-log row (CardScanLog, Part 3 addendum item 3) for this
    SAME anonymous_id, UNLESS that row's skip_reason is in RESCANNABLE_SKIP_REASONS - same
    per-engine exact-match idempotence pattern votes already use, just for abstentions instead
    of assents. Computed as an explicit `.values_list("card_id", ...)` subquery
    (non_rescannable_scanned_card_ids), NOT a single `.exclude(Q(...) & ~Q(...))` on the
    to-many `scan_logs` relation - that formulation looks equivalent but silently is not:
    Django translates a negated lookup on a multi-valued relation into its own independent
    `NOT EXISTS(...)` clause rather than a same-row condition, so `~Q(scan_logs__skip_reason__
    in=X)` really means "no scan_log row at all has that reason" (true even when a DIFFERENT
    row for this card does), not "this specific matched row doesn't have that reason". A card
    with both a rescannable AND a later non-rescannable row for the same anonymous_id would
    incorrectly stay eligible under the Q-object formulation - caught by
    TestScanLog::test_a_later_non_rescannable_reason_overrides_an_earlier_rescannable_one before
    this shipped, not assumed correct from the query reading right at a glance.

    BATCH SCOPING (`card_ids`, issue #533's first blocking prerequisite - the same shape issue
    #469 applied to `local_calculate_verdicts._eligible_cards_queryset` and PR #526 applied to
    `local_illustration._eligible_illustration_cards_queryset`): when a per-batch caller has
    already narrowed the population to a specific set of card pks, that narrowing is pushed INTO
    this queryset rather than applied by the caller afterwards - both onto the outer `Card` query
    AND into the `CardScanLog` exclusion subquery, which Django compiles as an UNCORRELATED
    `IN (SELECT U0."card_id" FROM "cardpicker_cardscanlog" U0 WHERE ...)` and which therefore
    scans that whole 2,093,147-row, append-only table on every invocation unless it is scoped
    too. Purely a cost narrowing, never a behaviour change: a scan-log row this subquery would
    find OUTSIDE `card_ids` could never survive the outer `.filter(pk__in=card_ids)` anyway. The
    other two exclusions (`printing_tags__anonymous_id`) already compile as CORRELATED
    `NOT EXISTS(... U1."card_id" = "cardpicker_card"."id" ...)` subqueries, so the outer scope
    already bounds them - nothing to push in there. `card_ids=None` (BULK mode - every
    management-command caller, `run_pilot`, `run_name_frequency_elimination`,
    `count_below_resolution_floor`, `select_candidates`) leaves this byte-identical to before.

    NOT EVERY CALLER OF THIS QUERYSET MAY SAFELY BE SCOPED, and the parameter existing here is
    not permission to pass it - stated explicitly because a future per-batch wiring pass will
    read this signature before it reads the callers. `run_name_frequency_elimination` gates its
    vote on `len(card_ids) != 1` over the cards this queryset returns for a NAME - i.e. on
    "exactly one unresolved eligible card exists CATALOG-WIDE for this name", which that
    function's own docstring calls "the difference between a sound inference and a coin flip".
    Narrowing this queryset to a micro-batch would silently reinterpret that count as "exactly
    one WITHIN THE BATCH" and cast votes for names whose other unresolved cards merely sat
    outside it; `compute_covered_printing_pks()` alongside it is catalog-wide in the same way.
    NOTE THAT `run_id` IS THE OPPOSITE CASE AND MUST NOT BE READ OFF THIS PARAGRAPH: `card_ids`
    narrows the population by a slice that has nothing to do with the question being asked, which
    corrupts the count; `run_id` REMOVES a narrowing the calculator inflicted on itself in an
    earlier run, which RESTORES the count to the catalog-wide one the gate is specified against.
    One must not be passed here and the other must, for the same underlying reason.
    `run_lands_identify` (the caller scoped under issue #533's first prerequisite) is safe
    because its own predicate is strictly per-card - `is_lands_target` on that card's own name
    and candidate count - never a count over the returned population. Any further caller must be
    re-derived against that distinction, not assumed into it.
    """
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(anonymous_id=anonymous_id).exclude(
        skip_reason__in=RESCANNABLE_SKIP_REASONS
    )
    if run_id is not None:
        # The abstention half of run-scoping - see this function's own docstring.
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(run_id=run_id)
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    non_rescannable_scanned_card_ids = non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True)
    # The vote half of run-scoping.
    # WHY AN EXPLICIT `pk__in` SUBQUERY AND NOT `.exclude(printing_tags__anonymous_id=...,
    # printing_tags__run_id=...)`. The latter is the obvious spelling and it is WRONG - verified
    # against this project's own Postgres by compiling it, not reasoned about. Django does NOT
    # combine the two conditions into one subquery the same related row must satisfy; it emits
    #   NOT (EXISTS(... U1.anonymous_id = X ...) AND EXISTS(... U1.run_id = Y ...))
    # - two INDEPENDENT `EXISTS` clauses over the same table. A card carrying THIS identity's vote
    # from an OLD run plus some OTHER identity's vote from THIS run satisfies both halves and is
    # excluded, even though this identity has done nothing in this run - silently re-creating
    # exactly the cross-run suppression run-scoping exists to remove, and in the hardest direction
    # to notice (fewer cards processed, no error). This is the same negated-multi-valued-lookup
    # trap `local_identify_printing_tags._eligible_base_queryset`'s own docstring already documents
    # for the scan-log exclusion, which is why that one has always been an explicit subquery too.
    #
    # The `run_id is None` branch keeps the ORIGINAL relation exclude verbatim rather than routing
    # through the subquery as well. The two are semantically equivalent (`NOT EXISTS` vs `NOT IN`
    # over the same rows), but "equivalent" is not "identical", and several tests plus
    # `stream_backstop_sweep` assert against this query's compiled SQL; a legacy caller should get
    # byte-identical SQL, not a plausible replacement.
    if run_id is None:
        own_vote_exclusion = Q(printing_tags__anonymous_id=anonymous_id)
    else:
        own_voted_card_ids_qs = CardPrintingTag.objects.filter(anonymous_id=anonymous_id, run_id=run_id)
        if card_ids is not None:
            own_voted_card_ids_qs = own_voted_card_ids_qs.filter(card_id__in=card_ids)
        own_vote_exclusion = Q(pk__in=own_voted_card_ids_qs.values_list("card_id", flat=True))
    queryset = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED, canonical_card__isnull=True, card_type=CardTypes.CARD
        )
        .exclude(own_vote_exclusion)
        # Left keyed on the EXACT id, unchanged by the 2026-07-29 re-scoping of the
        # deductive-backfill zero-weight ruling: this exclusion is a workload choice ("don't
        # spend a scan piling a weaker vote onto a card the exact-by-construction deductive
        # backfill already covered"), not an expression of that ruling, and it predates it.
        .exclude(printing_tags__anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
        .distinct()
        .select_related("source")
    )
    if exclude_source_pks:
        queryset = queryset.exclude(source_id__in=exclude_source_pks)
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def count_below_resolution_floor(anonymous_id: str, exclude_source_pks: Optional[Iterable[int]] = None) -> int:
    """Addendum item 4's report metric: of the cards otherwise eligible, how many were skipped
    for sitting below RESOLUTION_FLOOR_DPI. A separate COUNT query (not a Python-side tally) -
    cheap even at full-catalog scale, and keeps select_candidates' own iteration untouched."""
    return _eligible_base_queryset(anonymous_id, exclude_source_pks).filter(dpi__lt=RESOLUTION_FLOOR_DPI).count()


# Sentinel for addendum item 3's demand-rank sort key: a name with NO printing Scryfall ever
# ranked (edhrec_rank is null - ~10.7% of CanonicalPrintingMetadata rows, confirmed live
# 2026-07-15) sorts LAST within its coverage tier, not first - "no demand signal" is treated as
# lowest priority, not highest, so it never masquerades as the most in-demand name by accident.
_NO_DEMAND_RANK = 2**31


def _demand_rank_for_candidates(candidates: list[CandidatePrinting]) -> int:
    """A name's demand rank is its MOST popular printing's edhrec_rank (the minimum, since lower
    = more popular) - a name can span many printings and only needs one well-known one to be
    worth prioritizing. Missing ranks are excluded from the min, not treated as 0."""
    ranks = [c.edhrec_rank for c in candidates if c.edhrec_rank is not None]
    return min(ranks) if ranks else _NO_DEMAND_RANK


def compute_covered_printing_pks() -> set[int]:
    """Addendum item 1's "covered" definition, computed fresh on every call (never cached across
    invocations) so a nightly slice's ordering reflects that night's actual DB state, including
    human confirmations made in the queue since the previous slice: a printing is covered if
    >=1 Card has `canonical_card` pointing at it (a confirmed indexing match - already a direct,
    non-vote-based signal) OR `inferred_canonical_card` pointing at it with
    `printing_tag_status=RESOLVED` (a vote-derived match, gated on RESOLVED specifically so a
    machine vote sitting unconfirmed does NOT count as coverage - redundant machine suggestions
    on an already-machine-suggested-but-unconfirmed printing still add real value, per the
    respec's "machine votes pending confirmation do NOT count as coverage")."""
    via_confirmed = Card.objects.filter(canonical_card__isnull=False).values_list("canonical_card_id", flat=True)
    via_resolved_inference = Card.objects.filter(
        inferred_canonical_card__isnull=False, printing_tag_status=PrintingTagStatus.RESOLVED
    ).values_list("inferred_canonical_card_id", flat=True)
    return set(via_confirmed) | set(via_resolved_inference)


# Part 3 addendum, abstention-aware ordering (2026-07-17, built during the content_phash
# backfill's grind - see docs/features/catalog-completion-plan.md's Part 3 section): task #109's
# "coverage-gap ordering front-loads unmatchable [high-candidate-count] names" finding, upgraded
# from a static heuristic (the earlier token-exclusion fix) into an evidence-based one, using the
# durable scan-log data Part 3 now accumulates across restarts. Interim - Part 4 (LANDS,
# artist-decomposed identification) supersedes this for genuinely over-cap names with a real fix
# rather than a demotion once it ships.
HARD_NAME_MIN_ATTEMPTS = 5


def _compute_hard_names(anonymous_id: str, min_attempts: int = HARD_NAME_MIN_ATTEMPTS) -> frozenset[str]:
    """A name qualifies as "proven hard" for THIS anonymous_id/engine when it has >= min_attempts
    distinct cards with a non-rescannable scan-log row (a genuine, repeatable negative conclusion
    - not a transient/re-scannable one) and ZERO distinct cards with a vote, both all-time (every
    run_id ever, not just the current invocation) - real accumulating signal, not a per-run
    guess. A single real vote disqualifies the name immediately and permanently re-qualifies it
    for full-priority ordering on the very next queue build, regardless of how many prior
    attempts abstained - one success is proof the name isn't structurally unmatchable, even if it
    usually is."""
    scanned_counts = dict(
        CardScanLog.objects.filter(anonymous_id=anonymous_id)
        .exclude(skip_reason__in=RESCANNABLE_SKIP_REASONS)
        .values("card__name")
        .annotate(n=Count("card_id", distinct=True))
        .values_list("card__name", "n")
    )
    voted_names = set(
        CardPrintingTag.objects.filter(anonymous_id=anonymous_id).values_list("card__name", flat=True).distinct()
    )
    return frozenset(
        name for name, attempts in scanned_counts.items() if attempts >= min_attempts and name not in voted_names
    )


def _coverage_priority_key(
    selected: SelectedCard, covered_printing_pks: set[int], hard_names: frozenset[str] = frozenset()
) -> tuple[int, int, int, int, int, int]:
    """Addendum item 1's full ordering, verbatim, with one new LEADING dimension ahead of it
    (abstention-aware ordering, above): (0) proven-hard names demoted to the back, (1) among the
    rest, names with zero covered printings first, (2) descending count of uncovered printings,
    (3) demand rank within tier (item 3), (4) fewer candidates first, (5) pk for determinism.
    Demotion, not exclusion: a proven-hard name's candidates stay reachable if this invocation's
    queue is otherwise exhausted, they just sort after every non-demoted candidate - never
    permanently lost the way a hard exclusion would be."""
    candidates = selected.candidates
    total = len(candidates)
    covered = sum(1 for c in candidates if c.pk in covered_printing_pks)
    uncovered = total - covered
    return (
        1 if selected.card.name in hard_names else 0,  # (0) proven-hard names sort last
        0 if uncovered == total else 1,  # (1) zero-covered first
        -uncovered,  # (2) descending uncovered count within each of the two tiers above
        _demand_rank_for_candidates(candidates),  # (3) ascending edhrec_rank = more popular first
        total,  # (4) fewer candidates first
        selected.card.pk,  # (5) determinism
    )


def select_candidates(
    engine: Engine,
    index: Optional[CandidateNameIndex] = None,
    exclude_source_pks: Optional[Iterable[int]] = None,
    covered_printing_pks: Optional[set[int]] = None,
) -> list[SelectedCard]:
    """Ordered by addendum item 1's coverage-gap + demand key (see _coverage_priority_key) -
    names fully covered process LAST, not never, since redundant identifications still add image
    choice per printing and border/frame attribute votes are coverage-independent value. Also
    applies addendum item 4's resolution floor (RESOLUTION_FLOOR_DPI) - a card whose source image
    is already below it is never selected, so never fetched."""
    index = index or CandidateNameIndex()
    covered_printing_pks = covered_printing_pks if covered_printing_pks is not None else compute_covered_printing_pks()
    anonymous_id = OCR_ANONYMOUS_ID if engine == "ocr" else PHASH_ANONYMOUS_ID
    hard_names = _compute_hard_names(anonymous_id)
    selected: list[SelectedCard] = []
    for card in (
        _eligible_base_queryset(anonymous_id, exclude_source_pks)
        .exclude(dpi__lt=RESOLUTION_FLOOR_DPI)
        .only("pk", "name", "identifier", "source_id", "expansion_hint", "content_phash")
        .order_by("pk")
        .iterator(chunk_size=5000)
    ):
        candidates = index.candidates_for(card.name)
        if not candidates:
            continue
        selected.append(SelectedCard(card=card, candidates=candidates))
    selected.sort(key=lambda s: _coverage_priority_key(s, covered_printing_pks, hard_names))

    if hard_names:
        demoted = [s for s in selected if s.card.name in hard_names]
        demoted_names = {s.card.name for s in demoted}
        print(
            f"[{anonymous_id}] abstention-aware ordering: {len(demoted_names)} names / "
            f"{len(demoted)} candidates demoted to the back of this invocation's queue "
            f"(>= {HARD_NAME_MIN_ATTEMPTS} attempts, 0 votes, all-time)."
        )

    return selected


# The empirically-validated OCR resolution floor (pre-scale program item 6/3c, 2026-07-15):
# a real 6-way dpi sweep (100/150/200/250/300/native) against the same 30-card sample used to
# validate the tightened crop box (see local_ocr.DEFAULT_CROP_BOX's comment) showed dpi<=150
# genuinely degrades OCR yield (3/30, 7/30 vs. an 8/30 native-resolution baseline), while
# dpi>=200 matches or EXCEEDS the native baseline (12/30, 10/30, 9/30) despite a 2-4x smaller
# payload - smaller re-encoded JPEGs plausibly render small text more cleanly than a full-res
# original in some cases, though 30 cards is too small a sample to fully explain that. 250 was
# this constant's original value: a safety margin above the empirically-best 200, not the raw
# optimum - hedged against small-sample noise while still keeping most of the bandwidth win
# (mean 728KB vs. 1.84MB native, a 2.5x reduction at that dpi). Since 2026-08-14 this re-export
# instead inherits image_cdn_fetch.DEFAULT_FETCH_DPI directly (now 460), raised for downstream
# geometric-measurement precision (see that constant's own comment), not a new OCR-yield sweep -
# 460 still clears this module's 200 floor with room to spare, so the OCR-yield conclusion above
# still holds, it's just no longer the number that set the value. PILOT-ONLY: this constant is
# local_identify_printing_tags' own default, not shared with frontend/src/features/pdf/ or
# .../download/, which need full print resolution by design and are untouched by this change.
#
# get_worker_image_url/fetch_card_image moved to cardpicker.image_cdn_fetch (2026-07-16,
# hash-at-ingest work) - re-imported below since a second, non-pilot caller
# (cardpicker.sources.update_database's ingest hook) now needs the identical fetch.
DEFAULT_FETCH_DPI = image_cdn_fetch.DEFAULT_FETCH_DPI
get_worker_image_url = image_cdn_fetch.get_worker_image_url
fetch_card_image = image_cdn_fetch.fetch_card_image


@dataclass(frozen=True)
class EngineVote:
    engine: Engine
    printing_pk: int
    confidence: float
    detail: str  # raw OCR text, or a phash distance/margin summary - for the audit checkpoint


@dataclass
class CardOutcome:
    card_id: int
    ocr_vote: Optional[EngineVote] = None
    ocr_skip_reason: str = ""
    phash_vote: Optional[EngineVote] = None
    phash_skip_reason: str = ""
    disagreement: bool = False
    # `fallback_vote`/`fallback_skip_reason`/`fallback_evidence_types` REMOVED 2026-07-29 with the
    # pass-2 printing channel itself (module docstring) - nothing computes a fallback printing
    # verdict here any more, so there is no per-card fallback state left to carry.
    border_color: Optional[str] = None
    frame_reading_attempted: bool = False
    frame_class: Optional[str] = None
    frame_mismatch: bool = False  # printing vote withheld: frame reading contradicts the match
    image_fetched: bool = False  # distinguishes "no image at all" from "image present but a
    # reading came back ambiguous/None" for the abstain counters below (bleed_class is None in
    # both cases - this field is what lets the caller tell them apart, same convention as
    # frame_reading_attempted's identical purpose for the frame abstain counter).
    # bleed classification (addendum item 7) - now computed FIRST, ahead of everything else in
    # _compute_card, per the owner-directed reordering (2026-07-15): every other fixed-fraction
    # crop box in this card's pipeline (OCR collector line, phash art crop, illus-anchor crop,
    # symbol strip, border-sample bands) gets normalized against this reading via
    # local_fallback.normalize_crop_box, so it has to be known before any of them run, not after.
    bleed_class: Optional[str] = None
    # issue #207 instrumentation: the (possibly expansion_hint-narrowed, see
    # _narrow_candidates_by_expansion_hint) candidate pks this card's engines actually matched
    # against - captured here so the write loop can record fallback's trivially-known "no
    # candidate survived any filter" (no-evidence) survivor set without re-querying or
    # re-narrowing anything itself.
    candidate_pks_considered: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CardComputeResult:
    """The output of _compute_card - everything about a card that can be computed independent of
    every OTHER card's state (no DB writes, no shared counters) - see _compute_card's own
    docstring for why this split exists (pre-scale program item 3d, pipeline concurrency)."""

    card_id: int
    fetch_attempted: bool  # counts against --fetch-budget - see run_pilot's chunked loop
    outcome: CardOutcome


@dataclass
class OcrCardResult:
    vote: Optional[EngineVote] = None
    skip_reason: str = ""
    raw_texts: list[str] = field(default_factory=list)
    # frame-style signal (docs/features/printing-tags.md's Stage 8 "frame votes" addition): did
    # ANY preprocessing variant successfully extract a collector number, independent of whether
    # it went on to validate against a real candidate? A legible collector-line format is
    # itself evidence of a post-2003 frame, whether or not the specific number matched.
    parsed_a_collector_number: bool = False


def run_ocr_for_card(
    selected: SelectedCard,
    image: Optional["Image.Image"],
    crop_box: tuple[float, float, float, float] = local_ocr.DEFAULT_CROP_BOX,
    bleed_class: Optional[str] = None,
    known_set_codes: Optional[frozenset[str]] = None,
) -> OcrCardResult:
    """`bleed_class` (from local_fallback.classify_bleed_edge, run once per card ahead of
    everything else - see run_pilot) remaps `crop_box` via local_fallback.normalize_crop_box for
    a trimmed image; a no-op otherwise.

    `known_set_codes` (2026-07-23, issue #370's own recorded follow-up - the deferred item
    `local_calculate_verdicts.py`'s own module docstring flagged: "known_set_codes() below is
    written so that engine's own selection loop could reuse it directly in a focused follow-up"):
    the SET-CODE LEXICON GATE `local_calculate_verdicts.known_set_codes()` produces, threaded
    straight through from `run_pilot` (built once per invocation there - one DB query, not one
    per card - via a deferred/local import, since a module-level import here would be circular:
    `local_calculate_verdicts.py` already imports FROM this module). Gates which "no candidate
    matched" outcome this loop reports, not whether the loop tries every variant - it already
    does (no early exit on a non-match, only on a real match). A `parsed-but-no-match` variant
    (`validate_against_candidates` found 0 candidates - `local_ocr.py`'s own outcome) only keeps
    that label, which `run_pilot`'s own write loop casts a real, confident `is_no_match=True` vote
    from, when at least one tried variant's `set_code` is either `None` (the pre-M15 collector-
    number-only case, deliberately UNAFFECTED by this gate - the same carve-out
    `calculate_join_key_verdict`'s own SET-CODE LEXICON GATE uses) or a real `known_set_codes`
    member. If EVERY variant's `parsed-but-no-match` outcome carried an out-of-lexicon `set_code`
    (un-parsed noise shaped like a set code - `local_calculate_verdicts.py`'s own module docstring
    documents a live audit finding this is 85.5% of that outcome's real-world population), the
    outcome demotes to `unknown-set-code` instead: a named, non-rescannable ABSTENTION (no vote
    cast, the same treatment `no-text` already gets), never a confident negative the parse can't
    actually back up. `None` (the default - an older/direct caller that doesn't thread this
    through, e.g. a pre-2026-07-23 test) disables the gate entirely, reproducing the exact
    pre-2026-07-23 behavior (every `parsed-but-no-match` outcome casts a vote, regardless of
    `set_code` validity) - so this is purely additive: a card whose winning variant is a genuine
    candidate match, or whose collector line is genuinely illegible, sees zero behavior change."""
    if image is None:
        return OcrCardResult(skip_reason=UNFETCHABLE_IMAGE_SKIP_REASON)

    cropped = local_ocr.crop_collector_line(image, local_fallback.normalize_crop_box(crop_box, bleed_class))
    variants = local_ocr.preprocess_variants(cropped)

    result = OcrCardResult()
    # PREREQUISITE (issue #207): local_ocr.validate_against_candidates already returns a
    # distinct "ambiguous" outcome (>1 candidate on a collector-number-only match) separately
    # from "parsed-but-no-match" (0 candidates) - this loop used to discard that distinction
    # entirely (only ever inspecting `matched`, never `reason`, on a non-match), silently
    # folding a genuinely different outcome into "parsed-but-no-match" below. Tracked across
    # every preprocessing variant (not just the last one tried) and given priority over
    # "parsed-but-no-match" if any variant produced it: "ambiguous" means the read DID match
    # something (more than one something), which is real evidence the parse was plausible, not
    # the same as every variant failing to match anything at all.
    saw_ambiguous = False
    # SET-CODE LEXICON GATE (2026-07-23, issue #370's own recorded follow-up - see this
    # function's own `known_set_codes` docstring paragraph above for the full mechanism): True
    # once ANY tried variant's "parsed-but-no-match" outcome carries trustworthy signal (a real/
    # lexicon set code, or a genuine pre-M15 collector-number-only parse) rather than un-parsed
    # noise shaped like a set code - decides below whether the final outcome keeps the real
    # "parsed-but-no-match" label (casts a vote) or demotes to "unknown-set-code" (abstains).
    saw_lexicon_valid_no_match = False
    for variant in variants:
        raw_text = local_ocr.run_tesseract(variant)
        result.raw_texts.append(raw_text)
        parsed = local_ocr.parse_collector_line(raw_text)
        if parsed.collector_number is not None:
            result.parsed_a_collector_number = True
        matched, reason = local_ocr.validate_against_candidates(parsed, selected.candidates)
        if matched is not None:
            confidence = OCR_CONFIDENCE_BOTH if parsed.set_code is not None else OCR_CONFIDENCE_COLLECTOR_ONLY
            result.vote = EngineVote(
                engine="ocr", printing_pk=matched.pk, confidence=confidence, detail=raw_text.strip()
            )
            return result
        if reason == OCR_AMBIGUOUS_SKIP_REASON:
            saw_ambiguous = True
        elif reason == PARSED_BUT_NO_MATCH_SKIP_REASON and (
            parsed.set_code is None or known_set_codes is None or parsed.set_code in known_set_codes
        ):
            saw_lexicon_valid_no_match = True
    if saw_ambiguous:
        result.skip_reason = OCR_AMBIGUOUS_SKIP_REASON
    elif saw_lexicon_valid_no_match:
        result.skip_reason = PARSED_BUT_NO_MATCH_SKIP_REASON
    elif result.parsed_a_collector_number:
        # every "parsed-but-no-match" outcome this loop saw carried an out-of-lexicon set_code -
        # a distinct, non-rescannable ABSTENTION (see this function's own known_set_codes
        # docstring paragraph), not the confident "parsed-but-no-match" negative.
        result.skip_reason = OCR_UNKNOWN_SET_CODE_SKIP_REASON
    else:
        result.skip_reason = OCR_NO_TEXT_SKIP_REASON
    return result


def _hamming_distance(a: int, b: int, bits: int = 64) -> int:
    """Standard Hamming distance (popcount of XOR) between two `bits`-wide two's-complement
    ints - mathematically identical to `imagehash.ImageHash.__sub__` on the two hashes those
    ints encode (verified empirically against imagehash's own subtraction across 20 random
    64-bit hash pairs before use, not assumed), but computed here as pure integer arithmetic
    with no dependency on any of local_phash.py's own (PROTECTED CORE, see
    docs/upstreaming/license-provenance.md §2) private helpers or decision logic."""
    mask = (1 << bits) - 1
    return bin((a & mask) ^ (b & mask)).count("1")


def _classify_no_clear_winner(
    card_hash: int,
    candidates_with_hashes: list[tuple["CandidatePrinting", int]],
    distance_threshold: int,
    margin: int,
) -> str:
    """Issue #207 instrumentation: local_phash.find_best_match (PROTECTED CORE) deliberately
    folds two different reasons a card fails to produce a phash vote into one "no-clear-winner"
    skip_reason - the best distance was over threshold, or the runner-up was too close behind it.
    Splitting them for a future ranked-vote decision needs to know which applies, without editing
    that function's own decision logic. This re-derives the same distance ranking from the exact
    same inputs the caller already computed and passed to find_best_match (`card_hash`,
    `candidates_with_hashes`) using only pure arithmetic (_hamming_distance, not a re-tuned or
    independently-invented comparison) - `distance_threshold`/`margin` are still find_best_match's
    own values, passed straight through, just re-applied here to classify which branch fired.
    Only ever called when find_best_match itself already returned "no-clear-winner" (i.e.
    `candidates_with_hashes` is non-empty - "no-hashable-candidates" is find_best_match's own
    distinct outcome for the empty case and is never reclassified)."""
    scored = sorted(
        (
            (candidate, _hamming_distance(card_hash, candidate_hash))
            for candidate, candidate_hash in candidates_with_hashes
        ),
        key=lambda pair: pair[1],
    )
    best_distance = scored[0][1]
    runner_up_distance = scored[1][1] if len(scored) > 1 else None
    if best_distance > distance_threshold:
        return PHASH_NO_CLEAR_WINNER_DISTANCE_SKIP_REASON
    assert runner_up_distance is not None and (runner_up_distance - best_distance) <= margin  # the only other way
    # find_best_match returns "no-clear-winner" - a margin-too-tight runner-up, not a threshold miss.
    return PHASH_NO_CLEAR_WINNER_MARGIN_SKIP_REASON


def run_phash_for_card(
    selected: SelectedCard,
    image: Optional["Image.Image"],
    distance_threshold: int = local_phash.DEFAULT_DISTANCE_THRESHOLD,
    margin: int = local_phash.DEFAULT_MARGIN,
    max_candidates: int = PHASH_MAX_CANDIDATES,
    bleed_class: Optional[str] = None,
) -> tuple[Optional[EngineVote], str]:
    """`bleed_class` (from local_fallback.classify_bleed_edge, run once per card ahead of
    everything else - see run_pilot) remaps local_phash.ART_CROP_BOX via
    local_fallback.normalize_crop_box for a trimmed image; a no-op otherwise."""
    # checked first, before any candidate-hash fetch - see PHASH_MAX_CANDIDATES' comment for
    # why this matters (basic lands/staple commons can have hundreds of candidates)
    if len(selected.candidates) > max_candidates:
        return None, PHASH_TOO_MANY_CANDIDATES_SKIP_REASON

    if image is None:
        return None, UNFETCHABLE_IMAGE_SKIP_REASON

    card_hash = local_phash.compute_card_art_hash(image, bleed_class)

    canonicals_by_pk = {c.pk: c for c in CanonicalCard.objects.filter(pk__in=[c.pk for c in selected.candidates])}
    candidates_with_hashes: list[tuple[CandidatePrinting, int]] = []
    for candidate in selected.candidates:
        canonical = canonicals_by_pk.get(candidate.pk)
        if canonical is None:
            continue
        candidate_hash = local_phash.get_or_compute_canonical_hash(canonical)
        if candidate_hash is not None:
            candidates_with_hashes.append((candidate, candidate_hash))

    match, reason = local_phash.find_best_match(card_hash, candidates_with_hashes, distance_threshold, margin)
    if match is None:
        if reason == PHASH_NO_CLEAR_WINNER_SKIP_REASON:
            reason = _classify_no_clear_winner(card_hash, candidates_with_hashes, distance_threshold, margin)
        return None, reason
    detail = f"distance={match.distance} runner_up={match.runner_up_distance}"
    return EngineVote(engine="phash", printing_pk=match.candidate.pk, confidence=PHASH_CONFIDENCE, detail=detail), ""


# Default concurrent worker count (pre-scale program item 3d, 2026-07-15): measured, not
# assumed, against this box's real constraint - 2 CPU cores total, shared with 5 live production
# containers (Django/nginx/Postgres/Elasticsearch/worker). A live-contention test (10 real
# candidate cards, dry, fetch+OCR+phash only) compared this box's live API latency under three
# conditions: idle (79.8ms mean/94.7ms p95), the CURRENT single-threaded pilot running (88.7ms/
# 126.1ms), and a 2-worker concurrent pool running (93.9ms/135.7ms) - only ~5ms extra mean
# latency for 2 workers over the ALREADY-EXISTING single-threaded impact, while wall clock for
# the same 10 cards dropped from 13.42s to 6.34s (near-ideal ~2.1x speedup matching the 2-core
# count - tesseract's subprocess-based OCR genuinely parallelizes here, the GIL is released
# during the subprocess wait). 2 matches the core count exactly; more workers would only add
# contention without real additional parallelism on this box.
DEFAULT_WORKERS = 2


def _narrow_candidates_by_expansion_hint(selected: SelectedCard) -> SelectedCard:
    """Fast-follow (2026-07-16): a confidence PRIOR, not an entailment - narrows the candidate
    list an engine considers when the card's own `expansion_hint` (extracted from its filename
    at import time by `cardpicker.tags.Tags.extract` - a lone set-code bracket token that
    didn't resolve a direct CanonicalCard match, e.g. "[UNF]" with no collector number) matches
    at least one of its name's real candidates. Never narrows to empty: if the hint matches zero
    candidates (a real, measured ~9% data-quality case - the hint may be stale or mismatched),
    the full candidate list is used instead, exactly as if there were no hint at all - narrowing
    that made matching IMPOSSIBLE would be worse than not narrowing.

    Scoped to engine-matching ONLY - never call this from select_candidates/
    compute_covered_printing_pks/anything computing coverage or ordering, which need the true,
    unnarrowed candidate set to stay correct. The returned SelectedCard is a LOCAL substitute
    used only for this card's own OCR/phash calls within _compute_card; nothing
    downstream (run_pilot's own all_selected_by_card_id) ever sees the narrowed version.

    Real yield (measured live, 2026-07-15): of 2,466 pilot-eligible cards with a real
    expansion_hint, 645 currently exceed PHASH_MAX_CANDIDATES and get skipped entirely -
    narrowing brings 407 of those back under the cap, giving phash a real shot where it
    currently never runs at all. OCR's own exact-match logic doesn't benefit from narrowing
    (a smaller candidate list doesn't change whether a parsed code+number is IN it) - this is a
    phash-only unlock in practice, though harmless to apply uniformly to all three engines."""
    hint = selected.card.expansion_hint
    if not hint:
        return selected
    narrowed = [c for c in selected.candidates if c.expansion_code == hint]
    if not narrowed:
        return selected
    return SelectedCard(card=selected.card, candidates=narrowed)


def _compute_card(
    selected: SelectedCard,
    ocr_selected_ids: set[int],
    phash_selected_ids: set[int],
    ocr_crop_box: tuple[float, float, float, float],
    phash_distance_threshold: int,
    phash_margin: int,
    phash_max_candidates: int,
    fetch_dpi: Optional[int],
    known_set_codes: Optional[frozenset[str]] = None,
) -> CardComputeResult:
    """The parallelizable half of a card's work (pre-scale program item 3d): fetch + every
    read-only heuristic reading (OCR, phash, border/frame/bleed classification) - no DB
    writes, no shared/nonlocal state, safe to run concurrently across cards
    via ThreadPoolExecutor.map() (see run_pilot's chunked loop). Deliberately does NOT include
    the ground-truth-preferred attribute override or the frame-mismatch consistency check -
    both of those are tightly coupled to the write/consensus decision (which candidate_vote
    ultimately gets accepted) and stay in run_pilot's own sequential loop, same as before this
    split.

    Bleed classification runs FIRST, ahead of everything else (owner-directed reordering,
    2026-07-15) - it's the one reading every other fixed-fraction crop box in this function
    needs (via local_fallback.normalize_crop_box) to know whether to correct itself for a
    trimmed image, so it has to be available before OCR/phash/illus-anchor/border/symbol crop.

    `known_set_codes` (2026-07-23, issue #370's own recorded follow-up): built once by
    `run_pilot` and forwarded straight through to `run_ocr_for_card` - see that function's own
    docstring for the SET-CODE LEXICON GATE this controls.
    """
    card_id = selected.card.pk
    outcome = CardOutcome(card_id=card_id)
    fetch_attempted = get_worker_image_url(selected.card, fetch_dpi) is not None
    image = fetch_card_image(selected.card, fetch_dpi)
    ocr_raw_texts: list[str] = []

    # fast-follow (2026-07-16): narrow the candidate list every engine below sees, using this
    # card's own expansion_hint if it has one - `selected.card`/`card_id` above still reference
    # the ORIGINAL card either way; only the candidate list used for matching changes.
    selected = _narrow_candidates_by_expansion_hint(selected)
    outcome.candidate_pks_considered = [c.pk for c in selected.candidates]

    outcome.image_fetched = image is not None
    bleed_class = local_fallback.classify_bleed_edge(image) if image is not None else None
    outcome.bleed_class = bleed_class

    if card_id in ocr_selected_ids:
        ocr_result = run_ocr_for_card(selected, image, ocr_crop_box, bleed_class, known_set_codes)
        outcome.ocr_vote, outcome.ocr_skip_reason = ocr_result.vote, ocr_result.skip_reason
        ocr_raw_texts = ocr_result.raw_texts
    if card_id in phash_selected_ids:
        outcome.phash_vote, outcome.phash_skip_reason = run_phash_for_card(
            selected, image, phash_distance_threshold, phash_margin, phash_max_candidates, bleed_class
        )

    if outcome.ocr_vote is not None and outcome.phash_vote is not None:
        if outcome.ocr_vote.printing_pk != outcome.phash_vote.printing_pk:
            outcome.disagreement = True

    if image is not None:
        outcome.border_color = local_fallback.classify_border_color(image)
        illus_anchor_fired, _artist_name = local_fallback.detect_illus_anchor(image, ocr_raw_texts, bleed_class)
        # "unknown-set-code" (2026-07-23, the SET-CODE LEXICON GATE - see run_ocr_for_card's own
        # known_set_codes docstring paragraph) is included alongside "parsed-but-no-match" here
        # for the same reason OcrCardResult.parsed_a_collector_number's own docstring already
        # gives: a legible collector-line FORMAT is evidence of a post-2003 frame independent of
        # whether the specific number matched a real candidate OR whether its set_code happened
        # to be a real lexicon member - this signal is orthogonal to lexicon validity by design.
        parsed_a_collector_number = card_id in ocr_selected_ids and bool(
            outcome.ocr_vote is not None
            or outcome.ocr_skip_reason == "parsed-but-no-match"
            or outcome.ocr_skip_reason == "unknown-set-code"
        )
        outcome.frame_reading_attempted = True
        outcome.frame_class = local_fallback.classify_frame_style(parsed_a_collector_number, illus_anchor_fired)

    # PASS 2 (`local_fallback.run_fallback_for_card` -> a "local-fallback-v1" printing vote for
    # every card pass 1 missed) USED TO RUN HERE, and is RETIRED as of 2026-07-29 - see the
    # module docstring for the ruling, the measurement behind it, and what deliberately survives
    # it. Nothing calls `run_fallback_for_card` from this module any more; the border/artist/
    # symbol evidence combination it performed is now cast ONCE, by
    # `local_calculate_verdicts.calculate_fallback_verdict` off stored `ImageEvidence`. Note that
    # `detect_illus_anchor` above is NOT part of that retirement: it feeds the frame-style
    # classifier for EVERY card, independent of whether any printing vote is cast, and it was
    # already a separate call before pass 2 ran.

    return CardComputeResult(card_id=card_id, fetch_attempted=fetch_attempted, outcome=outcome)


@dataclass
class PilotResult:
    engine: str
    dry_run: bool = False
    # the run_id this invocation stamped every vote it wrote with (docs/features/
    # catalog-completion-plan.md's Part 1) - printed by the command so an operator can target a
    # future purge_machine_votes --run-id. Empty string means run_pilot wasn't actually invoked
    # for this engine (a PilotResult can exist as a placeholder before any work happens).
    run_id: str = ""
    votes_written: int = 0
    # issue #207: real is_no_match votes cast from a genuine whole-candidate-set no-match
    # conclusion (OCR's "parsed-but-no-match"; fallback's "eliminated" was the other, retired
    # 2026-07-29 with the pass-2 printing channel itself) - counted separately
    # from votes_written (which names a specific printing) rather than folded into it, so
    # existing callers/tests reading votes_written as "a printing was identified" don't silently
    # change meaning.
    no_match_votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    disagreements: list[dict[str, object]] = field(default_factory=list)
    audit: list[dict[str, object]] = field(default_factory=list)  # per-card checkpoint detail
    gate_violations: list[int] = field(default_factory=list)
    fetch_budget_exhausted: bool = False
    cards_not_attempted_this_invocation: int = 0
    # addendum item 4 (2026-07-15): cards otherwise eligible but skipped in the selection query
    # itself for sitting below RESOLUTION_FLOOR_DPI - never fetched, not just never OCR'd/hashed.
    # Its own skip category, separate from skip_counts (which is populated downstream of a fetch
    # attempt, not at selection time).
    skipped_below_resolution_floor: int = 0


@dataclass
class AttributeReport:
    """Side-effect votes cast alongside printing identification, and census-only findings that
    never write anything (docs/features/printing-tags.md's Stage 8 "border evidence does
    double duty" and "frame votes" additions)."""

    border_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    frame_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    frame_abstain_count: int = 0
    frame_mismatches: list[dict[str, object]] = field(default_factory=list)  # up to 10, for the report
    # of the totals above, how many came from the matched printing's own CanonicalPrintingMetadata
    # (ground truth) rather than this module's pixel/OCR heuristic - see run_pilot's
    # ground-truth-preferred wiring.
    border_ground_truth_count: int = 0
    frame_ground_truth_count: int = 0
    # addendum item 7 (2026-07-15): bleed-edge classification, votes on the pre-existing
    # `appropriate-bleed` SENSITIVE tag (local_fallback.classify_bleed_edge/cast_bleed_edge_vote).
    # No ground-truth counterpart - unlike border/frame, there's no Scryfall field encoding this.
    bleed_votes_by_class: dict[str, int] = field(default_factory=lambda: collections.defaultdict(int))
    bleed_abstain_count: int = 0
    # addendum item 1 (2026-07-15): the run's real progress metric, per the respec - "uncovered-
    # printings CLOSED that night, not raw votes". A run-level (not per-engine) count: of the
    # printings in scope this invocation that were uncovered at the start, how many are covered
    # (see compute_covered_printing_pks) by the time it ends. Almost always 0 for a pilot-only
    # run BY DESIGN, not a bug: a pilot vote is never a direct resolve (module docstring), and
    # "covered" explicitly excludes unresolved machine votes - a printing only counts as closed
    # here once a human confirms it in the queue and pushes it to RESOLVED, which is why item 5
    # (queue mirror, follow-up) front-loads human attention onto the same names this run
    # front-loaded machine effort onto. Always 0 in dry_run (nothing is written, so nothing can
    # have newly resolved).
    uncovered_printings_closed: int = 0
    # addendum item 2a (2026-07-15) -> superseded 2026-07-16: cluster dedup report - see
    # cardpicker.local_clustering.compute_two_threshold_clusters.
    cluster_count: int = 0
    cards_absorbed_into_clusters: int = 0


# THE BORDER/FRAME AGREEMENT CHECK'S OWN VOCABULARY AND EXTRACTOR REQUIREMENT (2026-07-30).
# `printing_attribute_disagreement` below is the single implementation of "does this card's
# already-stored evidence CONTRADICT this candidate printing"; these are the two answers it gives.
# The strings match `local_calculate_verdicts`' own `JOIN_KEY_BORDER_MISMATCH_SKIP_REASON` /
# `JOIN_KEY_FRAME_MISMATCH_SKIP_REASON` values, deliberately rather than incidentally - they name
# the same finding, and the per-calculator constants stay separate only because each calculator
# owns its own skip vocabulary under a different `anonymous_id`.
ATTRIBUTE_BORDER_MISMATCH = "border-mismatch"
ATTRIBUTE_FRAME_MISMATCH = "frame-mismatch"

# `classify_frame_style` takes exactly two inputs and each comes from a DIFFERENT extractor:
# `collector_line_collector_number` from `collector_line_ocr`, `illus_anchor_fired` from
# `artist_ocr`. `local_calculate_verdicts.FRAME_CHECK_REQUIRED_EXTRACTOR_KEYS` is now an alias for
# this, so the requirement has one definition and cannot drift between callers.
FRAME_CHECK_REQUIRED_EXTRACTOR_KEYS = frozenset({"collector_line_ocr", "artist_ocr"})


def printing_attribute_disagreement(evidence: Any, metadata: Any) -> Optional[str]:
    """
    DOES THIS CARD'S ALREADY-STORED EVIDENCE CONTRADICT THIS CANDIDATE PRINTING? Returns the
    disagreement's name (`ATTRIBUTE_BORDER_MISMATCH` / `ATTRIBUTE_FRAME_MISMATCH`) or `None` for
    "nothing contradicts it". NO IMAGE FETCH, no OCR, no new extraction - every input is a field
    already sitting on the row.

    Lifted verbatim out of `local_calculate_verdicts._apply_agreement_checks` (2026-07-30) so it
    has ONE implementation and two callers: that function, unchanged in behaviour, and
    `run_name_frequency_elimination`, which needed exactly this check and had no visual cross-check
    of any kind. It lives HERE rather than beside its original caller purely because of import
    direction - `local_calculate_verdicts` already imports this module and never the reverse, so
    this is the only side of the pair both callers can reach without a cycle.

    "MISSING DATA IS NOT EVIDENCE" throughout, which is this check's oldest rule and the one most
    easily broken by accident:
      * no `metadata` sidecar at all -> nothing to compare, no disagreement.
      * a blank `layout_class` or a blank `metadata.border_color` -> that half is skipped.
      * `frame_style_is_consistent` returns True whenever either side is unresolved (see its own
        docstring), so an unclassifiable frame never manufactures a mismatch.

    THE FRAME HALF IS GATED ON `artist_ocr` HAVING ACTUALLY RUN (PR #656), and that gate is the
    single best reason this is shared rather than re-derived. `illus_anchor_fired` is NULLABLE and
    `bool(None)` is `False`, indistinguishable from "artist_ocr ran and found no anchor". With no
    collector number either, `classify_frame_style` then confidently answers "modern" for a card it
    has no anchor evidence about at all, and a genuine OLD-frame printing gets vetoed. That is the
    one degradation here that is STRICT rather than permissive, so an absent `artist_ocr` skips the
    frame half entirely rather than evaluating it on invented input. A second implementation of
    this check would very likely have re-introduced that trap.

    BORDER IS A DIRECT STRING COMPARISON, FRAME IS NOT. `layout_class` mirrors
    `local_fallback.classify_border_color`'s return convention ("black"/"white"/"silver"/
    "borderless"), the SAME value space Scryfall's own `border_color` uses - so no remapping is
    correct there. `frame` is a Scryfall frame YEAR ("1993"/"2015"/...) and must go through
    `FRAME_VALUE_TO_CLASS`, which is what `frame_style_is_consistent` owns.
    """
    if metadata is None or evidence is None:
        return None

    layout_class = getattr(evidence, "layout_class", None)
    border_color = getattr(metadata, "border_color", None)
    if layout_class and border_color and layout_class != border_color:
        return ATTRIBUTE_BORDER_MISMATCH

    if FRAME_CHECK_REQUIRED_EXTRACTOR_KEYS <= (evidence.extractor_versions or {}).keys():
        frame_class = local_fallback.classify_frame_style(
            parsed_a_collector_number=bool(evidence.collector_line_collector_number),
            illus_anchor_fired=bool(evidence.illus_anchor_fired),
        )
        if not local_fallback.frame_style_is_consistent(frame_class, getattr(metadata, "frame", None)):
            return ATTRIBUTE_FRAME_MISMATCH

    return None


def build_propagated_cluster_votes(
    *,
    representative_card_id: int,
    printing_pk: int,
    anonymous_id: str,
    confidence: float,
    run_id: Optional[str],
    members_by_representative: dict[int, list[int]],
    members_already_voted: set[int],
    source: VoteSource = VoteSource.OCR,
) -> list[CardPrintingTag]:
    """
    THE CLUSTER-VOTE PROPAGATION RULE (addendum item 2a), lifted out of `run_pilot`'s own
    `propagate_cluster_vote` closure 2026-07-30 so it has exactly one implementation and two
    callers - `run_pilot` (unchanged behaviour: the closure now calls this and does its own
    batching) and `run_pipeline`, the one-command monolith, which had no way to reach it at all
    while it lived inside a closure over six pieces of `run_pilot`-local state.

    An accepted vote on a distance-0 cluster REPRESENTATIVE propagates as an identical vote (same
    `anonymous_id`, `printing`, `confidence`) to every OTHER member of its cluster. Absorbed
    members are, by construction, cards whose stored `content_phash` is bit-identical to the
    representative's - the same image - so this is an identity property first and a throughput
    lever second: it is what makes an identity group AGREE, and it does it without the member
    ever being fetched or computed.

    `members_already_voted` is the caller's pre-computed set of member card ids that ALREADY carry
    a vote under this same `anonymous_id` (one query, up front, never re-queried per call - see
    `run_pilot`'s own call site for why a member can legitimately be in that state). Propagating
    to one anyway would violate `CardPrintingTag`'s own (card, printing, anonymous_id) uniqueness
    constraint, and would silently double-vote or overwrite regardless.

    Returns the rows to write; it never writes them itself, so the caller keeps ownership of its
    own batching, purge-and-write discipline and gate accounting.
    """
    member_ids = members_by_representative.get(representative_card_id, [])
    return [
        CardPrintingTag(
            card_id=member_id,
            printing_id=printing_pk,
            is_no_match=False,
            anonymous_id=anonymous_id,
            source=source,
            confidence=confidence,
            run_id=run_id,
        )
        for member_id in member_ids
        if member_id not in members_already_voted
    ]


def run_pilot(
    engine: Literal["ocr", "phash", "both"] = "both",
    limit: int = 300,
    dry_run: bool = False,
    nice: bool = True,
    ocr_crop_box: tuple[float, float, float, float] = local_ocr.DEFAULT_CROP_BOX,
    phash_distance_threshold: int = local_phash.DEFAULT_DISTANCE_THRESHOLD,
    phash_margin: int = local_phash.DEFAULT_MARGIN,
    phash_max_candidates: int = PHASH_MAX_CANDIDATES,
    exclude_source_pks_by_engine: Optional[dict[Engine, list[int]]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_every: int = 50,
    fetch_budget: Optional[int] = None,
    fetch_dpi: Optional[int] = DEFAULT_FETCH_DPI,
    workers: int = DEFAULT_WORKERS,
    run_id: Optional[str] = None,
) -> tuple[dict[str, PilotResult], AttributeReport]:
    if nice:
        try:
            os.nice(15)
        except (AttributeError, PermissionError, OSError):
            logger.warning("os.nice unavailable in this environment - --nice throttling is CPU-yield-only")

    # Part 1 (docs/features/catalog-completion-plan.md): accepting an explicit value (rather
    # than always generating one internally) keeps this deterministic for tests and lets the
    # management command log/report it before any work starts.
    run_id = run_id or generate_run_id()
    # Part 3 addendum item 3: real-rate ETA math for the progress line below, not a guess -
    # wall-clock since THIS invocation started, measured against candidates actually processed
    # so far in it (not the corpus-wide unresolved count, which the progress line reports
    # separately and which this invocation alone can't project a rate against).
    run_start_time = time.time()

    index = CandidateNameIndex()
    # Set-code lexicon (2026-07-23, issue #370's own recorded follow-up - see run_ocr_for_card's
    # own known_set_codes docstring paragraph for the full mechanism this feeds): a DEFERRED
    # import, not a module-level one - local_calculate_verdicts.py already imports FROM this
    # module (CandidateNameIndex/generate_run_id/etc above), so a module-level import back here
    # would be circular. Built ONCE per invocation (one DB query, the same "call-once-reuse-
    # across-the-batch" convention CandidateNameIndex() above already follows), then threaded
    # through _compute_card/run_ocr_for_card via the functools.partial below rather than queried
    # per card.
    from cardpicker.local_calculate_verdicts import known_set_codes as _known_set_codes

    ocr_known_set_codes = _known_set_codes()
    engines_to_run: list[Engine] = ["ocr", "phash"] if engine == "both" else [engine]
    results: dict[str, PilotResult] = {e: PilotResult(engine=e, dry_run=dry_run, run_id=run_id) for e in engines_to_run}
    # No `results["fallback"]` entry any more: the pass-2 printing channel that produced it is
    # retired (module docstring), so a permanently all-zero PilotResult would only misreport a
    # calculator that no longer exists as one that ran and found nothing.
    attributes = AttributeReport()
    exclude_source_pks_by_engine = exclude_source_pks_by_engine or {}
    # addendum item 1 (2026-07-15): computed ONCE per invocation (not once per engine) and
    # reused for both select_candidates' ordering and the "uncovered_printings_closed" delta
    # below - fresh every call, per the respec's "refreshed at each nightly slice start" so
    # human confirmations from the queue since the last slice reshape this slice's ordering too.
    covered_printing_pks_before = compute_covered_printing_pks()
    selected_by_engine = {
        e: select_candidates(e, index, exclude_source_pks_by_engine.get(e), covered_printing_pks_before)[:limit]
        for e in engines_to_run
    }
    # Abstention-aware ordering (Part 3 addendum): one aggregate line alongside this invocation's
    # other startup context (run_id, git_sha - see the management command), combining every
    # engine's own per-engine demotion print (inside select_candidates) into a single total.
    total_hard_candidates = sum(
        1
        for e in engines_to_run
        for s in selected_by_engine[e]
        if s.card.name in _compute_hard_names(OCR_ANONYMOUS_ID if e == "ocr" else PHASH_ANONYMOUS_ID)
    )
    if total_hard_candidates:
        print(f"run_id={run_id} abstention-aware ordering demoted {total_hard_candidates} candidates total this run.")
    for e in engines_to_run:
        anonymous_id = OCR_ANONYMOUS_ID if e == "ocr" else PHASH_ANONYMOUS_ID
        results[e].skipped_below_resolution_floor = count_below_resolution_floor(
            anonymous_id, exclude_source_pks_by_engine.get(e)
        )

    # when both engines run, process the union of cards either engine selected so agreement/
    # disagreement can be evaluated per card - each engine still only ever votes on a card it
    # itself selected (its own eligibility/exclusion rules still apply independently).
    all_selected_by_card_id: dict[int, SelectedCard] = {}
    for e in engines_to_run:
        for s in selected_by_engine[e]:
            all_selected_by_card_id.setdefault(s.card.pk, s)

    # addendum item 1's "uncovered-printings closed" metric: every printing pk that was
    # uncovered at the start and belonged to some processed card's candidate list - checked
    # against fresh coverage state after the run below (dry_run: nothing is written, so this
    # set is used but the "after" recheck will always come back empty - see AttributeReport's
    # uncovered_printings_closed docstring).
    printing_pks_in_scope: set[int] = set()
    for s in all_selected_by_card_id.values():
        printing_pks_in_scope.update(c.pk for c in s.candidates)
    uncovered_printing_pks_in_scope = printing_pks_in_scope - covered_printing_pks_before

    # addendum item 2a (2026-07-15) -> SUPERSEDED (2026-07-16, hash-at-ingest work,
    # docs/features/printing-tags.md): the disabled fetch-based pre-pass
    # (compute_own_image_clusters, see git history for cf1bf007's disablement) is replaced by a
    # pure DB-column read over Card.content_phash (local_clustering.
    # compute_two_threshold_clusters) - no network fetch, no sequential pre-pass, no
    # observability gap. The disabled pre-pass's own fixed ~21.6h sequential cost (the reason it
    # was disabled) simply doesn't exist in this design; see local_clustering's module docstring
    # for the full d=0/d<=2 semantics. Cards without a stored hash yet (not ingested/backfilled)
    # cluster as singletons - the same safe fallback the old pre-pass had for a failed fetch.
    cluster_result = local_clustering.compute_two_threshold_clusters(list(all_selected_by_card_id.values()))
    attributes.cluster_count = len(cluster_result.members_by_representative)
    attributes.cards_absorbed_into_clusters = sum(len(m) for m in cluster_result.members_by_representative.values())
    # Only representatives reach _compute_card below - an absorbed (distance-0) member's vote
    # comes from propagate_cluster_vote in the write loop instead. Restores the filtering the
    # original (pre-disablement) implementation had (`all_selected_by_card_id = {s.card.pk: s
    # for s in cluster_result.representatives}`) - the no-op disabled version dropped this since
    # it was a no-op anyway with an always-empty members_by_representative.
    _absorbed_member_ids = {m for members in cluster_result.members_by_representative.values() for m in members}
    if _absorbed_member_ids:
        all_selected_by_card_id = {
            card_id: s for card_id, s in all_selected_by_card_id.items() if card_id not in _absorbed_member_ids
        }

    # a member can be a cluster member (via one engine's selection) while ALREADY having its own
    # vote from a DIFFERENT engine's anonymous_id from a prior invocation - e.g. only
    # phash-eligible this run (so it appears here) but already has an OCR vote from a previous
    # run (which is exactly why it was excluded from THIS run's OCR selection). Propagating a
    # same-anonymous_id vote to it anyway would violate CardPrintingTag's own
    # (card, printing, anonymous_id) uniqueness constraint - checked once, up front, per
    # anonymous_id, not re-queried per propagation call.
    _cluster_member_ids = {m for members in cluster_result.members_by_representative.values() for m in members}
    members_already_voted_by_anonymous_id: dict[str, set[int]] = collections.defaultdict(set)
    if _cluster_member_ids:
        for _card_id, _anonymous_id in CardPrintingTag.objects.filter(
            card_id__in=_cluster_member_ids,
            # FALLBACK_ANONYMOUS_ID dropped from this lookup 2026-07-29 with the pass-2 printing
            # channel (module docstring): nothing propagates a cluster vote under that identity
            # any more, so there is no uniqueness collision left for it to guard against.
            anonymous_id__in=[OCR_ANONYMOUS_ID, PHASH_ANONYMOUS_ID],
        ).values_list("card_id", "anonymous_id"):
            members_already_voted_by_anonymous_id[_anonymous_id].add(_card_id)

    # The pass-2 fallback's own `already_fallback_covered` idempotence set (a prior run's
    # "local-fallback-v1" vote or non-rescannable scan-log row) was removed here 2026-07-29 with
    # the channel it guarded - it existed only because the fallback had no selection query of its
    # own to apply RESCANNABLE_SKIP_REASONS through.

    def _absorb_engine_selection(engine_selected_ids: set[int]) -> set[int]:
        # a cluster's representative must run an engine if EITHER it or any absorbed member was
        # independently selected for that engine - otherwise clustering could silently drop an
        # engine's own eligibility just because the specific card that happened to become the
        # representative wasn't itself selected for it.
        absorbed = set(engine_selected_ids)
        for representative_id, member_ids in cluster_result.members_by_representative.items():
            if any(m in engine_selected_ids for m in member_ids):
                absorbed.add(representative_id)
        return absorbed

    ocr_selected_ids = _absorb_engine_selection({s.card.pk for s in selected_by_engine.get("ocr", [])})
    phash_selected_ids = _absorb_engine_selection({s.card.pk for s in selected_by_engine.get("phash", [])})

    # Checkpointing (Stage 8 pre-scale program item 2): a multi-day unattended run must survive
    # a kill without losing everything accumulated since the last flush. Matches
    # cardpicker.deductive_backfill.run_backfill's periodic-flush pattern (a plain re-invocation
    # resumes cleanly with no separate checkpoint file, since select_candidates already excludes
    # any card with an existing vote from this engine's own anonymous_id), but deliberately
    # DIVERGES from that precedent on ONE point: the gate check runs after every flush here, not
    # once at the very end. deductive_backfill's votes are provably exact by construction (a gate
    # violation there is structurally impossible), so a single end-of-run check is just belt-and-
    # suspenders; this pilot's OCR/phash votes are explicitly weaker, lower-confidence
    # signal (module docstring) where a real violation is more plausible, and a kill is an
    # EXPECTED event for a multi-day run (the whole reason this checkpointing exists) - a
    # violation in an already-flushed batch must not sit undetected in the DB indefinitely just
    # because the process died before reaching the final check.
    written_card_ids: list[int] = []
    all_gate_violations: list[int] = []
    votes_batch: list[CardPrintingTag] = []
    tag_votes_batch: list[CardTagVote] = []
    batch_written_card_ids: list[int] = []
    # Part 3 addendum item 3: abstention evidence, batched and flushed alongside votes (same
    # checkpoint granularity, no separate per-card write) - see RESCANNABLE_SKIP_REASONS and
    # _eligible_base_queryset for how these rows feed back into future runs' resume logic.
    scan_log_batch: list[CardScanLog] = []

    def flush() -> None:
        nonlocal votes_batch, tag_votes_batch, batch_written_card_ids, scan_log_batch
        if dry_run:
            votes_batch, tag_votes_batch, batch_written_card_ids, scan_log_batch = [], [], [], []
            return
        # CANCEL-SAFETY (2026-07-28): this flush was already better placed than most - a kill
        # loses at most one chunk, by design (see the checkpointing comment above) - but the purge
        # and the insert inside a chunk were still two untransacted statements, so a kill landing
        # between them deleted this chunk's cards' previous votes and wrote nothing back: strictly
        # worse than losing the chunk, because the pre-existing votes went too.
        # `vote_write.purge_and_write_votes` makes each pair atomic and scopes the purge to
        # exactly the rows it inserts. Passing `anonymous_id=None` reproduces the per-identity
        # grouping this flush did by hand: a pilot batch legitimately mixes engines' identities
        # (OCR/phash, plus propagated cluster votes), and each row must be purged under its OWN
        # family, never one representative's.
        #
        # RETIREMENT LOCK (2026-07-29, module docstring): the one place every printing vote this
        # module casts passes through, so the one place a retired identity can be caught before
        # it lands. Family-keyed, so a "-v2" redeploy of a retired calculator is caught too. This
        # deliberately does NOT screen `tag_votes_batch`: the SAME "local-fallback-v1" identity
        # still legitimately casts border/frame/bleed attribute chips there, and only its
        # PRINTING channel was retired.
        retired = sorted(
            {
                row.anonymous_id
                for row in votes_batch
                if calculator_family(row.anonymous_id) in RETIRED_PRINTING_VOTE_FAMILIES
            }
        )
        if retired:
            raise AssertionError(
                f"RETIRED CALCULATOR: refusing to write CardPrintingTag rows under {retired} - "
                "that calculator family's printing votes were retired as redundant (owner ruling "
                "2026-07-29, see this module's docstring). Existing rows are kept as history; "
                "casting new ones is not."
            )
        purge_and_write_votes(CardTagVote, tag_votes_batch, target_field="card_id", ignore_conflicts=True)
        purge_and_write_votes(CardPrintingTag, votes_batch, target_field="card_id")
        if scan_log_batch:
            CardScanLog.objects.bulk_create(scan_log_batch)
        if batch_written_card_ids:
            all_gate_violations.extend(verify_zero_resolutions(batch_written_card_ids))
        votes_batch, tag_votes_batch, batch_written_card_ids, scan_log_batch = [], [], [], []

    def propagate_cluster_vote(
        representative_card_id: int, printing_pk: int, anonymous_id: str, confidence: float
    ) -> int:
        """Addendum item 2a: an accepted vote on a cluster representative propagates as an
        identical vote (same anonymous_id, printing, confidence) to every OTHER cluster member -
        absorbed members never ran their own OCR/phash, so this is the only vote they
        ever get. Skips any member that already has a vote from this SAME anonymous_id (e.g. one
        engine's vote from a prior invocation, on a member only newly eligible for a DIFFERENT
        engine this run) - propagating anyway would violate CardPrintingTag's own
        (card, printing, anonymous_id) uniqueness constraint, and would silently double-vote or
        attempt to overwrite an existing vote regardless. Returns how many propagated votes were
        actually queued, for the engine's votes_written tally.

        The row-building half was lifted verbatim into the module-level
        `build_propagated_cluster_votes` (2026-07-30) so a second engine - `run_pipeline`, the
        one-command monolith - can propagate cluster votes without a second copy of it. This
        closure keeps everything that is genuinely `run_pilot`-local: which batch the rows join,
        and the two written-id ledgers the gate check reads."""
        rows = build_propagated_cluster_votes(
            representative_card_id=representative_card_id,
            printing_pk=printing_pk,
            anonymous_id=anonymous_id,
            confidence=confidence,
            run_id=run_id,
            members_by_representative=cluster_result.members_by_representative,
            members_already_voted=members_already_voted_by_anonymous_id.get(anonymous_id, set()),
        )
        for row in rows:
            votes_batch.append(row)
            if row.card_id not in written_card_ids:
                written_card_ids.append(row.card_id)
                batch_written_card_ids.append(row.card_id)
        return len(rows)

    # Fetch budget (pre-scale program item 3b): every image fetch is one request against the
    # image CDN Worker, which shares its daily request quota with live site traffic
    # (docs/features/image-cdn.md) - an unattended multi-hour pilot slice must not be able to
    # consume an unbounded share of that shared budget. Counts only requests actually sent
    # (get_worker_image_url returning None - an unsupported source type - never reaches the
    # network at all, so it doesn't count). On exhaustion, the run stops cleanly: whatever's
    # already been flushed stays committed, and every card not yet reached is left completely
    # untouched (no vote, no outcome recorded) so the next invocation's selection query picks
    # them up fresh with no special resume handling needed.
    fetches_made = 0
    budget_exhausted = False
    cards_attempted = 0

    # Pipeline concurrency (pre-scale program item 3d, 2026-07-15): the per-card COMPUTE work
    # (fetch, OCR, phash, border/frame/bleed classification - everything
    # _compute_card does) is independent per card and safe to run concurrently; the per-card
    # WRITE work below (votes_batch/tag_votes_batch staging, disagreement bookkeeping,
    # ground-truth-preferred attribute overrides, the frame-mismatch consistency check) stays
    # single-threaded and in selection order, completely UNCHANGED from before this split - only
    # where its input comes from is different (a CardComputeResult instead of being computed
    # inline). Chunked at `batch_size` granularity, reusing the SAME boundary as checkpointing's
    # flush/gate-check (Stage 8 pre-scale program item 2) rather than introducing a second
    # batching concept - each chunk's compute pool completes before that chunk's writes are
    # staged and flushed, so write order and gate-check timing are identical to running with
    # workers=1, just with the compute portion overlapped.
    all_items = list(all_selected_by_card_id.items())
    total_cards = len(all_items)
    workers = max(1, workers)
    if workers > 1:
        # tesseract's LSTM engine can use OpenMP internally - without this, N concurrent
        # tesseract subprocesses (one per in-flight OCR call) could each ALSO try to
        # multi-thread themselves, oversubscribing this box's 2 real cores well beyond
        # `workers`. setdefault, not direct assignment - respects an operator's own override.
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    compute = functools.partial(
        _compute_card,
        ocr_selected_ids=ocr_selected_ids,
        phash_selected_ids=phash_selected_ids,
        ocr_crop_box=ocr_crop_box,
        phash_distance_threshold=phash_distance_threshold,
        phash_margin=phash_margin,
        phash_max_candidates=phash_max_candidates,
        fetch_dpi=fetch_dpi,
        known_set_codes=ocr_known_set_codes,
    )

    chunk_start = 0
    # The pool is created ONCE for the whole run, outside the chunk loop (bug fix, 2026-07-16:
    # it used to be recreated per chunk here, which - because Django DB connections are
    # thread-local and nothing closes a connection when its owning thread is torn down -
    # leaked one Postgres connection per worker per chunk. At DEFAULT_BATCH_SIZE=25 and
    # workers=7 that exhausted max_connections=100 within minutes on a full-catalog run,
    # crashing it with "sorry, too many clients already". Reusing the same threads across
    # every chunk means each worker opens its DB connection at most once for the entire run,
    # exactly like workers=1's single persistent connection.) `nullcontext()` keeps the
    # workers==1 path allocation-free, same as before.
    pool_cm: "ThreadPoolExecutor | nullcontext[None]" = (
        ThreadPoolExecutor(max_workers=workers) if workers > 1 else nullcontext()
    )
    with pool_cm as pool:
        while chunk_start < total_cards:
            # Fetch budget (pre-scale program item 3b, belt-and-suspenders alongside the image
            # CDN Worker's own IMAGE_FULL_TIER_RATE_LIMITER - see the CLI command's
            # --fetch-budget help): checked between chunks, not per-card - a chunk already in
            # flight always runs to completion once started, so the real bound on an overshoot
            # is one chunk's worth of fetches (<= batch_size), not zero. Acceptable given this
            # is explicitly the secondary safeguard, not the primary one.
            if fetch_budget is not None and fetches_made >= fetch_budget:
                budget_exhausted = True
                break
            chunk = all_items[chunk_start : chunk_start + batch_size]
            chunk_start += len(chunk)
            selected_in_chunk = [selected for _card_id, selected in chunk]

            if workers > 1:
                # .map() preserves submission order in its results regardless of completion
                # order - the write loop below sees cards in the exact same order it would with
                # workers=1, so nothing downstream needs to know concurrency happened at all.
                # cast: workers > 1 is exactly the condition under which pool_cm above was built
                # as a real ThreadPoolExecutor rather than nullcontext()'s None.
                chunk_results = list(cast(ThreadPoolExecutor, pool).map(compute, selected_in_chunk))
            else:
                chunk_results = [compute(s) for s in selected_in_chunk]

            for compute_result in chunk_results:
                card_id = compute_result.card_id
                outcome = compute_result.outcome
                cards_attempted += 1
                if compute_result.fetch_attempted:
                    fetches_made += 1

                # Finalize + queue for write - a card's full cost (image fetch, OCR, phash) was
                # already paid once in _compute_card above; nothing here depends on
                # any OTHER card's outcome, only this card's own DB state (the frame-mismatch
                # consistency check below re-queries the matched printing's own metadata,
                # independent of processing order).
                result_ocr = results.get("ocr")
                result_phash = results.get("phash")

                printing_vote_withheld_for_frame_mismatch = False
                # consistency check: only meaningful once a printing vote exists to compare
                # against the observed frame reading.
                candidate_vote = outcome.ocr_vote or outcome.phash_vote
                if outcome.frame_class is not None and candidate_vote is not None and not outcome.disagreement:
                    canonical = (
                        CanonicalCard.objects.filter(pk=candidate_vote.printing_pk)
                        .select_related("printing_metadata")
                        .first()
                    )
                    printing_frame_value = (
                        canonical.printing_metadata.frame
                        if canonical is not None and getattr(canonical, "printing_metadata", None) is not None
                        else None
                    )
                    if not local_fallback.frame_style_is_consistent(outcome.frame_class, printing_frame_value):
                        outcome.frame_mismatch = True
                        printing_vote_withheld_for_frame_mismatch = True
                        attributes.frame_mismatches.append(
                            {
                                "card_id": card_id,
                                "observed_frame_class": outcome.frame_class,
                                "matched_printing_pk": candidate_vote.printing_pk,
                                "matched_printing_frame_value": printing_frame_value,
                            }
                        )

                if outcome.disagreement:
                    assert (
                        result_ocr is not None and result_phash is not None
                    )  # both engines ran, or there's no disagreement to detect
                    result_ocr.disagreements.append(
                        {"card_id": card_id, "ocr": outcome.ocr_vote, "phash": outcome.phash_vote}
                    )
                    result_ocr.skip_counts[DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON] += 1
                    result_phash.skip_counts[DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON] += 1
                    scan_log_batch.append(
                        CardScanLog(
                            card_id=card_id,
                            anonymous_id=OCR_ANONYMOUS_ID,
                            run_id=run_id,
                            skip_reason=DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON,
                        )
                    )
                    scan_log_batch.append(
                        CardScanLog(
                            card_id=card_id,
                            anonymous_id=PHASH_ANONYMOUS_ID,
                            run_id=run_id,
                            skip_reason=DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON,
                        )
                    )
                else:
                    if outcome.ocr_vote is not None and result_ocr is not None:
                        if printing_vote_withheld_for_frame_mismatch:
                            result_ocr.skip_counts[FRAME_MISMATCH_SKIP_REASON] += 1
                            scan_log_batch.append(
                                CardScanLog(
                                    card_id=card_id,
                                    anonymous_id=OCR_ANONYMOUS_ID,
                                    run_id=run_id,
                                    skip_reason=FRAME_MISMATCH_SKIP_REASON,
                                )
                            )
                        else:
                            votes_batch.append(
                                CardPrintingTag(
                                    card_id=card_id,
                                    printing_id=outcome.ocr_vote.printing_pk,
                                    is_no_match=False,
                                    anonymous_id=OCR_ANONYMOUS_ID,
                                    source=VoteSource.OCR,
                                    confidence=outcome.ocr_vote.confidence,
                                    run_id=run_id,
                                )
                            )
                            result_ocr.votes_written += 1
                            result_ocr.audit.append({"card_id": card_id, "raw_text": outcome.ocr_vote.detail})
                            written_card_ids.append(card_id)
                            batch_written_card_ids.append(card_id)
                            result_ocr.votes_written += propagate_cluster_vote(
                                card_id, outcome.ocr_vote.printing_pk, OCR_ANONYMOUS_ID, outcome.ocr_vote.confidence
                            )
                    elif outcome.ocr_skip_reason and result_ocr is not None:
                        if outcome.ocr_skip_reason == PARSED_BUT_NO_MATCH_SKIP_REASON:
                            # issue #207: a syntactically valid collector-line read that matches
                            # NONE of this card's own candidates is genuine evidence against the
                            # WHOLE candidate set (unlike "ambiguous", split out above, which is
                            # evidence FOR more than one candidate, not against the set) - cast as
                            # a real is_no_match vote, not merely logged as an abstention. Same
                            # "the vote IS the record, no scan-log row needed" convention a
                            # positive vote already follows (see
                            # TestScanLog.test_a_voted_card_gets_no_scan_log_row) - the
                            # anonymous_id exclusion in _eligible_base_queryset already covers
                            # this row for idempotence, no separate scan-log-based exclusion
                            # needed.
                            votes_batch.append(
                                CardPrintingTag(
                                    card_id=card_id,
                                    printing_id=None,
                                    is_no_match=True,
                                    anonymous_id=OCR_ANONYMOUS_ID,
                                    source=VoteSource.OCR,
                                    confidence=OCR_NO_MATCH_CONFIDENCE,
                                    run_id=run_id,
                                )
                            )
                            result_ocr.no_match_votes_written += 1
                            result_ocr.audit.append(
                                {"card_id": card_id, "no_match_reason": PARSED_BUT_NO_MATCH_SKIP_REASON}
                            )
                            if card_id not in written_card_ids:
                                written_card_ids.append(card_id)
                                batch_written_card_ids.append(card_id)
                        else:
                            result_ocr.skip_counts[outcome.ocr_skip_reason] += 1
                            scan_log_batch.append(
                                CardScanLog(
                                    card_id=card_id,
                                    anonymous_id=OCR_ANONYMOUS_ID,
                                    run_id=run_id,
                                    skip_reason=outcome.ocr_skip_reason,
                                )
                            )

                    if outcome.phash_vote is not None and result_phash is not None:
                        if printing_vote_withheld_for_frame_mismatch:
                            result_phash.skip_counts[FRAME_MISMATCH_SKIP_REASON] += 1
                            scan_log_batch.append(
                                CardScanLog(
                                    card_id=card_id,
                                    anonymous_id=PHASH_ANONYMOUS_ID,
                                    run_id=run_id,
                                    skip_reason=FRAME_MISMATCH_SKIP_REASON,
                                )
                            )
                        else:
                            votes_batch.append(
                                CardPrintingTag(
                                    card_id=card_id,
                                    printing_id=outcome.phash_vote.printing_pk,
                                    is_no_match=False,
                                    anonymous_id=PHASH_ANONYMOUS_ID,
                                    source=VoteSource.OCR,
                                    confidence=outcome.phash_vote.confidence,
                                    run_id=run_id,
                                )
                            )
                            result_phash.votes_written += 1
                            result_phash.audit.append({"card_id": card_id, "detail": outcome.phash_vote.detail})
                            if card_id not in written_card_ids:
                                written_card_ids.append(card_id)
                                batch_written_card_ids.append(card_id)
                            result_phash.votes_written += propagate_cluster_vote(
                                card_id,
                                outcome.phash_vote.printing_pk,
                                PHASH_ANONYMOUS_ID,
                                outcome.phash_vote.confidence,
                            )
                    elif outcome.phash_skip_reason and result_phash is not None:
                        result_phash.skip_counts[outcome.phash_skip_reason] += 1
                        scan_log_batch.append(
                            CardScanLog(
                                card_id=card_id,
                                anonymous_id=PHASH_ANONYMOUS_ID,
                                run_id=run_id,
                                skip_reason=outcome.phash_skip_reason,
                            )
                        )

                    # THE PASS-2 FALLBACK'S OWN WRITE BRANCH STOOD HERE and is RETIRED as of
                    # 2026-07-29 (module docstring): a positive "local-fallback-v1"
                    # CardPrintingTag vote (plus its cluster propagation), an is_no_match vote
                    # for the "eliminated" outcome, and the CardScanLog abstention rows for
                    # every other outcome. All three are gone because nothing computes a
                    # fallback printing verdict any more - not gated off, removed - and the
                    # `flush` guard above makes re-adding one fail loudly rather than silently
                    # restore a retired witness. The card's border/frame/bleed attribute votes
                    # are cast below, unchanged.

                # border/frame attribute votes are independent of printing-vote success or the
                # consistency-check outcome above - they fire for any card a border/frame reading
                # was taken on, per the module docstring's "double duty" note. BUT when a printing
                # was actually confirmed for this card this run, ground truth from that printing's
                # own CanonicalPrintingMetadata (Scryfall border_color/frame) is preferred over the
                # pixel/OCR heuristic estimate - the heuristic's whole purpose was to independently
                # validate an uncertain match (the consistency check above needs an independent
                # signal to compare against), not to guess an answer we now actually know. Falls
                # back to the heuristic reading whenever no printing was confirmed this run, or the
                # confirmed printing has no usable ground truth for that particular attribute.
                card = all_selected_by_card_id[card_id].card
                confirmed_printing_pk = (
                    candidate_vote.printing_pk
                    if candidate_vote is not None
                    and not outcome.disagreement
                    and not printing_vote_withheld_for_frame_mismatch
                    else None
                )
                ground_truth_metadata = None
                if confirmed_printing_pk is not None:
                    confirmed_canonical = (
                        CanonicalCard.objects.filter(pk=confirmed_printing_pk)
                        .select_related("printing_metadata")
                        .first()
                    )
                    if (
                        confirmed_canonical is not None
                        and getattr(confirmed_canonical, "printing_metadata", None) is not None
                    ):
                        ground_truth_metadata = confirmed_canonical.printing_metadata

                border_class = outcome.border_color
                border_confidence = local_fallback.BORDER_ATTRIBUTE_VOTE_CONFIDENCE
                if ground_truth_metadata is not None and ground_truth_metadata.border_color:
                    # gate on a known tag mapping before overriding - Scryfall's border_color can be
                    # "gold", outside this v1 taxonomy (see local_fallback.BORDER_COLOR_TO_TAG's
                    # docstring); an unmapped ground truth value must not discard a valid heuristic
                    # reading in favour of a vote that will silently resolve to nothing.
                    ground_truth_border_class = ground_truth_metadata.border_color
                    if ground_truth_border_class in local_fallback.BORDER_COLOR_TO_TAG:
                        border_class = ground_truth_border_class
                        border_confidence = local_fallback.GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE
                        attributes.border_ground_truth_count += 1

                if border_class is not None:
                    attributes.border_votes_by_class[border_class] += 1
                    border_vote = local_fallback.cast_border_attribute_vote(
                        card, border_class, confidence=border_confidence, run_id=run_id
                    )
                    if border_vote is not None and not dry_run:
                        tag_votes_batch.append(border_vote)

                frame_class = outcome.frame_class
                frame_confidence = local_fallback.FRAME_VOTE_CONFIDENCE
                if ground_truth_metadata is not None and ground_truth_metadata.frame:
                    ground_truth_frame_class = local_fallback.FRAME_VALUE_TO_CLASS.get(ground_truth_metadata.frame)
                    if ground_truth_frame_class is not None:
                        frame_class = ground_truth_frame_class
                        frame_confidence = local_fallback.GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE
                        attributes.frame_ground_truth_count += 1

                if outcome.frame_reading_attempted:
                    if frame_class is not None:
                        attributes.frame_votes_by_class[frame_class] += 1
                        frame_vote = local_fallback.cast_frame_style_vote(
                            card, frame_class, confidence=frame_confidence, run_id=run_id
                        )
                        if frame_vote is not None and not dry_run:
                            tag_votes_batch.append(frame_vote)
                    else:
                        attributes.frame_abstain_count += 1

                # addendum item 7: bleed-edge classification - independent of printing-vote success,
                # same "fires for any card with a fetched image" convention as border/frame above,
                # and (unlike those two) has no ground-truth counterpart to prefer, since Scryfall
                # doesn't encode this at all. Already computed once in _compute_card - FIRST, ahead
                # of everything else (see that function's docstring) - so this reads outcome.bleed_
                # class/outcome.image_fetched rather than recomputing against `image` (which is no
                # longer available here now that fetch+compute moved into _compute_card).
                if outcome.bleed_class is not None:
                    attributes.bleed_votes_by_class[outcome.bleed_class] += 1
                    bleed_vote = local_fallback.cast_bleed_edge_vote(card, outcome.bleed_class, run_id=run_id)
                    if bleed_vote is not None and not dry_run:
                        tag_votes_batch.append(bleed_vote)
                elif outcome.image_fetched:
                    attributes.bleed_abstain_count += 1

            flush()
            if nice:
                time.sleep(_NICE_SLEEP_SECONDS)
            if progress_every and chunk_start % progress_every < len(chunk):
                # Part 3 addendum item 3: "this invocation" progress is scoped to THIS run's own
                # selected pool (total_cards, already net of every prior invocation's votes and
                # scan-log rows) - separate from the corpus-wide unresolved count, which moves
                # for reasons this invocation doesn't control (human votes, other engines).
                # Conflating the two would make neither number trustworthy.
                elapsed = time.time() - run_start_time
                rate = chunk_start / elapsed if elapsed > 0 else 0.0
                unseen_remaining = total_cards - chunk_start
                eta_str = f"{(unseen_remaining / rate) / 3600:.1f}h" if rate > 0 else "unknown"
                unresolved_pool = Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED).count()
                print(
                    f"  ... this invocation {chunk_start}/{total_cards} "
                    f"(unseen-remaining {unseen_remaining}), {unresolved_pool} unresolved "
                    f"catalog-wide, rate={rate:.2f}/s, ETA {eta_str}"
                )

    cards_not_attempted = len(all_selected_by_card_id) - cards_attempted
    for result in results.values():
        if not dry_run:
            result.gate_violations = all_gate_violations
        result.fetch_budget_exhausted = budget_exhausted
        result.cards_not_attempted_this_invocation = cards_not_attempted

    if uncovered_printing_pks_in_scope and not dry_run:
        covered_printing_pks_after = compute_covered_printing_pks()
        attributes.uncovered_printings_closed = len(uncovered_printing_pks_in_scope & covered_printing_pks_after)

    return results, attributes


# Fast-follow (2026-07-16): name-frequency elimination - see run_name_frequency_elimination's
# own docstring for the full design rationale (in particular the SAFE 1:1 gate that makes this
# sound, not just "one uncovered printing").
NAME_FREQUENCY_ANONYMOUS_ID = "local-name-frequency-v1"
# Deliberately modest relative to OCR/phash's own confidences (0.85/0.75/0.8) - this is a purely
# structural deduction (no visual confirmation of THIS card at all), weaker evidence than an
# engine that actually looked at the image, even though the 1:1 gate makes it sound.
NAME_FREQUENCY_CONFIDENCE = 0.6


@dataclass
class NameFrequencyResult:
    dry_run: bool = False
    run_id: str = ""
    votes_written: int = 0
    gate_violations: list[int] = field(default_factory=list)
    # THE VISUAL CONJUNCT'S OWN ABSTENTION COUNTERS (2026-07-30). Reported separately from
    # `votes_written` so the cost of the new gate is legible on the first run rather than
    # inferred from a smaller total: `abstained_no_evidence` is "we have never looked at this
    # image", `abstained_attribute_mismatch` is "we looked and it contradicts the printing".
    # Those are very different findings and collapsing them would hide which one is doing the work.
    abstained_no_evidence: int = 0
    abstained_attribute_mismatch: int = 0


def _current_evidence_for(card_id: int) -> Optional[Any]:
    """This card's CURRENT `ImageEvidence` row, or `None` when it has never been extracted (or its
    only row is stale against the card's live hash/checksum). `current_evidence_queryset` is THE
    shared definition of "current" - content hash matches the card's live `content_phash`, and a
    stamped md5 agrees wherever both sides carry one - reused rather than re-expressed, since this
    module would otherwise become the Nth inline copy of a rule that already got centralised once.

    Imported at CALL time, not module scope: `image_evidence` imports `local_fallback`, which
    TYPE_CHECKING-imports this module, so a module-scope import here would turn a type-only cycle
    into a real one. Same posture `evidence_transfer`'s own call-time import documents.

    Only reached for a name that has ALREADY passed both counting gates (measured live 2026-07-16:
    1,678 names catalogue-wide qualify), so this per-name fetch is bounded by that number rather
    than by the eligible card population."""
    from cardpicker.image_evidence import current_evidence_queryset

    card = Card.objects.filter(pk=card_id).first()
    if card is None:
        return None
    return current_evidence_queryset(card).first()


def _printing_metadata_for(printing_pk: int) -> Optional[Any]:
    """The candidate printing's `CanonicalPrintingMetadata` sidecar, or `None` when it has none -
    which `printing_attribute_disagreement` already treats as "nothing to compare"."""
    canonical = CanonicalCard.objects.filter(pk=printing_pk).select_related("printing_metadata").first()
    return getattr(canonical, "printing_metadata", None) if canonical is not None else None


def run_name_frequency_elimination(
    dry_run: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, run_id: Optional[str] = None
) -> NameFrequencyResult:
    """Fast-follow (2026-07-16): for a NAME where exactly one of its printings remains
    uncovered (see compute_covered_printing_pks) AND exactly one pilot-eligible card is
    unresolved for that name, the match is deducible by elimination alone - no image fetch, no
    OCR/phash, no visual disambiguation needed at all.

    The SAFE gate is "exactly one uncovered printing AND exactly one unresolved-eligible card",
    not just "exactly one uncovered printing" - a name can have one uncovered printing while
    SEVERAL unresolved cards share that name, in which case elimination does NOT tell you WHICH
    of those cards is the missing one (any of the others could just as easily be a redundant
    depiction of an ALREADY-covered printing, uploaded by a different source). Gating on "and
    exactly one unresolved card too" is what makes the deduction airtight; it is not a
    nice-to-have refinement, it is the difference between a sound inference and a coin flip.
    Measured live against the full (not sampled) catalog, 2026-07-16: 2,076 names have exactly
    one uncovered printing; only 1,678 of those also have exactly one unresolved eligible card.
    The naive, ungated version would have voted - incorrectly, on average - for the other ~400
    names' multiple candidate cards.

    Still just a VOTE (this function's own anonymous_id), never a direct resolve - same
    consensus/gate-check discipline as every other engine in this module. Reuses
    _eligible_base_queryset for the exact same base eligibility rules (unresolved, no confirmed
    match, card_type=CARD, not deductive-backfill-covered, no custom-art/non-english tag) plus
    this function's own anonymous_id for idempotence, and the SAME batch-flush + gate-check
    pattern as run_pilot (a kill loses at most one batch; a plain re-invocation resumes cleanly).

    THE DEDUCTION MUST LOOK AT THE IMAGE (owner ruling, 2026-07-30): "just because a card was
    printed exactly once doesn't mean that the image in our catalogue is an accurate depiction of
    that card, it may have a different border or another issue."

    Everything the 1:1 gate above checks is a COUNT. Counting establishes that IF this card is a
    depiction of one of this name's printings, THEN it must be the uncovered one. It establishes
    NOTHING about the antecedent, and the only filters that spoke to it at all were the DECLARED
    `custom-art` / non-English tags - so an altered border, a custom frame or a misnamed upload
    that nobody had tagged yet sailed straight through and got a full-confidence structural vote.

    "IT IS ONLY A VOTE" IS NOT THE DEFENCE IT SOUNDS LIKE, which is why this was worth fixing
    rather than tolerating. Issue #593 established that a machine vote is what the question feed
    renders as THE SUGGESTION TO CONFIRM, and a human's click returns as a full-weight USER vote.
    A visually-unverified deduction therefore becomes a one-click rubber stamp, and the human-
    backed consensus gate - the thing that normally makes a wrong machine vote recoverable - is
    exactly the mechanism that launders it.

    SO THE MISSING CONJUNCT IS ADDED: the card's ALREADY-STORED evidence must be consistent with
    the candidate printing (`printing_attribute_disagreement` - border class and frame style, the
    same check `local_calculate_verdicts._apply_agreement_checks` has always applied to the
    join-key channel, now shared rather than re-derived). This is the same shape as the D1 fix: a
    tier claimed a cross-check it never performed, and adding the real one made it sound.

    NO NEW FETCH, NO NEW EXTRACTION. Every input is a field already on the card's current
    `ImageEvidence` row. That matters for what this function IS - a pure structural deduction that
    costs no network - and it is why the conjunct is affordable at catalogue scale.

    NO STORED EVIDENCE MEANS ABSTAIN, NOT PROCEED. If the card has no current `ImageEvidence` row
    at all, we have never looked at this image, so the antecedent is exactly as unestablished as it
    was before - and "we have no evidence" must not read as "no evidence against". This is the one
    place where this module's usual "missing data is not evidence" rule points the other way, and
    deliberately: that rule protects a match from being VETOED by silence, whereas here silence is
    being asked to ESTABLISH something. Counted as `abstained_no_evidence` so the size of that
    population is visible on the first run rather than inferred.

    WHY NOT SIMPLY DROP THIS CALCULATOR. It has never run in production (zero `PilotRunLedger`
    rows for `local_name_frequency_elimination`, ever), so nothing is contaminated and there is no
    retraction to plan - dropping it would have been clean. It is kept because the deduction is
    genuinely sound ONCE the antecedent is established, and elimination reaches a population the
    image-based channels structurally cannot: a name whose single uncovered printing has no
    distinguishing collector line to read. Deleting a sound tier because it was missing a guard is
    a worse trade than adding the guard.

    THE CENSUS MUST BE RUN-SCOPED (2026-07-30). `_eligible_base_queryset` is called with THIS
    run's `run_id`, and that argument is a soundness fix, not a resume convenience. The gate above
    is a COUNT OVER THE POPULATION THIS QUERYSET RETURNS - "exactly one unresolved eligible card
    for this name, catalog-wide" - while one of that queryset's exclusions is "cards already
    carrying THIS calculator's vote". Left unscoped, that exclusion is LIFETIME, so the calculator
    is taking a census over a population it is itself permanently shrinking:

        run 1   name N has TWO unresolved eligible cards, A and B. len(card_ids) != 1, so the
                gate correctly ABSTAINS - elimination cannot say which of A and B is the
                uncovered printing, and voting for either would be a coin flip.
        (later) some other channel votes on A, or A is resolved/confirmed by a human, or this
                calculator votes on A for some OTHER name it also qualifies under.
        run 2   A is gone from the pool. Name N now returns exactly ONE card, B. The gate PASSES
                and votes B for the printing - not because anything new was learned about B, but
                because the pool was depleted underneath the question.

    That is a FRESH WRONG POSITIVE, which is a strictly worse failure than the stale-vote and
    missed-vote cases the 2026-07-29 run-scoping directive was written for: nothing about B's
    image, evidence or name changed between the two runs, only the size of the population the
    gate counts. Passing `run_id` narrows the self-suppressing excludes to rows THIS run wrote, so
    a fresh run_id restores the catalog-wide count the gate is specified against and name N
    abstains on run 2 exactly as it did on run 1. Within-run resume is unaffected and still works:
    re-invoking with the SAME run_id still sees this run's own already-voted cards excluded, so a
    killed run picks up where it stopped rather than redoing completed batches.

    WHAT THIS DOES *NOT* CHANGE, deliberately. `compute_covered_printing_pks()` above stays
    catalog-wide and un-scoped, and must: "covered" is a fact about the CATALOGUE (a confirmed
    `canonical_card`, or a RESOLVED `inferred_canonical_card`), not about this calculator's
    progress, and run-scoping it would make every run re-derive coverage from an empty set and
    treat every printing as uncovered. The two halves of the gate are therefore scoped
    DIFFERENTLY, on purpose: the coverage half asks a question about the world, the census half
    asks a question about a population this calculator mutates. It also means a name whose single
    uncovered printing genuinely got covered between runs drops out of the gate naturally on the
    coverage half, which is why restoring the census half does not simply re-vote everything.

    `run_pilot`'s own `select_candidates` and `count_below_resolution_floor` are LEFT UNSCOPED -
    neither gates on a count over the returned population (the pilot's predicate is per-card and
    its selection is a fetch-budget ordering; the floor count is a report metric), so neither has
    the defect this fixes, and flipping them is the separate decision with the separate blast
    radius `_eligible_base_queryset`'s own docstring already records.
    """
    # a separate invocation entrypoint from run_pilot (own management command, own gate-check
    # loop) - generates its OWN run_id, never one shared with a run_pilot() call.
    run_id = run_id or generate_run_id()

    covered_printing_pks = compute_covered_printing_pks()
    index = CandidateNameIndex()

    cards_by_name: dict[str, list[int]] = collections.defaultdict(list)
    for card_id, name in (
        # `run_id` PASSED (2026-07-30) - THE CENSUS LEAK. See this function's own docstring's
        # "THE CENSUS MUST BE RUN-SCOPED" section for why this one argument is a correctness fix
        # and not a resume convenience.
        _eligible_base_queryset(NAME_FREQUENCY_ANONYMOUS_ID, run_id=run_id)
        .values_list("pk", "name")
        .order_by("pk")
        .iterator(chunk_size=5000)
    ):
        cards_by_name[name].append(card_id)

    result = NameFrequencyResult(dry_run=dry_run, run_id=run_id)
    votes_batch: list[CardPrintingTag] = []
    batch_written_card_ids: list[int] = []

    def flush() -> None:
        nonlocal votes_batch, batch_written_card_ids
        if dry_run:
            votes_batch, batch_written_card_ids = [], []
            return
        # CANCEL-SAFETY (2026-07-28) - same reasoning as run_pilot's own flush above and
        # `vote_write.purge_and_write_votes`' docstring: the purge and the insert are one atomic
        # pair scoped to exactly the rows written, so a kill mid-chunk loses the chunk rather
        # than also destroying whatever those cards had before. Every row here carries
        # NAME_FREQUENCY_ANONYMOUS_ID (single-engine entrypoint), so the identity is passed
        # explicitly rather than derived per row.
        purge_and_write_votes(
            CardPrintingTag,
            votes_batch,
            anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID,
            target_field="card_id",
        )
        if batch_written_card_ids:
            result.gate_violations.extend(verify_zero_resolutions(batch_written_card_ids))
        votes_batch, batch_written_card_ids = [], []

    for name, card_ids in cards_by_name.items():
        if len(card_ids) != 1:
            continue
        candidates = index.candidates_for(name)
        if not candidates:
            continue
        uncovered = [c for c in candidates if c.pk not in covered_printing_pks]
        if len(uncovered) != 1:
            continue

        # THE MISSING CONJUNCT (owner ruling, 2026-07-30) - see this function's own docstring's
        # "THE DEDUCTION MUST LOOK AT THE IMAGE" section. Everything above is a COUNT; nothing
        # above establishes that this card is a depiction of that printing at all.
        evidence = _current_evidence_for(card_ids[0])
        if evidence is None:
            result.abstained_no_evidence += 1
            continue
        disagreement = printing_attribute_disagreement(evidence, _printing_metadata_for(uncovered[0].pk))
        if disagreement is not None:
            result.abstained_attribute_mismatch += 1
            continue

        votes_batch.append(
            CardPrintingTag(
                card_id=card_ids[0],
                printing_id=uncovered[0].pk,
                is_no_match=False,
                anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID,
                source=VoteSource.OCR,
                confidence=NAME_FREQUENCY_CONFIDENCE,
                run_id=run_id,
            )
        )
        batch_written_card_ids.append(card_ids[0])
        result.votes_written += 1

        if len(batch_written_card_ids) >= batch_size:
            flush()

    flush()
    return result


def generate_run_id() -> str:
    """Fresh per-invocation run_id (docs/features/catalog-completion-plan.md's Part 1, see
    AbstractWeightedVote.run_id's own docstring for the full rationale) - a UTC-timestamp prefix
    for human scannability in logs/--dry-run output, plus a short random suffix so two
    invocations started in the same second never collide. Deliberately NOT the image's git SHA
    (that's logged separately - see cardpicker.utils.get_baked_git_sha - keeping run_id
    generation independent of whether the git-SHA build-info file happens to be present avoids
    coupling two different failure modes together). NOT reused across invocations, unlike
    anonymous_id - see purge_machine_votes for how this is consumed."""
    return f"{timezone.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def verify_zero_resolutions(card_ids: list[int], batch_size: int = 2000) -> list[int]:
    """Identical rationale/mechanism to cardpicker.deductive_backfill.verify_zero_resolutions -
    the *pure* resolve_printing (never resolve_and_persist_printing, which must never itself
    cause a write) re-checked against fresh DB state after the batch write above."""
    from cardpicker.printing_consensus import resolve_printing

    violations: list[int] = []
    for i in range(0, len(card_ids), batch_size):
        chunk = card_ids[i : i + batch_size]
        for card in Card.objects.filter(pk__in=chunk).iterator(chunk_size=batch_size):
            if resolve_printing(card) is not None:
                violations.append(card.pk)
    return violations


def run_fidelity_gate(
    *,
    run_id: str,
    write: Callable[[str], None],
    style_error: Optional[Callable[[str], str]] = None,
) -> list[int]:
    """
    THE SHARED STAGE D FIDELITY GATE. Answers one question over every card a run_id cast a
    CardPrintingTag vote for: did any of them reach a RESOLVED printing state on machine votes
    alone? The answer must be zero. This is verify_zero_resolutions (above) plus the run-scoping
    query that selects which cards to check it against, factored out so run_pipeline and
    backfill_survivor_pks share ONE gate rather than each keeping its own copy that could drift.

    Never rolls back, purges, or retracts anything - every row either command wrote stays written.
    A violation is reported (via write, and returned so the caller can exit non-zero on it) - a
    loud "read this run before trusting it", not an undo.
    """
    card_ids = list(CardPrintingTag.objects.filter(run_id=run_id).values_list("card_id", flat=True).distinct())
    if not card_ids:
        write("FIDELITY GATE: this run cast no printing votes - nothing to check.")
        return []
    violations = verify_zero_resolutions(card_ids)
    if violations:
        message = f"FIDELITY GATE VIOLATION: {len(violations)} card(s): {violations[:20]}"
        write(style_error(message) if style_error is not None else message)
    else:
        write(f"FIDELITY GATE: clear over {len(card_ids)} cards.")
    return violations


__all__ = [
    "OCR_ANONYMOUS_ID",
    "UNFETCHABLE_IMAGE_SKIP_REASON",
    "FRAME_MISMATCH_SKIP_REASON",
    "DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON",
    "OCR_AMBIGUOUS_SKIP_REASON",
    "OCR_NO_TEXT_SKIP_REASON",
    "OCR_UNKNOWN_SET_CODE_SKIP_REASON",
    "PARSED_BUT_NO_MATCH_SKIP_REASON",
    "PHASH_TOO_MANY_CANDIDATES_SKIP_REASON",
    # `PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON` / `PHASH_NO_CLEAR_WINNER_SKIP_REASON` are
    # deliberately absent: they are declared and exported by `cardpicker.local_phash`, their
    # origin. Re-exporting them from here would recreate the two-names-one-value ambiguity that
    # removing the mirror was meant to end.
    "PHASH_NO_CLEAR_WINNER_DISTANCE_SKIP_REASON",
    "PHASH_NO_CLEAR_WINNER_MARGIN_SKIP_REASON",
    "RESCANNABLE_SKIP_REASONS",
    "PHASH_ANONYMOUS_ID",
    "DEDUCTIVE_BACKFILL_ANONYMOUS_ID",
    "OCR_CONFIDENCE_BOTH",
    "OCR_CONFIDENCE_COLLECTOR_ONLY",
    "PHASH_CONFIDENCE",
    "CandidatePrinting",
    "CandidateNameIndex",
    "SelectedCard",
    "RESOLUTION_FLOOR_DPI",
    "count_below_resolution_floor",
    "compute_covered_printing_pks",
    "select_candidates",
    "get_worker_image_url",
    "fetch_card_image",
    "EngineVote",
    "CardOutcome",
    "CardComputeResult",
    "DEFAULT_WORKERS",
    "run_ocr_for_card",
    "run_phash_for_card",
    "PilotResult",
    "AttributeReport",
    "run_pilot",
    "NAME_FREQUENCY_ANONYMOUS_ID",
    "NAME_FREQUENCY_CONFIDENCE",
    "NameFrequencyResult",
    "run_name_frequency_elimination",
    "verify_zero_resolutions",
    "run_fidelity_gate",
    "generate_run_id",
]
