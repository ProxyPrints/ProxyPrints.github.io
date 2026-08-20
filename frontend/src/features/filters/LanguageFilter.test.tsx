import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { FilterSettings } from "@/common/schema_types";
import { localBackend } from "@/common/test-constants";
import { languagesNoResults, languagesTwoResults } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { LanguageFilter } from "./LanguageFilter";

const baseFilterSettings: FilterSettings = {
  excludesTags: [],
  includesTags: [],
  languages: [],
  maximumDPI: 1200,
  maximumSize: 100,
  minimumDPI: 300,
  fullArtOnly: false,
  borderlessOnly: false,
};

function renderFilter(
  filterSettings: FilterSettings,
  setFilterSettings: (value: FilterSettings) => void,
  allowedLanguages?: Array<string>
) {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <LanguageFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
        allowedLanguages={allowedLanguages}
      />
    </Provider>
  );
}

describe("LanguageFilter", () => {
  test("renders a chip for every known language when no present-language set is supplied", async () => {
    server.use(languagesTwoResults);
    renderFilter(baseFilterSettings, jest.fn());
    expect(await screen.findByTestId("language-chip-EN")).toBeVisible();
    expect(screen.getByTestId("language-chip-FR")).toBeVisible();
  });

  test("renders chips only for the caller-supplied present-language set", async () => {
    server.use(languagesTwoResults);
    renderFilter(baseFilterSettings, jest.fn(), ["EN"]);
    expect(await screen.findByTestId("language-chip-EN")).toBeVisible();
    expect(screen.queryByTestId("language-chip-FR")).not.toBeInTheDocument();
  });

  test("renders nothing when the language catalog is empty", async () => {
    server.use(languagesNoResults);
    renderFilter(baseFilterSettings, jest.fn());
    // Renders null both while the query is loading and once it resolves empty - nothing to
    // await here, the assertion holds throughout.
    expect(screen.queryByTestId("language-filter")).not.toBeInTheDocument();
  });

  test("marks the currently-selected language's chip checked", async () => {
    server.use(languagesTwoResults);
    renderFilter({ ...baseFilterSettings, languages: ["FR"] }, jest.fn());
    expect(
      await screen.findByRole("checkbox", { name: "French" })
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "English" })).not.toBeChecked();
  });

  test("clicking an unselected chip adds it to filterSettings.languages", async () => {
    const setFilterSettings = jest.fn();
    server.use(languagesTwoResults);
    renderFilter(baseFilterSettings, setFilterSettings);
    fireEvent.click(await screen.findByRole("checkbox", { name: "English" }));
    expect(setFilterSettings).toHaveBeenCalledWith({
      ...baseFilterSettings,
      languages: ["EN"],
    });
  });

  test("clicking an already-selected chip removes it from filterSettings.languages", async () => {
    const setFilterSettings = jest.fn();
    server.use(languagesTwoResults);
    renderFilter(
      { ...baseFilterSettings, languages: ["EN"] },
      setFilterSettings
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: "English" }));
    expect(setFilterSettings).toHaveBeenCalledWith({
      ...baseFilterSettings,
      languages: [],
    });
  });
});
