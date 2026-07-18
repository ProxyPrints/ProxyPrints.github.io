/**
 * Artist Support Links v1 - a zero-crawl link-out to MTG Artist Connection (a community-
 * maintained MTG artist directory, not affiliated with this project or its operator). See
 * docs/features/artist-support-links.md for the full design rationale.
 *
 * The href is built entirely deterministically from the artist's display name - no per-artist
 * database, no crawling, and by design no existence check: MTG Artist Connection is a
 * client-rendered SPA where every route (including ones for artists it doesn't know) returns
 * HTTP 200, so a status-based "does this link resolve to something real?" check is structurally
 * meaningless there, not just skipped for convenience. An artist not actually in their directory
 * lands on their own graceful in-app "No artist found" page - accepted v1 behaviour, not a
 * broken link from this project's own perspective.
 *
 * Callers are responsible for only rendering this once the artist name is confirmed/known (the
 * same precedence chain the backend's Card.serialise exposes via `canonicalArtist`, or a vote
 * the user just cast themselves) - never for a vote-pending/unknown artist, since there would be
 * no name to build a URL from in the first place.
 */
import React from "react";

import { MTGArtistConnection, MTGArtistConnectionArtistBaseURL } from "@/common/constants";
import { Icon } from "@/components/icon";

export function buildArtistSupportURL(artistName: string): string {
  return `${MTGArtistConnectionArtistBaseURL}${encodeURIComponent(artistName)}`;
}

interface ArtistSupportLinkProps {
  artistName: string;
  className?: string;
  children: React.ReactNode;
}

export function ArtistSupportLink({
  artistName,
  className,
  children,
}: ArtistSupportLinkProps) {
  return (
    <a
      href={buildArtistSupportURL(artistName)}
      target="_blank"
      rel="noopener noreferrer"
      title={`via ${MTGArtistConnection}`}
      className={className}
      data-testid="artist-support-link"
    >
      {children} <Icon bootstrapIconName="box-arrow-up-right" />
    </a>
  );
}
