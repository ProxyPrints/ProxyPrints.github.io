"""
Backs `GET 2/questionFeed/` - the unified single-question feed that replaces the three
printing/artist/tag tabs (see docs/features/printing-tags.md's questionFeed section and
journal/2026-07-14-queue-question-feed-design.md for the full design writeup this
implements). The ranked union is three remainder tiers with the first tier with supply winning
and no cross-tier scoring/ML, on top of which this module adds three SELECTION-layer policies:
the served-mix composition policy (2026-07-24, see "Mix composition policy" below), the
remainder-lane rotation policy (2026-08-10, see "Remainder mix policy" below), and the
within-tier information-gain re-ranking of each tier's own candidates (2026-08-09, see
"Information-gain question scoring" below). None of these changes how any tier's candidate set
is built or how votes are resolved - they change only WHICH candidate, and which tier, is served.

Tier 1 (confirm_suggestion) is large relative to the others at current volume (110,130 cards
carrying a machine DEDUCTION/OCR printing vote, measured live 2026-08-11) against the
contested/cold tiers' `settings.QUESTION_FEED_POOL_SIZE`-capped (500) pools: a voter working only
this feed used to not reach tiers 2-3 until tier 1 was exhausted, flagged as a known v1 property
in the original design doc's "Starvation risk" section rather than silently accepted. The
materialised candidate pools (issue #727, see "Materialised candidate pools" below) made this
starvation total rather than merely likely - a fixed confirm-then-contested-then-cold order over
a 500-entry contested/cold pool against a 110k-card confirm supply meant tiers 2/3 were
functionally unreachable, not just slow to reach. A weighted rotation across the remainder lanes
(`QUESTION_FEED_CONFIRM_MIX_WEIGHT`/`_CONTESTED_MIX_WEIGHT`/`_COLD_MIX_WEIGHT`, 2026-08-10) fixed
this for one release, but was itself interim - a lane RATIO invented, never measured, to paper
over tier 1 being asked for regardless of whether the machine's own evidence justified it. Issue
#766 tracks its removal; see "Evidence-gated printing-confirmation policy" below for what
replaces it (`docs/features/wtc-question-model.md` §2/§3, ratified 2026-08-11): tier 1 is no
longer one lane among three competing for a session's share, it is GATED - offered only when the
card's own recorded evidence justifies the claim - so there is no ratio left to tune, and the
former fixed confirm-then-contested-then-cold order is restored as the (now largely moot,
confirm-side) waterfall order.

Moderator report review used to be a fourth tier here (pending_approval pairs, moderator-only,
ranked between tiers 2 and 3-formerly-4) but that made every pending report displace the
normal tagging feed entirely for any moderator, for as long as reports stayed pending -
moved out to a dedicated Moderation tab (`POST 2/moderationQueue/` in views.py, unaffected by
this module) so ordinary tagging and report review are separate, switchable views instead of
one hijacking the other. See docs/features/moderation.md.

Mix composition policy (2026-07-24, owner-ratified per the WTC vote-queue data brief's OWNER
ADDENDUM; soundness citation now `docs/theory.md` §10 "Streaming and continuous operation" -
that section names this exact served-mix/human-vote-quality surface and its own "the place to
fold it in" invitation once a mix-logging mechanism landed, which this change is; full citation
in docs/features/printing-tags.md's "Unified question feed" section): serve
>=`settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO` (default
0.51) of a session's questions from the LIKELY-RESOLVE pool - a printing question one more
agreeing human vote would actually resolve under the real resolver, per
`is_likely_resolve_printing` below - whenever that pool still has supply for this voter,
falling back to the pre-existing three-tier ranked union otherwise (with one refinement inside
tier 4 - see `_tier_4_fresh`'s own docstring - that prioritizes cards whose latest Stage D
scan-log origin is a "quick-negative" reason over the harder/open-ended remainder, per the same
data brief's queue-composition ranking). This is a SELECTION-LAYER policy only: it makes zero
change to `vote_consensus.resolve_weighted_consensus`'s weights, `PRINTING_TAG_MIN_VOTES`/
`MIN_SHARE` thresholds, or the D1/D4 human-backed-priority mechanisms - `is_likely_resolve_
printing` calls that same real resolver to classify a question, it never reimplements its
arithmetic. Every served item (from either the likely-resolve pool or the remainder) is
recorded in `QuestionFeedServedLog` - the bias-conditioning record the data brief's SOUNDNESS
NOTE calls for, so a future audit can correlate click behavior against a session's
easy-question exposure. See `_served_mix_ratio`/`_log_served` below.

Evidence-gated printing-confirmation policy (2026-08-11, replaces the 2026-08-10 remainder mix
rotation, issue #766, docs/features/wtc-question-model.md §2/§3): the interim weighted rotation
across confirm/contested/cold (`QUESTION_FEED_CONFIRM_MIX_WEIGHT`/`_CONTESTED_MIX_WEIGHT`/
`_COLD_MIX_WEIGHT`, defaults 3/2/1) is deleted outright, not retuned - the ratified question model
holds there is no lane RATIO to tune in the first place: a printing confirmation (tier 1,
`confirm_suggestion`) is either JUSTIFIED by the machine's own recorded evidence for THIS card, or
it is not, and no target share fixes an unjustified claim being asked too often. `confirm_
suggestion` is the expensive question (see this module's own opening paragraph and the ratified
doc's §1): it asks the user to vouch for border, artist credit and set symbol (§2's fourth named
element, collector line, has no corresponding entry in `evidence_types_used` - see
`_KNOWN_EVIDENCE_TYPES`'s own comment for why this PR gates on the three that actually exist
rather than a fourth the calculator never produces) all at once, so it is gated at its one
construction site, `_confirm_suggestion_item` (see `_evidence_justifies_confirmation` below): a
`CardPrintingTag` vote is only ever offered as a `confirm_suggestion` suggestion when its own
`evidence_types_used` (issue #797 - carried onto the vote itself, not a separate `CardScanLog`
row a MATCH never writes) covers every evidence type the fallback calculator can record. Every
other card that would previously have been offered a confirmation - including every card with NO
recorded evidence at all, which was the overwhelming majority pre-#797 (measured 2026-08-11: 0 of
110,130 confirm-eligible cards cleared this gate, since a MATCHING fallback-calculator run
discarded its own computed evidence list instead of persisting it anywhere the gate could reach -
see `local_calculate_verdicts.calculate_fallback_verdict`)
- is simply not constructible as `confirm_suggestion`, and falls through to whichever of tier 2
(contested) or tier 4 (cold) already claims it: tier 4's own printing branch, in particular,
already includes every non-contested unresolved card regardless of vote count and already orders
by `-vote_count` first, so a card that fails the confirmation gate lands there ranked ahead of a
genuinely untouched (`vote_count=0`) card, and is served as `identify_printing` - a question that
presupposes nothing and is safe to ask regardless of evidence completeness (see the ratified
doc's own §7 "identify_printing - search-led"). No new lane, no new pool, no lane-selection
policy left to make: with tier 1 gated instead of ranked, the remainder waterfall
(`get_next_question_feed_item`'s loop below) is the plain confirm -> contested -> cold order the
mix rotation used to override, restored - it is no longer doing meaningful selection work of its
own (a gated, usually-empty tier 1 costs one cheap pool-miss check before falling through), so a
fixed order needs no proportional-fairness bookkeeping. This never starves the feed: the 110,130
cards that fail the gate keep their existing home in tier 4's non-contested printing population
(222,105 cards, measured 2026-08-11), they simply ask a cheaper, evidence-agnostic question
instead of an unjustified expensive one.

Correction (2026-08-21): the gate above shipped requiring border/artist/symbol - the vocabulary
`_KNOWN_EVIDENCE_TYPES` claimed was all the fallback calculator could ever produce - and never
served a single confirmation. Measured live: 0 of 230,318 printing votes pass it. Two defects,
both against the vocabulary claim itself. First, `symbol` is required but never recorded -
`_filter_by_symbol_phash` abstains on every card (see `_REQUIRED_EVIDENCE_TYPES`'s own comment for
its four abstention cases), so no vote has ever carried it; requiring an element no writer
produces makes the gate unsatisfiable by construction, not merely strict. Second, `collector_line`
- added to the vocabulary the same day as this gate (see `calculate_fallback_verdict`'s own
docstring) and recorded 2,369 times live - was never added to what the gate REQUIRES, dropping
the strongest of the four elements the ratified doc names. The gate now requires border/artist/
collector_line (`_REQUIRED_EVIDENCE_TYPES`) and treats a recorded `symbol` as optional
corroboration rather than a precondition; see that constant's own comment for the full reasoning.
Measured post-fix: ~1,637 votes pass (`artist,border,collector_line` is the one combination
observed live containing all three).

Information-gain selection within the remainder tiers (issue #716, 2026-08-09): where each
tier used to serve the first candidate of a fixed queryset, the tiers now score their
candidates by expected information gain - the entropy of the existing vote distribution across
the question's own dimension (printing candidates, artist consensus, tag review queues), or
the variance of the card's machine-derived attribute-chip signals where no vote distribution
exists yet - and serve the highest-scoring one, within a bounded candidate window. This is a
SELECTION-LAYER policy only, the direct successor to tier 4's old `-vote_count` "closest to
resolving" heuristic (which survives as that tier's tiebreak): it re-ranks WHICH candidate a
tier serves, never how `vote_consensus.resolve_weighted_consensus` weighs or resolves a vote,
and every prior selection rule (tier precedence, kind precedence, per-tier exclusion sets,
`-vote_count`/quick-negative/`-date_created` ordering) is preserved as the tiebreak whenever
two candidates score equally. See the "Information-gain question scoring" section below.

md5 identity groups (issue #473, owner-ratified 2026-07-25): a set of cards indexing a
byte-identical image file is ONE identification target, so this feed asks about it once. Two
consequences here, both delegated to `printing_consensus` rather than reimplemented: the
likely-resolve classification reads the GROUP's pooled tally (`_printing_vote_tuples` ->
`group_printing_votes`/`build_group_printing_vote_tuples`), and every printing tier excludes
the full identity group of every card this voter has already answered
(`_voter_answered_printing_card_ids`), so a voter is served at most one member per group rather
than N copies of the same question. Both degenerate exactly to the pre-#473 behavior for a card
whose group is itself alone, which - until that issue's PR-1 populates `Card.md5_checksum` - is
every card in the catalogue. The artist and tag tiers are untouched by this: identity grouping
is a statement about the IMAGE FILE, and those questions are already keyed differently.

Materialised candidate pools (issue #727): `get_next_question_feed_item` tries a
`question_feed_pools.draw_*` call for each of its likely-resolve pool / confirm / contested / cold
branches - likely-resolve always first, the remaining three in whichever order the "Remainder mix
policy" above picks for this request - and pools are the SOLE serving mechanism on this request
path - a pool draw returning `None` (a cache miss: never warmed, evicted, or the
`"shared"` backend isn't configured; or this voter's exclusion/staleness filtering exhausting
every entry) means that lane has no supply for this request, and the waterfall simply moves on
to the next lane. The request path never builds a pool inline and never falls back to a live
scan of a tier's own query - see `question_feed_pools`'s own module docstring for why (the cost
that would reintroduce). The `_tier_1_confirm_suggestion`/`_tier_2_contested`/`_tier_4_fresh`/
`_likely_resolve_printing_card` functions below still define each lane's SELECTION semantics
and item construction (`warm_pool_cache`'s builders mirror their filter/exclude/order clauses)
and remain directly callable/tested in isolation, but `get_next_question_feed_item` itself never
calls them - if every lane misses, the feed honestly returns `None` rather than paying for a
live build. See `question_feed_pools`'s own module docstring for the full pool architecture (why
pools are shared not per-voter, the bounded-and-randomised serve, per-lane warm cadence, and the
staleness/precedence reasoning).
"""

import hashlib
import math
import uuid
from collections import defaultdict
from typing import Any, Callable, Hashable, Iterable, Optional, Sequence

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.db.models import (
    Case,
    Count,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)

from cardpicker import question_feed_pools
from cardpicker.artist_consensus import get_contested_artist_card_ids
from cardpicker.attribute_tags import ATTRIBUTE_CHIP_TAG_NAMES
from cardpicker.illustration_consensus import eliminated_illustration_ids
from cardpicker.local_calculate_verdicts import (
    FALLBACK_ELIMINATED_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_BORDER_MISMATCH_SKIP_REASON,
    JOIN_KEY_FRAME_MISMATCH_SKIP_REASON,
    JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
)
from cardpicker.local_fallback import BORDER_COLOR_TO_TAG
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardArtistVote,
    CardIllustrationVote,
    CardPrintingTag,
    CardQuestionAbstention,
    CardScanLog,
    CardTagVote,
    HiddenCard,
    IllustrationVoteStatus,
    PrintingTagStatus,
    QuestionFeedServedLog,
    QuestionFeedServedPool,
    Tag,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.printing_candidates import get_ranked_printing_candidates
from cardpicker.printing_consensus import (
    build_group_printing_vote_tuples,
    get_contested_card_ids,
    group_printing_votes,
    identity_group_expanded_card_ids,
)
from cardpicker.reason_tags import NOT_OFFICIAL_ART_REASON_TAGS
from cardpicker.schema_types import (
    PrintingCandidate,
    QuestionFeedCounts,
    QuestionFeedItem,
    TypeEnum,
)
from cardpicker.tag_consensus import get_tag_net_polarity, get_tag_review_queue_pairs
from cardpicker.vote_consensus import (
    VoteTuple,
    is_human_backed_source,
    resolve_vote_weight,
    resolve_weighted_consensus,
)

