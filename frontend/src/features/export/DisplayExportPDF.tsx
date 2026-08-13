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
 *
 * Export-time settings (card selection mode, page range, image quality, cut-line colour/shape)
 * are choices about the OUTPUT FILE, not the sheet's own layout, so they live here - alongside
 * the export affordance itself, in a small settings step between clicking "PDF" and the actual
 * download - rather than joining the right rail's Page Setup section, which governs what the
 * live sheet shows, not what a given export run produces. Plain Bootstrap form controls only
 * (no `AutofillCollapse`/`StyledDropdownTreeSelect`/`NumericField` from `PDFGenerator.tsx`) so
 * this component stays free of that file's own import graph.
 */
import React, { useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import Dropdown from "react-bootstrap/Dropdown";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import {
  DisplayExportSettings,
  DisplaySheetExportSettings,
  useDisplayPDFProps,
} from "@/features/pdf/displayPdfProps";
import {
  CardSelectionMode,
  computePDFPageCount,
  CutLineShape,
  DEFAULT_CARD_SELECTION_MODE,
} from "@/features/pdf/PDF";
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

// The mode names alone mislead ("Distinct Backs" sounds like it emits backs, and for a
// shared-cardback deck it emits none), so each option carries its own one-line explanation.
const CARD_SELECTION_MODE_DESCRIPTIONS: {
  [mode in keyof typeof CardSelectionMode]: string;
} = {
  frontsAndBacks:
    "Every front and every back, front/back pages interleaved - safe default for a deck that relies on the shared project cardback.",
  frontsAndDistinctBacks:
    "Every front, plus only backs that differ from the project's shared cardback. Omits the shared cardback entirely - a deck where every card uses it exports no backs at all.",
  frontsOnly: "Fronts only, no back pages.",
  backsOnly: "Backs only, no front pages.",
};

const DEFAULT_EXPORT_SETTINGS: DisplayExportSettings = {
  cardSelectionMode: DEFAULT_CARD_SELECTION_MODE,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  imageDPI: 600,
  jpgQuality: 100,
  // Matches PagePreview.tsx's own E19 lime corner-only guide (#8ae234, "InsideOnly"), so the
  // export defaults to looking like the guide the sheet already showed.
  cutLineColor: "#8ae234",
  cutLineShape: "InsideOnly",
};

export function DisplayExportPDF({ sheetSettings }: DisplayExportPDFProps) {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const { clientSearchService } = useClientSearchContext();

  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [exportSettings, setExportSettings] = useState<DisplayExportSettings>(
    DEFAULT_EXPORT_SETTINGS
  );
  const setField = <K extends keyof DisplayExportSettings>(
    key: K,
    value: DisplayExportSettings[K]
  ) => setExportSettings((previous) => ({ ...previous, [key]: value }));

  const pdfProps = useDisplayPDFProps(sheetSettings, exportSettings);
  // The real page count, ignoring the range fields themselves - computePDFPageCount doesn't
  // read them (see its own comment) - so this always reflects what pagination actually
  // resolves to, letting the range control clamp against a real number instead of a guess.
  const totalPages = useMemo(() => computePDFPageCount(pdfProps), [pdfProps]);

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
          <Form.Group className="mb-3">
            <Form.Label>Cards to include</Form.Label>
            <Form.Select
              size="sm"
              data-testid="display-export-card-selection-mode"
              value={exportSettings.cardSelectionMode}
              onChange={(event) =>
                setField(
                  "cardSelectionMode",
                  event.target.value as keyof typeof CardSelectionMode
                )
              }
            >
              {Object.entries(CardSelectionMode).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Form.Select>
            <Form.Text className="text-muted">
              {
                CARD_SELECTION_MODE_DESCRIPTIONS[
                  exportSettings.cardSelectionMode
                ]
              }
            </Form.Text>
          </Form.Group>

          <Form.Group className="mb-3">
            <Form.Label>Pages ({totalPages} total)</Form.Label>
            <div className="d-flex gap-2 align-items-center">
              <Form.Control
                type="number"
                size="sm"
                min={1}
                max={totalPages}
                placeholder="1"
                aria-label="First page to export"
                data-testid="display-export-page-range-start"
                value={exportSettings.pageRangeStart ?? ""}
                onChange={(event) => {
                  const value = parseInt(event.target.value, 10);
                  setField(
                    "pageRangeStart",
                    Number.isNaN(value) ? undefined : value
                  );
                }}
              />
              <span className="text-muted small">to</span>
              <Form.Control
                type="number"
                size="sm"
                min={1}
                max={totalPages}
                placeholder={`${totalPages}`}
                aria-label="Last page to export"
                data-testid="display-export-page-range-end"
                value={exportSettings.pageRangeEnd ?? ""}
                onChange={(event) => {
                  const value = parseInt(event.target.value, 10);
                  setField(
                    "pageRangeEnd",
                    Number.isNaN(value) ? undefined : value
                  );
                }}
              />
            </div>
            <Form.Text className="text-muted">
              Leave blank on either end to export all pages.
            </Form.Text>
          </Form.Group>

          <Form.Group className="mb-3">
            <Form.Label>
              Card image DPI: <b>{exportSettings.imageDPI} DPI</b>
            </Form.Label>
            <Form.Range
              min={100}
              max={1500}
              step={100}
              value={exportSettings.imageDPI}
              data-testid="display-export-image-dpi"
              onChange={(event) =>
                setField("imageDPI", parseInt(event.target.value, 10))
              }
            />
            <Form.Label>
              JPG quality: <b>{exportSettings.jpgQuality}%</b>
            </Form.Label>
            <Form.Range
              min={5}
              max={100}
              step={5}
              value={exportSettings.jpgQuality}
              data-testid="display-export-jpg-quality"
              onChange={(event) =>
                setField("jpgQuality", parseInt(event.target.value, 10))
              }
            />
            <Form.Text className="text-muted">
              Higher DPI and quality print sharper but produce a much larger
              file and a slower export - 600 DPI / 100% matches a real print
              run; drop both for a quick proof copy.
            </Form.Text>
          </Form.Group>

          {sheetSettings.showCutLines && (
            <Form.Group className="mb-3">
              <Form.Label>Cut line colour</Form.Label>
              <Form.Control
                type="color"
                data-testid="display-export-cut-line-color"
                value={exportSettings.cutLineColor}
                onChange={(event) =>
                  setField("cutLineColor", event.target.value)
                }
              />
              <Form.Label className="mt-2">Cut line shape</Form.Label>
              <Form.Select
                size="sm"
                data-testid="display-export-cut-line-shape"
                value={exportSettings.cutLineShape}
                onChange={(event) =>
                  setField(
                    "cutLineShape",
                    event.target.value as keyof typeof CutLineShape
                  )
                }
              >
                {Object.entries(CutLineShape).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowSettings(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={isDownloading}
            data-testid="display-export-pdf-download-button"
            onClick={() => {
              setShowSettings(false);
              downloadPDF();
            }}
          >
            {isDownloading ? <Spinner size={1} /> : "Download PDF"}
          </Button>
        </Modal.Footer>
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
    </>
  );
}
