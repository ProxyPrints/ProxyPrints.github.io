import { useEffect, useMemo, useState } from "react";
import React from "react";
import Alert from "react-bootstrap/Alert";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Container from "react-bootstrap/Container";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";
import Row from "react-bootstrap/Row";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";
import { useDebounce } from "use-debounce";

import {
  BleedEdgeMM,
  CardHeightMM,
  CardWidthMM,
  ToggleButtonHeight,
} from "@/common/constants";
import { SourceType } from "@/common/schema_types";
import { StyledDropdownTreeSelect } from "@/common/StyledDropdownTreeSelect";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { AutofillCollapse } from "@/components/AutofillCollapse";
import { Blurrable } from "@/components/Blurrable";
import { OverflowCol } from "@/components/OverflowCol";
import { Spinner } from "@/components/Spinner";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { downloadFile, useDoFileDownload } from "@/features/download/download";
import { requestGoogleDriveWriteToken } from "@/features/googleDrive/googleDriveAuth";
import { isGoogleDriveAppConfigured } from "@/features/googleDrive/googleDriveConfig";
import { GoogleDriveService } from "@/features/googleDrive/GoogleDriveService";
import {
  BleedPrior,
  ManualOverride,
  willLikelyGenerateBleed,
} from "@/features/pdf/bleedNormalize";
import { resolveBleedPriors } from "@/features/pdf/bleedPriorResolution";
import { computeLayout } from "@/features/pdf/layout";
import {
  PagePreview,
  PagePreviewSlotContent,
} from "@/features/pdf/PagePreview";
import {
  CardSelectionMode,
  CardSelectionModeToPaginator,
  chunk,
  CutLinePlacement,
  CutLineShape,
  getPageSizeMM,
  PageSize,
  PDFProps,
} from "@/features/pdf/PDF";
import { PDFCanvasPreview } from "@/features/pdf/PDFCanvasPreview";
import {
  dedupeFailuresByIdentifier,
  ImageFetchFailure,
} from "@/features/pdf/pdfImage";
import { pdfRenderService } from "@/features/pdf/pdfRenderService";
import {
  BORDERLESS_STUDIO_EXPANSION_MM,
  scmOffsetMMToPx,
  ScmPaperLabels,
  ScmPaperSize,
  ScmRegistration,
  scmTemplateName,
  ScmVariant,
} from "@/features/pdf/scm/scmLayout";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  selectManualOverrides,
  selectProjectCardback,
  selectProjectMembers,
  setManualOverride,
} from "@/store/slices/projectSlice";
import { setNotification } from "@/store/slices/toastsSlice";
import { AppDispatch } from "@/store/store";

import { useClientSearchContext } from "../clientSearch/clientSearchContext";
import { useRenderPDF } from "./useRenderPDF";

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

const downloadPDF = async (
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
          Object.keys(props.cardDocumentsByIdentifier)
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

const saveToDrivePDF = async (
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
          Object.keys(props.cardDocumentsByIdentifier)
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

interface NumericFieldProps {
  label: string;
  value: number | undefined;
  setValue: (value: number | undefined) => void;
  min?: number;
  step?: number;
  max?: number;
}

const NumericField = (props: NumericFieldProps) => {
  const valueIsValid = (value: number) =>
    (props.min === undefined || props.min <= value) &&
    (props.max === undefined || props.max >= value);
  return (
    <>
      <Form.Label>{props.label}</Form.Label>
      <Form.Control
        type="number"
        min={props.min}
        step={props.step}
        value={props.value}
        isValid={props.value !== undefined && valueIsValid(props.value)}
        onChange={(event) => {
          const value = parseFloat(event.target.value);
          if (Number.isNaN(value)) {
            props.setValue(undefined);
          } else if (valueIsValid(value)) {
            props.setValue(value);
          }
        }}
      />
    </>
  );
};

interface PageSizeSettingsProps {
  pageWidth: number | undefined;
  setPageWidth: (value: number | undefined) => void;
  pageHeight: number | undefined;
  setPageHeight: (value: number | undefined) => void;
  pageSize: keyof typeof PageSize;
  setPageSize: (value: keyof typeof PageSize) => void;
}

const PageSizeSettings = ({
  pageWidth,
  setPageWidth,
  pageHeight,
  setPageHeight,
  pageSize,
  setPageSize,
}: PageSizeSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const isCustomPageSize = pageSize === "CUSTOM";

  const pageSizeOptions = useMemo(
    () =>
      Object.entries(PageSize).map(([value, label]) => ({
        value,
        label,
        checked: value === pageSize,
      })),
    [pageSize]
  );

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={15}
      title="Page Size"
    >
      <Container className="p-2">
        <Row>
          <Col xs={12}>
            <Form.Label>Page size</Form.Label>
            <StyledDropdownTreeSelect
              data={pageSizeOptions}
              onChange={(currentNode, selectedNodes) =>
                setPageSize(currentNode.value as keyof typeof PageSize)
              }
              mode="radioSelect"
              inlineSearchInput
            />
          </Col>
        </Row>
        {isCustomPageSize && (
          <Row>
            <Col xl={6} lg={12} md={12} sm={12} xs={12}>
              <NumericField
                label="Custom page width (mm)"
                value={pageWidth}
                setValue={setPageWidth}
                min={0}
                step={0.1}
              />
            </Col>
            <Col xl={6} lg={12} md={12} sm={12} xs={12}>
              <NumericField
                label="Custom page height (mm)"
                value={pageHeight}
                setValue={setPageHeight}
                min={0}
                step={0.1}
              />
            </Col>
          </Row>
        )}
      </Container>
    </AutofillCollapse>
  );
};

interface CardSelectionSettingsProps {
  cardSelectionMode: keyof typeof CardSelectionMode;
  setCardSelectionMode: (value: keyof typeof CardSelectionMode) => void;
}

const CardSelectionSettings = ({
  cardSelectionMode,
  setCardSelectionMode,
}: CardSelectionSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const cardSelectionModeOptions = useMemo(
    () =>
      Object.entries(CardSelectionMode).map(([value, label]) => ({
        value,
        label,
        checked: value === cardSelectionMode,
      })),
    [cardSelectionMode]
  );

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={14}
      title="Card Selection"
    >
      <Container className="p-2">
        <Form.Label>Select which cards to include</Form.Label>
        <StyledDropdownTreeSelect
          data={cardSelectionModeOptions}
          onChange={(currentNode, selectedNodes) =>
            setCardSelectionMode(
              currentNode.value as keyof typeof CardSelectionMode
            )
          }
          mode="radioSelect"
          inlineSearchInput
        />
      </Container>
    </AutofillCollapse>
  );
};

