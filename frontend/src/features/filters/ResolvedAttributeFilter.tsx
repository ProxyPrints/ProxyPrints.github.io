/**
 * Opt-in filters on printing attributes (full art, borderless) that the community has
 * confirmed via the printing-tag vote system. Both default off. Since these attributes are
 * only known for cards with a community-resolved printing, enabling a filter here never
 * removes a card that doesn't have one yet - it only excludes cards whose confirmed printing
 * actively fails the check. This component forms part of the Search Settings modal.
 */

import Container from "react-bootstrap/Container";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import { ToggleButtonHeight } from "@/common/constants";
import { FilterSettings } from "@/common/schema_types";

interface ResolvedAttributeFilterProps {
  filterSettings: FilterSettings;
  setFilterSettings: (value: FilterSettings) => void;
}

export function ResolvedAttributeFilter({
  filterSettings,
  setFilterSettings,
}: ResolvedAttributeFilterProps) {
  return (
    <Container className="px-1">
      <h5>Community-Confirmed Printing Attributes</h5>
      These filters only affect cards with a printing the community has
      confirmed via voting.
      <br />
      Cards without a confirmed printing are unknowns, not mismatches &mdash;
      they&apos;re never hidden by these filters.
      <br />
      <br />
      <Toggle
        onClick={() =>
          setFilterSettings({
            ...filterSettings,
            fullArtOnly: !filterSettings.fullArtOnly,
          })
        }
        on="Full Art Only"
        onClassName="flex-centre"
        off="Include All Art"
        offClassName="flex-centre"
        onstyle="success"
        offstyle="info"
        width={100 + "%"}
        size="md"
        height={ToggleButtonHeight + "px"}
        active={filterSettings.fullArtOnly}
      />
      <br />
      <br />
      <Toggle
        onClick={() =>
          setFilterSettings({
            ...filterSettings,
            borderlessOnly: !filterSettings.borderlessOnly,
          })
        }
        on="Borderless Only"
        onClassName="flex-centre"
        off="Include All Borders"
        offClassName="flex-centre"
        onstyle="success"
        offstyle="info"
        width={100 + "%"}
        size="md"
        height={ToggleButtonHeight + "px"}
        active={filterSettings.borderlessOnly}
      />
    </Container>
  );
}
