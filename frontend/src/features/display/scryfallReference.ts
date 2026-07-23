/**
 * Editor-completion package, E17 - the directed-help affordance's v1 cut (owner: "help users find
 * an instance where their art is available ... direct them"). Builds a deterministic, zero-crawl
 * outbound reference link from what the catalog already knows about an unresolved query - a
 * Scryfall printing page when the query names a printing (expansionCode+collectorNumber), else a
 * Scryfall name search - never a crawl, never anything stored (same governing-premise posture as
 * ArtistSupportLink.tsx). The ranked "known-available" resolver the spec's own Open Q3 floats is a
 * real backend dependency, deliberately NOT built here - this is the zero-backend-work v1 only.
 */
import { SearchQuery } from "@/common/types";

export function buildScryfallReferenceUrl(
  query: SearchQuery | undefined
): string | undefined {
  if (query == null) {
    return undefined;
  }
  if (query.expansionCode != null && query.expansionCode.length > 0) {
    const set = query.expansionCode.toLowerCase();
    return query.collectorNumber != null && query.collectorNumber.length > 0
      ? `https://scryfall.com/card/${set}/${query.collectorNumber}`
      : `https://scryfall.com/search?q=set%3A${encodeURIComponent(set)}`;
  }
  if (query.query != null && query.query.length > 0) {
    return `https://scryfall.com/search?q=${encodeURIComponent(query.query)}`;
  }
  return undefined;
}

/**
 * D14 confidence element (SPEC-display-left-rail.md §3) - the set-icon hover Popover's reference
 * image. Same zero-crawl, nothing-stored posture as `buildScryfallReferenceUrl` above (governing
 * premise + #271): Scryfall's own documented `?format=image` convenience redirect
 * (https://scryfall.com/docs/api/cards - "Card image" content negotiation) resolves a set code +
 * collector number straight to the actual card image on Scryfall's own CDN, with no Scryfall
 * card-UUID lookup step needed first - the frontend never fetches or stores the image itself,
 * only points an `<img src>` at it. `null`/absent inputs (no set or no number) return `undefined`,
 * same "nothing to build a URL from" convention as the sibling function above.
 */
export function buildScryfallReferenceImageUrl(
  expansionCode: string | null | undefined,
  collectorNumber: string | null | undefined
): string | undefined {
  if (expansionCode == null || expansionCode.length === 0) {
    return undefined;
  }
  if (collectorNumber == null || collectorNumber.length === 0) {
    return undefined;
  }
  return `https://api.scryfall.com/cards/${encodeURIComponent(
    expansionCode.toLowerCase()
  )}/${encodeURIComponent(collectorNumber)}?format=image`;
}
