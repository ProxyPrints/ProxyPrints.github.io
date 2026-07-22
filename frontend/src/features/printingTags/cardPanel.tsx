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
import { useEffect, useState } from "react";
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

// SUPERSEDED (quiz-reveal hero redesign, issue #305): this used to be `position: sticky` at
// >= md, tracking the outer page scroll via useStickyTop below so the card stayed in view
// beside a taller candidate column. The redesign's hero grid (see QuestionFeed.tsx's
// HeroGrid/HeroCardArea) bounds the whole hero to one viewport-height row at >= md and gives
// only the questions column its own internal scrollbar instead - the card's grid cell never
// scrolls in the first place, so there's nothing left for position: sticky to do. useStickyTop
// is removed alongside it (dead code with no other caller). Below `md`, HeroCardArea itself
// applies a compact `position: sticky` bar (see that component's own comment) - this styled
// component stays deliberately position-agnostic so that outer wrapper is the only thing
// controlling stickiness.
//
// `position: relative; z-index: 0;` together establish CardPanel's own local stacking context,
// containing BurstSvg's `z-index: -1` (see below) to just this panel - without a stacking
// context here, that negative z-index would search *up* the tree for the nearest positioned
// ancestor instead, risking the burst painting behind unrelated ancestor content rather than
// just behind this panel's own card art. `position: relative` alone (no z-index) does NOT
// establish a stacking context per the CSS spec, hence z-index: 0 (not left at auto) here.
export const CardPanel = styled.div`
  position: relative;
  z-index: 0;
  width: 100%;
`;

// Level 1's compact single-card confirmation screen (QuestionFeed.tsx) has no long scrollable
// candidate list to keep the card pinned against while scrolling past, at any viewport width -
// unlike Level 2's two-column layout. Same as CardPanel above now - `position: relative;
// z-index: 0;` gives BurstSvg/RevealOverlay the positioned containing block they anchor
// themselves to, and its own local stacking context for BurstSvg's negative z-index, with
// nothing sticky or detached from normal document flow at any width.
export const StaticCardPanel = styled.div`
  position: relative;
  z-index: 0;
  width: 100%;
`;

// Sized and centred purely with CSS (percentage width + aspect-ratio, both relative to
// CardPanel's own box) rather than a JS measurement - it scales naturally with the card's
// own responsive width at every breakpoint.
//
// `$hero` (additive, default off - wtc-redesign-spec.md §7) enlarges the burst for the quiz-
// reveal hero's left column, where it's meant to dominate the hero zone behind the card rather
// than stay tucked closely around it. Deliberately sized past the card's own box - the burst
// bleeding past CardPanel's edges (even into the hero's blue field or partway behind the
// words/questions columns) is on-aesthetic; CardPanel's own z-index: 0 stacking context (see
// above) keeps it from ever painting over the neighbouring columns' own text at >= md, since
// those render later in DOM order and are never negatively stacked themselves there.
//
// Below md the picture is different: HeroCardArea (QuestionFeed.tsx) becomes a small
// `position: sticky` bar sitting ABOVE the scrolling questions in z-index terms (by design -
// that's the whole point of the condensed pinning treatment), so an oversized burst bleeding
// out of that bar would obscure genuinely scrolled-under content, not just harmlessly bleed
// into empty hero field - a real legibility problem, unlike the desktop case. The hero
// enlargement backs off to a modest size on phone for exactly that reason.
export const BurstSvg = styled.svg<{ $hero?: boolean }>`
  position: absolute;
  top: 50%;
  left: 50%;
  width: ${(props) => (props.$hero ? "90%" : "55%")};
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  z-index: -1;
  pointer-events: none;

  @media (min-width: 768px) {
    width: ${(props) => (props.$hero ? "230%" : "55%")};
  }
`;

// The reference card itself pulses in lockstep with the "THAT" word (wtc-redesign-spec.md's
// owner addendum) - same easing/duration/delay as wtcWordPop in WhatsThatWords.tsx, but a much
// smaller amplitude (a full-size card visibly "breathing" at the word's 1.34x peak would read
// as violent, not playful) and disabled under reduced motion the same way. Deliberately a
// separate keyframe (not the words' shared one) since the two need different peak scales but
// must stay frame-for-frame in sync - keeping both timings as literal, matching values here and
// in WhatsThatWords.tsx is what actually keeps them in sync, not a shared constant (they're two
// independent CSS animations on unrelated elements with no runtime coupling). Re-armed the same
// way as the words - key this wrapper on the current item's card identifier so it remounts,
// and the animation restarts, on every new card.
export const wtcCardPulse = keyframes`
  0% { transform: scale(1); }
  48% { transform: scale(1.1); }
  100% { transform: scale(1); }
`;

export const CardPulseWrapper = styled.div`
  transform-origin: center;
  width: 100%;
  max-width: 320px;
  animation: ${wtcCardPulse} 480ms cubic-bezier(0.34, 1.45, 0.64, 1) both;
  animation-delay: 240ms;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
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
