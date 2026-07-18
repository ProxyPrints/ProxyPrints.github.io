/**
 * The version-picker's filters-column + results-column body, extracted out of
 * GridSelectorModal.tsx (Proposal H, PR 2a) so it can render either inside the classic Modal
 * (unchanged behavior) or inline inside the unified display page's rail (no modal chrome).
 * Pass the `search` object `useGridSelectorSearch` returns; this component only renders it.
 *
 * `variant` controls layout: "modal" wraps each column in `OverflowCol` sized against the
 * viewport (`heightDelta`), exactly as GridSelectorModal always has. "embedded" uses a plain
 * `Col` instead - `OverflowCol`'s `100vh`-relative height/scroll would be a second, competing
 * scroll region nested inside the rail's own already-scrolling container (see DisplayPage.tsx's
 * RailWrapper), not a real modal's fixed viewport. Two literal JSX branches (not a dynamically-
 * chosen component variable) so each variant's own prop set - OverflowCol's heightDelta isn't a
 * valid Col prop - type-checks against the real component it renders.
 */
import { Ref } from "react";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { Blurrable } from "@/components/Blurrable";
import { OverflowCol } from "@/components/OverflowCol";
import { Spinner } from "@/components/Spinner";
import { CardResultSet } from "@/features/card/CardResultSet";
import { GridSelectorFilters } from "@/features/gridSelector/GridSelectorFilters";
import { GridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { GenericErrorPage } from "@/features/ui/GenericErrorPage";

const ModalHeightDelta = 200;

interface GridSelectorResultsProps {
  variant: "modal" | "embedded";
  imageIdentifiers: Array<string>;
  selectedImage?: string;
  onSelectImage: (identifier: string) => void;
  focusRef: Ref<HTMLInputElement>;
  search: GridSelectorSearch;
}

function FiltersColumn({
  variant,
  imageIdentifiers,
  focusRef,
  onSelectImage,
  search,
}: Pick<
  GridSelectorResultsProps,
  "variant" | "imageIdentifiers" | "focusRef" | "onSelectImage" | "search"
>) {
  const filters = (
    <GridSelectorFilters
      imageIdentifiers={imageIdentifiers}
      focusRef={focusRef}
      selectImage={onSelectImage}
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
  );
  return variant === "modal" ? (
    <OverflowCol
      lg={3}
      sm={4}
      xs={6}
      className="border-end p-0"
      heightDelta={ModalHeightDelta}
    >
      {filters}
    </OverflowCol>
  ) : (
    <Col lg={3} sm={4} xs={6} className="border-end p-0">
      {filters}
    </Col>
  );
}

function ResultsColumn({
  variant,
  span,
  selectedImage,
  onSelectImage,
  search,
}: {
  variant: "modal" | "embedded";
  span: { lg: number; sm: number; xs: number };
  selectedImage: string | undefined;
  onSelectImage: (identifier: string) => void;
  search: GridSelectorSearch;
}) {
  const content = (
    <>
      {search.displaySpinner && (
        <Spinner size={6} zIndex={3} positionAbsolute={true} />
      )}
      <Blurrable disabled={search.displaySpinner}>
        <CardResultSet
          imageIdentifiers={search.sortedFilteredIdentifiers}
          handleClick={onSelectImage}
          selectedImage={selectedImage}
          favoriteIdentifiers={search.favoriteIdentifiersInFilteredResults}
          originalIndexMap={search.originalIndexMap}
        />
      </Blurrable>
      {search.noSearchResults && (
        <GenericErrorPage
          title="No results :("
          text={["Your filters didn't match any results."]}
        />
      )}
    </>
  );
  return variant === "modal" ? (
    <OverflowCol {...span} className="p-0" heightDelta={ModalHeightDelta}>
      {content}
    </OverflowCol>
  ) : (
    <Col {...span} className="p-0">
      {content}
    </Col>
  );
}

export function GridSelectorResults({
  variant,
  imageIdentifiers,
  selectedImage,
  onSelectImage,
  focusRef,
  search,
}: GridSelectorResultsProps) {
  return (
    <Row className="g-0">
      {search.settingsVisible && (
        <FiltersColumn
          variant={variant}
          imageIdentifiers={imageIdentifiers}
          focusRef={focusRef}
          onSelectImage={onSelectImage}
          search={search}
        />
      )}
      <ResultsColumn
        variant={variant}
        span={{
          lg: search.settingsVisible ? 9 : 12,
          sm: search.settingsVisible ? 8 : 12,
          xs: search.settingsVisible ? 6 : 12,
        }}
        selectedImage={selectedImage}
        onSelectImage={onSelectImage}
        search={search}
      />
    </Row>
  );
}
