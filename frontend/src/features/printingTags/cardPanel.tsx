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
// the middle, then fades to reveal the real art. The Scryfall candidate
// list is deliberately not rendered until this finishes (see `revealed` state below) - the
// whole point is to test recognition before handing over the answer options.
//
// Fix round (owner live-review, "the blue should fade sooner") - this used to hold at full
// opacity for the first 55% of its 1.8s run (a leftover from BEFORE #317 gated `$playing` on
// the real image-load event below: back when this fired at mount time regardless of whether
// the image had actually arrived, that hold bought the network a moment to catch up). Now that
// `$playing` already stays paused at this 0% frame until QuestionFeed.tsx confirms the image
// has genuinely loaded (see RevealOverlay's own `$playing` prop and QuestionFeed.tsx's
// `onCardImageSettled`), the hold is pure redundant lag layered ON TOP of the real wait - by
// the time this is ever allowed to run, the image is already there, so holding at opacity 1 for
// another ~1s just reads as "nothing happened yet". Collapsed to a plain two-stop fade (no hold
// checkpoint at all) so the drop starts the instant playback resumes, and shortened 1.8s ->
// 0.8s + switched ease-in -> ease-out so the fade is visibly moving immediately rather than
// creeping through its own first chunk before accelerating (ease-in's shape does that same
// "slow start" thing a hold does, just continuously instead of as a flat plateau). Timings
// (see cardPanel.tsx/whatsthat PR body): WhatsThatWords' pop sequence (0/0.24s/0.48s delay,
// 0.48s duration each - ends at 0.48s/0.72s/0.96s) and CardPulseWrapper's pulse (0.24s delay,
// 0.48s duration - ends 0.72s) now land ACROSS this fade's own 0-0.8s run rather than only
// starting after it had long finished (old: hold 0-0.99s, fade 0.99s-1.8s), so the pops
// visibly overlap the fade's tail (its last ~40%, 0.48s-0.8s) as intended.
export const revealAnimation = keyframes`
  from { opacity: 1; }
  to { opacity: 0; }
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
//
// Fix round (owner blocker, "the pulse doesn't sync with the pop") - this used to fade on a
// fixed 1.8s timer starting the moment it mounted, with no regard for whether the card image
// underneath had actually finished loading - a slow network could reveal a still-loading (or
// half-painted) image right as WhatsThatWords/CardPulseWrapper's own pops fired, breaking the
// "one queued moment" the owner asked for. `$playing` (paused by default, same
// `animation-play-state` mechanism as Word in WhatsThatWords.tsx) holds this at its own 0%
// frame - fully opaque, i.e. the same solid cover the user has been looking at since mount -
// until QuestionFeed.tsx confirms the image has settled, so the fade (and therefore the
// `onAnimationEnd`-driven `revealed` flip) can never start before the image is actually there
// to reveal. QuestionFeed.tsx never sets `$playing` at all for a failed load (see its own
// comment) - the cover simply stays at this 0% frame indefinitely instead of fading onto a
// broken image, which is the "failed treatment" the owner asked for.
export const RevealOverlay = styled.div<{ $playing: boolean }>`
  position: absolute;
  inset: 0;
  background: ${STARBURST_OUTER_COLOR};
  color: black;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
  font-weight: bold;
  /* 0.8s ease-out, no hold - see revealAnimation's own comment above for the full before/after
     timing rationale (was 1.8s ease-in with a 55% hold). */
  animation: ${revealAnimation} 0.8s ease-out forwards;
  animation-play-state: ${(props) => (props.$playing ? "running" : "paused")};
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

  // Fix round (owner live-review, "portrait static top block") - height-caps the reference
  // card at narrow widths so the static top block (wordmark + card + name/badge/question text
  // + static action row) plus the scrollable options row below it fits a typical phone
  // viewport with no page scroll (QuestionFeedResponsive.spec.ts's Pixel-7 no-scroll assertion).
  // Expressed as a max-WIDTH derived FROM the target height (width = height * 63/88,
  // CARD_ASPECT_RATIO's own ratio), not a max-height layered on top of the existing width-driven
  // box below - the img inside (RevealWrapper) still sizes itself via width: 100% plus
  // aspect-ratio: 63/88, completely unchanged, so capping the WIDTH here to whatever value
  // yields the target height achieves the same visual result without fighting that existing
  // mechanism or breaking RevealOverlay's inset: 0 tracking (which follows THIS box's width,
  // not the image's intrinsic size).
  //
  // 32vh, not the first pass's 38vh - a real Playwright measurement (Pixel 7, this task's own
  // report) with a genuinely-loaded (not empty-src) hero image found 38vh left the candidate
  // options row only 69-105px of its own ~176px natural height even after also compacting the
  // action-button grid (Level2NarrowGrid's own comment), forcing HeroQuestionsArea's
  // overflow-y: auto defensive fallback to activate - not the zero-internal-scroll outcome the
  // spec asks for. 32vh gives the text/action/options budget back the difference.
  @media (max-width: 767.98px) {
    max-width: min(100%, calc(32vh * 63 / 88));
    margin: 0 auto;
  }
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

  // Same height-cap-via-max-width as CardPanel above (see its own comment) - Level 1's
  // compact single-card screen gets the same 32vh-capped card at narrow widths.
  @media (max-width: 767.98px) {
    max-width: min(100%, calc(32vh * 63 / 88));
    margin: 0 auto;
  }
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
// Below md, HeroCardArea (QuestionFeed.tsx) is a compact card column sitting beside a
// horizontally-scrollable answer column, not overlaid on top of it (see that component's own
// "mobile row" comment) - a burst bleeding past the card's own edges there lands in the row's
// own gap/blue field, the same "on-aesthetic bleed" the >= md case already accepts, not on top
// of scrolled-under text the way the card's old `position: sticky` bar (superseded) would have
// made a big bleed risky.
//
// Fix round (owner live-review, "no starburst visible on mobile") - the previous mobile value
// here, `90%`, was SMALLER than the card's own box (100% of the same CardPanel/StaticCardPanel
// this centers on), and `aspect-ratio: 1` makes it a perfect square besides - centered on a
// panel whose real box is a full-width, taller-than-wide portrait card, a burst narrower AND
// shallower than that box is entirely eclipsed by the (opaque) card art in every direction, by
// construction, regardless of the jagged/spiky silhouette's own shape (confirmed via a real
// Pixel 7 portrait screenshot + getBoundingClientRect() diff in this task's own report - the
// burst rendered at `opacity` 1/`width` ~108px sat fully inside the card image's own ~120px
// box). No value <= 100% can ever be visible here; `90%` reads as a scale-DOWN-from-desktop
// intent (the code comment historically called this "backing off to a modest size") rather
// than a literal CSS-width-of-container instruction - `200%` below is that same "back off from
// the >= md value" intent (230% * ~0.9, rounded), just actually large enough to bleed past the
// card's own edges the way every other breakpoint here already does.
export const BurstSvg = styled.svg<{ $hero?: boolean }>`
  position: absolute;
  top: 50%;
  left: 50%;
  width: ${(props) => (props.$hero ? "200%" : "55%")};
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  z-index: -1;
  pointer-events: none;

  // Fix round (owner live-review, "portrait static top block") - the card name/badge/question
  // text now sits directly under the card (QuestionFeed.tsx), exactly where this hero burst's
  // enlarged 200% bleed radiates its lower spikes at narrow widths. Rather than shrinking the
  // burst back down (the owner's own earlier ask keeps it visible at 200% bleed on mobile - see
  // the fix round above), a bottom-fade mask keeps the top/sides fully opaque (nothing competes
  // with those) and fades the lower ~35% toward transparent, so the spikes never fight the text
  // below for contrast. $hero-only - the small per-candidate HoverBurst has no text sitting
  // underneath it and is unaffected.
  @media (max-width: 767.98px) {
    ${(props) =>
      props.$hero &&
      `
      mask-image: linear-gradient(to bottom, black 0%, black 55%, transparent 88%);
      -webkit-mask-image: linear-gradient(to bottom, black 0%, black 55%, transparent 88%);
    `}
  }

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
//
// Fix round (owner blocker, "the pulse doesn't sync with the pop") - `$playing` (same
// paused-until-told-otherwise `animation-play-state` mechanism as Word in WhatsThatWords.tsx
// and RevealOverlay above) holds this at its own 0% frame (scale(1) - visually identical to
// the un-pulsed rest state, so there's no flash) until QuestionFeed.tsx confirms the card
// image has actually loaded, so this can never fire early against a still-loading card - see
// QuestionFeed.tsx's own comment on the shared `imageLoaded` state that drives all three of
// these paused animations at once.
export const wtcCardPulse = keyframes`
  0% { transform: scale(1); }
  48% { transform: scale(1.1); }
  100% { transform: scale(1); }
