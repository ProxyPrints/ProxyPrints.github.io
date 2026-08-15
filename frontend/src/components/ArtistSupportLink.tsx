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
 * whatever the surface was actually about). The collapsed default render is now TWO lines: the
 * artist page link + disclosure toggle, then a small always-visible MTG Artist Connection credit
 * line underneath - never gated behind the toggle (owner ruling: attribution that only appears
 * after a click is not attribution). Only the commerce links and the signature badge move into a
 * panel that mounts once the user opts in - every link that existed before is still reachable,
 * just not always paid for in vertical space.
 *
 * **Design target: zero and one commerce links, not four or five.** Measured against the real
 * 2,389-artist export: 812 have zero commerce links, 818 have exactly one, only 13 have all five
 * (instagram - added later as a last-resort exception, not a commerce field - rescues 157 of
 * those 812 down to 655; ~598 have nothing but the MTGAC page link regardless of what's
 * allowlisted). The commerce-link panel lays its buttons out in a wrapping grid rather than a
 * full-height vertical stack, so the rare 4-5-link artist doesn't pay for 4-5 full button rows.
 *
 * Callers gate rendering on the artist being confirmed/known (the same precedence chain
 * `Card.serialise` exposes via `canonicalArtist`, or a vote just cast) - this component has no
 * opinion on that and never widens it; it only takes `artistName` (required, non-nullable) plus
 * an optional `className` for the caller's own layout/spacing, and an optional `defaultExpanded`
 * (see that prop's own doc comment below - unused by every current caller).
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

// The button shell - wraps the collapsed row and (once expanded) the disclosure panel, so the
// panel renders within the same widget boundary as the link/toggle rather than as an unrelated
// sibling block below it (issue #747).
const CompactLine = styled.div`
  display: flex;
  flex-direction: column;
  min-width: 0;
`;

// The collapsed row - primary link + toggle - never wraps to a second line, regardless of how
// narrow the caller's container is (the question feed's illustration credit caps it at 220px).
// The MTGAC credit (CreditLine, below) is a separate always-visible line underneath this row,
// not a third item squeezed into it - there isn't room to keep the credit legible next to a long
// artist name at 220px, and the collapsed view is explicitly allowed to be two lines now.
const CompactLineRow = styled.div`
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

// Always rendered, never gated behind `expanded` - the MTGAC credit is an obligation from the
// partnership (they accepted site credits), not decoration, so it must be visible without a
// click (owner ruling). Kept deliberately quiet/small per that same ruling.
const CreditLine = styled.div`
  font-size: 11px;
  color: var(--bs-secondary-color, #6c757d);
  margin-top: 2px;
`;

// Wraps commerce-link buttons into columns instead of stacking every one full-width - the
// expanded panel's main size cost for the rare 4-5-link artist (design target comment above:
// most artists carry zero or one). `w-100` on each `<a>` still fills its own grid cell.
const CommerceLinksGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
  gap: 4px;
  margin-top: 6px;
`;

interface ArtistSupportLinkProps {
  artistName: string;
  className?: string;
  /** Every caller starts collapsed (`undefined`/`false`) now that the MTGAC credit renders on
   * the collapsed line unconditionally (see CreditLine above) - `defaultExpanded` only controls
   * whether the commerce-link/signature-badge panel starts open, which every caller still wants
   * closed by default (the /editor rail included, since its own owner-approved rail-restructure
   * round retired the always-open applet - ArtistSection.tsx no longer passes this prop). Kept as
   * a prop rather than deleted since it's still meaningful (a future caller with genuine room to
   * spend could opt back in), just currently unused by any caller. */
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
        <CompactLineRow>
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
            <Icon
              bootstrapIconName={expanded ? "chevron-up" : "chevron-down"}
            />
            <span className="visually-hidden">
              {expanded ? "Hide artist links" : "Show more artist links"}
            </span>
          </ExpandToggle>
        </CompactLineRow>
        <CreditLine data-testid="artist-support-credit">
          Source:{" "}
          <a
            href={MTGArtistConnectionHomepageURL}
            target="_blank"
            rel="noopener noreferrer"
          >
            {MTGArtistConnection}
          </a>
        </CreditLine>
        {expanded && (
          <div id={expandedPanelId} data-testid="artist-support-expanded">
            {commerceLinks.length > 0 && (
              <CommerceLinksGrid data-testid="artist-support-commerce-links">
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
              </CommerceLinksGrid>
            )}
            {hasSignatureService && (
              <span
                className="badge text-bg-secondary mt-1"
                data-testid="artist-support-signature-badge"
              >
                <Icon bootstrapIconName="pen" /> Mark&apos;s Signature Service
              </span>
            )}
          </div>
        )}
      </CompactLine>
    </div>
  );
}
