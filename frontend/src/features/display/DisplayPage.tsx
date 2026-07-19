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
 */
import styled from "@emotion/styled";
import Link from "next/link";
import React, { useEffect, useMemo, useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";

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
import { RenderIfVisible } from "@/components/RenderIfVisible";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { paginateSlotsForDisplay } from "@/features/display/displayPagination";
import { GridSelectorResults } from "@/features/gridSelector/GridSelectorResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { computeLayout } from "@/features/pdf/layout";
import {
  PagePreview,
  PagePreviewSlotContent,
} from "@/features/pdf/PagePreview";
import { getPageSizeMM, PageSize } from "@/features/pdf/PDF";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  selectIsProjectEmpty,
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

// Width, in real CSS px, every sheet in the flat-scroll stack renders at - was PagePreview's own
// inline maxWidthPx={960} prop before Item 3; hoisted to a shared constant since sheetPixelHeightPx
// below needs the exact same value to estimate each sheet's rendered height for virtualization.
const SHEET_MAX_WIDTH_PX = 960;

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
  // Matches PagePreview's own internal scale-to-fit math exactly (scale = maxWidthPx /
  // pageWidthMM-in-px, height = pageHeightMM-in-px * scale - the px-per-mm factor cancels out),
  // so this estimate is exact, not approximate - RenderIfVisible's defaultHeight/visibleOffset
  // never has to correct a wrong guess via its own ResizeObserver fallback.
  const sheetPixelHeightPx =
    SHEET_MAX_WIDTH_PX * (sheetHeightMM / sheetWidthMM);

  const margins = useMemo(() => ({ top: 5, bottom: 5, left: 5, right: 5 }), []);
  const spacing = useMemo(() => ({ row: 0, col: 0 }), []);

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
          {/* Passive scroll-position readout, not a control - see the visibleSheetIndex
              IntersectionObserver above. The whole deck is one continuous vertical stack now
              (Item 3, flat scroll amendment); there's nothing left here to page between. */}
          <span data-testid="display-sheet-indicator">
            Sheet {clampedVisibleSheetIndex + 1} of {sheets.length}
          </span>
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

        <div className="ms-auto">
          {/* Full inline export (Generate PDF/Save to Drive wired directly off this page's own
              state) is Step 3 (switchover) in the design doc's §6 - not built here. For now
              this is a real, working link to the classic editor's Print tab, not a dead
              placeholder. */}
          <Link href="/editor" className="btn btn-primary btn-sm">
            Generate PDF (opens classic Print tab)
          </Link>
        </div>
      </div>

      {/* position: relative + an explicit non-auto z-index together, on the sticky rail's own
          PARENT - the specific fix docs/lessons.md's sticky/z-index entry documents (part 3):
          without both together, the rail's necessary stacking context can escape to an
          ancestor and make its own subtree un-hit-testable, even though it still paints fine. */}
      <div
        className="d-flex flex-column flex-md-row flex-grow-1"
        style={{ position: "relative", zIndex: 0 }}
      >
        <div
          className="flex-grow-1 d-flex flex-column align-items-center p-3"
          data-testid="display-sheet-region"
        >
          {sheets.map((sheet) => (
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
                  maxWidthPx={SHEET_MAX_WIDTH_PX}
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
          ))}
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
    </div>
  );
}