# Origin reasons `local_calculate_verdicts.py`'s Stage D join-key/fallback calculators write to
# `CardScanLog.skip_reason` that the 2026-07-24 data brief's queue-composition item classifies
# as "answerable-as-quick-negative" - a quick, low-ambiguity classification click (custom-art/
# no-match/visual-contradiction), not an open-ended one. All four now have named
# constants in `local_calculate_verdicts.py` (imported above): the 2026-07-29
# declaration-convention sweep gave the three that used to be bare literals here ("eliminated"/
# "border-mismatch"/"frame-mismatch") their own `*_SKIP_REASON` declarations at their write
# sites, so this set no longer restates any string by hand. See docs/reference/skip-reasons.md
# for the full roster.
# Deliberately EXCLUDES "ambiguous" despite the brief calling it "YES - answerable" in principle:
# the same brief's prioritization item ranks it as BLOCKED on a build dependency
# (`CardScanLog.survivor_pks` is unpopulated for every to-review card - see that field's own
# docstring), not free supply today, so it falls into this module's default/hard-open-ended
# bucket alongside "no-sub-check-evidence"/"no-text" rather than the quick-negative one.
QUICK_NEGATIVE_SKIP_REASONS = frozenset(
    {
        JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON,
        FALLBACK_ELIMINATED_SKIP_REASON,
        JOIN_KEY_BORDER_MISMATCH_SKIP_REASON,
        JOIN_KEY_FRAME_MISMATCH_SKIP_REASON,
    }
)

# anonymous_id placeholder for the hypothetical vote `is_likely_resolve_printing` adds - never
# persisted, never compared against a real anonymous_id; passed through `resolve_vote_weight`
# (rather than reading `vote_consensus._SOURCE_WEIGHTS[VoteSource.USER]` directly) purely so this
# stays routed through the one sanctioned weight-resolution entry point, matching every other
# caller's convention, even though `resolve_vote_weight`'s only override (the frozen 2026-07-14
# deductive-backfill cohort) can never match `source=VoteSource.USER` regardless of anonymous_id
# or run_id.
_HYPOTHETICAL_VOTE_ANONYMOUS_ID = "question-feed-hypothetical-vote"

# The full vocabulary `evidence_types_used` can ever contain, on either the `CardScanLog` row a
# skip writes or the `CardPrintingTag` vote a match writes (issue #797): border/artist/symbol are
# `calculate_fallback_verdict`'s three FILTERING sub-checks, and collector_line (added 2026-08-11)
# is RECORDED alongside them without filtering anything - see that function's own docstring and
# its inline comment at the append site for the full mechanism.
_KNOWN_EVIDENCE_TYPES = frozenset({"border", "artist", "symbol", "collector_line"})

# The subset of `_KNOWN_EVIDENCE_TYPES` the confirmation gate actually REQUIRES. Two corrections
# against the vocabulary above, both measured live 2026-08-21 against 230,318 printing votes:
#
# 1. `collector_line` is required. The ratified question model (docs/features/
#    wtc-question-model.md §2) names border, artist credit, set symbol AND collector line as the
#    four things "the machine must have matched" - collector_line is the strongest signal of the
#    four (`CanonicalCard`'s unique constraint on `(expansion, collector_number)` resolves it to
#    exactly one printing by construction) and it IS being recorded (2,369 times in the corpus),
#    so a gate that omits it is dropping the element it should trust most.
# 2. `symbol` is excluded. Every printing vote's `evidence_types_used` was inspected live: symbol
#    appears in ZERO of them. This is not missing data - `_filter_by_symbol_phash` abstains
#    (returns `None`, so `calculate_fallback_verdict` never appends "symbol") on every card it has
#    ever run against, per its own docstring's four abstention cases (no glyph reading, no glyph
#    rendered, distance over `SYMBOL_DISTANCE_THRESHOLD`, runner-up within `SYMBOL_MARGIN`).
#    Requiring an element no writer has ever produced makes the gate unsatisfiable by construction
#    - measured 2026-08-21, 0 of 230,318 printing votes passed a gate that required it.
#
# `symbol` stays in `_KNOWN_EVIDENCE_TYPES` above rather than being deleted from the vocabulary: an
# abstention is not a missing element to demand, but a recorded "symbol" is still real
# corroboration when the matcher does fire, and if that matcher is ever repaired a vote carrying
# it should keep counting - see `_evidence_justifies_confirmation` below, which checks subset
# containment, not equality, so a vote WITH "symbol" recorded still clears the gate. Do not add
# "symbol" back to this frozenset without first fixing `_filter_by_symbol_phash` so it can
# actually produce a reading; until then it would just re-break the gate the same way.
_REQUIRED_EVIDENCE_TYPES = frozenset({"border", "artist", "collector_line"})

# The four border-colour attribute-chip tags (`local_fallback.BORDER_COLOR_TO_TAG`'s own
# values, not restated) - the likely-resolve routing gate below checks whether any of them has
# reached RESOLVED_APPLY consensus for a card before treating its border colour as "recorded".
_BORDER_COLOR_TAG_NAMES = frozenset(BORDER_COLOR_TO_TAG.values())

# Reason code the frontend's "Can't tell from this scan." border answer sends on
# `CardQuestionAbstention.reason` - a stated inability to read the border colour off the scan,
# not a deferral. A plain Skip on the same question abstains with `reason=None`, which never
# matches this constant, so it is excluded from exclusion (the card stays answerable later).
CANNOT_TELL_ABSTENTION_REASON = "cannot-tell"


def _evidence_justifies_confirmation(vote: CardPrintingTag) -> bool:
    """True only when `vote`'s own recorded `evidence_types_used` covers every REQUIRED type
    (`_REQUIRED_EVIDENCE_TYPES`) - the operational form of docs/features/wtc-question-model.md
    §2's "all four matched" gate, applied to border/artist/collector_line (see
    `_REQUIRED_EVIDENCE_TYPES`'s own comment for why symbol is excluded from the requirement
    while staying in `_KNOWN_EVIDENCE_TYPES` as optional corroboration - subset containment below
    means a vote that DOES carry "symbol" still clears the gate). False for a vote with partial
    evidence and False for a vote with none recorded at all (`evidence_types_used` is null on
    every vote no writer has populated it for - every vote cast before this field existed, every
    human vote, every join-key/deductive-backfill vote) - both cases are routed identically here,
    to the SAME fallback (tier 2/4's existing `identify_printing` machinery), because there is no
    per-element question type in `TypeEnum` to route a specific gap to (`artist`/`tag`/
    `identify_printing`/`confirm_suggestion` are the only four - see `schema_types.TypeEnum`);
    the finer-grained "ask about specifically the missing element" routing the ratified doc's §3
    describes is not implementable at the backend-selection layer without a new question type,
    which is out of this change's scope (backend serving/selection only - no frontend, no new
    calculator work).

    Reads the field directly off the vote being confirmed, not off `CardScanLog` (issue #797):
    the only outcome that can ever reach this gate is a MATCH (`_confirm_suggestion_item` only
    calls this once a `CardPrintingTag` already exists to confirm), and a MATCH never writes a
    `CardScanLog` row at all (`local_calculate_verdicts.run_fallback_calculator`'s skip-only scan-
    log write) - so a scan-log read here was always structurally unreachable for the population
    this gate serves. `CardPrintingTag.evidence_types_used`'s own docstring is the single source
    of truth this reads; `CardScanLog.evidence_types_used` remains the skip path's own unchanged
    record and has no reader here."""
    return _REQUIRED_EVIDENCE_TYPES.issubset(frozenset(vote.evidence_types_used or []))


def _tag_confidence(card: Card) -> dict[str, float]:
    """netPolarity for every attribute-chip tag against `card`, for the chip fill overlay -
    always the full fixed set (not just tags with votes), so an unvoted chip predictably reads
    as 0.0 (neutral) rather than being absent from the payload."""
    tags_by_name = {tag.name: tag for tag in Tag.objects.filter(name__in=ATTRIBUTE_CHIP_TAG_NAMES)}
    return {name: get_tag_net_polarity(card, tag) for name, tag in tags_by_name.items()}


def _confirm_suggestion_item(card: Card) -> Optional[QuestionFeedItem]:
    # Two independent gates compose here, in the order that keeps the expensive read lazy.
    #
    # 1. The EVIDENCE GATE (#775, tightened to per-VOTE by #797's `_evidence_justifies_
    #    confirmation` below): does the specific vote a candidate would suggest carry its own
    #    recorded `evidence_types_used` covering every type the pipeline can record? Decides
    #    whether THAT vote may be offered as a confirmation AT ALL - a card with several machine
    #    votes can have some pass and others fail, so this filters `ai_votes` rather than
    #    short-circuiting on the card as a whole.
    # 2. ELIMINATION CONSENSUS - "Not this art" (docs/features/wtc-question-model.md §7.1): a
    #    candidate-SET-level filter. A suggestion whose artwork the group has already reached
    #    elimination consensus on (`illustration_consensus.eliminated_illustration_ids`) must
    #    not be re-served as a NEW confirm_suggestion question to a DIFFERENT voter - that
    #    would ask the same rejected question again, which is exactly the "discards usable
    #    evidence" failure this whole feature exists to close.
    #
    # The two commute semantically (both must hold; neither reads the other's output), so the
    # ordering is a COST decision, not a correctness one: the gate is a field access on rows
    # already fetched by the one query below, while `eliminated_illustration_ids(card)` is a
    # separate group-scoped consensus query - so the gate runs first, and the elimination read is
    # paid only for a card that still has a gate-admitted candidate left. Measured 2026-08-11
    # (pre-#797 fix), the gate rejected every confirm-eligible card, so keeping the elimination
    # read inside the candidate loop (its laziness is untouched: still computed only once a
    # candidate with a non-null illustration_id is actually seen) would have paid that consensus
    # query for every sampled confirm-shaped card at pool-warm time for zero served items - see
    # `question_feed_pools._build_pool_confirm`, which calls this per card. Only a card that
    # could actually be served as confirm_suggestion ever touches the elimination machinery.
    ai_votes = list(
        card.printing_tags.filter(source__in=[VoteSource.DEDUCTION, VoteSource.OCR], is_no_match=False)
        .select_related("printing__expansion", "printing__printing_metadata", "printing__artist")
        .order_by("pk")[:20]
    )
    # #775's own short-circuit, preserved: a card with no machine candidate at all is not
    # confirm-shaped, so neither the gate nor the elimination read is paid for it.
    if not ai_votes:
        return None
    ai_votes = [vote for vote in ai_votes if _evidence_justifies_confirmation(vote)]
    if not ai_votes:
        return None
    eliminated_ids: Optional[set[uuid.UUID]] = None
    ai_vote = None
    for candidate_vote in ai_votes:
        metadata = getattr(candidate_vote.printing, "printing_metadata", None)
        illustration_id = getattr(metadata, "illustration_id", None) if metadata is not None else None
        if illustration_id is not None:
            if eliminated_ids is None:
                try:
                    eliminated_ids = eliminated_illustration_ids(card)
                except Exception:
                    eliminated_ids = set()
            if illustration_id in eliminated_ids:
                continue
        ai_vote = candidate_vote
        break
    if ai_vote is None or ai_vote.printing is None:
        return None
    candidates = get_ranked_printing_candidates(card, card.name)
    return QuestionFeedItem(
        type=TypeEnum.confirmsuggestion,
        card=card.serialise(),
        suggestedPrinting=ai_vote.printing.serialise_as_printing_candidate(),
        candidates=[candidate.serialise_as_printing_candidate() for candidate in candidates],
        tagConfidence=_tag_confidence(card),
    )


def _identify_printing_item(card: Card) -> Optional[QuestionFeedItem]:
    """`None` when `card` has no ranked printing candidates at all
    (`get_ranked_printing_candidates` returns `[]`) - per docs/features/wtc-question-model.md
    §5 rule 5 ("never ask for a claim the user has not been shown the evidence to make"), a
    `identify_printing` question with nothing in its candidate grid asks the voter to pick a
    printing from a set that has no options, which no answer can satisfy. Every caller must
    treat `None` as "this card is not servable as identify_printing right now" and either try
    the next candidate or fall through to the next tier/lane - never serve the empty grid.
    Measured live 2026-08-22: ~10% of UNRESOLVED cards (all six Urza's Saga rows among them)
    carry zero ranked candidates and were being served this question anyway before this guard."""
    candidates = get_ranked_printing_candidates(card, card.name)
    if not candidates:
        return None
    return QuestionFeedItem(
        type=TypeEnum.identifyprinting,
        card=card.serialise(),
        candidates=[candidate.serialise_as_printing_candidate() for candidate in candidates],
        tagConfidence=_tag_confidence(card),
    )


