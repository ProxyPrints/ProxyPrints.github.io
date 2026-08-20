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
 * Export-time settings (card selection mode, page range, image quality, cut-line geometry,
 * corner rounding, an advanced page-margin override, and Silhouette/SCM cutting mode) are choices
 * about the OUTPUT FILE, not the sheet's own layout, so they live here - alongside the export
 * affordance itself, in a small settings step between clicking "PDF" and the actual download -
 * rather than joining the right rail's Page Setup section, which governs what the live sheet
 * shows, not what a given export run produces. Plain Bootstrap form controls only (no
 * `AutofillCollapse`/`StyledDropdownTreeSelect`/`NumericField` from `PDFGenerator.tsx`) so this
 * component stays free of that file's own import graph.
 *
 * ## Grouping
 *
 * SCM mode reads as a MODE SWITCH, not another checkbox in a list: it replaces the standard
 * parametric grid with `SCMPDF.tsx`'s registration-mark layout entirely (`PDF.tsx`'s `PDF`
 * component returns early into `<SCMPDF>` and never touches card selection, cut-line geometry,
 * corner rounding, or page margins for that render), so the settings step swaps its body between
 * two mutually-exclusive panels rather than appending SCM's six sub-settings to the existing
 * list. Only image quality (DPI/JPG) is genuinely shared between both panels - `SCMCard` reads it
 * exactly like the standard grid's own card image does - so it stays visible in both.
 */
import React, { useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import Dropdown from "react-bootstrap/Dropdown";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";
import { createPortal } from "react-dom";

import { useAppDispatch, useAppSelector } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { MARGIN_PROFILES } from "@/features/display/marginProfiles";
import { PostExportContributionPrompt } from "@/features/export/PostExportContributionPrompt";
import { wasLatestCardsPdfDownloadSuccessful } from "@/features/export/postExportContributionPrompt";
import { usePostExportContributionPrompt } from "@/features/export/usePostExportContributionPrompt";
import { isGoogleDriveAppConfigured } from "@/features/googleDrive/googleDriveConfig";
import {
  DisplayExportSettings,
  DisplaySheetExportSettings,
  PageMarginOverride,
  useDisplayPDFProps,
} from "@/features/pdf/displayPdfProps";
import {
  CardSelectionMode,
  computePDFPageCount,
  DEFAULT_CARD_SELECTION_MODE,
} from "@/features/pdf/PDF";
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
import {
  ScmPaperLabels,
  ScmPaperSize,
  ScmVariant,
} from "@/features/pdf/scm/scmLayout";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectMarginProfile } from "@/store/slices/marginProfileSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

