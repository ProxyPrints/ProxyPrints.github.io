/**
 * The display page rail's Artist accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Same precedence
 * chain/gating as the Card Detail Modal's "Canonical Aritst" row: a confirmed
 * cardDocument.canonicalArtist renders the applet, a null one renders "Unknown" plain text,
 * never a link with nothing to point at.
 *
 * M2 round (docs/features/artist-support-links.md): `ArtistSupportLink` is now a self-contained
 * applet (RTK Query fetch, commerce-link buttons, the Mark's Signature Service badge, the MTGAC
 * page link, the MTGAC credit line) rather than a single caller-styled `<a>` wrapping caller-
 * supplied `children` - this caller no longer passes `className`/children for button styling,
 * the applet owns its own layout ("buttons stretch to fill the applet", owner instruction). The
 * applet's own page-link button already names the artist, so this caller renders no separate
 * name label alongside it (issue #747).
 *
 * Upstream-divergence note (docs/upstreaming/readiness-audit.md's styling-divergence ledger):
 * chilli-axe/mpc-autofill has no artist-support surface at all - ArtistSupportLink is a
 * fork-only feature, additive, upstreamable independently.
 */
import React from "react";

import { CardDocument } from "@/common/types";
import { ArtistSupportLink } from "@/components/ArtistSupportLink";

interface ArtistSectionProps {
  cardDocument: CardDocument | undefined;
}

// diverges from upstream: chilli-axe/mpc-autofill has no artist-support surface at all
// (ArtistSupportLink is a fork-only feature, additive, upstreamable independently).
export function ArtistSection({ cardDocument }: ArtistSectionProps) {
  if (cardDocument == null) {
    return (
      <p className="text-muted small mb-0">
        Select an image for this slot first.
      </p>
    );
  }

  return (
    <div data-testid="display-artist-section">
      {cardDocument.canonicalArtist != null ? (
        <ArtistSupportLink
          artistName={cardDocument.canonicalArtist.name}
          defaultExpanded
        />
      ) : (
        <span className="text-muted">Unknown</span>
      )}
    </div>
  );
}
