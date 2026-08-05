from dataclasses import dataclass
from typing import Hashable, Iterable, Literal, Sequence, TypedDict

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import F, QuerySet

from cardpicker.evidence_transfer import md5_currency_q
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardPrintingTag,
    ImageEvidence,
    PrintingTagStatus,
    calculator_family,
)
from cardpicker.vote_consensus import (
    VoteTuple,
    contested_queryset,
    is_human_backed_source,
    pool_group_votes,
    resolve_vote_weight,
    resolve_weighted_consensus,
)

NO_MATCH: Literal["NO_MATCH"] = "NO_MATCH"

# `Card.md5_checksum` (the Drive-API-reported checksum of the image file this catalogue row
# indexes), referenced by NAME rather than as an attribute so this module is importable and
# correct both before and after that field exists: it is added by issue #473's PR-1
# (`md5-checksum-substrate`), which this branch is cut BEFORE and merges AFTER. Every read of it
# funnels through `_card_md5_checksum`/`_md5_checksums_for_card_ids`/`_card_ids_with_md5_checksums`
# below - the only three places in this module that touch the column - so on a checkout without
# the field every card is a group of one and every group-aware path below degenerates, provably,
# to its pre-#473 behavior.
MD5_CHECKSUM_FIELD = "md5_checksum"


def _card_md5_checksum(card: Card) -> str | None:
    """
    `card`'s file checksum, or `None` when it has none (`LOCAL_FILE` and other checksum-less
    sources, per issue #473 ruling 3) - and, until PR-1 lands, for every card, since the field
    doesn't exist yet and `getattr` reports the default. Empty string is normalized to `None`:
    "" is not an identity, and grouping every checksum-less card into one giant group would be a
    catastrophic misreading of exactly this degenerate case.
    """
    return getattr(card, MD5_CHECKSUM_FIELD, None) or None


