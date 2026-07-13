from collections import defaultdict, deque
from typing import Iterable, TypedDict

from django.conf import settings

from cardpicker.models import (
    Card,
    CardTagVote,
    Tag,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
    contested_queryset,
    resolve_weighted_consensus,
)


def resolve_tag(card: Card, tag: Tag) -> int | None:
    """
    Reconciles all `CardTagVote` votes cast for (card, tag) into a single resolved polarity
    (`VotePolarity.APPLY` or `VotePolarity.NOT_APPLICABLE`), or `None` if unresolved. Built on
    the same shared `resolve_weighted_consensus` core as printing/artist consensus - the only
    difference is the outcome space is the two `VotePolarity` values rather than a printing or
    artist id.
    """
    votes = list(card.tag_votes.filter(tag=tag))
    if not votes:
        return None
    vote_tuples = [
        VoteTuple(
            outcome_key=vote.polarity,
            weight=_SOURCE_WEIGHTS[vote.source],
            is_human_backed=vote.source != VoteSource.AI,
        )
        for vote in votes
    ]
    resolved = resolve_weighted_consensus(
        vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
    )
    if resolved is None:
        return None
    assert isinstance(resolved, int)
    return resolved


def resolve_and_persist_tag_votes(card: Card) -> None:
    """
    Resolves consensus for every tag that has at least one vote cast against `card` (tags are
    multi-valued per card, unlike printing/artist, so this resolves all of them in one pass
    rather than a single outcome), and merges the result directly into `card.tags`: a resolved
    APPLY adds the tag name if not already present; a resolved NOT_APPLICABLE removes it if
    present. Saves `card.tags` and pushes the change into Elasticsearch immediately - unlike
    printing/artist consensus (whose denormalised fields aren't ES-indexed), `tags` *is* an
    ES-indexed field (`documents.py`'s `KeywordField`), so a vote-triggered change has to reach
    the search index directly rather than waiting for the next scheduled re-scan.

    Also writes `card.tag_vote_statuses` (a JSONField, not ES-indexed, so no re-index needed
    for this part alone): for every voted tag, one of RESOLVED_APPLY/RESOLVED_REJECT/CONTESTED/
    UNRESOLVED. CONTESTED vs. UNRESOLVED is distinguished locally from the polarities already
    fetched below (no extra query) - contested means both polarities are present with votes;
    unresolved means only one side has voted so far, or thresholds simply aren't cleared yet.
    """
    from cardpicker.documents import (
        CardSearch,  # local import - avoids a top-level ES dependency in this module
    )

    votes_by_tag_id: dict[int, set[int]] = defaultdict(set)
    for tag_id, polarity in card.tag_votes.values_list("tag_id", "polarity"):
        votes_by_tag_id[tag_id].add(polarity)
    if not votes_by_tag_id:
        return

    tags_by_id = {tag.pk: tag for tag in Tag.objects.filter(pk__in=votes_by_tag_id.keys())}
    current_tags = set(card.tags)
    statuses = dict(card.tag_vote_statuses)
    tags_changed = False
    statuses_changed = False
    for tag_id, tag in tags_by_id.items():
        resolved = resolve_tag(card, tag)
        if resolved == VotePolarity.APPLY:
            new_status = TagVoteStatus.RESOLVED_APPLY
            if tag.name not in current_tags:
                current_tags.add(tag.name)
                tags_changed = True
        elif resolved == VotePolarity.NOT_APPLICABLE:
            new_status = TagVoteStatus.RESOLVED_REJECT
            if tag.name in current_tags:
                current_tags.discard(tag.name)
                tags_changed = True
        else:
            new_status = TagVoteStatus.CONTESTED if len(votes_by_tag_id[tag_id]) > 1 else TagVoteStatus.UNRESOLVED
        if statuses.get(tag.name) != new_status:
            statuses[tag.name] = new_status
            statuses_changed = True

    update_fields = []
    if tags_changed:
        card.tags = sorted(current_tags)
        update_fields.append("tags")
    if statuses_changed:
        card.tag_vote_statuses = statuses
        update_fields.append("tag_vote_statuses")
    if update_fields:
        card.save(update_fields=update_fields)
        if tags_changed:
            CardSearch().update([card], action="index")


class TagVoteTallyEntry(TypedDict):
    polarity: int
    count: int


def get_tag_vote_tally(card: Card, tag: Tag) -> list[TagVoteTallyEntry]:
    """Plain, unweighted per-polarity vote count for (card, tag) - mirrors `get_vote_tally`."""
    tally: dict[int, int] = defaultdict(int)
    for vote in card.tag_votes.filter(tag=tag):
        tally[vote.polarity] += 1
    return sorted(
        (TagVoteTallyEntry(polarity=polarity, count=count) for polarity, count in tally.items()),
        key=lambda entry: entry["count"],
        reverse=True,
    )


