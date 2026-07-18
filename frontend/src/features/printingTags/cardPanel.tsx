/**
 * Shared visual mechanics behind the "What's That Card?" subject-card panel: the sticky
 * starburst-backed card, the silhouette-reveal animation, the candidate-grid "mystery card"
 * placeholder/hover-zoom/hover-burst, and the flavor-text pool. Originally lived inline in
 * PrintingTagQueue.tsx (the single-card printing-tag queue); extracted verbatim so the
 * unified question feed (QuestionFeed.tsx) can reuse the exact same mechanics rather than
 * re-implementing them - see docs/features/printing-tags.md's questionFeed section and
 * journal/2026-07-14-queue-question-feed-design.md for why this is a re-composition, not a
 * rewrite. Every comment below is unchanged from its original call site.
 */

import { keyframes } from "@emotion/react";
import styled from "@emotion/styled";
import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";

import {
  STARBURST_OUTER_COLOR,
  STARBURST_OUTER_FRAMES,
} from "@/features/printingTags/starburstShape";

// Silhouette-reveal: the card starts as a black silhouette with a "?" in
// the middle, holds for a beat, then fades to reveal the real art. The Scryfall candidate
// list is deliberately not rendered until this finishes (see `revealed` state below) - the
// whole point is to test recognition before handing over the answer options.
export const revealAnimation = keyframes`
  0% { opacity: 1; }
  55% { opacity: 1; }
  100% { opacity: 0; }
`;

export const RevealWrapper = styled.div`
  position: relative;
  overflow: hidden;
`;

// Same blue as ArtPlaceholder below (and the starburst itself) rather than a plain black
// box, so the "mystery card" reveal reads as one consistent visual language with the
// candidate grid's own "?" placeholders instead of a mismatched black flash. Black text
// (matching the page-wide font colour) checked against this blue: contrast ratio ~6.2:1,
// clearly better than the white it replaced (~3.4:1).
export const RevealOverlay = styled.div`
  position: absolute;
  inset: 0;
  background: ${STARBURST_OUTER_COLOR};
  color: black;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
  font-weight: bold;
  animation: ${revealAnimation} 1.8s ease-in forwards;
  pointer-events: none;
`;

// The card, and the starburst behind it, stay glued to the viewport as the page scrolls
// (position: sticky) rather than scrolling away with the rest of the page - **desktop only,
// see the mobile override below**. "top" is set via inline style (see useStickyTop below) to
// wherever the panel naturally rendered when it first mounted, rather than a fixed offset -
// so it pins at its own original location on the page and never visibly jumps to a different
// spot once scrolling starts, it just stops moving exactly where it already was.
//
// z-index: -1 here (not just on BurstSvg) is deliberate and easy to get backwards: a sticky
// element always establishes its own stacking context, and *any* positioned descendant -
// even at the default z-index: auto - paints in front of plain, non-positioned in-flow
// siblings (the CSS spec's stacking order puts positioned content ahead of ordinary flow
// content, independent of DOM order or z-index value). Left at the default, that meant the
// whole panel - including the burst bleeding out of it - painted on top of the "What's That
// Card?" heading and the candidate grid's plain text/borders, hiding them. Pushing
// CardPanel itself to a negative stack level is what actually fixes that (giving BurstSvg
// alone a negative z-index only reorders it against its own siblings *inside* CardPanel,
// it can't reach past the sticky boundary).
//
// MOBILE OVERRIDE (layout reconciliation pass): real-device evidence (a phone, not this
// sandbox's Chromium, which never reproduces this) showed sticky-plus-negative-z-index
// compositing incorrectly below the `md` breakpoint - the sticky card's reserved layout-flow
// box and its actual pinned visual position diverge once the page scrolls, leaving a blank
// gap where the card "should" be and letting the candidates/answer controls below it in the
// DOM paint underneath/inside the card's own box instead of cleanly below it. This is the
// same mechanism Level 1's StaticCardPanel (below) was built to avoid entirely - Level 2 kept
// sticky because desktop's side-by-side two-column layout genuinely benefits from it and
// never showed the bug, but mobile's stacked single-column layout gets nothing from sticky
// (there's no side-by-side candidate list to stay pinned beside) and inherits the same
// cross-engine compositing risk Level 1 had. `position: static` below `md` removes the
// sticky/negative-stacking mechanism entirely on the widths where it broke, while `md` and up
// keeps the original desktop behavior unchanged. The `768px` threshold matches Bootstrap's own
// `md` breakpoint, the same one this page's `Col md={...}` two-column layout switches on.
export const CardPanel = styled.div`
  position: static;
  z-index: auto;

  @media (min-width: 768px) {
    position: sticky;
    top: 0;
    z-index: -1;
  }
`;

