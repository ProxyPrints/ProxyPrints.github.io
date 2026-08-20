import styled from "@emotion/styled";
import { useMemo } from "react";
import Form from "react-bootstrap/Form";
import ToggleButton from "react-bootstrap/ToggleButton";
import ToggleButtonGroup from "react-bootstrap/ToggleButtonGroup";

import { FilterSettings } from "@/common/schema_types";
import { useGetLanguagesQuery } from "@/store/api";

interface LanguageFilterProps {
  filterSettings: FilterSettings;
  setFilterSettings: (value: FilterSettings) => void;
  /** Languages actually present among the current search candidates - computed by the caller
   * from the same pre-filter identifier pool CanonicalCardFilter already uses for its own
   * available-printings/available-artists options (see GridSelectorFilters.tsx). `undefined`
   * (no caller-supplied present set - the Search Settings modal doesn't have a candidate pool
   * to compute one from) falls back to every known language rather than rendering nothing. */
  allowedLanguages?: Array<string>;
}

// Mirrors the funnel row's own chip styling (CompactToggleButton, SelectVersionResults.tsx) -
// same variant/size/padding convention - but stays local since that styled component isn't
// exported and this filter sits outside that file's scope.
const LanguageChip = styled(ToggleButton)`
  padding: 0.2rem 0.6rem;
  font-size: 0.8rem;
  line-height: 1.2;
  border-radius: 999px !important;
  margin: 0 !important;
`;

const LanguageChipGroup = styled(ToggleButtonGroup)`
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
`;

export const LanguageFilter = ({
  filterSettings,
  setFilterSettings,
  allowedLanguages,
}: LanguageFilterProps) => {
  const getLanguagesQuery = useGetLanguagesQuery();
  const languageOptions = useMemo(() => {
    const allOptions = (getLanguagesQuery.data ?? []).map((row) => ({
      label: row.name,
      value: row.code,
    }));
    if (allowedLanguages != null && allowedLanguages.length > 0) {
      const allowedSet = new Set(allowedLanguages);
      return allOptions.filter((opt) => allowedSet.has(opt.value));
    }
    return allOptions;
  }, [getLanguagesQuery.data, allowedLanguages]);

  if (languageOptions.length === 0) {
    return null;
  }

  return (
    <div data-testid="language-filter">
      <Form.Label id="language-filter-label" as="span">
        Languages
      </Form.Label>
      <div>
        <LanguageChipGroup
          type="checkbox"
          name="language-filter"
          aria-labelledby="language-filter-label"
          value={filterSettings.languages}
          onChange={(selected: Array<string>) =>
            setFilterSettings({ ...filterSettings, languages: selected })
          }
        >
          {languageOptions.map((option) => (
            <LanguageChip
              key={option.value}
              id={`language-chip-${option.value}`}
              value={option.value}
              variant="outline-secondary"
              size="sm"
              data-testid={`language-chip-${option.value}`}
            >
              {option.label}
            </LanguageChip>
          ))}
        </LanguageChipGroup>
      </div>
    </div>
  );
};
