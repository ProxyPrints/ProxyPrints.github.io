/**
 * The "quiz-reveal hero" teaser text (issue #305, wtc-redesign-spec.md W5/W9) - the wordmark
 * (`frontend/public/whatsthat-wordmark.svg`) sliced into its three words, WHAT'S / THAT /
 * CARD?, each rendered as its own cropped `<svg>` so they can sit independently in the hero
 * grid and pop in sequence on every new card.
 *
 * The wordmark's own path data is duplicated here verbatim (not loaded via `<img src="...">`)
 * specifically so each word can set its own `viewBox` - an externally-loaded SVG document's
 * viewBox can't be retargeted from the referencing `<img>`. This is the exact mechanism
 * wtc-redesign-spec.md's W5 describes: "inline the wordmark's <path> set once ... and render
 * three <svg> each with one band - same asset, three crops, zero new art." If the source
 * wordmark ever changes, regenerate LETTER_GROUPS by re-running the same extraction against
 * the new `whatsthat-wordmark.svg` (see docs/features/printing-tags.md's word-slicing note).
 */

import { keyframes } from "@emotion/react";
import styled from "@emotion/styled";
import React from "react";

// One entry per letter-group path in whatsthat-wordmark.svg's `<g transform="translate(7,9)">`
// shadow layer (16 groups - 14 letters, plus the "?" glyph's curve + dot as two separate
// paths). Extracted verbatim, not retyped - see this file's own header comment.
const LETTER_GROUPS: ReadonlyArray<{ d: string; transform: string }> = [
  {
    d: "M0 184 L76 184 L118 300 L150 214 L182 300 L224 184 L300 184 L248 380 L190 380 L150 272 L110 380 L52 380 Z",
    transform: "translate(0, 39.1) rotate(-4 150 300)",
  },
  {
    d: "M42 380 L42 206 L0 206 L0 184 L100 184 L100 274 L166 274 L166 206 L124 206 L124 184 L224 184 L224 380 L166 380 L166 320 L100 320 L100 380 L42 380 Z",
    transform: "translate(260, 17.6) rotate(3 112 300)",
  },
  {
    d: "M76 380 L76 232 L4 232 L4 206 L0 206 L0 184 L200 184 L200 206 L196 206 L196 232 L128 232 L128 380 L76 380 Z",
    transform: "translate(546, 3.5) rotate(5 100 300)",
  },
  {
    d: "M186 246 L186 232 Q186 184 106 184 Q22 184 22 246 Q22 294 96 308 L122 313 Q142 317 142 331 Q142 350 106 350 Q80 350 80 328 L80 320 L16 320 L16 332 Q16 380 108 380 Q198 380 198 318 Q198 270 124 256 L98 251 Q80 247 80 233 Q80 214 106 214 Q128 214 128 234 L128 246 Z",
    transform: "translate(786, 6.8) rotate(-3 105 300)",
  },
  {
    d: "M146 296 L146 380 L96 380 L96 360 Q74 384 40 378 Q0 370 0 320 Q0 262 56 258 Q92 255 96 284 L96 296 ZM96 306 Q96 290 70 290 Q48 290 48 320 Q48 350 70 350 Q96 350 96 334 Z",
    transform: "translate(440, 20.7) rotate(-3 73 300)",
  },
  {
    d: "M46 184 L82 196 L40 268 L6 254 Z",
    transform: "translate(716, 5.8) rotate(0 46 300)",
  },
  {
    d: "M76 380 L76 232 L4 232 L4 206 L0 206 L0 184 L200 184 L200 206 L196 206 L196 232 L128 232 L128 380 L76 380 Z",
    transform: "translate(1042, -4.9) rotate(4 100 300)",
  },
  {
    d: "M42 380 L42 206 L0 206 L0 184 L100 184 L100 274 L166 274 L166 206 L124 206 L124 184 L224 184 L224 380 L166 380 L166 320 L100 320 L100 380 L42 380 Z",
    transform: "translate(1200, 5.6) rotate(-3 112 300)",
  },
  {
    d: "M76 380 L76 232 L4 232 L4 206 L0 206 L0 184 L200 184 L200 206 L196 206 L196 232 L128 232 L128 380 L76 380 Z",
    transform: "translate(1486, 11.4) rotate(-3 100 300)",
  },
  {
    d: "M146 296 L146 380 L96 380 L96 360 Q74 384 40 378 Q0 370 0 320 Q0 262 56 258 Q92 255 96 284 L96 296 ZM96 306 Q96 290 70 290 Q48 290 48 320 Q48 350 70 350 Q96 350 96 334 Z",
    transform: "translate(1380, -0.6) rotate(4 73 300)",
  },
  {
    d: "M214 206 L180 234 A56 56 0 1 0 176 330 L210 356 A114 106 0 1 1 214 206 Z",
    transform: "translate(1732, 20.2) rotate(-6 107 300)",
  },
  {
    d: "M42 380 L42 206 L0 206 L0 184 L84 184 L150 184 Q206 184 206 242 Q206 290 164 306 L268 392 L186 392 L116 312 L100 312 L100 380 L42 380 ZM100 228 L144 228 Q164 228 164 250 Q164 272 144 272 L100 272 Z",
    transform: "translate(1978, 26.5) rotate(-2 134 300)",
  },
  {
    d: "M146 296 L146 380 L96 380 L96 360 Q74 384 40 378 Q0 370 0 320 Q0 262 56 258 Q92 255 96 284 L96 296 ZM96 306 Q96 290 70 290 Q48 290 48 320 Q48 350 70 350 Q96 350 96 334 Z",
    transform: "translate(1892, 30.2) rotate(4 73 300)",
  },
  {
    d: "M42 380 L42 206 L0 206 L0 184 L84 184 Q158 184 158 282 Q158 382 60 382 L42 382 ZM90 234 Q122 234 122 282 Q122 330 90 330 L88 330 L88 234 Z",
    transform: "translate(2206, 46.1) rotate(6 79 300)",
  },
  {
    d: "M760 190 L802 193 L846 208 L858 218 L856 232 L853 266 L846 296 L820 316 L814 384 L781 384 L784 316 L792 298 L806 290 L830 270 L817 236 L786 234 L786 264 L754 266 L735 256 L731 214 Z",
    transform: "translate(1686.0, 40.0) scale(1)",
  },
  {
    d: "M786 412 L822 414 L828 421 L826 450 L819 456 L787 453 L781 445 L783 418 Z",
    transform: "translate(1686.0, 40.0) scale(1)",
  },
];

