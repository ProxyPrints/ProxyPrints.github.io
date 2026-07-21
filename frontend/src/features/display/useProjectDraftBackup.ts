/**
 * Proposal H ADDENDUM D9(1)/F1 (docs/proposals/proposal-h-display-layout-spec.md) - the silent
 * local draft auto-backup, the first of D9's three save-before-PDF layers. HARD OWNER CONSTRAINT
 * (verbatim, D9): "save deck should come before PDF completes because we have to rely on clients
 * available mem for the PDF" - PDF generation is the client's most memory-hungry step and can
 * OOM/crash the tab, so the working project is mirrored to `localStorage` on every mutation,
 * independent of (and strictly before) any PDF render.
 *
 * GOVERNING PREMISE (CLAUDE.md "we index, we do not store images"): this mirrors `buildDeckPayload`'s
 * plaintext CONTENT shape - decklist identifiers, per-slot queries/overrides, and finish/page
 * settings - never image pixels. Exactly the same invariant deckPayload.ts's own encrypted saved
 * decks already honour, applied to this browser's own disk as strictly as to the network.
 *
 * Deliberately `localStorage`, not a saved-deck row: this is the ANONYMOUS-safe, account-free
 * safety net (no crypto session, no server round-trip) - the "the local draft is the anonymous
 * user's only persistence, and that is fine" line from D9(2). It is NOT a replacement for a real
 * saved deck - see the promotion nudge below and PrePrintSaveGate.tsx for the two paths that
 * invite promoting a draft into one.
 *
 * Serialization reuses deckPayload.ts's `buildDeckPayload` plaintext CONTENT shape (no version
 * tag of its own - this hook stamps its own small `draftVersion` wrapper instead, so a future
 * shape change can upgrade forward the same way `parseDeckPayload` already does for real saved
 * decks, without coupling to DECK_PAYLOAD_VERSION itself).
 *
 * Two other responsibilities live here, both keyed off the exact same `isProjectEmpty`
 * true->false/false->true transition this hook already has to watch for the debounced-write
 * gate, rather than each growing its own separate effect:
 *  - The restore nudge (F1's own second half): when `/display` mounts (or the project is cleared)
 *    with an EMPTY project and a non-empty draft already sitting in `localStorage`, `restorableDraft`
 *    is populated so DisplayPage's `DeckInputLanding` can offer a one-line "Restore your unsaved
 *    work?" affordance - the draft is a genuine crash/OOM safety net, so this never auto-restores
 *    without the user's say-so, and dismissing it only hides the banner for this session, it does
 *    NOT delete the underlying draft.
 *  - `notifyPromoteDraftPrePrint` - D9(2)'s promotion nudge ("draft backed up - name and save it?")
 *    at the PRE-PRINT moment; PrePrintSaveGate.tsx calls this once per print attempt. The POST-IMPORT
 *    half of the same nudge fires automatically, right here, off the empty->populated transition -
 *    the same shape as SavedDeckPanel.tsx's own anonymous-to-login "adopt your project" toast,
 *    reusing the same plain-informational Toasts system (no action button - the message points at
 *    the Finish footer's "Save Deck" button, exactly like that existing precedent).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppDispatch, useAppSelector } from "@/common/types";
import {
  buildDeckPayload,
  DeckPayloadContent,
  projectFromDeckPayload,
} from "@/features/savedDecks/deckPayload";
import {
  loadFinishSettings,
  selectFinishSettings,
} from "@/store/slices/finishSettingsSlice";
import {
  loadProject,
  selectIsProjectEmpty,
  selectManualOverrides,
  selectProjectCardback,
  selectProjectMembers,
} from "@/store/slices/projectSlice";
import { setNotification } from "@/store/slices/toastsSlice";
import { RootState } from "@/store/store";

/** Not `deckPayload.ts`'s own `DECK_PAYLOAD_VERSION` - a separate, small counter for this hook's
 * own wrapper shape, per this file's own module comment. Bump alongside a new upgrade branch in
 * `parseStoredDraft` below if `StoredDraft`'s own shape ever changes. */
