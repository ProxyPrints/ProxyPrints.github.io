/**
 * Resolves an MTG expansion code to its Keyrune icon-font glyph character. The glyph is
 * meant to be embedded directly inside a plain label string (not rendered as a separate
 * element) - see CanonicalCardFilter.tsx for why: the dropdown-tree-select library this
 * project uses requires node labels to stay plain strings, since its search filter and tag
 * ("pill") rendering both operate on `label` as a raw string. Keyrune is an icon font, so a
 * private-use-area character renders as a real vector glyph wherever `font-family: Keyrune`
 * applies (see StyledDropdownTreeSelect.tsx) - mixed with ordinary text in the same string,
 * browsers fall back per-character to the next font in the stack for anything Keyrune
 * doesn't define a glyph for, which is exactly what's needed here.
 */

import keyruneCodepoints from "@/common/generated/keyruneCodepoints.json";

export function getKeyruneChar(expansionCode: string): string {
  const codepoints: Record<string, string> = keyruneCodepoints;
  const hex = codepoints[expansionCode.toLowerCase()] ?? codepoints.default;
  return String.fromCodePoint(parseInt(hex, 16));
}
