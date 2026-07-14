from urllib.parse import urlparse

from allauth.account.adapter import DefaultAccountAdapter

from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme


class FrontendRedirectAccountAdapter(DefaultAccountAdapter):
    """
    The frontend is a static export on a different origin from this API (e.g.
    proxyprints.ca / proxyprints.github.io vs. api.proxyprints.ca), so login/logout links
    carry `?next=<full frontend URL>` to round-trip the user back to the page they came
    from. Stock allauth only considers same-host redirects safe; this adapter additionally
    trusts exactly the origins CORS already trusts (`CORS_ALLOWED_ORIGINS`), so the two
    allowlists can't drift apart.
    """

    def is_safe_url(self, url: str | None) -> bool:
        if super().is_safe_url(url):
            return True
        frontend_hosts = {urlparse(origin).netloc for origin in settings.CORS_ALLOWED_ORIGINS}
        # require_https=False because the localhost dev origins are plain http - the explicit
        # host allowlist is the actual control here.
        return url_has_allowed_host_and_scheme(url, allowed_hosts=frontend_hosts, require_https=False)
