/**
 * Proposal H (docs/proposals/proposal-h-unified-display-page.md) — the unified display page's
 * shell: a top toolbar, a live print-sheet preview (reusing PagePreview/computeLayout from
 * Proposal A - see PagePreview.tsx), slot selection, and the rail's always-visible status header
 * + accordion (AutofillCollapse, per the owner's accordion amendment). Choose Image is wired to
 * the real candidate/version picker (originally Step 2 PR 2a's flat GridSelectorResults grid,
 * replaced by the unified Select Version section - issue #167, SelectVersionResults.tsx - see
 * ChooseImageSection below; still shares useGridSelectorSearch.ts's search/filter state machine
 * with GridSelectorModal.tsx's own unchanged modal variant). The always-visible header now
 * carries the real requested-printing badge (Step 2 PR 2b - degraded-style variant keyed off
 * EditorSearchResponse.degradedQueries, wired end to end through searchResultsSlice's
 * selectIsSearchQueryDegraded; later extracted into its own RequestedPrintingBadge.tsx component
 * - item (c) of the frontend-polish package - so CardSlot.tsx's editor slots could mount the
 * exact same badge, one component instead of two copies that could drift) and the real
 * DeckbuilderConfirmAffordance (same component CardSlot.tsx mounts, adapted only via its
 * onOpenGridSelector prop - the rail has no modal to open, so N expands the Choose Image section
 * instead; SelectVersionResults.tsx also reuses this same component verbatim for its own
 * suggested-printing confirm moment - see that file's own module comment). Left-panel
 * unification (issue #164) filled in every remaining rail section: Attributes
 * (AttributesSection.tsx - the same tap/vote-submission logic AttributeChipPanel.tsx uses via the
 * shared useTagVoting hook, rendered as a plain vertical stack instead of a ring around a card),
 * Print Options (PrintOptionsSection.tsx - the same per-card bleed override
 * projectSlice/PDF.tsx's isBleedNormalizationEligible already implement for the classic PDF tab's
 * Bleed Overrides panel), Artist (ArtistSection.tsx - inherits ArtistSupportLink directly, per
 * docs/features/artist-support-links.md's own anticipated follow-on), and Slot Actions
 * (SlotActionsSection.tsx - the same getCardSlotMenuActions list CardSlot.tsx's 3-dot dropdown/
 * context menu use, rendered as a plain action list rather than a dropdown overlay). Every rail
 * section is now real, not a stub - see docs/proposals/proposal-h-unified-display-page.md's own
 * status line for what's still not built (tablet/mobile interaction patterns and the switchover
 * step).
 *
 * Item 3 (owner's hands-on review, flat-scroll amendment) replaced the original one-page-at-a-
 * time pager with a continuous vertical stack of every sheet (`sheets`, derived from
 * displayPagination.ts's `paginateSlotsForDisplay`) - each sheet's PagePreview mounts only when
 * on/near screen via RenderIfVisible (components/RenderIfVisible.tsx, already proven in
 * CardResultSet.tsx), so a large deck never holds more real <img> elements in memory than what's
 * actually near the viewport. The toolbar's old prev/next pager is gone; what remains is a
 * passive "Sheet N of M" readout driven by its own, tighter-band IntersectionObserver (distinct
 * from RenderIfVisible's own broader mount/unmount one - see the two effects' own comments).
 *
 * Deliberately NOT built here (see the design doc + this task's relay reports for the full
 * reasoning): the tablet off-canvas drawer and mobile bottom-sheet overlay interaction patterns
 * (§3) - below `md` the rail stacks in plain document flow below the sheet, which is usable but
 * not yet the polished drawer/overlay the doc specifies; that's follow-up work, not silently
 * dropped. Front-only pagination (see displayPagination.ts's own module comment) - a Fronts/
 * Backs toggle reuses the existing frontsVisible view setting rather than PDFGenerator's
 * export-time front-then-distinct-back interleaving.
 *
 * Issue #166 (post-export contribution prompt) - after a genuinely successful "Generate PDF" or
 * "Save PDF to Google Drive", a dismissible prompt points the user at the existing "What's That
 * Card?" vote-queue funnel (docs/features/printing-tags.md). See
 * features/export/postExportContributionPrompt.ts + usePostExportContributionPrompt.ts for the
 * success-detection and show-once-per-session logic - the same hook/component pair is also
 * mounted from PDFGenerator.tsx itself, so the classic "Print!" tab gets it too.
 *
 * Issue #238 (deck-input landing, design doc §4.1) - the `isProjectEmpty` early return used to
 * render only a plain "head to /editor" link, meaning this page could never start a project
 * standalone. See DeckInputLanding below: the same plain ImportText/ImportURL/ImportXML/ImportCSV
 * components ProjectEditor.tsx's own AddCardsPanel mounts, reused (not forked) inline in place of
 * that link - once addMembers fires, isProjectEmpty flips false and this component re-renders
 * straight into the sheet+rail layout below on its own.
 *
 * Issue #239 (Search Settings toolbar parity, design doc §5's SearchSettings row) - the toolbar
 * previously had no way to reach precise/fuzzy search type, DPI/file-size filter ranges, or
 * source reordering/toggling at all on this page. SearchSettings.tsx (the same self-contained
 * trigger-button-plus-modal ProjectEditor.tsx already mounts) is relocated in, unmodified - same
 * Modal, same searchSettingsSlice read/write, same setLocalStorageSearchSettings persistence path.
 *
 * Issue #240 (Cardback toolbar parity, design doc §5's CommonCardback row) - the toolbar
 * previously had no way to reach the project-wide cardback picker at all on this page (only the
 * classic editor's own right panel could). CardbackToolbarButton (CommonCardback.tsx) is a new,
 * small button+modal pairing - reusing MemoizedCommonCardbackGridSelector's existing
 * GridSelectorModal verbatim - rather than mounting CommonCardback itself, since that component's
 * swatch/prev-next CardFooter chrome belongs to the editor's right panel, not a toolbar button.
 *
 * Issue #241 (Export ▾ toolbar parity, design doc §5's export-beyond-PDF row) - the last of the
 * three toolbar-parity findings from the same audit. DisplayExportMenu.tsx composes the same
 * unchanged ExportXML/ExportImages/ExportDecklist Dropdown.Items Export.tsx already mounts on the
 * classic editor's own "Download" dropdown - same hooks, same gating selectors. ExportPDF.tsx's
 * own item is deliberately excluded, since this page's Generate PDF button already reuses
 * useDownloadPDF directly rather than opening the classic PDFGenerator modal that item dispatches
 * to (see the inline-export region comment below).
 *
 * Issue #266 (mobile responsive shell - docs/proposals' /display layout spec, owner-approved
 * 2026-07-21, §2/§4/§6 rows R1/R2/R4/R5/R6) replaced the single always-rendered `RailWrapper`
 * (static below md, sticky-in-place from md up) with the spec's real four-tier shell:
 *   - The sheet region now measures its own width via `ResizeObserver` (`sheetRenderWidthPx`)
 *     instead of a fixed constant, so `PagePreview`'s existing `maxWidthPx` prop fits the sheet to
 *     whatever width is actually available - phones get the WHOLE landscape page, scaled down,
 *     rather than a fixed-width sheet clipped by the viewport (the design doc's "only the middle
 *     cards visible" symptom, issue #266's own repro). No `PagePreview` changes - it already scales
 *     to any width.
 *   - Both rails are now ONE `Offcanvas` node each (`responsive="lg"` left, `responsive="xl"`
 *     right) - inline/sticky at their own breakpoint, a real dismissible drawer below it
 *     (`useViewportTier.ts` drives the left rail's phone-bottom-sheet vs. tablet-start-drawer
 *     placement switch, since Offcanvas's own `responsive` prop only knows one breakpoint at a
 *     time). Selecting a slot opens the left rail even where it's a drawer (harmless at inline
 *     tiers, where `show` is ignored - see Offcanvas's own source). Opening either rail closes the
 *     other, so the two overlays never stack.
 *   - The right rail is new: the settings/export controls this page used to keep in the toolbar
 *     unconditionally (paper size, bleed, guides, Fronts/Backs, Search Settings, Cardback, the
 *     export cluster, and the fetch-progress bar) are relocated there, reachable via the action
 *     bar's gear button below `xl` (hidden entirely at `xl`+, where the rail is already inline).
 *     This is, necessarily, also half of the design doc's §6 row T1 (the OTHER half - the
 *     populated-state add-cards search bar replacing the rest of the toolbar, T2-T5/I1 - is
 *     issue #267's own scope, not touched here): R4 (#266) can't have real content in its new
 *     placement without the controls actually moving out of the toolbar, so that move happens
 *     here using the existing components completely unforked, not the full #267 action-bar
 *     redesign. The right rail's sections are plain, always-expanded groups (not yet the spec's
 *     `AutofillCollapse` per-section chrome/collapsed-by-default hierarchy) - deferred to keep
 *     this PR's test surface to "open the drawer first", not "expand a section first" too.
 *   - Deliberately NOT built here (see the design doc's own issue-mapping + this file's own
 *     module comment history): the `CardDetailedViewBody` extraction and D3's promoted/demoted
 *     content reorder (design doc §7.5/R3 - its own follow-up, the rail's existing accordion
 *     content is reused as-is in the new placements), the D4-D6 4x2/margins/bleed defaults and D8
 *     color calibration (new scope beyond #266-268, own future issues), the #267 search-bar
 *     migration/action-bar sticky wrapper, and the #268 saved-decks landing.
 *
 * Issue #267 (design doc §3/§6 T2-T5/I1, ADDENDUM D12/D13/D15 - owner's locked comment on #267,
 * 2026-07-21) finishes the populated-state action bar #266 deferred, plus the row-mapped polish
 * additions:
 *   - The search bar (§3): a dual-mode Add/Browse `ToggleButtonGroup` prefix, one shared
 *     `searchBarText` state. Add mode mounts `ImportText`'s new "inline" `variant` prop (T3 -
 *     additive, default-unchanged, so every existing block-variant caller is untouched) - Enter
 *     runs the exact same `convertLinesIntoSlotProjectMembers`/`addMembers` pipeline the block
 *     variant does. Browse mode (D12, owner's locked comment: "v1 is FILTERS-FIRST plus plain
 *     text - typed operator grammar is #276, explicitly out of scope") binds the SAME text state
 *     to a plain controlled `Form.Control` instead - `ImportText` itself stays entirely unaware
 *     of Browse mode, per the "shared components gain only additive optional props" constraint.
 *     Beside the input, the existing `Import.tsx` dropdown (D15, = T4 restated) mounts verbatim -
 *     Text/XML/CSV/URL, zero new importer UI, closing the "add cards to a non-empty project"
 *     parity gap.
 *   - Browse results (D12/F10): a new `CatalogBrowseResults.tsx` (own module comment has the full
 *     reasoning, including a documented tile-reuse deviation) renders in the CENTER region,
 *     behind a "Print sheets"/"Browse results" `ToggleButtonGroup` bound to the SAME
 *     `isBrowseMode` state as the search bar's own mode toggle - one state, two controls, per the
 *     mockup's own demonstrated behavior (not the more elaborate two-independent-states reading
 *     the spec prose alone could suggest).
 *   - Invalid-identifiers feedback (D13's landing/search-bar half only - the right-rail Status
 *     row is issue #272's own remaining scope, not this one): `InvalidIdentifiersStatus` (already
 *     self-hiding, already dispatching `showModal("invalidIdentifiers")` into the globally-mounted
 *     `InvalidIdentifiersModal` - see `Layout.tsx`'s `<Modals />`) is mounted unmodified in both
 *     the populated-state action bar and the empty-project `DeckInputLanding`.
 *   - Phone condensation (T5): `ActionBarSearchGroup`'s own `@media (max-width: 767.98px)` rule
 *     gives the search-bar group the design doc §1 region table's specified "Full-width 2nd row"
 *     treatment, not just whatever a bare `flex-wrap` reflow happens to produce.
 */
