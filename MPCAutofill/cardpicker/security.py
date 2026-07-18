"""
Request-level security decorators for the moderation layer (docs/features/moderation.md).

Why these exist instead of Django's CSRF machinery: every API endpoint here is (and stays)
`@csrf_exempt`, because the primary clients are anonymous cross-origin browsers that never
receive a Django CSRF cookie - there is no token to round-trip, and votes are keyed by a
client-generated anonymous_id rather than a session. That was perfectly safe while nothing
read `request.user`. The moderation layer changes that: some POSTs now *consume a session*
(a moderator's SameSite=None cookie), which classic CSRF exploits - any website could forge
a privileged approve/reject from a logged-in moderator's browser.

`reject_untrusted_origin` closes exactly that hole: browsers unconditionally attach an
`Origin` header to cross-origin POSTs (fetch and form submissions alike) and a page cannot
forge it, so rejecting POSTs whose Origin is present-but-untrusted blocks browser-based
forgery while leaving non-browser clients (no Origin header at all - curl, scripts, the
desktop tool) at exactly today's trust level. GET endpoints (e.g. whoami) don't need it:
they change no state, and CORS already prevents untrusted pages from reading responses.
"""

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from cardpicker.moderation import is_moderator
from cardpicker.schema_types import ErrorResponse

F = TypeVar("F", bound=Callable[..., Any])


def _trusted_origins(request: HttpRequest) -> set[str]:
    # the CORS allowlist, plus this backend's own origin (same-origin browser POSTs - e.g.
    # anything served from the backend host itself - also carry an Origin header)
    return set(settings.CORS_ALLOWED_ORIGINS) | {f"{request.scheme}://{request.get_host()}"}


def reject_untrusted_origin(view: F) -> F:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        origin = request.headers.get("Origin")
        if request.method == "POST" and origin is not None and origin not in _trusted_origins(request):
            error = ErrorResponse(
                name="Untrusted origin", message="This origin is not allowed to submit to this endpoint."
            )
            return JsonResponse(error.model_dump(), status=403)
        return view(request, *args, **kwargs)

    return cast(F, wrapper)


def require_moderator(view: F) -> F:
    """
    403 unless the requesting session belongs to a member of the moderators group (see
    cardpicker.moderation.is_moderator). This is the actual enforcement behind the frontend's
    moderation tab - hiding the tab is presentation, this is security. Deliberately 403 (not
    a redirect): the API is consumed cross-origin by fetch, never navigated to.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not is_moderator(request.user):
            error = ErrorResponse(name="Moderator access required", message="This endpoint is for moderators only.")
            return JsonResponse(error.model_dump(), status=403)
        return view(request, *args, **kwargs)

    return cast(F, wrapper)


def require_authenticated(view: F) -> F:
    """
    403 unless the requesting session belongs to a logged-in user - strictly weaker than
    require_moderator (every moderator is authenticated, not every authenticated user is a
    moderator). Backs the saved-decks endpoints
    (docs/proposals/proposal-g-user-accounts-saved-decks.md §3/§8) - "is this deck's owner the
    requesting session's user" is enforced per-object inside each view, not here; this decorator
    only proves *a* real account is behind the request at all.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            error = ErrorResponse(name="Sign-in required", message="This endpoint requires a signed-in account.")
            return JsonResponse(error.model_dump(), status=403)
        return view(request, *args, **kwargs)

    return cast(F, wrapper)


__all__ = ["reject_untrusted_origin", "require_moderator", "require_authenticated"]
