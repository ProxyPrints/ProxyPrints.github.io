import {
  AnonymousIdKey,
  ManualOverridesKey,
  MaximumDPI,
  MaximumSize,
  MinimumDPI,
  SearchSettingsKey,
} from "@/common/constants";
import {
  getLocalStorageManualOverrides,
  getLocalStorageSearchSettings,
  getOrCreateAnonymousId,
  setLocalStorageManualOverrides,
} from "@/common/cookies";
import { defaultSettings, sourceDocuments } from "@/common/test-constants";

beforeEach(() => {
  window.localStorage.removeItem(SearchSettingsKey);
  window.localStorage.removeItem(AnonymousIdKey);
  window.localStorage.removeItem(ManualOverridesKey);
});
afterEach(() => {
  window.localStorage.removeItem(SearchSettingsKey);
  window.localStorage.removeItem(AnonymousIdKey);
  window.localStorage.removeItem(ManualOverridesKey);
});

//# region tests

test("default settings are returned when cookies are empty", () => {
  window.localStorage.setItem(SearchSettingsKey, JSON.stringify({}));

  expect(getLocalStorageSearchSettings(sourceDocuments)).toStrictEqual(
    defaultSettings
  );
});

test("default settings are returned when cookie data doesn't match schema", () => {
  // some arbitrary garbage json data
  window.localStorage.setItem(
    SearchSettingsKey,
    JSON.stringify({ a: 1, b: 2, garbage: true })
  );

  expect(getLocalStorageSearchSettings(sourceDocuments)).toStrictEqual(
    defaultSettings
  );
});

test("cookies with complete source order are respected", () => {
  // setting up some arbitrary non-default settings here
  const settingsWithCompleteSourceOrder = {
    searchTypeSettings: { fuzzySearch: true, filterCardbacks: false },
    sourceSettings: {
      sources: [
        [1, true],
        [0, false],
        [3, true],
        [2, false],
      ],
    },
    filterSettings: {
      minimumDPI: 100,
      maximumDPI: 200,
      maximumSize: 15,
      languages: [],
      includesTags: [],
      excludesTags: ["NSFW"],
      fullArtOnly: false,
      borderlessOnly: false,
    },
  };
  window.localStorage.setItem(
    SearchSettingsKey,
    JSON.stringify(settingsWithCompleteSourceOrder)
  );

  expect(getLocalStorageSearchSettings(sourceDocuments)).toStrictEqual(
    settingsWithCompleteSourceOrder
  );
});

test("referenced sources that don't exist in database are filtered out", () => {
  const settingsWithCompleteSourceOrder = {
    searchTypeSettings: { fuzzySearch: false, filterCardbacks: false },
    sourceSettings: {
      sources: [
        [1, true],
        [0, true],
        [3, true],
        [2, true],
        [5, true],
        [6, true],
      ],
    },
    filterSettings: {
      minimumDPI: MinimumDPI,
      maximumDPI: MaximumDPI,
      maximumSize: MaximumSize,
      languages: [],
      includesTags: [],
      excludesTags: ["NSFW"],
      fullArtOnly: false,
      borderlessOnly: false,
    },
  };
  window.localStorage.setItem(
    SearchSettingsKey,
    JSON.stringify(settingsWithCompleteSourceOrder)
  );

  expect(
    getLocalStorageSearchSettings(sourceDocuments).sourceSettings.sources
  ).toStrictEqual([
    [1, true],
    [0, true],
    [3, true],
    [2, true],
  ]);
});

test("cookies with incomplete source order are correctly reconciled", () => {
  const settingsWithCompleteSourceOrder = {
    searchTypeSettings: { fuzzySearch: true, filterCardbacks: false },
    sourceSettings: {
      sources: [
        [1, true],
        [0, false],
      ],
    },
    filterSettings: {
      minimumDPI: MinimumDPI,
      maximumDPI: MaximumDPI,
      maximumSize: MaximumSize,
      languages: [],
      includesTags: [],
      excludesTags: ["NSFW"],
      fullArtOnly: false,
      borderlessOnly: false,
    },
  };
  window.localStorage.setItem(
    SearchSettingsKey,
    JSON.stringify(settingsWithCompleteSourceOrder)
  );

  // sources 2 and 3 should be added onto the end and active
  expect(
    getLocalStorageSearchSettings(sourceDocuments).sourceSettings.sources
  ).toStrictEqual([
    [1, true],
    [0, false],
    [2, true],
    [3, true],
  ]);
});

