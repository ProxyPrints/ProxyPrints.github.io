/**
 * Pure helpers for "apply this image to the other slots holding the same card" - siblings are
 * identified the same way `bulkAlignMemberSelection` already groups slots for bulk selection
 * (matching `SearchQuery` on the same face, via `areSearchQueriesEqual`), not by selectedImage
 * value. Kept dependency-free (no redux/react), mirroring `cardbackApply.ts`'s own split
 * between pure counting helpers and the reducer that performs the mutation.
 */
import { areSearchQueriesEqual } from "@/common/processing";
import { Faces, SlotProjectMembers } from "@/common/types";

export interface SiblingApplyCounts {
  /** Sibling slots (same face, matching query, excluding the source slot itself) with no image
   * selected yet - these are what "Apply to siblings" will fill in. */
  toUpdate: number;
  /** Sibling slots that already carry a DIFFERENT image the user deliberately chose - never
   * touched by the apply action, counted here only so the affordance can say so. */
  skippedDifferent: number;
}

/**
 * Counts how many of `members`' other slots (on `face`) share `slot`'s search query and would
 * be affected by applying `slot`'s currently selected image to its siblings. Returns all zeros
 * when `slot` itself has no selected image - there's nothing to propagate.
 */
export function countSiblingSlotsForImage(
  members: Array<SlotProjectMembers>,
  face: Faces,
  slot: number
): SiblingApplyCounts {
  const source = members[slot]?.[face];
  const sourceImage = source?.selectedImage;
  if (source == null || sourceImage == null) {
    return { toUpdate: 0, skippedDifferent: 0 };
  }

  let toUpdate = 0;
  let skippedDifferent = 0;
  members.forEach((member, index) => {
    if (index === slot) {
      return;
    }
    const sibling = member[face];
    if (
      sibling == null ||
      !areSearchQueriesEqual(sibling.query, source.query)
    ) {
      return;
    }
    if (sibling.selectedImage == null) {
      toUpdate += 1;
    } else if (sibling.selectedImage !== sourceImage) {
      skippedDifferent += 1;
    }
  });
  return { toUpdate, skippedDifferent };
}
