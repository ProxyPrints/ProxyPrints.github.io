/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.1, `PKG1a`) - the no-cardback reminder GATE
 * STEP, composed into `usePrePrintSaveGate.startPrintFlow` (before the Save/Skip branch) AND the
 * classic direct "Generate PDF"/"Save PDF to Google Drive" buttons on `PDFGenerator.tsx` (the
 * spec's own coverage note: a user can reach `/print` directly, bypassing the editor's Finish
 * footer entirely, so the reminder needs its own independent guard there too - not just inside
 * `usePrePrintSaveGate`).
 *
 * OWNER AMENDMENT 1 (2026-07-24, supersedes the spec's own `OQ-A` recommendation): dismissing the
 * gate (✕/Esc/backdrop) means "use current default & continue" - the guarded action still runs.
 * There is no cancel path left in this gate at all; "Use current & continue" is a first-class
 * button purely so a keyboard/screen-reader user isn't limited to backdrop/Esc to proceed.
 *
 * Fire condition (`ridingUntouchedDefault`, `CB1`) - at most once per print ATTEMPT, and a
 * per-project sessionStorage suppress (`cardbackReminderSuppression.ts`) makes a second guarded
 * action in the same session silent, mirroring `usePostExportContributionPrompt`'s identical
 * once-per-session shape.
 *
 * R9 (editor-repass round, item 2) - "Choose a cardback" no longer swaps the gate for the full
 * `GridSelectorModal`; it swaps the modal's OWN body to the shared `CardbackSwatchStrip`
 * primitive (the third copy staying, per the R9 ruling, but now using the same strip component
 * as the two rails instead of a bespoke grid). Picking a swatch picks the cardback
 * project-wide (the same `bulkReplaceSelectedImage`/`setSelectedCardback` pair the grid pick
 * used) and proceeds - OWNER AMENDMENT 1's "no cancel path" still applies to the strip mode.
 */
import styled from "@emotion/styled";
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { Back } from "@/common/constants";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { CardbackSwatchStrip } from "@/features/card/CardbackSwatchStrip";
import {
  hasSuppressedCardbackReminderThisSession,
  suppressCardbackReminderThisSession,
  UNSAVED_PROJECT_SUPPRESSION_KEY,
} from "@/features/display/cardbackReminderSuppression";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  bulkReplaceSelectedImage,
  selectIsRidingUntouchedDefaultCardback,
  selectProjectCardback,
  selectProjectMembers,
  setSelectedCardback,
} from "@/store/slices/projectSlice";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";

const CurBackThumbnail = styled.div<{ $url: string | undefined }>`
  flex: 0 0 88px;
  width: 88px;
  aspect-ratio: 63 / 88;
  border: 1px solid rgba(var(--bs-body-color-rgb), 0.15);
  position: relative;
  background-color: #2a2320;
  background-image: ${(props) =>
    props.$url != null ? `url(${props.$url})` : "none"};
  background-size: cover;
  background-position: center;

  .cap {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.6);
    color: #a99;
    font-size: 9px;
    text-align: center;
    padding: 1px;
  }
`;

const ReminderBody = styled.div`
  display: flex;
  gap: 14px;
  align-items: flex-start;
`;

const SeamNote = styled.div`
  margin-top: 10px;
  font-size: 12px;
  color: var(--theme-muted);
  border-top: 1px solid var(--theme-divider);
  padding-top: 8px;

  .seam {
    color: var(--bs-warning);
  }
`;

interface CardbackReminderGateModalProps {
  curBackThumbnailUrl: string | undefined;
  onUseCurrentAndContinue: () => void;
  /** R9 - true once "Choose a cardback" flips the modal body to the swatch strip. */
  stripMode: boolean;
  strip: React.ReactElement;
  onChooseACardback: () => void;
}

