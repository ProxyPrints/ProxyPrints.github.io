/**
 * The editor's PDF export item - `DisplayExportMenu.tsx`'s fourth entry, alongside XML/Card
 * Images/Decklist. This page's own centre sheet already IS the export preview (a real
 * `computeLayout()`-driven `PagePreview`, not a mockup), so this component deliberately mounts
 * no preview of its own: no `PDFCanvasPreview` (pdf.js canvas rendering), no fast DOM preview
 * like `PDFGenerator.tsx`'s - either would make this page pay a render cost the sheet the user is
 * already looking at makes redundant.
 *
 * Props come from `displayPdfProps.ts`'s `useDisplayPDFProps` - the one adapter from this page's
 * live sheet settings to the `PDFProps` shape `PDF.tsx` already consumes. The actual download and
 * Google Drive save are `pdfDownload.tsx`'s `useDownloadPDF`/`useSaveToDrivePDF`, the exact same
 * hooks `/print`'s `PDFGenerator.tsx` uses for its own Download/Save-to-Drive buttons (the Drive
 * button is gated behind the same `isGoogleDriveAppConfigured()` check that file uses). Nothing
 * about the render pipeline is forked; only the source of its props and the trigger UI differ.
 * Both buttons run through `runExportGate` (`usePrePrintSaveGate.startPrintFlow`, threaded down
 * from `DisplayPage.tsx` via `FinishFooter`/`DisplayExportMenu`) before the actual export starts -
 * the draft-flush, cardback-reminder, and save-before-export gate that used to run only ahead of
 * a `/print` navigation.
 *
 * Every export-time setting this dialog once held - Silhouette/SCM cutting mode, image DPI/JPG
 * quality, corner rounding, the guide colour/length/thickness/offset/crosshair controls, the
 * page-level guillotine cut guide lines, card selection mode, page range, and the advanced
 * per-side page-margin override - has migrated OUT of this settings step into the right rail,
 * where each one is editable next to the live sheet it governs rather than behind the Export PDF
 * dialog - see `displayPdfProps.ts`'s `DisplaySheetExportSettings` for where every migrated field
 * lives now. This settings step is now just the download/Save-to-Drive trigger and its associated
 * progress/failure modals; it holds no settings of its own. Plain Bootstrap form controls only
 * (no `AutofillCollapse`/`StyledDropdownTreeSelect`/`NumericField` from `PDFGenerator.tsx`) so
 * this component stays free of that file's own import graph.
 */
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Dropdown from "react-bootstrap/Dropdown";
import Modal from "react-bootstrap/Modal";
import { createPortal } from "react-dom";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
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
  useDownloadPDF,
  useSaveToDrivePDF,
} from "@/features/pdf/pdfDownload";
import { ImageFetchFailure } from "@/features/pdf/pdfImage";
import {
  derivePDFWaitPhase,
  PDFProgressBox,
  PDFWaitGameEmbed,
} from "@/features/pdf/PDFWaitPanel";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

export interface DisplayExportPDFProps {
  sheetSettings: DisplaySheetExportSettings;
  /** `usePrePrintSaveGate.startPrintFlow` - runs the draft-flush/cardback-reminder/save-before-
   * export gate sequence, then calls the proceed callback given to it. Wraps this component's own
   * Download/Save-to-Drive buttons so that sequence still runs on every export, now that the
   * Finish footer no longer routes anywhere to reach it (see FinishFooter.tsx's own comment). */
  runExportGate: (proceed: () => void) => void;
}

