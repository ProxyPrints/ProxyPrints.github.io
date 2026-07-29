"""
Stage D illustration deduction calculator (public issue #507, ``stage-d-illustration-v2``) — a
new calculator in the Stage D framework that uses the ``illustration_id`` field imported from
Scryfall (issue #506) to deduce printing identity. When an artist-OCR hit identifies the artist,
and that artist's printings of this card name narrow to exactly ONE printing, we vote for it.

Anonymous ID: ``stage-d-illustration-v2``
Source: ``VoteSource.DEDUCTION``
Base confidence: ``BASE_CONFIDENCE = 0.85``

THE v1 → v2 BUMP, AND WHY IT IS PART OF A BUG FIX RATHER THAN A NEW METHOD (2026-07-29). v1
carried a gate that skipped every card whose ``ImageEvidence.layout_class`` was non-blank, on the
stated premise that ``layout_class`` records faced-ness. It does not: its only writer is
``local_fallback.classify_border_color`` and it holds a BORDER COLOUR (live distribution: black
138,728 / borderless 72,603 / white 7,475 / '' 1,455 / silver 408). Non-blank on 99.34% of rows,
so the gate discarded 99.28% of every population handed to the calculator — 3,409 of its 3,426
scanned rows logged ``multi-faced-v1``, and the calculator cast 3 illustration votes in its whole
existence against 230,753 catalog cards. The gate is DELETED (not repaired) — see "PER-FACE
ILLUSTRATIONS" below for why there is no longer anything for it to guard.

The version bump is what makes the fix take effect at all: ``multi-faced-v1`` is not in
``RESCANNABLE_SKIP_REASONS`` (which holds only ``no-evidence``) and
``_eligible_illustration_cards_queryset`` excludes any card carrying a non-rescannable
``CardScanLog`` row for its OWN ``anonymous_id``, so a repaired v1 would never re-examine the
3,409 cards it wrongly skipped. Renaming to v2 sidesteps that exclusion without deleting evidence
and without making genuine skips permanently re-runnable. ``models.calculator_family`` strips the
``-vN`` suffix, so every family-keyed behaviour (``purge_stale_machine_votes``' family-scoped
DELETE, ``printing_consensus.agent_dedupe_key``'s one-agent-one-vote pooling, and
``vote_consensus.resolve_vote_weight``'s zero-weight override — which is scoped to the
``deductive-backfill`` family and has never matched this one) follows the bump automatically:
family stays ``stage-d-illustration`` across v1/v2, so v1 rows are still purged by a v2 run and
still pool as the same agent.

PER-FACE ILLUSTRATIONS — WHY THE SINGLE-FACED GUARD IS GONE RATHER THAN FIXED. The guard's
STATED concern was real: ``CanonicalPrintingMetadata.illustration_id`` is populated from
``PrintingMetadataRow.resolved_illustration_id``, which returns ``card_faces[0].illustration_id``
— the FRONT face — so a back-face scan would have been voted with the front's artwork id. That is
now solved by better data rather than by refusing to look: ``CanonicalPrintingMetadata.
face_illustrations`` retains EVERY face's own ``illustration_id`` (populated only for genuine
double-faced layouts — see that field and ``PrintingMetadataRow.face_illustrations``), and
``IllustrationIndex`` keys each face's illustration under that FACE's own name. A back-face-named
upload therefore matches the back face's own artwork, which is the correct answer, so there is no
wrong-vote exposure left for a gate to guard.

Logic:
  1. Build an in-memory index ``(artist_pk, searchable_card_name) → {illustration_id → [printing_pk]}``
     from ``CanonicalCard``/``CanonicalPrintingMetadata`` pairs where ``illustration_id`` is
     non-null, using ``to_searchable`` normalization. For a genuine double-faced printing, EACH
     face additionally contributes an entry under that face's own name.
  2. For each eligible card, use ``match_artist`` to fuzzy-match the OCR-extracted artist name
     against the card's candidate artists.
  3. For each surviving artist, look up the illustration index by ``(artist_pk, searchable_name)``.
  4. Resolve a printing ONLY at 1:1 — exactly one surviving ``illustration_id`` AND that
     illustration mapping to exactly one printing:
     - 0 illustrations → abstain (``no-illustration-index-entry``)
     - 1 illustration → 1 printing → vote that printing at ``BASE_CONFIDENCE``
     - 1 illustration → N printings → abstain (``multiple-printings-one-illustration``)
     - N>1 illustrations → abstain (``multiple-illustrations``)

THE 1:1 RULE (issue #525, 2026-07-28) — WHY BOTH MULTI-OUTCOME BRANCHES ABSTAIN. This calculator
previously emitted one ``CardPrintingTag`` per printing in the verdict, so a single machine
identity ended up voting simultaneously for several MUTUALLY EXCLUSIVE printings of the same
card. The ``BASE_CONFIDENCE / N`` spread that was supposed to discount them is decorative:
``vote_consensus.resolve_vote_weight(source, anonymous_id, run_id)`` takes no confidence argument and
``VoteTuple`` carries no confidence field, so confidence NEVER reaches the tally — every emitted
row landed at full ``PRINTING_TAG_MACHINE_WEIGHT``. The DB does not stop it either:
``cardprintingtag_unique_printing_vote`` is on (card, printing, anonymous_id), so different
printings under one identity all persist. Where md5 identity-group pooling is active those rows
read as self-contradiction and get withheld; where it is not, they all count, at full machine
weight, for outcomes that cannot all be true. The human submit path cannot do this —
``post_submit_printing_tag`` deletes the voter's prior rows for the card before creating.

Confidence stays informational-only. The base/N division must NOT be "fixed" into weight math
(see ``vote_consensus.py``'s own warning); the fix is to stop casting the contradiction, not to
make the consensus layer honour a discount.

ABSTAIN-WITH-EVIDENCE, AND WHY THE TWO ABSTAIN REASONS ARE DISTINCT. Both multi-outcome cases
record a ``CardScanLog`` row rather than dropping silently, but only ONE of them carries a
recoverable fact: at 1 illustration → N printings the calculator KNOWS the illustration identity
with full confidence and merely cannot choose a printing, so ``IllustrationVerdict`` retains that
``illustration_id`` and the candidate printing pks. At N>1 illustrations there is no single
identity to retain and none is invented. The two are separate ``skip_reason`` strings so the
recoverable population is queryable.

THE SECOND WRITE GRAIN — ``CardIllustrationVote`` (issue #524, 2026-07-28). The retained identity
above is now PERSISTED, which is what #526's abstain-with-evidence was staged for. A run writes
at two independent grains:

  - ``CardPrintingTag`` — only at 1:1. The rule above is UNCHANGED; #524 does not weaken it.
  - ``CardIllustrationVote`` — whenever exactly ONE illustration was resolved, however many
    printings it maps to. That is the 1:1 cards PLUS the entire
    ``multiple-printings-one-illustration`` population, i.e. most of the coverage the 1:1 rule
    withholds at the printing grain is retained at the artwork grain instead of discarded.
    At N>1 illustrations nothing is written at either grain.

An illustration vote is a claim about the ARTWORK and must never be expanded into printing votes
for the printings sharing it — that expansion is exactly issue #525's defect. The narrowing stays
a READ: ``printings_for_illustration`` below. ``CardIllustrationVote``'s UNCONDITIONAL
(card, anonymous_id) unique constraint makes the contradiction unrepresentable at the table level
rather than merely discouraged by a submit view machine writers never call; see that model's own
docstring, and ``_split_new_illustration_votes`` here for why the write path must compare the
stored illustration_id VALUE and not just that key.

THE ARTIST INPUT IS OCR-DERIVED, NEVER VOTE-DERIVED (issue #523). Stated here as well as at the
``match_artist`` call site because #524 is precisely the change that makes the loop reachable: a
human illustration answer can derive a ``CardArtistVote`` (``illustration_id → artist`` is
functional), so if artist votes ever became input to this calculator's artist matching it would
re-confirm an artist derived from an illustration it proposed itself — agreement manufactured out
of one human click. The input is and must remain ``ImageEvidence.artist_ocr_name``.

Wired into ``local_calculate_verdicts.py`` (management command) after the fallback calculator,
before slow-path routing. Reuses ``_eligible_cards_queryset`` from that module for the base
eligibility query, with an additional artist-ocr filter. Gate: ``verify_zero_resolutions``
after writes (human-backed consensus prevents machine-only resolution).
"""

