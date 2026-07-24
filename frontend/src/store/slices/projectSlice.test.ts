import { Back, Front } from "@/common/constants";
import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType, Project, ThunkStatus } from "@/common/types";
import {
  applyCardbackToAllSlots,
  projectSlice,
  selectIsCardbackExplicitlySet,
  selectIsRidingUntouchedDefaultCardback,
  selectManualOverride,
  selectManualOverrides,
  selectQueriesWithoutSearchResults,
  setAllManualOverrides,
  setManualOverride,
  setSelectedCardback,
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
        degradedQueryHashKeys: [],
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
        degradedQueryHashKeys: [],
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
        degradedQueryHashKeys: [],
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
        degradedQueryHashKeys: [],
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
        degradedQueryHashKeys: [],
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
        degradedQueryHashKeys: [],
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

// Cardback flow round (SPEC-cardback-pdfwait.md §C.1/§C.2) - `cardbackExplicitlySet`,
// `setSelectedCardback`'s new `explicit` flag, `applyCardbackToAllSlots`, and the reminder gate's
// own fire-condition selector.
describe("cardback flow round - explicit-choice tracking + apply-all", () => {
  test("a fresh project has never explicitly chosen a cardback", () => {
    const state = { project: baseProjectState };
    expect(selectIsCardbackExplicitlySet(setupStore(state).getState())).toBe(
      false
    );
    expect(
      selectIsRidingUntouchedDefaultCardback(setupStore(state).getState())
    ).toBe(true);
  });

  test("setSelectedCardback WITHOUT explicit:true (the listenerMiddleware auto-seed path) does not flip cardbackExplicitlySet", () => {
    const seeded = projectSlice.reducer(
      baseProjectState,
      setSelectedCardback({ selectedImage: "auto-seeded-cardback" })
    );
    expect(seeded.cardback).toBe("auto-seeded-cardback");
    // Never explicitly written to `true` - `undefined` reads as `false` everywhere this is
    // consulted (see the `Project` type's own field comment), so this asserts via the real
    // selector rather than the raw (possibly-still-`undefined`) field value.
    expect(
      selectIsCardbackExplicitlySet(setupStore({ project: seeded }).getState())
    ).toBe(false);
  });

  test("setSelectedCardback WITH explicit:true (a real user pick) flips cardbackExplicitlySet permanently", () => {
    const picked = projectSlice.reducer(
      baseProjectState,
      setSelectedCardback({
        selectedImage: "user-picked-cardback",
        explicit: true,
      })
    );
    expect(picked.cardbackExplicitlySet).toBe(true);

    // Never resets back to false, even if the cardback is later cleared.
    const cleared = projectSlice.reducer(
      picked,
      setSelectedCardback({ selectedImage: null })
    );
    expect(cleared.cardback).toBeNull();
    expect(cleared.cardbackExplicitlySet).toBe(true);
  });

  test("selectIsRidingUntouchedDefaultCardback flips false once a cardback has been explicitly set", () => {
    const state = {
      project: { ...baseProjectState, cardbackExplicitlySet: true },
    };
    expect(
      selectIsRidingUntouchedDefaultCardback(setupStore(state).getState())
    ).toBe(false);
  });

  test("applyCardbackToAllSlots overrides EVERY slot's back face, including ones that already differ (custom backs)", () => {
    const seeded: Project = {
      ...baseProjectState,
      members: [
        {
          id: "t-0",
          front: null,
          back: {
            query: { query: null, cardType: "CARDBACK" as CardType },
            selectedImage: "old-default",
            selected: false,
          },
        },
        {
          id: "t-1",
          front: null,
          // A deliberately-custom back, different from the old project default.
          back: {
            query: { query: null, cardType: "CARDBACK" as CardType },
            selectedImage: "already-custom",
            selected: false,
          },
        },
        {
          // No back face at all yet.
          id: "t-2",
          front: null,
          back: null,
        },
      ],
    };
    const applied = projectSlice.reducer(
      seeded,
      applyCardbackToAllSlots({ selectedImage: "new-cardback" })
    );
    expect(
      applied.members.map((member) => member[Back]?.selectedImage)
    ).toStrictEqual(["new-cardback", "new-cardback", "new-cardback"]);
    // Front faces are untouched.
    expect(applied.members.every((member) => member[Front] == null)).toBe(true);
  });
});
