from typing import Literal, TypedDict

from django.conf import settings

from cardpicker.models import ArtistVoteStatus, CanonicalArtist, Card, VoteSource
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    VoteTuple,
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
                is_human_backed=vote.source != VoteSource.AI,
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
    """
    result = resolve_artist(card)
    if result is None:
        card.inferred_canonical_artist = None
        card.artist_vote_status = ArtistVoteStatus.UNRESOLVED
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


__all__ = ["UNKNOWN", "resolve_artist", "resolve_and_persist_artist", "get_artist_vote_tally", "ArtistVoteTallyEntry"]
