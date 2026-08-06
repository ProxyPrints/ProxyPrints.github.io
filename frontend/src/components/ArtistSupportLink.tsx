/**
 * MTG Artist Connection (MTGAC) artist-links applet, M2 - see
 * docs/features/artist-support-links.md for the full design (M1's backend consumer, the
 * normaliser, the commerce-only allowlist, the 8.2% slug-divergence finding this component
 * exists to fix). M1 shipped a `2/artistExternalLinks/` endpoint with no frontend consumer; this
 * file is that consumer, replacing the old v1 zero-crawl deterministic-link-only design.
 *
 * **Fetch via RTK Query** (`useGetArtistExternalLinksQuery`, store/api.ts) - never an ad-hoc
 * `fetch`. The endpoint is cache-only on the backend (never a live MTGAC call) and returns
 * `found: false` for two ordinary, expected reasons: the daily cache hasn't been warmed for this
 * artist yet, or this project doesn't index them in `CanonicalArtist` at all (see that endpoint's
 * own backend docstring). Both cases - and a not-yet-configured remote backend, and a
 * still-loading request - are treated identically here: fall back to the deterministic
 * `buildArtistSupportURL` construction. **Never a broken or empty state.**
 *
 * **Compact by default, expandable** (issue #709 - the applet used to always stack the page-link
 * button, up to five commerce buttons, a badge, and a credit line, up to ~8 rows deep next to
 * whatever the surface was actually about). The default render is ONE line: the artist page link
 * plus a small disclosure toggle. Commerce links, the signature badge, and the MTGAC credit line
 * move into a panel that only mounts once the user opts in - every link that existed before is
 * still reachable, just not always paid for in vertical space.
 *
 * **Design target: zero and one commerce links, not four or five.** Measured against the real
 * 2,389-artist export: 812 have zero commerce links, 818 have exactly one, only 13 have all five
 * (instagram - added later as a last-resort exception, not a commerce field - rescues 157 of
 * those 812 down to 655; ~598 have nothing but the MTGAC page link regardless of what's
 * allowlisted). The "Source: MTG Artist Connection" credit (an obligation, not decoration - site
 * credits were part of the MTGAC partnership) is always reachable through the disclosure, whether
 * or not this particular artist has any commerce links to go with it.
 *
 * Callers gate rendering on the artist being confirmed/known (the same precedence chain
 * `Card.serialise` exposes via `canonicalArtist`, or a vote just cast) - this component has no
 * opinion on that and never widens it; it only takes `artistName` (required, non-nullable) plus
 * an optional `className` for the caller's own layout/spacing, and an optional `defaultExpanded`
 * for the one surface (the /editor rail's Artist section) that has room to show the full applet
 * up front.
 */
import styled from "@emotion/styled";
import React, { useId, useState } from "react";

import {
  MTGArtistConnection,
  MTGArtistConnectionArtistBaseURL,
  MTGArtistConnectionHomepageURL,
} from "@/common/constants";
import { Icon } from "@/components/icon";
import { useGetArtistExternalLinksQuery } from "@/store/api";

export function buildArtistSupportURL(artistName: string): string {
  return `${MTGArtistConnectionArtistBaseURL}${encodeURIComponent(artistName)}`;
}

// Human labels for each allowlisted link type, in the exact SAME fixed priority order the
// backend emits them in (cardpicker.artist_external_links._LINK_PRIORITY) - this component never
// re-sorts `data.links`, it renders them in the order the backend already sent, and the backend
// is the single source of truth for that order.
const LINK_TYPE_LABELS: Record<string, string> = {
  website: "Website",
  artstation: "ArtStation",
  inprnt: "INPRNT",
  mountainmage: "Mountain Mage Signatures",
  omalink: "Original Magic Art",
  // Deliberate last-resort exception (owner ruling) - not a commerce field, allowlisted anyway
  // because it's the only link for 157 artists who would otherwise have none at all. Always
  // last in the backend's priority order, so it never displaces a commerce button above it.
  instagram: "Instagram",
};

