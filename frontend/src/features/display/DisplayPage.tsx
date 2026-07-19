/**
 * Proposal H (docs/proposals/proposal-h-unified-display-page.md) — the unified display page's
 * shell: a top toolbar, a live print-sheet preview (reusing PagePreview/computeLayout from
 * Proposal A - see PagePreview.tsx), slot selection, and the rail's always-visible status header
 * + accordion (AutofillCollapse, per the owner's accordion amendment). Choose Image is wired to
 * the real candidate/version picker (Step 2 PR 2a - see ChooseImageSection below, and
 * useGridSelectorSearch.ts/GridSelectorResults.tsx, extracted from GridSelectorModal.tsx so both
 * surfaces share one real search implementation). The always-visible header now carries the real
 * requested-printing badge (Step 2 PR 2b - degraded-style variant keyed off
 * EditorSearchResponse.degradedQueries, wired end to end through searchResultsSlice's
 * selectIsSearchQueryDegraded) and the real DeckbuilderConfirmAffordance (same component
 * CardSlot.tsx mounts, adapted only via its onOpenGridSelector prop - the rail has no modal to
 * open, so N expands the Choose Image section instead). Every other accordion section still
 * renders a labeled stub - see each section's own comment for which later PR fills it in, per
 * the design doc's §6 migration/sequencing plan.
 *
 * Deliberately NOT built here (see the design doc + this task's relay reports for the full
 * reasoning): the tablet off-canvas drawer and mobile bottom-sheet overlay interaction patterns
 * (§3) - below `md` the rail stacks in plain document flow below the sheet, which is usable but
 * not yet the polished drawer/overlay the doc specifies; that's follow-up work, not silently
 * dropped. Front-only pagination (see displayPagination.ts's own module comment) - a Fronts/
 * Backs toggle reuses the existing frontsVisible view setting rather than PDFGenerator's
 * export-time front-then-distinct-back interleaving.
 */
