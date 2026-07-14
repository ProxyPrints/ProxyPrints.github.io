/**
 * Every tag-rendering site shows `displayName ?? name` - the human-editable presentation
 * text if one's been set on the `Tag`, falling back to the raw machine key (`Tag.name`,
 * which is what every site rendered before `displayName` existed) otherwise. API
 * submissions/filters never go through this - they always send `name`, the immutable
 * interchange key (see cardpicker/models.py's Tag.display_name help_text and
 * docs/federation-v1.md).
 *
 * Built from the same, already-cached `useGetTagsQuery()` other consumers (e.g. TagFilter)
 * already use - calling this hook doesn't trigger a new fetch. Flattens the tag tree
 * (`children`, recursively) so a lookup works for a child tag too, not just top-level ones.
 */

import { useMemo } from "react";

import { useGetTagsQuery } from "@/store/api";

interface TagLike {
  name: string;
  displayName?: string | null;
  children: Array<TagLike>;
}

function flattenDisplayNames(tags: Array<TagLike>): Map<string, string> {
  const displayNameByName = new Map<string, string>();
  const visit = (tag: TagLike) => {
    if (tag.displayName != null) {
      displayNameByName.set(tag.name, tag.displayName);
    }
    tag.children.forEach(visit);
  };
  tags.forEach(visit);
  return displayNameByName;
}

export function useTagDisplayName(): (tagName: string) => string {
  const { data } = useGetTagsQuery();
  const displayNameByName = useMemo(
    () => flattenDisplayNames(data ?? []),
    [data]
  );
  return (tagName: string) => displayNameByName.get(tagName) ?? tagName;
}
