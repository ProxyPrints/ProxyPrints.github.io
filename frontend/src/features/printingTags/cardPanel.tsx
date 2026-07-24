/**
 * Shared visual mechanics behind the "What's That Card?" subject-card panel: the mystery-card
 * silhouette-reveal animation, the candidate-grid "mystery card" placeholder/hover-zoom, and
 * the flavor-text pool. Originally lived inline in PrintingTagQueue.tsx; extracted so the
 * unified question feed (QuestionFeed.tsx) can reuse the exact same mechanics rather than
 * re-implementing them - see docs/features/printing-tags.md's questionFeed section.
 *
 * WTC rebuild (2026-07-24, SPEC-wtc-rebuild.md, owner rulings) - this pass:
 *   - retints MysteryCardFace/its glyph onto the `--wtc-mystery-face`/`--wtc-mystery-glyph`
 *     tokens (WD1 - the old hardcoded starburst blue `#4d8ddf` mascot identity is killed);
 *     the glyph itself becomes plain, token-coloured text (no more `whatsthat-mark.svg` gold-
 *     gradient asset - that asset's fill is baked-in SVG, not retintable via CSS).
 *   - retires BurstSvg/HoverBurst/useStarburstFrame entirely (owner ruling 1: "BurstSvg
 *     starburst RETIRED - the token-derived field glow replaces it; reveal reads through the
 *     mystery-card flip only"). Nothing else in the app imports these (verified via a
 *     repo-wide grep before deleting), so this is a clean removal, not a stub.
 *   - retires `wtcCardPulse`/`CardPulseWrapper` (the card-pulse-in-sync-with-the-wordmark-pop
 *     effect) alongside the wordmark's own pop-in animation it was synced to (see
 *     WhatsThatWords.tsx's own rebuild note) - ANNEX C's animation inventory lists only the
 *     mystery reveal, the confirm-lands feedback, the static reveal glow, and the static
 *     solved affordance; the card pulse isn't one of them.
 *   - `revealAnimation` (the mystery-card fade itself) is UNCHANGED verbatim, including its
 *     existing reduced-motion gate (`$playing` never flips true under reduced motion - see
 *     QuestionFeed.tsx's `onCardImageSettled`) - preserved per the spec's file-level table.
 *   - `CardPanel`/`StaticCardPanel`'s old 767.98px max-width-derived-from-vh height cap (the
 *     "portrait static top block" hack) is retired (WD4 - the page is an ordinary scrolling
 *     document now); both collapse to a plain, un-media-queried `width: 100%` box.
 */

import { keyframes } from "@emotion/react";
import styled from "@emotion/styled";

// Silhouette-reveal: the card starts as a solid "mystery" face with a "?" in the middle, then
// fades to reveal the real art. The candidate list is deliberately not rendered until this
// finishes (see `revealed` state in QuestionFeed.tsx) - the whole point is to test recognition
// before handing over the answer options. Unchanged from the pre-rebuild implementation - see
// this file's own header note.
export const revealAnimation = keyframes`
  from { opacity: 1; }
  to { opacity: 0; }
`;

export const RevealWrapper = styled.div`
  position: relative;
  overflow: hidden;
`;

// The one "mystery card" backdrop every blue/purple-tinted placeholder on the page renders -
// the large hero reveal slot (RevealWrapper) and every small candidate-grid/no-match slot
// (ArtPlaceholder) share this exact component, so there's only ever one place to retint.
// `$playing` is optional and defaults to the same "paused at the 0% frame" behaviour every
// other gated animation on this page uses - when a caller never passes it at all (every
// candidate-grid/no-match slot), `animation-play-state` falls back to `"paused"` forever, i.e.
// a permanently-static backdrop. Only the hero reveal slot (QuestionFeed.tsx) ever passes
// `$playing`/`onAnimationEnd`.
export const MysteryCardFace = styled.div<{ $playing?: boolean }>`
  position: absolute;
  inset: 0;
  background: var(--wtc-mystery-face);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  /* box-shadow, not filter/animation - a STATIC glow (ANNEX C: "no animation, so no
     reduced-motion concern"), token-derived per the spec's --wtc-reveal-glow row. */
  box-shadow: 0 0 min(24px, 16cqi) var(--wtc-reveal-glow);
  animation: ${revealAnimation} 0.8s ease-out forwards;
  animation-play-state: ${(props) => (props.$playing ? "running" : "paused")};
`;

// The "?" glyph itself - plain, token-coloured text (WD1 retires the old gold-gradient
// `whatsthat-mark.svg` mascot asset; its fill is baked into the SVG file itself and can't be
// retinted via CSS, so a real glyph asset can't carry the new `--wtc-mystery-glyph` token at
// all - a text character can). Sized via `font-size: 66.6667cqi` of MysteryCardFace's own
// width (a `container-type: inline-size` ancestor - the box this glyph sits inside is exactly
// as wide as it is tall on every mystery-card slot on the page, so `cqi` and "percent of the
// card's own height" resolve to the same visual proportion here) rather than a fixed rem/px
// value, so it scales correctly across every very-differently-sized card on the page (the
// large hero card and the small candidate tiles) without a separate size constant per surface.
function MysteryCardQuestionMark() {
  return (
    <span
      aria-hidden="true"
      data-testid="mystery-card-glyph"
      style={{
        fontSize: "66.6667cqi",
        lineHeight: 1,
        color: "var(--wtc-mystery-glyph)",
        fontWeight: 900,
      }}
    >
      ?
    </span>
  );
}