def _md5_checksum_column_exists() -> bool:
    """
    Whether `Card.md5_checksum` exists on this checkout - False until issue #473's PR-1 merges
    into this branch, True forever after. Only the BULK reader below needs to ask: it filters on
    the column by name (`.values_list`), which raises rather than degrading if the field is
    absent, unlike `_card_md5_checksum`'s per-instance `getattr`. A `_meta` lookup, so this is a
    dict access, not a query - safe to call per request.
    """
    try:
        Card._meta.get_field(MD5_CHECKSUM_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def _md5_checksums_for_card_ids(card_ids: Iterable[int]) -> set[str]:
    """
    The distinct non-null checksums held by `card_ids` - ONE column read, not a fetch of whole
    `Card` rows (2026-07-25 gate on PR #482, condition f1: the row-fetch form regressed the
    question feed's per-request cost even before PR-1, since it hydrated a model instance per
    card the voter had ever voted on purely to read one string off it). Returns an empty set,
    without querying at all, while the column doesn't exist.
    """
    if not _md5_checksum_column_exists():
        return set()
    return {
        checksum
        for checksum in Card.objects.filter(pk__in=card_ids).values_list(MD5_CHECKSUM_FIELD, flat=True)
        if checksum
    }


def _card_ids_with_md5_checksums(checksums: set[str]) -> list[int]:
    """
    Every `Card.pk` whose checksum is in `checksums` - the one query in this module that filters
    ON the column (see `MD5_CHECKSUM_FIELD`). Unreachable while the field doesn't exist, because
    its only callers below skip it when they hold no non-null checksum, and `_card_md5_checksum`
    can only report non-null once PR-1 has added the column.
    """
    return list(Card.objects.filter(**{f"{MD5_CHECKSUM_FIELD}__in": checksums}).values_list("pk", flat=True))


def md5_group_key(card: Card) -> Hashable:
    """
    Stable identity of `card`'s md5 group, for callers that need to visit each group ONCE across
    a large iteration (`consensus_recompute`) rather than re-resolving the same group per member.
    A checksum-less card keys on its own pk, so it is always a group of one and never collides
    with another card's key.
    """
    checksum = _card_md5_checksum(card)
    return ("md5", checksum) if checksum is not None else ("card", card.pk)


def md5_group_card_ids(card: Card) -> list[int]:
    """
    The pks of `card`'s md5 identity group - every card indexing a byte-identical image file,
    `card` included - sorted, so the tally built from it is deterministic. `[card.pk]` for a
    checksum-less or unique-checksum card (issue #473 ruling 3's group of one), which is also
    the shape every card has before PR-1 adds the checksum column.
    """
    checksum = _card_md5_checksum(card)
    if checksum is None:
        return [card.pk]
    return sorted(set(_card_ids_with_md5_checksums({checksum})) | {card.pk})


def _require_full_md5_group(card: Card, group_card_ids: Sequence[int], parameter: str) -> None:
    """
    Raises unless `group_card_ids` is EXACTLY `card`'s md5 identity group. The completeness
    guard behind every caller-supplied group in this module - see `group_printing_votes`, its
    only call site, and `resolve_printing`'s docstring for the contract it enforces.

    WHY THIS EXISTS AT ALL (issue #473 ruling 1; docs/theory.md §10a's population-dependence
    classification, PR #546)
    ------------------------------------------------------------------------------------------
    Consensus pools votes across the whole md5 identity group and deduplicates per AGENT
    (`build_group_printing_vote_tuples` -> `vote_consensus.pool_group_votes`), so the tally is
    DEFINED over the group, not over whatever subset of it a caller happened to hold. Hand this
    module a subset and you do not get a weakened tally, you get a DIFFERENT one:

      - an agent that voted consistently on the members you kept but contradicted itself on a
        member you dropped is COUNTED here, where the full group withholds it entirely;
      - conversely, dropping the member carrying an agent's second, agreeing vote does not
        change that agent's contribution at all (pooling already collapsed it) - so the error is
        not even monotone in the number of members dropped;
      - the surviving members' weights are re-shared against a smaller total, moving
        `min_share`.

    The failure is SILENT: no exception, no log line, a plausible-looking `CanonicalCard` that
    can be a DIFFERENT PRINTING from the one the whole group's evidence selects, persisted onto
    every member by `resolve_and_persist_printing`. The invariant at risk - "one identification
    target gets one tally" - is exactly the thing #473 exists to establish, and it is not
    something a docstring can hold up on its own once a batch-scoping pass starts threading a
    batch's `card_ids` through this file (#533/#541: scoping a batch's TARGETS by `card_ids` is
    correct; scoping a target's md5 NEIGHBOURHOOD lookup by the same list is not). This guard is
    what makes that distinction enforceable rather than advisory.

    WHAT IS COMPARED, AND WHY IT IS NOT JUST SET EQUALITY
    -----------------------------------------------------
    `sorted(group_card_ids) == md5_group_card_ids(card)`, i.e. set equality AND no duplicates;
    ordering is normalised away and genuinely does not matter, duplicates genuinely do.

      - ORDER is irrelevant because of how the value is CONSUMED: `group_printing_votes` only
        ever feeds it to `filter(card_id__in=...)` (set semantics) and takes its `len()`. The
        determinism of the pooled tally comes from that query's own `.order_by("card_id", "pk")`,
        never from the order of this argument - so rejecting a correct group for arriving
        unsorted would be a gratuitous failure with no soundness content behind it.
      - DUPLICATES are NOT harmless, which is why plain set equality would have left a second,
        narrower hole open here. `group_printing_votes` branches on `len(group_card_ids) <= 1`:
        `[pk, pk]` for a genuine group of ONE compares set-equal to `[pk]` but has length 2, so
        it takes the multi-member branch and pools with `dedupe_key` set. That flips the tally
        for a real, reachable shape - one agent holding two contradicting printing votes on a
        single card is withheld under pooling and counted without it - i.e. exactly the
        silent-different-winner failure this function exists to stop, arriving through the one
        comparison a set-equality check waves through.

    COST, STATED PLAINLY: this re-derives the group, so `group_card_ids` NO LONGER SAVES A
    QUERY. Its optimisation value is gone, deliberately, and it is retained only as a checked
    assertion (removing the parameter outright would churn `resolve_and_persist_printing` and
    `consensus_recompute` for no soundness gain). That is an honest trade rather than a
    regression: what it costs back is ONE query - `md5_group_card_ids` is zero queries for a
    checksum-less card and, for a card with a checksum, a single equality lookup on
    `Card.md5_checksum`, which carries `db_index=True`. Set against the `CardPrintingTag` fetch
    with `select_related("printing")` this function's caller is about to issue anyway - plus, on
    the persist path, one UPDATE per member and possibly an Elasticsearch round trip - the
    parameter was always buying back a marginal fraction of the call's cost. Correctness that is
    checked in production is worth more than that, so this is deliberately NOT behind a
    settings/DEBUG flag: a guard that only fires in tests does not make the unsafe call
    unrepresentable where the damage is done, and the wiring mistake it guards is one that would
    reach production looking entirely reasonable.

    Not an `assert`, for the same reason: `python -O` strips those, and this must hold in the
    deployment where a wrong resolution actually gets written. `ValueError` matches this
    codebase's convention for a caller-supplied value that violates a documented contract
    (`golden_set.get_golden_cards`'s completeness check, `operating_envelope.acknowledge_trip`,
    `integrations.game.base`), as distinct from the `RuntimeError` it uses for missing
    environment/seed preconditions.

    Race note: the authoritative group is re-read here, so a checksum written to a sibling
    between the caller deriving its group and this check re-deriving it raises rather than
    resolving. That is the safe direction (the caller's group is genuinely stale at that point,
    and its resolution would be computed over the wrong target), it is self-healing on the next
    call, and in practice a card's checksum is written once by backfill/scan and not churned.
    """
    authoritative = md5_group_card_ids(card)  # sorted and deduplicated by construction
    supplied = list(group_card_ids)
    if sorted(supplied) == authoritative:
        return

    supplied_set = set(supplied)
    missing = sorted(set(authoritative) - supplied_set)
    foreign = sorted(supplied_set - set(authoritative))
    duplicated = sorted({card_id for card_id in supplied_set if supplied.count(card_id) > 1})
    raise ValueError(
        f"`{parameter}` is not card {card.pk}'s full md5 identity group "
        f"(missing {missing}, not in the group {foreign}, duplicated {duplicated}). "
        "This parameter is an OPTIMISATION ONLY and MUST be exactly `md5_group_card_ids(card)`. "
        "A partial group does not produce a weaker tally, it produces a DIFFERENT one: consensus "
        "pools votes across the whole group and deduplicates per agent, so dropping members "
        "changes which agents are counted and which are withheld for self-contradiction, and can "
        "therefore select a DIFFERENT WINNING PRINTING - silently, with a plausible-looking "
        "result written to every member. If you arrived here from a batch-scoping pass (#533/"
        "#541): scope the batch's TARGETS by its card_ids, never a target's md5 neighbourhood "
        f"lookup. The fix is to pass `{parameter}=None` and let this module derive the group "
        "itself, which costs one indexed query - never to widen or delete this check."
    )


def md5_group_cards(card: Card) -> list[Card]:
    """
    `card`'s md5 group as `Card` INSTANCES, with the caller's own `card` object first and
    unreplaced - `resolve_and_persist_printing` writes through these instances, and its callers
    (e.g. `consensus_recompute`, the vote-submission views) read `card.printing_tag_status` off
    their own object afterwards, so substituting a freshly-fetched copy of the same row would
    silently strand them on a stale status. A group of one performs no query at all.
    """
    group_card_ids = md5_group_card_ids(card)
    other_ids = [card_id for card_id in group_card_ids if card_id != card.pk]
    if not other_ids:
        return [card]
    return [card, *Card.objects.filter(pk__in=other_ids)]


def md5_group_expanded_card_ids(card_ids: Iterable[int]) -> set[int]:
    """
    `card_ids` widened to include every md5 sibling of every card in it - "the cards this voter
    has already answered" widened to "the identity groups this voter has already answered", for
    `question_feed`'s serve-one-member-per-group exclusion. Returns `card_ids` unchanged when
    none of them carry a checksum (which, before PR-1, is always - at a cost of zero queries,
    see `_md5_checksums_for_card_ids`). At most two queries otherwise, neither of which
    materializes a `Card` instance.
    """
    ids = set(card_ids)
    if not ids:
        return ids
    checksums = _md5_checksums_for_card_ids(ids)
    if not checksums:
        return ids
    return ids | set(_card_ids_with_md5_checksums(checksums))


# `ImageEvidence.artbox_phash` (issue #480) is a 64-bit perceptual hash of the card's own art-box
# region, populated by a whole-catalogue Stage C pass rather than being upload-time metadata like
# `Card.md5_checksum`. Distance-0 (exact) equality on it is a WIDER identity relation than md5:
# two files that are NOT byte-identical (a re-encode, a fresh re-upload, a genuine reprint using
# the same digital art asset) can still hash identically here. Issue #661 is what authorizes
# treating that as sound entailment rather than mere narrowing: `image_evidence.py`'s own
# "SOUNDNESS NOTE FOR ANY FUTURE CONSUMER" and `docs/theory.md` §4's two-threshold split both
# reserve d=0, and ONLY d=0, as "the same uploaded image, transitively true" - a Hamming-distance
# threshold match (`find_best_match`'s 20/5 cutoffs) stays narrowing-only, untouched by this
# module. The functions below mirror the md5 helpers above in shape (see each one's own
# docstring for the one place it must differ - `artbox_phash` lives on `ImageEvidence`, not on
# `Card`, so a per-card read costs a query current-checksum reads do not) and are never consulted
# on their own: `identity_group_card_ids` below is the sole entry point every caller outside this
# module (and `group_printing_votes`/`resolve_and_persist_printing` inside it) is meant to use -
# a phash-only grouping mechanism living BESIDE the md5 one is the outcome this module's own
# docstring framing exists to avoid.


def _current_artbox_phash_queryset() -> "QuerySet[ImageEvidence]":
    """
    Every `ImageEvidence` row that is (a) CURRENT for its card - `content_hash` agrees with the
    card's own live `content_phash`, and the row's own stamped `md5_checksum` doesn't actively
    disagree with the card's (the same bulk currency rule `modern_artist_credit.
    eligible_evidence_queryset` applies, via the shared, null-tolerant `evidence_transfer.
    md5_currency_q` - never reinvented here) - and (b) carries a computed `artbox_phash`. A STALE
    row (the card's image has changed since this row was written) is exactly as untrustworthy for
    grouping as it is for any other Stage C/D read in this codebase: it may describe art that no
    longer exists at this card, so it must never seed a vote-pooling group.
    """
    return ImageEvidence.objects.filter(content_hash=F("card__content_phash"), artbox_phash__isnull=False).filter(
        md5_currency_q()
    )


def _card_artbox_phash(card: Card) -> int | None:
    """
    `card`'s own CURRENT `artbox_phash`, or `None` if it has none - no evidence yet, a stale row,
    or a card whose art-box was never classifiable (`image_evidence.py`'s own docstring: an
    unclassifiable frame or a degenerate crop box). Unlike `_card_md5_checksum` (a plain
    `getattr`, zero queries - `md5_checksum` lives directly on `Card`), this costs one query:
    `artbox_phash` lives on the related `ImageEvidence` row, not on `Card` itself.
    """
    return _current_artbox_phash_queryset().filter(card_id=card.pk).values_list("artbox_phash", flat=True).first()


def _artbox_phashes_for_card_ids(card_ids: Iterable[int]) -> set[int]:
    """
    The phash analogue of `_md5_checksums_for_card_ids`: the distinct CURRENT, non-null
    `artbox_phash` values held by `card_ids` - one query, no `ImageEvidence` instances
    materialized. `phash is not None`, not a truthy check: unlike a checksum, `0` is a real,
    reachable hash value here, not an empty-string-style sentinel.
    """
    return {
        phash
        for phash in _current_artbox_phash_queryset()
        .filter(card_id__in=card_ids)
        .values_list("artbox_phash", flat=True)
        if phash is not None
    }


def _card_ids_with_artbox_phashes(phashes: set[int]) -> list[int]:
    """
    The phash analogue of `_card_ids_with_md5_checksums`: every `Card.pk` whose CURRENT
    `artbox_phash` is in `phashes`.
    """
    return list(_current_artbox_phash_queryset().filter(artbox_phash__in=phashes).values_list("card_id", flat=True))


def phash_group_card_ids(card: Card) -> list[int]:
    """
    The pks of `card`'s artbox-phash-d0 group - every card whose CURRENT `artbox_phash` exactly
    equals `card`'s own, `card` included - sorted, mirroring `md5_group_card_ids`. `[card.pk]`
    for a card with no current phash: absence of `artbox_phash` is a group of ONE, never a shared
    group with every other phash-less card - the same catastrophic-misread risk `_card_md5_
    checksum`'s own docstring already warns about for a checksum-less card, and exactly the
    failure mode issue #661's brief calls out by name ("cards with no artbox_phash are not a
    group of NULLs").
    """
    phash = _card_artbox_phash(card)
    if phash is None:
        return [card.pk]
    return sorted(set(_card_ids_with_artbox_phashes({phash})) | {card.pk})


def identity_group_key(card: Card) -> Hashable:
    """
    Stable identity of `card`'s COMBINED (md5 union phash-d0) group, for callers that visit each
    group once across a large iteration (`consensus_recompute`), mirroring `md5_group_key`'s own
    contract. Checksum is checked FIRST and, when present, used ALONE (never combined with phash
    in the key itself): every member of an md5 clique that also carries a current phash
    necessarily shares that SAME phash value too (`artbox_phash` is a deterministic function of
    the image bytes), so keying on checksum already reaches every such member - see
    `identity_group_card_ids`'s docstring for the full argument this relies on.

    This key can UNDER-collapse relative to the true combined group in one specific, harmless
    way: two true members of one group reached by DIFFERENT keys (one via `("md5", X)` because it
    has no phash, another via `("phash", Y)` because it has no checksum) both still return the
    same group from `identity_group_card_ids` when actually resolved - membership is never
    decided by this key, only VISIT-ONCE is. At worst this costs a redundant re-resolution of the
    same group from a second visited member (an extra query and an idempotent rewrite), never a
    wrong one.
    """
    checksum = _card_md5_checksum(card)
    if checksum is not None:
        return ("md5", checksum)
    phash = _card_artbox_phash(card)
    if phash is not None:
        return ("phash", phash)
    return ("card", card.pk)


def identity_group_card_ids(card: Card) -> list[int]:
    """
    `card`'s full pooling identity group (issue #661): the UNION of its md5 group (byte-identical
    files) and its artbox-phash-d0 group (perceptually-identical art-box crop), `card` included,
    sorted and deduplicated. This is THE group `group_printing_votes`/`resolve_printing`/
    `resolve_and_persist_printing` pool votes across - md5 alone was #473's definition of "one
    identification target"; issue #661 WIDENS that definition, it does not add a second one
    beside it.

    WHY A SINGLE UNION - NOT AN ITERATIVE TRANSITIVE CLOSURE - IS ALREADY THE FULL COMPONENT
    ------------------------------------------------------------------------------------------
    Two cards could in principle be linked only through a CHAIN - A shares a checksum with B, B
    (not A) shares a phash with C - in which case unioning A's own two DIRECT groups could look
    like it risks missing C. It never actually does, because `artbox_phash` is a deterministic
    function of the image bytes: if A and B are byte-identical (an md5 edge) and BOTH carry a
    current phash, that phash is necessarily the SAME value on both rows - so B's phash edge to C
    is already, independently, an edge from A to C directly (A and C share that same phash
    value), reachable by A's own phash-group lookup without visiting B first. The same argument
    runs symmetrically for two cards linked only by a shared phash whose md5-sibling reaches a
    third. One md5 lookup plus one phash lookup, both rooted at `card` itself, therefore already
    return the full connected component - no BFS/union-find needed.

    (This relies on `artbox_phash` having been computed consistently for both byte-identical
    rows, under the same extractor version. A version bump straddling two siblings' extraction
    times could, in the worst case, UNDER-group them - the safe direction, the same tolerance
    `agent_dedupe_key`'s own version-bump handling elsewhere in this module accepts - never
    falsely merge two genuinely different targets.)

    A card with neither a checksum nor a current phash is a group of one, same as ruling 3 always
    was for md5 alone.
    """
    return sorted(set(md5_group_card_ids(card)) | set(phash_group_card_ids(card)))


def _require_full_identity_group(card: Card, group_card_ids: Sequence[int], parameter: str) -> None:
    """
    Raises unless `group_card_ids` is EXACTLY `card`'s full combined identity group - the
    combined-group analogue of `_require_full_md5_group`; read THAT function's docstring for the
    complete argument (the silent-different-winner failure mode a partial group causes, why plain
    set equality is insufficient, the `ValueError`-not-`assert` choice). Everything there applies
    unchanged here, checked against `identity_group_card_ids(card)` in place of
    `md5_group_card_ids(card)`.
    """
    authoritative = identity_group_card_ids(card)
    supplied = list(group_card_ids)
    if sorted(supplied) == authoritative:
        return

    supplied_set = set(supplied)
    missing = sorted(set(authoritative) - supplied_set)
    foreign = sorted(supplied_set - set(authoritative))
    duplicated = sorted({card_id for card_id in supplied_set if supplied.count(card_id) > 1})
    raise ValueError(
        f"`{parameter}` is not card {card.pk}'s full identity group "
        f"(missing {missing}, not in the group {foreign}, duplicated {duplicated}). "
        "This parameter is an OPTIMISATION ONLY and MUST be exactly `identity_group_card_ids(card)`. "
        "A partial group does not produce a weaker tally, it produces a DIFFERENT one: consensus "
        "pools votes across the whole group and deduplicates per agent, so dropping members "
        "changes which agents are counted and which are withheld for self-contradiction, and can "
        "therefore select a DIFFERENT WINNING PRINTING - silently, with a plausible-looking "
        "result written to every member. If you arrived here from a batch-scoping pass (#533/"
        "#541): scope the batch's TARGETS by its card_ids, never a target's identity neighbourhood "
        f"lookup. The fix is to pass `{parameter}=None` and let this module derive the group "
        "itself, which costs a few indexed queries - never to widen or delete this check."
    )


def identity_group_cards(card: Card) -> list[Card]:
    """
    `card`'s combined identity group as `Card` INSTANCES, `card` itself first and unreplaced -
    mirrors `md5_group_cards` exactly (see its docstring for why identity, not just pk, must be
    preserved: callers write through and later read off their own `card` object).
    """
    group_card_ids = identity_group_card_ids(card)
    other_ids = [card_id for card_id in group_card_ids if card_id != card.pk]
    if not other_ids:
        return [card]
    return [card, *Card.objects.filter(pk__in=other_ids)]


def identity_group_expanded_card_ids(card_ids: Iterable[int]) -> set[int]:
    """
    `card_ids` widened to every member of each card's combined identity group - the phash-aware
    analogue of `md5_group_expanded_card_ids`, used the same way by `question_feed.py`: "cards
    this voter has answered" widened to "identity groups this voter has answered", so a voter who
    answered one member of a phash-d0 group is not re-asked the same art under a sibling's
    identifier either. At most four queries (the existing checksum pair, plus the phash pair) -
    see `identity_group_card_ids`'s docstring for why widening through each channel once, rooted
    in the ORIGINAL `card_ids`, already reaches the full component with no further iteration.
    """
    ids = set(card_ids)
    if not ids:
        return ids
    expanded = set(ids)
    checksums = _md5_checksums_for_card_ids(ids)
    if checksums:
        expanded |= set(_card_ids_with_md5_checksums(checksums))
    phashes = _artbox_phashes_for_card_ids(ids)
    if phashes:
        expanded |= set(_card_ids_with_artbox_phashes(phashes))
    return expanded


@dataclass(frozen=True)
class ResolvedPrinting:
    expansion_code: str
    collector_number: str
    full_art: bool
    border_color: str


def get_resolved_printings(identifiers: Iterable[str]) -> dict[str, ResolvedPrinting]:
    """
    Batch lookup of community-vote-RESOLVED printing data for a set of `Card.identifier`s.
    This is the hard-gate helper: cards absent from the returned dict are UNRESOLVED or
    NO_MATCH and MUST be treated as unaffected by any printing-tag-driven consumption
    behavior (search re-ranking, attribute filtering) - callers should never fall back to
    `canonical_card` or otherwise infer a printing for an identifier this function omits.
    Shared by both the search re-rank and the attribute-filter logic in
    `cardpicker.search.search_functions.retrieve_card_identifiers`, so the two features can't
    drift out of sync on what counts as "resolved."
    """
    cards = Card.objects.filter(
        identifier__in=identifiers,
        printing_tag_status=PrintingTagStatus.RESOLVED,
    ).select_related("inferred_canonical_card__expansion", "inferred_canonical_card__printing_metadata")
    result: dict[str, ResolvedPrinting] = {}
    for card in cards:
        printing = card.inferred_canonical_card
        if printing is None:
            # shouldn't happen given resolve_and_persist_printing's invariant (RESOLVED always
            # pairs with a non-null inferred_canonical_card), but a card in an inconsistent
            # state should be treated as unresolved rather than crash the search path.
            continue
        metadata = getattr(printing, "printing_metadata", None)
        result[card.identifier] = ResolvedPrinting(
            expansion_code=printing.expansion.code.upper(),
            collector_number=printing.collector_number,
            full_art=metadata.full_art if metadata is not None else False,
            border_color=metadata.border_color if metadata is not None else "",
        )
    return result


def group_printing_votes(card: Card, group_card_ids: Sequence[int] | None = None) -> tuple[list[CardPrintingTag], bool]:
    """
    Every `CardPrintingTag` row cast against any member of `card`'s combined identity group (md5
    union artbox-phash-d0, issue #661 - see `identity_group_card_ids`'s own docstring for the
    union-not-closure argument), plus whether that group actually has more than one member.

    `group_card_ids`, when given, MUST be `card`'s COMPLETE identity group - it is a convenience
    for a caller that already derived the group (e.g. it is about to persist to those same
    members), NOT a way to ask this function about part of one. That is CHECKED, not merely
    documented: this is the one place in this module where a caller-supplied group is consumed,
    so `_require_full_identity_group` is called here, before either use of the value below, and a
    narrowed group (the shape a batch-scoping pass would naturally produce - see #533/#541)
    raises instead of quietly returning a different tally's worth of rows. Read that function's
    docstring before changing this line, and note that the check must MOVE WITH THE CONSUMPTION:
    it lives here rather than in `resolve_printing` precisely so it cannot be bypassed by a
    second entry point, and so the group is re-derived once per call rather than twice.

    A group of ONE reads `card.printing_tags.all()` - deliberately the identical expression
    this module used before issue #473, not a `filter(card_id__in=[card.pk])` that happens to
    return the same rows: that expression is what honours a caller's own
    `prefetch_related("printing_tags")` (`consensus_recompute` batches on exactly that, one
    query per batch instead of one per card), and keeping it is what makes the singleton case a
    byte-for-byte no-op in query shape as well as in outcome. The multi-member branch orders by
    `(card_id, pk)` so the pooled tally `pool_group_votes` builds is deterministic across runs.
    """
    if group_card_ids is None:
        group_card_ids = identity_group_card_ids(card)
    else:
        _require_full_identity_group(card, group_card_ids, "group_card_ids")
    if len(group_card_ids) <= 1:
        return list(card.printing_tags.all()), False
    votes = list(
        CardPrintingTag.objects.filter(card_id__in=group_card_ids).select_related("printing").order_by("card_id", "pk")
    )
    return votes, True


def agent_dedupe_key(anonymous_id: str) -> str:
    """
    The identity of the AGENT behind `anonymous_id`, for `pool_group_votes`' `dedupe_key`: the
    versionless CALCULATOR FAMILY (`models.calculator_family` - "stage-d-join-key" for
    "stage-d-join-key-v1") when the id follows the machine naming convention, and otherwise the
    `anonymous_id` verbatim.

    WHY THE FAMILY IS THE AGENT, and why this must not be "simplified" back to the raw id
    ------------------------------------------------------------------------------------
    A machine calculator carries its version INSIDE its identity string rather than beside it as
    metadata, so bumping a calculator (`-v1` -> `-v2`) changes the string every one of its votes
    is stamped with. Keying pooling on that raw string makes ONE calculator look like TWO
    INDEPENDENT AGENTS the moment its version is bumped, because `pool_group_votes` compares
    keys for equality and "x-v1" != "x-v2".

    DELIBERATELY STILL FAMILY-KEYED after the 2026-07-29 re-scoping of the deductive-backfill
    zero-weight ruling (which moved THAT rule from the calculator family to one run's `run_id` -
    see `vote_consensus.resolve_vote_weight`). Pooling identity and vote weight are answering
    different questions, and this one is unchanged by that clarification: "is this the same agent
    speaking twice about byte-identical images?" has nothing to do with which run cast the vote.
    Keying pooling on `run_id` would make one calculator N independent agents, one per invocation
    - a far worse version of the version-bump bug described below.

    The consequence, spelled out because it looks alarming and is not: inside an md5 identity
    group, a frozen-cohort vote (weight 0) and a fresh deductive-backfill vote (weight 0.5) for
    the SAME outcome now pool together as one agent, and `pool_group_votes` keeps that agent's
    HIGHEST weight - 0.5. No weight is manufactured: 0.5 is exactly what the group would carry if
    the cohort row did not exist at all, which is precisely what "held out of the math" means.
    Disagreeing across the group still withholds the agent entirely, as for any other agent.

    That is reachable in ordinary operation, not a hypothetical: a version bump re-votes cards
    INCREMENTALLY, so an md5 identity group whose members straddle the migration holds some
    members' votes under the old version and some under the new one. Under a raw-id key those
    two rows sum, and one calculator on its own supplies the whole of `PRINTING_TAG_MIN_VOTES`
    - exactly the "summed weight means distinct agents" invariant `pool_group_votes` exists to
    enforce (see its docstring's soundness paragraph), defeated by a routine redeploy.

    v1 and v2 of one calculator are the SAME agent holding an updated opinion, not two
    independent observers: they run the same algorithm over the same evidence channel on the
    same bytes, so their agreement is correlated by construction and carries no more information
    than either alone. Keying on the family makes that structural fact mechanical - agreement
    across a version bump collapses to one event, and a calculator that CONTRADICTS ITSELF
    across a version bump (v1 said printing A, v2 says printing B - the normal shape of a
    corrective re-vote) is withheld from the group's tally entirely, which is the correct
    reading: it changed its mind about byte-identical bytes, so it is not evidence for either
    outcome until the group is re-voted consistently.

    HUMAN VOTERS ARE UNTOUCHED, structurally rather than by convention: human `anonymous_id`s
    are client-generated UUIDs (`frontend/src/common/anonymousId.ts`), which can never match
    `models.CALCULATOR_VERSION_RE`, so `calculator_family` returns None for every one of them
    and they fall through to the raw-id branch and dedupe on their own UUID exactly as before
    this function existed. The 2026-07-25 gate on PR #482 (condition 1) requires humans to be
    keyed at all - that is unchanged here; only the KEY a machine id maps to changes. Pinned by
    `test_md5_group_pooling.TestVersionedCalculatorIdentity`.

    Do NOT collapse this back to `vote.anonymous_id`. It reads like an identity function with
    extra steps only because the failure it prevents is invisible until a calculator is
    versioned up, at which point it silently lowers the quorum bar for that calculator's whole
    cohort with no error and no log line.
    """
    return calculator_family(anonymous_id) or anonymous_id


def build_group_printing_vote_tuples(
    votes: Iterable[CardPrintingTag], pool: bool, printings_by_id: dict[int, CanonicalCard] | None = None
) -> list[VoteTuple]:
    """
    Translates `CardPrintingTag` rows into the `VoteTuple`s `resolve_weighted_consensus` reads,
    pooling them across an md5 identity group when `pool` is True (issue #473 ruling 1, applied
    by `vote_consensus.pool_group_votes`): EVERY vote is keyed on the identity of the agent that
    cast it - human-backed votes included - so one agent's agreeing votes about a set of
    byte-identical images are ONE event no matter how many members carry a copy, and one agent
    that contradicts itself across members is withheld from the tally entirely. Distinct agents
    still sum: two different people voting on two members are two votes, which is the point of
    tallying a group as one target.

    That agent identity is `agent_dedupe_key(vote.anonymous_id)`, NOT `vote.anonymous_id` itself
    - read that function's docstring before touching this line. In short: a machine calculator's
    version lives inside its `anonymous_id`, so keying on the raw string counts one calculator
    as two independent agents across a version bump; the versionless family is the stable agent
    identity. Human voters' UUIDs have no family and key on themselves, unchanged.

    Human-backed votes were NOT keyed in this function's first form, on the reading that separate
    people are separate events regardless. That was wrong for the case that matters and was
    rejected at review (2026-07-25 gate on PR #482, condition 1): `anonymous_id` identifies the
    VOTER, so leaving human votes unkeyed let ONE person reach a 2.0 quorum by answering the same
    image twice under two of its identifiers - a resolution neither card could reach alone, from
    one human judgement. Keying humans too is what makes `PRINTING_TAG_MIN_VOTES` a count of
    distinct agents rather than of rows.

    With `pool=False` (a group of one) no vote is keyed, `pool_group_votes` is never called, and
    the returned list is exactly what this module built before #473.

    `votes` AND `pool` MUST COME FROM ONE `group_printing_votes` CALL, unsplit. This function
    shares `resolve_printing`'s silent-different-answer failure mode - a subset of a group's
    votes, or the right votes with `pool=False`, yields a plausible tally computed from part of
    the evidence - but it CANNOT check itself: it takes no `Card`, so it has no way to derive
    what the complete set would be, and `question_feed.is_likely_resolve_printing` legitimately
    feeds it a list that is not the DB's (it appends a hypothetical vote). The completeness
    guarantee therefore has to be established upstream, by `group_printing_votes`'
    `_require_full_md5_group` check, and carried here by passing that call's two return values
    together. Do not filter `votes` between the two calls, and do not compute `pool` yourself.

    Passing a `printings_by_id` dict populates it with each voted `CanonicalCard` (needed to map
    a winning outcome key back to a printing). Callers that only need the outcome KEY - e.g.
    `question_feed.is_likely_resolve_printing`, which runs this in a scan loop - pass `None` and
    this never touches `vote.printing`, so it costs no per-vote related lookup for them.

    Per-vote weight is resolved via `vote_consensus.resolve_vote_weight` (not a bare
    `_SOURCE_WEIGHTS[vote.source]` lookup) so the 2026-07-23 owner ruling zeroing the 2026-07-14
    deductive-backfill COHORT's weight - as re-scoped from the method to that one run by the
    2026-07-29 clarification (see that function's own docstring) - is honoured here -
    the one call site every printing consensus computation (winner selection, the gate checks
    and share math inside `resolve_weighted_consensus`, and every caller of `resolve_printing`,
    including `consensus_impact_report`/`consensus_recompute`) ultimately funnels through.
    """
    vote_tuples: list[VoteTuple] = []
    for vote in votes:
        key: int | Literal["NO_MATCH"]
        if vote.is_no_match:
            key = NO_MATCH
        else:
            # guaranteed non-null here by the model's printing_xor_no_match CheckConstraint
            assert vote.printing_id is not None
            key = vote.printing_id
            if printings_by_id is not None:
                assert vote.printing is not None
                printings_by_id[vote.printing_id] = vote.printing
        vote_tuples.append(
            VoteTuple(
                outcome_key=key,
                # `vote.run_id` is load-bearing here, not incidental metadata: it is what
                # distinguishes the frozen, zero-weighted 2026-07-14 deductive-backfill cohort
                # from an ordinary machine vote cast by the same calculator today (see
                # `resolve_vote_weight`). It is a plain column on the row this loop already
                # holds, so passing it costs no extra query - but do NOT add a `.only()`/
                # `.defer()` to any queryset feeding this that drops it, which would turn every
                # weight resolution into a per-row fetch.
                weight=resolve_vote_weight(vote.source, vote.anonymous_id, vote.run_id),
                is_human_backed=is_human_backed_source(vote.source),
                # agent identity, not the raw id - see `agent_dedupe_key`'s docstring for why a
                # version bump must not turn one calculator into two agents.
                dedupe_key=agent_dedupe_key(vote.anonymous_id) if pool else None,
            )
        )
    return pool_group_votes(vote_tuples) if pool else vote_tuples


def resolve_printing(
    card: Card, group_card_ids: Sequence[int] | None = None
) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Reconciles all `CardPrintingTag` votes cast against `card`'s combined identity group into a
    single resolved outcome: a specific `CanonicalCard` printing, the `NO_MATCH` sentinel
    (consensus is that no printing matches), or `None` if there isn't yet enough signal to
    conclude anything. See `cardpicker.vote_consensus.resolve_weighted_consensus` for the shared
    weighting/threshold rules (votes weighted by `source`, `PRINTING_TAG_MIN_VOTES`/
    `MIN_SHARE` gates, non-machine gate) - this is a thin wrapper translating `CardPrintingTag`
    rows into `VoteTuple`s and the winning outcome key back into a `CanonicalCard`.

    The identity group is the UNION (issue #661) of every card indexing a byte-identical image
    file (issue #473) and every card sharing `card`'s own artbox-phash at distance 0 - see
    `identity_group_card_ids`'s own docstring for why a single union already reaches the full
    connected component. Byte-identical files and phash-d0-identical art-box crops are both, by
    this module's own ruling, ONE identification target, so their votes are tallied once,
    together, and the outcome applies to all of it. A card with neither a checksum nor a current
    phash is a group of one (ruling 3) and takes the pre-#473 path unchanged - same rows, same
    query, same tuples, same result.

    `group_card_ids` - THE CONTRACT, in full
    ----------------------------------------
    Optional. When given it MUST be `card`'s COMPLETE identity group, i.e. exactly
    `identity_group_card_ids(card)` (ordering is normalised and irrelevant; duplicates are not
    permitted). It is a convenience for a caller that has already derived the group, never a way
    to scope this call to part of one.

    A BATCH-NARROWED GROUP IS THE SPECIFIC MISUSE THIS GUARDS. If you are threading a batch's
    `card_ids` through the pipeline (#533/#541), do not thread it into here: a batch's `card_ids`
    scopes which TARGETS get resolved, and this argument is a target's identity NEIGHBOURHOOD,
    whose members may lie outside the batch entirely. Scoping it by the batch is the
    natural-looking move and it is wrong.

    Passing anything else raises `ValueError`, because the failure it would otherwise cause is
    silent and is not a mere loss of signal: a subset yields a DIFFERENT tally, not a weaker one,
    and can select a different winning printing. See `_require_full_identity_group`/
    `_require_full_md5_group` for the full argument, what exactly is compared, and what the check
    costs; the check itself runs inside `group_printing_votes` below, where the value is actually
    consumed. Omitting the argument is always correct.
    """
    votes, is_group = group_printing_votes(card, group_card_ids)
    if not votes:
        return None

    printings_by_id: dict[int, CanonicalCard] = {}
    vote_tuples = build_group_printing_vote_tuples(votes, pool=is_group, printings_by_id=printings_by_id)

    winning_key = resolve_weighted_consensus(
        vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
    )
    if winning_key is None:
        return None
    if winning_key == NO_MATCH:
        return NO_MATCH
    assert isinstance(winning_key, int)
    return printings_by_id[winning_key]


def _effective_indexed_printing_id(status: str, printing_id: int | None) -> int | None:
    """
    The printing id that actually reaches Elasticsearch for a card in `status`: `Card.
    get_expansion_code`/`get_collector_number` (the fields `documents.py` indexes) only fall
    back to `inferred_canonical_card` while `printing_tag_status == RESOLVED` - a card that's
    UNRESOLVED or NO_MATCH is indexed as if `inferred_canonical_card` were `None`, regardless
    of what's actually stored there. Comparing this derived value (not the raw fields) before
    and after a consensus run is what lets a status flip with no printing change, or a
    printing change with no status flip, both correctly count as "the index needs updating."
    """
    return printing_id if status == PrintingTagStatus.RESOLVED else None


def resolve_and_persist_printing(
    card: Card, members: Sequence[Card] | None = None
) -> CanonicalCard | Literal["NO_MATCH"] | None:
    """
    Runs `resolve_printing(card)` and writes the outcome onto `inferred_canonical_card` and
    `printing_tag_status` together - for EVERY member of `card`'s combined identity group, not
    just `card` (issue #473 ruling 1, widened by issue #661: byte-identical images and
    phash-d0-identical art-box crops are each one identification target, so a resolution reached
    on one member is a resolution for all of them, and cannot be allowed to disagree with itself
    across the group by construction). `Card.serialise()` (which already reads
    `inferred_canonical_card`) and the printing-tag review queue (which filters on the indexed
    `printing_tag_status`, rather than recomputing consensus for every card) therefore stay in
    sync with the latest votes for every member at once. Intended to be called synchronously
    right after a vote is submitted for `card` - cheap, since it only touches this one group's
    own votes. Returns the same outcome `resolve_printing` returned, so callers don't need to
    recompute it again immediately afterwards.

    A group of one (neither a checksum nor a current phash - ruling 3) writes exactly the one
    row it always did, through the caller's own `card` instance, with no additional query.

    `members` may be passed by a caller that already materialized the group (see
    `identity_group_cards`, whose contract this expects: `card` itself, first, unreplaced). Both
    halves of that contract are now CHECKED rather than assumed, because both fail silently:

      - COMPLETENESS is enforced transitively and for free - the pks of `members` become
        `resolve_printing`'s `group_card_ids`, so a partial `members` is rejected by
        `_require_full_identity_group` on the line below, BEFORE anything is written. That
        matters twice over here: a narrowed `members` would not only compute a different tally,
        it would also persist the result to only part of the group, leaving siblings on a stale
        `printing_tag_status` and putting the group into exactly the self-disagreeing state
        ruling 1 says must be impossible by construction.
      - IDENTITY (`card` itself present, not a freshly-fetched equal-pk copy) is checked here,
        at no query cost, since the pk-level check above cannot see it. Substituting a copy
        leaves this function writing through a different instance from the one the caller holds
        and will read `printing_tag_status` off afterwards - the caller silently strands on a
        stale status, which is the failure the `identity_group_cards` docstring already warns
        about and which nothing verified until now.

    Also pushes each written card into Elasticsearch, but only when the outcome actually changes
    what's indexed for THAT card (see `_effective_indexed_printing_id`) - entering RESOLVED,
    leaving RESOLVED (contested/unresolved again after new votes), or the resolved printing
    itself changing while remaining RESOLVED. A re-resolve that lands on the same outcome as
    before (the common case whenever this runs against a card that already has a settled
    consensus) does not touch the index; the per-member gate means propagating an unchanged
    outcome across a group reindexes only the members that were actually out of step. The push
    itself is failure-isolated (`reindex_card_safely`) - an ES hiccup is logged, never raised;
    this function's own DB write has already committed by that point regardless.

    Members are WRITTEN in pk order (not in the caller-first order they arrive in), so two
    concurrent votes landing on two different members of the same group take that group's row
    locks in the same order and queue behind each other instead of deadlocking. For a group of
    one this is the same single write, in the same place, it always was.
    """
    group_cards = list(members) if members is not None else identity_group_cards(card)
    if members is not None and not any(member is card for member in group_cards):
        # identity, not `card.pk in {m.pk for m in group_cards}`: an equal-pk COPY is precisely
        # the case this rejects (see the `members` paragraph above). Completeness is left to
        # `resolve_printing`'s own guard on the next line rather than re-derived here.
        raise ValueError(
            f"`members` must contain the caller's own `card` instance (pk {card.pk}) itself, "
            "unreplaced - see `identity_group_cards`, whose output this expects. A freshly-fetched "
            "copy of the same row has the same pk but is a different object: this function would "
            "write the resolution through the copy, leaving the caller's `card` on a stale "
            "`printing_tag_status`/`inferred_canonical_card` with nothing to indicate it."
        )
    result = resolve_printing(card, group_card_ids=[member.pk for member in group_cards])

    for member in sorted(group_cards, key=lambda group_card: group_card.pk):
        prior_status = member.printing_tag_status
        prior_printing_id = member.inferred_canonical_card_id
        prior_effective = _effective_indexed_printing_id(prior_status, prior_printing_id)

        if result is None:
            member.inferred_canonical_card = None
            member.printing_tag_status = PrintingTagStatus.UNRESOLVED
        elif result == NO_MATCH:
            member.inferred_canonical_card = None
            member.printing_tag_status = PrintingTagStatus.NO_MATCH
        else:
            member.inferred_canonical_card = result
            member.printing_tag_status = PrintingTagStatus.RESOLVED
        member.save(update_fields=["inferred_canonical_card", "printing_tag_status"])

        new_effective = _effective_indexed_printing_id(member.printing_tag_status, member.inferred_canonical_card_id)
        if new_effective != prior_effective:
            from cardpicker.documents import (
                reindex_card_safely,  # local import - avoids a top-level ES dependency in this module
            )

            reindex_card_safely(member)

    return result


class VoteTallyEntry(TypedDict):
    printing: CanonicalCard | None
    is_no_match: bool
    count: int


def get_contested_card_ids() -> list[int]:
    """
    IDs of cards with conflicting printing-tag votes on record: more than one distinct
    printing voted for, or both a printing vote and a no-match vote. Coarser than
    `resolve_printing` (a card can show as contested here yet still resolve if one side
    dominates on weight), but avoids running the full consensus calculation per card for
    a queue/triage ordering. Shared between the admin's contested-card filter and the
    "What's That Card?" queue, which defaults to surfacing contested cards first.
    Materialized to a plain list (rather than returning the lazy QuerySet) since the set of
    actually-contested cards is always a small fraction of the total - cheap to evaluate
    eagerly, and sidesteps django-stubs' QuerySet generic entirely for callers.

    Delegates to the shared `vote_consensus.contested_queryset` - this function's name,
    signature, and behavior are unchanged; it's the reference point that function's own
    docstring calls "behavior-preserving".
    """
    return contested_queryset(
        CardPrintingTag.objects.all(), group_by="card_id", outcome_field="printing_id", sentinel_field="is_no_match"
    )


def get_vote_tally(card: Card) -> list[VoteTallyEntry]:
    """
    Returns a plain, unweighted per-outcome vote count for `card` - e.g. "3 votes for
    Ravnica Allegiance #45, 1 for no match" - for showing a voter what's been said so far
    before they confirm or dispute it. Deliberately doesn't weight by source the way
    `resolve_printing` does: this is for display, not for deciding the outcome.
    """
    tally: dict[int | Literal["NO_MATCH"] | None, VoteTallyEntry] = {}
    for vote in card.printing_tags.all():
        key: int | Literal["NO_MATCH"] | None = NO_MATCH if vote.is_no_match else vote.printing_id
        if key not in tally:
            tally[key] = VoteTallyEntry(printing=vote.printing, is_no_match=vote.is_no_match, count=0)
        tally[key]["count"] += 1
    return sorted(tally.values(), key=lambda entry: entry["count"], reverse=True)