import logging
import uuid as uuid_module
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from django.db import transaction
from django.db.models import Count, Max, Q, QuerySet

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_fallback import match_artist
from cardpicker.local_identify_printing_tags import CandidateNameIndex, generate_run_id
from cardpicker.models import (
    CanonicalCard,
    CanonicalPrintingMetadata,
    Card,
    CardIllustrationVote,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    ImageEvidence,
    PrintingTagStatus,
    VoteSource,
    purge_stale_machine_votes,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.search.sanitisation import to_searchable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Own anonymous_id — distinct from every other Stage D engine's identity for
# independent purge/re-run via ``purge_machine_votes --run-id``.
ILLUSTRATION_ANONYMOUS_ID = "stage-d-illustration-v2"

# Owner-ratified base confidence (issue #507 spec). Informational-only — does
# NOT flow into ``resolve_vote_weight``; the human-backed consensus gate
# prevents machine-only resolution regardless of confidence value.
BASE_CONFIDENCE = 0.85

# The two remaining knowledge-inventory constants, duplicated as literals from
# ``local_calculate_verdicts.py`` — same "avoid a hard import-time dependency
# between sibling engines over one constant" precedent.
RESOLUTION_FLOOR_DPI = 200
EXCLUDED_RESOLVED_TAGS = ["custom-art", "non-english"]

# Skip reasons
NO_EVIDENCE_SKIP_REASON = "no-evidence"
NO_ARTIST_OCR_SKIP_REASON = "no-artist-ocr"
# DELETED, DELIBERATELY NOT REPLACED: v1's `SINGLE_FACED_ONLY_SKIP_REASON = "multi-faced-v1"`.
# It gated on `ImageEvidence.layout_class`, which holds a BORDER COLOUR, never faced-ness (see
# the module docstring's v1 → v2 section). The 3,409 existing `multi-faced-v1` CardScanLog rows
# are left in place as evidence of what v1 did; they no longer exclude anything, because the
# eligibility query matches scan logs by `anonymous_id` and this calculator's id is now `-v2`.
NO_CANDIDATE_MATCH_SKIP_REASON = "no-candidate-match"
NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON = "no-illustration-index-entry"

# The two 1:1-rule abstentions (issue #525 — see the module docstring's "THE 1:1 RULE" section).
# Deliberately TWO strings, not one: only the second carries a fact issue #524 can later persist
# without re-deriving it, so the recoverable population has to be separable by a plain
# `WHERE skip_reason = '...'` query.
#
# N>1 surviving illustrations — genuinely ambiguous, no single illustration identity exists to
# retain. (This constant already existed in this module but was never reachable; the N>1 branch
# cast N competing votes instead of using it. It now does what its name always said.)
MULTIPLE_ILLUSTRATIONS_SKIP_REASON = "multiple-illustrations"
# Exactly 1 surviving illustration, but it maps to more than one printing — the illustration
# identity IS known; only the printing choice is undetermined. `IllustrationVerdict` carries the
# `illustration_id` and the candidate printing pks on this abstention.
MULTIPLE_PRINTINGS_SKIP_REASON = "multiple-printings-one-illustration"

# Cards the join-key calculator already concluded have no confident hit —
# this calculator only considers those. Carried verbatim from
# ``local_calculate_verdicts.JOIN_KEY_NO_HIT_SKIP_REASONS``.
_JOIN_KEY_NO_HIT_SKIP_REASONS = frozenset(
    {
        "ambiguous",
        "no-text",
        "proxy-marker-veto",
        "border-mismatch",
        "frame-mismatch",
        "truncated-image",
        "copyright-year-mismatch",
        "unknown-set-code",
    }
)

# Rescannable skip reasons for this calculator — "no-evidence" is transient
# (a future extraction may land it).
RESCANNABLE_SKIP_REASONS = frozenset({NO_EVIDENCE_SKIP_REASON})


# ---------------------------------------------------------------------------
# In-memory illustration index
# ---------------------------------------------------------------------------


class IllustrationIndex:
    """
    In-memory index mapping ``(artist_pk, searchable_card_name) → {illustration_id_str → [printing_pk]}``.

    Built from ``CanonicalCard`` rows that have ``CanonicalPrintingMetadata.illustration_id``
    non-null. TWO KINDS OF KEY are written per row:

      - the printing's own ``CanonicalCard.name`` → its scalar ``illustration_id``. For a
        double-faced printing that name is Scryfall's combined ``"{front} // {back}"`` string and
        that id is the FRONT face's, exactly as before — unchanged, and relied on by four other
        consumers of the scalar column.
      - for a genuine double-faced printing ONLY (``CanonicalPrintingMetadata.
        face_illustrations`` non-empty), one key per FACE: that face's own name → that face's own
        ``illustration_id``. This is what lets a back-face-named upload resolve to the artwork
        actually printed on the side that was scanned, instead of to the front's; it is why v1's
        single-faced gate could be deleted rather than repaired. Split/adventure/flip rows never
        reach here — ``face_illustrations`` is empty for them by construction, so a second MODE
        printed on the same physical face never becomes a second scannable artwork.

    A face whose ``illustration_id`` is null (Scryfall omits it for faces without art) is skipped:
    a missing artwork must not become an index entry keyed on the string ``"None"``.

    Both kinds of key map to the SAME printing pk, which is correct — the vote is for a printing,
    and a double-faced printing is one printing however many sides it has. Where a face name
    collides with a differently-illustrated card of the same name by the same artist (basic lands
    on ``reversible_card`` printings are the real instance), the key simply accumulates both
    illustrations and the calculator abstains with ``multiple-illustrations`` — the safe
    direction, and the honest one: such a scan genuinely does not say which artwork it is.

    Also exposes:
      - ``artist_by_pk``: ``{card_pk → artist_name}`` for ``match_artist``
      - ``card_pk_to_artist_pk``: ``{canonical_card_pk → artist_pk}`` for post-match lookups

    CATALOG-WIDE, NOT BATCH-SCOPED — two full ``CanonicalCard`` scans (113,224 rows live). Never
    construct this directly from a Stage E hot path; go through
    ``_get_cached_illustration_index()`` below, which memoizes one instance per worker process
    behind a cheap version stamp (see that function and the section comment above it).
    """

    def __init__(self) -> None:
        # (artist_pk, searchable_name) → {illustration_id_str → [printing_pk]}
        self._index: dict[tuple[int, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        # artist_pk → artist_name (for match_artist's artist_by_pk parameter)
        self.artist_by_pk: dict[int, str] = {}
        # canonical_card_pk → artist_pk (for post-match lookup)
        self.card_pk_to_artist_pk: dict[int, int] = {}

        # No `.select_related(...)` here: chained BEFORE a `.values_list()` that already names
        # its own traversals (`artist__name`, `printing_metadata__illustration_id`), it is a
        # documented no-op - `values_list` builds its own JOINs from the traversal arguments and
        # discards the select_related plan entirely, so the call added zero rows to the SELECT and
        # zero saved queries. Removed rather than "made effective" (i.e. rather than dropping the
        # traversals and hydrating model instances instead): hydrating 113,224 CanonicalCard +
        # CanonicalArtist + CanonicalPrintingMetadata objects to read four columns off each is the
        # expensive direction, and `values_list` is exactly what `CandidateNameIndex` itself uses
        # for the same catalog-wide-index-build job.
        rows = CanonicalCard.objects.filter(printing_metadata__illustration_id__isnull=False).values_list(
            "pk",
            "name",
            "artist__pk",
            "artist__name",
            "printing_metadata__pk",
            "printing_metadata__illustration_id",
            "printing_metadata__face_illustrations",
        )

        for (
            card_pk,
            card_name,
            artist_pk,
            artist_name,
            printing_pk,
            illustration_id,
            face_illustrations,
        ) in rows:
            if artist_pk is None:
                continue  # type: ignore[unreachable]
            searchable_name = to_searchable(card_name)
            key = (artist_pk, searchable_name)
            illustration_str = str(illustration_id)
            self._index[key][illustration_str].append(printing_pk)

            # Per-face keys — genuine double-faced printings only (see the class docstring).
            for face in face_illustrations or []:
                face_name = face.get("name") or ""
                face_illustration_id = face.get("illustration_id")
                if not face_name or face_illustration_id is None:
                    continue
                face_key = (artist_pk, to_searchable(face_name))
                if face_key == key:
                    # A face whose own name normalises to the combined name — no real Scryfall
                    # row does this, but a hand-built fixture can, and re-appending the same
                    # printing pk under the same key would read as ambiguity that isn't there.
                    continue
                self._index[face_key][str(face_illustration_id)].append(printing_pk)

        # Populate artist_by_pk and card_pk_to_artist_pk from ALL canonical cards (not just
        # those with illustration metadata) so match_artist can identify artists even when
        # they have no illustration data yet. The illustration lookup (illustration_printings)
        # will still return empty for cards whose artists have no metadata, correctly producing
        # NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON.
        all_cards = CanonicalCard.objects.filter(artist__isnull=False).values_list("pk", "artist__pk", "artist__name")
        for card_pk, artist_pk, artist_name in all_cards:
            self.artist_by_pk[card_pk] = artist_name
            self.card_pk_to_artist_pk[card_pk] = artist_pk

    def illustration_printings(self, artist_pk: int, searchable_card_name: str) -> dict[str, list[int]]:
        """Return ``{illustration_id_str → [printing_pk]}`` for the given (artist, card_name) key."""
        return dict(self._index.get((artist_pk, searchable_card_name), {}))


# ---------------------------------------------------------------------------
# Read-side narrowing: illustration → candidate printings (issue #524)
# ---------------------------------------------------------------------------


def printings_for_illustration(
    illustration_id: "str | uuid_module.UUID",
    candidate_printing_pks: Optional[Iterable[int]] = None,
) -> "QuerySet[CanonicalCard]":
    """
    THE NARROWING, AS A READ. Given a Scryfall ``illustration_id``, return the ``CanonicalCard``
    printings that carry it, joined through ``CanonicalPrintingMetadata.illustration_id``.

    This is the whole reason ``CardIllustrationVote`` stores an artwork rather than a printing.
    ``illustration_id → printing`` is 1:N (roughly 2.2 printings per illustration across the
    catalogue), so knowing the artwork narrows the printing without determining it. That
    narrowing is DERIVABLE FROM REFERENCE DATA AT READ TIME and must stay that way: it must
    NEVER be materialised as implied ``CardPrintingTag`` rows. Writing one row picks a printing
    the evidence does not support; writing N rows asserts N mutually exclusive printings under a
    single identity, which is exactly the defect issue #525 was filed for. There is no vote here
    and this function writes nothing.

    ``candidate_printing_pks`` (optional) intersects the result with a caller-supplied candidate
    list — e.g. ``IllustrationVerdict.candidate_printing_pks``, or the printings a Stage E
    micro-batch is already working with. Pass it whenever the caller HAS such a list, so the
    query costs O(candidates) instead of O(every printing carrying this artwork); the parameter
    exists for the same reason ``_eligible_illustration_cards_queryset``'s own ``card_ids``
    does (issues #458/#460 — nothing a micro-batch calls may cost O(catalog)). ``None`` returns
    the unscoped set.

    Returns a LAZY queryset (never a list), so a caller that only wants ``.count()``,
    ``.exists()``, or a ``values_list`` of pks never hydrates model instances, and so this
    composes into a larger query as a subquery rather than a materialised ``IN`` list.

    MATCHES BACK-FACE ILLUSTRATIONS TOO (2026-07-29). The scalar ``illustration_id`` column only
    ever holds the FRONT face's artwork, so an illustration vote naming a BACK face's artwork —
    which this calculator can now cast — would narrow to zero printings under a scalar-only
    filter, silently reading as "no printing carries this artwork" when the truth is "the column
    we looked in never stores that side". The ``face_illustrations`` containment term is the same
    claim asked of the per-face column; a printing matching on either term carries the artwork.
    """
    queryset = CanonicalCard.objects.filter(
        Q(printing_metadata__illustration_id=illustration_id)
        | Q(printing_metadata__face_illustrations__contains=[{"illustration_id": str(illustration_id)}])
    ).distinct()
    if candidate_printing_pks is not None:
        queryset = queryset.filter(pk__in=candidate_printing_pks)
    return queryset


# ---------------------------------------------------------------------------------------------
# LAZY, PER-WORKER-PROCESS ``IllustrationIndex`` CACHE — the same shape (and the same reason)
# ``local_calculate_verdicts._get_cached_candidate_name_index()`` already implements for
# ``CandidateNameIndex`` under issue #469, applied here because this calculator is invoked from
# ``stage_e_dispatch._run_stage_d`` ONCE PER 25-CARD MICRO-BATCH. ``IllustrationIndex.__init__``
# issues two catalog-wide ``CanonicalCard`` queries (113,224 rows live) — one filtered on
# ``printing_metadata__illustration_id``, one unfiltered over every card with an artist — and
# builds full-catalog dicts from both. Rebuilding that per micro-batch is O(catalog) work inside
# a conveyor whose whole contract (issues #458/#460) is O(batch), and it dominates the cost of a
# micro-batch that ends up with one eligible card, or none.
#
# Invalidation is a cheap version-stamp CHECK per call, not a write-time hook — the same
# "no soundness implication" trade ``_candidate_name_index_version_stamp`` documents. The stamp
# is ``(CanonicalCard max pk, CanonicalCard count, CanonicalPrintingMetadata max pk,
# CanonicalPrintingMetadata count, count of NON-NULL illustration_id, count of NON-EMPTY
# face_illustrations)``. The first four catch any INSERT (a fresh max pk) or DELETE (count moves
# even when max pk doesn't) in either table; the fifth and sixth exist because this index's whole
# input is TWO columns that are BACKFILLED IN PLACE — ``import_scryfall_printing_metadata``
# populates ``illustration_id`` and ``face_illustrations`` on rows that already exist, an UPDATE
# that moves neither max pk nor row count. Without those terms a worker process that built the
# index before a backfill would serve a stale, under-populated index for its whole lifetime.
# ``illustration_id`` is ``db_index=True`` and ``face_illustrations`` has a PARTIAL index whose
# predicate is exactly the sixth term's ``WHERE`` (``cpm_face_illustrations_present``, see the
# model), so both extra terms are index-only counts, not table scans.
#
# STILL NOT DETECTED (accepted, same reasoning as the CandidateNameIndex cache's own comment): an
# in-place rename of a ``CanonicalCard.name`` or ``CanonicalArtist.name``, or an in-place change
# of an ALREADY-NON-NULL ``illustration_id`` to a different value. Those are catalog-data edits,
# not routine, and a stale index in that narrow case re-derives the same deduction a fresh one
# would for every card whose row did not change. No vote-soundness exposure: this is a pure
# performance change.
# ---------------------------------------------------------------------------------------------

IllustrationIndexVersionStamp = tuple[int, int, int, int, int, int]

_illustration_index_cache: Optional[tuple[IllustrationIndexVersionStamp, "IllustrationIndex"]] = None


def _illustration_index_version_stamp() -> IllustrationIndexVersionStamp:
    """
    Cheap (index-only aggregates, not table scans) stamp used to detect a
    ``CanonicalCard``/``CanonicalPrintingMetadata`` write since the cached ``IllustrationIndex``
    was built — see this section's own comment above for the full invalidation-shape rationale,
    including why the non-null ``illustration_id`` count is a term and what is deliberately not
    detected.
    """
    canonical_card_agg = CanonicalCard.objects.aggregate(max_pk=Max("pk"), count=Count("pk"))
    printing_metadata_agg = CanonicalPrintingMetadata.objects.aggregate(max_pk=Max("pk"), count=Count("pk"))
    illustration_id_count = CanonicalPrintingMetadata.objects.filter(illustration_id__isnull=False).count()
    face_illustrations_count = CanonicalPrintingMetadata.objects.exclude(face_illustrations=[]).count()
    return (
        canonical_card_agg["max_pk"] or 0,
        canonical_card_agg["count"] or 0,
        printing_metadata_agg["max_pk"] or 0,
        printing_metadata_agg["count"] or 0,
        illustration_id_count,
        face_illustrations_count,
    )


def _get_cached_illustration_index() -> "IllustrationIndex":
    """
    Returns the current worker process's cached ``IllustrationIndex``, building (or rebuilding, on
    a version-stamp mismatch) it exactly once per distinct stamp. Call this LAZILY — only once
    there is a card that actually needs an illustration lookup, never unconditionally at the top
    of a dispatch — so a micro-batch whose ``card_ids``-scoped eligible set is empty pays neither
    the index build nor even this function's own version-stamp query.
    """
    global _illustration_index_cache
    stamp = _illustration_index_version_stamp()
    if _illustration_index_cache is not None and _illustration_index_cache[0] == stamp:
        return _illustration_index_cache[1]
    index = IllustrationIndex()
    _illustration_index_cache = (stamp, index)
    return index


def reset_illustration_index_cache_for_tests() -> None:
    """
    TEST-ONLY hook, never called from any production code path — clears the module-level
    ``IllustrationIndex`` cache above, so a test asserting an exact construction COUNT starts from
    a known-empty cache instead of depending on Postgres's own incidental
    sequence-advance-across-rollback behaviour. Mirrors
    ``local_calculate_verdicts.reset_candidate_name_index_cache_for_tests``.
    """
    global _illustration_index_cache
    _illustration_index_cache = None


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IllustrationVerdict:
    """
    Pure result of one card's illustration deduction — no DB write yet.

    ``printing_pks`` is the vote to cast and is EMPTY on every abstention. The narrowing evidence
    an abstention did establish lives in the three fields below it, deliberately kept out of
    ``printing_pks`` so no future reordering of the runner's loop can turn retained evidence into
    cast votes:

      - ``illustration_id``: the resolved illustration, as a string. Set when exactly one
        illustration survived — i.e. on the 1:1 vote AND on the
        ``MULTIPLE_PRINTINGS_SKIP_REASON`` abstention, which is the case issue #524
        (``CardIllustrationVote``) will be able to persist without re-deriving anything. Empty
        when N>1 illustrations survived: there is no single identity and none is invented.
      - ``candidate_printing_pks``: the printings that illustration narrowed to. Populated on the
        ``MULTIPLE_PRINTINGS_SKIP_REASON`` abstention.
      - ``illustration_count``/``printing_count``: how ambiguous the abstention was, so the
        narrowing is measurable rather than merely counted.

    Nothing here is persisted beyond the ``CardScanLog.skip_reason`` string — see the module
    docstring's "ABSTAIN-WITH-EVIDENCE" section.
    """

    card_id: int
    printing_pks: tuple[int, ...] = ()
    confidence: float = 0.0
    skip_reason: str = ""
    illustration_count: int = 0
    printing_count: int = 0
    illustration_id: str = ""
    candidate_printing_pks: tuple[int, ...] = ()


# ---------------------------------------------------------------------------
# Calculator result
# ---------------------------------------------------------------------------


@dataclass
class IllustrationCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    # `multi_faced_skipped` DELETED with v1's gate — it only ever counted the border-colour
    # misread (see the module docstring's v1 → v2 section). Nothing replaces it: there is no
    # faced-ness skip in v2, so a counter for one would be permanently zero.
    votes_would_cast: int = 0
    # Cards whose candidate list was resolved by widening a back-face name to its combined DFC
    # name (see `_resolve_illustration_candidates`). Counted, not asserted, so the population v1's
    # gate structurally could never reach is measurable from a dry run.
    back_face_resolved: int = 0
    votes_written: int = 0
    already_voted: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)
    # THE COVERAGE COST OF THE 1:1 RULE (issue #525), made measurable rather than asserted.
    # `cards_abstained_ambiguous` is how many cards the calculator would have voted on before the
    # rule and now abstains on; `printing_votes_withheld` is how many CardPrintingTag rows those
    # cards would have produced (one per competing printing). The ratio between them is the
    # per-card contradiction width. Both are counted in dry-run mode too, so the figure can be
    # obtained from a dry run rather than a live write.
    cards_abstained_ambiguous: int = 0
    printing_votes_withheld: int = 0
    # ILLUSTRATION-IDENTITY COVERAGE (issue #524) — counted separately from the printing-vote
    # counters above because the two now diverge on purpose: every card whose evidence resolves to
    # exactly ONE illustration records a `CardIllustrationVote`, including the cards the 1:1 rule
    # makes abstain from a printing vote. `illustration_votes_would_cast` therefore includes
    # `cards_abstained_ambiguous`' single-illustration share, and is the measure of how much of the
    # coverage `printing_votes_withheld` reports as lost is in fact RETAINED at the artwork grain
    # rather than discarded. Counted in dry-run mode too, same as the pair above.
    illustration_votes_would_cast: int = 0
    illustration_votes_written: int = 0
    illustration_votes_already_voted: int = 0


# ---------------------------------------------------------------------------
# Eligible-cards query
# ---------------------------------------------------------------------------


def _eligible_illustration_cards_queryset(
    join_key_voted_card_ids: Iterable[int],
    join_key_scanned_card_ids: Iterable[int],
    chunk_size: int = 500,
    card_ids: Optional[Iterable[int]] = None,
) -> "QuerySet[Card]":
    """
    Cards the join-key calculator already concluded have no confident hit, plus the same base
    eligibility filters as every other Stage D calculator (via a fresh queryset matching
    ``_eligible_cards_queryset``'s exact shape).

    Additional constraint:
      - Current ``ImageEvidence`` with non-null ``artist_ocr_name`` (checked per-card in the
        loop, not in the queryset, since ImageEvidence is keyed by content_phash).

    v1's "single-faced layouts only" constraint is GONE (see the module docstring): it read
    ``ImageEvidence.layout_class`` as faced-ness when that column holds a border colour, and the
    concern it stood for is now answered by per-face illustration data instead.

    ``card_ids`` (Stage E micro-batch scoping) mirrors
    ``local_calculate_verdicts._eligible_cards_queryset``'s own parameter exactly — a pure scope
    narrowing, applied to BOTH the outer ``Card`` queryset and the ``CardScanLog`` subquery below.
    ``None`` (BULK mode) leaves both unscoped, byte-identical to this function's pre-``card_ids``
    behaviour.
    """
    # Start with the same base query every Stage D calculator uses: unresolved, no
    # confirmed match, card_type=CARD, no own-vote, no non-rescannable scan-log,
    # resolution floor, excluded tags.
    non_rescannable_scanned = CardScanLog.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).exclude(
        skip_reason__in=RESCANNABLE_SKIP_REASONS
    )
    if card_ids is not None:
        # Issue #469 (Tron §8 gate finding, 2026-07-25), carried over to this calculator: CardScanLog
        # is 2,093,147 rows live and append-only, growing — when the caller has already narrowed the
        # outer Card queryset to `card_ids` (as `stage_e_dispatch._run_stage_d` does, 25 cards at a
        # time), this subquery must be scoped the same way rather than scanning the whole table.
        # Purely a cost narrowing, not a behaviour change: the resulting excluded-pk set is
        # equivalent for THIS caller either way, since a row this subquery would find outside
        # `card_ids` could never survive the outer queryset's own `.filter(pk__in=card_ids)`
        # (applied below) regardless. `card_ids is None` (BULK mode) leaves this exactly as it was
        # before this fix — unscoped over the whole table.
        non_rescannable_scanned = non_rescannable_scanned.filter(card_id__in=card_ids)

    queryset = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .exclude(printing_tags__anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned.values_list("card_id", flat=True))
        .exclude(Q(dpi__lt=RESOLUTION_FLOOR_DPI) & Q(dpi__isnull=False))
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[0]])
        .exclude(tags__contains=[EXCLUDED_RESOLVED_TAGS[1]])
        # Join-key no-hit population — cards the join-key calculator found no
        # confident hit for (is_no_match vote OR a non-rescannable skip).
        .filter(Q(pk__in=join_key_voted_card_ids) | Q(pk__in=join_key_scanned_card_ids))
        .distinct()
        .select_related("source")
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


