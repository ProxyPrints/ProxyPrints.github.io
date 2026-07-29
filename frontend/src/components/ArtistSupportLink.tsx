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
 * **Design target: zero and one commerce links, not four or five.** Measured against the real
 * 2,389-artist export: 812 have zero commerce links, 818 have exactly one, only 13 have all five
 * (instagram - added later as a last-resort exception, not a commerce field - rescues 157 of
 * those 812 down to 655; ~598 have nothing but the MTGAC page link regardless of what's
 * allowlisted). This applet ALWAYS renders the MTGAC page link and the "Source: MTG Artist
 * Connection" credit (an obligation, not decoration - site credits were part of the MTGAC
 * partnership) - commerce buttons are purely additive on top of that stable base, so the ~69% of
 * artists with zero or one link see a small, correctly-proportioned applet, not an empty box or
 * a layout built for a row of five buttons that's usually mostly missing.
 *
 * **No layout shift while loading**: the loading state and the "found: false"/zero-commerce-link
 * state render IDENTICALLY (MTGAC page link + credit only, no commerce buttons, no badge).
 * Commerce buttons and the signature-service badge are added on top once data confirms they
 * exist - for a third of all artists that's not a shift at all, since the loaded state IS the
 * base shape; for the rest, buttons appear below the stable base rather than a spinner/skeleton
 * collapsing into a completely different-shaped final layout.
 *
 * **Buttons stretch to fill the applet** (owner instruction) - every rendered `<a>`/button here
 * is full-width within whatever container the caller gives it, so the applet reads consistently
 * whether that container is a narrow table cell or a full-width rail panel.
 *
 * Callers gate rendering on the artist being confirmed/known (the same precedence chain
 * `Card.serialise` exposes via `canonicalArtist`, or a vote just cast) - this component has no
 * opinion on that and never widens it; it only takes `artistName` (required, non-nullable) plus
 * an optional `className` for the caller's own layout/spacing.
 */
import React from "react";

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

interface ArtistSupportLinkProps {
  artistName: string;
  className?: string;
}

export function ArtistSupportLink({
  artistName,
  className,
}: ArtistSupportLinkProps) {
  const { data } = useGetArtistExternalLinksQuery(artistName);

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
      <a
        href={pageHref}
        target="_blank"
        rel="noopener noreferrer"
        title={`via ${MTGArtistConnection}`}
        className="btn btn-primary btn-sm w-100 d-block"
        data-testid="artist-support-link"
      >
        {artistName} <Icon bootstrapIconName="box-arrow-up-right" />
      </a>
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
  );
}
