/**
 * Proposal H ADDENDUM D9(3)/F3 (docs/proposals/proposal-h-display-layout-spec.md, issue #275) -
 * the pre-print save gate. Pressing the Finish footer's "Print / Export →" runs a persist step
 * FIRST, before any navigation (and therefore any PDF render) begins:
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
 *   (c) only after persistence resolves (Save completes, or Skip/no-save-needed) does
 *       client-side navigation to the Print page (D10, pages/print.tsx) begin.
 *
 * "Saving gates PDF; PDF never gates saving" (D9's own summary line) - this hook never blocks on
 * anything PDF-related, only on the save choice itself, and an anonymous or clean (non-dirty)
 * session skips the prompt entirely and navigates immediately - the gate only ever appears when
 * there is genuinely something unsaved to decide about.
 *
 * Dismissing the prompt (close button/Escape/backdrop) is treated as cancelling the WHOLE print
 * attempt, not as an implicit Skip - the user stays on /display with nothing navigated and
 * nothing saved, which is the safer default for a modal that isn't itself a forced,
 * no-cancel-option safety net (unlike LoadSafetyModal, which never offers a plain dismiss).
 */
import { useRouter } from "next/router";
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { useAppSelector } from "@/common/types";
import { selectIsCurrentProjectDirty } from "@/features/savedDecks/selectors";
import { useSaveDeckFlow } from "@/features/savedDecks/useSaveDeckFlow";
import { useGetWhoamiQuery } from "@/store/api";

/** The Print page's own route (D10/F5 - pages/print.tsx, a thin wrapper mounting
 * FinishedMyProject/PrintPanel). */
const PRINT_PAGE_ROUTE = "/print";

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
  /** The Finish footer's "Print / Export →" `onClick` - runs the full D9(3) sequence. */
  startPrintFlow: () => void;
}

export function usePrePrintSaveGate({
  flushDraftNow,
  notifyPromoteDraftPrePrint,
}: UsePrePrintSaveGateOptions): UsePrePrintSaveGateResult {
  const router = useRouter();
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const isProjectDirty = useAppSelector(selectIsCurrentProjectDirty);
  const saveFlow = useSaveDeckFlow();

  const [showPrompt, setShowPrompt] = useState(false);

  const proceedToPrint = () => {
    router.push(PRINT_PAGE_ROUTE);
  };

  const startPrintFlow = () => {
    // D9(3)a - flush first, unconditionally, before any branch below. D9(2)'s pre-print
    // promotion nudge rides the same moment.
    flushDraftNow();
    notifyPromoteDraftPrePrint();

    if (isAuthenticated && isProjectDirty) {
      setShowPrompt(true);
    } else {
      // Nothing dirty to offer saving (or no account to save to at all) - navigate immediately.
      // "PDF never gates saving" cuts both ways: saving never gates a print attempt that has
      // nothing new to save either.
      proceedToPrint();
    }
  };

  const handleSave = () => {
    setShowPrompt(false);
    saveFlow.triggerSave(proceedToPrint);
  };

  const handleSkip = () => {
    setShowPrompt(false);
    proceedToPrint();
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
    </>
  );

  return { element, startPrintFlow };
}
