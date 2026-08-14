import { CardType, SearchSettings } from "@/common/schema_types";
import { getDefaultSearchSettings } from "@/store/slices/searchSettingsSlice";

// avoids pulling in GoogleDriveIndexer/LocalFilesIndexer's own dependency chain (unrelated to
// editorSearch) for a test that only exercises the class's precise-search override - a factory
// is required (not bare `jest.mock`) so Jest never loads the real module to auto-mock it
jest.mock("./indexer", () => ({
  Folder: jest.fn(),
  GoogleDriveIndexer: jest.fn(),
  LocalFilesIndexer: jest.fn(),
}));

import { ClientSearchService } from "./clientSearchService.worker";

describe("ClientSearchService.editorSearch", () => {
  it("always searches precisely for an already-imported project slot's query, regardless of the caller's fuzzy preference", () => {
    const service = new ClientSearchService();
    const fuzzySettings: SearchSettings = {
      ...getDefaultSearchSettings({}),
      searchTypeSettings: { fuzzySearch: true, filterCardbacks: false },
    };
    const retrieveCardIdentifiersSpy = jest
      .spyOn(service, "retrieveCardIdentifiers")
      .mockReturnValue([]);

    service.editorSearch(fuzzySettings, [
      { query: "lightning bolt", cardType: CardType.Card },
    ]);

    expect(retrieveCardIdentifiersSpy).toHaveBeenCalledTimes(1);
    const [passedSettings] = retrieveCardIdentifiersSpy.mock.calls[0];
    expect(passedSettings.searchTypeSettings.fuzzySearch).toBe(false);
    // the caller's own settings object must not be mutated
    expect(fuzzySettings.searchTypeSettings.fuzzySearch).toBe(true);
  });
});
