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
