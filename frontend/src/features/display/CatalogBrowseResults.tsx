/**
 * Issue #267 (design doc ADDENDUM D12/F10, owner-locked comment on #267: "Browse results render
 * in the center region via a new CatalogBrowseResults container - SelectVersionResults tile +
 * useGridSelectorSearch + GridSelectorFilters; CardGrid is layout template only - it renders deck
 * members, not catalog"). Mounted from DisplayPage.tsx's center region when the action bar's
 * Add/Browse toggle (see DisplayPage's own module comment) is in Browse mode.
 *
 * Component-reuse honesty (spec's own §A0 D12 note, restated here since this file is where the
 * choice actually gets made): `CardGrid.tsx` is NOT the catalog - it renders the PROJECT's own
 * members as slots (`MemoizedCardSlot`), so it is never mounted here; only its responsive
 * `Row xxl={4} lg={3} md={2} sm={1} xs={1}` grid TEMPLATE is copied, verbatim, as the visual
 * layout for this component's own tiles.
 *
 * DEVIATION from the spec's literal text (documented, not silent - same convention
 * SelectVersionResults.tsx's own module comment uses): the spec names "SelectVersionResults's
 * tile" as the reusable unit, but that component's actual tile (`SelectVersionTile`) is a private,
 * unexported function tightly coupled to a single project slot's printing-group/attribute-vote
 * chrome (canonical/suggested grouping keyed off one `requestedPrinting`, filter-chip state,
 * confirm-chip vote casting) - none of which has a well-defined meaning for an arbitrary catalog
 * query that may match many unrelated cards, not one slot's candidate versions. This component
 * instead reuses `MemoizedEditorCard` (`features/card/Card.tsx`) - the shared primitive
 * `SelectVersionTile` itself is built on top of - directly, with `AddCardToProjectForm` composed
 * underneath each one for the spec's own "+Add" affordance. This is a materially smaller surface
 * than full grouped-by-printing display, which is a deliberate v1 scope call (owner's locked
 * comment: "v1 is FILTERS-FIRST plus plain text") - flagged here and in the implementing PR.
 *
 * Search plumbing: a free-text query is run through the exact same machinery a slot's own query
 * uses (`doSearch`, searchResultsSlice.ts - local clientSearchService.editorSearch + remote
 * APIEditorSearch, merged) rather than a different "explore" endpoint (Explore.tsx exists but the
 * spec explicitly names the GridSelector family, not Explore's own ExploreFilters/DatedCard
 * pairing - see this task's own report for why Explore was rejected). The result is intentionally
 * NOT written into the global `searchResultsSlice` - that slice backs
 * `selectSearchResultsForQueryOrDefault`/degraded-query bookkeeping other UI (RequestedPrintingBadge)
 * reads, and an arbitrary browse query has no project slot to attribute a degraded-query verdict
 * to. Matching `CardDocument`s are fetched into the shared `cardDocumentsSlice` (the same
 * `addCardDocuments` action `fetchCardDocuments` itself dispatches), since that slice is a plain,
 * query-agnostic identifier->document cache shared by every surface that renders a `Card`.
 */
