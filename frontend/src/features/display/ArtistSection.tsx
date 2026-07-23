/**
 * The display page rail's Artist accordion section (Proposal H pane migration, left-panel
 * unification - docs/proposals/proposal-h-unified-display-page.md §5). Inherits
 * ArtistSupportLink directly, exactly as docs/features/artist-support-links.md's own "not built
 * in v1" note anticipated this surface would once built - same precedence chain/gating as the
 * Card Detail Modal's "Canonical Aritst" row: a confirmed cardDocument.canonicalArtist renders
 * the link, a null one renders "Unknown" plain text, never a link with nothing to point at.
 *
 * Fix round (SPEC-display-left-rail.md §5/§8, owner-approved 2026-07-23): the support link used
 * to render as a bare orange `<a>` - the buttons-look-like-buttons audit's own item 3 flags this
 * as an action-ish outbound link that should read as a button (it credits/navigates to a
 * specific named destination, not a plain in-page reference). `ArtistSupportLink.tsx` itself is
 * UNCHANGED (it already accepts `className`/`children`, already sets target/rel/title, already
 * appends the box-arrow-up-right icon) - only the props this caller passes changed: a real
 * `btn btn-outline-primary btn-sm` className, and children that spell out the destination
 * ("Support on MTG Artist Connection") instead of just the bare artist name. The plain credit
 * line ("Art by <Name>") stays separate, non-linked text above the button.
 *
 * Upstream-divergence note (docs/upstreaming/readiness-audit.md's styling-divergence ledger):
 * chilli-axe/mpc-autofill has no artist-support surface at all - ArtistSupportLink is a
 * fork-only feature; the `btn-outline-primary` button styling is a fork choice with no upstream
 * analogue to diverge from.
 */
import React from "react";

import { CardDocument } from "@/common/types";
import { ArtistSupportLink } from "@/components/ArtistSupportLink";

interface ArtistSectionProps {
  cardDocument: CardDocument | undefined;
}

// diverges from upstream: chilli-axe/mpc-autofill has no artist-support surface at all
// (ArtistSupportLink is a fork-only feature, additive, upstreamable independently); the
// btn-outline-primary button styling below is a fork choice with no upstream analogue.
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
        <>
          <div className="by mb-1">
            Art by{" "}
            <span className="fw-semibold">
              {cardDocument.canonicalArtist.name}
            </span>
          </div>
          <ArtistSupportLink
            artistName={cardDocument.canonicalArtist.name}
            className="btn btn-outline-primary btn-sm"
          >
            Support on MTG Artist Connection
          </ArtistSupportLink>
        </>
      ) : (
        <span className="text-muted">Unknown</span>
      )}
    </div>
  );
}
