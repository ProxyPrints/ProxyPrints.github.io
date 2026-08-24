/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2, OWNER AMENDMENT 2/OQ-B) - pure helpers
 * shared by the two "Apply to all card backs" entries (toolbar = project-wide, rail = per-slot).
 * Kept dependency-free (no redux/react) so the thumbnail-preview logic is unit-testable without a
 * store.
 *
 * Left-rail subject-matter round - a back is SPECIFIED (never touched by an apply action)
 * through any of three independent sources, checked without needing the back to have resolved
 * to an image yet: an intrinsic back (the front card's own layout carries real back art), an
 * import-specified back (a `front // back` directive left a real search query on the back
 * member), or a back the user manually changed for just this slot. Only a back that is none of
 * these - defaulted, and never touched - is eligible for a cardback apply.
 */
import { CardDocument, SlotProjectMembers } from "@/common/types";

// Mirrors the backend's `printing_metadata_import.DOUBLE_FACED_LAYOUTS` - the layout tags whose
// card has real back art (card_faces[1]), as opposed to a blank a project cardback fills in.
const INTRINSIC_BACK_LAYOUTS: ReadonlySet<string> = new Set([
  "transform",
  "modal_dfc",
  "double_faced_token",
  "battle",
  "reversible_card",
]);

export interface CustomBackSlotThumbnail {
  /** 1-based, matching the on-sheet "Slot N" labelling elsewhere in this app. */
  slotLabel: string;
  frontThumbnailUrl: string | undefined;
  frontName: string | undefined;
  backThumbnailUrl: string | undefined;
  backName: string | undefined;
}

/**
 * Whether `member`'s back face is one the user (or the card itself) specified, rather than a
 * plain default a cardback-apply action is free to overwrite.
 */
export function isBackSpecified(
  member: SlotProjectMembers,
  projectCardback: string | undefined,
  cardDocumentsByIdentifier: {
    [identifier: string]: CardDocument | undefined;
  }
): boolean {
  const back = member.back;
  if (back == null) {
    return false;
  }
  if (back.query.query != null) {
    return true;
  }
  const frontImage = member.front?.selectedImage;
  const frontLayout =
    frontImage != null ? cardDocumentsByIdentifier[frontImage]?.layout : null;
  if (frontLayout != null && INTRINSIC_BACK_LAYOUTS.has(frontLayout)) {
    return true;
  }
  return (
    back.selectedImage != null &&
    projectCardback != null &&
    back.selectedImage !== projectCardback
  );
}

/**
 * Every slot a cardback apply would SKIP - the front/current-back thumbnail pair OWNER
 * AMENDMENT 2 requires the prompt to show above the count line, now scoped to genuinely
 * specified backs (see this file's own module comment) rather than every back that merely
 * differs from the project cardback.
 */
export function resolveCustomBackSlotThumbnails(
  members: Array<SlotProjectMembers>,
  projectCardback: string | undefined,
  cardDocumentsByIdentifier: {
    [identifier: string]: CardDocument | undefined;
  }
): Array<CustomBackSlotThumbnail> {
  const results: Array<CustomBackSlotThumbnail> = [];
  members.forEach((member, index) => {
    if (!isBackSpecified(member, projectCardback, cardDocumentsByIdentifier)) {
      return;
    }
    const frontImage = member.front?.selectedImage;
    const frontDoc =
      frontImage != null ? cardDocumentsByIdentifier[frontImage] : undefined;
    const backImage = member.back?.selectedImage;
    const backDoc =
      backImage != null ? cardDocumentsByIdentifier[backImage] : undefined;
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

/** The slot indices (matching `members`' own array positions) an apply of `newCardback` is
 * actually allowed to touch - every slot whose back is NOT specified (see this file's own module
 * comment). Feed this straight into `applyCardbackToAllSlots`'s `slots` payload. */
export function resolveEligibleCardbackApplySlots(
  members: Array<SlotProjectMembers>,
  projectCardback: string | undefined,
  cardDocumentsByIdentifier: {
    [identifier: string]: CardDocument | undefined;
  }
): Array<number> {
  const slots: Array<number> = [];
  members.forEach((member, index) => {
    if (!isBackSpecified(member, projectCardback, cardDocumentsByIdentifier)) {
      slots.push(index);
    }
  });
  return slots;
}

export interface CardbackApplyCounts {
  /** Eligible slots whose back isn't already `newCardback` - what "Apply to all" will change. */
  toUpdate: number;
  /** Specified slots left untouched - counted here only so the prompt can say so, mirroring
   * `applySiblingImage.ts`'s own `skippedDifferent`. */
  skippedSpecified: number;
}

/** How many of `members`' back faces would change if `newCardback` were applied - the prompt's
 * own "Apply to all (N)" count - split from how many are protected and would be skipped. */
export function countCardbackApplyTargets(
  members: Array<SlotProjectMembers>,
  newCardback: string,
  projectCardback: string | undefined,
  cardDocumentsByIdentifier: {
    [identifier: string]: CardDocument | undefined;
  }
): CardbackApplyCounts {
  let toUpdate = 0;
  let skippedSpecified = 0;
  members.forEach((member) => {
    if (isBackSpecified(member, projectCardback, cardDocumentsByIdentifier)) {
      skippedSpecified += 1;
      return;
    }
    if (member.back?.selectedImage !== newCardback) {
      toUpdate += 1;
    }
  });
  return { toUpdate, skippedSpecified };
}
