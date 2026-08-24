/**
 * The PDF render/save orchestration used by the editor's export item (`DisplayExportPDF.tsx`).
 * Generation and destination are two independent steps here, not one: `renderCardsPdf` produces
 * a `Blob` and nothing else, and `saveCardsPdfToDisk`/`saveCardsPdfToDrive` each take that same
 * blob and place it somewhere. A caller that picks "Save to Drive" after already rendering never
 * re-renders - it just uploads the blob the render step already produced.
 */
import React from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { downloadFile } from "@/features/download/download";
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

export type CardsPdfRenderOutcome =
  | { status: "ready"; blob: Blob }
  | { status: "declined" }
  | { status: "cancelled" };

export interface CancellableCardsPdfRender {
  outcome: Promise<CardsPdfRenderOutcome>;
  /** Hard-cancels the render - see pdfRenderService.terminateAndReinitialise's own comment for
   * why this has to kill and replace the worker rather than something more surgical. Only
   * meaningful up until `onRenderSettled` fires; the render's own CPU/network work is done by
   * then; calling this after that point kills a worker with nothing left to cancel. */
  cancel: () => void;
}

/**
 * The generation step alone - produces a `Blob`, decides nothing about where it goes.
 * `onRenderSettled` fires the instant the worker call itself resolves (before the failure-
 * confirm step, if there is one) - a caller uses it to know cancellation is no longer possible,
 * since there's no in-progress worker call left to cancel from that point on.
 */
export const renderCardsPdf = (
  props: Omit<PDFProps, "fileHandles">,
  clientSearchService: ClientSearchService,
  dispatch: AppDispatch,
  backendURL: string | null,
  setProgress: (progress: { completed: number; total: number } | null) => void,
  confirmDespiteFailures: ConfirmDespiteFailures,
  onRenderSettled: () => void
): CancellableCardsPdfRender => {
  let cancelled = false;
  let notifyCancelled: () => void = () => undefined;
  const cancelSignal = new Promise<"cancelled">((resolve) => {
    notifyCancelled = () => resolve("cancelled");
  });

  const cancel = () => {
    if (cancelled) {
      return;
    }
    cancelled = true;
    pdfRenderService.terminateAndReinitialise();
    notifyCancelled();
  };

  const run = async (): Promise<CardsPdfRenderOutcome> => {
    const fileHandles = await clientSearchService.getFileHandlesByIdentifier(
      props.cardDocumentsByIdentifier
    );
    dispatch(
      setNotification([
        Math.random().toString(),
        {
          name: "Generating PDF",
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
    if (cancelled) {
      return { status: "cancelled" };
    }
    const { blob, failures: rawFailures } = await pdfRenderService.renderPDF({
      ...props,
      fileHandles,
      bleedPriors,
    });
    setProgress(null);
    onRenderSettled();
    if (cancelled) {
      return { status: "cancelled" };
    }
    const failures = dedupeFailuresByIdentifier(rawFailures);
    if (failures.length > 0 && !(await confirmDespiteFailures(failures))) {
      dispatch(
        setNotification([
          Math.random().toString(),
          {
            name: "Export Cancelled",
            message: `${failures.length} card image${
              failures.length === 1 ? "" : "s"
            } failed to load - PDF was not generated.`,
            level: "warning",
          },
        ])
      );
      return { status: "declined" };
    }
    return { status: "ready", blob };
  };

  const outcome = Promise.race([
    run(),
    cancelSignal.then((): CardsPdfRenderOutcome => ({ status: "cancelled" })),
  ]);
  return { outcome, cancel };
};

/** Places an already-rendered blob on disk - the destination half of the old `downloadPDF`,
 * split out so choosing it never re-renders a document that already exists. */
export const saveCardsPdfToDisk = async (
  blob: Blob,
  clientSearchService: ClientSearchService
): Promise<boolean> => {
  await downloadFile(blob, undefined, "cards.pdf", clientSearchService);
  return true;
};

/** Places an already-rendered blob in the user's Google Drive - the destination half of the old
 * `saveToDrivePDF`, split out for the same reason as `saveCardsPdfToDisk`. */
export const saveCardsPdfToDrive = async (blob: Blob): Promise<boolean> => {
  const token = await requestGoogleDriveWriteToken(
    process.env.NEXT_PUBLIC_GOOGLE_DRIVE_CLIENT_ID as string
  );
  await new GoogleDriveService(token).uploadFile({
    name: "cards.pdf",
    blob,
    mimeType: "application/pdf",
  });
  return true;
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