const DRAFT_FORMAT_VERSION = 1;

const DRAFT_STORAGE_KEY = "mpc-autofill-project-draft";

/** Debounce window between the last project mutation and the actual `localStorage` write - long
 * enough that a burst of rapid edits (typing a decklist, dragging several slots) coalesces into
 * one write, short enough that a crash moments after the last edit still has something recent to
 * recover. */
const DEBOUNCE_MS = 800;

interface StoredDraft {
  draftVersion: typeof DRAFT_FORMAT_VERSION;
  savedAt: string;
  payload: DeckPayloadContent;
}

export interface ProjectDraftSummary {
  memberCount: number;
  savedAt: string;
}

export interface UseProjectDraftBackupResult {
  /** True once this hook has actually written a draft THIS session - drives the Finish footer's
   * compact "✓ Draft backed up locally" note (D9's footer copy). Never true for an anonymous
   * empty project - there is nothing to back up yet. */
  hasBackedUpThisSession: boolean;
  /** Non-null only while the project is empty AND a real, non-empty draft is sitting in
   * `localStorage` from an earlier session - DeckInputLanding's own restore-nudge banner reads
   * this directly. */
  restorableDraft: ProjectDraftSummary | null;
  /** Rehydrates the current project + finish settings from the stored draft. No-op if there is
   * nothing restorable. */
  restoreDraft: () => void;
  /** Hides the restore-nudge banner for the rest of this session WITHOUT deleting the underlying
   * draft - it stays as a genuine safety net in case the user changes their mind, or a real crash
   * still needs it. */
  dismissRestoreDraft: () => void;
  /** Synchronous, non-debounced write - PrePrintSaveGate's own "flush the draft first" step
   * (D9(3)a), so the safety net is guaranteed current the instant before any PDF render begins,
   * rather than racing the debounce window above. */
  flushDraftNow: () => void;
  /** D9(2)'s promotion nudge, PRE-PRINT half - PrePrintSaveGate calls this once per print
   * attempt, right before the persist step it gates on. The POST-IMPORT half fires automatically
   * from this hook's own empty->populated transition effect, below. */
  notifyPromoteDraftPrePrint: () => void;
}

function readStoredDraft(): StoredDraft | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
    if (raw == null) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (
      parsed?.draftVersion !== DRAFT_FORMAT_VERSION ||
      !Array.isArray(parsed?.payload?.members) ||
      parsed.payload.members.length === 0
    ) {
      return null;
    }
    return parsed as StoredDraft;
  } catch {
    // Corrupted/foreign localStorage content - treat exactly like "no draft", this hook's own
    // best-effort contract (see the module comment: it's a safety net, never a hard dependency).
    return null;
  }
}

const PROMOTE_NUDGE_MESSAGE =
  "Your project is backed up in this browser only - use Save Deck below to keep it permanently.";

