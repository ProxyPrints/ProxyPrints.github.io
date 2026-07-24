/**
 * The "What's That Card?" wordmark - WTC rebuild (2026-07-24, SPEC-wtc-rebuild.md section 1c
 * "wordmark h1"/"wordmark sub" rows + file-level change row for QuestionFeed.tsx).
 *
 * SUPERSEDES the pre-rebuild implementation entirely: that version inlined
 * `whatsthat-wordmark.svg`'s own `<path>` data (duplicated verbatim, see the old header
 * comment this replaces) so WHAT'S/THAT/CARD? could each pop in on their own staggered
 * animation, split into a `NarrowWordmark` (static single-line image, < md) / `WideWordmark`
 * (the animated sliced version, >= md) CSS-display fork. The rebuild retires BOTH the fork and
 * the animation itself:
 *   - WD1 kills the old gold/navy identity this wordmark's own gradient/stroke fills were
 *     hardcoded to (`#F8D42B`/`#124063`/`#1a659a`) - none of that is a token, so it can't be
 *     retinted onto `--wtc-wordmark` without a rewrite regardless.
 *   - the container-first policy (spec section 3) retires the 768px viewport-driven
 *     NarrowWordmark/WideWordmark CSS-display swap - one tree, `clamp()`-sized, no fork.
 *   - ANNEX C's animation inventory (mystery reveal, confirm-lands feedback, the static reveal
 *     glow, the static solved affordance) does not list a wordmark pop - it isn't carried
 *     forward into the rebuild.
 *
 * A plain, semantic `<h1>` (per-element binding table: colour `--wtc-wordmark`, the "?" echoed
 * in `--primary`, `font-size: clamp(26px, 4.4cqi, 44px)`, weight 900) replaces the sliced-SVG
 * animation - see wtc-mockup.html's `.wordmark` for the exact binding shape. whatsthat.tsx's own
 * `VisuallyHiddenHeading` (the page's *accessible*-name-only heading) is retired alongside this -
 * this IS now the page's one real, visible `<h1>`, so a second hidden one would be a duplicate
 * heading, not a fallback.
 */

import styled from "@emotion/styled";
import React from "react";

const Wordmark = styled.h1`
  margin: 0;
  line-height: 0.98;
  font-weight: 900;
  letter-spacing: -0.015em;
  color: var(--wtc-wordmark);
  font-size: clamp(26px, 4.4cqi, 44px);
  text-shadow: 0 0 22px
    color-mix(in srgb, var(--accent, #bb9af7) 26%, transparent);

  .q {
    color: var(--primary);
  }

  small {
    display: block;
    font-size: 0.34em;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--muted);
    text-shadow: none;
    margin-top: 3px;
  }
`;

export function WhatsThatWords() {
  return (
    <Wordmark data-testid="whatsthat-words">
      What&apos;s That Card
      <span className="q">?</span>
      <small>
        Help tag which real-world printing each scanned image depicts
      </small>
    </Wordmark>
  );
}
