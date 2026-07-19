/**
 * The display page rail's Artist accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Inherits
 * ArtistSupportLink directly, exactly as docs/features/artist-support-links.md's own "not built
 * in v1" note anticipated this surface would once built - same precedence chain/gating as the
 * Card Detail Modal's "Canonical Aritst" row: a confirmed cardDocument.canonicalArtist renders
 * the link, a null one renders "Unknown" plain text, never a link with nothing to point at.
 */
import React from "react";

import { CardDocument } from "@/common/types";
import { ArtistSupportLink } from "@/components/ArtistSupportLink";

interface ArtistSectionProps {
  cardDocument: CardDocument | undefined;
}

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
        <span>
          Art by{" "}
          <ArtistSupportLink artistName={cardDocument.canonicalArtist.name}>
            {cardDocument.canonicalArtist.name}
          </ArtistSupportLink>
        </span>
      ) : (
        <span className="text-muted">Unknown</span>
      )}
    </div>
  );
}