import styled from "@emotion/styled";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Accordion } from "react-bootstrap";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Form from "react-bootstrap/Form";
import Offcanvas, { OffcanvasPlacement } from "react-bootstrap/Offcanvas";
import ProgressBar from "react-bootstrap/ProgressBar";
import Row from "react-bootstrap/Row";
import ToggleButton from "react-bootstrap/ToggleButton";
import ToggleButtonGroup from "react-bootstrap/ToggleButtonGroup";

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
import { RightPaddedIcon } from "@/components/icon";
import { RenderIfVisible } from "@/components/RenderIfVisible";
import { Spinner } from "@/components/Spinner";
import { CardbackToolbarButton } from "@/features/card/CommonCardback";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { RequestedPrintingBadge } from "@/features/card/RequestedPrintingBadge";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { ArtistSection } from "@/features/display/ArtistSection";
import { AttributesSection } from "@/features/display/AttributesSection";
import { CatalogBrowseResults } from "@/features/display/CatalogBrowseResults";
import { paginateSlotsForDisplay } from "@/features/display/displayPagination";
import { PrintOptionsSection } from "@/features/display/PrintOptionsSection";
import { SlotActionsSection } from "@/features/display/SlotActionsSection";
import { useViewportTier } from "@/features/display/useViewportTier";
import { DisplayExportMenu } from "@/features/export/DisplayExportMenu";
import { PostExportContributionPrompt } from "@/features/export/PostExportContributionPrompt";
import { wasLatestCardsPdfDownloadSuccessful } from "@/features/export/postExportContributionPrompt";
import { usePostExportContributionPrompt } from "@/features/export/usePostExportContributionPrompt";
import { isGoogleDriveAppConfigured } from "@/features/googleDrive/googleDriveConfig";
import { SelectVersionResults } from "@/features/gridSelector/SelectVersionResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { Import } from "@/features/import/Import";
import { ImportCSV } from "@/features/import/ImportCSV";
import { ImportText } from "@/features/import/ImportText";
import { ImportURL } from "@/features/import/ImportURL";
import { ImportXML } from "@/features/import/ImportXML";
import { InvalidIdentifiersStatus } from "@/features/invalidIdentifiers/InvalidIdentifiersStatus";
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
import { SavedDeckPanel } from "@/features/savedDecks/SavedDeckPanel";
import { SearchSettings } from "@/features/searchSettings/SearchSettings";
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
import { selectSearchResultsForQueryOrDefault } from "@/store/slices/searchResultsSlice";
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

