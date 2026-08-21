/**
 * A visible on/off switch for excluding external-IP art (custom proxies of non-Magic
 * properties) from search results. Deliberately NOT a new filter field: the toggle just
 * adds/removes the `external-ip` tag in `excludesTags`, the exact same state the tag
 * filter above edits - one source of truth, so the two controls can never disagree.
 * Part of the Search Settings modal.
 */

import Container from "react-bootstrap/Container";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import { CompactToggleHeight, EXTERNAL_IP_TAG_NAME } from "@/common/constants";
import { FilterSettings } from "@/common/schema_types";

interface UniverseWithinFilterProps {
  filterSettings: FilterSettings;
  setFilterSettings: (value: FilterSettings) => void;
}

export function UniverseWithinFilter({
  filterSettings,
  setFilterSettings,
}: UniverseWithinFilterProps) {
  const showingExternalIP =
    !filterSettings.excludesTags.includes(EXTERNAL_IP_TAG_NAME);
  const onClick = () =>
    setFilterSettings({
      ...filterSettings,
      excludesTags: showingExternalIP
        ? [...filterSettings.excludesTags, EXTERNAL_IP_TAG_NAME]
        : filterSettings.excludesTags.filter(
            (tag) => tag !== EXTERNAL_IP_TAG_NAME
          ),
    });
  return (
    <Container className="px-1">
      <h5>Universe Within</h5>
      Show only cards using original Magic art, hiding cards the community has
      tagged as borrowing art from an external, non-Magic property. This switch
      drives the <b>External IP</b> entry in the tag filter above &mdash;
      they&apos;re the same setting.
      <br />
      <br />
      <Toggle
        onClick={onClick}
        on="Showing Original Magic Art"
        onClassName="flex-centre"
        off="Hiding External IP Art"
        offClassName="flex-centre"
        onstyle="info"
        offstyle="warning"
        width={"100%"}
        size="sm"
        height={CompactToggleHeight + "px"}
        active={showingExternalIP}
      />
    </Container>
  );
}