import styled from "@emotion/styled";
import Link from "next/link";
import React, { useMemo, useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import ProgressBar from "react-bootstrap/ProgressBar";

import {
  Back,
  BleedEdgeMM,
  CardHeightMM,
  CardWidthMM,
  Front,
} from "@/common/constants";
import {
  CardDocument,
  Faces,
  SearchQuery,
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import { AutofillCollapse } from "@/components/AutofillCollapse";
import { Spinner } from "@/components/Spinner";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { paginateSlotsForDisplay } from "@/features/display/displayPagination";
import { isGoogleDriveAppConfigured } from "@/features/googleDrive/googleDriveConfig";
import { GridSelectorResults } from "@/features/gridSelector/GridSelectorResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { computeLayout } from "@/features/pdf/layout";
import {
  PagePreview,
  PagePreviewSlotContent,
} from "@/features/pdf/PagePreview";
import { getPageSizeMM, PageSize, PDFProps } from "@/features/pdf/PDF";
import {
  ImageFailureConfirmModal,
  useDownloadPDF,
  useSaveToDrivePDF,
} from "@/features/pdf/PDFGenerator";
import { ImageFetchFailure } from "@/features/pdf/pdfImage";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  selectIsProjectEmpty,
  selectManualOverrides,
  selectProjectCardback,
  selectProjectMember,
  selectProjectMembers,
  setSelectedImages,
} from "@/store/slices/projectSlice";
import {
  selectIsSearchQueryDegraded,
  selectSearchResultsForQueryOrDefault,
} from "@/store/slices/searchResultsSlice";
import {
  selectFrontsVisible,
  toggleFaces,
} from "@/store/slices/viewSettingsSlice";

//# region local, page-only settings state
//
// A deliberately small subset of PDFGenerator.tsx's full settings panel - just enough to drive
// a genuinely live sheet (real computeLayout() inputs, not fake ones). The rest of that panel
// (card selection mode, cut-line geometry, quality/DPI, SCM mode, spacing/margins) stays on the
// classic PDF tab for now; relocating all of it here is Step 3 (switchover) in the design doc's
// §6 sequencing, not Step 1.

interface DisplaySheetSettings {
  pageSize: keyof typeof PageSize;
  bleedEdgeMM: number;
  showCutLines: boolean;
}

const DEFAULT_SHEET_SETTINGS: DisplaySheetSettings = {
  pageSize: "A4",
  bleedEdgeMM: BleedEdgeMM,
  showCutLines: true,
};

//# endregion

//# region accordion section stubs

type AccordionSectionKey =
  | "chooseImage"
  | "attributes"
  | "printOptions"
  | "artist"
  | "slotActions";

const DEFAULT_EXPANDED: Record<AccordionSectionKey, boolean> = {
  chooseImage: true,
  attributes: false,
  printOptions: false,
  artist: false,
  slotActions: false,
};

const Stub = ({ children }: { children: React.ReactNode }) => (
  <p className="text-muted small mb-0" data-testid="display-rail-stub">
    {children}
  </p>
);

interface RailSectionProps {
  sectionKey: AccordionSectionKey;
  title: string;
  expandedSections: Record<AccordionSectionKey, boolean>;
  onToggle: (key: AccordionSectionKey) => void;
  children: React.ReactElement;
}

const RailSection = ({
  sectionKey,
  title,
  expandedSections,
  onToggle,
  children,
}: RailSectionProps) => (
  <AutofillCollapse
    title={<h6 className="mb-0">{title}</h6>}
    expanded={expandedSections[sectionKey]}
    onClick={() => onToggle(sectionKey)}
    pad={2}
  >
    {children}
  </AutofillCollapse>
);

//# endregion

//# region always-visible rail header

interface RailHeaderProps {
  face: Faces;
  slot: number;
  cardName: string | undefined;
  printingBadge: string | undefined;
  // Whether this slot's printing-specific search (expansionCode/collectorNumber) found nothing
  // and the backend retried it unfiltered - EditorSearchResponse.degradedQueries, wired end to
  // end in Step 2's second instrument PR (see selectIsSearchQueryDegraded). Meaningless when
  // printingBadge is undefined (no printing filter to have degraded in the first place).
  isDegraded: boolean;
  cardIdentifier: string | undefined;
  searchQuery: SearchQuery | undefined;
  onOpenChooseImage: () => void;
}

const RailHeader = ({
  face,
  slot,
  cardName,
  printingBadge,
  isDegraded,
  cardIdentifier,
  searchQuery,
  onOpenChooseImage,
}: RailHeaderProps) => (
  <div className="p-2 border-bottom" data-testid="display-rail-header">
    <div className="fw-bold">
      Slot {slot + 1}{" "}
      <span className="text-muted text-uppercase small ms-1">{face}</span>
    </div>
    <div>
      {cardName ?? (
        <span className="text-muted fst-italic">No art selected yet</span>
      )}
    </div>
    {printingBadge != null && (
      <span
        className={`badge mt-1 ${
          isDegraded ? "bg-warning text-dark" : "bg-secondary"
        }`}
        style={{ fontFamily: "monospace" }}
        data-testid="display-printing-badge"
        data-degraded={isDegraded}
        title={
          isDegraded
            ? "This printing wasn't found - showing the closest available match instead."
            : undefined
        }
      >
        {isDegraded && <i className="bi bi-exclamation-triangle-fill me-1" />}
        {printingBadge}
      </span>
    )}
    {/* Adapts CardSlot.tsx's own mount of this component (same props, same gating logic inside
        DeckbuilderConfirmAffordance itself - not forked) for the rail's status header: N's
        "open the grid selector" becomes "expand (or keep expanded, if already open) the Choose
        Image accordion section" here instead of opening GridSelectorModal, since the rail has
        no modal to open - see the design doc's §4.3/§4.4. */}
    {cardIdentifier != null && (
      <DeckbuilderConfirmAffordance
        cardIdentifier={cardIdentifier}
        searchQuery={searchQuery}
        onOpenGridSelector={onOpenChooseImage}
      />
    )}
  </div>
);

//# endregion

//# region Choose Image section (PR 2a - the real candidate/version picker)

interface ChooseImageSectionProps {
  face: Faces;
  slot: number;
  query: SearchQuery | undefined;
  selectedImage: string | undefined;
}

// Reuses the same real search/filter machinery GridSelectorModal itself now delegates to
// (useGridSelectorSearch + GridSelectorResults, extracted in this PR) rather than a modal - the
// design doc's §4.4 calls for this to render inline in the rail's own scroll container, not a
// second overlapping dialog. Selecting an image dispatches the same setSelectedImages action
// CardSlot.tsx's own grid selector uses, so the sheet's thumbnail for this slot updates
// immediately (same Redux state, same PagePreview render path).
const ChooseImageSection = ({
  face,
  slot,
  query,
  selectedImage,
}: ChooseImageSectionProps) => {
  const dispatch = useAppDispatch();
  const searchResultsForQuery =
    useAppSelector((state) =>
      selectSearchResultsForQueryOrDefault(
        state,
        query?.query,
        query?.cardType,
        query?.expansionCode,
        query?.collectorNumber,
        face
      )
    ) ?? [];
  const focusRef = useRef<HTMLInputElement>(null);
  const search = useGridSelectorSearch({
    imageIdentifiers: searchResultsForQuery,
    active: true,
  });

  const onSelectImage = (identifier: string) => {
    dispatch(
      setSelectedImages({
        slots: [[face, slot]],
        selectedImage: identifier,
        deselect: true,
      })
    );
  };

  if (searchResultsForQuery.length === 0) {
    return (
      <p className="text-muted small mb-0">
        No candidate images found for this slot&apos;s query.
      </p>
    );
  }

  return (
    <>
      <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
        <span className="text-muted small">
          {search.resultCount.toLocaleString()} result
          {search.resultCount !== 1 ? "s" : ""}
        </span>
        <Button
          variant="outline-primary"
          size="sm"
          onClick={() => search.setSettingsVisible((v) => !v)}
        >
          <i
            className={`bi bi-chevron-${
              search.settingsVisible ? "left" : "right"
            }`}
          />{" "}
          Filters
        </Button>
      </div>
      <GridSelectorResults
        variant="embedded"
        imageIdentifiers={searchResultsForQuery}
        selectedImage={selectedImage}
        onSelectImage={onSelectImage}
        focusRef={focusRef}
        search={search}
      />
    </>
  );
};

//# endregion

interface SelectedSlotRef {
  face: Faces;
  slot: number;
}

// Static (plain document flow) below `md`, sticky with its own scroll container from `md` up -
// mirrors cardPanel.tsx's own static-below-md/sticky-at-md-up precedent (docs/lessons.md's
// sticky/z-index entry) via ONE styled element with a media query, not a duplicate render
// toggled by Bootstrap's d-none/d-md-none utilities (which would duplicate every testid/
// heading/interactive control in the DOM at every viewport).
const RailWrapper = styled.div`
  width: 380px;
  max-width: 100%;
  position: static;

  @media (min-width: 768px) {
    position: sticky;
    top: 0;
    max-height: 100vh;
    overflow-y: auto;
  }
`;

interface RailProps {
  selectedSlotRef: SelectedSlotRef | null;
  // CardDocument | undefined, not just CardDocument: useCardDocumentsByIdentifier's own return
  // type (cardDocumentsSlice.ts) is deliberately widened to include undefined - a project
  // member's CardDocument may not have been fetched yet, and the missing annotation used to
  // hide that from tsc entirely (see that file's own comment, task #135). Every actual field
  // access below already goes through `?.`, so this is a type-only fix - no behavior change.
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
}

const Rail = ({ selectedSlotRef, cardDocumentsByIdentifier }: RailProps) => {
  const [expandedSections, setExpandedSections] =
    useState<Record<AccordionSectionKey, boolean>>(DEFAULT_EXPANDED);

  const projectMember = useAppSelector((state) =>
    selectedSlotRef != null
      ? selectProjectMember(state, selectedSlotRef.face, selectedSlotRef.slot)
      : undefined
  );
  const query = projectMember?.query;
  // Hooks must run unconditionally on every render (same order regardless of selectedSlotRef),
  // so this - like the projectMember selector above - is called before the idle-state early
  // return below, with the "nothing selected yet" case handled inside the selector itself
  // rather than by skipping the call.
  const isDegraded = useAppSelector((state) =>
    selectIsSearchQueryDegraded(
      state,
      query?.query,
      query?.cardType,
      query?.expansionCode,
      query?.collectorNumber
    )
  );

  if (selectedSlotRef == null) {
    return (
      <div
        className="text-muted text-center fst-italic p-4"
        data-testid="display-rail-idle"
      >
        Select a card on the sheet to see its details.
      </div>
    );
  }

  const selectedImage = projectMember?.selectedImage;
  const cardName =
    selectedImage != null
      ? cardDocumentsByIdentifier[selectedImage]?.name
      : undefined;
  const printingBadge =
    query?.expansionCode != null
      ? `${query.expansionCode.toUpperCase()}${
          query.collectorNumber ? " " + query.collectorNumber : ""
        }`
      : undefined;

  const onToggle = (key: AccordionSectionKey) =>
    setExpandedSections((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  // "focus, if already open" (design doc §4.3.4) - always force-open, never toggle-closed, so
  // the Confirm affordance's N path can't accidentally collapse a section the user already had
  // open.
  const onOpenChooseImage = () =>
    setExpandedSections((previous) => ({ ...previous, chooseImage: true }));

  return (
    <div data-testid="display-rail-content">
      <RailHeader
        face={selectedSlotRef.face}
        slot={selectedSlotRef.slot}
        cardName={cardName}
        printingBadge={printingBadge}
        isDegraded={isDegraded}
        cardIdentifier={selectedImage}
        searchQuery={query}
        onOpenChooseImage={onOpenChooseImage}
      />
      <RailSection
        sectionKey="chooseImage"
        title="Choose Image"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <ChooseImageSection
          face={selectedSlotRef.face}
          slot={selectedSlotRef.slot}
          query={query}
          selectedImage={selectedImage}
        />
      </RailSection>
      <RailSection
        sectionKey="attributes"
        title="Attributes"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <Stub>
          Attribute chips (AttributeChipPanel) land here in Step 2&apos;s third
          instrument-parity PR.
        </Stub>
      </RailSection>
      <RailSection
        sectionKey="printOptions"
        title="Print Options"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <Stub>
          Per-card bleed override — blocked on Proposal B PR-2 (its Auto/Force
          bleed/Force trimmed control + projectSlice persistence haven&apos;t
          shipped yet); this section ships once that lands.
        </Stub>
      </RailSection>
      <RailSection
        sectionKey="artist"
        title="Artist"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <Stub>
          The artist line + support link lands here in Step 2&apos;s fifth
          instrument-parity PR.
        </Stub>
      </RailSection>
      <RailSection
        sectionKey="slotActions"
        title="Slot Actions"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <Stub>
          Change Query / Duplicate / Delete (CardSlotMenuActions) land here in
          Step 2&apos;s fourth instrument-parity PR.
        </Stub>
      </RailSection>
    </div>
  );
};

export function DisplayPage() {
  const dispatch = useAppDispatch();
  const projectMembers = useAppSelector(selectProjectMembers);
  const projectCardback = useAppSelector(selectProjectCardback);
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const frontsVisible = useAppSelector(selectFrontsVisible);
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();

  const [settings, setSettings] = useState<DisplaySheetSettings>(
    DEFAULT_SHEET_SETTINGS
  );
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedSlotRef, setSelectedSlotRef] =
    useState<SelectedSlotRef | null>(null);

  const activeFace: Faces = frontsVisible ? Front : Back;

  // Landscape: PDF.tsx's own PageSize table is portrait-oriented (matches the classic PDF
  // export's own page-size semantics, unchanged there) - swapping width/height here is what
  // makes THIS page's sheet landscape, per the design doc's own default. See the design doc's
  // §1 for the computeLayout() math confirming this yields a 4x2 grid at A4 + realistic bleed.
  const portraitSize = getPageSizeMM(settings.pageSize, undefined, undefined);
  const sheetWidthMM = portraitSize.height;
  const sheetHeightMM = portraitSize.width;

  const margins = useMemo(() => ({ top: 5, bottom: 5, left: 5, right: 5 }), []);
  const spacing = useMemo(() => ({ row: 0, col: 0 }), []);

  //# region inline export (item 2, owner's hands-on review) - the real export pipeline, run
  // in-page rather than navigating to the classic PDF tab. Reuses PDFGenerator.tsx's own
  // useDownloadPDF/useSaveToDrivePDF/ImageFailureConfirmModal verbatim (exported for this, not
  // forked) - same #81 paced-fetcher/retry machinery, same in-app failure-confirm modal, same
  // Google Drive upload path. Only this page's own settings feed it (paper size, bleed edge,
  // guides, the sheet's current fronts/backs view) - every other PDFProps field neither exposed
  // here nor meaningful for this page's default "export what you see" use case (card selection
  // mode, cut-line geometry, quality/DPI, spacing/margins, SCM mode) takes PDFGenerator's own
  // documented default, matching its classic-tab behavior exactly for anyone who hasn't touched
  // those settings there either.

  const { clientSearchService } = useClientSearchContext();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const manualOverrides = useAppSelector(selectManualOverrides);

  const [isDownloading, setIsDownloading] = useState<boolean>(false);
  const [isSavingToDrive, setIsSavingToDrive] = useState<boolean>(false);
  const [imageFetchProgress, setImageFetchProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  // Determinate while images are still being fetched (a real count, "N of ~M"); indeterminate
  // once every image has resolved but @react-pdf/renderer is still assembling the file itself -
  // pdfRenderService/pdf.worker.ts only report per-image progress, so "assembling" is inferred
  // the moment completed reaches total, not a separate signal the worker sends.
  const [exportPhase, setExportPhase] = useState<
    "fetching" | "assembling" | null
  >(null);
  const [pendingFailureConfirm, setPendingFailureConfirm] = useState<{
    failures: Array<ImageFetchFailure>;
    resolve: (value: boolean) => void;
  } | null>(null);
  const confirmDespiteFailures = (
    failures: Array<ImageFetchFailure>
  ): Promise<boolean> =>
    new Promise((resolve) => setPendingFailureConfirm({ failures, resolve }));

  const setExportProgress = (
    progress: { completed: number; total: number } | null
  ) => {
    setImageFetchProgress(progress);
    if (progress == null) {
      setExportPhase(null);
    } else {
      setExportPhase(
        progress.total > 0 && progress.completed >= progress.total
          ? "assembling"
          : "fetching"
      );
    }
  };

  // CUSTOM + explicit width/height, not the named pageSize alone - PDF.tsx's getPageSizeMM only
  // honours pageWidth/pageHeight when pageSize is "CUSTOM" (otherwise it returns that name's own
  // portrait dimensions), so this is what makes the exported file match this page's own
  // landscape sheet (sheetWidthMM/sheetHeightMM, computed just below) rather than silently
  // reverting to portrait.
  const exportPdfProps: Omit<PDFProps, "fileHandles"> = {
    cardSelectionMode: "frontsAndDistinctBacks",
    pageSize: "CUSTOM",
    pageWidth: sheetWidthMM,
    pageHeight: sheetHeightMM,
    bleedEdgeMM: settings.bleedEdgeMM,
    roundCorners: false,
    drawCardCutLines: settings.showCutLines,
    drawPageCutLines: true,
    cutLineLengthMM: 2,
    cutLineOffsetMM: 0,
    cutLineThicknessMM: 0.2,
    cutLineColor: "#FF0000",
    cutLinePlacement: "Inside",
    cutLineShape: "InsideOnly",
    cardSpacingRowMM: spacing.row,
    cardSpacingColMM: spacing.col,
    pageMarginTopMM: margins.top,
    pageMarginBottomMM: margins.bottom,
    pageMarginLeftMM: margins.left,
    pageMarginRightMM: margins.right,
    cardDocumentsByIdentifier: cardDocumentsByIdentifier,
    projectMembers: projectMembers,
    projectCardback: projectCardback,
    bleedOverrides: manualOverrides,
    scmMode: false,
    scmPaperSize: "letter",
    scmVariant: "default",
    scmRegistration: 3,
    scmDuplex: true,
    scmOffsetXMM: 0,
    scmOffsetYMM: 0,
    scmOffsetAngleDeg: 0,
    imageQuality: "full-resolution",
    imageDPI: 600,
    jpgQuality: 100,
  };

  const generatePdf = useDownloadPDF(
    exportPdfProps,
    clientSearchService,
    dispatch,
    setIsDownloading,
    backendURL,
    setExportProgress,
    confirmDespiteFailures
  );
  const saveToDrive = useSaveToDrivePDF(
    exportPdfProps,
    clientSearchService,
    dispatch,
    setIsSavingToDrive,
    backendURL,
    setExportProgress,
    confirmDespiteFailures
  );

  //# endregion

  const layout = useMemo(
    // Mirrors PagePreview's own computeLayout() call so cardsPerPage here matches exactly
    // what the sheet itself will render - both this page and PagePreview compute from the
    // same inputs via the same pure function, rather than one deriving cardsPerPage from the
    // other's internals.
    () =>
      computeLayout(
        sheetWidthMM,
        sheetHeightMM,
        CardWidthMM,
        CardHeightMM,
        settings.bleedEdgeMM,
        margins,
        spacing
      ),
    [sheetWidthMM, sheetHeightMM, settings.bleedEdgeMM, margins, spacing]
  );
  const cardsPerPage = layout.cardsPerRow * layout.cardsPerCol;

  const pages = useMemo(
    () => paginateSlotsForDisplay(projectMembers, cardsPerPage),
    [projectMembers, cardsPerPage]
  );
  const pageCount = Math.max(pages.length, 1);
  const clampedPageIndex = Math.min(pageIndex, pageCount - 1);
  const currentPageEntries = pages[clampedPageIndex] ?? [];

  // Only this one page's slots ever get resolved to thumbnail URLs and handed to
  // PagePreview - the performance rule from the design doc ("render only the current sheet
  // page"). `pages` above is cheap index bookkeeping, not image work.
  const currentPageSlots: Array<PagePreviewSlotContent> =
    currentPageEntries.map((entry) => {
      const projectMember = entry.member[activeFace];
      const identifier = projectMember?.selectedImage;
      const cardDocument =
        identifier != null ? cardDocumentsByIdentifier[identifier] : undefined;
      return {
        imageUrl: cardDocument?.mediumThumbnailUrl,
        name: cardDocument?.name ?? `Slot ${entry.slot + 1}`,
      };
    });

  const handleSlotClick = (indexOnPage: number) => {
    const entry = currentPageEntries[indexOnPage];
    if (entry == null) {
      return;
    }
    setSelectedSlotRef({ face: activeFace, slot: entry.slot });
  };

  const selectedSlotIndexOnPage =
    selectedSlotRef != null && selectedSlotRef.face === activeFace
      ? currentPageEntries.findIndex(
          (entry) => entry.slot === selectedSlotRef.slot
        )
      : -1;

  if (isProjectEmpty) {
    return (
      <div className="text-center p-5" data-testid="display-empty-state">
        <p>Your project is empty at the moment.</p>
        <p>
          <Link href="/editor">Head to the editor</Link> to add cards, then come
          back here.
        </p>
      </div>
    );
  }

  return (
    <div className="d-flex flex-column" data-testid="display-page">
      <div
        className="d-flex align-items-center flex-wrap gap-2 px-3 py-2 border-bottom"
        data-testid="display-toolbar"
      >
        <div className="d-flex align-items-center gap-2">
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
            disabled={clampedPageIndex === 0}
            aria-label="Previous page"
          >
            ◀
          </Button>
          <span data-testid="display-page-indicator">
            Page {clampedPageIndex + 1} of {pageCount}
          </span>
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => setPageIndex((i) => Math.min(pageCount - 1, i + 1))}
            disabled={clampedPageIndex >= pageCount - 1}
            aria-label="Next page"
          >
            ▶
          </Button>
        </div>

        <Button
          size="sm"
          variant="outline-secondary"
          onClick={() => dispatch(toggleFaces())}
        >
          {frontsVisible ? "Showing: Fronts" : "Showing: Backs"}
        </Button>

        <Form.Select
          size="sm"
          style={{ width: "auto" }}
          value={settings.pageSize}
          onChange={(event) =>
            setSettings((previous) => ({
              ...previous,
              pageSize: event.target.value as keyof typeof PageSize,
            }))
          }
          aria-label="Paper size"
        >
          {Object.keys(PageSize)
            .filter((key) => key !== "CUSTOM")
            .map((key) => (
              <option key={key} value={key}>
                {key} (landscape)
              </option>
            ))}
        </Form.Select>

        <Form.Control
          size="sm"
          type="number"
          style={{ width: "6rem" }}
          min={0}
          max={BleedEdgeMM}
          step={0.1}
          value={settings.bleedEdgeMM}
          onChange={(event) => {
            const value = parseFloat(event.target.value);
            if (!Number.isNaN(value)) {
              setSettings((previous) => ({ ...previous, bleedEdgeMM: value }));
            }
          }}
          aria-label="Bleed edge (mm)"
        />

        <Form.Check
          type="switch"
          id="display-cut-lines-toggle"
          label="Guides"
          checked={settings.showCutLines}
          onChange={(event) =>
            setSettings((previous) => ({
              ...previous,
              showCutLines: event.target.checked,
            }))
          }
        />

        <div className="ms-auto d-flex align-items-center gap-2">
          {isGoogleDriveAppConfigured() && (
            <Button
              size="sm"
              variant="outline-primary"
              onClick={saveToDrive}
              disabled={isSavingToDrive || isDownloading}
              data-testid="display-save-to-drive"
            >
              {isSavingToDrive ? (
                <Spinner size={1.2} />
              ) : (
                "Save PDF to Google Drive"
              )}
            </Button>
          )}
          <Button
            size="sm"
            variant="primary"
            onClick={generatePdf}
            disabled={isDownloading || isSavingToDrive}
            data-testid="display-generate-pdf"
          >
            {isDownloading ? <Spinner size={1.2} /> : "Generate PDF"}
          </Button>
        </div>
      </div>

      {/* Item 2 (owner's hands-on review): a real determinate progress bar, not a spinner - a
          large export paced to the image CDN's shared rate limit (see pdfImage.ts) can take
          several minutes, and this is what turns that wait into "fetching images: N of ~M"
          instead of something that looks hung. Switches to an indeterminate "Assembling PDF…"
          bar once every image has resolved but the file itself is still being built - see
          setExportProgress's own comment for how that phase is inferred. */}
      {exportPhase != null && (
        <div
          className="px-3 py-2 border-bottom"
          data-testid="display-export-progress"
        >
          {exportPhase === "fetching" && imageFetchProgress != null ? (
            <ProgressBar
              now={
                imageFetchProgress.total > 0
                  ? (imageFetchProgress.completed / imageFetchProgress.total) *
                    100
                  : 0
              }
              label={`Fetching images: ${imageFetchProgress.completed} of ~${imageFetchProgress.total}`}
              data-testid="display-export-progress-bar"
            />
          ) : (
            <ProgressBar
              now={100}
              animated
              striped
              label="Assembling PDF…"
              data-testid="display-export-progress-bar"
            />
          )}
        </div>
      )}

      {/* position: relative + an explicit non-auto z-index together, on the sticky rail's own
          PARENT - the specific fix docs/lessons.md's sticky/z-index entry documents (part 3):
          without both together, the rail's necessary stacking context can escape to an
          ancestor and make its own subtree un-hit-testable, even though it still paints fine. */}
      <div
        className="d-flex flex-column flex-md-row flex-grow-1"
        style={{ position: "relative", zIndex: 0 }}
      >
        <div
          className="flex-grow-1 d-flex justify-content-center p-3"
          data-testid="display-sheet-region"
        >
          <PagePreview
            pageWidthMM={sheetWidthMM}
            pageHeightMM={sheetHeightMM}
            bleedEdgeMM={settings.bleedEdgeMM}
            margins={margins}
            spacing={spacing}
            slots={currentPageSlots}
            showCutLines={settings.showCutLines}
            maxWidthPx={960}
            onSlotClick={handleSlotClick}
            selectedSlotIndex={
              selectedSlotIndexOnPage >= 0 ? selectedSlotIndexOnPage : undefined
            }
          />
        </div>

        {/* Sticky + its own scroll container only from md up; plain document flow below md -
            ONE rendered instance either way (a second copy toggled by Bootstrap's d-none/
            d-md-none utility classes would duplicate every testid/heading/interactive control
            in the DOM at every viewport, which is exactly what a real screen reader - and this
            page's own Playwright suite - would trip over). Mirrors cardPanel.tsx's own
            static-below-md/sticky-at-md-up precedent (see docs/lessons.md's sticky/z-index
            entry) via a single styled wrapper with a media query, not a duplicate render. The
            tablet drawer and mobile bottom-sheet overlay this eventually becomes are follow-up
            work - see this component's own module comment. */}
        <RailWrapper className="border-start" data-testid="display-rail">
          {/* `key` here (not inside Rail itself) is what actually forces a remount on slot
              change - a key set on an element INSIDE a component's own render output has no
              effect on that same component's hooks; only the key the PARENT assigns to the
              component element does. Caught by this page's own Playwright suite: without this,
              expandedSections silently persisted across slot selections instead of resetting to
              the documented per-slot default (see the design doc's §4.2). */}
          <Rail
            key={
              selectedSlotRef != null
                ? `${selectedSlotRef.face}-${selectedSlotRef.slot}`
                : "idle"
            }
            selectedSlotRef={selectedSlotRef}
            cardDocumentsByIdentifier={cardDocumentsByIdentifier}
          />
        </RailWrapper>
      </div>
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
    </div>
  );
}
