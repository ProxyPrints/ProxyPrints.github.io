/**
 * A series of numeric range filters which allow control over which Cards are included in search results.
 * Users can filter on a DPI range and set a maximum allowable file size.
 * This component forms part of the Search Settings modal.
 */

import React from "react";
require("react-dropdown-tree-select/dist/styles.css");

import { FilterSettings as FilterSettingsType } from "@/common/types";

import { DPIFilter } from "../filters/DPIFilter";
import { LanguageFilter } from "../filters/LanguageFilter";
import { MatureContentFilter } from "../filters/MatureContentFilter";
import { ResolvedAttributeFilter } from "../filters/ResolvedAttributeFilter";
import { SizeFilter } from "../filters/SizeFilter";
import { TagFilter } from "../filters/TagFilter";

interface FilterSettingsProps {
  filterSettings: FilterSettingsType;
  setFilterSettings: {
    (newFilterSettings: FilterSettingsType): void;
  };
  minDPILowerBound?: number;
  maxDPIUpperBound?: number;
  maxSizeUpperBound?: number;
  allowedLanguages?: Array<string>;
  showBoilerplate?: boolean;
  /** The /display rail already renders the spec's Treatment/Frame/Border chip fieldset
   * (SPEC-display-left-rail.md), so its embedding of this panel hides the duplicate
   * stock attribute toggles. Every other caller (Search Settings modal, classic grid
   * selector) leaves this true and is unchanged. */
  showResolvedAttributeFilter?: boolean;
}

export function FilterSettings({
  filterSettings,
  setFilterSettings,
  minDPILowerBound,
  maxDPIUpperBound,
  maxSizeUpperBound,
  allowedLanguages,
  showBoilerplate = true,
  showResolvedAttributeFilter = true,
}: FilterSettingsProps) {
  return (
    <>
      {showBoilerplate && (
        <>
          <h5>Filters</h5>
          Configure the DPI (dots per inch) and file size ranges the search
          results must be within.
          <br />
          At a fixed physical size, a higher DPI yields a higher resolution
          print.
          <br />
          Print resolution has a practical ceiling, though &mdash; beyond a
          certain point, a higher DPI print will <b>look the same</b> as a lower
          one.
          <br />
          <br />
        </>
      )}
      <DPIFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
        minDPILowerBound={minDPILowerBound}
        maxDPIUpperBound={maxDPIUpperBound}
      />
      <SizeFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
        maxSizeUpperBound={maxSizeUpperBound}
      />
      <LanguageFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
        allowedLanguages={allowedLanguages}
      />
      <TagFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
      />
      <br />
      <MatureContentFilter
        filterSettings={filterSettings}
        setFilterSettings={setFilterSettings}
      />
      {showResolvedAttributeFilter && (
        <>
          <br />
          <ResolvedAttributeFilter
            filterSettings={filterSettings}
            setFilterSettings={setFilterSettings}
          />
        </>
      )}
    </>
  );
}