// gradient id matches the source SVG's own pre-namespaced `wtc-grad-word` (chosen there
// specifically so it can't collide with whatsthat-mark.svg's `wtc-grad-mark` if both an
// icon-only asset and this inlined copy ever render on the same page at once - see
// whatsthat.tsx's manifest icons).
function WordmarkGlyphs() {
  return (
    <>
      <defs>
        <linearGradient id="wtc-grad-word" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#F8D42B" />
          <stop offset="52%" stopColor="#EFCB16" />
          <stop offset="100%" stopColor="#D6AB11" />
        </linearGradient>
      </defs>
      {/* The wordmark's offset "shadow" copy - a solid navy duplicate nudged down-right,
          giving the letters a chunky drop-shadow without needing an SVG filter. */}
      <g transform="translate(7,9)">
        {LETTER_GROUPS.map((glyph, index) => (
          <path
            key={`shadow-${index}`}
            d={glyph.d}
            fillRule="evenodd"
            transform={glyph.transform}
            fill="#124063"
            stroke="#124063"
            strokeWidth={15}
            strokeLinejoin="round"
            strokeLinecap="round"
            paintOrder="stroke fill"
          />
        ))}
      </g>
      {/* The un-offset letters themselves - a navy outline pass (gives the gradient fill a
          crisp border) followed by the actual gold-gradient fill on top. */}
      {LETTER_GROUPS.map((glyph, index) => (
        <React.Fragment key={`letter-${index}`}>
          <path
            d={glyph.d}
            fillRule="evenodd"
            transform={glyph.transform}
            fill="#1a659a"
            stroke="#1a659a"
            strokeWidth={15}
            strokeLinejoin="round"
            strokeLinecap="round"
            paintOrder="stroke fill"
          />
          <path
            d={glyph.d}
            fillRule="evenodd"
            transform={glyph.transform}
            fill="url(#wtc-grad-word)"
          />
        </React.Fragment>
      ))}
    </>
  );
}

