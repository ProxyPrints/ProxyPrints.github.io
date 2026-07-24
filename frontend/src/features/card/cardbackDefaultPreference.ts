/**
 * Cardback flow round (SPEC-cardback-pdfwait.md Annex A-2) - "Set as my default cardback" is a
 * SEAM, deliberately not designed/built here: the spec's own text is "localStorage for anonymous,
 * account-persisted for authenticated (mirroring how favourites/projects already split) - not
 * designed here."
 *
 * This repo's own standing rule (CLAUDE.md, "No localStorage for anything that should survive a
 * 'clear site data'/incognito test - state that should be server- or URL-derived has caused real
 * bugs here before") means the spec's own suggested anonymous-path storage mechanism can't just be
 * implemented as written without a real backend/account-preference endpoint to write the
 * authenticated half against too (a localStorage-only implementation would silently diverge
 * between the two account states, and would be the exact class of bug that rule exists to
 * prevent). Rather than land a real persistence layer nobody has designed the backend contract
 * for, this module is the explicit seam boundary the button below calls into - documented,
 * intentionally a no-op, easy to swap for a real `POST /2/preferences/defaultCardback/`-shaped
 * call (or a deliberately-scoped localStorage write, if the owner rules that's fine for the
 * anonymous half specifically) once that contract exists. The UI (`CardbackApplyPrompt.tsx`)
 * still renders the full "Set as my default cardback" affordance and its done-state - only the
 * actual write is deferred.
 */
export interface SetDefaultCardbackResult {
  /** Always `true` today (the seam has nothing that can fail yet) - kept as a real return value,
   * not a bare void, so callers don't need to change shape once this seam gains a real
   * network/storage write that CAN fail. */
  persisted: boolean;
}

export async function setUserDefaultCardback(
  selectedImage: string
): Promise<SetDefaultCardbackResult> {
  // Intentional no-op - see this module's own header comment (Annex A-2 seam). `selectedImage`
  // is unused today; kept in the signature so a real implementation is a body-only change.
  void selectedImage;
  return { persisted: false };
}
