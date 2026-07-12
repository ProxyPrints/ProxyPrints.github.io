from collections import defaultdict
from typing import Iterable, TypedDict

from django.conf import settings

from cardpicker.models import Card, CardTagVote, Tag, VotePolarity, VoteSource
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
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
    """
    from cardpicker.documents import (
        CardSearch,  # local import - avoids a top-level ES dependency in this module
    )

    voted_tag_ids = list(card.tag_votes.values_list("tag_id", flat=True).distinct())
    if not voted_tag_ids:
        return

    tags_by_id = {tag.pk: tag for tag in Tag.objects.filter(pk__in=voted_tag_ids)}
    current_tags = set(card.tags)
    changed = False
    for tag_id, tag in tags_by_id.items():
        resolved = resolve_tag(card, tag)
        if resolved == VotePolarity.APPLY and tag.name not in current_tags:
            current_tags.add(tag.name)
            changed = True
        elif resolved == VotePolarity.NOT_APPLICABLE and tag.name in current_tags:
            current_tags.discard(tag.name)
            changed = True

    if changed:
        card.tags = sorted(current_tags)
        card.save(update_fields=["tags"])
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


__all__ = [
    "resolve_tag",
    "resolve_and_persist_tag_votes",
    "get_tag_vote_tally",
    "get_resolved_tag_overlay",
    "TagVoteTallyEntry",
]
