/**
 * Proposal B PR-1 (docs/proposals/proposal-b-bleed-normalization.md) - the main-thread batch
 * resolution of each export card's appropriate-bleed machine-vote lean, via the same per-card
 * confidence-fill path the attribute chips use (APIGetTagConsensus, store/api.ts - already
 * exists, no new endpoint). MUST run on the main thread, not inside pdf.worker.ts's Worker
 * context: APIGetTagConsensus's CSRF header needs document.cookie, and Workers have no
 * `document`. The resolved {[identifier]: BleedPrior} map is plain, structured-clone-safe data
 * that PDFGenerator.tsx hands to the worker via PDFProps.bleedPriors - the worker itself never
 * fetches anything for this.
 */

import { mapWithConcurrencyLimit } from "@/common/concurrencyLimit";
import { BleedPrior } from "@/features/pdf/bleedNormalize";
import { APIGetTagConsensus } from "@/store/api";

export const APPROPRIATE_BLEED_TAG_NAME = "appropriate-bleed";

// Matches GoogleDriveService's own default worker cap (executeCall's Semaphore) - not
// empirically tuned for this specific endpoint, but a reasonable, already-precedented starting
// point for "how many concurrent requests is polite to this backend." Bounded per the approved
// spec's memory-discipline section ("bounded export concurrency... explicit worker cap").
export const BLEED_PRIOR_RESOLUTION_CONCURRENCY = 6;

/**
 * One card's lean, from its appropriate-bleed TagConsensusEntry.netPolarity (if any). A clearly
 * positive lean maps to "bleed"; a clearly negative lean maps to "trimmed"; a missing entry or a
 * zero/near-zero lean maps to "unresolved" - resolveBleedPlan's own fallback treats "trimmed"
 * and "unresolved" identically (both extend the full target), so this 3-way split exists for
 * code clarity/debugging, not because the two cases are handled differently downstream.
 *
 * Never throws - a failed lookup for one card (network blip, rate limit, a card the backend
 * doesn't recognize) degrades that single card to "unresolved" rather than failing the whole
 * batch. This is the safe, spec-defined default (extend the full target), not a silent data
 * hole - resolveBleedPlan's manual override still lets a user correct an individual card that
 * guessed wrong.
 */
async function resolveSingleBleedPrior(
  backendURL: string,
  identifier: string
): Promise<BleedPrior> {
  try {
    const response = await APIGetTagConsensus(backendURL, identifier);
    const entry = response.tags.find(
      (tag) => tag.tagName === APPROPRIATE_BLEED_TAG_NAME
    );
    if (entry == null || entry.netPolarity === 0) {
      return "unresolved";
    }
    return entry.netPolarity > 0 ? "bleed" : "trimmed";
  } catch {
    return "unresolved";
  }
}

/**
 * Resolves the bleed prior for every unique card identifier in `identifiers`, with bounded
 * concurrency. Callers pass the export's own card set (e.g.
 * Object.keys(cardDocumentsByIdentifier), already deduplicated by that map's own construction) -
 * deduplicated again here defensively in case a caller passes a raw, possibly-repeating list.
 */
export async function resolveBleedPriors(
  backendURL: string,
  identifiers: readonly string[],
  concurrency: number = BLEED_PRIOR_RESOLUTION_CONCURRENCY
): Promise<Record<string, BleedPrior>> {
  const uniqueIdentifiers = Array.from(new Set(identifiers));
  const priors = await mapWithConcurrencyLimit(
    uniqueIdentifiers,
    concurrency,
    (identifier) => resolveSingleBleedPrior(backendURL, identifier)
  );
  return Object.fromEntries(
    uniqueIdentifiers.map((identifier, index) => [identifier, priors[index]])
  );
}