interface CardQualitySettingsProps {
  imageDPI: number;
  setImageDPI: (value: number) => void;
  jpgQuality: number;
  setJPGQuality: (value: number) => void;
}

const CardQualitySettings = ({
  imageDPI,
  setImageDPI,
  jpgQuality,
  setJPGQuality,
}: CardQualitySettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={13}
      title="Card Quality"
    >
      <Container className="p-2">
        <Form.Label>
          Card image DPI: <b>{imageDPI} DPI</b>
        </Form.Label>
        <Form.Range
          defaultValue={600}
          min={100}
          max={1500}
          step={100}
          onChange={(event) => {
            setImageDPI(parseInt(event.target.value));
          }}
        />
        <Form.Label>
          JPG quality: <b>{jpgQuality}%</b>
        </Form.Label>
        <Form.Range
          defaultValue={600}
          min={5}
          max={100}
          step={5}
          onChange={(event) => {
            setJPGQuality(parseInt(event.target.value));
          }}
        />
      </Container>
    </AutofillCollapse>
  );
};

interface EdgeSettingsProps {
  bleedEdgeMM: number | undefined;
  setBleedEdgeMM: (value: number | undefined) => void;
  roundCorners: boolean;
  setRoundCorners: (value: boolean) => void;
}

const EdgeSettings = ({
  bleedEdgeMM,
  setBleedEdgeMM,
  roundCorners,
  setRoundCorners,
}: EdgeSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={12}
      title="Card Edges"
    >
      <Container className="p-2">
        <NumericField
          label={`Bleed edge (max: ${BleedEdgeMM} mm)`}
          value={bleedEdgeMM}
          setValue={setBleedEdgeMM}
          min={0}
          max={BleedEdgeMM}
          step={0.001}
        />
        <Form.Label>Corners</Form.Label>
        <Toggle
          onClick={() => setRoundCorners(!roundCorners)}
          on="Round"
          onClassName="flex-centre"
          off="Square"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={roundCorners}
        />
      </Container>
    </AutofillCollapse>
  );
};

interface CutLinesSettingsProps {
  drawCardCutLines: boolean;
  setDrawCardCutLines: (value: boolean) => void;
  drawPageCutLines: boolean;
  setDrawPageCutLines: (value: boolean) => void;
  cutLineShape: keyof typeof CutLineShape;
  setCutLineShape: (value: keyof typeof CutLineShape) => void;
  cutLinePlacement: keyof typeof CutLinePlacement;
  setCutLinePlacement: (value: keyof typeof CutLinePlacement) => void;
  cutLineLengthMM: number | undefined;
  setCutLineLengthMM: (value: number | undefined) => void;
  cutLineOffsetMM: number | undefined;
  setCutLineOffsetMM: (value: number | undefined | undefined) => void;
  cutLineThicknessMM: number | undefined;
  setCutLineThicknessMM: (value: number | undefined) => void;
  cutLineColor: string;
  setCutLineColor: (value: string) => void;
}

