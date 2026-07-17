import { useEffect } from "react";
import { useAsync } from "react-use";

import { pdfRenderService } from "@/features/pdf/pdfRenderService";

import { useClientSearchContext } from "../clientSearch/clientSearchContext";
import { PDFProps } from "./PDF";
import { ImageFetchFailure } from "./pdfImage";

export const useRenderPDF = ({
  cardSelectionMode,
  pageSize,
  pageWidth,
  pageHeight,
  bleedEdgeMM,
  roundCorners,
  drawCardCutLines,
  drawPageCutLines,
  cutLineLengthMM,
  cutLineOffsetMM,
  cutLineThicknessMM,
  cutLineColor,
  cutLinePlacement,
  cutLineShape,
  cardSpacingRowMM,
  cardSpacingColMM,
  pageMarginTopMM,
  pageMarginBottomMM,
  pageMarginLeftMM,
  pageMarginRightMM,
  cardDocumentsByIdentifier,
  projectMembers,
  projectCardback,
  imageQuality,
  imageDPI,
  jpgQuality,
  scmMode,
  scmPaperSize,
  scmVariant,
  scmRegistration,
  scmDuplex,
  scmOffsetXMM,
  scmOffsetYMM,
  scmOffsetAngleDeg,
}: Omit<PDFProps, "fileHandles">) => {
  const { clientSearchService } = useClientSearchContext();
  const { value, loading, error } = useAsync(async (): Promise<{
    url: string;
    failures: Array<ImageFetchFailure>;
  }> => {
    const fileHandles = await clientSearchService.getFileHandlesByIdentifier(
      cardDocumentsByIdentifier
    );
    const { blob, failures } = await pdfRenderService.renderPDFInWorker({
      cardSelectionMode,
      pageSize,
      pageWidth,
      pageHeight,
      bleedEdgeMM,
      roundCorners,
      drawCardCutLines,
      drawPageCutLines,
      cutLineLengthMM,
      cutLineOffsetMM,
      cutLineThicknessMM,
      cutLineColor,
      cutLinePlacement,
      cutLineShape,
      cardSpacingRowMM,
      cardSpacingColMM,
      pageMarginTopMM,
      pageMarginBottomMM,
      pageMarginLeftMM,
      pageMarginRightMM,
      cardDocumentsByIdentifier,
      projectMembers,
      projectCardback,
      imageQuality,
      imageDPI,
      jpgQuality,
      scmMode,
      scmPaperSize,
      scmVariant,
      scmRegistration,
      scmDuplex,
      scmOffsetXMM,
      scmOffsetYMM,
      scmOffsetAngleDeg,
      fileHandles,
    });
    return { url: URL.createObjectURL(blob), failures };
  }, [
    cardSelectionMode,
    pageSize,
    pageWidth,
    pageHeight,
    bleedEdgeMM,
    roundCorners,
    drawCardCutLines,
    drawPageCutLines,
    cutLineLengthMM,
    cutLineThicknessMM,
    cutLineColor,
    cutLinePlacement,
    cutLineShape,
    cardSpacingRowMM,
    cardSpacingColMM,
    pageMarginTopMM,
    pageMarginBottomMM,
    pageMarginLeftMM,
    pageMarginRightMM,
    cardDocumentsByIdentifier,
    projectMembers,
    projectCardback,
    imageQuality,
    imageDPI,
    jpgQuality,
    scmMode,
    scmPaperSize,
    scmVariant,
    scmRegistration,
    scmDuplex,
    scmOffsetXMM,
    scmOffsetYMM,
    scmOffsetAngleDeg,
  ]);

  useEffect(
    () => (value?.url ? () => URL.revokeObjectURL(value.url) : undefined),
    [value?.url]
  );
  return {
    url: value?.url,
    failures: value?.failures ?? [],
    loading,
    error,
  };
};