// Sequenced grow-then-shrink pop (wtc-redesign-spec.md W9/§5) - scale only (GPU-friendly),
// rotation held constant via a CSS custom property so each word keeps its own small rest tilt
// through every frame instead of snapping to upright mid-animation.
export const wtcWordPop = keyframes`
  0% { transform: rotate(var(--wtc-word-rotate, 0deg)) scale(1); }
  48% { transform: rotate(var(--wtc-word-rotate, 0deg)) scale(1.34); }
  100% { transform: rotate(var(--wtc-word-rotate, 0deg)) scale(1); }
`;

const WordsColumn = styled.div`
  display: flex;
  flex-direction: column;
  /* Flex's default align-items: stretch forces each Word's cross-axis size (width, in this
     column-direction flex - a replaced element's width: auto is exactly the trigger condition
     for stretch to override it) to fill the container's full width - which then re-derives
     each SVG's internal preserveAspectRatio scale against that stretched, no-longer-intrinsic
     box, revealing glyphs beyond the intended viewBox crop instead of respecting it. flex-start
     keeps every Word at its own intrinsic (height-driven) width so each one crops to exactly
     its own band. */
  align-items: flex-start;
  gap: 0.125rem;
  line-height: 0.92;

  /* Phone stack (wtc-mockup.html's .is-phone .wtc-words) centers the words instead - matching
     the rest of the phone stack (card, counts, question panel all centered below md). */
  @media (max-width: 767.98px) {
    align-items: center;
  }
`;