// The collapsed row - primary link + toggle - never wraps to a second line, regardless of how
// narrow the caller's container is (the question feed's illustration credit caps it at 220px).
const CompactLine = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
`;

const CompactLink = styled.a`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1 1 auto;
`;

// The artist name is the part that can be arbitrarily long, so ellipsis lives on this inner
// span rather than the flex anchor itself (text-overflow needs a single-line inline box, not a
// flex container with a sibling icon).
const CompactLinkLabel = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
`;

const ExpandToggle = styled.button`
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--bs-border-color, currentColor);
  border-radius: var(--r-btn, 4px);
  color: inherit;
  cursor: pointer;
`;

interface ArtistSupportLinkProps {
  artistName: string;
  className?: string;
  /** The /editor rail's Artist section (ArtistSection.tsx) is a dedicated accordion pane with
   * room for the full stacked applet, and its own Playwright coverage already asserts the credit
   * line renders without any interaction - so that one caller opts into starting expanded. Every
   * other caller (the question feed's inline credits, the card-detail modal's metadata table) is
   * space-constrained next to whatever the surface is actually about, so `undefined`/`false`
   * (the default) starts collapsed to a single line. */
  defaultExpanded?: boolean;
}

export function ArtistSupportLink({
  artistName,
  className,
  defaultExpanded = false,
}: ArtistSupportLinkProps) {
  const { data } = useGetArtistExternalLinksQuery(artistName);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const expandedPanelId = useId();

  // Prefer MTGAC's own authoritative pageUrl when we have it - this is the actual point of the
  // applet, not a nice-to-have: 197/2,389 (8.2%) of this project's deterministically-constructed
  // URLs disagree with MTGAC's real slugs (accents folded, periods dropped, case normalised,
  // truncation) and land on MTGAC's own "no artist found" page under the old v1 behaviour. A
  // cold cache, a not-yet-loaded request, an unconfigured remote backend, and an artist absent
  // from CanonicalArtist all fall back to the same deterministic construction, indistinguishably.
  const pageHref =
    data?.found && data.pageUrl != null
      ? data.pageUrl
      : buildArtistSupportURL(artistName);

  const commerceLinks = data?.found ? data.links : [];
  const hasSignatureService = data?.found === true && data.hasSignatureService;

  return (
    <div
      className={["artist-support-applet", className].filter(Boolean).join(" ")}
      data-testid="artist-support-applet"
    >
      <CompactLine>
        <CompactLink
          href={pageHref}
          target="_blank"
          rel="noopener noreferrer"
          title={`via ${MTGArtistConnection}`}
          className="btn btn-primary btn-sm"
          data-testid="artist-support-link"
        >
          <CompactLinkLabel>{artistName}</CompactLinkLabel>
          <Icon bootstrapIconName="box-arrow-up-right" />
        </CompactLink>
        <ExpandToggle
          type="button"
          onClick={() => setExpanded((previous) => !previous)}
          aria-expanded={expanded}
          aria-controls={expandedPanelId}
          data-testid="artist-support-toggle"
        >
          <Icon bootstrapIconName={expanded ? "chevron-up" : "chevron-down"} />
          <span className="visually-hidden">
            {expanded ? "Hide artist links" : "Show more artist links"}
          </span>
        </ExpandToggle>
      </CompactLine>
      {expanded && (
        <div id={expandedPanelId} data-testid="artist-support-expanded">
          {commerceLinks.length > 0 && (
            <div
              className="d-grid gap-2 mt-2"
              data-testid="artist-support-commerce-links"
            >
              {commerceLinks.map((link) => (
                <a
                  key={link.type}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-outline-primary btn-sm w-100"
                  data-testid="artist-support-commerce-link"
                  data-link-type={link.type}
                >
                  {LINK_TYPE_LABELS[link.type] ?? link.type}{" "}
                  <Icon bootstrapIconName="box-arrow-up-right" />
                </a>
              ))}
            </div>
          )}
          {hasSignatureService && (
            <span
              className="badge text-bg-secondary mt-2"
              data-testid="artist-support-signature-badge"
            >
              <Icon bootstrapIconName="pen" /> Mark&apos;s Signature Service
            </span>
          )}
          <div
            className="text-muted small mt-1"
            data-testid="artist-support-credit"
          >
            Source:{" "}
            <a
              href={MTGArtistConnectionHomepageURL}
              target="_blank"
              rel="noopener noreferrer"
            >
              {MTGArtistConnection}
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