export function DisplayExportPDF({
  sheetSettings,
  runExportGate,
}: DisplayExportPDFProps) {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const { clientSearchService } = useClientSearchContext();

  const [showSettings, setShowSettings] = useState<boolean>(false);

  const pdfProps = useDisplayPDFProps(sheetSettings);

  const [isDownloading, setIsDownloading] = useState<boolean>(false);
  const [isSavingToDrive, setIsSavingToDrive] = useState<boolean>(false);
  const [imageFetchProgress, setImageFetchProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  const [pendingFailureConfirm, setPendingFailureConfirm] = useState<{
    failures: Array<ImageFetchFailure>;
    resolve: (value: boolean) => void;
  } | null>(null);
  const confirmDespiteFailures: ConfirmDespiteFailures = (failures) =>
    new Promise((resolve) => setPendingFailureConfirm({ failures, resolve }));

  const generating = isDownloading || isSavingToDrive;
  const waitPhase = derivePDFWaitPhase(generating, imageFetchProgress);
  const contributionPrompt = usePostExportContributionPrompt();

  const downloadPDF = useDownloadPDF(
    pdfProps,
    clientSearchService,
    dispatch,
    setIsDownloading,
    backendURL,
    setImageFetchProgress,
    confirmDespiteFailures
  );

  // Reuses the exact same shared hook /print's PDFGenerator.tsx uses for its own "Save PDF to
  // Google Drive" button - no forked upload logic, see pdfDownload.tsx's own module comment.
  const saveToDrive = useSaveToDrivePDF(
    pdfProps,
    clientSearchService,
    dispatch,
    setIsSavingToDrive,
    backendURL,
    setImageFetchProgress,
    confirmDespiteFailures
  );

  return (
    <>
      <Dropdown.Item
        disabled={isProjectEmpty || isDownloading}
        data-testid="display-export-pdf-button"
        onClick={() => setShowSettings(true)}
      >
        <RightPaddedIcon bootstrapIconName="file-pdf" />
        {isDownloading ? <Spinner size={1} /> : "PDF"}
      </Dropdown.Item>
      <Modal
        show={showSettings}
        onHide={() => setShowSettings(false)}
        data-testid="display-export-pdf-settings-modal"
      >
        <Modal.Header closeButton>
          <Modal.Title>Export PDF</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Ready to export - every setting for this PDF lives in the right rail.
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowSettings(false)}>
            Cancel
          </Button>
          {isGoogleDriveAppConfigured() && (
            <Button
              variant="outline-primary"
              disabled={isDownloading || isSavingToDrive}
              data-testid="display-export-pdf-drive-button"
              onClick={() => {
                setShowSettings(false);
                runExportGate(() => {
                  saveToDrive().then((succeeded) => {
                    if (succeeded === true) {
                      contributionPrompt.notifyExportSucceeded();
                    }
                  });
                });
              }}
            >
              {isSavingToDrive ? (
                <Spinner size={1} />
              ) : (
                "Save PDF to Google Drive"
              )}
            </Button>
          )}
          <Button
            variant="primary"
            disabled={isDownloading || isSavingToDrive}
            data-testid="display-export-pdf-download-button"
            onClick={() => {
              setShowSettings(false);
              runExportGate(() => {
                downloadPDF().then(() => {
                  if (wasLatestCardsPdfDownloadSuccessful()) {
                    contributionPrompt.notifyExportSucceeded();
                  }
                });
              });
            }}
          >
            {isDownloading ? <Spinner size={1} /> : "Download PDF"}
          </Button>
        </Modal.Footer>
      </Modal>
      {/* Blocks interaction (static backdrop, no keyboard/close dismiss) for the render's actual
          duration - the same click-again impulse issue #811 describes has nowhere to land while
          this is up. Shown purely off `generating`, so it clears itself the instant the render
          settles (success, cancellation, or error) with no separate "done" state to dismiss. */}
      <Modal
        show={generating}
        backdrop="static"
        keyboard={false}
        onHide={() => undefined}
        data-testid="display-export-pdf-progress-modal"
      >
        <Modal.Header>
          <Modal.Title>Generating your PDF</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <PDFProgressBox
            phase={waitPhase}
            imageFetchProgress={imageFetchProgress}
          />
          {(waitPhase === "fetching" || waitPhase === "assembling") && (
            <PDFWaitGameEmbed
              phase={waitPhase}
              imageFetchProgress={imageFetchProgress}
            />
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
          would sit on top of them for the rest of the session (the prompt has no auto-hide). */}
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
    </>
  );
}
