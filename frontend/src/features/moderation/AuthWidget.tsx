/**
 * Discord login/logout links for moderators (docs/features/moderation.md), rendered on the
 * vote-queue page. Ordinary voters never need this - the whole widget renders nothing unless
 * the backend reports Discord auth is configured (and also on any whoami error, so pointing
 * the frontend at a third-party backend without credentialed CORS degrades to exactly the
 * pre-moderation UI rather than surfacing an error).
 *
 * The links round-trip: they point at the backend's allauth routes with
 * `?next=<current frontend URL>`, which the backend's account adapter validates against the
 * same origin allowlist CORS uses (see accounts/adapter.py).
 */

import React, { useEffect, useState } from "react";

import { useAppSelector } from "@/common/types";
import { useGetWhoamiQuery } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";

export function AuthWidget() {
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const whoami = useGetWhoamiQuery();
  // window isn't available during the static export build - resolve the return URL on the
  // client only
  const [currentHref, setCurrentHref] = useState<string | null>(null);
  useEffect(() => {
    setCurrentHref(window.location.href);
  }, []);

  if (
    backendURL == null ||
    whoami.isError ||
    whoami.data == null ||
    !whoami.data.discordEnabled ||
    currentHref == null
  ) {
    return null;
  }

  const next = `?next=${encodeURIComponent(currentHref)}`;
  return (
    <p className="small" data-testid="auth-widget">
      {whoami.data.authenticated ? (
        <>
          Signed in as <b>{whoami.data.username}</b>
          {whoami.data.moderator && " (moderator)"} ·{" "}
          <a
            href={`${backendURL}${whoami.data.logoutUrl}${next}`}
            data-testid="auth-widget-logout"
          >
            Sign out
          </a>
        </>
      ) : (
        <a
          href={`${backendURL}${whoami.data.loginUrl}${next}`}
          data-testid="auth-widget-login"
        >
          Moderator login (Discord)
        </a>
      )}
    </p>
  );
}
