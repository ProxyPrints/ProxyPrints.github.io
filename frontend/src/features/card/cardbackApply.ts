/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2, OWNER AMENDMENT 2/OQ-B) - pure helpers
 * shared by the two "Apply to all card backs" entries (toolbar = project-wide, rail = per-slot).
 * Kept dependency-free (no redux/react) so the thumbnail-preview logic is unit-testable without a
 * store.
 */
import { CardDocument, SlotProjectMembers } from "@/common/types";

export interface CustomBackSlotThumbnail {
  /** 1-based, matching the on-sheet "Slot N" labelling elsewhere in this app. */
  slotLabel: string;
  frontThumbnailUrl: string | undefined;
  frontName: string | undefined;
  backThumbnailUrl: string | undefined;
  backName: string | undefined;
}

/**
 * Every slot whose current back-face image differs from `projectCardback` - i.e. a
 * deliberately-custom back that "Apply to all" would override, with the front/current-back
 * thumbnail pair OWNER AMENDMENT 2 requires the prompt to show above the count line.
 * `projectCardback == null` (no project cardback chosen at all yet) means there is nothing to be
 * "different" FROM, so nothing counts as custom.
 */
export function resolveCustomBackSlotThumbnails(
  members: Array<SlotProjectMembers>,
  projectCardback: string | undefined,
  cardDocumentsByIdentifier: {
    [identifier: string]: CardDocument | undefined;
  }
): Array<CustomBackSlotThumbnail> {
  if (projectCardback == null) {
    return [];
  }
  const results: Array<CustomBackSlotThumbnail> = [];
  members.forEach((member, index) => {
    const backImage = member.back?.selectedImage;
    if (backImage == null || backImage === projectCardback) {
      return;
    }
    const frontImage = member.front?.selectedImage;
    const frontDoc =
      frontImage != null ? cardDocumentsByIdentifier[frontImage] : undefined;
    const backDoc = cardDocumentsByIdentifier[backImage];
    results.push({
      slotLabel: `Slot ${index + 1}`,
      frontThumbnailUrl: frontDoc?.smallThumbnailUrl,
      frontName: frontDoc?.name,
      backThumbnailUrl: backDoc?.smallThumbnailUrl,
      backName: backDoc?.name,
    });
  });
  return results;
}

/** How many of `members`' back faces would change if `newCardback` were applied to every slot
 * (project-wide "Apply to all") - the prompt's own "6 backs" count, independent of the
 * custom-back subset above. */
export function countBackFacesAffectedByApplyAll(
  members: Array<SlotProjectMembers>,
  newCardback: string
): number {
  return members.filter((member) => member.back?.selectedImage !== newCardback)
    .length;
}