// `$delayMs` staggers WHAT'S -> THAT -> CARD? into one continuous left-to-right ripple (one
// word is still shrinking as the next grows) rather than three isolated pops - see
// wtc-redesign-spec.md §5's timeline. `both` fill holds the pre-delay start frame and the
// post-animation end frame, so there's no flash at a different size before/after the pop.
// Fix round (owner live-review blocker, post-#310): each word used to be a fixed 3.75rem/
// 4.5rem tall (60px/72px) - roughly 1.4x the height wtc-mockup.html's own approved design
// actually renders at (measured via a real headless render of that file with its demo-only
// scale transform removed: the L1 word stack's own line-box height is 164px total for all
// three words at 1280px wide, not the ~220px this used to render at). That's a "graphic",
// not a "header" - and since #310 bounded the WHOLE hero to one viewport-height row (the
// owner's pinning addendum), every extra pixel spent on the words came directly out of
// HeroQuestionsArea's own budget (HeroGrid's `auto` row - see that component's comment) -
// exactly why even Level 1 stopped fitting without an internal scroll.
// Even mockup's own 164px figure isn't quite enough headroom once bounded to one viewport row
// (mockup itself was never height-constrained - its hero simply grew as tall as it needed,
// with the page scrolling normally below), so this goes a further step smaller than the
// mockup's own absolute number - clamp()'d to a fraction of the viewport height (not a flat
// rem guess) so it structurally can't reclaim the fix on a shorter viewport than 1400x900 was
// checked at, while never rendering smaller than genuinely legible (min bound) or larger than
// a true "header" ought to look (max bound).
// Second pass (rebase onto #313's three-tier Footer redesign) - the new Footer is
// substantially taller (its own margin-top plus top padding alone add up to 48px, on top of
// its actual three-tier content), which pushed HeroGrid's own available height down further
// still. Re-measured directly via this task's own Playwright diagnostics rather than
// re-deriving by hand: the >= md clamp() bound is reduced again here so the words read
// smaller still - closer to a compact wordmark "sticker" than even the first pass's header
// scale - specifically to restore real margin under Level 1's hard no-scroll assertion
// against this heavier footer, not because the mockup proportion itself changed.
// Fix round (owner blocker, "the pulse doesn't sync with the pop") - the whole choreography
// (blue cover fade + this pop sequence + CardPulseWrapper's card pulse, cardPanel.tsx) is now
// anchored to the subject card image's own load event, not to this component's mount time (see
// QuestionFeed.tsx's imageLoaded state and the comment on its cardImage block). `$playing`
// starts false (the animation is frozen at its own delay/0% frame - CSS's own
// `animation-play-state: paused`, applied from this component's very first style computation,
// never lets the timeline - delay included - advance at all) and flips true only once
// QuestionFeed.tsx confirms the image has actually settled, so a slow network can't run this
// pop against a still-loading (or half-painted) card. Reduced-motion is unaffected by this prop
// - the `@media (prefers-reduced-motion: reduce)` override below still wins regardless of
// `$playing`'s value, exactly as before this fix round.
const Word = styled.svg<{ $delayMs: number; $playing: boolean }>`
  display: block;
  height: clamp(1.5rem, 3.2dvh, 2rem);
  width: auto;
  max-width: 100%;
  /* A root <svg> (unlike a nested one) defaults to overflow: visible per the SVG spec's own UA
     stylesheet - without this, each word's viewBox crop (W5) does nothing and every instance
     paints the ENTIRE wordmark, just re-centered, rather than clipping to its own band. */
  overflow: hidden;
  transform-origin: center;
  transform: rotate(var(--wtc-word-rotate, 0deg));
  animation: ${wtcWordPop} 480ms cubic-bezier(0.34, 1.45, 0.64, 1) both;
  animation-delay: ${(props) => props.$delayMs}ms;
  animation-play-state: ${(props) => (props.$playing ? "running" : "paused")};

  @media (min-width: 768px) {
    height: clamp(1.15rem, 2.1dvh, 1.6rem);
  }

  /* Suppresses the pop (words render statically at rest size) - reduced-motion never gets a
     flash-of-unanimated-content since the base transform: rotate(...) rule above already
     renders the correct rest-state tilt with no animation involved. */
  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

interface WordSlice {
  label: string;
  viewBox: string;
  delayMs: number;
  rotateDeg: number;
}

// viewBox bands measured directly off whatsthat-wordmark.svg's own letter-start x-coordinates
// (wtc-redesign-spec.md W5's table) - the wide gaps between words (789->1042, 1486->1732)
// are what make a clean three-way crop possible with no new art.
const WORDS: ReadonlyArray<WordSlice> = [
  { label: "WHAT'S", viewBox: "-40 150 1030 340", delayMs: 0, rotateDeg: -2 },
  { label: "THAT", viewBox: "990 150 695 340", delayMs: 240, rotateDeg: 1.5 },
  { label: "CARD?", viewBox: "1685 150 905 340", delayMs: 480, rotateDeg: -1 },
];

interface WhatsThatWordsProps {
  // Re-arms the pop sequence by forcing React to remount every word (wtc-redesign-spec.md
  // W9: "re-armed by keying the words container on the item id") - pass the current queue
  // item's card identifier so a fresh card always restarts the ripple from WHAT'S.
  animationKey: string;
  // Fix round (owner blocker) - see the Word component's own comment. False (the default new
  // callers should pass explicitly, see QuestionFeed.tsx) holds every word paused at its own
  // delay/0% frame; true starts the whole staggered sequence from that frozen point.
  playing: boolean;
}

export function WhatsThatWords({ animationKey, playing }: WhatsThatWordsProps) {
  return (
    // Purely decorative re-statement of the page's own <h1> (see whatsthat.tsx) - hidden from
    // assistive tech rather than duplicating the accessible name. aria-hidden lives on the
    // container itself (not a wrapping <span> around the three <svg>s) so each Word stays a
    // direct flex child and stacks correctly - an inline wrapper here would break the column.
    <WordsColumn data-testid="whatsthat-words" aria-hidden="true">
      {WORDS.map((word) => (
        <Word
          key={`${word.label}-${animationKey}`}
          $delayMs={word.delayMs}
          $playing={playing}
          viewBox={word.viewBox}
          style={
            { "--wtc-word-rotate": `${word.rotateDeg}deg` } as
              | React.CSSProperties
              | undefined
          }
          data-testid={`whatsthat-word-${word.label.replace(/[^a-z]/gi, "")}`}
        >
          <WordmarkGlyphs />
        </Word>
      ))}
    </WordsColumn>
  );
}