// Upper bound, in real CSS px, on every sheet's rendered width - was PagePreview's own fixed
// maxWidthPx={960} prop before Item 3, and stayed a fixed value until issue #266's fit-to-width
// rule: the sheet-region ResizeObserver below now clamps to whichever is SMALLER, this cap or the
// region's actual measured width, so a narrow viewport (phone/tablet, or a laptop/desktop rail
// eating into the region) shrinks the sheet instead of clipping it. Still the same shared constant
// sheetPixelHeightPx needs for its own height estimate, just no longer the only input.
const SHEET_MAX_WIDTH_PX = 960;

//# endregion

//# region accordion sections

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
  cardIdentifier: string | undefined;
  searchQuery: SearchQuery | undefined;
  onOpenChooseImage: () => void;
}

const RailHeader = ({
  face,
  slot,
  cardName,
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
    {/* Item (c) of the frontend-polish package extracted this into its own shared component
        (RequestedPrintingBadge.tsx) so CardSlot.tsx's editor slots could mount the identical
        badge - one place the degraded-style logic lives, so the two surfaces can't drift. */}
    <div className="mt-1">
      <RequestedPrintingBadge query={searchQuery} />
    </div>
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

//# region Choose Image section (issue #167 - the unified Select Version section, spec §4.4′)

interface ChooseImageSectionProps {
  face: Faces;
  slot: number;
  query: SearchQuery | undefined;
  selectedImage: string | undefined;
  backendURL: string;
}

// Reuses the same real search/filter machinery GridSelectorModal itself now delegates to
// (useGridSelectorSearch, still shared with the modal variant) rather than a modal - the design
// doc's §4.4 calls for this to render inline in the rail's own scroll container, not a second
// overlapping dialog. Selecting an image dispatches the same setSelectedImages action
// CardSlot.tsx's own grid selector uses, so the sheet's thumbnail for this slot updates
// immediately (same Redux state, same PagePreview render path). The results themselves are now
// SelectVersionResults (issue #167) - grouped by printing/reason-tag/unknown per the spec's §4.4′
// rather than GridSelectorResults' flat CardResultSet grid; GridSelectorModal.tsx's own modal
// variant (CardSlot.tsx's editor grid) is untouched, out of this issue's scope.
const ChooseImageSection = ({
  face,
  slot,
  query,
  selectedImage,
  backendURL,
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
      <SelectVersionResults
        imageIdentifiers={searchResultsForQuery}
        selectedImage={selectedImage}
        onSelectImage={onSelectImage}
        focusRef={focusRef}
        search={search}
        requestedPrinting={
          query?.expansionCode != null
            ? {
                expansionCode: query.expansionCode,
                collectorNumber: query.collectorNumber,
              }
            : undefined
        }
        backendURL={backendURL}
      />
    </>
  );
};

//# endregion

//# region deck-input landing (issue #238, design doc §4.1)

// Renders the same plain import components ProjectEditor.tsx's own AddCardsPanel mounts on the
// classic editor's "Add Cards" tab - ImportText/ImportURL/ImportXML/ImportCSV - inline, in place
// of the old "go to /editor" link, so an empty project can be started without ever leaving this
// page. Deliberately NOT AddCardsPanel itself: that component wraps its two columns in an
// OverflowCol sized via a heightDelta of NavPillButtonHeight + NavbarHeight, both editor-tab-
// specific concepts this page has neither of (this page also has no bottom nav-pill tab strip to
// account for) - and NavbarHeight is a currently-wrong hardcoded constant (issue #250, navbar
// renders at 64px not the constant's 50px), so a second surface deriving a forced 100vh-minus-
// NavbarHeight scroll region from it would just compound that same bug here. This page's own
// root already sits inside Layout.tsx's fixed-position, overflow-y:scroll ContentContainer (see
// this file's own flat-scroll comment above), so the landing just flows in that existing scroll
// container - no forced height calc of its own needed.
//
// onImportComplete is intentionally omitted (design doc §4.1 step 3): once addMembers fires,
// selectIsProjectEmpty flips false and DisplayPage re-renders straight into the sheet+rail layout
// on its own - there's no separate tab to switch away from here, unlike ProjectEditor.tsx's own
// use of this same callback to flip its Tab.Panes. Confirmed safe to omit by reading all four
// components' own onImportComplete call sites: each dispatches addMembers synchronously, then
// (if the prop is provided at all) calls onImportComplete as its very last statement with no
// state updates afterwards - nothing here depends on this page's own subtree remaining mounted
// once that callback fires.
const DeckInputLanding = () => (
  <div className="p-3" data-testid="display-empty-state">
    <Row className="g-0">
      <Col lg={6} md={6} sm={12} xs={12} className="px-2">
        <h5>Enter a Card List</h5>
        <ImportText />
        {/* Design doc ADDENDUM D13 (issue #267's landing/search-bar feedback half) - the same
            self-contained, self-hiding status component (visible only when
            selectInvalidIdentifiersCount > 0) the populated-state action bar mounts below;
            attached here too so an import that leaves unresolved identifiers is visible on the
            empty-project landing, not just once a project already exists. */}
        <InvalidIdentifiersStatus />
      </Col>
      <Col lg={6} md={6} sm={12} xs={12} className="px-2">
        <h5>Import a File or URL</h5>
        <Accordion defaultActiveKey="url">
          <Accordion.Item eventKey="url">
            <Accordion.Header>
              <RightPaddedIcon bootstrapIconName="link-45deg" /> URL
            </Accordion.Header>
            <Accordion.Body>
              <ImportURL />
            </Accordion.Body>
          </Accordion.Item>
          <Accordion.Item eventKey="xml">
            <Accordion.Header>
              <RightPaddedIcon bootstrapIconName="file-code" /> XML
            </Accordion.Header>
            <Accordion.Body>
              <ImportXML />
            </Accordion.Body>
          </Accordion.Item>
          <Accordion.Item eventKey="csv">
            <Accordion.Header>
              <RightPaddedIcon bootstrapIconName="file-earmark-spreadsheet" />{" "}
              CSV
            </Accordion.Header>
            <Accordion.Body>
              <ImportCSV />
            </Accordion.Body>
          </Accordion.Item>
        </Accordion>
      </Col>
    </Row>
  </div>
);

//# endregion

interface SelectedSlotRef {
  face: Faces;
  slot: number;
}

// Issue #266 (design doc §4/§6 R2/R4) - the three-region body: left rail · sheet · right rail,
// laid out as a single flex row only once EITHER rail actually goes inline (`lg`, 992px - the
// left rail's own inline threshold, the first of the two). Below that, both rails render as
// fixed-position Offcanvas drawers (out of normal flow entirely - see LeftRailOffcanvas/
// RightRailOffcanvas below), so this wrapper only ever needs to arrange the sheet region itself.
// `position: relative; z-index: 0` is scoped to the SAME `lg`-up media query - the specific fix
// docs/lessons.md's sticky/z-index entry documents (part 3) - deliberately NOT applied below `lg`:
// react-bootstrap's Offcanvas dialog renders through a portal while open (its own z-index escapes
// any ancestor stacking context), so an unconditional zIndex: 0 parent here would only reintroduce
// the exact stacking trap this fix exists to avoid, for no benefit, on tiers where the rail is a
// drawer instead of an inline sibling (see the design doc's own portal note, §context/R2).
const DisplayBodyRegion = styled.div`
  display: flex;
  flex-direction: column;
  align-items: stretch;
  flex-grow: 1;

  @media (min-width: 992px) {
    flex-direction: row;
    align-items: flex-start;
    position: relative;
    z-index: 0;
  }
`;

// Both rails are ONE `Offcanvas` node each (design doc §4's "hard precedent... no d-none
// duplicate renders"): `responsive` picks the CSS class Bootstrap keys its own breakpoint media
// queries off (`.offcanvas-lg`/`.offcanvas-xl`), which - above that breakpoint - already resets
// `position`/`display` to plain in-flow values and hides `.offcanvas-header` entirely (Bootstrap's
// own stock CSS, not custom here). Everything below fills in what Bootstrap's inline reset
// deliberately leaves unstyled: a fixed width, sticky positioning, and its own scroll container -
// see the design doc's §4 "Inline styling... attaches via a wrapper class scoped to the inline
// tiers" instruction. The bottom-sheet's 72vh height + rounded top corners (design doc §4.1) are
// scoped to `.offcanvas-bottom` specifically, since this same node also renders as `.offcanvas-
// start` on tablet (leftPlacement below) - the two placements should not share sizing.
const LeftRailOffcanvas = styled(Offcanvas)`
  &.offcanvas-bottom {
    border-top-left-radius: 0.75rem;
    border-top-right-radius: 0.75rem;
  }

  @media (min-width: 992px) {
    &.offcanvas-lg {
      width: 380px;
      max-width: 380px;
      flex: 0 0 380px;
      position: sticky;
      top: 0;
      max-height: 100vh;
      overflow-y: auto;
      border-right: var(--bs-border-width) solid
        var(--bs-border-color-translucent);
    }
  }
`;

const RightRailOffcanvas = styled(Offcanvas)`
  @media (min-width: 1200px) {
    &.offcanvas-xl {
      width: 300px;
      max-width: 300px;
      flex: 0 0 300px;
      position: sticky;
      top: 0;
      max-height: 100vh;
      overflow-y: auto;
      border-left: var(--bs-border-width) solid
        var(--bs-border-color-translucent);
    }
  }
`;

// Design doc §4.1's tablet-only discoverability affordance: "a 'Card details' edge handle keeps
// it discoverable with nothing selected" - without this, a tablet user with no slot selected has
// no visible way to reach the left rail at all (there's nothing on the sheet to tap yet, and the
// gear only opens the RIGHT rail). Phone doesn't need this (D2's mockup omits it there too) -
// nothing-selected still shows the rail's own idle message, which is reachable by tapping any
// slot the moment one exists. Laptop/desktop don't need it either - the rail's already inline.
const TabletRailHandle = styled(Button)`
  display: none;

  @media (min-width: 768px) and (max-width: 991.98px) {
    display: block;
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 1030;
    writing-mode: vertical-rl;
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
  }
`;

// Issue #267 (design doc §1's region table + §6 T5) - "Add-cards search bar ... Full-width 2nd
// row" on phone specifically, not just whatever a bare `flex-wrap` reflow happens to produce
// (the mockup's own `.addbar{flex-basis:100%;order:9;}` chunk - see display-mockup.html). Below
// `md`, this group becomes its own full-width row (ordered after the sheet-indicator/SavedDeckPanel
// pair, before the gear) instead of squeezing into whatever horizontal space is left in the bar.
const ActionBarSearchGroup = styled.div`
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1 1 240px;
  min-width: 0;

  @media (max-width: 767.98px) {
    flex-basis: 100%;
    order: 9;
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
  backendURL: string;
  // Called after Slot Actions' Delete - see SlotActionsSection's own prop comment for why the
  // rail needs to hand control back to the page rather than just re-rendering its own subtree.
  onSlotDeleted: () => void;
}

const Rail = ({
  selectedSlotRef,
  cardDocumentsByIdentifier,
  backendURL,
  onSlotDeleted,
}: RailProps) => {
  const [expandedSections, setExpandedSections] =
    useState<Record<AccordionSectionKey, boolean>>(DEFAULT_EXPANDED);

  const projectMember = useAppSelector((state) =>
    selectedSlotRef != null
      ? selectProjectMember(state, selectedSlotRef.face, selectedSlotRef.slot)
      : undefined
  );
  const query = projectMember?.query;

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
          backendURL={backendURL}
        />
      </RailSection>
      <RailSection
        sectionKey="attributes"
        title="Attributes"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <AttributesSection
          backendURL={backendURL}
          cardIdentifier={selectedImage}
        />
      </RailSection>
      <RailSection
        sectionKey="printOptions"
        title="Print Options"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <PrintOptionsSection
          cardDocument={
            selectedImage != null
              ? cardDocumentsByIdentifier[selectedImage]
              : undefined
          }
        />
      </RailSection>
      <RailSection
        sectionKey="artist"
        title="Artist"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <ArtistSection
          cardDocument={
            selectedImage != null
              ? cardDocumentsByIdentifier[selectedImage]
              : undefined
          }
        />
      </RailSection>
      <RailSection
        sectionKey="slotActions"
        title="Slot Actions"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <SlotActionsSection
          face={selectedSlotRef.face}
          slot={selectedSlotRef.slot}
          searchQuery={query}
          onDeleted={onSlotDeleted}
        />
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
  const [selectedSlotRef, setSelectedSlotRef] =
    useState<SelectedSlotRef | null>(null);

  // Issue #267 (design doc ADDENDUM D12/F9) - the populated-state search bar's dual Add/Browse
  // mode. One boolean drives BOTH the search bar's own mode toggle and the center region's
  // "Print sheets"/"Browse results" switch (see DisplayBodyRegion's own render below) - the
  // mockup's real JS (setBrowse(on)) demonstrates these as one combined state, not two
  // independently toggleable pieces of state, so that's what's implemented here rather than the
  // more elaborate reading the spec prose alone could suggest. The search bar's own text is
  // shared between both modes too (Add mode's ImportText "inline" variant vs. Browse mode's
  // CatalogBrowseResults query) - see the action bar's own render below for why ImportText
  // itself stays entirely unaware of Browse mode (additive-prop-only constraint).
  const [isBrowseMode, setIsBrowseMode] = useState(false);
  const [searchBarText, setSearchBarText] = useState("");

  // Issue #266 (design doc §4) - which tier drives the left rail's drawer placement (phone:
  // bottom sheet, tablet: start drawer; laptop/desktop: inline, where placement is moot - see
  // LeftRailOffcanvas's own comment) and the gear button's visibility.
  const viewportTier = useViewportTier();
  const leftPlacement: OffcanvasPlacement =
    viewportTier === "phone" ? "bottom" : "start";
  const [leftRailOpen, setLeftRailOpen] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState(false);
  // Design doc §4's "two overlays, one screen" invariant - opening either rail closes the other,
  // so they never stack below their own inline tier. Harmless to call at inline tiers too:
  // Offcanvas ignores `show` there entirely (see its own source - `hideResponsiveOffcanvas`
  // forces the portal closed once the viewport reaches the `responsive` breakpoint).
  const openLeftRail = () => {
    setRightRailOpen(false);
    setLeftRailOpen(true);
  };
  const openRightRail = () => {
    setLeftRailOpen(false);
    setRightRailOpen(true);
  };

  const activeFace: Faces = frontsVisible ? Front : Back;

  // Landscape: PDF.tsx's own PageSize table is portrait-oriented (matches the classic PDF
  // export's own page-size semantics, unchanged there) - swapping width/height here is what
  // makes THIS page's sheet landscape, per the design doc's own default. See the design doc's
  // §1 for the computeLayout() math confirming this yields a 4x2 grid at A4 + realistic bleed.
  const portraitSize = getPageSizeMM(settings.pageSize, undefined, undefined);
  const sheetWidthMM = portraitSize.height;
  const sheetHeightMM = portraitSize.width;

  // Issue #266 (design doc §2, D1) - fit-to-width: the sheet region measures its own real
  // available width, and the rendered sheet is the SMALLER of that and SHEET_MAX_WIDTH_PX - no
  // PagePreview change, this only changes what's passed into its existing maxWidthPx prop. The
  // landscape page's own aspect ratio (already handled by PagePreview's scale-to-fit math) is
  // what naturally "letterboxes" it on a narrow viewport - the whole page shrinks proportionally,
  // it isn't a separately-drawn letterbox frame. Quantized to the nearest 8px so a sub-pixel
  // ResizeObserver jitter (common when a scrollbar appears/disappears) doesn't cause a visible
  // reflow loop.
  const [sheetRenderWidthPx, setSheetRenderWidthPx] =
    useState<number>(SHEET_MAX_WIDTH_PX);

  // The sheet-region div doesn't exist at the very first (empty-project) mount - this page's own
  // early-return below swaps the whole tree to `DeckInputLanding` until a project actually
  // starts - so the ResizeObserver has to attach lazily, once the real div mounts, not just once
  // at component-mount time. A callback ref writing into state (React's own documented pattern
  // for "an effect that needs to react to a DOM node changing", since a plain ref object's
  // mutation is invisible to React and won't re-run a dependent effect) is what makes the effect
  // below re-run whenever that div mounts/unmounts/remounts - covering the empty→populated
  // transition and any StrictMode-driven remount identically, with no risk of a stale observer
  // instance surviving past its own node (an earlier lazy-ref-initialized single ResizeObserver
  // wired up via ad hoc disconnect()/observe() calls in the ref callback itself was NOT
  // StrictMode-safe: dev-mode's double invoke of mount/cleanup could leave more than one live
  // observer instance racing to set this state, with a stale one's oversized last-fired
  // measurement winning and never getting corrected - see docs/troubleshooting.md's entry on
  // this, filed after CI caught the resulting overlap in `SelectVersionSection.spec.ts`).
  const [sheetRegionNode, setSheetRegionNode] = useState<HTMLDivElement | null>(
    null
  );
  const sheetRegionRef = useCallback((element: HTMLDivElement | null) => {
    setSheetRegionNode(element);
  }, []);

  useEffect(() => {
    if (sheetRegionNode == null || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const measuredWidthPx = entries[0]?.contentRect.width;
      if (measuredWidthPx == null || measuredWidthPx <= 0) {
        return;
      }
      const clampedWidthPx = Math.min(SHEET_MAX_WIDTH_PX, measuredWidthPx);
      setSheetRenderWidthPx(Math.max(160, Math.round(clampedWidthPx / 8) * 8));
    });
    observer.observe(sheetRegionNode);
    return () => observer.disconnect();
  }, [sheetRegionNode]);

  // Matches PagePreview's own internal scale-to-fit math exactly (scale = maxWidthPx /
  // pageWidthMM-in-px, height = pageHeightMM-in-px * scale - the px-per-mm factor cancels out),
  // so this estimate is exact, not approximate - RenderIfVisible's defaultHeight/visibleOffset
  // never has to correct a wrong guess via its own ResizeObserver fallback. Derives from the same
  // measured sheetRenderWidthPx (not the fixed cap) so virtualization placeholders stay exact at
  // every viewport, not just the desktop one.
  const sheetPixelHeightPx =
    sheetRenderWidthPx * (sheetHeightMM / sheetWidthMM);

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

  // Issue #166 - post-export contribution prompt. useDownloadPDF's returned promise resolves
  // void (its own useDoFileDownload wrapper swallows the inner success boolean - see
  // postExportContributionPrompt.ts's own comment), so success is read back out of the same
  // fileDownloads redux slice the download manager UI already populates, once this exact click's
  // download has finished. useSaveToDrivePDF has no such wrapper - .finally() passes its
  // .then()'s resolved boolean straight through, so awaiting saveToDrive() directly already
  // gives the real success/cancelled value.
  const contributionPrompt = usePostExportContributionPrompt();
  const onGeneratePdfClick = async () => {
    await generatePdf();
    if (wasLatestCardsPdfDownloadSuccessful()) {
      contributionPrompt.notifyExportSucceeded();
    }
  };
  const onSaveToDriveClick = async () => {
    const succeeded = await saveToDrive();
    if (succeeded === true) {
      contributionPrompt.notifyExportSucceeded();
    }
  };

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
  // Item 3 (owner's hands-on review, flat scroll amendment) - EVERY sheet's slots get resolved
  // here now, not just one page's, since the whole deck renders as one continuous vertical
  // stack. This is still cheap index/string bookkeeping, not image work - the actual per-slot
  // <img> only mounts once RenderIfVisible below decides a given sheet is on/near-screen, which
  // is what keeps this in line with the design doc's original "don't hold more image memory
  // than what's already on screen" rule. Always at least one sheet, even for an empty page's
  // worth of grid capacity - matches the page-shell's pre-flat-scroll behaviour of always
  // showing one (possibly all-placeholder) sheet rather than rendering nothing.
  const sheets = useMemo(
    () =>
      (pages.length > 0 ? pages : [[]]).map((entries, pageIndex) => ({
        pageIndex,
        entries,
        slots: entries.map((entry) => {
          const projectMember = entry.member[activeFace];
          const identifier = projectMember?.selectedImage;
          const cardDocument =
            identifier != null
              ? cardDocumentsByIdentifier[identifier]
              : undefined;
          const query = projectMember?.query;
          // Item 1 (owner's hands-on review) - a slot with no resolved thumbnail shows this on
          // the sheet itself instead of a blank hole. `undefined` only for a genuinely
          // query-less slot (a shared-cardback back face) - PagePreview then falls back to
          // `name`'s own "Slot N".
          const queryText =
            query?.query != null && query.query.length > 0
              ? `${query.query}${
                  query.expansionCode != null
                    ? ` (${query.expansionCode.toUpperCase()}${
                        query.collectorNumber ? " " + query.collectorNumber : ""
                      })`
                    : ""
                }`
              : undefined;
          const content: PagePreviewSlotContent = {
            imageUrl: cardDocument?.mediumThumbnailUrl,
            name: cardDocument?.name ?? `Slot ${entry.slot + 1}`,
            queryText,
          };
          return content;
        }),
      })),
    [pages, activeFace, cardDocumentsByIdentifier]
  );

  const handleSlotClick = (pageIndex: number, indexOnPage: number) => {
    const entry = sheets[pageIndex]?.entries[indexOnPage];
    if (entry == null) {
      return;
    }
    setSelectedSlotRef({ face: activeFace, slot: entry.slot });
    // Issue #266 (design doc §4.1) - "fixes 'tapping a card shows nothing'": below `lg`, the left
    // rail is a closed-by-default drawer, so selecting a slot must also open it. No-op at `lg`+,
    // where the rail is already inline and ignores `show` entirely.
    openLeftRail();
  };

  // Which sheet (not just which slot-on-a-page) currently holds the selected slot - needed now
  // that every sheet renders simultaneously, rather than only ever having "the current page"'s
  // own local index to check.
  const selectedSheetIndex =
    selectedSlotRef != null && selectedSlotRef.face === activeFace
      ? sheets.findIndex((sheet) =>
          sheet.entries.some((entry) => entry.slot === selectedSlotRef.slot)
        )
      : -1;

  // Passive "Sheet N of M" scroll-position indicator (design doc's flat-scroll amendment - a
  // read-only reflection of scroll position, not a navigation control like the old prev/next
  // pager). Deliberately its own IntersectionObserver, distinct from RenderIfVisible's below -
  // that one asks "should this sheet's images be mounted at all" (generous, ±1-sheet-ish
  // rootMargin); this one asks "which single sheet is the user currently looking at" (a thin
  // band near vertical centre), and the two thresholds are unrelated by design.
  const sheetRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [visibleSheetIndex, setVisibleSheetIndex] = useState(0);

  useEffect(() => {
    const indexByElement = new Map<Element, number>();
    sheetRefs.current.forEach((element, index) => {
      if (element != null) {
        indexByElement.set(element, index);
      }
    });
    if (indexByElement.size === 0) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const intersectingIndices = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => indexByElement.get(entry.target))
          .filter((index): index is number => index != null);
        if (intersectingIndices.length > 0) {
          setVisibleSheetIndex(Math.min(...intersectingIndices));
        }
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 }
    );
    indexByElement.forEach((_index, element) => observer.observe(element));
    return () => observer.disconnect();
  }, [sheets.length]);

  const clampedVisibleSheetIndex = Math.min(
    visibleSheetIndex,
    sheets.length - 1
  );

  if (isProjectEmpty) {
    return <DeckInputLanding />;
  }

  // Issue #266 (design doc §2/§4/§6 R4) - the export fetch-progress bar, extracted so both its
  // old top-of-page placement's markup and its new right-rail-footer placement below render the
  // exact same element rather than two hand-copied blocks that could drift.
  const exportProgressBar = exportPhase != null && (
    <div className="py-2" data-testid="display-export-progress">
      {exportPhase === "fetching" && imageFetchProgress != null ? (
        <ProgressBar
          now={
            imageFetchProgress.total > 0
              ? (imageFetchProgress.completed / imageFetchProgress.total) * 100
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
  );

  return (
    <div className="d-flex flex-column" data-testid="display-page">
      {/* Issue #266 (design doc §3/§6 R4) - identity + the gear that opens the right rail; the
          settings/export controls this toolbar used to hold unconditionally now live in
          RightRailOffcanvas below (necessarily also half of design doc row T1 - see this file's
          own module comment for why). Issue #267 (design doc §3/§6 T2-T5, ADDENDUM D12/D15) adds
          the populated-state add-cards/browse search bar: a dual-mode Add/Browse
          ToggleButtonGroup, the shared search-bar input (ImportText's "inline" variant in Add
          mode, a plain controlled Form.Control in Browse mode - see ActionBarSearchGroup's own
          comment for why ImportText itself stays unaware of Browse mode), and the existing
          Import.tsx dropdown (D15 - Text/XML/CSV/URL, verbatim, unforked). */}
      <div
        className="d-flex align-items-center flex-wrap gap-2 px-3 py-2 border-bottom"
        data-testid="display-toolbar"
      >
        <div className="d-flex align-items-center gap-2">
          {/* Passive scroll-position readout, not a control - see the visibleSheetIndex
              IntersectionObserver above. The whole deck is one continuous vertical stack now
              (Item 3, flat scroll amendment); there's nothing left here to page between. */}
          <span data-testid="display-sheet-indicator">
            Sheet {clampedVisibleSheetIndex + 1} of {sheets.length}
          </span>
        </div>

        {/* Issue #165, Proposal G save integration - the same reverse-breadcrumb + Save
            button ProjectEditor.tsx mounts (SavedDeckPanel is fully route-agnostic; only
            the spacing differs - see that component's own comment). Renders nothing at all
            for an anonymous session, matching the editor's degradation exactly. Doubles as
            this toolbar's "deck name" slot (design doc §2's information architecture never
            anticipated saved decks, since Proposal G landed after that doc's own pass - see
            saved-decks.md's "Where it's wired in" section for the full cross-reference). */}
        <SavedDeckPanel className="" />

        <ActionBarSearchGroup data-testid="display-search-bar-group">
          <ToggleButtonGroup
            type="radio"
            name="display-search-mode"
            value={isBrowseMode ? "browse" : "add"}
            onChange={(value) => setIsBrowseMode(value === "browse")}
          >
            <ToggleButton
              id="display-search-mode-add"
              value="add"
              variant="outline-secondary"
              size="sm"
              data-testid="display-search-mode-add"
            >
              Add
            </ToggleButton>
            <ToggleButton
              id="display-search-mode-browse"
              value="browse"
              variant="outline-secondary"
              size="sm"
              data-testid="display-search-mode-browse"
            >
              Browse
            </ToggleButton>
          </ToggleButtonGroup>

          {isBrowseMode ? (
            // Browse mode: the same shared searchBarText state, bound to a plain controlled
            // input rather than ImportText - CatalogBrowseResults (mounted in the center region
            // below) debounces off this value itself, there is no submit step here at all.
            <Form.Control
              size="sm"
              type="text"
              placeholder="Search the catalog… (e.g. Lightning Bolt)"
              value={searchBarText}
              onChange={(event) => setSearchBarText(event.target.value)}
              aria-label="catalog-browse-search"
              data-testid="display-browse-search-input"
            />
          ) : (
            <ImportText
              variant="inline"
              textValue={searchBarText}
              onTextChange={setSearchBarText}
              onImportComplete={() => setSearchBarText("")}
            />
          )}

          {/* Design doc ADDENDUM D15 (= §6 T4, restated) - the existing Import.tsx dropdown
              (Text/XML/CSV/URL *Button modal variants), mounted verbatim: no new importer UI,
              closes the "add cards to a non-empty project" parity gap #267 names. */}
          <Import />
        </ActionBarSearchGroup>

        {/* Design doc ADDENDUM D13 (issue #267's landing/search-bar feedback half) - self-hides
            when selectInvalidIdentifiersCount === 0, so this costs nothing when the project is
            clean. Its own flex-basis:100% (see the className below) keeps it from squeezing the
            bar's other controls - it wraps onto its own row only when it actually has something
            to show. */}
        <div className="w-100" style={{ order: 20 }}>
          <InvalidIdentifiersStatus />
        </div>

        {/* Design doc §1's region table: hidden entirely at desktop (≥1200, xl) where the right
            rail is already inline - visible at every narrower tier, where it's the only way to
            open it. */}
        <Button
          size="sm"
          variant="outline-secondary"
          className="ms-auto d-xl-none"
          onClick={openRightRail}
          aria-expanded={rightRailOpen}
          data-testid="display-gear-button"
          aria-label="Print & Settings"
        >
          <RightPaddedIcon bootstrapIconName="gear" />
          Print &amp; Settings
        </Button>
      </div>

      {/* Issue #166 - shown once per session, immediately after this button's first genuine
          export success (see usePostExportContributionPrompt.ts) - never blocks the export
          result above it, dismissible, and never re-fires again this session per its own
          show-once logic. */}
      {contributionPrompt.visible && (
        <div
          className="px-3 pt-2"
          data-testid="display-contribution-prompt-wrapper"
        >
          <PostExportContributionPrompt
            show={contributionPrompt.visible}
            onDismiss={contributionPrompt.dismiss}
          />
        </div>
      )}

      <DisplayBodyRegion>
        {/* Issue #266 (design doc §4.1) - ONE node, all widths: inline sticky 380px column at
            `lg`+, `placement="start"` drawer on tablet, `placement="bottom"` 72vh sheet on phone
            (leftPlacement, driven by useViewportTier.ts). Opens on slot tap below `lg`
            (handleSlotClick's own openLeftRail call) - closing does NOT clear selectedSlotRef, so
            re-opening (gear/handle/another slot tap) comes back to the same card. */}
        <LeftRailOffcanvas
          show={leftRailOpen}
          onHide={() => setLeftRailOpen(false)}
          responsive="lg"
          placement={leftPlacement}
          data-testid="display-rail"
          aria-label="Card details and art selection"
        >
          {leftPlacement === "bottom" && (
            <div
              className="d-flex justify-content-center pt-2 pb-1 d-lg-none"
              role="button"
              aria-label="Dismiss"
              onClick={() => setLeftRailOpen(false)}
            >
              <span
                style={{
                  width: 44,
                  height: 5,
                  borderRadius: 3,
                  backgroundColor: "var(--bs-border-color-translucent)",
                  display: "block",
                }}
              />
            </div>
          )}
          <Offcanvas.Header closeButton>
            <Offcanvas.Title>Card details</Offcanvas.Title>
          </Offcanvas.Header>
          <Offcanvas.Body>
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
              backendURL={backendURL ?? ""}
              onSlotDeleted={() => setSelectedSlotRef(null)}
            />
          </Offcanvas.Body>
        </LeftRailOffcanvas>

        <div
          ref={sheetRegionRef}
          className="flex-grow-1 d-flex flex-column align-items-center p-3"
          data-testid="display-sheet-region"
          style={{ minWidth: 0, width: "100%" }}
        >
          {/* Design doc ADDENDUM D12/F10 - the center region's own "Print sheets"/"Browse
              results" switch, bound to the SAME isBrowseMode state the action bar's Add/Browse
              toggle drives (see that state's own comment) - two controls for one state, not two
              independent ones, matching the mockup's real behavior. */}
          <ToggleButtonGroup
            type="radio"
            name="display-center-view"
            value={isBrowseMode ? "browse" : "sheets"}
            onChange={(value) => setIsBrowseMode(value === "browse")}
            className="mb-2"
          >
            <ToggleButton
              id="display-center-view-sheets"
              value="sheets"
              variant="outline-secondary"
              size="sm"
              data-testid="display-center-view-sheets"
            >
              Print sheets
            </ToggleButton>
            <ToggleButton
              id="display-center-view-browse"
              value="browse"
              variant="outline-secondary"
              size="sm"
              data-testid="display-center-view-browse"
            >
              Browse results
            </ToggleButton>
          </ToggleButtonGroup>

          {isBrowseMode ? (
            <CatalogBrowseResults query={searchBarText} />
          ) : (
            sheets.map((sheet) => (
              <div
                key={sheet.pageIndex}
                ref={(element) => {
                  sheetRefs.current[sheet.pageIndex] = element;
                }}
                data-sheet-index={sheet.pageIndex}
                data-testid="display-sheet-wrapper"
                className="d-flex flex-column align-items-center mb-4 p-2 border rounded"
              >
                <div
                  className="text-muted small mb-2"
                  data-testid="display-sheet-label"
                >
                  Sheet {sheet.pageIndex + 1} of {sheets.length}
                </div>
                {/* Sheet-level virtualization (Item 3's benchmark-gated requirement): only the
                  sheet(s) within one sheet-height of the viewport actually mount their
                  PagePreview (real <img> tags); everything further away is a fixed-height
                  placeholder div, per RenderIfVisible's own contract - see this component's
                  module comment for why a from-scratch IntersectionObserver wasn't needed here.
                  The first sheet starts mounted unconditionally so the common single-sheet case
                  never waits on an observer round-trip. */}
                <RenderIfVisible
                  initialVisible={sheet.pageIndex === 0}
                  defaultHeight={sheetPixelHeightPx}
                  visibleOffset={sheetPixelHeightPx}
                >
                  <PagePreview
                    pageWidthMM={sheetWidthMM}
                    pageHeightMM={sheetHeightMM}
                    bleedEdgeMM={settings.bleedEdgeMM}
                    margins={margins}
                    spacing={spacing}
                    slots={sheet.slots}
                    showCutLines={settings.showCutLines}
                    maxWidthPx={sheetRenderWidthPx}
                    onSlotClick={(indexOnPage) =>
                      handleSlotClick(sheet.pageIndex, indexOnPage)
                    }
                    selectedSlotIndex={
                      selectedSheetIndex === sheet.pageIndex
                        ? sheet.entries.findIndex(
                            (entry) => entry.slot === selectedSlotRef?.slot
                          )
                        : undefined
                    }
                  />
                </RenderIfVisible>
              </div>
            ))
          )}
        </div>

        {/* Issue #266 (design doc §4.2) - editing settings + preparing print, ONE node, all
            widths: inline sticky 300px column at `xl`+ (≥1200 - the region table's own "Laptop
            deliberately keeps the right rail as a drawer" call, 380+300 doesn't fit under the
            1200px ContentMaxWidth cap), `placement="end"` drawer everywhere narrower, opened by
            the action bar's gear button. Content here is the same components the toolbar used to
            mount unconditionally, relocated verbatim - not yet the design doc's own
            `AutofillCollapse` per-section chrome (deferred, see this file's own module comment). */}
        <RightRailOffcanvas
          show={rightRailOpen}
          onHide={() => setRightRailOpen(false)}
          responsive="xl"
          placement="end"
          style={
            {
              "--bs-offcanvas-width": "min(92vw, 320px)",
            } as React.CSSProperties
          }
          data-testid="display-print-settings-rail"
          aria-label="Print and project settings"
        >
          <Offcanvas.Header closeButton>
            <Offcanvas.Title>Print &amp; Settings</Offcanvas.Title>
          </Offcanvas.Header>
          <Offcanvas.Body className="d-flex flex-column p-0">
            <div className="flex-grow-1 overflow-auto p-3">
              <div className="mb-3">
                <h6>Page Setup</h6>
                <Form.Select
                  size="sm"
                  className="mb-2"
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

                <Form.Group className="mb-2">
                  <Form.Label className="small mb-1">
                    Bleed edge (mm)
                  </Form.Label>
                  <Form.Control
                    size="sm"
                    type="number"
                    min={0}
                    max={BleedEdgeMM}
                    step={0.1}
                    value={settings.bleedEdgeMM}
                    onChange={(event) => {
                      const value = parseFloat(event.target.value);
                      if (!Number.isNaN(value)) {
                        setSettings((previous) => ({
                          ...previous,
                          bleedEdgeMM: value,
                        }));
                      }
                    }}
                    aria-label="Bleed edge (mm)"
                  />
                </Form.Group>

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
              </div>

              <div className="mb-3">
                <h6>View</h6>
                <Button
                  size="sm"
                  variant="outline-secondary"
                  onClick={() => dispatch(toggleFaces())}
                >
                  {frontsVisible ? "Showing: Fronts" : "Showing: Backs"}
                </Button>
              </div>

              <div className="mb-3">
                {/* No section heading here (unlike Page Setup/View above) - the button's own
                    label already reads "Cardback", and a separate identical-text heading would
                    make any future generic getByText("Cardback") locator ambiguous, exactly the
                    ambiguity the Search Settings section right below used to hit (see this file's
                    own history/PR notes). Issue #240 (design doc §5's CommonCardback row) - a
                    project-wide setting (true of the whole deck, not one selected slot),
                    relocated here unmodified - opens the same GridSelectorModal instance
                    CommonCardback.tsx's editor mount already owns (see that component's own
                    CardbackToolbarButton comment). */}
                <CardbackToolbarButton />
              </div>

              <div>
                {/* Issue #239 (design doc §5's SearchSettings row) - the same self-contained
                    trigger-button-plus-modal ProjectEditor.tsx already mounts, relocated here
                    unmodified: same Modal, same searchSettingsSlice read/write, same
                    setLocalStorageSearchSettings persistence path. No section heading (see the
                    Cardback div above) - the button's own label already reads "Search Settings",
                    and test-utils.ts's shared openSearchSettingsModal helper uses a plain
                    getByText(/Search Settings/) that a duplicate heading would make ambiguous. */}
                <SearchSettings />
              </div>
            </div>

            {/* Design doc §4.2's "Prepare Print footer - pinned, always visible at the rail's
                bottom (flex column: body scrolls, footer doesn't)". */}
            <div className="border-top p-3 d-grid gap-2">
              {exportProgressBar}
              {/* Issue #241 (design doc §5's export-beyond-PDF row) - XML/Card Images/Decklist,
                  relocated unmodified from the classic editor's own "Download" dropdown. */}
              <DisplayExportMenu />
              {isGoogleDriveAppConfigured() && (
                <Button
                  size="sm"
                  variant="outline-primary"
                  onClick={onSaveToDriveClick}
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
                onClick={onGeneratePdfClick}
                disabled={isDownloading || isSavingToDrive}
                data-testid="display-generate-pdf"
              >
                {isDownloading ? <Spinner size={1.2} /> : "Generate PDF"}
              </Button>
            </div>
          </Offcanvas.Body>
        </RightRailOffcanvas>
      </DisplayBodyRegion>

      {/* Design doc §4.1's tablet-only discoverability affordance - see TabletRailHandle's own
          comment for why this doesn't exist on phone/laptop/desktop. */}
      <TabletRailHandle
        variant="primary"
        size="sm"
        onClick={openLeftRail}
        data-testid="display-rail-handle"
        aria-label="Card details"
      >
        Card details
      </TabletRailHandle>

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
