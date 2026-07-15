from typing import Literal, TypedDict

from django.conf import settings

from cardpicker.models import ArtistVoteStatus, CanonicalArtist, Card, CardArtistVote
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
    contested_queryset,
    is_human_backed_source,
    resolve_weighted_consensus,
)

UNKNOWN: Literal["UNKNOWN"] = "UNKNOWN"


def resolve_artist(card: Card) -> CanonicalArtist | Literal["UNKNOWN"] | None:
    """
    Reconciles all `CardArtistVote` votes cast against `card` into a single resolved outcome:
    a specific `CanonicalArtist`, the `UNKNOWN` sentinel (consensus is that the artist is
    unlisted/unidentifiable), or `None` if there isn't yet enough signal. Mirrors
    `cardpicker.printing_consensus.resolve_printing` exactly, built on the same shared
    `resolve_weighted_consensus` core.

    Note this outcome is only ever surfaced to a viewer when the card's printing-tag
    consensus *hasn't* resolved a printing - see the artist fallback chain in
    `Card.serialise()`, where a resolved printing's own artist always takes precedence.
    """
    votes = list(card.artist_votes.all())
    if not votes:
        return None

    artists_by_id: dict[int, CanonicalArtist] = {}
    vote_tuples: list[VoteTuple] = []
    for vote in votes:
        key: int | Literal["UNKNOWN"]
        if vote.is_unknown:
            key = UNKNOWN
        else:
            # guaranteed non-null here by the model's artist_xor_unknown CheckConstraint
            assert vote.artist_id is not None
            assert vote.artist is not None
            key = vote.artist_id
            artists_by_id[vote.artist_id] = vote.artist
        vote_tuples.append(
            VoteTuple(
                outcome_key=key,
                weight=_SOURCE_WEIGHTS[vote.source],
                is_human_backed=is_human_backed_source(vote.source),
            )
        )

    winning_key = resolve_weighted_consensus(
        vote_tuples, min_weight=settings.PRINTING_TAG_MIN_VOTES, min_share=settings.PRINTING_TAG_MIN_SHARE
    )
    if winning_key is None:
        return None
    if winning_key == UNKNOWN:
        return UNKNOWN
    assert isinstance(winning_key, int)
    return artists_by_id[winning_key]


def resolve_and_persist_artist(card: Card) -> CanonicalArtist | Literal["UNKNOWN"] | None:
    """
    Runs `resolve_artist(card)` and writes the outcome onto `card.inferred_canonical_artist`
    and `card.artist_vote_status` together - same pattern as
    `cardpicker.printing_consensus.resolve_and_persist_printing`. Deliberately doesn't consult
    `card.printing_tag_status` at all: the precedence rule ("a resolved printing's artist wins")
    is enforced entirely by `Card.serialise()`'s fallback chain, not here, so this function
    stays decoupled from printing-tag state.

    When unresolved, additionally distinguishes `CONTESTED` (more than one distinct outcome
    has votes) from plain `UNRESOLVED` (not enough votes yet to conclude anything) - a second,
    lightweight query, only taken on this branch, so the common resolved case pays nothing
    extra for it.
    """
    result = resolve_artist(card)
    if result is None:
        distinct_outcomes = {
            UNKNOWN if is_unknown else artist_id
            for is_unknown, artist_id in card.artist_votes.values_list("is_unknown", "artist_id")
        }
        card.inferred_canonical_artist = None
        card.artist_vote_status = (
            ArtistVoteStatus.CONTESTED if len(distinct_outcomes) > 1 else ArtistVoteStatus.UNRESOLVED
        )
    elif result == UNKNOWN:
        card.inferred_canonical_artist = None
        card.artist_vote_status = ArtistVoteStatus.UNKNOWN
    else:
        card.inferred_canonical_artist = result
        card.artist_vote_status = ArtistVoteStatus.RESOLVED
    card.save(update_fields=["inferred_canonical_artist", "artist_vote_status"])
    return result


class ArtistVoteTallyEntry(TypedDict):
    artist: CanonicalArtist | None
    is_unknown: bool
    count: int


def get_artist_vote_tally(card: Card) -> list[ArtistVoteTallyEntry]:
    """
    Plain, unweighted per-outcome vote count for `card` - mirrors
    `cardpicker.printing_consensus.get_vote_tally`, for showing a voter what's already been
    said before they confirm or dispute it.
    """
    tally: dict[int | Literal["UNKNOWN"], ArtistVoteTallyEntry] = {}
    for vote in card.artist_votes.all():
        key: int | Literal["UNKNOWN"]
        if vote.is_unknown:
            key = UNKNOWN
        else:
            assert vote.artist_id is not None
            key = vote.artist_id
        if key not in tally:
            tally[key] = ArtistVoteTallyEntry(artist=vote.artist, is_unknown=vote.is_unknown, count=0)
        tally[key]["count"] += 1
    return sorted(tally.values(), key=lambda entry: entry["count"], reverse=True)


def get_contested_artist_card_ids() -> list[int]:
    """
    IDs of cards with conflicting artist votes on record - mirrors
    `cardpicker.printing_consensus.get_contested_card_ids` exactly, generalized via
    `vote_consensus.contested_queryset`. See that function's docstring for what "contested"
    means here and why this is a cheap proxy, not a full consensus recomputation.
    """
    return contested_queryset(
        CardArtistVote.objects.all(), group_by="card_id", outcome_field="artist_id", sentinel_field="is_unknown"
    )


__all__ = [
    "UNKNOWN",
    "resolve_artist",
    "resolve_and_persist_artist",
    "get_artist_vote_tally",
    "get_contested_artist_card_ids",
    "ArtistVoteTallyEntry",
]
