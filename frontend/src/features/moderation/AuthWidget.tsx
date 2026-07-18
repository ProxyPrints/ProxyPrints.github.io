/**
 * Sign-in/sign-out links, mounted in the navbar on every page (see
 * docs/proposals/proposal-g-user-accounts-saved-decks.md decision 6 - relocated here from
 * the /whatsthat-only mount it used to have, back when only moderators needed it, see
 * docs/features/moderation.md). Ordinary voters never see anything if the backend hasn't
 * configured Discord auth - the whole widget renders nothing unless the backend reports it's
 * enabled (and also on any whoami error, so pointing the frontend at a third-party backend
 * without credentialed CORS degrades to exactly today's UI rather than surfacing an error).
 *
 * The button reads "Sign in" (benefit-framed via its title tooltip), not "Sign in with
 * Discord" - Discord is presented as the *method*, surfaced at the auth step itself (allauth's
 * own login/consent redirect), never baked into the label. Ships Discord-only in v1; the
 * label is deliberately provider-agnostic so a second provider (see docs/proposals/
 * proposal-g-user-accounts-saved-decks.md §1's provider mechanism note) is a backend-only
 * change later, not a copy change here too.
 *
 * The links round-trip: they point at the backend's allauth routes with
 * `?next=<current frontend URL>`, which the backend's account adapter validates against the
 * same origin allowlist CORS uses (see accounts/adapter.py).
 */

import styled from "@emotion/styled";
import React, { useEffect, useState } from "react";

import { useAppSelector } from "@/common/types";
import { useGetWhoamiQuery } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";

// Discord's brand blurple (https://discord.com/branding) and its documented hover shade -
// this button follows their "Log in with Discord" usage guidance (solid blurple pill, white
// wordmark, the Clyde glyph on the left) rather than inventing our own login-button styling.
const DISCORD_BLURPLE = "#5865F2";
const DISCORD_BLURPLE_HOVER = "#4752C4";

const DiscordButton = styled.a`
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: ${DISCORD_BLURPLE};
  color: white;
  font-weight: 600;
  font-size: 0.9rem;
  line-height: 1;
  padding: 0.5rem 0.9rem;
  border-radius: 0.3rem;
  text-decoration: none;
  &:hover,
  &:focus {
    background-color: ${DISCORD_BLURPLE_HOVER};
    color: white;
    text-decoration: none;
  }
`;

// Discord's "Clyde" glyph mark - a widely-reused, brand-guideline-compliant path (the same
// one Discord's own asset kit and most third-party "Log in with Discord" buttons ship), not
// project-specific artwork. currentColor so it matches the button's white text.
function DiscordIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.0991.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.522 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
    </svg>
  );
}

const StatusRow = styled.p`
  display: flex;
  align-items: center;
  gap: 0.6rem;
`;

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
  return whoami.data.authenticated ? (
    <StatusRow className="small m-0" data-testid="auth-widget">
      <span>
        Signed in as <b>{whoami.data.username}</b>
        {whoami.data.moderator && " (moderator)"}
      </span>
      <a
        href={`${backendURL}${whoami.data.logoutUrl}${next}`}
        data-testid="auth-widget-logout"
      >
        Sign out
      </a>
    </StatusRow>
  ) : (
    <DiscordButton
      href={`${backendURL}${whoami.data.loginUrl}${next}`}
      title="Sign in to save decks & track your confirmations"
      data-testid="auth-widget-login"
    >
      <DiscordIcon />
      Sign in
    </DiscordButton>
  );
}