export function useProjectDraftBackup(): UseProjectDraftBackupResult {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const projectMembers = useAppSelector(selectProjectMembers);
  const projectCardback = useAppSelector(selectProjectCardback);
  const manualOverrides = useAppSelector(selectManualOverrides);
  const finishSettings = useAppSelector(selectFinishSettings);
  const cardDocuments = useAppSelector(
    (state: RootState) => state.cardDocuments.cardDocuments
  );

  const [hasBackedUpThisSession, setHasBackedUpThisSession] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [restorableDraft, setRestorableDraft] =
    useState<ProjectDraftSummary | null>(null);

  const writeDraftNow = useCallback(() => {
    if (isProjectEmpty || typeof window === "undefined") {
      return;
    }
    const content = buildDeckPayload(
      "",
      {
        members: projectMembers,
        nextMemberId: 0,
        cardback: projectCardback ?? null,
        mostRecentlySelectedSlot: null,
        manualOverrides,
      },
      finishSettings,
      cardDocuments
    );
    const draft: StoredDraft = {
      draftVersion: DRAFT_FORMAT_VERSION,
      savedAt: new Date().toISOString(),
      payload: content,
    };
    try {
      window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      setHasBackedUpThisSession(true);
    } catch {
      // Storage quota/private-mode denial - this is a best-effort safety net, never a hard
      // dependency (see module comment); silently skipping a write here is the correct
      // degradation, not a crash.
    }
  }, [
    isProjectEmpty,
    projectMembers,
    projectCardback,
    manualOverrides,
    finishSettings,
    cardDocuments,
  ]);

  // D9(1) - the debounced auto-write. Coalesces a burst of rapid project mutations into one
  // write per DEBOUNCE_MS of quiet, per this file's own module comment.
  useEffect(() => {
    if (isProjectEmpty) {
      return;
    }
    const timeout = setTimeout(writeDraftNow, DEBOUNCE_MS);
    return () => clearTimeout(timeout);
  }, [isProjectEmpty, writeDraftNow]);

  // The restore-nudge check: only ever relevant while the project is EMPTY (a populated project
  // has nothing to "restore" into) and not already dismissed this session.
  useEffect(() => {
    if (!isProjectEmpty || dismissed) {
      setRestorableDraft(null);
      return;
    }
    const stored = readStoredDraft();
    setRestorableDraft(
      stored != null
        ? {
            memberCount: stored.payload.members.length,
            savedAt: stored.savedAt,
          }
        : null
    );
  }, [isProjectEmpty, dismissed]);

  // D9(2)'s promotion nudge, POST-IMPORT half: fires once per session the moment the project
  // flips from empty to populated - the exact same transition-detection shape as
  // SavedDeckPanel.tsx's own anonymous->authenticated "adopt your project" toast, reusing the
  // same plain-informational Toasts system (no action button in that system at all - see
  // Toasts.tsx - so, like that existing precedent, the message points at the footer's own Save
  // Deck button rather than embedding an action here).
  const firedPostImportNudge = useRef(false);
  const previousIsProjectEmpty = useRef(isProjectEmpty);
  useEffect(() => {
    const was = previousIsProjectEmpty.current;
    if (
      was === true &&
      isProjectEmpty === false &&
      !firedPostImportNudge.current
    ) {
      firedPostImportNudge.current = true;
      dispatch(
        setNotification([
          "draft-backup-promote-post-import",
          {
            name: "Backed up locally",
            message: PROMOTE_NUDGE_MESSAGE,
            level: "info",
          },
        ])
      );
    }
    previousIsProjectEmpty.current = isProjectEmpty;
  }, [isProjectEmpty, dispatch]);

  const notifyPromoteDraftPrePrint = useCallback(() => {
    dispatch(
      setNotification([
        "draft-backup-promote-pre-print",
        {
          name: "Backed up locally",
          message: PROMOTE_NUDGE_MESSAGE,
          level: "info",
        },
      ])
    );
  }, [dispatch]);

  const restoreDraft = useCallback(() => {
    const stored = readStoredDraft();
    if (stored == null) {
      return;
    }
    const { project, finishSettings: restoredFinishSettings } =
      projectFromDeckPayload({
        ...stored.payload,
        version: 2,
        revision: 0,
        modifiedAt: stored.savedAt,
      });
    dispatch(loadProject(project));
    dispatch(loadFinishSettings(restoredFinishSettings));
    setRestorableDraft(null);
  }, [dispatch]);

  const dismissRestoreDraft = useCallback(() => {
    setDismissed(true);
    setRestorableDraft(null);
  }, []);

  return {
    hasBackedUpThisSession,
    restorableDraft,
    restoreDraft,
    dismissRestoreDraft,
    flushDraftNow: writeDraftNow,
    notifyPromoteDraftPrePrint,
  };
}

/** Test-only escape hatch - a fresh session/tab in real use always starts with no stored draft;
 * this exists so a single jest process can exercise the restore path without polluting other
 * tests' own `localStorage` (mirrors postExportContributionPrompt.ts's own reset-for-tests
 * precedent). */
export function clearStoredProjectDraftForTests(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(DRAFT_STORAGE_KEY);
  }
}
