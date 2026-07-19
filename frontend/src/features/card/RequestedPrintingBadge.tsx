/**
 * A small monospace badge showing the REQUESTED printing from a slot's own search query (e.g.
 * "MID 245") - not the resolved canonicalCard, and not printing-tag consensus status. This is
 * what the user's decklist/query actually asked for, which otherwise gets visually "sanitized
 * away" the moment an image is selected - the slot just shows art, with no at-a-glance way to
 * tell which specific printing was requested without opening the change-query modal.
 *
 * Originally built inline for Proposal H Step 2 PR 2b's /display rail header (DisplayPage.tsx).
 * Extracted here as its own component (item (c) of the frontend-polish package) so the standard
 * editor's CardSlot.tsx can mount the exact same badge - one component, one place the degraded-
 * style logic lives, so the two surfaces can't drift apart from each other over time.
 */
import React from "react";

import { SearchQuery, useAppSelector } from "@/common/types";
import { selectIsSearchQueryDegraded } from "@/store/slices/searchResultsSlice";

interface RequestedPrintingBadgeProps {
  query: SearchQuery | undefined;
}

export function RequestedPrintingBadge({ query }: RequestedPrintingBadgeProps) {
  // Called unconditionally on every render of this component regardless of whether the badge
  // ends up rendering anything - satisfies the rules-of-hooks the same way DisplayPage.tsx's own
  // Rail component previously had to (see its own comment on why this selector runs ahead of any
  // early return) simply by living inside its own component now, rather than needing every
  // caller to remember to call it upstream of their own conditional rendering.
  const isDegraded = useAppSelector((state) =>
    selectIsSearchQueryDegraded(
      state,
      query?.query,
      query?.cardType,
      query?.expansionCode,
      query?.collectorNumber
    )
  );

  if (query?.expansionCode == null) {
    return null;
  }

  const printingBadge = `${query.expansionCode.toUpperCase()}${
    query.collectorNumber ? " " + query.collectorNumber : ""
  }`;

  return (
    <span
      className={`badge ${
        isDegraded ? "bg-warning text-dark" : "bg-secondary"
      }`}
      style={{ fontFamily: "monospace" }}
      data-testid="requested-printing-badge"
      data-degraded={isDegraded}
      title={
        isDegraded
          ? "This printing wasn't found - showing the closest available match instead."
          : undefined
      }
    >
      {isDegraded && <i className="bi bi-exclamation-triangle-fill me-1" />}
      {printingBadge}
    </span>
  );
}