import React, { useEffect, useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";
import { useDebounce } from "use-debounce";

import { Card, ExploreDebounceMS } from "@/common/constants";
import { computeSearchQueryHashKey } from "@/common/processing";
import {
  SearchQuery,
  useAppDispatch,
  useAppSelector,
  useAppStore,
} from "@/common/types";
import { Spinner } from "@/components/Spinner";
import { AddCardToProjectForm } from "@/features/card/AddCardToProjectForm";
import { MemoizedEditorCard } from "@/features/card/Card";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { GridSelectorFilters } from "@/features/gridSelector/GridSelectorFilters";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { GenericErrorPage } from "@/features/ui/GenericErrorPage";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import {
  addCardDocuments,
  getCardDocumentRequestPromiseChain,
  selectCardDocumentByIdentifier,
} from "@/store/slices/cardDocumentsSlice";
import { doSearch } from "@/store/slices/searchResultsSlice";
import { selectSearchSettings } from "@/store/slices/searchSettingsSlice";

interface BrowseResultTileProps {
  identifier: string;
}

// The spec's own "+Add" affordance - AddCardToProjectForm's existing add path, the same one
// CardDetailedViewModal already mounts, composed directly under the tile rather than forked into
// it. Renders nothing (not even the tile) until this identifier's CardDocument has actually been
// fetched into cardDocumentsSlice (see this file's own module comment) - MemoizedEditorCard can
// render a bare "no card found" placeholder for an unresolved identifier, but AddCardToProjectForm
// requires a real CardDocument to build its addMembers line from.
function BrowseResultTile({ identifier }: BrowseResultTileProps) {
  const cardDocument = useAppSelector((state) =>
    selectCardDocumentByIdentifier(state, identifier)
  );

  return (
    <Col data-testid={`catalog-browse-tile-${identifier}`}>
      <div className="p-1">
        <MemoizedEditorCard
          imageIdentifier={identifier}
          cardHeaderTitle={cardDocument?.name ?? "Loading…"}
          noResultsFound={false}
          compressed={false}
        />
        {cardDocument != null && (
          <AddCardToProjectForm cardDocument={cardDocument} />
        )}
      </div>
    </Col>
  );
}

export interface CatalogBrowseResultsProps {
  /** The plain-text query typed into the shared search bar (design doc D12 - v1 is
   * filters-first plain text; no typed operator grammar - that's issue #276). */
  query: string;
}

export function CatalogBrowseResults({ query }: CatalogBrowseResultsProps) {
  const dispatch = useAppDispatch();
  const store = useAppStore();
  const { clientSearchService } = useClientSearchContext();
  const searchSettings = useAppSelector(selectSearchSettings);
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [debouncedQuery] = useDebounce(query.trim(), ExploreDebounceMS);
  const [catalogIdentifiers, setCatalogIdentifiers] = useState<Array<string>>(
    []
  );
  const [isSearching, setIsSearching] = useState(false);
  const focusRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    if (debouncedQuery.length === 0) {
      setCatalogIdentifiers([]);
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    const searchQuery: SearchQuery = { query: debouncedQuery, cardType: Card };
    doSearch(
      store.getState(),
      [searchQuery],
      searchSettings,
      clientSearchService
    )
      .then(async ({ results }) => {
        if (cancelled) {
          return;
        }
        const identifiers =
          results[computeSearchQueryHashKey(searchQuery)] ?? [];
        setCatalogIdentifiers(identifiers);
        const [remoteDocs, localDocs] = await Promise.all([
          getCardDocumentRequestPromiseChain(identifiers, backendURL),
          clientSearchService.getCardDocuments(identifiers),
        ]);
        if (!cancelled) {
          dispatch(addCardDocuments({ ...remoteDocs, ...localDocs }));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsSearching(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery]);

  const search = useGridSelectorSearch({
    imageIdentifiers: catalogIdentifiers,
    active: true,
  });

  const noResults =
    debouncedQuery.length > 0 &&
    !isSearching &&
    !search.displaySpinner &&
    search.sortedFilteredIdentifiers.length === 0;

  return (
    <div className="w-100" data-testid="catalog-browse-results">
      <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
        {debouncedQuery.length === 0 ? (
          <span className="text-muted small">
            Type a card name above to browse the catalog.
          </span>
        ) : (
          <span className="text-muted small">
            {search.resultCount.toLocaleString()} result
            {search.resultCount !== 1 ? "s" : ""} for &ldquo;{debouncedQuery}
            &rdquo;
          </span>
        )}
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
      <Row className="g-0">
        {search.settingsVisible && (
          <Col lg={3} sm={4} xs={6} className="border-end p-0">
            <GridSelectorFilters
              imageIdentifiers={catalogIdentifiers}
              focusRef={focusRef}
              // "Jump to Version" has no meaningful destination in browse mode (there is no
              // single slot's candidate list to jump within) - a no-op keeps the filters panel's
              // existing composition unforked rather than special-casing this one sub-section.
              selectImage={() => undefined}
              sortBy={search.sortBy}
              setSortBy={search.setSortBy}
              printings={search.printings}
              setPrintings={search.setPrintings}
              artists={search.artists}
              setArtists={search.setArtists}
              filterSettings={search.filterSettings}
              setFilterSettings={search.setFilterSettings}
              sourceSettings={search.sourceSettings}
              setSourceSettings={search.setSourceSettings}
              projectFilter={search.projectFilter}
            />
          </Col>
        )}
        <Col
          lg={search.settingsVisible ? 9 : 12}
          sm={search.settingsVisible ? 8 : 12}
          xs={search.settingsVisible ? 6 : 12}
          className="p-0"
        >
          {(isSearching || search.displaySpinner) && (
            <div className="text-center py-3">
              <Spinner size={2} />
            </div>
          )}
          {noResults && (
            <GenericErrorPage
              title="No results :("
              text={["Your search didn't match any results."]}
            />
          )}
          {/* CardGrid.tsx's own responsive template (§context, this file's own module comment) -
              copied verbatim as a layout only, CardGrid itself is never mounted here. */}
          <Row xxl={4} lg={3} md={2} sm={1} xs={1} className="g-0">
            {search.sortedFilteredIdentifiers.map((identifier) => (
              <BrowseResultTile key={identifier} identifier={identifier} />
            ))}
          </Row>
        </Col>
      </Row>
    </div>
  );
}
