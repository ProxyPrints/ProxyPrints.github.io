/**
 * Proposal H ADDENDUM D9(3)/F3 (docs/proposals/proposal-h-display-layout-spec.md, issue #275) -
 * the pre-export save gate. Runs a persist step FIRST, before the export action it wraps begins:
 *   (a) flush the local draft synchronously (useProjectDraftBackup's `flushDraftNow`) - never
 *       debounced, so the crash/OOM safety net is guaranteed current the instant before whatever
 *       happens next;
 *   (b) if authenticated AND the project is dirty (savedDeckSessionSlice's own dirty-check,
 *       selectIsCurrentProjectDirty), show a lightweight "Save before printing?" prompt - Save
 *       (opens useSaveDeckFlow.ts's own passphrase-setup/unlock/save chain, the same one the
 *       Finish footer's own Save Deck button and SavedDeckPanel's toolbar Save button use) or
 *       Skip - mirroring LoadSafetyModal.tsx's existing "always take a safety copy before a
 *       destructive step" pattern, here applied to the PDF-render step instead of a deck-load
 *       step;
 *   (c) only after persistence resolves (Save completes, or Skip/no-save-needed) does the
 *       caller-supplied `proceed` callback run.
 *
 * Originally this always ended in a client-side navigation to the Print page (D10,
 * pages/print.tsx). Once Drive save landed on the editor too (see docs/features/pdf-generator.md's
 * "Editor-native PDF export" section), that destination stopped being the only place an export
 * could finish, so `startPrintFlow` takes the export action itself as a `proceed` parameter rather
 * than hardcoding one - its only caller today is `DisplayExportPDF.tsx`'s Download/Save-to-Drive
 * buttons (threaded down via `FinishFooter`/`DisplayExportMenu`), which run the actual export in
 * place instead of navigating away.
 *
 * "Saving gates PDF; PDF never gates saving" (D9's own summary line) - this hook never blocks on
 * anything PDF-related, only on the save choice itself, and an anonymous or clean (non-dirty)
 * session skips the prompt entirely and proceeds immediately - the gate only ever appears when
 * there is genuinely something unsaved to decide about.
 *
 * Dismissing the prompt (close button/Escape/backdrop) is treated as cancelling the WHOLE export
 * attempt, not as an implicit Skip - the user stays on the editor with nothing exported and
 * nothing saved, which is the safer default for a modal that isn't itself a forced,
 * no-cancel-option safety net (unlike LoadSafetyModal, which never offers a plain dismiss).
 *
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.1, `PKG1a`) - a NEW gate step
 * (`useCardbackReminderGate`) now runs FIRST, before this file's own Save/Skip branch: the deck-
 * completeness decision (does the export need a cardback?) precedes the persistence decision.
 * Unlike this Save gate's own dismiss=cancel rule, the cardback reminder's own dismiss semantics
 * are OWNER AMENDMENT 1 (dismiss = "use current & continue", not cancel) - the two gates are
 * deliberately NOT symmetric; see that hook's own module comment for why.
 */
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { useAppSelector } from "@/common/types";
import { useCardbackReminderGate } from "@/features/display/useCardbackReminderGate";
import { selectIsCurrentProjectDirty } from "@/features/savedDecks/selectors";
import { useSaveDeckFlow } from "@/features/savedDecks/useSaveDeckFlow";
import { useGetWhoamiQuery } from "@/store/api";

export interface UsePrePrintSaveGateOptions {
  /** useProjectDraftBackup's own `flushDraftNow` - D9(3)a, always run first. */
  flushDraftNow: () => void;
  /** useProjectDraftBackup's own `notifyPromoteDraftPrePrint` - D9(2)'s promotion nudge,
   * pre-print half, fired alongside the flush. */
  notifyPromoteDraftPrePrint: () => void;
}

export interface UsePrePrintSaveGateResult {
  /** Render this once - the "Save before printing?" prompt plus whatever useSaveDeckFlow.ts's
   * own modal chain needs, all in one place. */
  element: React.ReactElement;
  /** Runs the full D9(3) gate sequence (draft flush, cardback reminder, then the save-before-
   * export prompt if there's something dirty to save), then calls `proceed` - the actual export
   * action, supplied by the caller. */
  startPrintFlow: (proceed: () => void) => void;
}

export function usePrePrintSaveGate({
  flushDraftNow,
  notifyPromoteDraftPrePrint,
}: UsePrePrintSaveGateOptions): UsePrePrintSaveGateResult {
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const isProjectDirty = useAppSelector(selectIsCurrentProjectDirty);
  const saveFlow = useSaveDeckFlow();
  const cardbackReminderGate = useCardbackReminderGate();

  const [showPrompt, setShowPrompt] = useState(false);
  const [pendingProceed, setPendingProceed] = useState<
    (() => void) | undefined
  >(undefined);

  const runSaveBranch = (proceed: () => void) => {
    if (isAuthenticated && isProjectDirty) {
      setPendingProceed(() => proceed);
      setShowPrompt(true);
    } else {
      // Nothing dirty to offer saving (or no account to save to at all) - proceed immediately.
      // "PDF never gates saving" cuts both ways: saving never gates an export attempt that has
      // nothing new to save either.
      proceed();
    }
  };

  const startPrintFlow = (proceed: () => void) => {
    // D9(3)a - flush first, unconditionally, before any branch below. D9(2)'s pre-print
    // promotion nudge rides the same moment.
    flushDraftNow();
    notifyPromoteDraftPrePrint();

    // Cardback flow round (SPEC-cardback-pdfwait.md §C.1) - the deck-completeness decision runs
    // BEFORE the persistence decision; `guard` is a no-op (calls `runSaveBranch` immediately) once
    // a cardback has been explicitly chosen or the reminder's already been dismissed this session.
    cardbackReminderGate.guard(() => runSaveBranch(proceed));
  };

  const handleSave = () => {
    setShowPrompt(false);
    const proceed = pendingProceed;
    setPendingProceed(undefined);
    saveFlow.triggerSave(() => proceed?.());
  };

  const handleSkip = () => {
    setShowPrompt(false);
    const proceed = pendingProceed;
    setPendingProceed(undefined);
    proceed?.();
  };

  const element = (
    <>
      <Modal
        show={showPrompt}
        onHide={() => setShowPrompt(false)}
        data-testid="pre-print-save-gate-modal"
      >
        <Modal.Header closeButton>
          <Modal.Title>Save before printing?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p>
            You have unsaved changes. Printing can use a lot of memory, so
            it&apos;s safest to save your deck first - your local draft is
            already backed up, but a real saved deck can be reached from any
            device.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="outline-secondary"
            onClick={handleSkip}
            data-testid="pre-print-save-gate-skip"
          >
            Skip
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            data-testid="pre-print-save-gate-save"
          >
            Save
          </Button>
        </Modal.Footer>
      </Modal>
      {saveFlow.element}
      {cardbackReminderGate.element}
    </>
  );

  return { element, startPrintFlow };
}
