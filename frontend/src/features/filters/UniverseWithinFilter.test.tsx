import { render, screen } from "@testing-library/react";
import React from "react";

import { FilterSettings } from "@/common/schema_types";

import { UniverseWithinFilter } from "./UniverseWithinFilter";

const baseFilterSettings: FilterSettings = {
  excludesTags: [],
  includesTags: [],
  languages: ["en"],
  maximumDPI: 1200,
  maximumSize: 100,
  minimumDPI: 300,
  fullArtOnly: false,
  borderlessOnly: false,
};

describe("UniverseWithinFilter", () => {
  test("reads as showing original art when excludesTags has no external-ip entry", () => {
    render(
      <UniverseWithinFilter
        filterSettings={baseFilterSettings}
        setFilterSettings={jest.fn()}
      />
    );
    expect(screen.getByText("Showing Original Magic Art")).toBeVisible();
  });

  // Proves the toggle has no state of its own: excluding "external-ip" via the tag tree above
  // (which writes the same excludesTags array this component reads) is indistinguishable from
  // clicking the toggle itself - one source of truth, so the two controls can never disagree.
  test("reads as hiding external IP art when excludesTags already contains external-ip", () => {
    render(
      <UniverseWithinFilter
        filterSettings={{
          ...baseFilterSettings,
          excludesTags: ["external-ip"],
        }}
        setFilterSettings={jest.fn()}
      />
    );
    expect(screen.getByText("Hiding External IP Art")).toBeVisible();
  });

  test("clicking the toggle adds external-ip to excludesTags", () => {
    const setFilterSettings = jest.fn();
    render(
      <UniverseWithinFilter
        filterSettings={baseFilterSettings}
        setFilterSettings={setFilterSettings}
      />
    );
    screen.getByText("Showing Original Magic Art").click();
    expect(setFilterSettings).toHaveBeenCalledWith({
      ...baseFilterSettings,
      excludesTags: ["external-ip"],
    });
  });

  test("clicking the toggle removes external-ip from excludesTags", () => {
    const setFilterSettings = jest.fn();
    render(
      <UniverseWithinFilter
        filterSettings={{
          ...baseFilterSettings,
          excludesTags: ["external-ip"],
        }}
        setFilterSettings={setFilterSettings}
      />
    );
    screen.getByText("Hiding External IP Art").click();
    expect(setFilterSettings).toHaveBeenCalledWith({
      ...baseFilterSettings,
      excludesTags: [],
    });
  });
});