def get_resolved_tag_overlay(card_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    """
    Batched version of `resolve_tag`, computed for every (card, tag) pair with at least one
    vote among `card_ids` in a single query - returns `{card_id: {tag_name: resolved_polarity}}`.

    Used by `cardpicker.sources.update_database.bulk_sync_objects` to merge consensus
    corrections into freshly re-scanned `Card.tags` before they're written, so a scheduled
    re-scan can never silently revert a resolved tag-vote correction back to whatever the
    filename currently says.
    """
    rows = CardTagVote.objects.filter(card_id__in=card_ids).values(
        "card_id", "tag_id", "tag__name", "source", "polarity"
    )
    grouped: dict[tuple[int, int], list[VoteTuple]] = defaultdict(list)
    tag_names: dict[int, str] = {}
    for row in rows:
        tag_names[row["tag_id"]] = row["tag__name"]
        grouped[(row["card_id"], row["tag_id"])].append(
            VoteTuple(
                outcome_key=row["polarity"],
                weight=_SOURCE_WEIGHTS[row["source"]],
                is_human_backed=row["source"] != VoteSource.AI,
            )
        )

    overlay: dict[int, dict[str, int]] = defaultdict(dict)
    for (card_id, tag_id), vote_tuples in grouped.items():
        resolved = resolve_weighted_consensus(
            vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
        )
        if resolved is not None:
            assert isinstance(resolved, int)
            overlay[card_id][tag_names[tag_id]] = resolved
    return dict(overlay)


def get_contested_tag_pairs() -> list[tuple[int, int]]:
    """
    (card_id, tag_id) pairs with conflicting tag votes on record - both polarities present.
    Mirrors `cardpicker.printing_consensus.get_contested_card_ids`'s shape, generalized via
    `vote_consensus.contested_queryset`. Unlike printing/artist, tags have no sentinel outcome
    (polarity only ever takes two values), so "contested" here just means both are present.
    """
    return contested_queryset(CardTagVote.objects.all(), group_by=["card_id", "tag_id"], outcome_field="polarity")


def get_tag_review_queue_pairs() -> list[tuple[int, str]]:
    """
    (card_id, tag_name) pairs still needing review for the tag-mode vote queue, backing
    `POST 2/voteQueue/?kind=tag`.

    Candidate set is the *persisted* `Card.tag_vote_statuses` state (CONTESTED/UNRESOLVED
    entries), not raw `CardTagVote` existence - so a pair that's already resolved
    (RESOLVED_APPLY/RESOLVED_REJECT) stays out of the queue even as unrelated new votes trickle
    in on the same card afterwards. `tag_vote_statuses` is a small per-card JSON dict with no
    native per-key DB filter for "any key has value X", so this materializes candidates eagerly
    in Python - same rationale as `vote_consensus.contested_queryset`: the candidate set is
    always a small fraction of the catalogue.

    Ordering: primarily by ascending absolute net polarity weight (a 5-vs-4 split outranks a
    6-vs-1 split - closest contests first), then interleaved by card_id (round-robin across
    each card's own items, preserving each card's internal relative order) so the same card
    isn't served back-to-back for different tags when a different card's item could go in
    between instead.
    """
    candidates: list[tuple[int, str]] = [
        (card_id, tag_name)
        for card_id, statuses in Card.objects.exclude(tag_vote_statuses={}).values_list("id", "tag_vote_statuses")
        for tag_name, status in statuses.items()
        if status in (TagVoteStatus.CONTESTED, TagVoteStatus.UNRESOLVED)
    ]
    if not candidates:
        return []

    card_ids = {card_id for card_id, _ in candidates}
    rows = CardTagVote.objects.filter(card_id__in=card_ids).values("card_id", "tag__name", "source", "polarity")
    net_weight: dict[tuple[int, str], float] = defaultdict(float)
    for row in rows:
        net_weight[(row["card_id"], row["tag__name"])] += row["polarity"] * _SOURCE_WEIGHTS[row["source"]]
    candidates.sort(key=lambda pair: abs(net_weight.get(pair, 0.0)))

    grouped: dict[int, deque[tuple[int, str]]] = defaultdict(deque)
    group_order: list[int] = []
    for pair in candidates:
        card_id = pair[0]
        if card_id not in grouped:
            group_order.append(card_id)
        grouped[card_id].append(pair)
    interleaved: list[tuple[int, str]] = []
    remaining = list(group_order)
    while remaining:
        for card_id in list(remaining):
            interleaved.append(grouped[card_id].popleft())
            if not grouped[card_id]:
                remaining.remove(card_id)
    return interleaved


__all__ = [
    "resolve_tag",
    "resolve_and_persist_tag_votes",
    "get_tag_vote_tally",
    "get_resolved_tag_overlay",
    "get_contested_tag_pairs",
    "get_tag_review_queue_pairs",
    "TagVoteTallyEntry",
]
