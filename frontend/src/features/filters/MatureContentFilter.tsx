/**
 * A visible on/off switch for the mature-content exclusion that has always been baked into
 * the default search settings as `excludesTags: ["NSFW"]` (previously only discoverable by
 * digging the NSFW tag out of the tag-filter tree). Deliberately NOT a new filter field:
 * the toggle just adds/removes the NSFW tag in `excludesTags`, the exact same state the tag
 * filter above edits - one source of truth, so the two controls can never disagree.
 * Part of the Search Settings modal.
 */

import Container from "react-bootstrap/Container";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import { CompactToggleHeight, NSFW_TAG_NAME } from "@/common/constants";
import { FilterSettings } from "@/common/schema_types";

interface MatureContentFilterProps {
  filterSettings: FilterSettings;
  setFilterSettings: (value: FilterSettings) => void;
}

export function MatureContentFilter({
  filterSettings,
  setFilterSettings,
}: MatureContentFilterProps) {
  const showingMatureContent =
    !filterSettings.excludesTags.includes(NSFW_TAG_NAME);
  const onClick = () =>
    setFilterSettings({
      ...filterSettings,
      excludesTags: showingMatureContent
        ? [...filterSettings.excludesTags, NSFW_TAG_NAME]
        : filterSettings.excludesTags.filter((tag) => tag !== NSFW_TAG_NAME),
    });
  return (
    <Container className="px-1">
      <h5>Mature Content</h5>
      Cards the community has confirmed as NSFW are hidden from search by
      default. This switch drives the <b>NSFW</b> entry in the tag filter above
      &mdash; they&apos;re the same setting.
      <br />
      <br />
      <Toggle
        onClick={onClick}
        on="Showing Mature Content"
        onClassName="flex-centre"
        off="Hiding Mature Content"
        offClassName="flex-centre"
        onstyle="warning"
        offstyle="info"
        width={"100%"}
        size="sm"
        height={CompactToggleHeight + "px"}
        active={showingMatureContent}
      />
    </Container>
  );
}
