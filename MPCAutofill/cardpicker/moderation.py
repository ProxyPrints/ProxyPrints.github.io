"""
Moderator-role helpers for the moderation layer (see docs/features/moderation.md).

"Moderator" is defined as membership of the `settings.MODERATORS_GROUP_NAME` auth group -
deliberately the only place that definition lives. Logging in (via Discord/allauth) grants
nothing by itself; an admin adds users to the group as a one-time action. Keeping the
grant mechanism behind these two functions means a future alternative (e.g. syncing group
membership from a Discord guild role, for a federation-wide moderator roster) changes how
the group is *populated* without touching any consumer.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser, AnonymousUser, User


def get_moderator_user_ids() -> set[int]:
    """
    The user ids of every member of the moderators group, in one query. Consensus code
    resolving many votes calls this once and shares the set, rather than querying group
    membership per vote.
    """
    return set(User.objects.filter(groups__name=settings.MODERATORS_GROUP_NAME).values_list("id", flat=True))


def is_moderator(user: AbstractUser | AnonymousUser) -> bool:
    if not isinstance(user, AbstractUser):
        return False
    return user.groups.filter(name=settings.MODERATORS_GROUP_NAME).exists()


def is_privileged_vote(source: str, user_id: int | None, moderator_ids: set[int]) -> bool:
    """
    Whether a vote carries elevated moderation authority - the `is_privileged` input to
    `cardpicker.vote_consensus.VoteTuple`. Admin-sourced votes are privileged by definition;
    user votes are privileged when their recorded `user` is currently in the moderators group
    (`moderator_ids` = `get_moderator_user_ids()`, fetched once by the caller and shared
    across a whole resolution pass). Membership is checked at resolution time, not stored on
    the vote, so revoking a moderator retroactively de-privileges every vote they cast.
    """
    from cardpicker.models import (
        VoteSource,  # local import - avoids a models<->moderation import cycle
    )

    return source == VoteSource.ADMIN or (user_id is not None and user_id in moderator_ids)


def privileged_weight(source: str, privileged: bool) -> float:
    """
    The weight a vote contributes to `resolve_weighted_consensus`, accounting for privilege:
    a privileged vote weighs at least `VOTE_PRIVILEGED_WEIGHT` (default = the admin weight,
    so a lone moderator clears the consensus threshold like a lone admin does), via max() so
    an admin-sourced vote is never *down*-weighted by this.
    """
    from cardpicker.vote_consensus import _SOURCE_WEIGHTS

    base: float = _SOURCE_WEIGHTS[source]
    if privileged:
        return max(base, float(settings.VOTE_PRIVILEGED_WEIGHT))
    return base


__all__ = ["get_moderator_user_ids", "is_moderator", "is_privileged_vote", "privileged_weight"]