const CutLinesSettings = ({
  drawCardCutLines,
  setDrawCardCutLines,
  drawPageCutLines,
  setDrawPageCutLines,
  cutLineShape,
  setCutLineShape,
  cutLinePlacement,
  setCutLinePlacement,
  cutLineLengthMM,
  setCutLineLengthMM,
  cutLineOffsetMM,
  setCutLineOffsetMM,
  cutLineThicknessMM,
  setCutLineThicknessMM,
  cutLineColor,
  setCutLineColor,
}: CutLinesSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);

  const cutLineShapeOptions = useMemo(
    () =>
      Object.entries(CutLineShape).map(([value, label]) => ({
        value,
        label,
        checked: value === cutLineShape,
      })),
    [cutLineShape]
  );

  const cutLinePlacementOptions = useMemo(
    () =>
      Object.entries(CutLinePlacement).map(([value, label]) => ({
        value,
        label,
        checked: value === cutLinePlacement,
      })),
    [cutLinePlacement]
  );

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={11}
      title="Cut Lines"
    >
      <Container className="p-2">
        <Form.Label>Card Cut Guide Lines</Form.Label>
        <Toggle
          onClick={() => setDrawCardCutLines(!drawCardCutLines)}
          on="On"
          onClassName="flex-centre"
          off="Off"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={drawCardCutLines}
        />
        <Form.Label>Page Cut Guide Lines</Form.Label>
        <Toggle
          onClick={() => setDrawPageCutLines(!drawPageCutLines)}
          on="On"
          onClassName="flex-centre"
          off="Off"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={drawPageCutLines}
        />
        {(drawCardCutLines || drawPageCutLines) && (
          <Row className="mt-1">
            {drawCardCutLines && (
              <>
                <Col xs={12}>
                  <Form.Label>Card Cut Lines Shape</Form.Label>
                  <StyledDropdownTreeSelect
                    data={cutLineShapeOptions}
                    onChange={(currentNode, selectedNodes) =>
                      setCutLineShape(
                        currentNode.value as keyof typeof CutLineShape
                      )
                    }
                    mode="radioSelect"
                    inlineSearchInput
                  />
                </Col>
                <Col xs={12}>
                  <Form.Label>Card Cut Lines Placement</Form.Label>
                  <StyledDropdownTreeSelect
                    data={cutLinePlacementOptions}
                    onChange={(currentNode, selectedNodes) =>
                      setCutLinePlacement(
                        currentNode.value as keyof typeof CutLinePlacement
                      )
                    }
                    mode="radioSelect"
                    inlineSearchInput
                  />
                </Col>
              </>
            )}
            <Col xs={6}>
              <NumericField
                label="Cut Lines Length (mm)"
                value={cutLineLengthMM}
                setValue={setCutLineLengthMM}
                min={0.1}
                step={0.1}
              />
            </Col>
            <Col xs={6} className="mt-1">
              <NumericField
                label="Cut Lines Thickness (mm)"
                value={cutLineThicknessMM}
                setValue={setCutLineThicknessMM}
                min={0.01}
                step={0.01}
              />
            </Col>
            <Col xs={6}>
              <NumericField
                label="Cut Lines Offset (mm)"
                value={cutLineOffsetMM}
                setValue={setCutLineOffsetMM}
                step={0.1}
              />
            </Col>
            <Col xs={6} className="mt-1">
              <Form.Label>Cut Lines Colour</Form.Label>
              <Form.Control
                type="color"
                value={cutLineColor}
                onChange={(e) => setCutLineColor(e.target.value)}
              />
            </Col>
          </Row>
        )}
      </Container>
    </AutofillCollapse>
  );
};

interface SpacingAndMarginsSettingsProps {
  cardSpacingRowMM: number | undefined;
  setCardSpacingRowMM: (value: number | undefined) => void;
  cardSpacingColMM: number | undefined;
  setCardSpacingColMM: (value: number | undefined) => void;
  pageMarginTopMM: number | undefined;
  setPageMarginTopMM: (value: number | undefined) => void;
  pageMarginBottomMM: number | undefined;
  setPageMarginBottomMM: (value: number | undefined) => void;
  pageMarginLeftMM: number | undefined;
  setPageMarginLeftMM: (value: number | undefined) => void;
  pageMarginRightMM: number | undefined;
  setPageMarginRightMM: (value: number | undefined) => void;
}

const SpacingAndMarginsSettings = ({
  cardSpacingRowMM,
  setCardSpacingRowMM,
  cardSpacingColMM,
  setCardSpacingColMM,
  pageMarginTopMM,
  setPageMarginTopMM,
  pageMarginBottomMM,
  setPageMarginBottomMM,
  pageMarginLeftMM,
  setPageMarginLeftMM,
  pageMarginRightMM,
  setPageMarginRightMM,
}: SpacingAndMarginsSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={10}
      title="Spacing & Margins"
    >
      <Container className="p-2">
        <Row>
          <Col lg={6} md={12} sm={12} xs={12}>
            <NumericField
              label="Row spacing (mm)"
              value={cardSpacingRowMM}
              setValue={setCardSpacingRowMM}
              min={0}
              step={0.1}
            />
          </Col>
          <Col lg={6} md={12} sm={12} xs={12}>
            <NumericField
              label="Column spacing (mm)"
              value={cardSpacingColMM}
              setValue={setCardSpacingColMM}
              min={0}
              step={0.1}
            />
          </Col>
        </Row>
        <Row>
          <Col lg={6} md={6} sm={12} xs={12}>
            <NumericField
              label="Page margin top (mm)"
              value={pageMarginTopMM}
              setValue={setPageMarginTopMM}
              min={0}
              step={0.1}
            />
          </Col>
          <Col lg={6} md={6} sm={12} xs={12}>
            <NumericField
              label="Page margin bottom (mm)"
              value={pageMarginBottomMM}
              setValue={setPageMarginBottomMM}
              min={0}
              step={0.1}
            />
          </Col>
        </Row>
        <Row>
          <Col lg={6} md={6} sm={12} xs={12}>
            <NumericField
              label="Page margin left (mm)"
              value={pageMarginLeftMM}
              setValue={setPageMarginLeftMM}
              min={0}
              step={0.1}
            />
          </Col>
          <Col lg={6} md={6} sm={12} xs={12}>
            <NumericField
              label="Page margin right (mm)"
              value={pageMarginRightMM}
              setValue={setPageMarginRightMM}
              min={0}
              step={0.1}
            />
          </Col>
        </Row>
      </Container>
    </AutofillCollapse>
  );
};

