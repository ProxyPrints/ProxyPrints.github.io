/**
 * Stable, machine-readable DOM hooks (data attributes + a DOM event) attached to
 * rendered cards, for client-side tooling, testing selectors, and accessibility.
 * See frontend/docs/dom-api.md for the documented contract.
 */

import { CardDocument } from "@/common/types";

export const CardSelectedEventName = "mpc:card-selected";

export interface CardSelectedEventDetail {
  name?: string;
  identifier?: string;
  sourceKey?: string;
  dpi?: number;
  cardType?: string;
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
  return detail;
}