def _scryfall_illustration_url(card: Card) -> Optional[str]:
    """
    The Scryfall art-crop URL of `card`'s canonical printing, surfaced on artist-type feed
    items (WTC artist question re-frame) so the frontend can show the artwork itself rather
    than the full scanned card image. Delegates the printing lookup to `Card.
    _get_indexed_printing_metadata` rather than re-deriving the same `canonical_card` (a
    confirmed indexing match) -> RESOLVED-gated `inferred_canonical_card` precedence here -
    that's the exact fallback chain `get_border_color`/`get_frame`/`get_frame_effects`/
    `get_full_art` already share, and reimplementing it a second time would only risk the two
    copies drifting. The URL itself is the one already harvested from Scryfall's bulk-data
    dump into `CanonicalPrintingMetadata.art_crop_url` (see that field's own docstring), never
    a hand-assembled CDN path - Scryfall's `cards.scryfall.io` image URLs are keyed by the
    card's Scryfall UUID, not by set code/collector number, so a URL this module didn't read
    out of the metadata sidecar could not be constructed correctly here anyway. Returns None
    when the card has no canonical printing or that printing's metadata row carries no
    art_crop_url (the frontend falls back to the plain card image).

    Costs up to two small indexed lookups per call (the canonical printing FK, then its
    metadata sidecar) - bounded and per-served-item, not per-candidate-scan, so no prefetch
    wiring is added for it (artist items are served one per feed request).
    """
    metadata = card._get_indexed_printing_metadata()
    if metadata is None or not metadata.art_crop_url:
        return None
    return metadata.art_crop_url


def _artist_item(card: Card) -> QuestionFeedItem:
    serialised = card.serialise()
    confidently_known_artist_name = (
        serialised.canonicalArtist.name
        if serialised.canonicalArtist is not None and not serialised.canonicalArtistIsFromVoteOnly
        else None
    )
    return QuestionFeedItem(
        type=TypeEnum.artist,
        card=serialised,
        confidentlyKnownArtistName=confidently_known_artist_name,
        scryfallIllustrationUrl=_scryfall_illustration_url(card),
    )


def _tag_item(card: Card, tag_name: str) -> QuestionFeedItem:
    return QuestionFeedItem(type=TypeEnum.tag, card=card.serialise(), tagName=tag_name)


def _border_item(card: Card) -> QuestionFeedItem:
    """
    The per-element border question (wtc-question-model.md §7): asks which of the four
    border colours - Black / White / Silver / Borderless, the exclusive `BORDER_COLOR_GROUP`
    axis - this card has. Renders the border axis alone as the answer surface; each chip tap
    casts through the existing `CardTagVote` path (`useTagVoting`/`APISubmitTagVote`, the same
    call every other attribute chip in the feed makes), so no new vote model or endpoint is
    involved. `tagConfidence` carries the full attribute-chip net-polarity set (the same
    payload confirm/identify items ship) so the frontend can seed the chips' fill overlay; the
    border chips are the only ones the border question renders.

    Additive-only by scope: this builder exists beside `_artist_item`/`_tag_item` but is NOT
    wired into `get_next_question_feed_item`'s selection/waterfall, which PR #775 owns.
    """
    return QuestionFeedItem(
        type=TypeEnum.border,
        card=card.serialise(),
        tagConfidence=_tag_confidence(card),
    )


def _illustration_item(card: Card) -> Optional[QuestionFeedItem]:
    """
    The illustration question (wtc-question-model.md §7.2): asks which artwork this card
    depicts. Renders art crops only, never framed card renders, grouped by unique
    illustration_id. Each tap casts through the existing `2/submitIllustrationVote/` endpoint
    (cast_illustration_vote), which also derives an artist vote automatically. A rejection
    casts through `2/submitIllustrationRejection/` (cast_illustration_rejection). This
    question never casts a printing vote regardless of group size - a proxy scan may be an
    unofficial variant of the artwork, so illustration identification is distinct from
    printing identification.

    `None` unless the deduplicated candidate set is a genuine MULTI-WAY choice (at least two
    distinct illustration_ids): the illustration UI is a grid to pick among, and a set that
    collapses to zero or one distinct artwork is not a choice at all - a zero-candidate result
    renders nothing under the prompt, and a one-candidate result is a confirmation wearing a
    chooser's clothes. Every caller must treat `None` as "this card is not servable as
    illustration right now" and either try the next candidate or fall through to the next
    tier/lane, mirroring `_identify_printing_item`'s own "None means unservable this way"
    contract. This is the fix for the mismatch between what admits a card into the illustration
    lane (`_tier_4_fresh`/`_build_pool_cold` check only whether SOME cast printing tag carries
    an illustration_id) and what actually builds its answers (a name-similarity search of the
    card, `get_ranked_printing_candidates`, which routinely disagrees with that one tag).
    """
    candidates = get_ranked_printing_candidates(card, card.name)
    seen_illustration_ids: set[Optional[str]] = set()
    unique_candidates: list[PrintingCandidate] = []
    for candidate in candidates:
        illustration_id = candidate.serialise_as_printing_candidate().illustrationId
        if illustration_id not in seen_illustration_ids:
            seen_illustration_ids.add(illustration_id)
            unique_candidates.append(candidate.serialise_as_printing_candidate())
    if len(unique_candidates) < 2:
        return None
    return QuestionFeedItem(
        type=TypeEnum.illustration,
        card=card.serialise(),
        illustrationCandidates=unique_candidates,
        tagConfidence=_tag_confidence(card),
    )


def _printing_vote_tuples(card: Card) -> list[VoteTuple]:
    """
    Builds `VoteTuple`s for the current `CardPrintingTag` rows of `card`'s md5 IDENTITY GROUP -
    every card indexing a byte-identical image file, `card` included (issue #473) - by calling
    `printing_consensus.group_printing_votes`/`build_group_printing_vote_tuples`, the exact
    functions `printing_consensus.resolve_printing` itself uses, so the group expansion, the
    per-vote weight/human-backed resolution, and the machine-evidence pooling are one shared
    implementation rather than a second copy that could drift from the real resolver. Passing no
    `printings_by_id` keeps this off `vote.printing` entirely: only the outcome KEY (an int pk or
    the `NO_MATCH` sentinel) matters for the likely-resolve check below, and this runs in a scan
    loop. A group of one yields exactly the tuples this function built before #473.
    """
    votes, is_group = group_printing_votes(card)
    return build_group_printing_vote_tuples(votes, pool=is_group)


# ---------------------------------------------------------------------------------------------
# Information-gain question scoring (issue #716). The tiers below select their candidate by
# expected information gain per unit of user effort: the question whose existing evidence is
# most uncertain - the community's votes most evenly split across the outcomes that question
# asks about - is the one whose next answer resolves the most, so it is the one worth serving
# next. Each question dimension gets its own entropy term (printing candidates, artist
# consensus, tag review queues), and a card with no vote distribution at all is scored on the
# variance of its machine-derived attribute-chip signals instead (the cold-start "attribute
# variance" dimension - a card whose own derived picture is internally inconsistent is where
# a human vote is worth the most). This is a SELECTION-LAYER change only: it re-ranks which
# candidate each tier serves, never how `vote_consensus.resolve_weighted_consensus` weighs or
# resolves a vote, and every existing selection rule (`-vote_count`, the quick-negative
# tiebreak, `-date_created`, per-tier exclusion sets) survives as the tiebreak whenever two
# candidates score equally (see `_max_scored_candidate`).
# ---------------------------------------------------------------------------------------------

# How many candidates (per question kind) a live tier actually scores per serve. A bounded
# window rather than a full-pool sort: each scored candidate costs a small number of indexed
# vote queries, and this re-ranking runs on the live tier functions' own (direct-call, off the
# request path) paths - the materialised pools serve the hot path, where the draw's windowed
# sort uses the score each entry captured at WARM time in `PoolEntry.score` instead (see
# `question_feed_pools._precomputed_information_gain_score`, which computes this same value).
# The window is the ranking's candidate horizon: a genuinely higher-value question past the
# window is not seen this serve, but nothing is lost permanently - the next serve draws a fresh
# window from the same pre-ranked queryset, and the pool is the long-horizon layer this reorder
# refines.
_CANDIDATE_SCORING_WINDOW = 50

# Weight of the cold-start attribute-variance signal inside a printing question's score. A
# printing question that already carries votes is scored on the entropy of that vote
# distribution alone (the community IS the signal); a zero-vote card has no distribution, so
# the machine's own derived attribute confidence is the only signal available. The scale keeps
# a cold card from outranking a genuine contested-vote disagreement (the "medium = break a tie
# between competing votes" lane sits above the cold lane in issue #716's difficulty model) - a
# cold card's best possible variance (1.0) scores 0.25 against a contested card's entropy,
# which reaches 0.69+ nats for a two-way 50/50 split.
_ATTRIBUTE_VARIANCE_SCALE = 0.25


def _shannon_entropy(weights: Iterable[float]) -> float:
    """Shannon entropy, in nats, of the probability distribution formed by `weights` (entropy
    over the non-zero weights only - a zero-weight outcome contributes no probability mass).
    This is the expected-information-gain heuristic every score below is built on: a question
    whose evidence is evenly split (entropy at its maximum) is one whose next answer resolves
    the most uncertainty, so it is the highest-value question to serve; a unanimous or absent
    distribution (entropy 0.0) carries nothing left to learn. Returns 0.0 for an empty or
    all-zero weight set."""
    weights = [weight for weight in weights if weight > 0]
    total = sum(weights)
    if total <= 0:
        return 0.0
    return -sum(weight / total * math.log(weight / total) for weight in weights)