`;

export const CardPulseWrapper = styled.div<{ $playing: boolean }>`
  transform-origin: center;
  width: 100%;
  max-width: 320px;
  animation: ${wtcCardPulse} 480ms cubic-bezier(0.34, 1.45, 0.64, 1) both;
  animation-delay: 240ms;
  animation-play-state: ${(props) => (props.$playing ? "running" : "paused")};

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
// `$edge` (fix round, PR #305/#308) - the candidate grid's scroll box (HeroQuestionsArea,
// QuestionFeed.tsx) genuinely clips this burst's full 331.2% bloom for the leftmost/rightmost
// column in every row (confirmed via a real boundingBox()-vs-container overlap check, not just
// a visual read): even with that box's own added bleed room (2.5rem each side), a burst this
// oversized still overhangs past it for an edge column specifically (a middle column's bloom
// safely overlaps its neighbours instead, which is the existing, accepted "on-aesthetic bleed"
// look). Shrinking ONLY the edge columns' burst - not every candidate's - keeps the approved,
// full-size glow everywhere it geometrically fits, trading a uniformly smaller effect
// (which would look identical everywhere but weaker) for a fully unclipped one that's only
// slightly reduced right at the two edges where there's genuinely no more room to give it.
export const HoverBurst = styled.svg<{ $edge?: boolean }>`
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

  @media (min-width: 768px) {
    width: ${(props) => (props.$edge ? "150%" : "331.2%")};
  }
`;