interface SCMSettingsProps {
  scmPaperSize: ScmPaperSize;
  setScmPaperSize: (value: ScmPaperSize) => void;
  scmVariant: ScmVariant;
  setScmVariant: (value: ScmVariant) => void;
  scmRegistration: ScmRegistration;
  setScmRegistration: (value: ScmRegistration) => void;
  scmDuplex: boolean;
  setScmDuplex: (value: boolean) => void;
  scmOffsetXMM: number | undefined;
  setScmOffsetXMM: (value: number | undefined) => void;
  scmOffsetYMM: number | undefined;
  setScmOffsetYMM: (value: number | undefined) => void;
  scmOffsetAngleDeg: number | undefined;
  setScmOffsetAngleDeg: (value: number | undefined) => void;
}

const SCMSettings = ({
  scmPaperSize,
  setScmPaperSize,
  scmVariant,
  setScmVariant,
  scmRegistration,
  setScmRegistration,
  scmDuplex,
  setScmDuplex,
  scmOffsetXMM,
  setScmOffsetXMM,
  scmOffsetYMM,
  setScmOffsetYMM,
  scmOffsetAngleDeg,
  setScmOffsetAngleDeg,
}: SCMSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(true);

  const paperSizeOptions = useMemo(
    () =>
      Object.keys(ScmPaperLabels).map((value) => ({
        value,
        label: ScmPaperLabels[value as ScmPaperSize],
        checked: value === scmPaperSize,
      })),
    [scmPaperSize]
  );

  const isBorderless = scmVariant === "borderless";

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={15}
      title="Silhouette Template"
    >
      <Container className="p-2">
        <Row>
          <Col xs={12}>
            <Form.Label>Paper size</Form.Label>
            <StyledDropdownTreeSelect
              data={paperSizeOptions}
              onChange={(currentNode) =>
                setScmPaperSize(currentNode.value as ScmPaperSize)
              }
              mode="radioSelect"
              inlineSearchInput
            />
          </Col>
        </Row>
        <Form.Label>Template</Form.Label>
        <Toggle
          onClick={() => setScmVariant(isBorderless ? "default" : "borderless")}
          on="Borderless"
          onClassName="flex-centre"
          off="Normal"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={isBorderless}
        />
        <Form.Label>Registration marks</Form.Label>
        <Toggle
          onClick={() => setScmRegistration(scmRegistration === 3 ? 4 : 3)}
          on="4 Corner (Cameo 5)"
          onClassName="flex-centre"
          off="3 Corner"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={scmRegistration === 4}
        />
        <Form.Label>Sides</Form.Label>
        <Toggle
          onClick={() => setScmDuplex(!scmDuplex)}
          on="Duplex (front + back)"
          onClassName="flex-centre"
          off="Fronts only"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={scmDuplex}
        />
        <hr />
        <p className="mb-1">Load this cutting template in Silhouette Studio:</p>
        <p className="mb-1">
          <a
            href="https://github.com/Alan-Cha/silhouette-card-maker/tree/main/cutting_templates"
            target="_blank"
            rel="noreferrer"
          >
            <code>{scmTemplateName(scmPaperSize, scmVariant)}</code>
          </a>
        </p>
        {isBorderless && (
          <p className="text-muted" style={{ fontSize: "0.85em" }}>
            Borderless: in Silhouette Studio, set a custom page size{" "}
            <b>{BORDERLESS_STUDIO_EXPANSION_MM}mm larger</b> in each dimension
            than the real paper so the registration marks land at the correct
            inset.
          </p>
        )}
        {scmDuplex && (
          <Row className="mt-1">
            <Col xs={12}>
              <Form.Label>Back alignment offset</Form.Label>
              <p className="text-muted mb-1" style={{ fontSize: "0.8em" }}>
                Millimetres. X+ = right, Y+ = up, angle+ = clockwise, relative
                to the back page. SCM&apos;s <code>offset_pdf</code> uses pixels
                at 300 DPI — your offsets ≈{" "}
                <b>{scmOffsetMMToPx(scmOffsetXMM ?? 0)}</b>,{" "}
                <b>{scmOffsetMMToPx(scmOffsetYMM ?? 0)}</b> px.
              </p>
            </Col>
            <Col xs={6}>
              <NumericField
                label="Offset X (mm)"
                value={scmOffsetXMM}
                setValue={setScmOffsetXMM}
                step={0.1}
              />
            </Col>
            <Col xs={6}>
              <NumericField
                label="Offset Y (mm)"
                value={scmOffsetYMM}
                setValue={setScmOffsetYMM}
                step={0.1}
              />
            </Col>
            <Col xs={6} className="mt-1">
              <NumericField
                label="Angle (°)"
                value={scmOffsetAngleDeg}
                setValue={setScmOffsetAngleDeg}
                step={0.1}
              />
            </Col>
          </Row>
        )}
      </Container>
    </AutofillCollapse>
  );
};

interface BleedOverrideSettingsProps {
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
}

/**
 * Proposal B PR-2: per-card manual override (Auto / Force bleed / Force trimmed) for the
 * export-time bleed measurement. Only lists cards bleed normalization can actually apply to
 * (see PDF.tsx's isBleedNormalizationEligible - full-resolution Google Drive/local-file images
 * only) so an override control never sits next to a card it would silently do nothing for.
 * Reads/writes projectSlice directly (decision 4: persists in project state, not local
 * component state) rather than taking value/setValue props like this file's other settings
 * sections.
 */