# ---------------------------------------------------------------------------
# Verdict calculation
# ---------------------------------------------------------------------------


def calculate_illustration_verdict(
    card_id: int,
    evidence: ImageEvidence,
    illustration_index: IllustrationIndex,
    candidates: list[Any],
    searchable_card_name: str,
) -> IllustrationVerdict:
    """
    Pure function — computes one card's illustration verdict from evidence and index state.

    Flow:
      1. ``match_artist(evidence.artist_ocr_name, candidates, illustration_index.artist_by_pk)``
         → surviving candidate pks.
      2. For each surviving candidate pk, get its artist_pk via
         ``illustration_index.card_pk_to_artist_pk``.
      3. Look up ``(artist_pk, searchable_card_name)`` in the illustration index → illustration_ids.
      4. Resolve a printing ONLY at 1:1 (issue #525 — see the module docstring's "THE 1:1 RULE"):
         0 illustrations → abstain; 1 illustration → 1 printing → vote; 1 illustration → N
         printings → abstain, RETAINING the illustration identity; N>1 illustrations → abstain,
         retaining nothing but the counts.

    ``candidates`` is a list of objects with a ``.pk`` attribute (CanonicalCard pks) — either
    real ``CandidatePrinting`` objects from ``CandidateNameIndex.candidates_for()`` or lightweight
    adapter objects (see ``_CandidateAdapter`` below).
    """
    # INVARIANT (issue #523) — THE ARTIST INPUT IS OCR-EVIDENCE-DERIVED AND MUST NEVER BE
    # VOTE-DERIVED. Both arguments below are vote-free by construction and must stay that way:
    # `evidence.artist_ocr_name` comes off an `ImageEvidence` row (Tesseract output), and
    # `illustration_index.artist_by_pk` is built from `CanonicalCard`/`CanonicalArtist` reference
    # data. Neither reads `CardArtistVote`.
    #
    # WHY THIS MATTERS NOW RATHER THAN LATER: `illustration_id -> artist` is functional, so a human
    # illustration answer can legitimately derive a `CardArtistVote` from it - and this calculator
    # runs the INVERSE direction, matching an OCR artist name to find the illustration. Sourcing
    # the artist input from votes would close the loop: the calculator would re-confirm an artist
    # that was itself derived from an illustration the calculator proposed, manufacturing
    # multi-source "agreement" out of a single human click and a single machine guess. Issue #524
    # (`CardIllustrationVote`, landed alongside this comment) is what makes that loop reachable at
    # all, which is why the lock lands with it and not after.
    #
    # Pinned by `test_local_illustration.py::TestArtistInputIsOcrDerivedNotVoteDerived`, which
    # asserts on THIS SEAM directly - the exact argument passed here - rather than on the verdict,
    # because a rewire that swapped the source could still produce an identical verdict.
    surviving_card_pks = match_artist(evidence.artist_ocr_name, candidates, illustration_index.artist_by_pk)

    if surviving_card_pks is None:
        return IllustrationVerdict(card_id=card_id, skip_reason=NO_CANDIDATE_MATCH_SKIP_REASON)

    # Collect unique illustration_ids across all surviving candidates' artists.
    illustration_printing_map: dict[str, list[int]] = {}
    for card_pk in surviving_card_pks:
        artist_pk = illustration_index.card_pk_to_artist_pk.get(card_pk)
        if artist_pk is None:
            continue
        illustrations = illustration_index.illustration_printings(artist_pk, searchable_card_name)
        for illustration_id_str, printing_pks in illustrations.items():
            if illustration_id_str not in illustration_printing_map:
                illustration_printing_map[illustration_id_str] = []
            illustration_printing_map[illustration_id_str].extend(printing_pks)

    if not illustration_printing_map:
        return IllustrationVerdict(card_id=card_id, skip_reason=NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON)

    n_illustrations = len(illustration_printing_map)

    if n_illustrations > 1:
        # N>1 illustrations — abstain (issue #525). This branch used to cast the union of
        # printings across all N illustrations, one vote each at BASE_CONFIDENCE/N: N
        # full-machine-weight votes for mutually exclusive printings under ONE anonymous_id,
        # because confidence never reaches the tally. Nothing is retained beyond the counts:
        # there is no single illustration identity here and inventing a representative would be
        # picking an answer the evidence does not support.
        distinct_printing_pks: list[int] = []
        seen_pks: set[int] = set()
        for printing_pks in illustration_printing_map.values():
            for pk in printing_pks:
                if pk not in seen_pks:
                    seen_pks.add(pk)
                    distinct_printing_pks.append(pk)
        return IllustrationVerdict(
            card_id=card_id,
            skip_reason=MULTIPLE_ILLUSTRATIONS_SKIP_REASON,
            illustration_count=n_illustrations,
            printing_count=len(distinct_printing_pks),
        )

    single_illustration_id, single_illustration_pks_raw = next(iter(illustration_printing_map.items()))
    # de-duplicate: the same printing can be reached twice when two surviving candidates share an
    # artist, which would otherwise read as "ambiguous" for a genuinely 1:1 narrowing.
    single_illustration_pks = list(dict.fromkeys(single_illustration_pks_raw))

    if len(single_illustration_pks) != 1:
        # Exactly 1 illustration, but it maps to N printings — the common case for any reprinted
        # artwork, not an edge case. Abstain (issue #525), but RETAIN what was genuinely
        # established: the illustration identity is known with full confidence, only the printing
        # choice is undetermined. Issue #524 (`CardIllustrationVote`) is where this becomes a
        # persisted answer; nothing is written here.
        return IllustrationVerdict(
            card_id=card_id,
            skip_reason=MULTIPLE_PRINTINGS_SKIP_REASON,
            illustration_count=1,
            printing_count=len(single_illustration_pks),
            illustration_id=single_illustration_id,
            candidate_printing_pks=tuple(single_illustration_pks),
        )

    # 1:1 — exactly one illustration, exactly one printing. The only case that votes.
    return IllustrationVerdict(
        card_id=card_id,
        printing_pks=(single_illustration_pks[0],),
        confidence=BASE_CONFIDENCE,
        illustration_count=1,
        printing_count=1,
        illustration_id=single_illustration_id,
    )


