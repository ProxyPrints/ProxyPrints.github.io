/**
 * Pure grouping logic for the unified display page's Select Version section (issue #167,
 * docs/proposals/proposal-h-unified-display-page.md §4.4′ - "Select Version section - unified
 * spec"). Takes the same candidate identifier list `useGridSelectorSearch`/`GridSelectorResults`
 * already produce (sorted/filtered) and buckets them into the spec's three ordered groups:
 *
 *   1. canonical   - one representative per distinct real printing (grouped by
 *                    `canonicalCard`/`suggestedCanonicalCard` identifier - the two fields are the
 *                    SAME Scryfall printing UUID regardless of which one happens to be populated
 *                    for a given copy, so a resolved copy and a still-suggested copy of the exact
 *                    same printing naturally cluster under one key without extra logic).
 *   2. nonCanonical - cards with no printing data at all but a resolved no-match reason tag
 *                    (custom-art / altered-frame / ai-art - the three the spec names), grouped by
 *                    that tag.
 *   3. unknown      - everything else: no printing data, no classifying tag. The "honest residue"
 *                    - deliberately NOT representative-grouped, per the spec's own wording ("last",
 *                    no "+N more" pattern described for it).
 *
 * No React, no Redux - this is unit-tested directly (selectVersionGrouping.test.ts) rather than
 * through a rendered component, per the task's "grouping logic" test requirement.
 */
import { CardDocument } from "@/common/types";

/**
 * The three no-match reason tags the spec names for group 2's sub-grouping, in priority order
 * ("frame type first" - altered-frame is the one frame-related tag of the three; custom-art vs.
 * ai-art relative order isn't specified by the spec text, so this ordering is a documented,
 * arbitrary pick - see this task's OPEN ITEMS). These are a DIFFERENT taxonomy from
 * attributeChips.ts's ALL_ATTRIBUTE_CHIPS (border/frame/fullart/etc.) - see
 * cardpicker.reason_tags/docs/features/printing-tags.md's "no-match reason tags" section. Three
 * of the six seeded reason tags are used here (custom-art, altered-frame, ai-art); the other
 * three (upscaled, no-collector-line, non-english) aren't printing-identity-relevant in the way
 * this grouping cares about and are left in the "unknown" bucket if present alone.
 */
export const SELECT_VERSION_REASON_TAG_PRIORITY: ReadonlyArray<string> = [
  "altered-frame",
  "custom-art",
  "ai-art",
];

export type PrintingGroupStatus = "resolved" | "suggested";

export interface SelectVersionPrintingGroup {
  /** The real Scryfall printing UUID this cluster represents - canonicalCard/suggestedCanonicalCard's own `identifier` field. */
  key: string;
  /** "resolved" if ANY copy in this cluster has a human-resolved `canonicalCard` for this printing; "suggested" only when every copy is still machine-suggested/unconfirmed. */
  status: PrintingGroupStatus;
  expansionCode: string;
  collectorNumber: string;
  /** The highest-DPI copy in the cluster (ties broken in favor of a resolved copy over a suggested one). */
  representative: string;
  /** Every other copy in the cluster, in original order - the "+N more of this printing" set. */
  rest: string[];
  /** True when this cluster matches the slot's own requested printing (searchQuery) - sorts first, badge-worthy, regardless of resolved/suggested status. */
  isRequestedPrinting: boolean;
}

export interface SelectVersionReasonTagGroup {
  tagName: string;
  representative: string;
  rest: string[];
}

export interface SelectVersionGroups {
  canonical: SelectVersionPrintingGroup[];
  nonCanonical: SelectVersionReasonTagGroup[];
  unknown: string[];
}

export interface RequestedPrinting {
  expansionCode?: string | null;
  collectorNumber?: string | null;
}

function pickRepresentative(
  identifiers: string[],
  cardDocumentsByIdentifier: Record<string, CardDocument | undefined>
): { representative: string; rest: string[] } {
  let representative = identifiers[0];
  let bestDpi = cardDocumentsByIdentifier[representative]?.dpi ?? -1;
  let bestResolved =
    cardDocumentsByIdentifier[representative]?.canonicalCard != null;

  for (const identifier of identifiers.slice(1)) {
    const card = cardDocumentsByIdentifier[identifier];
    const dpi = card?.dpi ?? -1;
    const resolved = card?.canonicalCard != null;
    // Highest DPI wins outright (spec: "the highest-DPI copy in that printing's cluster"); a tie
    // prefers a resolved copy over a still-suggested one, so the representative also carries the
    // strongest available verification signal when DPI alone doesn't decide it.
    if (dpi > bestDpi || (dpi === bestDpi && resolved && !bestResolved)) {
      representative = identifier;
      bestDpi = dpi;
      bestResolved = resolved;
    }
  }
  return {
    representative,
    rest: identifiers.filter((identifier) => identifier !== representative),
  };
}

