/**
 * State management for search results - what images are returned for what search queries.
 */

import { createSelector } from "@reduxjs/toolkit";

import { Back, SearchResultsEndpointPageSize } from "@/common/constants";
import { computeSearchQueryHashKey } from "@/common/processing";
import {
  CardType,
  createAppAsyncThunk,
  createAppSlice,
  Faces,
  SearchQuery,
  SearchResults,
  SearchResultsState,
  SearchSettings,
} from "@/common/types";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { APIEditorSearch, EditorSearchResult } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectCardbacks } from "@/store/slices/cardbackSlice";
import { selectQueriesWithoutSearchResults } from "@/store/slices/projectSlice";
import { selectSearchSettings } from "@/store/slices/searchSettingsSlice";
import { setNotification } from "@/store/slices/toastsSlice";
import { AppDispatch, RootState } from "@/store/store";

//# region async thunk

const typePrefix = "searchResults/fetchCards";

export const mergeSearchResults = (
  a: SearchResults,
  b: SearchResults
): SearchResults => {
  const mergedResults: SearchResults = structuredClone(a);
  for (const [hashKey, searchResults] of Object.entries(b)) {
    if (Object.prototype.hasOwnProperty.call(mergedResults, hashKey)) {
      // initialize the array if it doesn't exist
      mergedResults[hashKey] ??= [];
      // merge the arrays
      const existingIds = new Set(mergedResults[hashKey]);
      mergedResults[hashKey] = [
        ...mergedResults[hashKey],
        ...searchResults.filter((id) => !existingIds.has(id)),
      ];
    } else {
      mergedResults[hashKey] = structuredClone(searchResults);
    }
  }
  return mergedResults;
};

export interface SearchResultsAndDegraded {
  results: SearchResults;
  degradedQueryHashKeys: Array<string>;
}

export const doSearch = async (
  state: RootState,
  queriesToSearch: Array<SearchQuery>,
  searchSettings: SearchSettings,
  clientSearchService: ClientSearchService
): Promise<SearchResultsAndDegraded> => {
  const backendURL = selectRemoteBackendURL(state);
  const localResultsPromise: Promise<SearchResults> =
    clientSearchService.editorSearch(searchSettings, queriesToSearch);
  // Client-side (local-folder) search never reports degradedQueries - only the remote backend
  // can retry a printing-specific filter unfiltered, so that signal is remote-only by
  // construction, not a gap in the local search implementation.
  const remoteResultsPromise: Promise<EditorSearchResult> =
    queriesToSearch.length > 0 && backendURL != null
      ? Array.from(
          Array(
            Math.ceil(queriesToSearch.length / SearchResultsEndpointPageSize)
          ).keys()
        ).reduce(function (
          promiseChain: Promise<EditorSearchResult>,
          page: number
        ) {
          return promiseChain.then(async function (
            previousValue: EditorSearchResult
          ) {
            const { results, degradedQueries } = await APIEditorSearch(
              backendURL,
              searchSettings,
              queriesToSearch.slice(
                page * SearchResultsEndpointPageSize,
                (page + 1) * SearchResultsEndpointPageSize
              )
            );
            return {
              results: { ...previousValue.results, ...results },
              degradedQueries: [
                ...previousValue.degradedQueries,
                ...degradedQueries,
              ],
            };
          });
        },
        Promise.resolve({ results: {}, degradedQueries: [] }))
      : new Promise(async (resolve) =>
          resolve({ results: {}, degradedQueries: [] })
        );
  return await Promise.all([localResultsPromise, remoteResultsPromise]).then(
    ([localResults, remote]) => ({
      results: mergeSearchResults(localResults, remote.results),
      degradedQueryHashKeys: remote.degradedQueries,
    })
  );
};