# ---------------------------------------------------------------------------
# Candidate adapter for match_artist compatibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CandidateAdapter:
    """Lightweight adapter with just a ``.pk`` attribute — satisfies ``match_artist``'s interface."""

    pk: int


def _resolve_illustration_candidates(
    name: str,
    candidate_name_index: "CandidateNameIndex",
    default_cards_path: "Optional[Path]" = None,
) -> tuple[list[_CandidateAdapter], str, bool]:
    """
    Back-face-aware candidate selection for this calculator, returning
    ``(candidates, illustration_index_name, widened)``.

    THE TWO NAMES ARE DELIBERATELY DIFFERENT, and that difference is the whole point.
    ``CanonicalCard.name`` for a genuine double-faced card is Scryfall's combined
    ``"{front} // {back}"`` string, so a back-face-named upload can never match
    ``CandidateNameIndex.candidates_for(name)`` directly — structurally, however good the OCR is.
    ``local_calculate_verdicts._resolve_candidates_for_card`` already solved that for the join-key
    engine by widening to the combined name via the ``DFCPair`` table, and this reuses the same
    two-step, same ``is_back_face`` guard, same "return the (empty) direct result rather than
    guessing" failure mode.

    What it does NOT reuse is which name the illustration lookup is keyed on. The CANDIDATES must
    be found under the combined name (that is where the ``CanonicalCard`` rows live), but the
    ILLUSTRATION must be looked up under the BACK-FACE name — because
    ``IllustrationIndex`` now files each face's own artwork under that face's own name, and the
    combined-name key still resolves to the FRONT face's scalar ``illustration_id``. Keying the
    illustration lookup on the widened name would hand a back-face scan the front's artwork,
    which is precisely the wrong-vote exposure v1's deleted gate was standing in for.

    The direct (single-faced, front-named, or combined-named upload) path is byte-identical to
    what this calculator did before: same candidates, same ``to_searchable(card.name)`` key. The
    ``DFCPair``/``is_back_face`` lookups are only paid by names the direct lookup missed, which is
    the same "only pay for what you use" shape ``_resolve_candidates_for_card`` established.
    """
    direct = candidate_name_index.candidates_for(name)
    if direct:
        return [_CandidateAdapter(pk=c.pk) for c in direct], to_searchable(name), False

    from cardpicker.models import DFCPair
    from cardpicker.printing_metadata_import import is_back_face

    if not is_back_face(name, default_cards_path=default_cards_path):
        return [], to_searchable(name), False
    front_name = DFCPair.objects.filter(back=name).values_list("front", flat=True).first()
    if front_name is None:
        return [], to_searchable(name), False
    widened = candidate_name_index.candidates_for(f"{front_name} // {name}")
    if not widened:
        return [], to_searchable(name), False
    # Candidates from the COMBINED name; illustration key from the BACK-FACE name.
    return [_CandidateAdapter(pk=c.pk) for c in widened], to_searchable(name), True


