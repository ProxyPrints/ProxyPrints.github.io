/**
 * The corner surface a dismissed PDF export moves into (DisplayExportPDF.tsx's own "Continue in
 * background" affordance on its blocking progress modal). Bottom-RIGHT (`end`), the mirror of
 * PostExportContributionPrompt.tsx's own bottom-LEFT placement - the two never occupy the same
 * corner, so a contribution prompt showing from an earlier export can never be covered by this
 * panel, or vice versa.
 *
 * One slot, not a literal multi-item queue: `pdfRenderService` is a single shared worker
 * (pdfRenderService.ts), and DisplayExportPDF.tsx already disables its own "PDF" trigger for the
 * whole time a render is in flight (backgrounded or not) - there is only ever one export to show
 * here at a time by construction, so this panel renders at most one entry.
 */
import styled from "@emotion/styled";
import React from "react";
import Button from "react-bootstrap/Button";
import Card from "react-bootstrap/Card";
import ProgressBar from "react-bootstrap/ProgressBar";

import { Icon, RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { PDFImageFetchProgress } from "@/features/pdf/PDFWaitPanel";

export type PdfExportQueueEntryState =
  | { kind: "rendering"; imageFetchProgress: PDFImageFetchProgress | null }
  | { kind: "ready" };

export interface PdfExportQueuePanelProps {
  state: PdfExportQueueEntryState;
  /** Only offered while `state.kind === "rendering"` AND the underlying worker call hasn't
   * already settled - see renderCardsPdf's own `onRenderSettled` comment. */
  canCancel: boolean;
  driveConfigured: boolean;
  isSavingToDisk: boolean;
  isSavingToDrive: boolean;
  onExpand: () => void;
  onCancel: () => void;
  onDiscard: () => void;
  onSaveToDisk: () => void;
  onSaveToDrive: () => void;
}

const PanelCard = styled(Card)`
  width: 300px;
`;

const ClickableBody = styled(Card.Body)`
  cursor: pointer;
`;

export function PdfExportQueuePanel({
  state,
  canCancel,
  driveConfigured,
  isSavingToDisk,
  isSavingToDrive,
  onExpand,
  onCancel,
  onDiscard,
  onSaveToDisk,
  onSaveToDrive,
}: PdfExportQueuePanelProps) {
  const completed =
    state.kind === "rendering" ? state.imageFetchProgress?.completed ?? 0 : 0;
  const total =
    state.kind === "rendering" ? state.imageFetchProgress?.total ?? 0 : 0;
  const percent = total > 0 ? Math.min((completed / total) * 100, 99) : 0;

  return (
    <PanelCard data-testid="pdf-export-queue-panel">
      <Card.Header className="d-flex align-items-center justify-content-between py-1 px-2">
        <span className="small fw-semibold">
          <RightPaddedIcon bootstrapIconName="file-pdf" />
          {state.kind === "rendering" ? "Generating PDF…" : "PDF ready"}
        </span>
        <Button
          variant="link"
          size="sm"
          className="p-0 text-muted"
          onClick={onDiscard}
          aria-label="Dismiss"
          data-testid="pdf-export-queue-discard"
        >
          <Icon bootstrapIconName="x-lg" />
        </Button>
      </Card.Header>
      <ClickableBody
        className="py-2 px-2"
        onClick={onExpand}
        data-testid="pdf-export-queue-expand"
      >
        {state.kind === "rendering" ? (
          <>
            <div className="d-flex align-items-center gap-2">
              <Spinner size={1} />
              <span className="small text-muted">
                {total > 0
                  ? `Fetching images… ${completed} of ~${total}`
                  : "Working…"}
              </span>
            </div>
            <ProgressBar
              now={percent}
              className="mt-2"
              data-testid="pdf-export-queue-progress"
            />
            {canCancel && (
              <div className="d-grid mt-2">
                <Button
                  variant="outline-danger"
                  size="sm"
                  onClick={(event) => {
                    event.stopPropagation();
                    onCancel();
                  }}
                  data-testid="pdf-export-queue-cancel"
                >
                  Cancel
                </Button>
              </div>
            )}
          </>
        ) : (
          <div
            className="d-flex flex-column gap-2"
            onClick={(event) => event.stopPropagation()}
          >
            <Button
              variant="primary"
              size="sm"
              disabled={isSavingToDisk || isSavingToDrive}
              onClick={onSaveToDisk}
              data-testid="pdf-export-queue-save-disk"
            >
              {isSavingToDisk ? <Spinner size={1} /> : "Save to disk"}
            </Button>
            {driveConfigured && (
              <Button
                variant="outline-primary"
                size="sm"
                disabled={isSavingToDisk || isSavingToDrive}
                onClick={onSaveToDrive}
                data-testid="pdf-export-queue-save-drive"
              >
                {isSavingToDrive ? (
                  <Spinner size={1} />
                ) : (
                  "Save to Google Drive"
                )}
              </Button>
            )}
          </div>
        )}
      </ClickableBody>
    </PanelCard>
  );
}
