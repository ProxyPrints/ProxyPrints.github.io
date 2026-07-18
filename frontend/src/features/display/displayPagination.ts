/**
 * Pure sheet-pagination helper for the unified display page (Proposal H,
 * docs/proposals/proposal-h-unified-display-page.md). Chunks the project's slots into sheet
 * pages while preserving each slot's original index - unlike `CardSelectionModeToPaginator`
 * (features/pdf/PDF.tsx), which resolves each member straight to a plain `CardDocument` and
 * discards which (face, slot) produced it. That's fine for a one-way PDF render; it isn't
 * enough for this page's click-a-card-to-select-it interaction, which needs to dispatch back
 * to a specific (face, slot) pair. Reuses `common/utils.ts`'s shared `chunk` (see its own
 * comment - the same primitive PDF.tsx re-exports for its existing callers) rather than
 * re-implementing chunking.
 *
 * Deliberately paginates ONE face at a time (mirrors the editor's own Fronts/Backs toggle,
 * `viewSettingsSlice`'s `frontsVisible`) rather than PDFGenerator's export-time
 * front-then-distinct-back interleaving (`paginateFrontsAndDistinctBacks`) - a full interleaved
 * dual-face sheet is deferred; see the design doc's component-mapping table.
 */
import { SlotProjectMembers } from "@/common/types";
import { chunk } from "@/common/utils";

export interface DisplaySlotEntry {
  slot: number;
  member: SlotProjectMembers;
}

export function paginateSlotsForDisplay(
  projectMembers: Array<SlotProjectMembers>,
  cardsPerPage: number,
): Array<Array<DisplaySlotEntry>> {
  if (cardsPerPage <= 0) {
    return [];
  }
  const entries: Array<DisplaySlotEntry> = projectMembers.map(
    (member, slot) => ({
      slot,
      member,
    }),
  );
  return chunk(entries, cardsPerPage);
}