export interface DisplayExportPDFProps {
  sheetSettings: DisplaySheetExportSettings;
  /** `usePrePrintSaveGate.startPrintFlow` - runs the draft-flush/cardback-reminder/save-before-
   * export gate sequence, then calls the proceed callback given to it. Wraps this component's own
   * Download/Save-to-Drive buttons so that sequence still runs on every export, now that the
   * Finish footer no longer routes anywhere to reach it (see FinishFooter.tsx's own comment). */
  runExportGate: (proceed: () => void) => void;
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

const SCM_VARIANT_LABELS: { [variant in ScmVariant]: string } = {
  default: "Normal",
  borderless: "Borderless",
};

const DEFAULT_EXPORT_SETTINGS: DisplayExportSettings = {
  cardSelectionMode: DEFAULT_CARD_SELECTION_MODE,
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  imageDPI: 600,
  jpgQuality: 100,
  // Matches PagePreview.tsx's own E19 lime guide colour (#8ae234), so the export's default
  // outline colour matches what the sheet already showed on screen.
  cutLineColor: "#8ae234",
  // Crosshair corner marks are an opt-in addition to the default dashed trim outline
  // (PDF.tsx's PDFProps.showCrossCutLines) - off by default.
  showCrossCutLines: false,
  cutLineLengthMM: 3,
  cutLineThicknessMM: 0.6,
  cutLineOffsetMM: 0,
  roundCorners: false,
  // Matches /print's PDFGenerator.tsx's own default - a guillotine cutting a printed stack
  // relies on these, independent of whether per-card cut lines are also on.
  drawPageCutLines: true,
  marginOverride: undefined,
  scmMode: false,
  scmPaperSize: "letter",
  scmVariant: "default",
  scmRegistration: 3,
  scmDuplex: true,
  scmOffsetXMM: 0,
  scmOffsetYMM: 0,
  scmOffsetAngleDeg: 0,
};

export function DisplayExportPDF({
  sheetSettings,
  runExportGate,
}: DisplayExportPDFProps) {
  const dispatch = useAppDispatch();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const marginProfile = useAppSelector(selectMarginProfile).profile;
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
  // Not meaningful in SCM mode (SCM paginates independently - see computePDFPageCount's own
  // comment), so the Pages control itself is hidden whenever scmMode is on (below).
  const totalPages = useMemo(() => computePDFPageCount(pdfProps), [pdfProps]);

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

  const setMarginOverrideField = <K extends keyof PageMarginOverride>(
    key: K,
    value: number
  ) =>
    setExportSettings((previous) =>
      previous.marginOverride
        ? {
            ...previous,
            marginOverride: { ...previous.marginOverride, [key]: value },
          }
        : previous
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
          {/* Cutting mode - a mode switch, not another checkbox: it swaps the entire body below
              between the standard-grid panel and SCM's own six sub-settings (see this file's own
              module comment). */}
          <div className="border rounded p-2 mb-3 bg-body-tertiary">
            <Form.Check
              type="switch"
              id="display-export-scm-mode-switch"
              data-testid="display-export-scm-mode-switch"
              label={<strong>Silhouette (SCM) cutting mode</strong>}
              checked={exportSettings.scmMode}
              onChange={(event) => setField("scmMode", event.target.checked)}
            />
            <Form.Text className="text-muted">
              Exports a Silhouette Studio-compatible registration-mark layout
              instead of the standard grid - a different file format, not a
              style option.
            </Form.Text>
          </div>

          {exportSettings.scmMode ? (
            <>
              <Form.Group className="mb-3">
                <Form.Label>Paper size</Form.Label>
                <Form.Select
                  size="sm"
                  data-testid="display-export-scm-paper-size"
                  value={exportSettings.scmPaperSize}
                  onChange={(event) =>
                    setField("scmPaperSize", event.target.value as ScmPaperSize)
                  }
                >
                  {Object.entries(ScmPaperLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Template variant</Form.Label>
                <Form.Select
                  size="sm"
                  data-testid="display-export-scm-variant"
                  value={exportSettings.scmVariant}
                  onChange={(event) =>
                    setField("scmVariant", event.target.value as ScmVariant)
                  }
                >
                  {Object.entries(SCM_VARIANT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Registration marks</Form.Label>
                <Form.Select
                  size="sm"
                  data-testid="display-export-scm-registration"
                  value={exportSettings.scmRegistration}
                  onChange={(event) =>
                    setField(
                      "scmRegistration",
                      parseInt(event.target.value, 10) as 3 | 4
                    )
                  }
                >
                  <option value={3}>3-corner (default)</option>
                  <option value={4}>4-corner (Cameo 5 Alpha)</option>
                </Form.Select>
              </Form.Group>

              <Form.Check
                type="switch"
                id="display-export-scm-duplex"
                className="mb-3"
                data-testid="display-export-scm-duplex"
                label={exportSettings.scmDuplex ? "Duplex" : "Fronts only"}
                checked={exportSettings.scmDuplex}
                onChange={(event) =>
                  setField("scmDuplex", event.target.checked)
                }
              />

              <Form.Group className="mb-3">
                <Form.Label>Back-alignment offset (mm)</Form.Label>
                <div className="d-flex gap-2 align-items-center">
                  <Form.Control
                    type="number"
                    size="sm"
                    step={0.1}
                    aria-label="Back-alignment offset X (mm)"
                    data-testid="display-export-scm-offset-x"
                    value={exportSettings.scmOffsetXMM}
                    onChange={(event) => {
                      const value = parseFloat(event.target.value);
                      if (!Number.isNaN(value)) setField("scmOffsetXMM", value);
                    }}
                  />
                  <Form.Control
                    type="number"
                    size="sm"
                    step={0.1}
                    aria-label="Back-alignment offset Y (mm)"
                    data-testid="display-export-scm-offset-y"
                    value={exportSettings.scmOffsetYMM}
                    onChange={(event) => {
                      const value = parseFloat(event.target.value);
                      if (!Number.isNaN(value)) setField("scmOffsetYMM", value);
                    }}
                  />
                </div>
                <Form.Text className="text-muted">
                  Corrects duplex printer misalignment on the back page - X then
                  Y.
                </Form.Text>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Offset angle (degrees)</Form.Label>
                <Form.Control
                  type="number"
                  size="sm"
                  step={0.1}
                  data-testid="display-export-scm-offset-angle"
                  value={exportSettings.scmOffsetAngleDeg}
                  onChange={(event) => {
                    const value = parseFloat(event.target.value);
                    if (!Number.isNaN(value))
                      setField("scmOffsetAngleDeg", value);
                  }}
                />
              </Form.Group>
            </>
          ) : (
            <>
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
            </>
          )}

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

          {!exportSettings.scmMode && (
            <>
              <Form.Check
                type="switch"
                id="display-export-page-cut-lines"
                className="mb-3"
                data-testid="display-export-page-cut-lines"
                label={
                  exportSettings.drawPageCutLines
                    ? "Page cut guide lines: On"
                    : "Page cut guide lines: Off"
                }
                checked={exportSettings.drawPageCutLines}
                onChange={(event) =>
                  setField("drawPageCutLines", event.target.checked)
                }
              />
              <Form.Text className="text-muted d-block mb-3">
                Guide lines across the whole sheet for cutting a printed stack
                with a guillotine - independent of the per-card cut lines below.
              </Form.Text>

              {sheetSettings.showCutLines && (
                <Form.Group className="mb-3">
                  <Form.Label>Cut line</Form.Label>
                  <div className="d-flex gap-2 align-items-center mb-2">
                    <Form.Control
                      type="color"
                      data-testid="display-export-cut-line-color"
                      value={exportSettings.cutLineColor}
                      onChange={(event) =>
                        setField("cutLineColor", event.target.value)
                      }
                    />
                    <Form.Control
                      type="number"
                      size="sm"
                      step={0.1}
                      min={0}
                      aria-label="Cut line length (mm)"
                      data-testid="display-export-cut-line-length"
                      value={exportSettings.cutLineLengthMM}
                      onChange={(event) => {
                        const value = parseFloat(event.target.value);
                        if (!Number.isNaN(value))
                          setField("cutLineLengthMM", value);
                      }}
                    />
                    <Form.Control
                      type="number"
                      size="sm"
                      step={0.1}
                      min={0}
                      aria-label="Cut line thickness (mm)"
                      data-testid="display-export-cut-line-thickness"
                      value={exportSettings.cutLineThicknessMM}
                      onChange={(event) => {
                        const value = parseFloat(event.target.value);
                        if (!Number.isNaN(value))
                          setField("cutLineThicknessMM", value);
                      }}
                    />
                    <Form.Control
                      type="number"
                      size="sm"
                      step={0.1}
                      aria-label="Cut line offset (mm)"
                      data-testid="display-export-cut-line-offset"
                      value={exportSettings.cutLineOffsetMM}
                      onChange={(event) => {
                        const value = parseFloat(event.target.value);
                        if (!Number.isNaN(value))
                          setField("cutLineOffsetMM", value);
                      }}
                    />
                  </div>
                  <Form.Text className="text-muted d-block mb-2">
                    Colour, then length / thickness / offset (mm), left to right
                    - applies to the dashed trim outline traced on the
                    card&apos;s cut boundary, and to the crosshair marks below
                    if enabled.
                  </Form.Text>
                  <Form.Check
                    type="switch"
                    id="display-export-cross-cut-lines"
                    data-testid="display-export-cross-cut-lines"
                    label="Also show crosshair corner marks"
                    checked={exportSettings.showCrossCutLines}
                    onChange={(event) =>
                      setField("showCrossCutLines", event.target.checked)
                    }
                  />
                </Form.Group>
              )}

              <Form.Check
                type="switch"
                id="display-export-round-corners"
                className="mb-3"
                data-testid="display-export-round-corners"
                label={
                  exportSettings.roundCorners
                    ? "Round corners"
                    : "Square corners"
                }
                checked={exportSettings.roundCorners}
                onChange={(event) =>
                  setField("roundCorners", event.target.checked)
                }
              />

              <Form.Group className="mb-3">
                <Form.Check
                  type="checkbox"
                  id="display-export-margin-override-toggle"
                  data-testid="display-export-margin-override-toggle"
                  label="Override page margins for this export"
                  checked={exportSettings.marginOverride !== undefined}
                  onChange={(event) =>
                    setField(
                      "marginOverride",
                      event.target.checked
                        ? { ...MARGIN_PROFILES[marginProfile].margins }
                        : undefined
                    )
                  }
                />
                {exportSettings.marginOverride && (
                  <>
                    <div className="d-flex gap-2 align-items-center mt-2">
                      <Form.Control
                        type="number"
                        size="sm"
                        step={0.1}
                        min={0}
                        aria-label="Top margin (mm)"
                        data-testid="display-export-margin-top"
                        value={exportSettings.marginOverride.top}
                        onChange={(event) => {
                          const value = parseFloat(event.target.value);
                          if (!Number.isNaN(value))
                            setMarginOverrideField("top", value);
                        }}
                      />
                      <Form.Control
                        type="number"
                        size="sm"
                        step={0.1}
                        min={0}
                        aria-label="Bottom margin (mm)"
                        data-testid="display-export-margin-bottom"
                        value={exportSettings.marginOverride.bottom}
                        onChange={(event) => {
                          const value = parseFloat(event.target.value);
                          if (!Number.isNaN(value))
                            setMarginOverrideField("bottom", value);
                        }}
                      />
                      <Form.Control
                        type="number"
                        size="sm"
                        step={0.1}
                        min={0}
                        aria-label="Left margin (mm)"
                        data-testid="display-export-margin-left"
                        value={exportSettings.marginOverride.left}
                        onChange={(event) => {
                          const value = parseFloat(event.target.value);
                          if (!Number.isNaN(value))
                            setMarginOverrideField("left", value);
                        }}
                      />
                      <Form.Control
                        type="number"
                        size="sm"
                        step={0.1}
                        min={0}
                        aria-label="Right margin (mm)"
                        data-testid="display-export-margin-right"
                        value={exportSettings.marginOverride.right}
                        onChange={(event) => {
                          const value = parseFloat(event.target.value);
                          if (!Number.isNaN(value))
                            setMarginOverrideField("right", value);
                        }}
                      />
                    </div>
                    <Form.Text className="text-muted">
                      Top / bottom / left / right, seeded from the rail&apos;s
                      current margin profile. Overrides that profile for this
                      export only - the live sheet and the profile itself are
                      unaffected.
                    </Form.Text>
                  </>
                )}
              </Form.Group>
            </>
          )}
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