// Level 1's compact single-card confirmation screen (QuestionFeed.tsx) has no long scrollable
// candidate list to keep the card pinned against while scrolling past, at any viewport width -
// unlike Level 2's two-column layout, which is what CardPanel's desktop-only sticky-plus-
// negative-z-index mechanism above exists for. `position: relative` still gives
// BurstSvg/RevealOverlay the positioned containing block they anchor themselves to (identical
// visual result to CardPanel for that part), but with no sticky and no negative z-index at any
// width, there's nothing to detach from its own reserved space or to invert paint order
// against its siblings - the whole thing just stays one ordinary block in normal document flow,
// unconditionally.
export const StaticCardPanel = styled.div`
  position: relative;
`;

// Measures how far the panel naturally sits below the top of its scrolling ancestor (see
// ContentContainer in Layout.tsx - the app's content area is a fixed-position, internally
// scrolling box, not the normal document body) right after it mounts, and uses that as the
// sticky "top" offset. Re-measures whenever the subject card changes (a new card can nudge
// the layout by a few px - e.g. flavor text length), so each card pins at wherever it
// actually rendered rather than an offset carried over from a previous card. Runs in a
// plain useEffect, not useLayoutEffect - the measured value only matters once the user
// scrolls far enough for sticky to engage, so there's nothing to flash before it settles,
// and useLayoutEffect warns during Next's static export (no DOM on the server).
export function useStickyTop(deps: React.DependencyList): {
  ref: React.RefObject<HTMLDivElement>;
  top: number | null;
} {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [top, setTop] = useState<number | null>(null);

  useEffect(() => {
    const panel = ref.current;
    if (panel == null) {
      return;
    }
    let scrollParent: HTMLElement | null = panel.parentElement;
    while (
      scrollParent != null &&
      !["scroll", "auto"].includes(
        window.getComputedStyle(scrollParent).overflowY
      )
    ) {
      scrollParent = scrollParent.parentElement;
    }
    if (scrollParent == null) {
      return;
    }
    const panelRect = panel.getBoundingClientRect();
    const scrollRect = scrollParent.getBoundingClientRect();
    setTop(panelRect.top - scrollRect.top + scrollParent.scrollTop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ref, top };
}

// Sized and centred purely with CSS (percentage width + aspect-ratio, both relative to
// CardPanel's own box) rather than a JS measurement - it scales naturally with the card's
// own responsive width at every breakpoint, and travels with CardPanel automatically under
// sticky scrolling with no extra code.
export const BurstSvg = styled.svg`
  position: absolute;
  top: 50%;
  left: 50%;
  width: 55%;
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  z-index: -1;
  pointer-events: none;
`;

const STARBURST_FRAME_INTERVAL_MS = 150;

// Cycles through the precomputed jagged frames (see starburstShape.ts) to reproduce the
// reference gif's flicker. Always starts at frame 0 and only starts advancing inside
// useEffect (client-only, post-mount), so server-rendered and first-client-render markup
// stay identical - no hydration mismatch. Skips animating entirely under
// prefers-reduced-motion.
export function useStarburstFrame(
  frameCount: number = STARBURST_OUTER_FRAMES.length
): number {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const id = setInterval(() => {
      setFrame((previous) => (previous + 1) % frameCount);
    }, STARBURST_FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [frameCount]);

  return frame;
}

// Zooms the thumbnail in on hover, rather than the whole button, so the border/label stay
// put and only the artwork itself grows. Deliberately left uncropped (no overflow: hidden)
// so the enlarged art is fully visible rather than cut off at the original box edge -
// raised above its siblings on hover so it doesn't render underneath the neighbouring grid
// cells it now overlaps.
export const ZoomableThumbnail = styled.div`
  position: relative;
  z-index: 0;

  img {
    transition: transform 0.15s ease-out;
  }

  &:hover {
    z-index: 2;
  }

  &:hover img {
    transform: scale(1.6);
  }
`;

const FLAVOR_TEXT = [
  "Your spark ignites! On to the next mystery.",
  "A collector's eye for detail - nicely done!",
  "The multiverse is a little better catalogued because of you.",
  "Sharper than a Sphinx's riddle. Next card incoming!",
  "That's the stuff legends are made of. Keep going!",
  "Another printing pinned down. Onward!",
  "You've got a good spark for this. Next!",
  "Precisely the kind of insight the Multiverse needs.",
  "Well spotted. Here comes another.",
  "Your knowledge of the planes grows ever stronger.",
];

export function randomFlavorText(): string {
  return FLAVOR_TEXT[Math.floor(Math.random() * FLAVOR_TEXT.length)];
}

// Real Magic card ratio (63mm x 88mm), matching the print-ready `.ratio-7x5` convention
// already used elsewhere (custom.css) - reserves each thumbnail's box up front via CSS
// alone, so an image resolving its intrinsic size late over the network can't reflow the
// page (the starburst is centred on the card's own box - see CardPanel - so any unreserved
// reflow here would visibly resize the burst along with it).
export const CARD_ASPECT_RATIO = "63 / 88";

// Shared "mystery card" backdrop for every Scryfall art box in the candidate grid - reuses
// the starburst's own blue so it reads as one consistent visual language against the orange
// background rather than a mismatched placeholder colour. Candidates render their real
// artwork on top of this (so a slow-loading image transitions from a blue "?" card into the
// real art instead of a blank flash), and it's also the entire visual for the "No match"
// option, which has no real artwork to show at all - replacing the old black
// "Card Not Found :(" placeholder image.
export const ArtPlaceholder = styled.div`
  position: relative;
  width: 100%;
  aspect-ratio: ${CARD_ASPECT_RATIO};
  background: ${STARBURST_OUTER_COLOR};
  /* Deliberately no overflow: hidden here - object-fit: cover below already keeps the image
     contained within this box on its own (it crops the underlying image content to fit,
     it doesn't make the <img> element itself overflow), and clipping at this level was
     silently re-breaking ZoomableThumbnail's hover-zoom (added in a previous round
     specifically *without* overflow: hidden, so the enlarged art could pop out uncropped) -
     since ArtPlaceholder wraps ZoomableThumbnail, its own overflow: hidden clipped the zoom
     right back down to this box's edge, reading as a hard rectangular cut through the
     enlarged artwork. */

  &::before {
    content: "?";
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(0, 0, 0, 0.5);
    font-size: 3rem;
    font-weight: bold;
  }

  img {
    position: relative;
    z-index: 1;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
`;

// Bootstrap's `outline-secondary` border doesn't scale with the hover-zoomed thumbnail
// inside it (see ZoomableThumbnail) - it stays put as a stationary frame while the art
// visibly grows past it, breaking the effect - so it's dropped entirely (`border-0`,
// applied at each call site below) and this component only needs to own the "highlighted"
// look. Bootstrap's green `success` variant clashed with the page's blue "mystery" motif
// established elsewhere (ArtPlaceholder, RevealOverlay, the starburst itself), so "this is
// the resolved consensus pick" is now a solid fill in that same blue instead - there's no
// built-in Bootstrap variant in this exact shade, hence the custom class rather than
// swapping to `variant="primary"`. Black text (matching the page-wide font colour) checked
// against it: ~6.2:1 contrast, clearly better than white's ~3.4:1; the artist line below it
// is Bootstrap's `.text-muted` grey, which nearly disappeared against this blue, so it's
// darkened to translucent black specifically inside `.highlighted` (needs `!important` -
// Bootstrap's own text-color utilities are declared `!important`, so nothing else can win
// against it).
//
// Bootstrap's own `.btn-outline-secondary:hover` background (a flat grey) was still
// showing through around the card on hover, which read as a mismatched grey frame against
// the page's blue theme. Per direct request, that hover highlight is now a scaled-down copy
// of the page's own starburst (HoverBurst below) instead of a flat colour - `position:
// relative` + `z-index: 0` here gives HoverBurst's `z-index: -1` a local stacking context
// to sit behind ArtPlaceholder/the text without leaking out to sit behind this button's
// *siblings* in the grid too (the same mechanism as CardPanel/BurstSvg on the page-level
// starburst - see the comment there for the underlying CSS stacking rule).
export const CandidateButton = styled(Button)`
  position: relative;
  z-index: 0;
  overflow: visible;

  &:hover,
  &:focus {
    background-color: transparent !important;
  }

  &:hover .hover-burst {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }

  &.highlighted {
    background-color: ${STARBURST_OUTER_COLOR};
    color: #000000;
  }

  &.highlighted .text-muted {
    color: rgba(0, 0, 0, 0.65) !important;
  }
`;

// A smaller copy of the same starburst geometry, driven by the same shared
// `starburstFrame` state as the page-level burst (see useStarburstFrame below) rather than
// a frame of its own, so a zoomed card's highlight visibly flickers/moves in lockstep with
// the big one on the left instead of holding still - every instance ticks over together
// regardless of which card is actually hovered, since only the hovered one is visible
// (opacity 0 otherwise) and re-rendering a handful of invisible polygons every frame is
// cheap. Centred on and scaled up from the button's own box, the same way the page-level
// burst is centred on the subject card. Faded/scaled in via CSS on CandidateButton's
// `:hover` above rather than JS state, so nothing needs to track which card is hovered.
export const HoverBurst = styled.svg`
  position: absolute;
  top: 50%;
  left: 50%;
  width: 331.2%;
  aspect-ratio: 1;
  transform: translate(-50%, -50%) scale(0.75);
  opacity: 0;
  transition: opacity 0.18s ease-out, transform 0.18s ease-out;
  pointer-events: none;
  z-index: -1;
`;
