/**
 * The PDF download/save-to-Drive orchestration shared by every surface that generates a PDF:
 * `/print`'s `PDFGenerator.tsx` (the original home of this code) and the /display editor's own
 * export item (`DisplayExportPDF.tsx`). Extracted so the editor can reuse the exact same
 * pipeline without statically importing `PDFGenerator.tsx` — that module pulls in
 * `PDFCanvasPreview` (pdfjs-dist) and the whole settings panel, which the editor must not pay
 * for (its page has to stay fast; see `DisplayExportPDF.tsx`'s own module comment).
 *
 * Nothing here is reimplemented — every line moved verbatim from `PDFGenerator.tsx`, which now
 * imports these same functions from here. The render engine itself (`PDF.tsx`, `pdf.worker.ts`,
 * `pdfRenderService.ts`) is untouched.
 */
import React from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { downloadFile, useDoFileDownload } from "@/features/download/download";
import { requestGoogleDriveWriteToken } from "@/features/googleDrive/googleDriveAuth";
import { GoogleDriveService } from "@/features/googleDrive/GoogleDriveService";
import { resolveBleedPriors } from "@/features/pdf/bleedPriorResolution";
import { computeExportedCardIdentifiers, PDFProps } from "@/features/pdf/PDF";
import {
  dedupeFailuresByIdentifier,
  ImageFetchFailure,
} from "@/features/pdf/pdfImage";
import { pdfRenderService } from "@/features/pdf/pdfRenderService";
import { setNotification } from "@/store/slices/toastsSlice";
import { AppDispatch } from "@/store/store";

/**
 * @react-pdf/renderer silently skips a card image it can't fetch rather than
 * failing the whole render (see pdfImage.ts) - so a successful render can
 * still contain blank cards. Confirming with the user before committing to
 * the download/upload is the only point this is still cheaply recoverable:
 * once the file is saved, a blank card is easy to miss until it's already
 * been sent off to print.
 *
 * An in-app modal (below, ImageFailureConfirmModal), not the native window.confirm() this used
 * to be - a real incident's screenshot showed Firefox's own "allow notifications?" anti-spam
 * chrome sitting right next to the confirm dialog, which can make a browser auto-suppress
 * FUTURE window.confirm() calls on that origin without any visible warning - silently turning
 * this safeguard off. An in-app modal can't be affected by that browser-level heuristic at all.
 */
export type ConfirmDespiteFailures = (
  failures: Array<ImageFetchFailure>
) => Promise<boolean>;

export const downloadPDF = async (
  props: Omit<PDFProps, "fileHandles">,
  clientSearchService: ClientSearchService,
  dispatch: AppDispatch,
  backendURL: string | null,
  setProgress: (progress: { completed: number; total: number } | null) => void,
  confirmDespiteFailures: ConfirmDespiteFailures
): Promise<boolean> => {
  const fileHandles = await clientSearchService.getFileHandlesByIdentifier(
    props.cardDocumentsByIdentifier
  );
  dispatch(
    setNotification([
      Math.random().toString(),
      {
        name: "Download Started",
        message: "Generating your PDF...",
        level: "info",
      },
    ])
  );
  // Proposal B PR-1: resolved here (main thread, has cookie access for the CSRF header) rather
  // than inside pdf.worker.ts, which can't fetch this itself - see bleedPriorResolution.ts's
  // module comment. Skipped entirely (bleedPriors stays undefined) when no remote backend is
  // configured - PDFCardImage already defaults a missing entry to the safe "unresolved" fallback.
  const bleedPriors =
    backendURL != null
      ? await resolveBleedPriors(
          backendURL,
          computeExportedCardIdentifiers(props)
        )
      : undefined;
  // Registered before the render call, not after - see pdfRenderService.onImageProgress's own
  // comment for why. A large export can take several minutes once full-resolution fetches are
  // paced to the image CDN's shared rate limit (see pdfImage.ts) - this is what turns that wait
  // into "fetching images: N/M" instead of a spinner that looks hung.
  pdfRenderService.onImageProgress((completed, total) =>
    setProgress({ completed, total })
  );
  const { blob, failures: rawFailures } = await pdfRenderService.renderPDF({
    ...props,
    fileHandles,
    bleedPriors,
  });
  setProgress(null);
  const failures = dedupeFailuresByIdentifier(rawFailures);
  if (failures.length > 0 && !(await confirmDespiteFailures(failures))) {
    dispatch(
      setNotification([
        Math.random().toString(),
        {
          name: "Download Cancelled",
          message: `${failures.length} card image${
            failures.length === 1 ? "" : "s"
          } failed to load - PDF was not downloaded.`,
          level: "warning",
        },
      ])
    );
    return false;
  }
  await downloadFile(blob, undefined, "cards.pdf", clientSearchService);
  return true;
};

export const useDownloadPDF = (
  props: Omit<PDFProps, "fileHandles">,
  clientSearchService: ClientSearchService,
  dispatch: AppDispatch,
  setIsDownloading: (newState: boolean) => void,
  backendURL: string | null,
  setProgress: (progress: { completed: number; total: number } | null) => void,
  confirmDespiteFailures: ConfirmDespiteFailures
) => {
  const doFileDownload = useDoFileDownload();
  return () =>
    Promise.resolve(setIsDownloading(true))
      .then(() =>
        doFileDownload(
          "pdf",
          "cards.pdf",
          (): Promise<boolean> =>
            downloadPDF(
              props,
              clientSearchService,
              dispatch,
              backendURL,
              setProgress,
              confirmDespiteFailures
            )
        )
      )
      .finally(() => {
        setIsDownloading(false);
        setProgress(null);
      });
};