def _standard_deviation(values: Sequence[float]) -> float:
    """Population standard deviation of `values` - the "attribute variance" measure used by
    `_attribute_variance_map` below. 0.0 for an empty sequence."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _attribute_variance_map(cards: Sequence[Card]) -> dict[int, float]:
    """Attribute-variance score for every card in `cards`: the standard deviation of the card's
    attribute-chip net-polarity vector - the per-chip values `_tag_confidence` computes for the
    served item's confidence overlay (weighted net polarity per `ATTRIBUTE_CHIP_TAG_NAMES`,
    IMPLICIT votes excluded) - normalised to [0, 1] since every chip value lies in [-1, 1].

    What it means for selection (the "attribute variance" dimension of issue #716's policy): a
    card whose machine-derived attribute signals are internally inconsistent - some chips
    confidently positive, others confidently negative - is one the machine's own evidence
    disagrees about, and is therefore where a human answer resolves the most; a card with no
    chip signal at all (every chip neutral 0.0) or with uniform confidence scores 0.0. This is
    the cold-start term `_printing_question_score` falls back to for a card with no printing
    vote distribution, and the whole of `_tier_1_confirm_suggestion`'s re-ranking (its
    candidates all carry exactly one machine-sourced suggestion, so their vote entropy is
    identically zero).

    BATCHED: one query over every (candidate, chip-tag) vote for the whole window, instead of
    `_tag_confidence`'s per-card scan (N cards x ~11 chips would otherwise be N x 11 queries).
    The per-chip net-polarity math mirrors `get_tag_net_polarity` exactly - the same IMPLICIT
    exclusion and the same weights, routed through `resolve_vote_weight` (which for a tag vote
    never matches the frozen deductive-backfill cohort - that override is printing-only, see
    its own docstring - so it resolves to `_SOURCE_WEIGHTS[source]`, the identical value
    `get_tag_net_polarity` indexes directly) - so a windowed card scores identically to how its
    served-item confidence would read."""
    if not cards:
        return {}
    card_ids = [card.pk for card in cards]
    net_total_by_pair: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    rows = CardTagVote.objects.filter(card_id__in=card_ids, tag__name__in=ATTRIBUTE_CHIP_TAG_NAMES).values_list(
        "card_id", "tag__name", "source", "anonymous_id", "run_id", "polarity"
    )
    for card_id, tag_name, source, anonymous_id, run_id, polarity in rows:
        if source == VoteSource.IMPLICIT:
            continue
        weight = resolve_vote_weight(source, anonymous_id, run_id)
        accumulator = net_total_by_pair[(card_id, tag_name)]
        accumulator[0] += weight
        accumulator[1] += polarity * weight
    result: dict[int, float] = {}
    for card in cards:
        chip_values = []
        for tag_name in ATTRIBUTE_CHIP_TAG_NAMES:
            total_weight, net = net_total_by_pair.get((card.pk, tag_name), (0.0, 0.0))
            chip_values.append(net / total_weight if total_weight > 0 else 0.0)
        result[card.pk] = _standard_deviation(chip_values)
    return result


def _attribute_variance(card: Card) -> float:
    """`_attribute_variance_map` for a single card - the cold-start signal `_printing_question_
    score` consults when a card has no printing-vote distribution yet."""
    return _attribute_variance_map([card])[card.pk]


def _printing_question_score(card: Card) -> float:
    """Information-gain score for `card` served as a PRINTING question: the entropy of the
    weighted printing-outcome distribution across the card's md5 identity group (the same
    pooled tuples `is_likely_resolve_printing` reads - see `_printing_vote_tuples`), so a
    community split across candidate printings scores highest. A card with no printing votes at
    all has no distribution to be uncertain about - it falls back to the scaled attribute-
    variance signal (see `_ATTRIBUTE_VARIANCE_SCALE`), since the machine's own derived signals
    are then the only evidence that exists."""
    weights_by_outcome: dict[Hashable, float] = defaultdict(float)
    for vote in _printing_vote_tuples(card):
        weights_by_outcome[vote.outcome_key] += vote.weight
    if weights_by_outcome:
        return _shannon_entropy(weights_by_outcome.values())
    return _ATTRIBUTE_VARIANCE_SCALE * _attribute_variance(card)


def _artist_question_score(card: Card) -> float:
    """Information-gain score for `card` served as an ARTIST question: the entropy of the
    weighted artist-outcome distribution (one outcome per distinct `CanonicalArtist`, plus the
    unknown-artist sentinel for an `is_unknown` vote) - the artist-consensus dimension. A card
    whose community is split across candidate artists scores highest; an unanswered or
    unanimous card scores 0.0."""
    weights_by_outcome: dict[Hashable, float] = defaultdict(float)
    for vote in card.artist_votes.all():
        outcome_key: Hashable = ("unknown",) if vote.is_unknown else ("artist", vote.artist_id)
        weights_by_outcome[outcome_key] += resolve_vote_weight(vote.source, vote.anonymous_id, vote.run_id)
    return _shannon_entropy(weights_by_outcome.values())


def _tag_question_score(card: Card, tag_name: str) -> float:
    """Information-gain score for `card` served as a TAG question for `tag_name`: the entropy of
    the weighted polarity distribution for that (card, tag) pair - the tag-review-queue
    dimension. A pair whose community is split roughly evenly between apply and not-apply
    (the queue's own "closest contest" shape) scores highest. Mirrors `get_tag_net_polarity`'s
    weighting convention: IMPLICIT votes are excluded (a passive filter-chip by-product is not
    a deliberate opinion about the tag), everything else routes through `resolve_vote_weight`.
    One indexed query per pair."""
    weights_by_polarity: dict[int, float] = defaultdict(float)
    rows = CardTagVote.objects.filter(card_id=card.pk, tag__name=tag_name).values_list(
        "source", "anonymous_id", "run_id", "polarity"
    )
    for source, anonymous_id, run_id, polarity in rows:
        if source == VoteSource.IMPLICIT:
            continue
        weights_by_polarity[polarity] += resolve_vote_weight(source, anonymous_id, run_id)
    return _shannon_entropy(weights_by_polarity.values())


def _question_information_gain_score(kind: str, card: Card, tag_name: Optional[str] = None) -> float:
    """Dispatches `_printing_question_score`/`_artist_question_score`/`_tag_question_score` on
    `question_feed_pools.KIND_*` - one seam the tiers below call instead of three per-kind
    branches."""
    # KIND_ILLUSTRATION scores on the same printing-vote/attribute-variance signal as
    # KIND_PRINTING: there is no separate illustration-vote entropy dimension (illustration
    # votes derive an artist vote automatically but never cast a printing vote - see
    # `_illustration_item`'s own docstring), and an illustration-unresolved card is, in
    # practice, the same cold-start population `_printing_question_score`'s attribute-variance
    # fallback already covers.
    if kind in (question_feed_pools.KIND_PRINTING, question_feed_pools.KIND_ILLUSTRATION):
        return _printing_question_score(card)
    if kind == question_feed_pools.KIND_ARTIST:
        return _artist_question_score(card)
    assert tag_name is not None  # a KIND_TAG question always carries a tag_name
    return _tag_question_score(card, tag_name)


def _max_scored_candidate(cards: Sequence[Card], score_fn: Callable[[Card], float]) -> Optional[Card]:
    """Argmax of `score_fn` over `cards`, STABLE (Python's `max` returns the first maximal
    element), so the caller's pre-ranking - which encodes every existing selection rule
    (`-vote_count`, the quick-negative tiebreak, `-date_created`, kind precedence) - is the
    tiebreak whenever two candidates score equally. `None` for an empty sequence. The tiers
    pass their querysets pre-ranked by the OLD rules and get back the highest-scoring candidate
    among the first `_CANDIDATE_SCORING_WINDOW` of them."""
    if not cards:
        return None
    return max(cards, key=score_fn)


def _first_answerable_printing_candidate(
    cards: Sequence[Card], score_fn: Callable[[Card], float]
) -> Optional[tuple[Card, QuestionFeedItem]]:
    """The printing-tier analogue of `_max_scored_candidate` above, for the one dimension where
    the argmax candidate can turn out unservable: `_identify_printing_item` returns `None` for a
    card with no ranked printing candidates (see that function's own docstring), and the argmax
    alone has no way to recover from that - it would either serve a dead question or, worse, be
    read as "this tier has nothing" and drop the tier entirely. This tries every candidate in
    SCORE order (`sorted(..., reverse=True)`, which - like `max` - is stable, so ties keep the
    caller's own pre-rank order exactly as `_max_scored_candidate` does), returning the first
    `(card, item)` pair whose item actually has candidates to show, or `None` if every candidate
    in the window is unservable this way. `None` here means "no printing question in this
    window", not "this tier has nothing" - the caller falls through to its next kind/lane exactly
    as an empty `cards` sequence already would."""
    for card in sorted(cards, key=score_fn, reverse=True):
        item = _identify_printing_item(card)
        if item is not None:
            return card, item
    return None


def _first_answerable_illustration_candidate(
    cards: Sequence[Card], score_fn: Callable[[Card], float]
) -> Optional[tuple[Card, QuestionFeedItem]]:
    """The illustration-tier analogue of `_first_answerable_printing_candidate` above:
    `_illustration_item` returns `None` for a card whose deduplicated candidate set is not a
    genuine multi-way choice (see that function's own docstring). Tries every candidate in
    score order and returns the first `(card, item)` pair that is actually servable, or `None`
    if the whole window has nothing - the caller falls through to its next kind/lane exactly as
    an empty `cards` sequence already would."""
    for card in sorted(cards, key=score_fn, reverse=True):
        item = _illustration_item(card)
        if item is not None:
            return card, item
    return None


def _voter_answered_printing_card_ids(anonymous_id: str) -> set[int]:
    """
    Every card this voter has already cast a printing vote on, WIDENED to those cards' full
    combined identity groups (`printing_consensus.identity_group_expanded_card_ids` - md5 union
    artbox-phash-d0, issue #661) - the exclusion set the printing tiers below filter against, so
    a voter who answered one member of a group is never asked the same byte-identical or
    phash-d0-identical image again under a sibling's identifier (issue #473: the feed serves one
    member per group, not N).

    This replaces the `.exclude(printing_tags__anonymous_id=anonymous_id)` clause those tiers
    used before, and is exactly equivalent to it for a card whose group is itself alone (the
    same set of cards, expressed as pks) - which, for a checksum-less catalogue, is every card.
    One indexed query, plus the expansion's own (at most two, and zero before PR-1 adds the
    checksum column - see `printing_consensus._md5_checksums_for_card_ids`).

    ALSO reads `CardIllustrationVote` (issue #713). `identify_printing` has two answer paths on
    the frontend: a single/unclustered candidate posts straight to `CardPrintingTag`, but a
    shared-illustration cluster of N>=2 candidates posts to `illustration_vote.
    cast_illustration_vote` instead, which writes `CardPrintingTag` ONLY when the illustration
    resolves to exactly one live printing (see that function's own docstring) - at N>1, the
    premise of the cluster UI that fired, nothing lands on the printing channel at all. Without
    this, a voter who answered via the cluster path cast a real, persisted vote
    (`CardIllustrationVote` is always written) that this exclusion could not see, so the card
    stayed eligible and was immediately re-served - production evidence: both of the only two
    human illustration votes on record were each followed within seconds by an `is_no_match`
    escape vote on the same card. Every `CardIllustrationVote` row - not just the N>1 case - is
    included unconditionally: for the N=1 case the card is already covered by the
    `CardPrintingTag` query above, so this is a no-op union there, not a special case to branch
    on; keeping it unconditional means one query shape covers both outcomes of
    `cast_illustration_vote` rather than two.

    NOT `CardQuestionAbstention` (issue #712/#731): that model records a human "Not sure" - a
    real non-answer - and reusing it here for a real, weighted answer would conflate the two,
    corrupting the exact distinction #712 was built to preserve. See this function's own tests
    and the issue #713 PR description for the full reasoning.

    COMPUTED ONCE PER FEED REQUEST, in `get_next_question_feed_item`, and passed down to every
    tier that needs it (2026-07-25 gate on PR #482, condition f1: each tier calling this for
    itself multiplied the cost by the number of tiers consulted, for an answer that cannot change
    within one request). The tiers keep an optional parameter rather than a required one so a
    direct caller - a test, a shell - can still ask for one tier by `anonymous_id` alone.
    """
    voted_card_ids = set(CardPrintingTag.objects.filter(anonymous_id=anonymous_id).values_list("card_id", flat=True))
    illustration_voted_card_ids = set(
        CardIllustrationVote.objects.filter(anonymous_id=anonymous_id).values_list("card_id", flat=True)
    )
    return identity_group_expanded_card_ids(voted_card_ids | illustration_voted_card_ids)


def _voter_answered_artist_card_ids(anonymous_id: str) -> set[int]:
    """
    The artist-tier analogue of `_voter_answered_printing_card_ids` above: every card this voter
    has already cast a `CardArtistVote` on, widened to those cards' full combined identity
    groups, so a voter who answered one member of a byte-identical or phash-d0-identical group is
    not re-asked the same artist question under a sibling's identifier (issue #473, widened by
    #661). Scoped to `_tier_2_contested` only
    (2026-08-04 gate on the phase-C/md5 routing brief) - `_tier_4_fresh`'s own artist exclusion
    keeps its pre-existing, unwidened `.exclude(artist_votes__anonymous_id=...)` form.

    COMPUTED ONCE PER FEED REQUEST, mirroring `_voter_answered_printing_card_ids`'s own
    convention exactly.
    """
    voted_card_ids = CardArtistVote.objects.filter(anonymous_id=anonymous_id).values_list("card_id", flat=True)
    return identity_group_expanded_card_ids(voted_card_ids)


def _voter_answered_tag_card_ids_by_tag(anonymous_id: str) -> dict[str, set[int]]:
    """
    For every tag name this voter has cast a `CardTagVote` on, the set of card ids - each widened
    to its full combined identity group - that count as "already answered" for THAT tag. Widening is
    on the CARD axis only, never the tag axis: `_tier_2_contested`'s own-vote exclusion is
    deliberately scoped to (card, tag, anonymous_id), not (card, anonymous_id) - a card carries
    ~11 independent attribute-chip tags, and a card-level exclude would silently hide every other
    still-open tag the moment a voter touches any one of them (see that function's own comment).
    This applies the identical scoping onto md5 siblings: "has this voter answered THIS tag on
    ANY member of this card's md5 group", never "has this voter answered ANY tag on this card's
    md5 group".

    ONE query fetches every (tag_name, card_id) pair this voter has ever voted on - cost scales
    with this voter's own vote count, not with `get_tag_review_queue_pairs()`'s output, so it
    does not multiply per review pair. The md5 expansion then runs once per distinct tag name
    this voter has touched (bounded by the fixed attribute-chip taxonomy), never once per pair.
    """
    rows = CardTagVote.objects.filter(anonymous_id=anonymous_id).values_list("tag__name", "card_id")
    card_ids_by_tag: dict[str, set[int]] = defaultdict(set)
    for tag_name, card_id in rows:
        card_ids_by_tag[tag_name].add(card_id)
    return {tag_name: identity_group_expanded_card_ids(card_ids) for tag_name, card_ids in card_ids_by_tag.items()}


def _voter_cannot_tell_card_ids(anonymous_id: str, question_type: str) -> set[int]:
    """Cards (md5-widened) where this voter recorded a `CardQuestionAbstention` for
    `question_type` with `reason=CANNOT_TELL_ABSTENTION_REASON` - a stated "the scan doesn't
    show this", not a deferral. A plain Skip on the same question type abstains with
    `reason=None` and never matches this filter, so it stays answerable later."""
    card_ids = CardQuestionAbstention.objects.filter(
        anonymous_id=anonymous_id, question_type=question_type, reason=CANNOT_TELL_ABSTENTION_REASON
    ).values_list("card_id", flat=True)
    return identity_group_expanded_card_ids(set(card_ids))


def _voter_answered_border_card_ids(anonymous_id: str) -> set[int]:
    """
    Cards (md5-widened) this voter has already answered the border question for: either cast a
    `CardTagVote` on one of the four border-colour tags (`_BORDER_COLOR_TAG_NAMES` - the same
    vote every `BorderColorQuestion` chip tap casts), or abstained on a served `border` question
    with reason `cannot-tell` (`_voter_cannot_tell_card_ids`).

    Treated as ONE axis, not four independent tags like `_voter_answered_tag_card_ids_by_tag`'s
    general attribute-chip walk: the four colours are mutually exclusive on the frontend's own
    `BORDER_COLOR_GROUP`, so a vote on any one of them answers the whole "which border colour"
    question for this card - unlike the ~11-tag walk, where a card carries many independent
    questions and answering one must not hide the others.
    """
    voted_card_ids = CardTagVote.objects.filter(
        anonymous_id=anonymous_id, tag__name__in=_BORDER_COLOR_TAG_NAMES
    ).values_list("card_id", flat=True)
    return identity_group_expanded_card_ids(set(voted_card_ids)) | _voter_cannot_tell_card_ids(
        anonymous_id, TypeEnum.border.value
    )


def _not_official_art_card_ids() -> set[int]:
    """
    Cards a human has declared NOT official art via a positive (`VotePolarity.APPLY`)
    `CardTagVote` for one of `reason_tags.NOT_OFFICIAL_ART_REASON_TAGS` - the phase-C routing
    signal the WTC phase B partition (`reason_tags.py`'s module docstring) was always meant to
    feed. For such a card the artwork question is UNANSWERABLE, so the feed must stop serving
    artist-shaped questions for it; the printing question is unaffected (see this function's
    call sites, both in the artist half only). Widened to each card's full md5 identity group,
    since byte-identical files share the same artwork.

    Human-backed only (`is_human_backed_source`), not "any positive vote": these reason tags are
    cast by a human through `NoMatchReasonStrip`, but nothing in the schema stops a machine
    caster from writing one in principle, and this routing signal is meant to represent an
    actual human declaration that the artwork question is meaningless for this card - a future
    machine-cast source earning the same trust would need its own explicit decision, not a
    silent inclusion here. Widened via the combined identity group, not md5 alone (issue #661).

    Unlike `_voter_answered_printing_card_ids`/`_voter_answered_artist_card_ids` above, this is
    NOT per-voter: it is a fact about the CARD, so it applies identically to every voter's feed.
    Still COMPUTED ONCE PER FEED REQUEST, same convention as the per-voter exclusions.
    """
    rows = CardTagVote.objects.filter(
        tag__name__in=NOT_OFFICIAL_ART_REASON_TAGS, polarity=VotePolarity.APPLY
    ).values_list("card_id", "source")
    human_backed_card_ids = {card_id for card_id, source in rows if is_human_backed_source(source)}
    return identity_group_expanded_card_ids(human_backed_card_ids)


def _voter_hidden_card_ids(anonymous_id: str) -> set[int]:
    """
    Every card this anonymous_id has hidden for themselves via a `hide=True` card report
    (`HiddenCard`, written by `views.post_report_card` in the same transaction as the report
    - see docs/features/moderation.md's hidden-card section). The exclusion set every feed
    candidate below is filtered against, so a card a voter asked to stop seeing never comes
    back in that identity's own future feed items, across every question kind - printing,
    artist and tag questions all key on the same card, so one card-level exclusion covers
    all three (unlike the answered-card exclusions, none of which is question-kind-agnostic).

    Widened to each card's full md5 identity group (`identity_group_expanded_card_ids`), same
    as `_voter_answered_printing_card_ids`/`_voter_answered_artist_card_ids`: this module's
    identity-grouping premise is that a byte-identical image file is ONE identification
    target (issue #473), and a voter who hid "this image" hid the group, not just the one
    member the report modal happened to be showing - otherwise the feed would immediately
    re-serve the same artwork under a sibling identifier and the hide would look broken.
    Degenerates exactly to the card-scoped behavior while no `Card.md5_checksum` rows exist
    (the pre-PR-1 state, same as every other widened exclusion here).

    COMPUTED ONCE PER FEED REQUEST, in `get_next_question_feed_item`, and passed down to
    every branch that needs it (the 2026-07-25 gate on PR #482, condition f1 convention);
    the tiers keep an optional parameter so a direct caller - a test, a shell - can still
    ask for one tier by `anonymous_id` alone.
    """
    hidden_card_ids = HiddenCard.objects.filter(anonymous_id=anonymous_id).values_list("card_id", flat=True)
    return identity_group_expanded_card_ids(hidden_card_ids)


def is_likely_resolve_printing(card: Card) -> bool:
    """
    True when ONE hypothetical additional agreeing human vote (`VoteSource.USER` weight) added
    to the current highest-weighted printing outcome group of `card`'s md5 IDENTITY GROUP (issue
    #473 - the pooled tally of every byte-identical sibling, via `_printing_vote_tuples`, not
    this one card's rows in isolation; a group one human vote from resolving is likely-resolve
    for every member of it, and resolving it resolves all of them) would resolve it under the
    REAL resolver (`vote_consensus.resolve_weighted_consensus` - the same function
    `printing_consensus.resolve_printing` calls; this never reimplements its weight/threshold
    arithmetic). This is the serve-time LIKELY-RESOLVE classification the 2026-07-24 data
    brief's exact-code simulation approach specifies (the same method that produced its
    46,310-card LIKELY-RESOLVE SUPPLY figure): find the currently-leading outcome group by
    summed weight, add one hypothetical `VoteSource.USER` vote to THAT group, re-run the real
    resolver, and check whether it wins with that group's own key.

    False for a card with no printing-tag votes at all (there is no "leading" group to add to -
    this is exactly the cold-start population the brief's item 1 table calls out as having
    "ZERO non-zero-weight signal", never likely-resolve by this definition) and false for an
    already-RESOLVED card (a caller should never ask, since `_likely_resolve_printing_card`
    only scans `PrintingTagStatus.UNRESOLVED` cards, but this stays a plain `False` rather than
    raising either way - the resolver would simply report the same key already won, which this
    function would then also (correctly, if uninterestingly) report as "likely resolve").
    """
    vote_tuples = _printing_vote_tuples(card)
    if not vote_tuples:
        return False

    current_weight_by_key: dict[Hashable, float] = defaultdict(float)
    for vote in vote_tuples:
        current_weight_by_key[vote.outcome_key] += vote.weight
    leading_key = max(current_weight_by_key.items(), key=lambda pair: pair[1])[0]

    # No `dedupe_key`: this stands for a NEW voter, distinct from everyone already in the pooled
    # tally, so it must not collapse into any of them (issue #473 - inside a group, real votes
    # are keyed on their caster's `anonymous_id`; see `vote_consensus.pool_group_votes`). The
    # tuples it joins are already pooled, and this list is not re-pooled.
    hypothetical_vote = VoteTuple(
        outcome_key=leading_key,
        # `run_id=None`: a hypothetical vote belongs to no run at all, and is USER-sourced anyway,
        # so the zero-weight cohort override can never match it on either conjunct.
        weight=resolve_vote_weight(VoteSource.USER, _HYPOTHETICAL_VOTE_ANONYMOUS_ID, None),
        is_human_backed=True,
    )
    winning_key = resolve_weighted_consensus(
        vote_tuples + [hypothetical_vote],
        min_weight=settings.PRINTING_TAG_MIN_VOTES,
        min_share=settings.PRINTING_TAG_MIN_SHARE,
    )
    return winning_key == leading_key


def _likely_resolve_printing_card(
    anonymous_id: str, answered_card_ids: Optional[set[int]] = None, hidden_card_ids: Optional[set[int]] = None
) -> Optional[Card]:
    """
    First UNRESOLVED printing card (in `date_created` order, same scan convention tier 1 uses)
    that both carries at least one existing `CardPrintingTag` row and passes
    `is_likely_resolve_printing` - the >=51% mix-composition policy's own supply pool (see this
    module's docstring for the ratio policy this feeds, and `get_next_question_feed_item` for
    where it's consulted). `hidden_card_ids` (this voter's `_voter_hidden_card_ids` set, or a
    direct caller's own) is excluded like `answered_card_ids` - a card this voter hid for
    themselves must not resurface through this pool either.

    Cost/approach (compute-per-serve, no caching layer - stated per this change's own spec):
    pre-filters to `printing_tags__isnull=False` (97,212 of 218,345 cards at the 2026-07-24 data
    brief's snapshot - cards carrying ANY printing-tag signal, not the full unresolved
    population, though this still includes the ~8k zero-weight-only deductive-backfill rows
    that `is_likely_resolve_printing` will correctly reject) before doing a per-card Python-side
    `is_likely_resolve_printing` check via `.iterator()` - the same "scan in priority order,
    stop at the first match" shape `_tier_1_confirm_suggestion` already uses, not a new
    performance-risk pattern this change introduces. Worst case (this voter has already
    excluded most of the pool, or the pool is nearly exhausted) is a bounded scan of the
    pre-filtered ~97k rows, not the full 218k-card catalog and not unbounded - accepted as a v1
    cost matching this module's own "known v1 property, not a bug" convention (see the module
    docstring), not solved with a materialized/cached index here.

    ONE ADDITIONAL QUERY PER SCANNED CARD once issue #473's PR-1 populates `Card.md5_checksum`:
    `is_likely_resolve_printing` reads the card's identity GROUP, and a card carrying a checksum
    costs a group-membership lookup to find its siblings before its tally can be built (a
    checksum-less card still costs nothing extra - it takes the group-of-one path with no query).
    Accepted explicitly here rather than discovered later (2026-07-25 gate on PR #482, condition
    f2): it rides on the same bounded, stop-at-first-match scan this docstring already accepts as
    a v1 cost, and the pooling it pays for is what stops that pool from serving n copies of one
    question. If this scan is ever the profile's hot spot, the fix is the materialized
    likely-resolve index this docstring already defers, not un-grouping the tally.
    """
    if answered_card_ids is None:
        answered_card_ids = _voter_answered_printing_card_ids(anonymous_id)
    if hidden_card_ids is None:
        hidden_card_ids = _voter_hidden_card_ids(anonymous_id)
    candidates = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, printing_tags__isnull=False)
        .exclude(pk__in=answered_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .distinct()
        .order_by("date_created")
    )
    for card in candidates.iterator():
        if is_likely_resolve_printing(card):
            return card
    return None


def _card_border_unrecorded(card: Card) -> bool:
    """True unless one of the four border-colour tags (`_BORDER_COLOR_TAG_NAMES`) has reached
    RESOLVED_APPLY consensus for `card` - i.e. this card's own border colour has not yet been
    settled by a resolved attribute-chip vote."""
    statuses = card.tag_vote_statuses
    return not any(statuses.get(tag_name) == TagVoteStatus.RESOLVED_APPLY for tag_name in _BORDER_COLOR_TAG_NAMES)


def _candidates_split_on_border(candidates: Sequence[PrintingCandidate]) -> bool:
    """True when `candidates` (a card's own ranked printing candidates) carry more than one
    distinct non-empty `borderColor` - i.e. a border answer would actually eliminate at least
    one candidate from this card's own candidate set, rather than merely filling a gap."""
    border_colors = {candidate.borderColor for candidate in candidates if candidate.borderColor}
    return len(border_colors) > 1


def _likely_resolve_item(card: Card, allow_narrowing: bool = True, *, anonymous_id: str) -> Optional[QuestionFeedItem]:
    """
    For the LIKELY-RESOLVE pool (a printing question one more agreeing human vote would
    resolve, per `is_likely_resolve_printing`): serves the MOST DISCRIMINATING question for
    THIS card rather than always a printing confirmation, per
    docs/features/wtc-question-model.md's routing rule -

    1. If `allow_narrowing` and `card`'s own candidates split on border colour AND that colour
       hasn't been recorded yet (`_card_border_unrecorded`/`_candidates_split_on_border`) AND
       `anonymous_id` hasn't already answered border for this card
       (`_voter_answered_border_card_ids`), a border answer narrows this card's own candidate
       set - serve `border`. Without the third condition this card would be re-served to the
       same voter on every future visit, since the first two conditions are catalogue-wide
       facts that a single voter's own answer never changes.
    2. Otherwise, if `allow_narrowing` and `card`'s illustration identity is still unresolved,
       serve the illustration question.
    3. Otherwise, fall through to the pre-existing behaviour: a `confirm_suggestion` (it has a
       live machine-sourced suggestion to confirm - the common shape within this pool, the data
       brief's 45,154-of-46,310 single-candidate split) or a bare `identify_printing` question
       (the multi-candidate remainder).

    The likely-resolve pool changes WHICH card gets served first; this routing changes WHAT
    QUESTION is asked about that card - narrowing candidates resolves the card faster than an
    unconditional printing confirmation whenever a cheaper, narrowing answer is available.

    `allow_narrowing` (default `True`, so every existing per-card routing test above is
    unaffected) is `get_next_question_feed_item`'s session-level valve, not a property of the
    card: no border-colour tag has ever reached RESOLVED_APPLY catalogue-wide (measured
    2026-08-21), so step 1's own condition is true for essentially every card whose candidates
    split on border, and step 2 absorbs most of what step 1 doesn't - uncapped, this pool never
    reaches step 3, the printing question the pool exists to serve. See
    `_likely_resolve_narrowing_ratio`/`settings.QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO`
    for the cap that sets this to `False` once a session's own narrowing share is high enough.

    Returns `None` when none of the above can be served: `card` has no ranked printing
    candidates (so steps 1/2 can never trigger, since both read off the same candidate list) AND
    `_confirm_suggestion_item` also declines (no gate-clearing machine suggestion) AND
    `_identify_printing_item` therefore also declines (empty candidate grid - see that
    function's own docstring). `card` reaching this pool at all only requires an existing
    `CardPrintingTag` row (`_likely_resolve_printing_card`'s own query) - not a non-empty ranked
    candidate list, so this is reachable in principle even though `confirm_suggestion`'s own
    `suggestedPrinting` comes from the vote directly rather than the ranked list and often still
    succeeds here. `get_next_question_feed_item` must treat `None` as "no supply from this pool
    for this request" and fall through to the remainder waterfall, never serve nothing.
    """
    candidates = get_ranked_printing_candidates(card, card.name)
    serialised_candidates = [candidate.serialise_as_printing_candidate() for candidate in candidates]
    if allow_narrowing:
        if (
            _card_border_unrecorded(card)
            and _candidates_split_on_border(serialised_candidates)
            and card.pk not in _voter_answered_border_card_ids(anonymous_id)
        ):
            return _border_item(card)
        # Gated on actually carrying illustration data (mirrors `_tier_4_fresh`'s own
        # `illustration_id__isnull=False` filter), not merely UNRESOLVED - that status is the
        # model default for every card, so an ungated check would route almost every likely-resolve
        # card through here regardless of whether an illustration question is even answerable for it.
        # This is a cheap pre-filter only (reusing `serialised_candidates`, already computed
        # above) - `_illustration_item` itself is the real gate, and can still decline (`None`)
        # for a card that has SOME illustration_id-carrying candidate but whose deduplicated set
        # isn't a genuine multi-way choice; that card falls through to step 3 below exactly like
        # a card with no illustration data at all.
        if card.illustration_vote_status == IllustrationVoteStatus.UNRESOLVED and any(
            candidate.illustrationId is not None for candidate in serialised_candidates
        ):
            illustration_item = _illustration_item(card)
            if illustration_item is not None:
                return illustration_item
    item = _confirm_suggestion_item(card)
    if item is not None:
        return item
    return _identify_printing_item(card)


def _tier_1_confirm_suggestion(
    anonymous_id: str, answered_card_ids: Optional[set[int]] = None, hidden_card_ids: Optional[set[int]] = None
) -> Optional[QuestionFeedItem]:
    if answered_card_ids is None:
        answered_card_ids = _voter_answered_printing_card_ids(anonymous_id)
    if hidden_card_ids is None:
        hidden_card_ids = _voter_hidden_card_ids(anonymous_id)
    cards = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .exclude(pk__in=answered_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .distinct()
        .order_by("date_created")
    )
    # Issue #716 information-gain re-ranking: every tier-1 candidate carries exactly one
    # machine-sourced suggestion, so their printing-vote entropy is identically zero - the only
    # differentiating signal is the "attribute variance" dimension (how internally inconsistent
    # the machine's own attribute-chip picture of the card is), so the bounded window is re-
    # ranked by that. A candidate that fails to build a suggestion (a machine vote with a null
    # printing, or - issue #766 - one whose evidence doesn't clear
    # `_evidence_justifies_confirmation`) is skipped; if the whole window yields nothing, the
    # unchanged full scan takes over.
    windowed = list(cards[:_CANDIDATE_SCORING_WINDOW])
    variances = _attribute_variance_map(windowed)
    windowed.sort(key=lambda card: variances.get(card.pk, 0.0), reverse=True)
    for card in windowed:
        item = _confirm_suggestion_item(card)
        if item is not None:
            return item
    windowed_pks = {card.pk for card in windowed}
    for card in cards.iterator():
        if card.pk in windowed_pks:
            continue
        item = _confirm_suggestion_item(card)
        if item is not None:
            return item
    # Every tier-1 candidate carries a machine suggestion, but none built an item - either the
    # evidence gate (`_evidence_justifies_confirmation`) rejected the card, or every
    # suggestion's artwork is elimination-consensus-eliminated ("Not this art", §7.1) - this
    # tier still has a card to ask about, it just cannot ask for a printing confirmation yet.
    # Per the ratified question model (docs/features/
    # wtc-question-model.md §2: "any element unmatched -> ask the question that fills the gap"),
    # fall through to `identify_printing` rather than returning `None` and silently dropping it -
    # the same confirm-or-identify fallback `_likely_resolve_item` already uses for the
    # likely-resolve pool. An eliminated suggestion implies "this specific artwork is wrong", not
    # "this card is unidentifiable", so the card still gets asked - as the cheaper,
    # evidence-agnostic question, exactly like a gate-failing card. `identify_printing`'s own
    # candidate grid is deliberately not elimination-filtered: narrowing the served SUGGESTION is
    # this feature's scope; a voter asked "which of these is it" should still be able to pick the
    # correct printing even after a wrong suggestion was eliminated.
    #
    # `_identify_printing_item` can itself decline (`None`, no ranked printing candidates at all
    # - see that function's own docstring), so this tries every windowed candidate in the same
    # (highest-variance-first) order the confirm loop above already used, then the remaining
    # full scan, rather than only ever trying `windowed[0]` and risking a `None` this tier could
    # have avoided by trying the next candidate.
    for card in windowed:
        item = _identify_printing_item(card)
        if item is not None:
            return item
    for card in cards.iterator():
        if card.pk in windowed_pks:
            continue
        item = _identify_printing_item(card)
        if item is not None:
            return item
    return None


def _tier_2_contested(
    anonymous_id: str,
    answered_card_ids: Optional[set[int]] = None,
    answered_artist_card_ids: Optional[set[int]] = None,
    answered_tag_card_ids_by_tag: Optional[dict[str, set[int]]] = None,
    not_official_art_card_ids: Optional[set[int]] = None,
    contested_card_ids: Optional[list[int]] = None,
    contested_artist_card_ids: Optional[list[int]] = None,
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[QuestionFeedItem, str]]:
    if answered_card_ids is None:
        answered_card_ids = _voter_answered_printing_card_ids(anonymous_id)
    if answered_artist_card_ids is None:
        answered_artist_card_ids = _voter_answered_artist_card_ids(anonymous_id)
    if answered_tag_card_ids_by_tag is None:
        answered_tag_card_ids_by_tag = _voter_answered_tag_card_ids_by_tag(anonymous_id)
    if not_official_art_card_ids is None:
        not_official_art_card_ids = _not_official_art_card_ids()
    if contested_card_ids is None:
        contested_card_ids = get_contested_card_ids()
    if contested_artist_card_ids is None:
        contested_artist_card_ids = get_contested_artist_card_ids()
    if hidden_card_ids is None:
        hidden_card_ids = _voter_hidden_card_ids(anonymous_id)

    # Issue #716 information-gain re-ranking: each kind's bounded candidate window (pre-ranked
    # by the pre-existing `-date_created` rule) is scored by its dimension's vote entropy, and
    # the highest-scoring candidate is served - a community split across candidate printings
    # or artists, or across a tag's polarities, is the highest-value question. Equal scores
    # fall back to the pre-rank (see `_max_scored_candidate`), so kind precedence and the
    # existing intra-kind order are unchanged whenever the score cannot distinguish candidates.
    printing_candidates = list(
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED, pk__in=contested_card_ids)
        .exclude(pk__in=answered_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .order_by("-date_created")[:_CANDIDATE_SCORING_WINDOW]
    )
    printing_result = _first_answerable_printing_candidate(printing_candidates, _printing_question_score)
    if printing_result is not None:
        _, printing_item = printing_result
        return printing_item, "tier_2_contested_printing"

    artist_candidates = list(
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.CONTESTED, pk__in=contested_artist_card_ids)
        .exclude(pk__in=answered_artist_card_ids)
        .exclude(pk__in=not_official_art_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .order_by("-date_created")[:_CANDIDATE_SCORING_WINDOW]
    )
    artist_card = _max_scored_candidate(artist_candidates, _artist_question_score)
    if artist_card is not None:
        return _artist_item(artist_card), "tier_2_contested_artist"

    tag_candidates: list[tuple[Card, str]] = []
    for card_id, tag_name in get_tag_review_queue_pairs():
        if len(tag_candidates) >= _CANDIDATE_SCORING_WINDOW:
            break
        # scoped to (card, tag, anonymous_id) widened to the card's md5 group, not just (card,
        # anonymous_id) - a voter who already answered a *different* tag on this card (there
        # are ~11 attribute-chip tags per card) must still see this tag if they haven't
        # answered it yet, and a voter who answered THIS tag on a byte-identical sibling of
        # this card must not be re-asked it here either (issue #473). A card-level exclude here
        # (dropping the tag axis) would silently hide every other still-open tag on a card the
        # moment this voter touches any one tag on it.
        if card_id in answered_tag_card_ids_by_tag.get(tag_name, set()):
            continue
        if card_id in hidden_card_ids:
            continue
        card = Card.objects.get(pk=card_id)
        status = card.tag_vote_statuses.get(tag_name)
        if status == TagVoteStatus.CONTESTED:
            tag_candidates.append((card, tag_name))
    if tag_candidates:
        best_tag = max(tag_candidates, key=lambda pair: _tag_question_score(*pair))
        return _tag_item(*best_tag), "tier_2_contested_tag"
    return None


def _latest_stage_d_origin_reason_subquery() -> Subquery:
    """Correlated subquery: `card`'s most recent Stage D join-key/fallback `CardScanLog.
    skip_reason` (the ORIGIN reason - the specific sub-check outcome that first routed this card
    toward review), or `None` if no such row exists. Feeds `_tier_4_fresh`'s quick-negative
    reordering below - see that function's own docstring for why."""
    return Subquery(
        CardScanLog.objects.filter(
            card_id=OuterRef("pk"), anonymous_id__in=[JOIN_KEY_ANONYMOUS_ID, STAGE_D_FALLBACK_ANONYMOUS_ID]
        )
        .order_by("-scanned_at")
        .values("skip_reason")[:1]
    )


def _tier_4_fresh(
    anonymous_id: str,
    answered_card_ids: Optional[set[int]] = None,
    not_official_art_card_ids: Optional[set[int]] = None,
    contested_card_ids: Optional[list[int]] = None,
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[QuestionFeedItem, str]]:
    # named "tier 4" (not renumbered to 3) even though moderation's former tier 3 was removed
    # (see module docstring) - keeps this name stable against every docstring/test/comment
    # that already refers to "tier 4" rather than triggering a pure-renumbering diff.
    # A card with one machine-sourced vote plus one *agreeing* human vote (weight 1.5 at default
    # settings - still short of PRINTING_TAG_MIN_VOTES=2) is exactly as close to resolving as
    # a card can get without being resolved outright, yet it's excluded from tier 1 (any human
    # vote moves a card out of tier 1's "machine-only" pool) and isn't contested (agreeing votes,
    # not conflicting, so tier 2's contested check doesn't catch it either) - it lands here,
    # in tier 4, with zero votes and 28,112 genuinely-untouched cards. The candidate window is
    # ranked by `-vote_count` first (issue #716's information-gain re-rank uses it as the
    # tiebreak - see `_max_scored_candidate`), which surfaces these "one vote from resolving"
    # cards ahead of the untouched population, the same "prioritize whichever question is
    # closest to actually resolving" answer this tier always gave, now folded into the score's
    # tiebreak chain rather than standing alone.
    #
    # 2026-07-24 addition: `is_quick_negative` is a SECONDARY tiebreak (after `-vote_count`,
    # never ahead of it - a real "closer to resolving" card still wins first, exactly as
    # before) that prioritizes a card whose latest Stage D scan-log origin is a quick-negative
    # reason (`QUICK_NEGATIVE_SKIP_REASONS`) over one that's hard/open-ended or has no scan-log
    # row at all - the data brief's queue-composition ranking's second-from-last remainder
    # slice, ahead of the smallest "hard/open-ended" slice. Most tier-4 candidates share
    # `vote_count=0` (the "totally fresh" case), so in practice this origin-reason tiebreak is
    # what actually decides ordering among them, not a rarely-reached fallback.
    #
    # 2026-08-09 (issue #716): the primary selection within the window is now information-gain
    # scoring (`_max_scored_candidate` + `_printing_question_score`/`_artist_question_score`/
    # `_tag_question_score`) - a card whose votes are split, or whose machine-derived attribute
    # signals are internally inconsistent, is served before an equally-cold card, with
    # `-vote_count`, `is_quick_negative`, and `-date_created` preserved as the tiebreak chain.
    if answered_card_ids is None:
        answered_card_ids = _voter_answered_printing_card_ids(anonymous_id)
    if not_official_art_card_ids is None:
        not_official_art_card_ids = _not_official_art_card_ids()
    if contested_card_ids is None:
        contested_card_ids = get_contested_card_ids()
    if hidden_card_ids is None:
        hidden_card_ids = _voter_hidden_card_ids(anonymous_id)
    illustration_candidates = list(
        Card.objects.filter(illustration_vote_status=IllustrationVoteStatus.UNRESOLVED)
        .exclude(pk__in=answered_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .filter(printing_tags__printing__printing_metadata__illustration_id__isnull=False)
        .distinct()
        .order_by("-date_created")[:_CANDIDATE_SCORING_WINDOW]
    )
    illustration_result = _first_answerable_illustration_candidate(illustration_candidates, _printing_question_score)
    if illustration_result is not None:
        _, illustration_item = illustration_result
        return illustration_item, "tier_4_fresh_illustration"

    printing_candidates = list(
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .exclude(pk__in=contested_card_ids)
        .exclude(pk__in=answered_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .annotate(vote_count=Count("printing_tags", distinct=True))
        .annotate(origin_reason=_latest_stage_d_origin_reason_subquery())
        .annotate(
            is_quick_negative=Case(
                When(origin_reason__in=QUICK_NEGATIVE_SKIP_REASONS, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-vote_count", "is_quick_negative", "-date_created")[:_CANDIDATE_SCORING_WINDOW]
    )
    # Issue #716 information-gain re-ranking: within the bounded window, a card whose printing
    # votes are split (entropy > 0) or whose machine-derived attribute signals are inconsistent
    # (`_printing_question_score`'s cold-start variance term) outranks one that is unanimous or
    # untouched - the highest-value question is the one with the most uncertainty left to
    # resolve. The pre-rank (`-vote_count`, quick-negative, `-date_created`) remains the
    # tiebreak via `_max_scored_candidate`'s stability, so "closest to resolving" and the
    # quick-negative origin still decide whenever the scores cannot distinguish candidates.
    printing_result = _first_answerable_printing_candidate(printing_candidates, _printing_question_score)
    if printing_result is not None:
        printing_card, printing_item = printing_result
        origin_reason = (
            "tier_4_quick_negative_to_review"
            if getattr(printing_card, "origin_reason", None) in QUICK_NEGATIVE_SKIP_REASONS
            else "tier_4_fresh_printing"
        )
        return printing_item, origin_reason

    artist_candidates = list(
        Card.objects.filter(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
        .exclude(artist_votes__anonymous_id=anonymous_id)
        .exclude(pk__in=not_official_art_card_ids)
        .exclude(pk__in=hidden_card_ids)
        .order_by("-date_created")[:_CANDIDATE_SCORING_WINDOW]
    )
    artist_card = _max_scored_candidate(artist_candidates, _artist_question_score)
    if artist_card is not None:
        return _artist_item(artist_card), "tier_4_fresh_artist"

    tag_candidates: list[tuple[Card, str]] = []
    for card_id, tag_name in get_tag_review_queue_pairs():
        if len(tag_candidates) >= _CANDIDATE_SCORING_WINDOW:
            break
        # see tier 2's identical comment above - scoped to (card, tag, anonymous_id)
        if CardTagVote.objects.filter(card_id=card_id, tag__name=tag_name, anonymous_id=anonymous_id).exists():
            continue
        if card_id in hidden_card_ids:
            continue
        card = Card.objects.get(pk=card_id)
        status = card.tag_vote_statuses.get(tag_name)
        if status == TagVoteStatus.UNRESOLVED:
            tag_candidates.append((card, tag_name))
    if tag_candidates:
        best_tag = max(tag_candidates, key=lambda pair: _tag_question_score(*pair))
        return _tag_item(*best_tag), "tier_4_fresh_tag"
    return None


def _served_mix_ratio(anonymous_id: str) -> float:
    """
    `likely_resolve` share of this `anonymous_id`'s own served-question history so far
    (`QuestionFeedServedLog`) - consulted by `get_next_question_feed_item` to decide whether the
    NEXT served item should try the likely-resolve pool first. Two cheap `COUNT` queries,
    indexed on `(anonymous_id, served_at)` - no per-row scan, no caching needed at this cost.

    Returns 0.0 (below every plausible target ratio) for a session with no served-log rows yet,
    so a fresh session's very first question still tries the likely-resolve pool, rather than
    treating "no data" as "ratio already satisfied."
    """
    total = QuestionFeedServedLog.objects.filter(anonymous_id=anonymous_id).count()
    if total == 0:
        return 0.0
    likely_resolve_count = QuestionFeedServedLog.objects.filter(
        anonymous_id=anonymous_id, pool=QuestionFeedServedPool.LIKELY_RESOLVE
    ).count()
    return likely_resolve_count / total


# Narrowing question types `_likely_resolve_narrowing_ratio` counts against a LIKELY-RESOLVE
# serving - the two `_likely_resolve_item` can serve instead of a printing question
# (confirm_suggestion/identify_printing) when `allow_narrowing` is `True`.
_NARROWING_QUESTION_TYPES = frozenset({TypeEnum.border.value, TypeEnum.illustration.value})


def _likely_resolve_narrowing_ratio(anonymous_id: str) -> float:
    """
    `_likely_resolve_item`'s own analogue of `_served_mix_ratio` above: the share of this
    `anonymous_id`'s own LIKELY_RESOLVE-pool servings so far that were a narrowing question
    (border/illustration) rather than a printing question (confirm_suggestion/
    identify_printing) - the ratio `get_next_question_feed_item` checks against
    `settings.QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO` before calling
    `_likely_resolve_item(card, allow_narrowing=...)`. Same "0.0 for no history yet" convention
    as `_served_mix_ratio`: a fresh session's first likely-resolve question still gets to try
    the most-discriminating-question routing before the cap applies.
    """
    total = QuestionFeedServedLog.objects.filter(
        anonymous_id=anonymous_id, pool=QuestionFeedServedPool.LIKELY_RESOLVE
    ).count()
    if total == 0:
        return 0.0
    narrowing_count = QuestionFeedServedLog.objects.filter(
        anonymous_id=anonymous_id,
        pool=QuestionFeedServedPool.LIKELY_RESOLVE,
        question_type__in=_NARROWING_QUESTION_TYPES,
    ).count()
    return narrowing_count / total


# The remainder waterfall's try-order (issue #766: replaces the deleted weighted rotation -
# see this module's own "Evidence-gated printing-confirmation policy" docstring section for why
# a ratio is no longer the right tool once tier 1 is gated rather than ranked). Fixed, not
# session-dependent: tier 1 is gated at construction (`_confirm_suggestion_item`), so it is
# either a cheap pool-miss (usually, today) or a genuinely justified confirmation - either way
# there is nothing left to rebalance a share against.
_REMAINDER_LANE_ORDER: tuple[str, str, str] = (
    question_feed_pools.LANE_CONFIRM,
    question_feed_pools.LANE_CONTESTED,
    question_feed_pools.LANE_COLD,
)


def _log_served(anonymous_id: str, item: QuestionFeedItem, pool: str, origin_reason: str) -> QuestionFeedItem:
    """Records one served-question row (see `QuestionFeedServedLog`'s own docstring for why -
    the data brief's SOUNDNESS NOTE bias-conditioning record) and returns `item` unchanged, so
    every `get_next_question_feed_item` return path can stay a simple one-liner."""
    QuestionFeedServedLog.objects.create(
        anonymous_id=anonymous_id, pool=pool, question_type=item.type.value, origin_reason=origin_reason
    )
    return item


def _pool_contested_result(
    answered_card_ids: set[int],
    answered_artist_card_ids: set[int],
    answered_tag_card_ids_by_tag: dict[str, set[int]],
    not_official_art_card_ids: set[int],
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[QuestionFeedItem, str]]:
    """Pool-backed fast path for `_tier_2_contested`: converts a drawn `(kind, card, tag_name,
    reason)` into the same `(QuestionFeedItem, reason)` shape that function returns, using its
    own item-builders (`_identify_printing_item`/`_artist_item`/`_tag_item`) so a pool-served item
    is byte-for-byte the same shape a live-served one would be. `None` on a pool miss - the
    caller falls back to `_tier_2_contested` itself. `hidden_card_ids` is threaded to
    `draw_contested_entry` unchanged (this voter's `_voter_hidden_card_ids` set); `None` means
    no hidden exclusion, which only a direct caller ever exercises - `get_next_question_feed_item`
    always passes the computed set."""
    drawn = question_feed_pools.draw_contested_entry(
        answered_card_ids,
        answered_artist_card_ids,
        answered_tag_card_ids_by_tag,
        not_official_art_card_ids,
        hidden_card_ids,
    )
    if drawn is None:
        return None
    kind, card, tag_name, reason = drawn
    if kind == question_feed_pools.KIND_PRINTING:
        # `question_feed_pools._build_pool_contested` already excludes a zero-candidate card
        # from ever entering this pool (mirrors this function's own gate at warm time), so `None`
        # here should only ever happen for a card that lost its candidates between warm and read
        # - a defensive re-check, not the primary guard. Treated as a pool miss, same as any
        # other drawn entry that turns out unstale-but-unservable: the caller falls through to
        # the next lane rather than serving the empty grid this whole change exists to prevent.
        item = _identify_printing_item(card)
        if item is None:
            return None
        return item, reason or "tier_2_contested_printing"
    if kind == question_feed_pools.KIND_ARTIST:
        return _artist_item(card), reason or "tier_2_contested_artist"
    assert tag_name is not None  # guaranteed by draw_contested_entry for KIND_TAG
    return _tag_item(card, tag_name), reason or "tier_2_contested_tag"


def _pool_cold_result(
    anonymous_id: str,
    answered_card_ids: set[int],
    not_official_art_card_ids: set[int],
    contested_card_ids: list[int],
    hidden_card_ids: Optional[set[int]] = None,
) -> Optional[tuple[QuestionFeedItem, str]]:
    """The `_tier_4_fresh` analogue of `_pool_contested_result` above. `hidden_card_ids` is
    threaded to `draw_cold_entry` unchanged; `None` means no hidden exclusion (see that
    function's own docstring for the same direct-caller-only caveat)."""
    drawn = question_feed_pools.draw_cold_entry(
        anonymous_id, answered_card_ids, not_official_art_card_ids, contested_card_ids, hidden_card_ids
    )
    if drawn is None:
        return None
    kind, card, tag_name, reason = drawn
    if kind == question_feed_pools.KIND_ILLUSTRATION:
        # See `_pool_contested_result`'s identical guard for why this defensive re-check exists
        # alongside `_build_pool_cold`'s own warm-time gate.
        item = _illustration_item(card)
        if item is None:
            return None
        return item, reason or "tier_4_fresh_illustration"
    if kind == question_feed_pools.KIND_PRINTING:
        # See `_pool_contested_result`'s identical guard for why this defensive re-check exists
        # alongside `_build_pool_cold`'s own warm-time gate.
        item = _identify_printing_item(card)
        if item is None:
            return None
        return item, reason or "tier_4_fresh_printing"
    if kind == question_feed_pools.KIND_ARTIST:
        return _artist_item(card), reason or "tier_4_fresh_artist"
    assert tag_name is not None  # guaranteed by draw_cold_entry for KIND_TAG
    return _tag_item(card, tag_name), reason or "tier_4_fresh_tag"


def get_next_question_feed_item(
    anonymous_id: str, contested_card_ids: Optional[list[int]] = None
) -> Optional[QuestionFeedItem]:
    """
    The ranked union itself. When this session's served-mix ratio (`_served_mix_ratio`) is
    below `settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO` AND the likely-resolve pool still
    has supply for this voter, that pool is served first - otherwise (ratio already at/above
    target, or the pool has no supply for this voter right now) this falls through to the
    three remainder lanes (confirm/contested/cold), tried in `_REMAINDER_LANE_ORDER`'s fixed
    confirm-then-contested-then-cold order - first lane with supply wins. Tier 1 is gated rather
    than rationed (see this module's own "Evidence-gated printing-confirmation policy" docstring
    section), so there is no per-session ordering left to compute here; a starved tier 1 is
    simply one cheap pool-miss before falling through. Each lane's own bounded candidate window
    is re-ranked by
    information-gain score before being drawn from (issue #716 - see the "Information-gain
    question scoring" section below; the cold lane keeps its own quick-negative tiebreak, see its
    docstring). This never infinite-loops or blocks on a starved pool - each branch is a single
    bounded query/scan, and an exhausted lane simply moves on to the next in the order, letting
    both the likely-resolve ratio and the per-lane remainder mix drop honestly rather than
    stalling to protect either.

    The voter's answered-card exclusion set (`_voter_answered_printing_card_ids`, md5-group-
    expanded per issue #473) is resolved ONCE here and passed to every printing tier below - it
    cannot change mid-request, and recomputing it per tier was a real per-request regression the
    2026-07-25 PR #482 gate (condition f1) called out. The same convention now covers two more
    request-scoped exclusions (2026-08-04 gate on the phase-C/md5 routing brief):
    `_voter_answered_artist_card_ids`/`_voter_answered_tag_card_ids_by_tag` (md5-widened, own-
    vote exclusions for `_tier_2_contested`'s artist/tag halves - see those functions' own
    docstrings for why this is scoped to that tier only), and `_not_official_art_card_ids` (the
    phase-C routing signal: a card a human has declared not-official-art via `reason_tags.
    NOT_OFFICIAL_ART_REASON_TAGS` stops being served as an artist-shaped question, in both
    `_tier_2_contested` and `_tier_4_fresh` - printing questions are unaffected). One more
    request-scoped exclusion rides the same convention (issue #714): `_voter_hidden_card_ids`
    (a card this voter hid for themselves via a `hide=True` card report - see that function's
    docstring), threaded to EVERY branch below, since unlike the answered-card exclusions it is
    question-kind-agnostic: a hidden card must not resurface as a printing, artist OR tag
    question.

    `contested_card_ids` is an optional pre-resolved value (issue #713 part 2, extending PR
    #729's "compute once, thread as an optional parameter" convention across the view boundary
    for the first time): `views.get_question_feed` calls `get_contested_card_ids()` once per
    HTTP request and passes the result to both this function and `get_remaining_estimate`, since
    both independently called it before (measured 520-562ms per call against live production
    data) even though neither can see a vote the other cast mid-request. `None` (every direct
    caller - tests, a shell) still resolves it here exactly as before.
    """
    answered_card_ids = _voter_answered_printing_card_ids(anonymous_id)
    answered_artist_card_ids = _voter_answered_artist_card_ids(anonymous_id)
    answered_tag_card_ids_by_tag = _voter_answered_tag_card_ids_by_tag(anonymous_id)
    not_official_art_card_ids = _not_official_art_card_ids()
    # This voter's own hidden-card exclusion (issue #714 - `HiddenCard` rows written by
    # `views.post_report_card` when a report carries `hide=True`): computed ONCE here and
    # threaded to every branch below, same convention as the other request-scoped exclusions,
    # so a card this identity hid for themselves never comes back in their feed, whichever
    # tier would otherwise have served it.
    hidden_card_ids = _voter_hidden_card_ids(anonymous_id)

    if _served_mix_ratio(anonymous_id) < settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO:
        likely_resolve_card = question_feed_pools.draw_resolution_imminent_card(
            answered_card_ids, hidden_card_ids=hidden_card_ids
        )
        if likely_resolve_card is not None:
            allow_narrowing = (
                _likely_resolve_narrowing_ratio(anonymous_id)
                < settings.QUESTION_FEED_LIKELY_RESOLVE_NARROWING_MAX_RATIO
            )
            item = _likely_resolve_item(likely_resolve_card, allow_narrowing=allow_narrowing, anonymous_id=anonymous_id)
            if item is not None:
                return _log_served(
                    anonymous_id, item, QuestionFeedServedPool.LIKELY_RESOLVE, "printing_one_vote_from_resolving"
                )
            # `_likely_resolve_item` declined (see its own docstring: no border/illustration
            # narrowing available AND no confirm_suggestion AND no ranked printing candidates) -
            # this card is not servable from this pool at all, but it is one card, not a lane
            # miss, so falling through to the remainder waterfall below (rather than returning
            # `None` for the whole request) is what keeps a single unservable likely-resolve
            # card from silently ending the voter's session.

    for lane in _REMAINDER_LANE_ORDER:
        if lane == question_feed_pools.LANE_CONFIRM:
            tier_1_card = question_feed_pools.draw_confirm_card(answered_card_ids, hidden_card_ids=hidden_card_ids)
            if tier_1_card is not None:
                tier_1_item = _confirm_suggestion_item(tier_1_card)
                if tier_1_item is not None:
                    return _log_served(
                        anonymous_id, tier_1_item, QuestionFeedServedPool.REMAINDER, "tier_1_confirm_suggestion"
                    )
        elif lane == question_feed_pools.LANE_CONTESTED:
            if contested_card_ids is None:
                contested_card_ids = get_contested_card_ids()
            tier_2_result = _pool_contested_result(
                answered_card_ids,
                answered_artist_card_ids,
                answered_tag_card_ids_by_tag,
                not_official_art_card_ids,
                hidden_card_ids=hidden_card_ids,
            )
            if tier_2_result is not None:
                tier_2_item, tier_2_reason = tier_2_result
                return _log_served(anonymous_id, tier_2_item, QuestionFeedServedPool.REMAINDER, tier_2_reason)
        else:
            if contested_card_ids is None:
                contested_card_ids = get_contested_card_ids()
            tier_4_result = _pool_cold_result(
                anonymous_id,
                answered_card_ids,
                not_official_art_card_ids,
                contested_card_ids,
                hidden_card_ids=hidden_card_ids,
            )
            if tier_4_result is not None:
                tier_4_item, tier_4_reason = tier_4_result
                return _log_served(anonymous_id, tier_4_item, QuestionFeedServedPool.REMAINDER, tier_4_reason)

    return None


def _tag_review_card_ids_by_status() -> tuple[set[int], set[int]]:
    """
    (contested_card_ids, unresolved_card_ids) - distinct cards with >=1 persisted
    `tag_vote_statuses` entry of that status. Same source query as
    `tag_consensus.get_tag_review_queue_pairs` (one pass over `Card.tag_vote_statuses` - a
    JSONField has no native per-key/per-value DB filter, see that function's docstring), but
    skips its second query (vote weights, for pair ordering) and the interleaving, since a
    distinct-card count doesn't need per-pair identity or ordering.
    """
    contested_ids: set[int] = set()
    unresolved_ids: set[int] = set()
    for card_id, statuses in Card.objects.exclude(tag_vote_statuses={}).values_list("id", "tag_vote_statuses"):
        values = statuses.values()
        if TagVoteStatus.CONTESTED in values:
            contested_ids.add(card_id)
        if TagVoteStatus.UNRESOLVED in values:
            unresolved_ids.add(card_id)
    return contested_ids, unresolved_ids


_REMAINING_ESTIMATE_CACHE_KEY = "question-feed-remaining-estimate:v1"
_REMAINING_ESTIMATE_CACHE_TTL = 300  # seconds - see get_remaining_estimate's docstring


def _remaining_estimate_cache_key(contested_card_ids: Optional[list[int]]) -> str:
    """
    Cache key for `get_remaining_estimate`'s four counts, derived from the function's effective
    inputs so two callers that resolved different contested id-sets never share a cached value.

    `None` (the caller lets this function resolve the contested id-set itself) maps to a single
    stable key - the resolved set is an implementation detail, and a stable key is what lets the
    cache actually hit across requests. A pre-resolved set (the view path, issue #713 part 2)
    maps to a digest of that set's CONTENT, so a caller that resolved a different set than the
    one a cached value was computed against gets a miss and a fresh compute, never another
    caller's stale counts. The digest is sha1 over the sorted set - never Python's builtin
    `hash`, which is salted per process and would produce different keys in the warmer and the
    endpoint - and stays well under the DatabaseCache's 255-character key column.
    """
    if contested_card_ids is None:
        return _REMAINING_ESTIMATE_CACHE_KEY
    digest = hashlib.sha1(repr(sorted(set(contested_card_ids))).encode()).hexdigest()
    return f"{_REMAINING_ESTIMATE_CACHE_KEY}:{digest}"


def _remaining_estimate_shared_cache() -> Optional[Any]:
    """
    The cross-process `"shared"` cache (see `settings.CACHES` and `docs/infrastructure.md`'s
    cache section), or `None` on a pre-#543 environment.

    Same read-side degradation convention as `question_feed_pools._shared_cache_for_read`: a
    missing alias is an ordinary miss and the caller falls back to computing the counts live -
    the feed must never 500 because an advisory-header cache isn't configured.
    """
    try:
        return caches["shared"]
    except InvalidCacheBackendError:
        return None


def get_remaining_estimate(
    contested_card_ids: Optional[list[int]] = None, *, force_refresh: bool = False
) -> QuestionFeedCounts:
    """
    "Still need help with" counts for the feed header - NOT per-voter (doesn't account for
    own-vote exclusion, which is comparatively cheap to skip here since this is advisory copy,
    not a candidate set). Pending-moderation-report count is deliberately not folded in here -
    it has its own badge on the dedicated Moderation tab (see this module's docstring),
    separate from ordinary tagging's "remaining" counts.

    Returns four numbers instead of one flat sum:
    - `total`: DISTINCT cards needing review in any category (printing, artist, or tag) - a
      single `.distinct().count()` query, bounded by catalogue size. This replaces the old
      implementation's `printing.count() + artist.count() + len(tag_pairs)`, which summed three
      overlapping per-category counts and could count the same untouched card 2-3+ times (every
      fresh card defaults to UNRESOLVED on *both* printing and artist simultaneously) - see
      docs/features/printing-tags.md's questionFeed section for the diagnosis that motivated
      this fix.
    - `confirmable`/`contested`/`fresh`: aggregate counts mirroring the feed's own three tiers
      (`_tier_1_confirm_suggestion`/`_tier_2_contested`/`_tier_4_fresh`), for a more informative
      header than one opaque number - e.g. "N quick confirmations" up front. These are
      independent per-tier metrics, not a partition of `total`: a single card can count toward
      more than one bucket (e.g. a machine-suggested-but-unconfirmed printing plus a still-fresh
      artist question), same as it can appear in more than one tier across separate voter
      sessions in the real feed.

    Query shape: `get_contested_card_ids()` (contested-printing ids) and
    `_tag_review_card_ids_by_status()` (contested/unresolved-tag ids) each run once and get
    reused across every bucket below - 2 queries total for those, plus one indexed `.count()`
    per bucket (4 buckets), for 6 queries overall. No per-card sub-queries in a loop - the only
    Python-side materialization is the tag-status scan, which was already the established
    pattern for this JSONField (see `_tag_review_card_ids_by_status`'s docstring).

    `contested_card_ids` is an optional pre-resolved value - see `get_next_question_feed_item`'s
    matching parameter docstring for why (issue #713 part 2): `views.get_question_feed` calls
    `get_contested_card_ids()` once and passes it to both functions, since this one always needs
    it and the other needed it as often. `None` (every other caller, e.g. `catalog_stats.py`)
    resolves it here exactly as before.

    CACHING (2026-08-07): the four counts are cached on the cross-process `"shared"` cache
    (issue #538/#543 - never `default`, which is per-process `LocMemCache` and would make a
    warmer and the endpoint disagree silently) for `_REMAINING_ESTIMATE_CACHE_TTL` (300s).
    Measured against live production on 2026-08-16, the uncached body is ~9.2s per feed request
    (`_tag_review_card_ids_by_status`'s JSONField scan ~1.5s + the 4 `.distinct().count()`
    buckets ~7.6s); a cache hit skips all of it for one small indexed SELECT on `shared_cache`.
    These counts are "advisory copy, not a candidate set" (see the docstring header above), so
    the TTL IS the invalidation policy - votes change the counts, but a 300s-stale header is
    the accepted window and there are deliberately no invalidation hooks on vote submission.
    The key is derived from the function's effective inputs (see `_remaining_estimate_cache_key`):
    one key when `contested_card_ids` is `None`, a digest of the resolved set when the caller
    passes one, so a request that resolved a different contested set never reads another
    request's cached counts. With `printing_consensus.get_contested_card_ids` itself cached for
    the same 300s window (2026-08-16), the pre-resolved set the view path passes is stable
    within that TTL - so the digest key stops churning with every vote change and the ~9.2s
    cold body is paid at most once per contested-ids TTL, aligned with the `None`-key path's own
    once-per-300s cadence. Cache miss -> compute -> store, exactly as before otherwise.

    `force_refresh` (2026-08-20, `warm_feed_supply_cache`'s own fix): skips the cache READ
    so a scheduled warm always recomputes, but still performs the cache WRITE below - a
    warm that lands while the entry is still valid (the normal case on a warm cadence
    shorter than the TTL) must still reset the TTL, or the entry keeps expiring 300s after
    its original write regardless of how often the warm runs. Defaults `False` so every
    other caller - above all `views.get_question_feed`'s request path - keeps reading the
    cache exactly as before; only the warm ever passes `True`.
    """
    shared_cache = _remaining_estimate_shared_cache()
    cache_key = _remaining_estimate_cache_key(contested_card_ids)
    cached = shared_cache.get(cache_key) if shared_cache is not None and not force_refresh else None
    if cached is not None:
        return cached

    contested_printing_ids = contested_card_ids if contested_card_ids is not None else get_contested_card_ids()
    tag_contested_ids, tag_unresolved_ids = _tag_review_card_ids_by_status()

    confirmable = (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            printing_tags__source__in=[VoteSource.DEDUCTION, VoteSource.OCR],
        )
        .exclude(printing_tags__source__in=[VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED])
        .distinct()
        .count()
    )

    contested = (
        Card.objects.filter(
            (Q(pk__in=contested_printing_ids) & Q(printing_tag_status=PrintingTagStatus.UNRESOLVED))
            | Q(artist_vote_status=ArtistVoteStatus.CONTESTED)
            | Q(pk__in=tag_contested_ids)
        )
        .distinct()
        .count()
    )

    fresh = (
        Card.objects.filter(
            (Q(printing_tag_status=PrintingTagStatus.UNRESOLVED) & ~Q(pk__in=contested_printing_ids))
            | Q(artist_vote_status=ArtistVoteStatus.UNRESOLVED)
            | Q(pk__in=tag_unresolved_ids)
        )
        .distinct()
        .count()
    )

    total = (
        Card.objects.filter(
            Q(printing_tag_status=PrintingTagStatus.UNRESOLVED)
            | Q(artist_vote_status__in=[ArtistVoteStatus.UNRESOLVED, ArtistVoteStatus.CONTESTED])
            | Q(pk__in=tag_contested_ids | tag_unresolved_ids)
        )
        .distinct()
        .count()
    )

    counts = QuestionFeedCounts(total=total, confirmable=confirmable, contested=contested, fresh=fresh)
    if shared_cache is not None:
        shared_cache.set(cache_key, counts, _REMAINING_ESTIMATE_CACHE_TTL)
    return counts


def warm_feed_supply_cache() -> QuestionFeedCounts:
    """Refreshes the two 300s-TTL "shared"-cache entries `views.get_question_feed` reads on
    every request (`printing_consensus.get_contested_card_ids`'s own cache, then this module's
    own `get_remaining_estimate` cache) - the body of the `warm_question_feed_remaining_estimate`
    management command. Both are compute-on-miss caches with the TTL as their only invalidation
    (see each function's own docstring): whichever request happens to land after either entry
    has expired pays the uncached cost - measured 2026-08-16 at ~9.2s for `get_remaining_
    estimate` alone - instead of a scheduled warm paying it off the request path. Calling this
    on a cadence shorter than the 300s TTL (`settings.QUESTION_FEED_REMAINING_ESTIMATE_WARM_
    MINUTES`) keeps both entries from ever lapsing under real traffic gaps.

    Passes force_refresh=True to both calls (2026-08-20 fix): on the normal cadence - a warm
    interval shorter than the 300s TTL - both entries are still valid when the warm runs, so
    without force_refresh each call would hit the read-through cache, return the cached value,
    and write nothing - the entry's expiry stays pinned to its original write and still lapses
    300s later regardless of how often this runs, so a visitor eventually pays the uncached cost
    anyway (measured live 2026-08-20: a warm at T+108s returned in 0.23s and wrote nothing; the
    entry, written at T+0, still expired at T+300s as if the warm had never happened). Forcing
    the recompute makes every warm actually recompute-and-overwrite, resetting the TTL each time,
    so the entry can never lapse between warms - see this module's own docstring's "Idempotent
    and safe to re-run" line, which already asserted this and is now what the code does. Only
    this warm ever passes force_refresh=True; every other caller (above all views.
    get_question_feed's request path) keeps reading through the cache exactly as before.

    Threads the SAME resolved `contested_card_ids` list into `get_remaining_estimate` that
    `views.get_question_feed` itself threads into it (see that view's own comment on why it
    resolves this once and passes it to both calls) - the digest-keyed cache entry this warm
    writes is therefore the exact key a subsequent live request will read, not a different,
    unreachable one (see `_remaining_estimate_cache_key`'s own docstring for why the key is a
    digest of the list's content rather than a stable constant)."""
    contested_card_ids = get_contested_card_ids(force_refresh=True)
    return get_remaining_estimate(contested_card_ids, force_refresh=True)


__all__ = [
    "get_next_question_feed_item",
    "get_remaining_estimate",
    "is_likely_resolve_printing",
    "warm_feed_supply_cache",
    "QUICK_NEGATIVE_SKIP_REASONS",
]