# ---------------------------------------------------------------------------------------------
# CardIllustrationVote write path (issue #524)
#
# FOLLOW-UP — UNIFY WITH THE GENERALIZED PRIMITIVE. The two functions below are a deliberate
# small equivalent of `local_calculate_verdicts._split_new_printing_tag_votes` /
# `_purge_and_write_printing_tag_votes`, written here rather than there because that module is
# being generalized concurrently by another worker and must not be edited from this change. Once
# that generalization lands (a model-agnostic split/purge/write primitive), these should be
# deleted and replaced by calls into it — with the ONE semantic difference below carried across,
# not dropped: this model's split compares the illustration_id VALUE as well as the
# (card, anonymous_id) key.
# ---------------------------------------------------------------------------------------------


def _split_new_illustration_votes(
    votes_batch: list[CardIllustrationVote],
) -> tuple[list[CardIllustrationVote], int]:
    """
    Partition `votes_batch` into (votes to write, count already voted) — the same pre-write
    skip-if-exists guard, and the same ordering contract, as
    `local_calculate_verdicts._split_new_printing_tag_votes`: one batched existence query scoped
    to just the (card_id, anonymous_id) pairs present in this batch, run BEFORE any purge (a
    purge run first would delete exactly the rows this function looks for, making the
    `already_voted` counter structurally zero forever — see that function's own docstring and
    `stage_e_dispatch.DispatchOutcome`'s "zero forever would suggest the guard itself is dead
    code" contract).

    THE ONE DIFFERENCE, AND IT IS LOAD-BEARING: this function compares the illustration_id VALUE,
    not only the (card_id, anonymous_id) KEY.

    `CardIllustrationVote`'s unique constraint is UNCONDITIONAL on (card, anonymous_id) — see
    that model's own docstring for why it diverges from `CardPrintingTag`/`CardArtistVote`. Under
    a key-only comparison that constraint would make a CORRECTED answer permanently unlandable:
    if a metadata refresh (an `import_scryfall_printing_metadata` run that changes which
    illustration this card's artwork resolves to) produces a DIFFERENT `illustration_id` for a
    card that already has a row, a key-only split sees the existing row, calls it "already
    voted", drops the card from `new_votes` — and so the card never reaches the purge that would
    have made room for the new value. Even if it somehow did reach the insert,
    `ignore_conflicts=True` would swallow it silently. The stale answer would win forever, with
    no error and no counter moving.

    So the comparison is on the pair AND the value:
      - existing row, SAME illustration_id  → genuinely redundant. Skipped, counted in
        `already_voted`. Re-running the calculator is a no-op, which is the idempotence property
        the whole Stage D framework depends on.
      - existing row, DIFFERENT illustration_id → a changed conclusion, NOT a collision. Kept in
        `new_votes`, so `_purge_and_write_illustration_votes` deletes the stale row and writes
        the new one inside one transaction — an overwrite, which is what a corrected answer is.
      - no existing row → a fresh vote. Kept.

    `is_unknown` rows compare as a NULL illustration_id, so a flip in either direction between
    "unknown" and a named illustration is also treated as a changed answer, not a collision.

    This is deliberately NOT the "skip-and-count, not retract-and-recast" choice
    `_split_new_printing_tag_votes` documents, and the difference is not an inconsistency: that
    function's reasoning is explicitly conditioned on both racing invocations computing the SAME
    verdict from the SAME inputs, and it names a genuinely-changed conclusion (re-extracted
    evidence, a corrected catalogue) as the case its skip does NOT cover. Here the value
    comparison is what distinguishes the two, so the redundant case is still skipped and only the
    genuinely-changed case overwrites.
    """
    if not votes_batch:
        return [], 0

    card_ids = {vote.card_id for vote in votes_batch}
    anonymous_ids = {vote.anonymous_id for vote in votes_batch}
    existing_by_key: dict[tuple[int, str], Optional[uuid_module.UUID]] = {
        (card_id, anonymous_id): illustration_id
        for card_id, anonymous_id, illustration_id in CardIllustrationVote.objects.filter(
            card_id__in=card_ids, anonymous_id__in=anonymous_ids
        ).values_list("card_id", "anonymous_id", "illustration_id")
    }

    new_votes = []
    for vote in votes_batch:
        key = (vote.card_id, vote.anonymous_id)
        if key in existing_by_key and _same_illustration(existing_by_key[key], vote.illustration_id):
            continue  # unchanged answer — a genuine no-op
        new_votes.append(vote)
    return new_votes, len(votes_batch) - len(new_votes)