export const saveToDrivePDF = async (
  props: Omit<PDFProps, "fileHandles">,
  clientSearchService: ClientSearchService,
  dispatch: AppDispatch,
  backendURL: string | null,
  setProgress: (progress: { completed: number; total: number } | null) => void,
  confirmDespiteFailures: ConfirmDespiteFailures
): Promise<boolean> => {
  const fileHandles = await clientSearchService.getFileHandlesByIdentifier(
    props.cardDocumentsByIdentifier
  );
  dispatch(
    setNotification([
      Math.random().toString(),
      {
        name: "Saving to Google Drive",
        message: "Generating your PDF...",
        level: "info",
      },
    ])
  );
  // See downloadPDF's identical step for why this runs here, not inside the worker.
  const bleedPriors =
    backendURL != null
      ? await resolveBleedPriors(
          backendURL,
          computeExportedCardIdentifiers(props)
        )
      : undefined;
  pdfRenderService.onImageProgress((completed, total) =>
    setProgress({ completed, total })
  );
  const { blob, failures: rawFailures } = await pdfRenderService.renderPDF({
    ...props,
    fileHandles,
    bleedPriors,
  });
  setProgress(null);
  const failures = dedupeFailuresByIdentifier(rawFailures);
  if (failures.length > 0 && !(await confirmDespiteFailures(failures))) {
    dispatch(
      setNotification([
        Math.random().toString(),
        {
          name: "Save Cancelled",
          message: `${failures.length} card image${
            failures.length === 1 ? "" : "s"
          } failed to load - PDF was not saved.`,
          level: "warning",
        },
      ])
    );
    return false;
  }
  const token = await requestGoogleDriveWriteToken(
    process.env.NEXT_PUBLIC_GOOGLE_DRIVE_CLIENT_ID as string
  );
  await new GoogleDriveService(token).uploadFile({
    name: "cards.pdf",
    blob,
    mimeType: "application/pdf",
  });
  dispatch(
    setNotification([
      Math.random().toString(),
      {
        name: "Saved to Google Drive",
        message: "cards.pdf was saved to your Google Drive.",
        level: "info",
      },
    ])
  );
  return true;
};

export const useSaveToDrivePDF = (
  props: Omit<PDFProps, "fileHandles">,
  clientSearchService: ClientSearchService,
  dispatch: AppDispatch,
  setIsSavingToDrive: (newState: boolean) => void,
  backendURL: string | null,
  setProgress: (progress: { completed: number; total: number } | null) => void,
  confirmDespiteFailures: ConfirmDespiteFailures
) => {
  return () =>
    Promise.resolve(setIsSavingToDrive(true))
      .then(() =>
        saveToDrivePDF(
          props,
          clientSearchService,
          dispatch,
          backendURL,
          setProgress,
          confirmDespiteFailures
        )
      )
      .catch((reason) =>
        dispatch(
          setNotification([
            Math.random().toString(),
            {
              name: "Saving to Google Drive Failed",
              message:
                reason instanceof Error ? reason.message : String(reason),
              level: "error",
            },
          ])
        )
      )
      .finally(() => {
        setIsSavingToDrive(false);
        setProgress(null);
      });
};

export interface ImageFailureConfirmModalProps {
  failures: Array<ImageFetchFailure> | null;
  onCancel: () => void;
  onContinue: () => void;
}

/** In-app replacement for window.confirm() - see the module comment above
 * ConfirmDespiteFailures for why. `failures === null` means "nothing pending," rendered as a
 * closed Modal rather than not rendering the component at all, so it can animate closed rather
 * than vanishing abruptly. Exported (Proposal H item 2) so the display page's own inline export
 * reuses this exact modal instead of forking it - same failure-confirmation UX everywhere a PDF
 * gets generated. */
export const ImageFailureConfirmModal = ({
  failures,
  onCancel,
  onContinue,
}: ImageFailureConfirmModalProps) => {
  const shown = (failures ?? []).slice(0, 10);
  const remainder = (failures?.length ?? 0) - shown.length;
  return (
    <Modal
      show={failures != null}
      onHide={onCancel}
      data-testid="image-failure-confirm-modal"
    >
      <Modal.Header closeButton>
        <Modal.Title>Some card images couldn&apos;t be loaded</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p>
          {failures?.length ?? 0} card image
          {(failures?.length ?? 0) === 1 ? "" : "s"} couldn&apos;t be loaded and
          will be blank:
        </p>
        <ul>
          {shown.map((failure) => (
            <li key={failure.identifier}>{failure.label}</li>
          ))}
        </ul>
        {remainder > 0 && (
          <p className="text-muted mb-0">…and {remainder} more</p>
        )}
        <p className="mt-3 mb-0">Continue anyway?</p>
      </Modal.Body>
      <Modal.Footer>
        <Button
          variant="outline-secondary"
          onClick={onCancel}
          data-testid="image-failure-confirm-cancel"
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={onContinue}
          data-testid="image-failure-confirm-continue"
        >
          Continue anyway
        </Button>
      </Modal.Footer>
    </Modal>
  );
};
