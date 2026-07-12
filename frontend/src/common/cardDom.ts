/**
 * Stable, machine-readable DOM hooks (data attributes + a DOM event) attached to
 * rendered cards, for client-side tooling, testing selectors, and accessibility.
 * See frontend/docs/dom-api.md for the documented contract.
 */

import { PrintingCandidate } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

export const CardSelectedEventName = "mpc:card-selected";

export interface CardSelectedEventDetail {
  name?: string;
  identifier?: string;
  sourceKey?: string;
  dpi?: number;
  cardType?: string;
  setCode?: string;
  collectorNumber?: string;
}

const cardTypeAttributeValue = (
  cardType: CardDocument["cardType"] | undefined
): string | undefined =>
  cardType != null ? cardType.toLowerCase() : undefined;

/**
 * Data attributes for a card's root DOM element, sourced from the `CardDocument`
 * the frontend already has in memory. Any field that isn't available is omitted
 * entirely rather than emitted as an empty attribute.
 */
export function getCardDataAttributes(
  cardDocument: CardDocument | undefined
): Record<string, string | number> {
  if (cardDocument == null) {
    return {};
  }

  const attributes: Record<string, string | number> = {};
  if (cardDocument.name != null) {
    attributes["data-card-name"] = cardDocument.name;
  }
  if (cardDocument.identifier != null) {
    attributes["data-card-identifier"] = cardDocument.identifier;
  }
  if (cardDocument.source != null) {
    attributes["data-source-key"] = cardDocument.source;
  }
  if (cardDocument.dpi != null) {
    attributes["data-card-dpi"] = cardDocument.dpi;
  }
  const cardType = cardTypeAttributeValue(cardDocument.cardType);
  if (cardType != null) {
    attributes["data-card-type"] = cardType;
  }
  if (cardDocument.canonicalCard?.expansionCode != null) {
    attributes["data-card-set-code"] = cardDocument.canonicalCard.expansionCode;
  }
  if (cardDocument.canonicalCard?.collectorNumber != null) {
    attributes["data-card-collector-number"] =
      cardDocument.canonicalCard.collectorNumber;
  }
  return attributes;
}

/**
 * Builds the `detail` payload for the `mpc:card-selected` event from the same
 * `CardDocument` fields exposed as data attributes by `getCardDataAttributes`.
 */
export function getCardSelectedEventDetail(
  cardDocument: CardDocument
): CardSelectedEventDetail {
  const detail: CardSelectedEventDetail = {};
  if (cardDocument.name != null) {
    detail.name = cardDocument.name;
  }
  if (cardDocument.identifier != null) {
    detail.identifier = cardDocument.identifier;
  }
  if (cardDocument.source != null) {
    detail.sourceKey = cardDocument.source;
  }
  if (cardDocument.dpi != null) {
    detail.dpi = cardDocument.dpi;
  }
  const cardType = cardTypeAttributeValue(cardDocument.cardType);
  if (cardType != null) {
    detail.cardType = cardType;
  }
  if (cardDocument.canonicalCard?.expansionCode != null) {
    detail.setCode = cardDocument.canonicalCard.expansionCode;
  }
  if (cardDocument.canonicalCard?.collectorNumber != null) {
    detail.collectorNumber = cardDocument.canonicalCard.collectorNumber;
  }
  return detail;
}

/**
 * Data attributes for a printing-candidate element (the printing-tag
 * queue/picker), sourced from a `PrintingCandidate` plus the name of the
 * card currently being tagged. Distinct from getCardDataAttributes: here
 * data-card-name is the card being tagged, while data-card-set-code /
 * data-card-collector-number / data-card-identifier describe this one
 * candidate printing, which may or may not turn out to be a match.
 */
export function getPrintingCandidateDataAttributes(
  cardName: string,
  candidate: PrintingCandidate
): Record<string, string> {
  return {
    "data-card-name": cardName,
    "data-card-identifier": candidate.identifier,
    "data-card-set-code": candidate.expansionCode,
    "data-card-collector-number": candidate.collectorNumber,
  };
}
