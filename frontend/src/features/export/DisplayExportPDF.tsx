/**
 * The editor's PDF export item - `DisplayExportMenu.tsx`'s fourth entry, alongside XML/Card
 * Images/Decklist. This page's own centre sheet already IS the export preview (a real
 * `computeLayout()`-driven `PagePreview`, not a mockup), so this component deliberately mounts
 * no preview of its own: no `PDFCanvasPreview` (pdf.js canvas rendering), no fast DOM preview
 * like `PDFGenerator.tsx`'s - either would make this page pay a render cost the sheet the user is
 * already looking at makes redundant.
 *
 * Props come from `displayPdfProps.ts`'s `useDisplayPDFProps` - the one adapter from this page's
 * live sheet settings to the `PDFProps` shape `PDF.tsx` already consumes.
 *
 * Generation and destination are two independent steps (`pdfDownload.tsx`'s own module comment):
 * clicking "PDF" only renders - it decides nothing about where the file goes. Once the render
 * settles, this component's own progress/ready modal offers "Save to disk" and, when Google
 * Drive is configured, "Save to Google Drive" on the SAME blob; picking either one never
 * re-renders. Both buttons still run through `runExportGate` (`usePrePrintSaveGate.startPrintFlow`,
 * threaded down from `DisplayPage.tsx` via `FinishFooter`/`DisplayExportMenu`) before generation
 * starts - the draft-flush, cardback-reminder, and save-before-export gate that used to run only
 * ahead of a `/print` navigation.
 *
 * Dismissing the progress/ready modal (its own header close button, distinct from the disabled
 * backdrop/Escape dismissal below) never cancels the render - it moves the whole thing into
 * `PdfExportQueuePanel`, a small bottom-right corner surface the user can reopen, save from, or
 * cancel outright. The panel's OWN close button is the real removal action (cancel while
 * rendering, discard while ready) - see its own module comment for why the two X buttons mean
 * different things at different levels.
 */