def _same_illustration(stored: Any, proposed: Any) -> bool:
    """
    Value comparison for `_split_new_illustration_votes`, normalising through `uuid.UUID` so a
    string-vs-UUID mismatch never reads as a changed answer. `IllustrationVerdict.illustration_id`
    is a `str` (the index keys on strings), the DB column is a `UUIDField`, and an unsaved model
    instance holds whatever the caller assigned — three representations of the same value that
    a naive `==` would call different, which would turn every re-run into a spurious overwrite.
    `None` (an `is_unknown` row) compares equal only to `None`.
    """
    return _as_uuid(stored) == _as_uuid(proposed)


def _as_uuid(value: Any) -> Optional[uuid_module.UUID]:
    if value is None or value == "":
        return None
    if isinstance(value, uuid_module.UUID):
        return value
    try:
        return uuid_module.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _purge_and_write_illustration_votes(anonymous_id: str, new_votes: list[CardIllustrationVote]) -> None:
    """
    Purge + write, all-or-nothing — the established semantics of
    `local_calculate_verdicts._purge_and_write_printing_tag_votes`, applied to
    `CardIllustrationVote`. Read that function's docstring for the full reasoning; the three
    properties carried over verbatim are:

    ORDERING: callers MUST run `_split_new_illustration_votes` FIRST and pass its `new_votes`
    output here, never the raw batch. `purge_stale_machine_votes` deletes by CALCULATOR FAMILY
    (`^<family>-v\\d+$`), which necessarily includes the caller's own current `anonymous_id`, so a
    purge run first empties the table the split is about to interrogate.

    SCOPED TO `new_votes`, NOT THE FULL BATCH: a card whose vote the split skipped as unchanged
    must KEEP its existing row. Purging on the full batch would delete that row and then not
    re-insert it (it is no longer in `new_votes`), destroying a committed vote to replace it with
    nothing.

    CANCEL-SAFETY: DELETE and INSERT are separate statements; a process killed between them —
    which this project's operator does deliberately, mid-flight — would otherwise leave the
    affected cards with their previous vote deleted and no replacement. `transaction.atomic()`
    makes the pair all-or-nothing. `ignore_conflicts=True` stays as the second line of defence for
    the residual check-then-insert window.

    WHAT THE PURGE DOES HERE THAT IT DOES NOT DO FOR `CardPrintingTag`: because
    `cardillustrationvote_unique_vote` is unconditional on (card, anonymous_id), the purge is also
    the mechanism by which a CHANGED answer replaces the stale one — the split lets such a card
    through precisely so it reaches this delete-then-insert. Both stale-VERSION rows (`...-v1`
    when the calculator is now `...-v2`) and stale-VALUE rows under the current version are
    removed by the same family-scoped DELETE, so version self-overwrite (#519/#520) is preserved
    unchanged and answer correction works by the same path.
    """
    if not new_votes:
        return
    with transaction.atomic():
        purge_stale_machine_votes(CardIllustrationVote, anonymous_id, "card_id", [_v.card_id for _v in new_votes])
        CardIllustrationVote.objects.bulk_create(new_votes, ignore_conflicts=True)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_illustration_calculator(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
    default_cards_path: Optional[Path] = None,
) -> IllustrationCalculatorResult:
    """
    Batch runner for the illustration deduction calculator (issue #507).

    Mirrors ``run_fallback_calculator``'s shape: iterates eligible cards, computes verdicts,
    batches ``CardPrintingTag`` writes, calls ``resolve_and_persist_printing`` per touched card.
    ``dry_run=True`` (default) computes and counts everything without writing.
    ``card_ids`` is forwarded to the eligibility queryset for Stage E micro-batch scoping.
    ``default_cards_path`` is passed straight through to ``_resolve_illustration_candidates``'
    own ``is_back_face`` call — ``None`` (the default, used in production) resolves to the real
    on-disk Scryfall cache; only ever overridden by a test.

    TWO INDEPENDENT WRITE GRAINS (issue #524). A run now produces up to two kinds of vote per
    card, on DIFFERENT conditions, and they must not be conflated:

      - ``CardPrintingTag`` — cast ONLY at 1:1 (exactly one illustration mapping to exactly one
        printing). Issue #525's rule, UNCHANGED by #524. Nothing below weakens it.
      - ``CardIllustrationVote`` — cast whenever exactly ONE illustration was resolved, no matter
        how many printings that illustration maps to. That includes every card the 1:1 rule makes
        abstain from a printing vote with ``MULTIPLE_PRINTINGS_SKIP_REASON``, which is the whole
        point: #526 deliberately RETAINED the resolved ``illustration_id`` on the verdict so this
        writer can persist it without re-deriving anything, and until #524 there was nowhere to
        put it. At N>1 illustrations nothing is written at either grain — there is no single
        identity to record, and the ``MULTIPLE_ILLUSTRATIONS_SKIP_REASON`` scan-log row #526
        writes is retained exactly as-is.

    The illustration vote is a claim about the ARTWORK, not the printing. It does NOT imply, and
    must never be expanded into, printing votes for the printings sharing that artwork — see
    ``printings_for_illustration``, which is the read-side narrowing that replaces materialising
    them, and ``CardIllustrationVote``'s own docstring for the constraint that makes the
    contradiction unrepresentable.
    """
    run_id = run_id or generate_run_id()
    result = IllustrationCalculatorResult(dry_run=dry_run, run_id=run_id)

    # Lazy, CACHED indexes — both are catalog-wide builds, resolved on first actual need below and
    # never unconditionally here, so a micro-batch whose eligible set turns out empty pays for
    # neither. See ``_get_cached_illustration_index`` above and
    # ``local_calculate_verdicts._get_cached_candidate_name_index`` (issue #469) for the shared
    # per-worker-process, version-stamped caching these local variables sit in front of; the local
    # variables themselves exist only so the version-stamp CHECK is paid once per invocation
    # rather than once per card, exactly as ``run_join_key_calculator``/``run_fallback_calculator``
    # do with their own ``index`` locals.
    illustration_index: Optional[IllustrationIndex] = None
    candidate_name_index: Optional[CandidateNameIndex] = None

    votes_batch: list[CardPrintingTag] = []
    illustration_votes_batch: list[CardIllustrationVote] = []
    scan_log_batch: list[CardScanLog] = []
    touched_card_ids: list[int] = []

    # Pre-compute join-key no-hit populations for eligibility filtering.
    from cardpicker.local_calculate_verdicts import (
        JOIN_KEY_ANONYMOUS_ID,
        JOIN_KEY_NO_HIT_SKIP_REASONS,
        _get_cached_candidate_name_index,
    )

    # Deliberately NOT wrapped in `list(...)`: these stay lazy querysets so Django compiles them
    # into SQL subqueries of the `Q(pk__in=...) | Q(pk__in=...)` filter below, evaluated inside the
    # one eligibility query and narrowed by its own `card_ids` scope. Materializing them instead
    # pulled every join-key no-match vote and every join-key no-hit CardScanLog row (2,093,147 rows
    # live, append-only) into this process's memory on EVERY micro-batch, before any card_ids
    # scoping applied. Matches `local_calculate_verdicts._fallback_eligible_cards_queryset`, which
    # has always kept the identical pair lazy.
    join_key_no_match_card_ids = CardPrintingTag.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
    ).values_list("card_id", flat=True)
    join_key_no_hit_scanned_card_ids = CardScanLog.objects.filter(
        anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS
    ).values_list("card_id", flat=True)

    queryset = _eligible_illustration_cards_queryset(
        join_key_voted_card_ids=join_key_no_match_card_ids,
        join_key_scanned_card_ids=join_key_no_hit_scanned_card_ids,
        card_ids=card_ids,
    )

    for card in queryset.iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash to key ImageEvidence lookup

        # Lazy illustration index — resolved once we know there are eligible cards, from the
        # per-worker-process cache (NOT a fresh catalog-wide build per micro-batch).
        if illustration_index is None:
            illustration_index = _get_cached_illustration_index()

        evidence = (
            current_evidence_queryset(card)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )

        if evidence is None:
            result.skip_counts[NO_EVIDENCE_SKIP_REASON] = result.skip_counts.get(NO_EVIDENCE_SKIP_REASON, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=NO_EVIDENCE_SKIP_REASON,
                    )
                )
            continue

        if not evidence.artist_ocr_name or not evidence.artist_ocr_name.strip():
            result.skip_counts[NO_ARTIST_OCR_SKIP_REASON] = result.skip_counts.get(NO_ARTIST_OCR_SKIP_REASON, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=NO_ARTIST_OCR_SKIP_REASON,
                    )
                )
            continue

        result.cards_considered += 1

        # Lazy CandidateNameIndex — resolved through `local_calculate_verdicts`' own
        # per-worker-process cache (issue #469), the same call `run_join_key_calculator`/
        # `run_fallback_calculator` make. This used to call `CandidateNameIndex()` directly while
        # claiming in a comment to use "the same cached pattern" — it did not: it bypassed the
        # cache entirely and paid a fresh 113,224-row, 1.48s catalog scan on every micro-batch
        # that had at least one card with artist OCR.
        if candidate_name_index is None:
            candidate_name_index = _get_cached_candidate_name_index()

        # Build candidate list for match_artist — adapter objects with .pk — AND the name the
        # illustration index is keyed on. The two diverge for a back-face-named upload: see
        # `_resolve_illustration_candidates`.
        candidates, searchable_card_name, widened = _resolve_illustration_candidates(
            card.name, candidate_name_index, default_cards_path=default_cards_path
        )
        if widened:
            result.back_face_resolved += 1

        verdict = calculate_illustration_verdict(
            card_id=card.pk,
            evidence=evidence,
            illustration_index=illustration_index,
            candidates=candidates,
            searchable_card_name=searchable_card_name,
        )

        # THE ILLUSTRATION-IDENTITY WRITE (issue #524), decided BEFORE the skip branch below
        # because it is deliberately NOT conditioned on whether a printing vote gets cast.
        #
        # `verdict.illustration_id` is non-empty on EXACTLY the cards where one illustration
        # survived - the 1:1 vote AND the `MULTIPLE_PRINTINGS_SKIP_REASON` abstention - and empty
        # at N>1 illustrations, where there is no single identity and #526 deliberately invents no
        # representative. So this one truthiness check IS the rule "exactly one illustration
        # resolved". Nothing is re-derived: #526 retained this field on the verdict for precisely
        # this consumer.
        #
        # The confidence written here is BASE_CONFIDENCE, not `verdict.confidence`. Those differ on
        # the abstain path, and correctly so: `verdict.confidence` is the confidence in the
        # PRINTING (0.0 when no printing was chosen), while this vote's claim is about the
        # ARTWORK, which the calculator resolved with full confidence in both cases - the module
        # docstring's "the calculator KNOWS the illustration identity with full confidence and
        # merely cannot choose a printing". Reusing `verdict.confidence` would silently record a
        # confident identity claim as a zero-confidence one on the majority of its own population.
        if verdict.illustration_id:
            result.illustration_votes_would_cast += 1
            if not dry_run:
                illustration_votes_batch.append(
                    CardIllustrationVote(
                        card_id=card.pk,
                        illustration_id=verdict.illustration_id,
                        is_unknown=False,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        source=VoteSource.DEDUCTION,
                        confidence=BASE_CONFIDENCE,
                        run_id=run_id,
                    )
                )

        if verdict.skip_reason:
            result.skip_counts[verdict.skip_reason] = result.skip_counts.get(verdict.skip_reason, 0) + 1
            if verdict.skip_reason in (MULTIPLE_ILLUSTRATIONS_SKIP_REASON, MULTIPLE_PRINTINGS_SKIP_REASON):
                # The 1:1 rule's own coverage cost (issue #525) - see the result dataclass' own
                # comment. `printing_count` is exactly the number of CardPrintingTag rows the
                # pre-#525 code would have written for this card.
                result.cards_abstained_ambiguous += 1
                result.printing_votes_withheld += verdict.printing_count
                if len(result.audit) < audit_sample_size:
                    # The retained narrowing, carried into the audit sample so an operator can see
                    # WHAT was established without querying anything. `illustration_id` is set only
                    # for the single-illustration case - issue #524's recoverable population.
                    result.audit.append(
                        {
                            "card_id": card.pk,
                            "skip_reason": verdict.skip_reason,
                            "illustration_count": verdict.illustration_count,
                            "printing_count": verdict.printing_count,
                            "illustration_id": verdict.illustration_id,
                            "candidate_printing_pks": list(verdict.candidate_printing_pks),
                        }
                    )
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=verdict.skip_reason,
                    )
                )
            continue

        # Vote to cast. Post-#525 this is always exactly one printing - the 1:1 rule is the only
        # branch that reaches here with a non-empty `printing_pks` - but the loop below is left
        # general rather than asserting a length, since the batching shape is shared with the
        # other Stage D calculators.
        n_printings = len(verdict.printing_pks)
        result.votes_would_cast += n_printings

        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "card_id": card.pk,
                    "illustration_count": verdict.illustration_count,
                    "printing_count": verdict.printing_count,
                    "illustration_id": verdict.illustration_id,
                    "confidence": verdict.confidence,
                    "printing_pks": list(verdict.printing_pks),
                }
            )

        if not dry_run:
            for printing_pk in verdict.printing_pks:
                votes_batch.append(
                    CardPrintingTag(
                        card_id=card.pk,
                        printing_id=printing_pk,
                        is_no_match=False,
                        anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
                        source=VoteSource.DEDUCTION,
                        confidence=verdict.confidence,
                        run_id=run_id,
                    )
                )
            touched_card_ids.append(card.pk)

    if not dry_run:
        from cardpicker.local_calculate_verdicts import (
            _purge_and_write_printing_tag_votes,
            _split_new_printing_tag_votes,
        )

        # ORDER MATTERS — split/count FIRST, purge SECOND, purge+insert inside ONE transaction.
        # See `_purge_and_write_printing_tag_votes`' own docstring for both halves: running the
        # purge first deleted exactly the rows `_split_new_printing_tag_votes` looks for (so
        # `already_voted` was structurally 0 forever — the "zero forever would suggest the guard
        # itself is dead code" case
        # `stage_e_dispatch.DispatchOutcome.stage_d_illustration_already_voted` documents), and an
        # untransacted DELETE-then-INSERT loses votes outright if the process is killed between
        # the two, which this project's operator does deliberately, mid-flight.
        new_votes, result.already_voted = _split_new_printing_tag_votes(votes_batch)
        _purge_and_write_printing_tag_votes(ILLUSTRATION_ANONYMOUS_ID, new_votes)

        # Same ordering contract, same transaction shape, for the illustration grain - see
        # `_split_new_illustration_votes`/`_purge_and_write_illustration_votes` above, including
        # why this split compares the illustration_id VALUE and not just the key. Deliberately a
        # SEPARATE transaction from the printing-tag write rather than one wrapping both: the two
        # grains are independent claims, and coupling them would mean an illustration identity the
        # calculator resolved with full confidence gets rolled back because a printing vote for
        # some OTHER card in the same batch failed to insert.
        new_illustration_votes, result.illustration_votes_already_voted = _split_new_illustration_votes(
            illustration_votes_batch
        )
        _purge_and_write_illustration_votes(ILLUSTRATION_ANONYMOUS_ID, new_illustration_votes)
        result.illustration_votes_written = len(new_illustration_votes)

        if scan_log_batch:
            CardScanLog.objects.bulk_create(scan_log_batch)
        for touched_card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_printing(touched_card)

        result.votes_written = len(new_votes)

    return result