test("cookies with incomplete source order plus invalid sources are correctly reconciled", () => {
  const settingsWithCompleteSourceOrder = {
    searchTypeSettings: { fuzzySearch: true, filterCardbacks: false },
    sourceSettings: {
      sources: [
        [6, true],
        [1, true],
        [0, false],
        [5, false],
      ],
    },
    filterSettings: {
      minimumDPI: MinimumDPI,
      maximumDPI: MaximumDPI,
      maximumSize: MaximumSize,
      languages: [],
      includesTags: [],
      excludesTags: ["NSFW"],
      fullArtOnly: false,
      borderlessOnly: false,
    },
  };
  window.localStorage.setItem(
    SearchSettingsKey,
    JSON.stringify(settingsWithCompleteSourceOrder)
  );

  // sources 2 and 3 should be added onto the end and active
  expect(
    getLocalStorageSearchSettings(sourceDocuments).sourceSettings.sources
  ).toStrictEqual([
    [1, true],
    [0, false],
    [2, true],
    [3, true],
  ]);
});

test("getOrCreateAnonymousId generates and persists an id when none exists", () => {
  expect(window.localStorage.getItem(AnonymousIdKey)).toBeNull();

  const id = getOrCreateAnonymousId();

  expect(id).toEqual(expect.any(String));
  expect(id.length).toBeGreaterThan(0);
  expect(window.localStorage.getItem(AnonymousIdKey)).toEqual(id);
});

test("getOrCreateAnonymousId returns the same id on repeated calls", () => {
  const first = getOrCreateAnonymousId();
  const second = getOrCreateAnonymousId();

  expect(second).toEqual(first);
});

test("getOrCreateAnonymousId respects an id already in localStorage", () => {
  window.localStorage.setItem(AnonymousIdKey, "existing-anonymous-id");

  expect(getOrCreateAnonymousId()).toEqual("existing-anonymous-id");
});

//# endregion

//# region manual bleed overrides (Proposal B PR-2)

test("getLocalStorageManualOverrides returns an empty object when nothing is stored", () => {
  expect(getLocalStorageManualOverrides()).toStrictEqual({});
});

test("getLocalStorageManualOverrides returns an empty object for malformed JSON", () => {
  window.localStorage.setItem(ManualOverridesKey, "not valid json{");

  expect(getLocalStorageManualOverrides()).toStrictEqual({});
});

test("getLocalStorageManualOverrides returns an empty object for a value that isn't an object", () => {
  window.localStorage.setItem(ManualOverridesKey, JSON.stringify(["a", "b"]));

  expect(getLocalStorageManualOverrides()).toStrictEqual({});
});

test("getLocalStorageManualOverrides returns an empty object when a value isn't a recognised override", () => {
  window.localStorage.setItem(
    ManualOverridesKey,
    JSON.stringify({ "card-1": "not-a-real-override" })
  );

  expect(getLocalStorageManualOverrides()).toStrictEqual({});
});

test("getLocalStorageManualOverrides round-trips a valid stored map", () => {
  const overrides = { "card-1": "force-bleed", "card-2": "force-trimmed" };
  window.localStorage.setItem(ManualOverridesKey, JSON.stringify(overrides));

  expect(getLocalStorageManualOverrides()).toStrictEqual(overrides);
});

test("setLocalStorageManualOverrides persists the map for getLocalStorageManualOverrides to read back", () => {
  setLocalStorageManualOverrides({ "card-1": "force-bleed" });

  expect(getLocalStorageManualOverrides()).toStrictEqual({
    "card-1": "force-bleed",
  });
});

//# endregion