export const fetchSearchResults = createAppAsyncThunk(
  typePrefix,
  /**
   * concurrently resolve local and remote searches
   */
  async (arg, { getState, extra }) => {
    const state = getState();
    const { clientSearchService } = extra as {
      clientSearchService: ClientSearchService;
    };

    const searchSettings = selectSearchSettings(state);
    const queriesToSearch = selectQueriesWithoutSearchResults(state); // TODO: is there an edge case here when a local directory is added?
    return doSearch(
      state,
      queriesToSearch,
      searchSettings,
      clientSearchService
    );
  }
);

export async function fetchSearchResultsAndReportError(dispatch: AppDispatch) {
  try {
    await dispatch(fetchSearchResults()).unwrap();
  } catch (error: any) {
    console.log(error);
    dispatch(
      setNotification([
        typePrefix,
        { name: error.name, message: error.message, level: "error" },
      ])
    );
    return null;
  }
}

//# endregion

//# region slice configuration

const initialState: SearchResultsState = {
  searchResults: {},
  degradedQueryHashKeys: [],
  status: "idle",
  error: null,
};

export const searchResultsSlice = createAppSlice({
  name: "searchResults",
  initialState,
  reducers: {
    addSearchResults: (state, action) => {
      state.searchResults = { ...state.searchResults, ...action.payload };
    },
    clearSearchResults: (state) => {
      state.searchResults = {};
      state.degradedQueryHashKeys = [];
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchSearchResults.pending, (state, action) => {
        state.status = "loading";
      })
      .addCase(fetchSearchResults.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.searchResults = {
          ...state.searchResults,
          ...action.payload.results,
        };
        state.degradedQueryHashKeys = Array.from(
          new Set([
            ...state.degradedQueryHashKeys,
            ...action.payload.degradedQueryHashKeys,
          ])
        );
      })
      .addCase(fetchSearchResults.rejected, (state, action) => {
        state.status = "failed";
        state.error = {
          name: action.error.name ?? null,
          message: action.error.message ?? null,
          level: "error",
        };
      });
  },
});

export const { addSearchResults, clearSearchResults } =
  searchResultsSlice.actions;

export default searchResultsSlice.reducer;

//# endregion

//# region selectors

const defaultEmptySearchResults: Array<string> = [];

/**
 * Handle the fallback logic where cardbacks with no query use the common cardback's list of cards.
 */
export const selectSearchResultsForQueryOrDefault = createSelector(
  // TODO: this pattern is awful
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => state.searchResults.searchResults,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => query,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => cardType,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => expansionCode,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => collectorNumber,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => face,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined,
    face: Faces
  ) => selectCardbacks(state),
  (
    searchResults,
    query,
    cardType,
    expansionCode,
    collectorNumber,
    face,
    cardbacks
  ) =>
    query != null && query.length > 0 && cardType !== undefined
      ? searchResults[
          computeSearchQueryHashKey({
            query,
            cardType,
            expansionCode,
            collectorNumber,
          })
        ]
      : face === Back
      ? cardbacks
      : defaultEmptySearchResults
);

const selectDegradedQueryHashKeysSet = createSelector(
  (state: RootState) => state.searchResults.degradedQueryHashKeys,
  (hashKeys) => new Set(hashKeys)
);

/**
 * Whether this specific printing-filtered query (expansionCode/collectorNumber) found nothing
 * and the backend retried it unfiltered - mirrors EditorSearchResponse.degradedQueries. Queries
 * with no printing filter at all are never degraded (there's no filter to have been dropped).
 */
export const selectIsSearchQueryDegraded = createSelector(
  selectDegradedQueryHashKeysSet,
  (
    state: RootState,
    query: string | null | undefined,
    cardType: CardType | undefined,
    expansionCode: string | undefined,
    collectorNumber: string | undefined
  ) =>
    query != null &&
    query.length > 0 &&
    cardType !== undefined &&
    expansionCode != null
      ? computeSearchQueryHashKey({
          query,
          cardType,
          expansionCode,
          collectorNumber,
        })
      : undefined,
  (degradedQueryHashKeysSet, hashKey) =>
    hashKey != null && degradedQueryHashKeysSet.has(hashKey)
);

//# endregion