function CardbackReminderGateModal({
  curBackThumbnailUrl,
  onUseCurrentAndContinue,
  stripMode,
  strip,
  onChooseACardback,
}: CardbackReminderGateModalProps) {
  return (
    <Modal
      show
      // OWNER AMENDMENT 1 - dismiss (✕/Esc/backdrop, all routed through `onHide`) means "use
      // current & continue", not cancel.
      onHide={onUseCurrentAndContinue}
      data-testid="pre-print-cardback-gate"
    >
      <Modal.Header closeButton>
        <Modal.Title>Pick a cardback before printing?</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {stripMode ? (
          strip
        ) : (
          <>
            <ReminderBody>
              <CurBackThumbnail $url={curBackThumbnailUrl}>
                <span className="cap">Current cardback</span>
              </CurBackThumbnail>
              <div>
                <p>
                  Your deck is still using the <b>default cardback</b>. Most
                  printers put a back on every card - choosing your own is quick
                  and easy to forget.
                </p>
                <div style={{ fontSize: 13, color: "var(--theme-muted)" }}>
                  You can keep the default and continue - this only asks once
                  per print.
                </div>
              </div>
            </ReminderBody>
            <SeamNote>
              The site default cardback (which source&apos;s cardback document
              ships as the fallback) is a{" "}
              <span className="seam">backend/config seed</span> - Annex A-1, not
              designed here.
            </SeamNote>
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button
          variant="outline-light"
          onClick={onUseCurrentAndContinue}
          data-testid="cardback-gate-use-current"
        >
          Use current &amp; continue
        </Button>
        {!stripMode && (
          <Button
            variant="primary"
            onClick={onChooseACardback}
            data-testid="cardback-gate-choose"
          >
            Choose a cardback
          </Button>
        )}
      </Modal.Footer>
    </Modal>
  );
}

export interface UseCardbackReminderGateResult {
  /** Render this once (mirrors `usePrePrintSaveGate`'s own `element` convention) - the reminder
   * Modal, whose body swaps between the reminder copy and the cardback strip. */
  element: React.ReactElement;
  /** Wraps any "about to print/export" action: shows the reminder first if the fire condition
   * holds, otherwise runs `proceed` immediately. */
  guard: (proceed: () => void) => void;
}

export function useCardbackReminderGate(): UseCardbackReminderGateResult {
  const dispatch = useAppDispatch();
  const projectMembers = useAppSelector(selectProjectMembers);
  const ridingUntouchedDefault = useAppSelector(
    selectIsRidingUntouchedDefaultCardback
  );
  const projectCardback = useAppSelector(selectProjectCardback);
  const cardbackSearchResults = useAppSelector(selectCardbacks);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();
  const currentSavedDeck = useAppSelector(selectCurrentSavedDeck);
  const projectKey =
    currentSavedDeck.currentDeckKey ?? UNSAVED_PROJECT_SUPPRESSION_KEY;

  const [showGate, setShowGate] = useState(false);
  const [showStrip, setShowStrip] = useState(false);
  const [pendingProceed, setPendingProceed] = useState<
    (() => void) | undefined
  >(undefined);

  const resolvedCardback =
    projectCardback != null
      ? cardDocumentsByIdentifier[projectCardback]
      : undefined;

  const finishGate = () => {
    suppressCardbackReminderThisSession(projectKey);
    setShowGate(false);
    setShowStrip(false);
    const proceed = pendingProceed;
    setPendingProceed(undefined);
    proceed?.();
  };

  const handleStripSelect = (image: string) => {
    // Same project-wide pair the retired grid pick dispatched, then straight to the guarded
    // action (R9: pick and proceed, no apply prompt in the reminder).
    if (projectCardback != null) {
      dispatch(
        bulkReplaceSelectedImage({
          currentImage: projectCardback,
          selectedImage: image,
          face: Back,
        })
      );
    }
    dispatch(setSelectedCardback({ selectedImage: image, explicit: true }));
    finishGate();
  };

  const guard = (proceed: () => void) => {
    if (
      !ridingUntouchedDefault ||
      projectMembers.length === 0 ||
      hasSuppressedCardbackReminderThisSession(projectKey)
    ) {
      proceed();
      return;
    }
    setPendingProceed(() => proceed);
    setShowGate(true);
  };

  const element = (
    <>
      {showGate && (
        <CardbackReminderGateModal
          curBackThumbnailUrl={resolvedCardback?.smallThumbnailUrl}
          onUseCurrentAndContinue={finishGate}
          onChooseACardback={() => setShowStrip(true)}
          stripMode={showStrip}
          strip={
            <CardbackSwatchStrip
              imageIdentifiers={cardbackSearchResults}
              selectedImage={projectCardback}
              onSelect={handleStripSelect}
              testId="cardback-gate-strip"
            />
          }
        />
      )}
    </>
  );

  return { element, guard };
}