function matchesRequestedPrinting(
  expansionCode: string,
  collectorNumber: string,
  requestedPrinting: RequestedPrinting | undefined
): boolean {
  if (requestedPrinting?.expansionCode == null) {
    return false;
  }
  if (
    expansionCode.toUpperCase() !==
    requestedPrinting.expansionCode.toUpperCase()
  ) {
    return false;
  }
  return (
    requestedPrinting.collectorNumber == null ||
    collectorNumber === requestedPrinting.collectorNumber
  );
}

export function groupSelectVersionCandidates(
  identifiers: string[],
  cardDocumentsByIdentifier: Record<string, CardDocument | undefined>,
  requestedPrinting?: RequestedPrinting
): SelectVersionGroups {
  const printingClusters = new Map<
    string,
    {
      identifiers: string[];
      anyResolved: boolean;
      expansionCode: string;
      collectorNumber: string;
    }
  >();
  const reasonClusters = new Map<string, string[]>();
  const unknown: string[] = [];

  identifiers.forEach((identifier) => {
    const card = cardDocumentsByIdentifier[identifier];
    // A candidate identifier this page doesn't have a CardDocument for yet (still loading) can't
    // be classified - park it in "unknown" rather than dropping it, so it's still reachable/
    // selectable while its data streams in.
    if (card == null) {
      unknown.push(identifier);
      return;
    }

    const printing = card.canonicalCard ?? card.suggestedCanonicalCard ?? null;
    if (printing != null) {
      const existing = printingClusters.get(printing.identifier);
      const resolved = card.canonicalCard != null;
      if (existing == null) {
        printingClusters.set(printing.identifier, {
          identifiers: [identifier],
          anyResolved: resolved,
          expansionCode: printing.expansionCode,
          collectorNumber: printing.collectorNumber,
        });
      } else {
        existing.identifiers.push(identifier);
        existing.anyResolved = existing.anyResolved || resolved;
      }
      return;
    }

    const reasonTag = SELECT_VERSION_REASON_TAG_PRIORITY.find((tagName) =>
      card.tags.includes(tagName)
    );
    if (reasonTag != null) {
      const cluster = reasonClusters.get(reasonTag) ?? [];
      cluster.push(identifier);
      reasonClusters.set(reasonTag, cluster);
      return;
    }

    unknown.push(identifier);
  });

  const canonical: SelectVersionPrintingGroup[] = Array.from(
    printingClusters.entries()
  ).map(([key, cluster]) => {
    const { representative, rest } = pickRepresentative(
      cluster.identifiers,
      cardDocumentsByIdentifier
    );
    return {
      key,
      status: cluster.anyResolved ? "resolved" : "suggested",
      expansionCode: cluster.expansionCode,
      collectorNumber: cluster.collectorNumber,
      representative,
      rest,
      isRequestedPrinting: matchesRequestedPrinting(
        cluster.expansionCode,
        cluster.collectorNumber,
        requestedPrinting
      ),
    };
  });

  // Requested printing (if present in this result set at all) sorts first regardless of its own
  // resolved/suggested status; resolved printings sort ahead of suggested ones otherwise; stable
  // (Array.prototype.sort is a stable sort in every JS engine this codebase targets) so ties keep
  // their original cluster-discovery order rather than reshuffling arbitrarily.
  canonical.sort((a, b) => {
    if (a.isRequestedPrinting !== b.isRequestedPrinting) {
      return a.isRequestedPrinting ? -1 : 1;
    }
    if (a.status !== b.status) {
      return a.status === "resolved" ? -1 : 1;
    }
    return 0;
  });

  const nonCanonical: SelectVersionReasonTagGroup[] =
    SELECT_VERSION_REASON_TAG_PRIORITY.filter((tagName) =>
      reasonClusters.has(tagName)
    ).map((tagName) => {
      const clusterIdentifiers = reasonClusters.get(tagName) as string[];
      const { representative, rest } = pickRepresentative(
        clusterIdentifiers,
        cardDocumentsByIdentifier
      );
      return { tagName, representative, rest };
    });

  return { canonical, nonCanonical, unknown };
}
