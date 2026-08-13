/**
 * The editor's PDF export item - `DisplayExportMenu.tsx`'s fourth entry, alongside XML/Card
 * Images/Decklist. This page's own centre sheet already IS the export preview (a real
 * `computeLayout()`-driven `PagePreview`, not a mockup), so this component deliberately mounts
 * no preview of its own: no `PDFCanvasPreview` (pdf.js canvas rendering), no fast DOM preview
 * like `PDFGenerator.tsx`'s - either would make this page pay a render cost the sheet the user is
 * already looking at makes redundant.
 *
 * Props come from `displayPdfProps.ts`'s `useDisplayPDFProps` - the one adapter from this page's
 * live sheet settings to the `PDFProps` shape `PDF.tsx` already consumes - and the actual
 * download is `pdfDownload.tsx`'s `useDownloadPDF`, the exact same hook `/print`'s
 * `PDFGenerator.tsx` uses for its own Download button. Nothing about the render pipeline is
 * forked; only the source of its props and the trigger UI differ.
 */
import React, { useState } from "react";
import Dropdown from "react-bootstrap/Dropdown";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import {
  DisplaySheetExportSettings,
  useDisplayPDFProps,
} from "@/features/pdf/displayPdfProps";
import {
  ConfirmDespiteFailures,
  ImageFailureConfirmModal,
  useDownloadPDF,
} from "@/features/pdf/pdfDownload";
import { ImageFetchFailure } from "@/features/pdf/pdfImage";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

export interface DisplayExportPDFProps {
  sheetSettings: DisplaySheetExportSettings;
}

export function DisplayExportPDF({ sheetSettings }: DisplayExportPDFProps) {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const { clientSearchService } = useClientSearchContext();
  const pdfProps = useDisplayPDFProps(sheetSettings);

  const [isDownloading, setIsDownloading] = useState<boolean>(false);
  const [, setImageFetchProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  const [pendingFailureConfirm, setPendingFailureConfirm] = useState<{
    failures: Array<ImageFetchFailure>;
    resolve: (value: boolean) => void;
  } | null>(null);
  const confirmDespiteFailures: ConfirmDespiteFailures = (failures) =>
    new Promise((resolve) => setPendingFailureConfirm({ failures, resolve }));

  const downloadPDF = useDownloadPDF(
    pdfProps,
    clientSearchService,
    dispatch,
    setIsDownloading,
    backendURL,
    setImageFetchProgress,
    confirmDespiteFailures
  );

  return (
    <>
      <Dropdown.Item
        disabled={isProjectEmpty || isDownloading}
        data-testid="display-export-pdf-button"
        onClick={downloadPDF}
      >
        <RightPaddedIcon bootstrapIconName="file-pdf" />
        {isDownloading ? <Spinner size={1} /> : "PDF"}
      </Dropdown.Item>
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
    </>
  );
}
