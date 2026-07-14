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


__all__ = ["get_moderator_user_ids", "is_moderator"]
