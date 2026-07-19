import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType } from "@/common/schema_types";
import { ThunkStatus } from "@/common/types";
import {
  clearSearchResults,
  fetchSearchResults,
  mergeSearchResults,
  searchResultsSlice,
  selectIsSearchQueryDegraded,
} from "@/store/slices/searchResultsSlice";
import { setupStore } from "@/store/store";

describe("mergeSearchResults", () => {
  test("deduplicates identifiers present in both local and remote results", () => {
    const local = { key1: ["id-1", "id-2"] };
    const remote = { key1: ["id-2", "id-3"] };
    expect(mergeSearchResults(local, remote)).toEqual({
      key1: ["id-1", "id-2", "id-3"],
    });
  });

  test("merges non-overlapping results without duplication", () => {
    const local = { key1: ["id-1"] };
    const remote = { key1: ["id-2"] };
    expect(mergeSearchResults(local, remote)).toEqual({
      key1: ["id-1", "id-2"],
    });
  });

  test("merges disjoint keys", () => {
    const local = { key1: ["id-1"] };
    const remote = { key2: ["id-2"] };
    expect(mergeSearchResults(local, remote)).toEqual({
      key1: ["id-1"],
      key2: ["id-2"],
    });
  });
});

// Proposal H, Step 2 PR 2b - degradedQueryHashKeys wiring (EditorSearchResponse.degradedQueries,
// consumed end to end for the first time by the requested-printing badge's degraded style).
describe("degradedQueryHashKeys", () => {
  const initialState = searchResultsSlice.getInitialState();

  test("fetchSearchResults.fulfilled merges new degraded hash keys without duplicating existing ones", () => {
    const afterFirst = searchResultsSlice.reducer(
      initialState,
      fetchSearchResults.fulfilled(
        { results: {}, degradedQueryHashKeys: ["hash-1"] },
        "requestId1",
        undefined
      )
    );
    expect(afterFirst.degradedQueryHashKeys).toEqual(["hash-1"]);

    const afterSecond = searchResultsSlice.reducer(
      afterFirst,
      fetchSearchResults.fulfilled(
        { results: {}, degradedQueryHashKeys: ["hash-1", "hash-2"] },
        "requestId2",
        undefined
      )
    );
    expect([...afterSecond.degradedQueryHashKeys].sort()).toEqual([
      "hash-1",
      "hash-2",
    ]);
  });

  test("clearSearchResults resets degradedQueryHashKeys alongside searchResults", () => {
    const populated = searchResultsSlice.reducer(
      initialState,
      fetchSearchResults.fulfilled(
        { results: { key: ["id"] }, degradedQueryHashKeys: ["hash-1"] },
        "requestId",
        undefined
      )
    );
    const cleared = searchResultsSlice.reducer(populated, clearSearchResults());
    expect(cleared.searchResults).toEqual({});
    expect(cleared.degradedQueryHashKeys).toEqual([]);
  });
});

describe("selectIsSearchQueryDegraded", () => {
  test("true only for the exact printing-filtered query the backend reported as degraded", () => {
    const hashKey = computeSearchQueryHashKey({
      query: "lightning bolt",
      cardType: CardType.Card,
      expansionCode: "2ED",
      collectorNumber: "162",
    });
    const state = setupStore({
      searchResults: {
        searchResults: {},
        degradedQueryHashKeys: [hashKey],
        status: "idle" as ThunkStatus,
        error: null,
      },
    }).getState();

    expect(
      selectIsSearchQueryDegraded(
        state,
        "lightning bolt",
        CardType.Card,
        "2ED",
        "162"
      )
    ).toBe(true);
    // Different collector number - a different query, not degraded.
    expect(
      selectIsSearchQueryDegraded(
        state,
        "lightning bolt",
        CardType.Card,
        "2ED",
        "999"
      )
    ).toBe(false);
    // No printing filter at all - never degraded, even for the same base query.
    expect(
      selectIsSearchQueryDegraded(
        state,
        "lightning bolt",
        CardType.Card,
        undefined,
        undefined
      )
    ).toBe(false);
  });
});
