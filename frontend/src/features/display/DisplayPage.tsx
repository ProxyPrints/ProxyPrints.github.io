/**
 * Proposal H, Step 1 (docs/proposals/proposal-h-unified-display-page.md) — the unified display
 * page's shell: a top toolbar, a live print-sheet preview (reusing PagePreview/computeLayout
 * from Proposal A - see PagePreview.tsx), slot selection, and the rail's always-visible status
 * header + accordion skeleton (AutofillCollapse, per the owner's accordion amendment). Real
 * components are wired where the data/logic already exists; every other accordion section
 * renders a labeled stub - see each section's own comment for which later PR fills it in, per
 * the design doc's §6 migration/sequencing plan.
 *
 * Deliberately NOT built here (see the design doc + this task's relay report for the full
 * reasoning): the tablet off-canvas drawer and mobile bottom-sheet overlay interaction patterns
 * (§3) - below `md` the rail stacks in plain document flow below the sheet, which is usable but
 * not yet the polished drawer/overlay the doc specifies; that's follow-up work, not silently
 * dropped. Front-only pagination (see displayPagination.ts's own module comment) - a Fronts/
 * Backs toggle reuses the existing frontsVisible view setting rather than PDFGenerator's
 * export-time front-then-distinct-back interleaving.
 */
import styled from "@emotion/styled";
import Link from "next/link";
import React, { useMemo, useState } from "react";
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
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import { AutofillCollapse } from "@/components/AutofillCollapse";
import { paginateSlotsForDisplay } from "@/features/display/displayPagination";
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
} from "@/store/slices/projectSlice";
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
}

const RailHeader = ({
  face,
  slot,
  cardName,
  printingBadge,
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
        className="badge bg-secondary mt-1"
        style={{ fontFamily: "monospace" }}
        data-testid="display-printing-badge"
      >
        {printingBadge}
      </span>
    )}
    {/* Confirm? affordance (DeckbuilderConfirmAffordance) wires in here for real in Step 2's
        second instrument PR, alongside the printing badge's full degraded-state treatment
        (degradedQueries) - see the design doc's §6. */}
  </div>
);

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

  const query = projectMember?.query;
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

  return (
    <div data-testid="display-rail-content">
      <RailHeader
        face={selectedSlotRef.face}
        slot={selectedSlotRef.slot}
        cardName={cardName}
        printingBadge={printingBadge}
      />
      <RailSection
        sectionKey="chooseImage"
        title="Choose Image"
        expandedSections={expandedSections}
        onToggle={onToggle}
      >
        <Stub>
          The candidate/version picker (GridSelectorModal) lands here in Step
          2&apos;s first instrument-parity PR.
        </Stub>
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
    </div>
  );
}