const BleedOverrideSettings = ({
  cardDocumentsByIdentifier,
}: BleedOverrideSettingsProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const dispatch = useAppDispatch();
  const manualOverrides = useAppSelector(selectManualOverrides);

  const eligibleCards = useMemo(
    () =>
      Object.entries(cardDocumentsByIdentifier)
        // cardDocumentsByIdentifier is keyed by every project member identifier, including ones
        // whose CardDocument hasn't finished loading into the store yet (selectCardDocumentsByIdentifiers
        // maps a not-yet-fetched identifier to undefined) - the fast preview's own eligibility
        // filter (fastPreviewEligibleIdentifiers, below) already guards against this; this one
        // didn't, and crashed on `cardDocument.sourceType` the instant this panel rendered before
        // every card had loaded (task #135 - see docs/lessons.md).
        .filter(
          (entry): entry is [string, CardDocument] =>
            entry[1] != null &&
            (entry[1].sourceType === SourceType.GoogleDrive ||
              entry[1].sourceType === SourceType.LocalFile)
        )
        .sort(([, a], [, b]) => a.name.localeCompare(b.name)),
    [cardDocumentsByIdentifier]
  );

  return (
    <AutofillCollapse
      expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      zIndex={9}
      title="Bleed Overrides"
    >
      <Container className="p-2">
        <p className="text-muted" style={{ fontSize: "0.85em" }}>
          Bleed is measured automatically per card at export. Override a card
          below if the automatic measurement gets it wrong.
        </p>
        {eligibleCards.length === 0 ? (
          <p className="text-muted mb-0" style={{ fontSize: "0.85em" }}>
            No cards in this project support bleed normalization yet (Google
            Drive / local-file sources only).
          </p>
        ) : (
          eligibleCards.map(([identifier, cardDocument]) => (
            <Row key={identifier} className="align-items-center mb-1">
              <Col xs={7} className="text-truncate" title={cardDocument.name}>
                {cardDocument.name}
              </Col>
              <Col xs={5}>
                <Form.Select
                  size="sm"
                  data-testid={`bleed-override-select-${identifier}`}
                  value={manualOverrides[identifier] ?? "auto"}
                  onChange={(event) =>
                    dispatch(
                      setManualOverride({
                        identifier,
                        override: event.target.value as ManualOverride,
                      })
                    )
                  }
                >
                  <option value="auto">Auto</option>
                  <option value="force-bleed">Force bleed</option>
                  <option value="force-trimmed">Force trimmed</option>
                </Form.Select>
              </Col>
            </Row>
          ))
        )}
      </Container>
    </AutofillCollapse>
  );
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

export const PDFGenerator = ({ heightDelta = 0 }: { heightDelta?: number }) => {
  const dispatch = useAppDispatch();
  const [cardSpacingRowMM, setCardSpacingRowMM] = useState<number | undefined>(
    0
  );
  const [cardSpacingColMM, setCardSpacingColMM] = useState<number | undefined>(
    0
  );
  const [pageMarginTopMM, setPageMarginTopMM] = useState<number | undefined>(5);
  const [pageMarginBottomMM, setPageMarginBottomMM] = useState<
    number | undefined
  >(5);
  const [pageMarginLeftMM, setPageMarginLeftMM] = useState<number | undefined>(
    5
  );
  const [pageMarginRightMM, setPageMarginRightMM] = useState<
    number | undefined
  >(5);
  const [bleedEdgeMM, setBleedEdgeMM] = useState<number | undefined>(0);
  const [roundCorners, setRoundCorners] = useState<boolean>(false);
  const [drawCardCutLines, setDrawCardCutLines] = useState<boolean>(true);
  const [drawPageCutLines, setDrawPageCutLines] = useState<boolean>(true);
  const [cutLineLengthMM, setCutLineLengthMM] = useState<number | undefined>(2);
  const [cutLineOffsetMM, setCutLineOffsetMM] = useState<number | undefined>(0);
  const [cutLineThicknessMM, setCutLineThicknessMM] = useState<
    number | undefined
  >(0.2);
  const [cutLineColor, setCutLineColor] = useState<string>("#FF0000");

  // SCM (Silhouette Card Maker) mode state.
  const [scmMode, setScmMode] = useState<boolean>(false);
  const [scmPaperSize, setScmPaperSize] = useState<ScmPaperSize>("letter");
  const [scmVariant, setScmVariant] = useState<ScmVariant>("default");
  const [scmRegistration, setScmRegistration] = useState<ScmRegistration>(3);
  const [scmDuplex, setScmDuplex] = useState<boolean>(true);
  const [scmOffsetXMM, setScmOffsetXMM] = useState<number | undefined>(0);
  const [scmOffsetYMM, setScmOffsetYMM] = useState<number | undefined>(0);
  const [scmOffsetAngleDeg, setScmOffsetAngleDeg] = useState<
    number | undefined
  >(0);

  const { clientSearchService } = useClientSearchContext();
  const projectMembers = useAppSelector(selectProjectMembers);
  const projectCardback = useAppSelector(selectProjectCardback);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const manualOverrides = useAppSelector(selectManualOverrides);

  const [pageSize, setPageSize] = useState<keyof typeof PageSize>(PageSize.A4);
  const [pageWidth, setPageWidth] = useState<number | undefined>(undefined);
  const [pageHeight, setPageHeight] = useState<number | undefined>(undefined);
  const [imageDPI, setImageDPI] = useState<number>(600);
  const [jpgQuality, setJPGQuality] = useState<number>(100);

  const [cardSelectionMode, setCardSelectionMode] = useState<
    keyof typeof CardSelectionMode
  >("frontsAndDistinctBacks");
  const [cutLineShape, setCutLineShape] =
    useState<keyof typeof CutLineShape>("InsideOnly");
  const [cutLinePlacement, setCutLinePlacement] =
    useState<keyof typeof CutLinePlacement>("Inside");

  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();

  // TODO: look at when i'm more awake
  function equalityFn<T>(left: T, right: T): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
  }
  const pdfProps: Omit<PDFProps, "fileHandles"> = {
    cardSelectionMode: cardSelectionMode,
    pageSize: pageSize,
    pageWidth: pageWidth,
    pageHeight: pageHeight,
    bleedEdgeMM: bleedEdgeMM ?? 0,
    roundCorners: roundCorners,
    drawCardCutLines: drawCardCutLines,
    drawPageCutLines: drawPageCutLines,
    cutLineLengthMM: cutLineLengthMM ?? 2,
    cutLineOffsetMM: cutLineOffsetMM ?? 0,
    cutLineThicknessMM: cutLineThicknessMM ?? 0.2,
    cutLineColor: cutLineColor,
    cutLinePlacement: cutLinePlacement,
    cutLineShape: cutLineShape,
    cardSpacingRowMM: cardSpacingRowMM ?? 0,
    cardSpacingColMM: cardSpacingColMM ?? 0,
    pageMarginTopMM: pageMarginTopMM ?? 0,
    pageMarginBottomMM: pageMarginBottomMM ?? 0,
    pageMarginLeftMM: pageMarginLeftMM ?? 0,
    pageMarginRightMM: pageMarginRightMM ?? 0,
    cardDocumentsByIdentifier: cardDocumentsByIdentifier,
    projectMembers: projectMembers,
    projectCardback: projectCardback,
    bleedOverrides: manualOverrides,
    scmMode: scmMode,
    scmPaperSize: scmPaperSize,
    scmVariant: scmVariant,
    scmRegistration: scmRegistration,
    scmDuplex: scmDuplex,
    scmOffsetXMM: scmOffsetXMM ?? 0,
    scmOffsetYMM: scmOffsetYMM ?? 0,
    scmOffsetAngleDeg: scmOffsetAngleDeg ?? 0,
    // the following settings don't matter for previewing and should remain stable to prevent unnecessary re-renders.
    imageQuality: "small-thumbnail",
    imageDPI: undefined,
    jpgQuality: 100,
  };
  const [debouncedPDFProps, debouncedState] = useDebounce(pdfProps, 500, {
    equalityFn,
  });

  const {
    url,
    failures: rawFailures,
    loading,
    error,
  } = useRenderPDF(debouncedPDFProps);
  const failures = dedupeFailuresByIdentifier(rawFailures);

  const showSpinner = debouncedState.isPending() || loading;

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

  // "Fast" (the default) skips @react-pdf/renderer + pdf.js entirely - just computeLayout()
  // and plain DOM/CSS, updated instantly (no debounce, no spinner, no canvas) from the
  // existing small-tier thumbnail URLs already in memory. "Exact" is the pre-existing
  // pdf.js-rendered canvas preview, a real (debounced) PDF render - useful for confirming cut
  // lines/bleed exactly as they'll print, at the cost of the heavier render pipeline.
  const [previewMode, setPreviewMode] = useState<"fast" | "exact">("fast");
  const fastPreviewSize = getPageSizeMM(pageSize, pageWidth, pageHeight);
  const fastPreviewMargins = {
    top: pageMarginTopMM ?? 0,
    bottom: pageMarginBottomMM ?? 0,
    left: pageMarginLeftMM ?? 0,
    right: pageMarginRightMM ?? 0,
  };
  const fastPreviewSpacing = {
    row: cardSpacingRowMM ?? 0,
    col: cardSpacingColMM ?? 0,
  };
  const fastPreviewLayout = computeLayout(
    fastPreviewSize.width,
    fastPreviewSize.height,
    CardWidthMM,
    CardHeightMM,
    bleedEdgeMM ?? 0,
    fastPreviewMargins,
    fastPreviewSpacing
  );
  const fastPreviewCardsPerPage =
    fastPreviewLayout.cardsPerRow * fastPreviewLayout.cardsPerCol;
  // Reuses the PDF generator's own pagination functions (not a reimplementation) so the fast
  // preview's page-1 card selection always matches what the real PDF would generate first.
  const fastPreviewCardSets = CardSelectionModeToPaginator[cardSelectionMode](
    projectMembers,
    cardDocumentsByIdentifier,
    projectCardback,
    fastPreviewCardsPerPage
  );
  const fastPreviewFirstPage =
    fastPreviewCardSets.flatMap((set) =>
      chunk(set, fastPreviewCardsPerPage)
    )[0] ?? [];

  // Proposal B PR-3: the preview badge's own bleed-prior lookup, scoped to just the currently-
  // visible fast-preview page (not the whole project) and only for sources bleed normalization
  // can apply to - same eligibility filter as BleedOverrideSettings. Debounced (matching this
  // component's own pdfProps debounce) so retyping a search query doesn't fire a fresh batch of
  // requests on every keystroke.
  const fastPreviewEligibleIdentifiers = fastPreviewFirstPage
    .filter(
      (doc) =>
        doc != null &&
        (doc.sourceType === SourceType.GoogleDrive ||
          doc.sourceType === SourceType.LocalFile)
    )
    .map((doc) => doc!.identifier);
  const [debouncedPreviewIdentifiers] = useDebounce(
    fastPreviewEligibleIdentifiers,
    500,
    { equalityFn }
  );
  const [fastPreviewBleedPriors, setFastPreviewBleedPriors] = useState<{
    [identifier: string]: BleedPrior;
  }>({});
  useEffect(() => {
    let cancelled = false;
    if (backendURL == null || debouncedPreviewIdentifiers.length === 0) {
      setFastPreviewBleedPriors({});
      return;
    }
    resolveBleedPriors(backendURL, debouncedPreviewIdentifiers).then(
      (priors) => {
        if (!cancelled) {
          setFastPreviewBleedPriors(priors);
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, [backendURL, debouncedPreviewIdentifiers]);

  const fastPreviewSlots: Array<PagePreviewSlotContent> =
    fastPreviewFirstPage.map((doc) => {
      const eligible =
        doc != null &&
        (doc.sourceType === SourceType.GoogleDrive ||
          doc.sourceType === SourceType.LocalFile);
      const prior =
        doc != null ? fastPreviewBleedPriors[doc.identifier] : undefined;
      const override =
        doc != null ? manualOverrides[doc.identifier] ?? "auto" : "auto";
      // Only render the badge once there's a real signal to hedge on (an explicit override, or
      // a resolved prior) - showing a provisional guess before either is available would flicker
      // wrong-then-right as the prior fetch resolves.
      const willGenerateBleed =
        eligible && (override !== "auto" || prior != null)
          ? willLikelyGenerateBleed(prior ?? "unresolved", override)
          : undefined;
      return {
        imageUrl: doc?.smallThumbnailUrl,
        name: doc?.name ?? "",
        willGenerateBleed,
      };
    });

  const fullResolutionPDFProps = {
    ...debouncedPDFProps,
    imageQuality: "full-resolution" as const,
    imageDPI: imageDPI,
    jpgQuality: jpgQuality,
  };

  const downloadPDF = useDownloadPDF(
    fullResolutionPDFProps,
    clientSearchService,
    dispatch,
    setIsDownloading,
    backendURL,
    setImageFetchProgress,
    confirmDespiteFailures
  );

  const saveToDrive = useSaveToDrivePDF(
    fullResolutionPDFProps,
    clientSearchService,
    dispatch,
    setIsSavingToDrive,
    backendURL,
    setImageFetchProgress,
    confirmDespiteFailures
  );

  return (
    <Container fluid>
      <Row>
        <OverflowCol
          lg={3}
          md={4}
          sm={5}
          xs={6}
          className="py-2"
          heightDelta={heightDelta}
        >
          <p>
            Generate a PDF file from your project suitable for printing at home
            or professionally.
          </p>
          <ol>
            <li>
              Configure how your PDF should be laid out with the settings below.
            </li>
            <li>
              A <b>live preview</b> of your PDF is shown on the right-hand side.
            </li>
            <li>
              When you&apos;re done, click the <b>Generate PDF</b> button below!
            </li>
          </ol>
          <hr />
          <Form.Label>Silhouette (SCM) cutting mode</Form.Label>
          <Toggle
            onClick={() => setScmMode(!scmMode)}
            on="On"
            onClassName="flex-centre"
            off="Off"
            offClassName="flex-centre"
            onstyle="success"
            offstyle="info"
            width={100 + "%"}
            size="md"
            height={ToggleButtonHeight + "px"}
            active={scmMode}
          />
          <p className="text-muted mt-1" style={{ fontSize: "0.85em" }}>
            Generate a PDF with registration marks compatible with{" "}
            <a
              href="https://github.com/Alan-Cha/silhouette-card-maker"
              target="_blank"
              rel="noreferrer"
            >
              silhouette-card-maker
            </a>{" "}
            cutting templates (standard 63×88mm cards).
          </p>
          <hr />
          {scmMode ? (
            <>
              <SCMSettings
                scmPaperSize={scmPaperSize}
                setScmPaperSize={setScmPaperSize}
                scmVariant={scmVariant}
                setScmVariant={setScmVariant}
                scmRegistration={scmRegistration}
                setScmRegistration={setScmRegistration}
                scmDuplex={scmDuplex}
                setScmDuplex={setScmDuplex}
                scmOffsetXMM={scmOffsetXMM}
                setScmOffsetXMM={setScmOffsetXMM}
                scmOffsetYMM={scmOffsetYMM}
                setScmOffsetYMM={setScmOffsetYMM}
                scmOffsetAngleDeg={scmOffsetAngleDeg}
                setScmOffsetAngleDeg={setScmOffsetAngleDeg}
              />
              <CardQualitySettings
                imageDPI={imageDPI}
                setImageDPI={setImageDPI}
                jpgQuality={jpgQuality}
                setJPGQuality={setJPGQuality}
              />
            </>
          ) : (
            <>
              <PageSizeSettings
                pageWidth={pageWidth}
                setPageWidth={setPageWidth}
                pageHeight={pageHeight}
                setPageHeight={setPageHeight}
                pageSize={pageSize}
                setPageSize={setPageSize}
              />
              <CardSelectionSettings
                cardSelectionMode={cardSelectionMode}
                setCardSelectionMode={setCardSelectionMode}
              />
              <CardQualitySettings
                imageDPI={imageDPI}
                setImageDPI={setImageDPI}
                jpgQuality={jpgQuality}
                setJPGQuality={setJPGQuality}
              />
              <EdgeSettings
                bleedEdgeMM={bleedEdgeMM}
                setBleedEdgeMM={setBleedEdgeMM}
                roundCorners={roundCorners}
                setRoundCorners={setRoundCorners}
              />
              <CutLinesSettings
                drawCardCutLines={drawCardCutLines}
                setDrawCardCutLines={setDrawCardCutLines}
                drawPageCutLines={drawPageCutLines}
                setDrawPageCutLines={setDrawPageCutLines}
                cutLineShape={cutLineShape}
                setCutLineShape={setCutLineShape}
                cutLinePlacement={cutLinePlacement}
                setCutLinePlacement={setCutLinePlacement}
                cutLineLengthMM={cutLineLengthMM}
                setCutLineLengthMM={setCutLineLengthMM}
                cutLineOffsetMM={cutLineOffsetMM}
                setCutLineOffsetMM={setCutLineOffsetMM}
                cutLineThicknessMM={cutLineThicknessMM}
                setCutLineThicknessMM={setCutLineThicknessMM}
                cutLineColor={cutLineColor}
                setCutLineColor={setCutLineColor}
              />
              <SpacingAndMarginsSettings
                cardSpacingRowMM={cardSpacingRowMM}
                setCardSpacingRowMM={setCardSpacingRowMM}
                cardSpacingColMM={cardSpacingColMM}
                setCardSpacingColMM={setCardSpacingColMM}
                pageMarginTopMM={pageMarginTopMM}
                setPageMarginTopMM={setPageMarginTopMM}
                pageMarginBottomMM={pageMarginBottomMM}
                setPageMarginBottomMM={setPageMarginBottomMM}
                pageMarginLeftMM={pageMarginLeftMM}
                setPageMarginLeftMM={setPageMarginLeftMM}
                pageMarginRightMM={pageMarginRightMM}
                setPageMarginRightMM={setPageMarginRightMM}
              />
              <BleedOverrideSettings
                cardDocumentsByIdentifier={cardDocumentsByIdentifier}
              />
            </>
          )}
          <hr />
          <div className="d-grid gap-0">
            <Button onClick={downloadPDF} disabled={isDownloading}>
              {isDownloading ? <Spinner size={1.5} /> : "Generate PDF"}
            </Button>
          </div>
          {isGoogleDriveAppConfigured() && (
            <div className="d-grid gap-0 mt-2">
              <Button
                variant="outline-primary"
                onClick={saveToDrive}
                disabled={isSavingToDrive}
              >
                {isSavingToDrive ? (
                  <Spinner size={1.5} />
                ) : (
                  "Save PDF to Google Drive"
                )}
              </Button>
            </div>
          )}
          {(isDownloading || isSavingToDrive) && imageFetchProgress != null && (
            <p
              className="text-muted text-center mt-2 mb-0"
              style={{ fontSize: "0.85em" }}
              data-testid="pdf-image-fetch-progress"
            >
              {/* Approximate, not exact - see pdf.worker.ts's own comment on why "total" can
                    undercount a deck with duplicate cards. A large export paced to the image
                    CDN's shared rate limit can take several minutes - this exists so that wait
                    reads as "working," not "hung." */}
              Fetching images: {imageFetchProgress.completed} of ~
              {imageFetchProgress.total}
            </p>
          )}
        </OverflowCol>
        <Col lg={9} md={8} sm={7} xs={6} style={{ position: "relative" }}>
          {!scmMode && (
            <div className="d-flex justify-content-end mb-2">
              <Button
                size="sm"
                variant="outline-secondary"
                data-testid="preview-mode-toggle"
                onClick={() =>
                  setPreviewMode(previewMode === "fast" ? "exact" : "fast")
                }
              >
                {previewMode === "fast"
                  ? "Switch to exact PDF preview"
                  : "Switch to fast preview"}
              </Button>
            </div>
          )}
          {/* Image-fetch-failure/error detection comes from the real (debounced)
              @react-pdf/renderer render via useRenderPDF, which runs unconditionally
              regardless of which preview is on screen - these warnings stay visible in fast
              mode too, not just exact mode, since generating a PDF full of silently-blank
              cards is exactly the mistake this warns against, independent of which preview
              the user happened to be looking at. */}
          {!showSpinner && error != null && (
            <Alert
              variant="danger"
              className="m-2"
              data-testid="pdf-preview-error"
            >
              Couldn&apos;t generate a preview:{" "}
              {error instanceof Error ? error.message : String(error)}
            </Alert>
          )}
          {!showSpinner && error == null && failures.length > 0 && (
            <Alert
              variant="warning"
              className="m-2"
              data-testid="pdf-preview-image-failures"
            >
              {failures.length} card image{failures.length === 1 ? "" : "s"}{" "}
              couldn&apos;t be loaded and will appear blank:{" "}
              {failures.map((failure) => failure.label).join(", ")}
            </Alert>
          )}
          {!scmMode && previewMode === "fast" ? (
            <PagePreview
              pageWidthMM={fastPreviewSize.width}
              pageHeightMM={fastPreviewSize.height}
              bleedEdgeMM={bleedEdgeMM ?? 0}
              margins={fastPreviewMargins}
              spacing={fastPreviewSpacing}
              slots={fastPreviewSlots}
              showCutLines={drawCardCutLines}
              maxWidthPx={480}
            />
          ) : (
            <>
              {showSpinner && (
                <Spinner size={6} zIndex={3} positionAbsolute={true} />
              )}
              <Blurrable
                disabled={showSpinner}
                style={{ height: 100 + "%", overflowY: "hidden" }}
              >
                <PDFCanvasPreview url={url} />
              </Blurrable>
            </>
          )}
        </Col>
      </Row>
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
    </Container>
  );
};
