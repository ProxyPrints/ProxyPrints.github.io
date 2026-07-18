import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType, Project, ThunkStatus } from "@/common/types";
import {
  projectSlice,
  selectManualOverride,
  selectManualOverrides,
  selectQueriesWithoutSearchResults,
  setAllManualOverrides,
  setManualOverride,
} from "@/store/slices/projectSlice";
import { setupStore } from "@/store/store";

const baseProjectState: Project = {
  members: [],
  nextMemberId: 0,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

describe("selectQueriesWithoutSearchResults tests", () => {
  test("empty", () => {
    const state = {
      project: {
        members: [],
        nextMemberId: 0,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([]);
  });

  test("one query", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
        ],
        nextMemberId: 1,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {},
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([{ query: "query 1", cardType: "CARD" }]);
  });

  test("two queries", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
          {
            id: "t-1",
            front: {
              query: {
                query: "query 2",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
        ],
        nextMemberId: 2,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {},
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([
      { query: "query 1", cardType: "CARD" },
      { query: "query 2", cardType: "CARD" },
    ]);
  });

  test("three queries", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
          {
            id: "t-1",
            front: {
              query: {
                query: "query 2",
                cardType: "TOKEN" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: {
              query: {
                query: "query 3",
                cardType: "CARDBACK" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
          },
        ],
        nextMemberId: 2,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {},
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([
      { query: "query 1", cardType: "CARD" },
      { query: "query 2", cardType: "TOKEN" },
      { query: "query 3", cardType: "CARDBACK" },
    ]);
  });

  test("two queries but one has search results", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
          {
            id: "t-1",
            front: {
              query: {
                query: "query 2",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
        ],
        nextMemberId: 2,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {
          [computeSearchQueryHashKey({
            query: "query 1",
            cardType: "CARD" as CardType,
          })]: [],
        },
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([{ query: "query 2", cardType: "CARD" }]);
  });

  test("duplicated query", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
          {
            id: "t-1",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
        ],
        nextMemberId: 2,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {},
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([{ query: "query 1", cardType: "CARD" }]);
  });

  test("duplicated query but across multiple types", () => {
    const state = {
      project: {
        members: [
          {
            id: "t-0",
            front: {
              query: {
                query: "query 1",
                cardType: "CARD" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
          {
            id: "t-1",
            front: {
              query: {
                query: "query 1",
                cardType: "TOKEN" as CardType,
              },
              selectedImage: undefined,
              selected: false,
            },
            back: null,
          },
        ],
        nextMemberId: 2,
        cardback: null,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      searchResults: {
        searchResults: {},
        status: "idle" as ThunkStatus,
        error: null,
      },
    };
    expect(
      selectQueriesWithoutSearchResults(setupStore(state).getState())
    ).toStrictEqual([
      { query: "query 1", cardType: "CARD" },
      { query: "query 1", cardType: "TOKEN" },
    ]);
  });
});

describe("manual bleed override reducers and selectors (Proposal B PR-2)", () => {
  test("setManualOverride records a non-auto override", () => {
    const state = projectSlice.reducer(
      baseProjectState,
      setManualOverride({ identifier: "card-1", override: "force-bleed" })
    );
    expect(state.manualOverrides).toStrictEqual({ "card-1": "force-bleed" });
  });

  test("setManualOverride back to 'auto' deletes the entry rather than storing it", () => {
    const withOverride = projectSlice.reducer(
      baseProjectState,
      setManualOverride({ identifier: "card-1", override: "force-trimmed" })
    );
    const backToAuto = projectSlice.reducer(
      withOverride,
      setManualOverride({ identifier: "card-1", override: "auto" })
    );
    expect(backToAuto.manualOverrides).toStrictEqual({});
  });

  test("setManualOverride only touches the given identifier", () => {
    const first = projectSlice.reducer(
      baseProjectState,
      setManualOverride({ identifier: "card-1", override: "force-bleed" })
    );
    const second = projectSlice.reducer(
      first,
      setManualOverride({ identifier: "card-2", override: "force-trimmed" })
    );
    expect(second.manualOverrides).toStrictEqual({
      "card-1": "force-bleed",
      "card-2": "force-trimmed",
    });
  });

  test("setAllManualOverrides replaces the whole map (e.g. loading from localStorage)", () => {
    const seeded = projectSlice.reducer(
      baseProjectState,
      setManualOverride({ identifier: "stale", override: "force-bleed" })
    );
    const loaded = projectSlice.reducer(
      seeded,
      setAllManualOverrides({ "card-1": "force-trimmed" })
    );
    expect(loaded.manualOverrides).toStrictEqual({
      "card-1": "force-trimmed",
    });
  });

  test("selectManualOverrides returns the whole map", () => {
    const state = {
      project: {
        ...baseProjectState,
        manualOverrides: { "card-1": "force-bleed" as const },
      },
    };
    expect(selectManualOverrides(setupStore(state).getState())).toStrictEqual({
      "card-1": "force-bleed",
    });
  });

  test("selectManualOverride defaults a missing entry to 'auto'", () => {
    const state = { project: baseProjectState };
    expect(
      selectManualOverride(setupStore(state).getState(), "unset-card")
    ).toBe("auto");
  });

  test("selectManualOverride returns a stored override", () => {
    const state = {
      project: {
        ...baseProjectState,
        manualOverrides: { "card-1": "force-trimmed" as const },
      },
    };
    expect(selectManualOverride(setupStore(state).getState(), "card-1")).toBe(
      "force-trimmed"
    );
  });
});
