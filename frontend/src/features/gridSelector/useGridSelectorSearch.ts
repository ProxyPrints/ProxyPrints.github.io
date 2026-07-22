/**
 * The version-picker's filtering/search state machine, extracted out of GridSelectorModal.tsx
 * (Proposal H, PR 2a - docs/proposals/proposal-h-unified-display-page.md) so the unified
 * display page's rail can mount the same real search behavior without the Modal chrome around
 * it. GridSelectorModal itself now calls this hook too - its own outward behavior (verified by
 * its existing Playwright suite) is unchanged; only where the state/effects live moved.
 *
 * `active` replaces the original inline `show` gate: GridSelectorModal passes its own `show`
 * (effects only run while the modal is open, exactly as before); the rail passes a constant
 * `true`, since its own containing `Rail` component already fully unmounts/remounts per slot
 * selection (see DisplayPage.tsx), which re-initializes this hook's state the same way opening
 * the modal used to.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDebounce } from "use-debounce";

import { ExploreDebounceMS, Printing } from "@/common/constants";
import { SortBy } from "@/common/schema_types";
import {
  CardDocument,
  FilterSettings,
  SourceSettings,
  useAppSelector,
} from "@/common/types";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { selectCardDocumentsByIdentifiers } from "@/store/slices/cardDocumentsSlice";
import { selectFavoriteIdentifiersSet } from "@/store/slices/favoritesSlice";
import {
  getDefaultSearchSettings,
  selectSearchSettings,
} from "@/store/slices/searchSettingsSlice";
import { selectSourceDocuments } from "@/store/slices/sourceDocumentsSlice";

// Below Bootstrap's `sm` breakpoint, the filters column and results column split 6/6 -
// defaulting filters closed under that width leaves the results column full-width on a phone
// instead of squeezed into half the screen. Purely an initial default - still user-toggleable
// via the Filters button either way.
export const SmallViewportFiltersBreakpointPx = 576;

export interface UseGridSelectorSearchArgs {
  imageIdentifiers: Array<string>;
  active: boolean;
  /** When false, ignore project-level search settings and use unconstrained defaults instead. */
  applySearchSettings?: boolean;
  /** Editor-completion package, E3/X2 (Bkg 5) - additive, optional override for the initial
   * `settingsVisible` value. `undefined` (every existing caller - GridSelectorModal) preserves
   * today's width-based default below; the /display rail passes `false` so the Filters
   * disclosure starts collapsed there regardless of viewport width, instead of auto-opening
   * cramped inside the 380px rail. */
  initialSettingsVisible?: boolean;
}

