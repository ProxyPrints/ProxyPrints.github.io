import classnames from "classnames";
import React from "react";

/**
 * Renders a Keyrune MTG set-symbol glyph via the `ss ss-<code>` classes Keyrune's CSS
 * defines (stylesheet loaded globally in _document.tsx). Unlike CanonicalCardFilter.tsx,
 * nothing here constrains rendering to a plain-string label, so this uses real markup
 * instead of the embedded-PUA-character trick that component needs (see common/keyrune.ts).
 * An expansion code Keyrune doesn't recognise falls back to its default `.ss:before` glyph
 * automatically, since only the more specific `.ss-<code>` rule is missing - no explicit
 * fallback logic needed here.
 */
export const SetIcon = ({
  expansionCode,
  className,
}: {
  expansionCode: string;
  className?: string;
}) => (
  <i
    className={classnames("ss", `ss-${expansionCode.toLowerCase()}`, className)}
    aria-hidden="true"
  />
);