import React, { useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Dropdown from "react-bootstrap/Dropdown";
import Modal from "react-bootstrap/Modal";
import { createPortal } from "react-dom";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { Icon, RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { useDoFileDownload } from "@/features/download/download";
import { PdfExportQueuePanel } from "@/features/export/PdfExportQueuePanel";
import { PostExportContributionPrompt } from "@/features/export/PostExportContributionPrompt";
import { wasLatestCardsPdfDownloadSuccessful } from "@/features/export/postExportContributionPrompt";
import { usePostExportContributionPrompt } from "@/features/export/usePostExportContributionPrompt";
import { isGoogleDriveAppConfigured } from "@/features/googleDrive/googleDriveConfig";
import {
  DisplaySheetExportSettings,
  useDisplayPDFProps,
} from "@/features/pdf/displayPdfProps";
import {
  ConfirmDespiteFailures,
  ImageFailureConfirmModal,
  renderCardsPdf,
  saveCardsPdfToDisk,
  saveCardsPdfToDrive,
} from "@/features/pdf/pdfDownload";
import { ImageFetchFailure } from "@/features/pdf/pdfImage";
import {
  derivePDFWaitPhase,
  PDFImageFetchProgress,
  PDFProgressBox,
  PDFWaitGameEmbed,
} from "@/features/pdf/PDFWaitPanel";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

export interface DisplayExportPDFProps {
  sheetSettings: DisplaySheetExportSettings;
  /** `usePrePrintSaveGate.startPrintFlow` - runs the draft-flush/cardback-reminder/save-before-
   * export gate sequence, then calls the proceed callback given to it. Wraps this component's own
   * PDF generation button so that sequence still runs on every export, now that the Finish
   * footer no longer routes anywhere to reach it (see FinishFooter.tsx's own comment). */
  runExportGate: (proceed: () => void) => void;
}

type Phase =
  | { kind: "idle" }
  | { kind: "rendering"; imageFetchProgress: PDFImageFetchProgress | null }
  | { kind: "ready"; blob: Blob };

export function DisplayExportPDF({
  sheetSettings,
  runExportGate,
}: DisplayExportPDFProps) {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const { clientSearchService } = useClientSearchContext();
  const driveConfigured = isGoogleDriveAppConfigured();

  const pdfProps = useDisplayPDFProps(sheetSettings);

  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  // Minimized to the corner queue panel rather than showing the blocking modal - see the module
  // comment for the two-levels-of-dismissal split. Never implies cancellation on its own.
  const [backgrounded, setBackgrounded] = useState(false);
  // Only true while there's an in-flight worker call left to actually cancel - see
  // renderCardsPdf's own onRenderSettled comment.
  const [canCancel, setCanCancel] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);

  const [isSavingToDisk, setIsSavingToDisk] = useState(false);
  const [isSavingToDrive, setIsSavingToDrive] = useState(false);
  const doSaveToDisk = useDoFileDownload();
  const doSaveToDrive = useDoFileDownload();

  const [pendingFailureConfirm, setPendingFailureConfirm] = useState<{
    failures: Array<ImageFetchFailure>;
    resolve: (value: boolean) => void;
  } | null>(null);
  const confirmDespiteFailures: ConfirmDespiteFailures = (failures) =>
    new Promise((resolve) => setPendingFailureConfirm({ failures, resolve }));

  const contributionPrompt = usePostExportContributionPrompt();

  const waitPhase = derivePDFWaitPhase(
    phase.kind === "rendering",
    phase.kind === "rendering" ? phase.imageFetchProgress : null
  );

  const startGeneration = () => {
    setPhase({ kind: "rendering", imageFetchProgress: null });
    setCanCancel(true);
    const { outcome, cancel } = renderCardsPdf(
      pdfProps,
      clientSearchService,
      dispatch,
      backendURL,
      (imageFetchProgress) =>
        setPhase((prev) =>
          prev.kind === "rendering" ? { ...prev, imageFetchProgress } : prev
        ),
      confirmDespiteFailures,
      () => setCanCancel(false)
    );
    cancelRef.current = cancel;
    outcome.then((result) => {
      cancelRef.current = null;
      if (result.status === "ready") {
        setPhase({ kind: "ready", blob: result.blob });
      } else {
        setPhase({ kind: "idle" });
        setBackgrounded(false);
      }
    });
  };

  const closeAndReset = () => {
    setPhase({ kind: "idle" });
    setBackgrounded(false);
  };

  // The queue panel's own close button - a real removal, not a minimize. Cancels the in-flight
  // worker call if there's one left to cancel; otherwise (nothing running, or the failure-
  // confirm modal already owns the decision) it's a plain discard.
  const discardOrCancel = () => {
    if (phase.kind === "rendering") {
      if (canCancel) {
        cancelRef.current?.();
      }
      return;
    }
    closeAndReset();
  };

  const handleSaveToDisk = () => {
    if (phase.kind !== "ready") {
      return;
    }
    const { blob } = phase;
    setIsSavingToDisk(true);
    doSaveToDisk("pdf", "cards.pdf", () =>
      saveCardsPdfToDisk(blob, clientSearchService)
    )
      .then(() => {
        if (wasLatestCardsPdfDownloadSuccessful()) {
          contributionPrompt.notifyExportSucceeded();
        }
      })
      .finally(() => {
        setIsSavingToDisk(false);
        closeAndReset();
      });
  };

  const handleSaveToDrive = () => {
    if (phase.kind !== "ready") {
      return;
    }
    const { blob } = phase;
    setIsSavingToDrive(true);
    doSaveToDrive("pdf", "cards.pdf", () => saveCardsPdfToDrive(blob))
      .then(() => {
        if (wasLatestCardsPdfDownloadSuccessful()) {
          contributionPrompt.notifyExportSucceeded();
        }
      })
      .finally(() => {
        setIsSavingToDrive(false);
        closeAndReset();
      });
  };

  const readyBlobActions = (
    <div className="d-grid gap-2 mt-3">
      <Button
        variant="primary"
        disabled={isSavingToDisk || isSavingToDrive}
        onClick={handleSaveToDisk}
        data-testid="display-export-pdf-save-disk-button"
      >
        {isSavingToDisk ? <Spinner size={1} /> : "Save to disk"}
      </Button>
      {driveConfigured && (
        <Button
          variant="outline-primary"
          disabled={isSavingToDisk || isSavingToDrive}
          onClick={handleSaveToDrive}
          data-testid="display-export-pdf-save-drive-button"
        >
          {isSavingToDrive ? <Spinner size={1} /> : "Save to Google Drive"}
        </Button>
      )}
    </div>
  );

  return (
    <>
      <Dropdown.Item
        disabled={isProjectEmpty || phase.kind !== "idle"}
        data-testid="display-export-pdf-button"
        onClick={() => {
          runExportGate(() => startGeneration());
        }}
      >
        <RightPaddedIcon bootstrapIconName="file-pdf" />
        {phase.kind === "rendering" ? <Spinner size={1} /> : "PDF"}
      </Dropdown.Item>
      {/* Blocks interaction (static backdrop, no keyboard/close dismiss) - the click-again
          impulse issue #811 describes has nowhere to land while this is up. Its own header close
          button is the one way out, and it always minimizes to PdfExportQueuePanel rather than
          cancelling or discarding anything - see the module comment. */}
      <Modal
        show={phase.kind !== "idle" && !backgrounded}
        backdrop="static"
        keyboard={false}
        onHide={() => undefined}
        data-testid="display-export-pdf-progress-modal"
      >
        <Modal.Header>
          <Modal.Title>
            {phase.kind === "ready"
              ? "Your PDF is ready"
              : "Generating your PDF"}
          </Modal.Title>
          <Button
            variant="link"
            className="p-0 ms-auto text-muted"
            aria-label="Continue in background"
            onClick={() => setBackgrounded(true)}
            data-testid="display-export-pdf-minimize-button"
          >
            <Icon bootstrapIconName="dash-square" />
          </Button>
        </Modal.Header>
        <Modal.Body>
          {phase.kind === "rendering" && (
            <>
              <PDFProgressBox
                phase={waitPhase}
                imageFetchProgress={phase.imageFetchProgress}
              />
              {(waitPhase === "fetching" || waitPhase === "assembling") && (
                <PDFWaitGameEmbed
                  phase={waitPhase}
                  imageFetchProgress={phase.imageFetchProgress}
                />
              )}
            </>
          )}
          {phase.kind === "ready" && (
            <>
              <p className="mb-0">
                Choose where to save <code>cards.pdf</code>.
              </p>
              {readyBlobActions}
            </>
          )}
        </Modal.Body>
      </Modal>
      <ImageFailureConfirmModal
        failures={pendingFailureConfirm?.failures ?? null}
        onCancel={() => {
          pendingFailureConfirm?.resolve(false);
          setPendingFailureConfirm(null);
        }}
        onContinue={() => {
          pendingFailureConfirm?.resolve(true);
          setPendingFailureConfirm(null);
        }}
      />
      {/* Portalled to document.body, not rendered in place: this component lives inside
          <Dropdown.Menu>, which Bootstrap sets to `display:none` the moment the dropdown itself
          closes (react-bootstrap auto-closes it on item selection) - a plain in-tree node would
          be invisible the instant the user picked "PDF", same class of bug SelectVersionResults
          .tsx's own FloatFiltersPortalRoot comment documents for a sibling case. Bottom-LEFT
          (`start`), matching Toasts.tsx's own sitewide `position="bottom-start"` convention -
          the editor's own Export controls live in the right rail, so a bottom-right placement
          would sit on top of them for the rest of the session (the prompt has no auto-hide) -
          and PdfExportQueuePanel below deliberately claims that bottom-right corner instead, so
          the two never collide. */}
      {contributionPrompt.visible &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="position-fixed bottom-0 start-0 p-3"
            style={{ zIndex: 1080, maxWidth: 380 }}
            data-testid="post-export-contribution-prompt-container"
          >
            <PostExportContributionPrompt
              show={contributionPrompt.visible}
              onDismiss={contributionPrompt.dismiss}
            />
          </div>,
          document.body
        )}
      {backgrounded &&
        phase.kind !== "idle" &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="position-fixed bottom-0 end-0 p-3"
            style={{ zIndex: 1080 }}
            data-testid="pdf-export-queue-container"
          >
            <PdfExportQueuePanel
              state={
                phase.kind === "rendering"
                  ? {
                      kind: "rendering",
                      imageFetchProgress: phase.imageFetchProgress,
                    }
                  : { kind: "ready" }
              }
              canCancel={phase.kind === "rendering" && canCancel}
              driveConfigured={driveConfigured}
              isSavingToDisk={isSavingToDisk}
              isSavingToDrive={isSavingToDrive}
              onExpand={() => setBackgrounded(false)}
              onCancel={() => cancelRef.current?.()}
              onDiscard={discardOrCancel}
              onSaveToDisk={handleSaveToDisk}
              onSaveToDrive={handleSaveToDrive}
            />
          </div>,
          document.body
        )}
    </>
  );
}