export function useGridSelectorSearch({
  imageIdentifiers,
  active,
  applySearchSettings = true,
  initialSettingsVisible,
}: UseGridSelectorSearchArgs) {
  //# region queries and hooks

  const { clientSearchService } = useClientSearchContext();

  const favoriteIdentifiersSet = useAppSelector(selectFavoriteIdentifiersSet);
  const globalSearchSettings = useAppSelector(selectSearchSettings);
  const cardDocumentsByIdentifier = useAppSelector((state) =>
    selectCardDocumentsByIdentifiers(state, imageIdentifiers)
  );
  const sourceDocuments = useAppSelector(selectSourceDocuments);

  //# endregion

  //# region state

  const [settingsVisible, setSettingsVisible] = useState<boolean>(
    () =>
      initialSettingsVisible ??
      (typeof window === "undefined" ||
        window.innerWidth >= SmallViewportFiltersBreakpointPx)
  );

  const [filterSettings, setFilterSettings] = useState<FilterSettings>(
    globalSearchSettings.filterSettings
  );
  const [sourceSettings, setSourceSettings] = useState<SourceSettings>(
    globalSearchSettings.sourceSettings
  );
  const [sortBy, setSortBy] = useState<SortBy | undefined>(undefined);
  const [filteredIdentifiers, setFilteredIdentifiers] =
    useState<Array<string>>(imageIdentifiers);
  const [isFiltering, setIsFiltering] = useState<boolean>(false);
  const [artists, setArtists] = useState<Array<string>>([]);
  const [printings, setPrintings] = useState<Array<Printing>>([]);

  //# endregion

  //# region debouncing

  function equalityFn<T>(left: T, right: T): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
  }

  const [debouncedFilter, debouncedFilterState] = useDebounce(
    { filterSettings, sourceSettings, sortBy, artists, printings },
    ExploreDebounceMS,
    { equalityFn }
  );

  //# endregion

  //# region effects

  // Re-initialise local settings from global search settings each time this becomes active
  const globalSearchSettingsRef = useRef(globalSearchSettings);
  globalSearchSettingsRef.current = globalSearchSettings;
  const sourceDocumentsRef = useRef(sourceDocuments);
  sourceDocumentsRef.current = sourceDocuments;
  useEffect(() => {
    if (active) {
      if (applySearchSettings) {
        const settings = globalSearchSettingsRef.current;
        setFilterSettings(settings.filterSettings);
        // Only expose sources that are enabled at the project level
        setSourceSettings({
          sources: settings.sourceSettings.sources.filter(
            ([, enabled]) => enabled
          ),
        });
      } else {
        const defaults = getDefaultSearchSettings(
          sourceDocumentsRef.current ?? {}
        );
        setFilterSettings(defaults.filterSettings);
        setSourceSettings(defaults.sourceSettings);
      }
      setSortBy(undefined);
      setArtists([]);
      setPrintings([]);
    }
    // intentionally only re-initialise on the active toggle, not on every global settings change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, applySearchSettings]);

  // Filter and sort identifiers via the worker whenever debounced settings or identifiers change
  useEffect(() => {
    if (!active) return;
    setIsFiltering(true);
    const cards = Object.values(cardDocumentsByIdentifier).filter(
      (card): card is CardDocument => card !== undefined
    );
    clientSearchService
      .filterGridSelectorIdentifiers(
        cards,
        {
          searchTypeSettings:
            globalSearchSettingsRef.current.searchTypeSettings,
          filterSettings: debouncedFilter.filterSettings,
          sourceSettings: debouncedFilter.sourceSettings,
        },
        debouncedFilter.sortBy,
        debouncedFilter.artists,
        debouncedFilter.printings
      )
      .then((ids) => {
        setFilteredIdentifiers(ids);
        setIsFiltering(false);
      })
      .catch(() => {
        setFilteredIdentifiers(imageIdentifiers);
        setIsFiltering(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, cardDocumentsByIdentifier, debouncedFilter]);

  //# endregion

  //# region computed constants

  const filteredIdentifiersSet = useMemo(
    () => new Set(filteredIdentifiers),
    [filteredIdentifiers]
  );

  // Filter favorites to only those present in the current filtered results
  const favoriteIdentifiersInFilteredResults = useMemo(
    () =>
      Array.from(favoriteIdentifiersSet).filter((id) =>
        filteredIdentifiersSet.has(id)
      ),
    [favoriteIdentifiersSet, filteredIdentifiersSet]
  );

  // Sort: favorites first, then Orama's sort order within each group
  const sortedFilteredIdentifiers = useMemo(() => {
    const favoriteSet = new Set(favoriteIdentifiersInFilteredResults);
    return [...filteredIdentifiers].sort((a, b) => {
      const aIsFavorite = favoriteSet.has(a);
      const bIsFavorite = favoriteSet.has(b);
      if (aIsFavorite && !bIsFavorite) return -1;
      if (!aIsFavorite && bIsFavorite) return 1;
      return 0;
    });
  }, [filteredIdentifiers, favoriteIdentifiersInFilteredResults]);

  // Map from identifier to original index (for consistent option numbering)
  const originalIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    imageIdentifiers.forEach((id, index) => map.set(id, index));
    return map;
  }, [imageIdentifiers]);

  const displaySpinner = debouncedFilterState.isPending() || isFiltering;

  // Constraints derived from the project-level search settings (only applied when applySearchSettings is true)
  const projectFilter = applySearchSettings
    ? globalSearchSettings.filterSettings
    : undefined;

  const noSearchResults =
    sortedFilteredIdentifiers.length === 0 && !displaySpinner;

  //# endregion

  return {
    settingsVisible,
    setSettingsVisible,
    filterSettings,
    setFilterSettings,
    sourceSettings,
    setSourceSettings,
    sortBy,
    setSortBy,
    artists,
    setArtists,
    printings,
    setPrintings,
    sortedFilteredIdentifiers,
    favoriteIdentifiersInFilteredResults,
    originalIndexMap,
    displaySpinner,
    noSearchResults,
    projectFilter,
    resultCount: filteredIdentifiers.length,
  };
}

export type GridSelectorSearch = ReturnType<typeof useGridSelectorSearch>;