interface MysteryCardProps {
  // Hero-reveal-only (own comment on MysteryCardFace above) - every other call site omits both
  // and gets the permanently-static backdrop.
  playing?: boolean;
  onAnimationEnd?: () => void;
  "data-testid"?: string;
}

// The one composition every "mystery card" slot on the page renders - see MysteryCardFace's
// own comment for the full "one shared card, used everywhere" rationale.
export function MysteryCard({
  playing,
  onAnimationEnd,
  "data-testid": dataTestId,
}: MysteryCardProps) {
  return (
    <MysteryCardFace
      $playing={playing}
      onAnimationEnd={onAnimationEnd}
      data-testid={dataTestId}
      style={{ containerType: "inline-size" }}
    >
      <MysteryCardQuestionMark />
    </MysteryCardFace>
  );
}

// The reference card itself - normal document flow at every width now (WD4 retires the old
// 767.98px height-cap-via-max-width "portrait static top block" hack; the page is an ordinary
// scrolling document). `position: relative; z-index: 0` still establishes a local stacking
// context, harmless now that nothing negatively z-indexes into it, and kept so a future
// absolutely-positioned child (e.g. a badge overlay) has a sane containing block without a
// separate follow-up change.
export const CardPanel = styled.div`
  position: relative;
  z-index: 0;
  width: 100%;
`;

// Level 1's compact single-card confirmation screen (QuestionFeed.tsx). Same box model as
// CardPanel above now that both have dropped their old mobile-only height cap (own comment).
export const StaticCardPanel = styled.div`
  position: relative;
  z-index: 0;
  width: 100%;
`;

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

  @media (prefers-reduced-motion: reduce) {
    img {
      transition: none;
    }
    &:hover img {
      transform: none;
    }
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
// alone, so an image resolving its intrinsic size late over the network can't reflow the page.
export const CARD_ASPECT_RATIO = "63 / 88";

// Sized box for every card-art slot in the candidate grid - `<MysteryCard />` (own comment
// above) is always rendered as this box's first child at each call site (QuestionFeed.tsx),
// providing the "mystery card" backdrop + "?" glyph real artwork renders on top of (so a
// slow-loading image transitions from the mystery face into the real art instead of a blank
// flash) - and it's also the entire visual for the "No match" option, which has no real
// artwork to show at all.
export const ArtPlaceholder = styled.div`
  position: relative;
  width: 100%;
  aspect-ratio: ${CARD_ASPECT_RATIO};
  /* Deliberately no overflow: hidden here - object-fit: cover below already keeps the image
     contained within this box on its own, and clipping at this level would re-break
     ZoomableThumbnail's hover-zoom (built specifically *without* overflow: hidden so the
     enlarged art can pop out uncropped). */

  img {
    position: relative;
    z-index: 1;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
`;

// The spec's ".ctile" candidate tile (SPEC-wtc-rebuild.md section 1c "candidate tile" row) -
// `bg raised, border divider; .sel outline 2px --accent`. "highlighted" (this component's own
// className, kept unchanged at every call site) marks the suggested printing from a
// confirm_suggestion item that's been dropped to Level 2 via NOT SURE/NO - the ONLY documented
// candidate-tile highlight state in the binding token table is the outline-only ".sel" look
// (token-derived `--accent`, WD2: purple carries identity/selection), which replaces the
// pre-rebuild's solid accent-fill treatment.
export const CandidateButton = styled.button`
  position: relative;
  z-index: 0;
  display: block;
  width: 100%;
  padding: 0;
  background: var(--raised);
  border: 1px solid var(--divider);
  border-radius: var(--r-card, 8px);
  overflow: hidden;
  color: inherit;
  text-align: left;
  cursor: pointer;

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &:focus-visible {
    outline: 2px solid var(--accent, #bb9af7);
  }

  &.highlighted {
    outline: 2px solid var(--accent, #bb9af7);
    outline-offset: -1px;
    border-color: var(--accent, #bb9af7);
  }
`;

// The spec's ".ccap" candidate caption (SPEC-wtc-rebuild.md section 1c "candidate caption"
// row) - name `--text` 700, set `--muted` monospace 10px; pad 5px 7px 6px; 11px.
export const CandidateCaption = styled.div`
  padding: 5px 7px 6px;
  font-size: 11px;
  line-height: 1.25;

  .cn {
    font-weight: 700;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .cs {
    color: var(--muted);
    font-family: "Courier New", monospace;
    font-size: 10px;
  }
`;

// The spec's ".candgrid" (SPEC-wtc-rebuild.md section 1c "candidate grid" row + section 3's
// "continuous fold points" table) - an intrinsic auto-fill grid in container units, replacing
// the old `MobileCandidateScroller` horizontal-scroll wrapper (retired, WD8) with a grid that
// folds continuously (6 -> 4 -> 3 -> 2 columns) as the hero container narrows, no breakpoint.
export const CandidateGrid = styled.div`
  display: grid;
  gap: clamp(7px, 1.6cqi, 11px);
  margin-top: 4px;
  grid-template-columns: repeat(
    auto-fill,
    minmax(clamp(78px, 15cqi, 116px), 1fr)
  );
`;
