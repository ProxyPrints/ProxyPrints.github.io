/**
 * The unified "What's That Card?" question feed - replaces the old printing/artist/tag tab
 * switcher (PrintingTagQueue.tsx + GenericVoteQueue.tsx, both deleted alongside that earlier
 * change) with a single `GET 2/questionFeed/`-driven stream of one question at a time, typed
 * per cardpicker.question_feed's three-tier ranked union. See docs/features/printing-tags.md's
 * questionFeed section for the full design writeup.
 *
 * WTC REBUILD (2026-07-24, SPEC-wtc-rebuild.md, owner rulings on that spec's three open
 * questions) - this is a full visual/layout rewrite of this file's RETURN TREE. The
 * interaction contract (every function below `advance`/`selectCandidate`/`classifyAsCustomArt`/
 * `tapLevel3Chip`/`confirmLevel3`/`rejectSuggestion`/the fetch effect's per-item state reset)
 * is preserved VERBATIM - only the JSX/styling changed. See the spec's section 2
 * ("question-shape inventory") for the shape -> contract mapping and section 5 for the
 * file-level change rows this implements:
 *   - Deleted: the three styled gold/navy button overrides (ThumbButton/FilterToggleButton/
 *     ThumbChip's `QUIZ_BUTTON_GOLD`/`_HOVER`/`_NAVY` treatment - WD1, bespoke identity killed),
 *     `HeroGrid`'s 768px `grid-template-areas` swap, `MobileButtonRow`/`MobileCandidateScroller`/
 *     `MobileChipRow` + their shared `mobileScrollbarCSS`, `Level2NarrowGrid`'s narrow-only 2x2
 *     action grid + its `Narrow*Area` wrappers, `WideWordmark`/`NarrowWordmark`'s CSS-display
 *     fork, `BurstSvg`/`HoverBurst`/`useStarburstFrame` (owner ruling 1), `CardPulseWrapper`
 *     (its own sync target, the wordmark pop, is retired alongside it - ANNEX C's animation
 *     inventory doesn't list it).
 *   - Replaced by: one `@container`-driven hero (`WtcHero`/`Subject`/`QPanel`, section 3) that
 *     folds continuously via flex-wrap + `clamp()` + `auto-fill`/`auto-fit` grids - no viewport
 *     breakpoint drives ANY sizing; the one permitted viewport media query
 *     (`.wtc-head { flex-direction: column }` below 520px) is a structural header reorder only.
 *   - Added: the quiet "N tagged this session" affordance (WD6, owner ruling 2 - kept,
 *     volume-rewarding/direction-neutral, the ONLY reward surface; no streak/score/confetti)
 *     and the quiet "confirm-lands" fade (ANNEX C) shown on a successful confirm/pick while the
 *     next item is in flight.
 *   - Preserved verbatim: the candidate question's interaction contract (issue #728 removed
 *     the level1 -> level2 funnel, not the answers - see the de-laddering notes at
 *     `initialStage`'s old site, `rejectSuggestion`, and `candidateQuestionBody`),
 *     `getAutoTagChips` auto-tagging on candidate pick, the singleton-NO terminal vote,
 *     per-item state reset inside the fetch `.then()` (not a keyed `useEffect` - the
 *     stale-filter fix), the rate-limit banner, `data-card-*` attributes + the
 *     `mpc:card-selected` event (via `getPrintingCandidateDataAttributes`, unchanged), every
 *     `data-testid` this file's own Playwright/jest coverage keys off of.
 *   - Added (UX repass, 2026-08-09): #748 - a rejected Level 1 suggestion stays reachable in
 *     the Level 2 grid as a de-emphasised (`data-rejected`) re-selectable tile instead of
 *     vanishing (see gridCandidates / renderCandidateTile); #745 - illustration groups flow
 *     side-by-side via IllustrationGroupFlow; #744 - a viewport-relative min-height on WtcHero
 *     gives Subject's container-scoped sticky real scroll slack even on a short Level 1
 *     question.
 *
 * COMPOSITION PASS (2026-08-11) - the interaction contract above no longer covers
 * confirm_suggestion. Its own render now carries only the subject, the suggested printing and
 * its own answer set - no chip panel, no candidate grid, on first render.
 * `identificationBody` is the shared candidate-grid identification question (identify_printing,
 * and confirm_suggestion's own "Not this art" follow-up). The answer set changed from
 * Yes/Not sure/No to Yes / Same art, but... / Not this art / Skip (`markSameArtBut` /
 * `markNotThisArt` / `abstainAndAdvance`) - "Same art, but..." casts the suggested printing's
 * illustration vote on tap and summons a border/frame `AttributeChipPanel` follow-up
 * (`sameArtButActive`). Illustration grouping (issue #503) dropped its `>= 2` cluster rule -
 * a singleton illustration still renders as a cluster of one and still votes through
 * `selectIllustrationGroup`, never `selectCandidate`.
 */

import styled from "@emotion/styled";
import React, { useEffect, useRef, useState } from "react";
import Alert from "react-bootstrap/Alert";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getPrintingCandidateDataAttributes } from "@/common/cardDom";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { getWorkerImageURL } from "@/common/image";
import {
  PrintingCandidate,
  QuestionFeedCounts,
  QuestionFeedItem,
} from "@/common/schema_types";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { ArtistSupportLink } from "@/components/ArtistSupportLink";
import { SetIcon } from "@/components/SetIcon";
import { Spinner } from "@/components/Spinner";
import {
  AttributeChipPanel,
  initialChipStates,
} from "@/features/attributeChips/AttributeChipPanel";
import {
  ChipVoteState,
  EXCLUSION_GROUPS,
  ExclusionGroup,
  filterCandidatesByChipStates,
  getAutoTagChips,
  getOpenExclusionGroups,
} from "@/features/attributeChips/attributeChips";
import { BorderColorQuestion } from "@/features/attributeChips/BorderColorQuestion";
import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import {
  NO_MATCH_REASON_TAG_GROUPS,
  NoMatchReasonStrip,
} from "@/features/attributeVoting/NoMatchReasonStrip";
import { QueueTagQuestion } from "@/features/attributeVoting/QueueTagQuestion";
import {
  ArtPlaceholder,
  CandidateButton,
  CandidateCaption,
  CandidateGrid,
  CARD_ASPECT_RATIO,
  CardPanel,
  ILLUSTRATION_CROP_ASPECT_RATIO,
  IllustrationArtPlaceholder,
  MysteryCard,
  randomFlavorText,
  RevealWrapper,
  ZoomableThumbnail,
} from "@/features/printingTags/cardPanel";
import { IllustrationQuestion } from "@/features/questionFeed/IllustrationQuestion";
import { WhatsThatWords } from "@/features/questionFeed/WhatsThatWords";
import { recordSessionContribution } from "@/features/stats/sessionContributionSlice";
import {
  APIGetQuestionFeed,
  APISubmitIllustrationRejection,
  APISubmitIllustrationVote,
  APISubmitPrintingTag,
  APISubmitQuestionAbstention,
  APISubmitTagVote,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

type FollowUp = "none" | "no-match-reason";

// ---------------------------------------------------------------------------------------
// Layout primitives (SPEC-wtc-rebuild.md section 1c's per-element binding table + section 3's
// container-first layout spec). Every size/spacing/colour value below is copied verbatim from
// that table - see wtc-mockup.html for the same values in their original mockup-authored form.
// ---------------------------------------------------------------------------------------

const FeedRoot = styled.div``;

// wtc-head: wordmark + the quiet session-count affordance. The ONE permitted viewport
// breakpoint (section 3) - a structural reorder (wordmark above the pill on a narrow
// VIEWPORT), never a size change.
const WtcHead = styled.div`
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  max-width: 1600px;
  margin: 0 auto 12px;

  @media (max-width: 520px) {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
`;

// The quiet, non-gamified reward affordance (WD6, owner ruling 2) - a muted resolved-count,
// deliberately NOT a score/streak (no confetti, no sound, direction-neutral - see ANNEX A).
const SolvedPill = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid var(--divider);
  border-radius: var(--r-pill);
  padding: 5px 12px;
  font-size: 12px;
  color: var(--muted);

  b {
    color: var(--success);
    font-variant-numeric: tabular-nums;
  }
`;

const SolvedDots = styled.span`
  display: inline-flex;
  gap: 3px;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--divider);
    display: inline-block;

    &.f {
      background: var(--success);
    }
  }
`;

// The one hero container (section 3) - `container-type: inline-size` so every descendant
// below folds against ITS OWN rendered width, not the viewport. `Subject`/`QPanel` wrap
// intrinsically via flex-basis; no media query drives the subject<->question column split.
const WtcHero = styled.div`
  container-type: inline-size;
  container-name: hero;
  max-width: 1600px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: clamp(12px, 2.2cqi, 22px);
  align-items: start;
  /* Issue #744 - scroll slack for Subject's 'position: sticky'. Sticky can only visibly pin
     while its containing block (this hero) has vertical travel room beyond the subject's own
     height; a Level 1 question with a short QPanel column (a singleton suggestion, or few
     candidates) used to collapse the hero to ~the subject's own height, leaving ~12px of
     slack, so the pinned reference card scrolled off 1:1 with the page. A viewport-relative
     min-height (SIZING, not positioning - A2's container-scoped sticky policy is untouched)
     guarantees the hero spans roughly the first fold of the scroll container even when the
     question is short, which is exactly the travel room sticky needs. */
  min-height: calc(100dvh - 132px);
`;

// Reference-card visibility (issue #710, A2 amendment) - pinned WITHIN the hero container via
// `position: sticky`, not the page viewport (WD4's rejection of viewport-COUPLED positioning
// stands; this is scoped to WtcHero's own box, since a flex item's sticky containing block is
// its flex container - it stays pinned only as long as WtcHero itself, whose height spans the
// taller QPanel column too, hasn't scrolled past). Applies unconditionally at every hero
// width, including the WD3-compacted horizontal strip below the 560px fold - there is no
// separate mobile-only rule to keep the "always visible" guarantee genuinely universal.
const Subject = styled.div`
  flex: 1 1 300px;
  min-width: 0;
  max-width: clamp(240px, 30cqi, 340px);
  position: sticky;
  top: 16px;
  z-index: 1;

  /* Continuous fold point (section 3's table): the subject compacts to horizontal (WD3) on a
     narrow CONTAINER, not a narrow viewport - keeps the confirm hero reachable near the top
     on a phone with no bounded-height hack (WD4). */
  @container hero (max-width: 560px) {
    flex: 1 1 100%;
    max-width: none;
  }
`;

const QPanel = styled.div`
  flex: 2.2 1 440px;
  min-width: 0;
`;

const SubjectCardBox = styled.div`
  background: var(--raised);
  border: 1px solid var(--divider);
  border-radius: var(--r-card);
  overflow: hidden;

  @container hero (max-width: 560px) {
    display: flex;
    align-items: stretch;
  }
`;

// Issue #741 - the art frame and the title bar are now two stacked boxes rather than one
// box with the title absolutely positioned over the art's own bottom edge (SubjectArtImage
// owns the sizing/aspect-ratio, SubjectArtTitle is a normal-flow sibling below it), so the
// title can never cover the artwork it labels. SubjectArt itself is just the flex column
// that holds both - at the hero's compact fold it becomes the 132px-wide row item WD3
// specifies, stretched to the row's height by SubjectCardBox's `align-items: stretch`.
const SubjectArt = styled.div`
  position: relative;

  @container hero (max-width: 560px) {
    display: flex;
    flex-direction: column;
    flex: 0 0 132px;
    width: 132px;
  }
`;

// DESIGN-REPASS Rule 3 (#746) - `$landscape` is set only by the artist-question subject slot,
// whose image is the harvested Scryfall illustration crop (a landscape 584/444 region, not a
// card scan). Rendering it in the portrait card frame cropped its top and bottom off inside a
// box sized for a card; the landscape frame is the same ratio the illustration-group candidate
// tiles already use, so the same artwork reads at the same proportions wherever it appears.
const SubjectArtImage = styled.div<{ $landscape?: boolean }>`
  position: relative;
  aspect-ratio: ${(props) =>
    props.$landscape ? ILLUSTRATION_CROP_ASPECT_RATIO : CARD_ASPECT_RATIO};

  @container hero (max-width: 560px) {
    flex: 1;
    aspect-ratio: auto;
  }
`;

const SubjectArtTitle = styled.div`
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  font-weight: 700;
  font-size: clamp(13px, 3.4cqi, 17px);
  padding: 6px 10px;
`;

const SubjectCap = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  font-size: 12px;
  color: var(--muted);
  border-top: 1px solid var(--divider);
  background: var(--conf);

  .glyph {
    width: 18px;
    height: 18px;
    flex: 0 0 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent);
    font-weight: 900;
  }

  @container hero (max-width: 560px) {
    flex: 1;
    border-top: none;
    border-left: 1px solid var(--divider);
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 4px;
  }
`;

const QHead = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 2px 0 12px;
`;

const Prompt = styled.p`
  font-size: clamp(17px, 3.4cqi, 22px);
  font-weight: 800;
  color: var(--text);
  margin: 0;
`;

const ShapePill = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 3px 10px;
  border-radius: var(--r-pill);

  &.easy {
    color: var(--btn-ink);
    background: var(--success);
  }

  &.pick {
    color: var(--btn-ink);
    background: var(--accent);
  }

  &.neg {
    color: var(--btn-ink);
    background: var(--danger);
  }

  &.hard {
    color: var(--accent);
    background: transparent;
    border: 1px dashed var(--accent);
  }
`;

const QHint = styled.p`
  font-size: 13px;
  color: var(--muted);
  margin: -6px 0 12px;
`;

// Issue #745 - the wrapper that makes multiple illustration groups flow side-by-side (the way
// `CandidateGrid`'s own tiles do) instead of each group stacking as its own block row down the
// page. Each group (representative tile + label + credit) is one grid item; auto-fill keeps
// every group in a single column on a narrow container and lets several sit alongside each
// other when the question panel has the width. `align-items: start` so a taller group never
// stretches its shorter neighbours.
const IllustrationGroupFlow = styled.div`
  display: grid;
  grid-template-columns: repeat(
    auto-fill,
    minmax(clamp(150px, 26cqi, 240px), 1fr)
  );
  gap: clamp(12px, 2.4cqi, 20px);
  align-items: start;
  margin-bottom: 6px;
`;

// Issue #503 (WTC phase C1) - a small labelled cluster around one `CandidateGrid` (imported,
// unmodified) per shared Scryfall illustration, so candidates that are visually near-identical
// group together instead of forcing a guess across a flat grid. Deliberately reuses
// `CandidateGrid`'s own grid/gap/columns rather than a new grid primitive - this is a
// regrouping of the same tiles, not a new component family. Inside IllustrationGroupFlow the
// group is purely its own box (label + credit + the representative tile) - spacing between
// groups comes from the wrapper's grid gap, so this carries no margin of its own.
const IllustrationGroup = styled.div`
  min-width: 0;
`;

const IllustrationGroupLabel = styled.p`
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 4px;
`;

// Caps the width of the reused ArtistSupportLink applet so a full-bleed button (its own
// "stretch to fill" rule - see the component's docstring, not overridden here) reads as a
// compact cluster credit rather than a page-width CTA repeated once per cluster.
// DESIGN-REPASS Rule 6 (#711-adjacent MTGAC work) - the ArtistSupportLink applet renders in two
// places on this surface (under an illustration cluster's credit, and under the artist
// question's post-answer moment) and must look the same in both. The illustration credit
// always capped it at 220px; the post-answer banner had no cap and let the collapsed row's
// primary link stretch to the full question-panel width. One shared cap makes the two renders
// identical instead of one tidy 220px line and one full-width button.
const ArtistCredit = styled.div`
  max-width: 220px;
`;

const IllustrationCredit = styled(ArtistCredit)`
  margin-bottom: 8px;
`;

// Issue #707 - the attribute-chip panel's home now that it no longer replaces the subject
// card slot (see plainCardPanel's own comment). Framed like the page's other secondary
// panels (SuggestedCard/NegWrap/OpenWrap) rather than left bare, so it reads as a distinct,
// dismissible section of QPanel instead of loose content between the prompt and the grid.
// Compact (2026-08-10): the chips inside are a tight flowing multi-line list, so this wrapper
// stays visually quiet.
const FilterPanelWrap = styled.div`
  background: var(--conf);
  border: 1px solid var(--divider);
  border-radius: var(--r-card);
  padding: 8px 10px;
  margin: 8px 0;
`;

// The spec's `.btn` base + variants (section 1c) - min 44px thumb targets (mobile funnel
// pass, WCAG 2.5.5/Apple HIG), replacing the old `ThumbButton`/`FilterToggleButton` gold
// overrides with plain token-derived variants. A native <button>, not a react-bootstrap
// `Button` wrapper - none of Bootstrap's own variant machinery is needed once every colour
// here comes from a token instead of a Bootstrap `$theme-colors` entry.
const Btn = styled.button`
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  padding: 6px 16px;
  border-radius: var(--r-btn);
  border: 1px solid transparent;
  cursor: pointer;
  line-height: 1.2;
  text-align: center;
  /* DESIGN-REPASS Rule 2 (#715) - opt out of the mobile double-tap-zoom gesture, which
     otherwise swallows a fast single tap and reads as "this button needs two taps". */
  touch-action: manipulation;

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &.block {
    width: 100%;
  }

  &.primary {
    background: var(--primary);
    color: var(--btn-ink);
    border-color: var(--primary);
  }

  &.secondary {
    background: var(--raised);
    color: var(--text);
    border-color: var(--divider);
  }

  &.accent {
    background: var(--accent);
    color: var(--btn-ink);
    border-color: var(--accent);
    font-weight: 800;
  }

  &.ghost {
    background: transparent;
    color: var(--muted);
    border-color: transparent;
  }

  &.danger {
    background: transparent;
    color: var(--danger);
    border-color: var(--danger);
  }
`;

// Action rows fold intrinsically (auto-fit), replacing the old MobileButtonRow/
// MobileChipRow horizontal scrollers (WD8) - never a scroller, always a wrap/grid.
const ActionStack = styled.div`
  display: flex;
  flex-direction: column;
  gap: 9px;
  margin-top: 4px;

  /* Issue #740 - dropping .block from the Yes button (this stack's first child) only sizes
     it to its content if it also opts out of the flex column's default align-items: stretch;
     ActionGrid (the second child) keeps stretching, since its own grid needs the full row
     width to lay out its three siblings. */
  > button:first-child {
    align-self: flex-start;
  }
`;

const ActionGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(
    auto-fit,
    minmax(clamp(120px, 34cqi, 180px), 1fr)
  );
  gap: 9px;
  margin-top: 10px;

  /* Continuous fold point (section 3's table): stacks to one column on a truly tiny
     container, never a viewport breakpoint. */
  @container hero (max-width: 380px) {
    grid-template-columns: 1fr;
  }
`;

const ActionRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 10px;
`;

// Shape (a) - the 1-click confirm hero.
const SuggestedCard = styled.div`
  display: flex;
  gap: 13px;
  align-items: stretch;
  background: var(--conf);
  border: 1px solid var(--divider);
  border-radius: var(--r-card);
  padding: 11px;
`;

const SuggestedThumb = styled.div`
  flex: 0 0 clamp(70px, 20cqi, 104px);
  width: clamp(70px, 20cqi, 104px);
  aspect-ratio: ${CARD_ASPECT_RATIO};
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--divider);
  position: relative;

  /* Issue #705 - clips the resting thumbnail to its rounded frame as before, but stops
     clipping for exactly as long as the pointer is over it, which is also exactly when
     ZoomableThumbnail's own hover rule (cardPanel.tsx) scales its <img> up - letting the
     zoomed art escape uncropped instead of being cut flush at this box's edge. */
  &:hover {
    overflow: visible;
  }
`;

const SuggestedMeta = styled.div`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
`;

const SuggestedName = styled.span`
  font-size: clamp(16px, 3.2cqi, 19px);
  font-weight: 800;
  color: var(--text);
`;

const SuggestedSet = styled.span`
  font-size: 13px;
  color: var(--muted);
  font-family: "Courier New", monospace;
`;

const ConfidencePill = styled.span`
  align-self: flex-start;
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: var(--r-pill);
  padding: 2px 9px;

  i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    display: inline-block;
  }
`;

const ExactWord = styled.span`
  text-decoration: underline;
  text-underline-offset: 2px;
`;

// Confirm-lands micro-feedback (ANNEX C) - a brief fade-in on a successful cast, instant under
// reduced motion (no transition at all, per the media query below), then advance. Quiet by
// design (WD6): success-tinted pill, no motion beyond the fade, no sound, no confetti.
const LandedFeedback = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--success);
  background: color-mix(in srgb, var(--success) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--success) 45%, transparent);
  border-radius: var(--r-pill);
  padding: 5px 12px;
  animation: wtc-landed-fade-in 0.2s ease-out;

  @keyframes wtc-landed-fade-in {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

// Shape (c) - quick-negative, danger-framed (WD7: visually distinct so reflex-tapping the
// confirm shape doesn't bleed into this one).
const NegWrap = styled.div`
  border: 1px solid var(--danger);
  border-radius: var(--r-card);
  background: color-mix(in srgb, var(--danger) 8%, var(--conf));
  padding: 13px;
`;

// Shape (d) - open-ended, dashed accent "tricky one" (WD7). No new search endpoint exists on
// the backend (API surface unchanged, per this task's own critical constraint) - this frames
// the SAME Level 2 candidate-grid/"None of these"/Skip flow the app already has for a
// zero-candidate `identify_printing` item, rather than a speculative search field wired to
// nothing. See this PR's report for the "no invented backend surface" reasoning.
const OpenWrap = styled.div`
  border: 1px dashed var(--accent);
  border-radius: var(--r-card);
  background: color-mix(in srgb, var(--accent) 6%, var(--conf));
  padding: 14px;
`;

// Level 3 - exclusion-group chips + independent toggles.
const GroupLabel = styled.div`
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin: 12px 0 5px;
  font-weight: 700;
`;

const TriStateChipRow = styled.div`
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
`;

const TriStateChip = styled.button`
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  background: transparent;
  color: var(--text);
  border: 1px solid var(--muted);
  border-radius: var(--r-btn);
  touch-action: manipulation;

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &.pos {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 20%, transparent);
    color: var(--accent);
  }
`;

// The pre-existing "N ready / N in catalog / N contested" info line - unrelated to the
// SolvedPill session counter above. Kept at the bottom of the questions column, always
// visible now (container-first policy retires the old viewport-hide-below-md rule this used
// to carry).
const StatsLine = styled.p`
  color: var(--muted);
  font-size: 12px;
  margin: 12px 0 0;
`;

// Frontend and backend deploy independently (GitHub Pages vs. a separate Django API) - there's
// a real window where this frontend build can be live against a not-yet-deployed backend still
// returning the old `remainingEstimate: number` shape. TypeScript's `as QuestionFeedResponse`
// cast in api.ts can't catch that at runtime, so `counts` here is trusted-but-unverified -
// without this guard, `counts.confirmable`/`counts.total` on a raw number both resolve to
// `undefined`, rendering the literal string "undefined cards" instead of degrading gracefully.
function normalizeQuestionFeedCounts(
  raw: QuestionFeedCounts | number | null | undefined
): QuestionFeedCounts | null {
  if (raw == null) {
    return null;
  }
  if (typeof raw === "number") {
    // legacy shape - no tier breakdown available, so confirmable/contested fall back to 0
    // (never show a false "N ready" count in the stats line below) and fresh mirrors total.
    return { total: raw, confirmable: 0, contested: 0, fresh: raw };
  }
  // `total === fresh` is expected for the legacy number shape above (fresh is forced to mirror
  // total there), but for a genuine object-shaped response it would mean every card in the
  // catalog is still "fresh" - vanishingly unlikely in practice, and far more likely a sign that
  // this build is talking to a backend that hasn't finished rolling out the fresh/total split.
  // Never shown to the user (the stats line below never renders `fresh` at all) - this is
  // purely a version-skew signal for whoever reads the console.
  if (raw.total === raw.fresh) {
    console.warn(
      "QuestionFeed: counts.total === counts.fresh on a non-legacy response - possible backend/frontend version skew."
    );
  }
  return raw;
}

export function QuestionFeed() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [item, setItem] = useState<QuestionFeedItem | null>(null);
  const [counts, setCounts] = useState<QuestionFeedCounts | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [caughtUp, setCaughtUp] = useState<boolean>(false);
  const [fetchError, setFetchError] = useState<boolean>(false);
  const [flavorText, setFlavorText] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<boolean>(false);
  // Fix round (owner blocker, "the pulse doesn't sync with the pop") - the reveal fade used to
  // fire the moment its element mounted, with no regard for whether the subject card's own
  // <img> had actually finished loading - on a slow connection this could reveal a still-
  // loading or half-painted image. `imageLoaded`/`imageErrored` below, together with
  // `cardImageRef`'s mount-time `.complete` check, gate the reveal (via MysteryCardFace's own
  // `$playing` prop, cardPanel.tsx) on one single real load-complete moment.
  const [imageLoaded, setImageLoaded] = useState<boolean>(false);
  // A failed load never gets a legitimate "reveal" moment to sync to - the cover stays up
  // permanently (below) with no animation at all. See onCardImageSettled below for how
  // `revealed` still unblocks the rest of the question UI regardless, so a failed image can't
  // strand the user on an infinite spinner.
  const [imageErrored, setImageErrored] = useState<boolean>(false);
  // Bumped unconditionally alongside the reset above, on EVERY fetch resolution - not just
  // ones that land on a genuinely different card. See the fetch effect's own comment.
  const [imageGeneration, setImageGeneration] = useState<number>(0);
  const cardImageRef = useRef<HTMLImageElement>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  // DESIGN-REPASS Rule 2 (#715) - `disabled={submitting}` only takes effect on the re-render
  // React batches AFTER the current event handler returns, so two taps inside that window (a
  // double-click, or a stray second tap on a tile) both re-enter the vote handler and cast the
  // vote twice. This ref is set synchronously at handler entry and read at the top of every
  // handler, closing the window - the second entry is dropped, not queued - while the state
  // flag keeps driving the disabled/visual state. Advance-only handlers (skip, Not sure) hold
  // it until the next item lands (the fetch effect clears it) so a double-tap can't skip two
  // cards; vote handlers release it in their own `.finally` (a Level 3 transition must re-enable
  // the chips immediately).
  const voteInFlightRef = useRef<boolean>(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null
  );
  const [chipStates, setChipStates] = useState<Record<string, ChipVoteState>>(
    initialChipStates()
  );
  const [followUp, setFollowUp] = useState<FollowUp>("none");
  // The one candidate the user has explicitly said NO to within THIS item's flow (issue #728:
  // with the ladder gone this can only ever be the suggested candidate - the only candidate
  // rejected by name; "Not sure" is genuine uncertainty, not a rejection, and deliberately
  // never adds here). Drives the suggestion slot's "you said not this one" collapse - reset on
  // every new item below.
  const [rejectedCandidateIds, setRejectedCandidateIds] = useState<Set<string>>(
    new Set()
  );
  const [fetchToken, setFetchToken] = useState<number>(0);
  // Artist Support Links v1 - set once the user casts a real (non-"Unknown") artist vote on an
  // "artist"-type item, via ArtistVotePicker's onArtistConfirmed below. Drives the post-answer
  // ArtistSupportLink banner - reset on every new item alongside the other per-question state,
  // so it can't bleed into the next question.
  const [confirmedArtistName, setConfirmedArtistName] = useState<string | null>(
    null
  );
  // A 429 from any vote-casting call below (printing, tag, artist) sets this instead of firing
  // the usual error toast - see the banner rendered near the top of the item below. In a
  // one-tap funnel, a rate-limit pause is an expected, honest condition, not a failure, so it
  // gets a persistent inline notice rather than a transient, alarm-toned toast.
  const [rateLimited, setRateLimited] = useState<boolean>(false);

  // The de-laddered feed (issue #728) has no fixed level1 -> level2 -> level3 sequence. The
  // only remaining "stage" is the data-driven post-selection attribute confirmation (formerly
  // Level 3), entered solely when a selected candidate leaves an exclusion group open - never
  // a fixed-sequence step.
  const [level3Active, setLevel3Active] = useState<boolean>(false);
  // "Same art, but..." (confirm_suggestion only) - set once the illustration vote for the
  // suggested printing has been cast on tap, which summons the border/frame chip follow-up in
  // place of the suggestion slot. Reset alongside every other per-item flag in the fetch
  // effect below.
  const [sameArtButActive, setSameArtButActive] = useState<boolean>(false);
  // Collapsed by default (decision: chip-as-filter survives on the candidate grid, but
  // off-path for the common case). Selecting a candidate below ignores this entirely; it only
  // ever narrows which tiles are shown.
  const [filterExpanded, setFilterExpanded] = useState<boolean>(false);
  // Level 3 only ever asks about groups an already-selected candidate left open - keyed by
  // tagName, but only ever contains chips from getOpenExclusionGroups(pendingCandidate).
  const [level3ChipStates, setLevel3ChipStates] = useState<
    Record<string, ChipVoteState>
  >({});
  // WTC rebuild (WD6, owner ruling 2) - the quiet "N tagged this session" affordance, the ONLY
  // reward surface (no streak/score/confetti - ANNEX A's soundness note). Plain component
  // state, not localStorage - it's explicitly "this session" (resets on a real page reload,
  // same as every other piece of in-flight feed state here), never meant to survive a "clear
  // site data" test the way persisted state would need to.
  const [sessionTaggedCount, setSessionTaggedCount] = useState<number>(0);
  const bumpSessionCount = () => {
    setSessionTaggedCount((previous) => previous + 1);
    // 2026-07-29 directive item 4 - the homepage's dashed "you would be the Nth" dot turns into
    // a filled, green thank-you once THIS client has cast a vote. This is the single place every
    // successful vote in this feed already funnels through, so it's also the single place that
    // in-session fact gets recorded - see sessionContributionSlice.ts's own module comment for
    // why this is a Redux dispatch (not localStorage, not a new endpoint).
    dispatch(recordSessionContribution());
  };
  // ANNEX C's "confirm-lands" micro-feedback - a brief fade-in on a successful cast, shown
  // while the next item's fetch is already in flight (advance() below never adds an artificial
  // delay of its own - the interaction contract's "advance immediately" behavior is unchanged;
  // this just fills the pre-existing async gap between vote success and the next item's fetch
  // resolving with a quiet success pill instead of nothing). Reset alongside every other
  // per-item flag in the fetch effect.
  const [landed, setLanded] = useState<boolean>(false);

  const fetchNext = () => setFetchToken((previous) => previous + 1);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    setFetchError(false);
    APIGetQuestionFeed(backendURL, getOrCreateAnonymousId())
      .then((response) => {
        const newItem = response.item ?? null;
        setItem(newItem);
        setCounts(normalizeQuestionFeedCounts(response.remainingEstimate));
        setCaughtUp(newItem == null);
        // Reset per-question local state in the SAME update as the new item, rather than a
        // separate effect keyed on item?.card.identifier/type. Two consecutive feed items can
        // legitimately share both (e.g. the same card can carry more than one pending question
        // type, or the same question can be re-served) - a dependency-array-keyed effect skips
        // the reset entirely when neither value changes, silently carrying stale chipStates
        // (and revealed/selectedCandidateId/etc) over from the previous card. Resetting here
        // instead makes the reset unconditional on every new item, with no dependency array to
        // miss.
        setRevealed(false);
        setImageLoaded(false);
        setImageErrored(false);
        setImageGeneration((previous) => previous + 1);
        // A new item has landed (or the feed is empty) - release any advance-only in-flight
        // ref (skip / Not sure) so the next question's controls are live immediately.
        voteInFlightRef.current = false;
        // A synchronous throw inside a vote handler strands submitting true; a landed
        // question must always start with both flags live so no button is silently disabled.
        setSubmitting(false);
        // A genuinely empty configured URL (this test suite's own fixture convention - real
        // cards always carry a real CDN URL) has nothing to load at all, so it's settled right
        // here rather than waiting on any image event.
        if (newItem != null && newItem.card.mediumThumbnailUrl === "") {
          onCardImageSettled(false);
        }
        setChipStates(initialChipStates());
        setFollowUp("none");
        setRejectedCandidateIds(new Set());
        setSelectedCandidateId(null);
        setConfirmedArtistName(null);
        setRateLimited(false);
        // Issue #707 / A4 amendment - shown automatically for identify_printing's shortlist,
        // where the attribute chips actually narrow something on first render. confirm_suggestion
        // never auto-shows this: its own question renders the subject, suggested printing and
        // answer set only - nothing summons the chip panel until "Same art, but..." is tapped,
        // which has its own dedicated render below rather than reusing this flag.
        setFilterExpanded(
          newItem != null && newItem.type === "identify_printing"
        );
        setLevel3ChipStates({});
        setLanded(false);
        // The only remaining "stage" (issue #728) is the post-selection attribute
        // confirmation - every new item starts outside it.
        setLevel3Active(false);
        setSameArtButActive(false);
      })
      .catch(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
        setItem(null);
        setFetchError(true);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, fetchToken]);

  // The one moment the mystery-card reveal fade is anchored to. Two cases skip the animated
  // queue entirely and jump straight to `revealed`: reduced motion (nothing should ever
  // visibly fade, so there's no animationend event to wait for) and a failed load (no
  // legitimate image to reveal).
  const onCardImageSettled = (errored: boolean) => {
    setImageLoaded(true);
    if (errored) {
      setImageErrored(true);
    }
    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
    if (errored || reducedMotion) {
      setRevealed(true);
    }
  };

  // Catches a genuinely cached REAL image - the browser sometimes never fires onLoad for a
  // cache hit. Checks `naturalWidth > 0`, not just `.complete` - `.complete` alone is `true`
  // for a FAILED load too. Deliberately keyed on `imageGeneration`, NOT
  // `item?.card.identifier` - see the fetch handler's own comment on why.
  useEffect(() => {
    if (
      cardImageRef.current != null &&
      cardImageRef.current.complete &&
      cardImageRef.current.naturalWidth > 0
    ) {
      onCardImageSettled(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageGeneration]);

  const advance = () => {
    setFlavorText(randomFlavorText());
    fetchNext();
  };

  const reportVoteFailed = (error: unknown) => {
    if (isRateLimited(error)) {
      setRateLimited(true);
      return;
    }
    dispatch(
      setNotification([
        Math.random().toString(),
        errorToNotification(error, {
          name: "Vote failed",
          message:
            "Something went wrong submitting your vote - please try again.",
        }),
      ])
    );
  };

  // Selecting a candidate casts the printing vote plus one positive CardTagVote per attribute
  // the candidate itself carries true - standalone booleans and whichever exclusion-group chip
  // actually matches (see attributeChips.ts's getAutoTagChips). If that leaves a group
  // genuinely undecided (getOpenExclusionGroups), Level 3 renders to ask just about that;
  // otherwise the feed advances straight to the next card.
  const selectCandidate = (
    candidate: PrintingCandidate | undefined,
    isNoMatch: boolean
  ) => {
    if (backendURL == null || item == null || voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    setSubmitting(true);
    setSelectedCandidateId(candidate?.identifier ?? "no-match");
    const anonymousId = getOrCreateAnonymousId();
    APISubmitPrintingTag(
      backendURL,
      item.card.identifier,
      anonymousId,
      candidate?.identifier,
      isNoMatch,
      "question-feed"
    )
      .then(() => {
        bumpSessionCount();
        if (candidate != null) {
          const autoTagChips = getAutoTagChips(candidate);
          Promise.all(
            autoTagChips.map((chip) =>
              APISubmitTagVote(
                backendURL,
                item.card.identifier,
                anonymousId,
                chip.tagName,
                1,
                "same-origin",
                "question-feed"
              )
            )
          ).catch(() => undefined); // best-effort - a failed auto-tag shouldn't block advancing
        }
        if (isNoMatch) {
          setFollowUp("no-match-reason");
        } else if (candidate != null) {
          const openGroups = getOpenExclusionGroups(candidate);
          if (openGroups.length > 0) {
            setLevel3ChipStates(
              Object.fromEntries(
                openGroups.flatMap((group) =>
                  group.chips.map((chip) => [chip.tagName, "untouched"])
                )
              )
            );
            setLevel3Active(true);
          } else {
            setLanded(true);
            advance();
          }
        } else {
          advance();
        }
      })
      .catch(reportVoteFailed)
      .finally(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
        setSelectedCandidateId(null);
      });
  };

  // Issue #503 (WTC phase C2) / #524 - tapping a tile inside an illustration-grouped cluster
  // (illustrationGroups below, always >=2 members - a singleton never forms a visible cluster,
  // see that constant's own comment) submits ONE illustrationId through /2/submitIllustrationVote/,
  // never a printing list: the browser's own candidate payload is a snapshot and cannot be
  // trusted to know whether the group is still >1 printing by the time this fires (reference
  // data can move between render and tap) - that check is server-side, against live data, at
  // write time (see illustration_vote.py). The backend derives up to two further votes
  // (a printing vote at a live 1:1 match, a artist vote when absent) in the same transaction, so
  // - unlike selectCandidate - this never knows which single printing (if any) was actually
  // voted for, and therefore skips the auto-tag-chip / Level 3 attribute-exclusion flow (both
  // require knowing the specific printing's own attributes) and goes straight to advancing.
  const selectIllustrationGroup = (
    illustrationId: string,
    tappedCandidate: PrintingCandidate
  ) => {
    if (backendURL == null || item == null || voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    setSubmitting(true);
    setSelectedCandidateId(tappedCandidate.identifier);
    const anonymousId = getOrCreateAnonymousId();
    APISubmitIllustrationVote(
      backendURL,
      item.card.identifier,
      anonymousId,
      illustrationId,
      false,
      "question-feed"
    )
      .then(() => {
        bumpSessionCount();
        setLanded(true);
        advance();
      })
      .catch(reportVoteFailed)
      .finally(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
        setSelectedCandidateId(null);
      });
  };

  // The pre-classified exit for "this is real art, just not an official printing" - one tap
  // instead of "None of these" -> the reason strip, since the tap already told us why (see
  // reason_tags.py's existing seeded "custom-art" tag - no new endpoint).
  const classifyAsCustomArt = () => {
    if (backendURL == null || item == null || voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    setSubmitting(true);
    setSelectedCandidateId("custom-art");
    const anonymousId = getOrCreateAnonymousId();
    APISubmitPrintingTag(
      backendURL,
      item.card.identifier,
      anonymousId,
      undefined,
      true,
      "question-feed"
    )
      .then(() => {
        bumpSessionCount();
        APISubmitTagVote(
          backendURL,
          item.card.identifier,
          anonymousId,
          "custom-art",
          1,
          "same-origin",
          "question-feed"
        ).catch(() => undefined);
        fetchNext();
      })
      .catch(reportVoteFailed)
      .finally(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
        setSelectedCandidateId(null);
      });
  };

  // Real single-select lock (decision: scoped to Level 3 only) - picking one option in a group
  // resets any other member of the same group back to untouched, unlike the funnel's usual
  // independent tri-state cycling that Level 2's optional filter panel keeps.
  const tapLevel3Chip = (group: ExclusionGroup, tagName: string) => {
    // Issue #715 - chips stay inert while a Level 3 submission is in flight; the visual
    // `disabled={submitting}` only applies on the post-render, so the ref closes the window.
    if (voteInFlightRef.current) {
      return;
    }
    setLevel3ChipStates((previous) => {
      const next = { ...previous };
      group.chips.forEach((chip) => {
        next[chip.tagName] = "untouched";
      });
      next[tagName] =
        previous[tagName] === "positive" ? "untouched" : "positive";
      return next;
    });
  };

  const confirmLevel3 = () => {
    if (voteInFlightRef.current) {
      return;
    }
    if (backendURL == null || item == null) {
      advance();
      return;
    }
    const anonymousId = getOrCreateAnonymousId();
    const picked = Object.entries(level3ChipStates).filter(
      ([, state]) => state === "positive"
    );
    if (picked.length === 0) {
      advance();
      return;
    }
    voteInFlightRef.current = true;
    setSubmitting(true);
    Promise.all(
      picked.map(([tagName]) =>
        APISubmitTagVote(
          backendURL,
          item.card.identifier,
          anonymousId,
          tagName,
          1,
          "same-origin",
          "question-feed"
        )
      )
    )
      .then(() => {
        bumpSessionCount();
        advance();
      })
      .catch(reportVoteFailed)
      .finally(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
      });
  };

  // Advance-only handlers hold the in-flight ref until the next item lands (the fetch effect
  // clears it) - a double-tap on Skip / Not sure must not advance two cards at once.
  const skip = () => {
    if (voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    advance();
  };

  // Records an abstention (issue #712) and moves on - fire-and-forget, same best-effort
  // convention as the auto-tag-chip casts in selectCandidate above: the write is informative,
  // not gating, so a failed request never blocks the transition. Used by confirm_suggestion's
  // own Skip answer, which - unlike a bare advance - must leave a distinguishable trace that
  // this question was seen and abstained on rather than never served.
  const abstainAndAdvance = (reason?: string) => {
    if (voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    if (backendURL != null && item != null) {
      APISubmitQuestionAbstention(
        backendURL,
        item.card.identifier,
        getOrCreateAnonymousId(),
        item.type,
        reason
      ).catch(() => undefined);
    }
    advance();
  };

  // confirm_suggestion's "Not this art" answer. Two things happen on tap.
  //
  // 1. A negative ILLUSTRATION signal is recorded when the suggested printing carries an
  //    illustrationId: a fire-and-forget POST to /2/submitIllustrationRejection/
  //    (`APISubmitIllustrationRejection` -> `CardIllustrationRejection` - see
  //    docs/features/wtc-question-model.md §7.1 and printing-tags.md's illustration-elimination
  //    section for the mechanism). Best-effort, same convention as `abstainAndAdvance`'s
  //    abstention write. This is the write path #770's comment below could not name - it was
  //    landed by the same series that introduced the answer set, closing the loop so a
  //    rejected suggestion is not re-served to a different voter as if it were new
  //    (`question_feed._confirm_suggestion_item` consumes the resulting elimination consensus).
  // 2. The client-side collapse #770 describes: the suggestion slot gives way to the
  //    candidate-grid identification question on the SAME page, carrying the #748
  //    re-selectable-tile mechanic (the rejected printing stays reachable, not the terminal
  //    isNoMatch vote a truly-empty grid used to force here - "wrong artwork entirely" and
  //    "no official printing at all" are different claims, and only the latter has a vote to cast).
  const markNotThisArt = () => {
    if (item?.suggestedPrinting == null || voteInFlightRef.current) {
      return;
    }
    const illustrationId = item.suggestedPrinting.illustrationId;
    if (backendURL != null && illustrationId != null) {
      APISubmitIllustrationRejection(
        backendURL,
        item.card.identifier,
        getOrCreateAnonymousId(),
        illustrationId
      ).catch(() => undefined);
    }
    const rejectedIdentifier = item.suggestedPrinting.identifier;
    setRejectedCandidateIds((previous) =>
      new Set(previous).add(rejectedIdentifier)
    );
  };

  // confirm_suggestion's "Same art, but..." answer - casts the illustration vote for the
  // suggested printing's own illustration the moment this is tapped, true regardless of
  // whether the border/frame follow-up below is ever completed, then summons that follow-up.
  // Falls straight through to the follow-up with no cast when the suggested printing carries
  // no illustrationId - best-effort, same convention as the auto-tag-chip casts above.
  const markSameArtBut = () => {
    if (
      backendURL == null ||
      item?.suggestedPrinting == null ||
      voteInFlightRef.current
    ) {
      return;
    }
    const illustrationId = item.suggestedPrinting.illustrationId;
    if (illustrationId == null) {
      setSameArtButActive(true);
      return;
    }
    voteInFlightRef.current = true;
    setSubmitting(true);
    APISubmitIllustrationVote(
      backendURL,
      item.card.identifier,
      getOrCreateAnonymousId(),
      illustrationId,
      false,
      "question-feed"
    )
      .then(() => {
        bumpSessionCount();
        setSameArtButActive(true);
      })
      .catch(reportVoteFailed)
      .finally(() => {
        voteInFlightRef.current = false;
        setSubmitting(false);
      });
  };

  // Leaves the border/frame follow-up (any chip taps already cast their own votes as they
  // happened - see useTagVoting) and advances - guarded the same way as skip() above so a
  // double-tap can't advance two cards.
  const finishSameArtBut = () => {
    if (voteInFlightRef.current) {
      return;
    }
    voteInFlightRef.current = true;
    advance();
  };

  if (loading && item == null) {
    return (
      <div className="text-center py-4" data-testid="question-feed-loading">
        <Spinner size={2} />
      </div>
    );
  }

  // A fetch failure (backend outage, network error) is distinct from a genuine "no cards
  // left" empty state - the old code treated both identically, so an outage looked exactly
  // like being caught up and a user could walk away thinking they'd finished the queue.
  if (fetchError) {
    return (
      <div data-testid="question-feed-error">
        <p className="text-danger">
          Something went wrong loading the next question.
        </p>
        <Btn
          className="secondary"
          onClick={fetchNext}
          data-testid="question-feed-retry"
        >
          Try again
        </Btn>
      </div>
    );
  }

  if (caughtUp || item == null || backendURL == null) {
    return (
      <div data-testid="question-feed-empty">
        <p className="text-primary">
          You&apos;re all caught up - no cards left to work on right now!
        </p>
        {flavorText != null && (
          <p className="text-muted" data-testid="question-feed-flavor-text">
            {flavorText}
          </p>
        )}
      </div>
    );
  }

  const isCandidateType =
    item.type === "confirm_suggestion" || item.type === "identify_printing";
  const allCandidates = item.candidates ?? [];
  // Issue #728 - the suggested candidate is judged exactly ONCE in its own slot above and is
  // never re-offered as a grid tile while that slot is still asking (the old Level 2
  // re-presented it "highlighted" - the same candidate asked about twice). The grid is the
  // REST of the candidates, plus - since #748 - any the user has explicitly rejected at the
  // suggestion slot, which stay accessible as de-emphasised, re-selectable tiles rather than
  // vanishing (the rejected set drives both that grid inclusion below and the "you said not
  // this one" context further down).
  const suggestedCandidateId =
    item.type === "confirm_suggestion"
      ? item.suggestedPrinting?.identifier ?? null
      : null;
  const gridCandidates = allCandidates.filter(
    (candidate) =>
      rejectedCandidateIds.has(candidate.identifier) ||
      candidate.identifier !== suggestedCandidateId
  );
  const visibleCandidates = filterCandidatesByChipStates(
    gridCandidates,
    chipStates
  );
  const hiddenCount = gridCandidates.length - visibleCandidates.length;

  // Issue #503 (WTC phase C1) - group the candidate grid by shared Scryfall illustration,
  // including a group of one: group size is orthogonal to which question is being asked (a
  // singleton is still an illustration whose printing hasn't been narrowed - the thing being
  // identified is a proxy scan that may be an unofficial variant of that artwork, and per this
  // catalog's own corpus the most common such variant is an altered frame, not different art).
  // Every candidate with no illustrationId at all (CanonicalPrintingMetadata.illustration_id is
  // nullable and frequently absent, see local_illustration.py:137) renders in the flat
  // "ungrouped" grid below the clusters instead, so nothing is ever dropped from the grid.
  //
  // Phase C2: tapping a tile inside one of these clusters submits through
  // selectIllustrationGroup (ONE illustrationId, /2/submitIllustrationVote/) rather than
  // selectCandidate - see that function's own comment. Ungrouped tiles are unaffected: they
  // still call selectCandidate with that exact PrintingCandidate through the unchanged
  // /2/submitPrintingTag/ path.
  const illustrationGroupsById = new Map<string, PrintingCandidate[]>();
  visibleCandidates.forEach((candidate) => {
    // Issue #748 - a rejected candidate never joins an illustration cluster: clusters render
    // only one representative tile, so burying the rejected suggestion inside one would
    // silently drop it again. It always renders as a standalone (de-emphasised) ungrouped tile
    // instead, guaranteeing the reconsider path stays visible.
    if (
      !candidate.illustrationId ||
      rejectedCandidateIds.has(candidate.identifier)
    ) {
      return;
    }
    const existingGroup = illustrationGroupsById.get(candidate.illustrationId);
    if (existingGroup != null) {
      existingGroup.push(candidate);
    } else {
      illustrationGroupsById.set(candidate.illustrationId, [candidate]);
    }
  });
  const illustrationGroups = Array.from(illustrationGroupsById.values());
  const groupedCandidateIds = new Set(
    illustrationGroups.flatMap((group) =>
      group.map((candidate) => candidate.identifier)
    )
  );
  const ungroupedCandidates = visibleCandidates.filter(
    (candidate) => !groupedCandidateIds.has(candidate.identifier)
  );

  // The user tapped "Not this art" - the suggestion slot gives way to the candidate-grid
  // identification question on the SAME page (issue #728: not a stage transition), carrying
  // the #748 re-selectable-tile mechanic. See markNotThisArt's own comment for why no vote is
  // forced here even when that leaves the grid empty.
  const notThisArtActive =
    item.type === "confirm_suggestion" &&
    item.suggestedPrinting != null &&
    rejectedCandidateIds.has(item.suggestedPrinting.identifier);

  // Shape (d) - open-ended (ANNEX B): an `identify_printing` item with no shortlist at all
  // (the smallest slice - cold-start/no-evidence). Framed as the "tricky one" (WD7) instead of
  // the neutral pick-grid shape.
  const isOpenEndedShape =
    isCandidateType &&
    item.type === "identify_printing" &&
    allCandidates.length === 0;

  const subjectCaptionText = isOpenEndedShape
    ? "no strong machine candidate for this one"
    : "the scanned image you're identifying";

  const heroImageSrc =
    item.card.mediumThumbnailUrl === ""
      ? ""
      : getWorkerImageURL(item.card, "small") ?? item.card.smallThumbnailUrl;

  // Artist questions re-frame the subject as the artwork itself (WTC artist re-frame): the
  // backend surfaces the canonical printing's Scryfall art-crop URL on these items, so the
  // voter judges the art without the scanned card's frame/glare. Falls back to the plain
  // card image when the item carries no art crop (no canonical printing / no harvested URL).
  const subjectImageSrc =
    item.type === "artist" && item.scryfallIllustrationUrl != null
      ? item.scryfallIllustrationUrl
      : heroImageSrc;

  // The subject card's art + reveal overlay - no starburst (owner ruling 1 retires BurstSvg;
  // the token-derived `--wtc-field`/`--wtc-reveal-glow` carry the reveal moment's "game feel"
  // instead - ANNEX C).
  const cardArt = (
    <RevealWrapper>
      <img
        ref={cardImageRef}
        src={heroImageSrc}
        alt={item.card.name}
        style={{ width: "100%", aspectRatio: CARD_ASPECT_RATIO }}
        onLoad={() => onCardImageSettled(false)}
        onError={() => onCardImageSettled(item.card.mediumThumbnailUrl !== "")}
      />
      {(!revealed || imageErrored) && (
        <MysteryCard
          data-testid="question-feed-reveal-overlay"
          playing={imageLoaded && !imageErrored}
          onAnimationEnd={() => setRevealed(true)}
        />
      )}
    </RevealWrapper>
  );

  // The full subject card composition (SPEC-wtc-rebuild.md's "subject card"/"subject art"/
  // "subject art title"/"subject caption" rows) - art, the card name below it in its own row
  // (issue #741 - previously overlaid on the art's own bottom edge), plus a caption strip
  // explaining what the subject IS.
  const subjectCard = (
    <SubjectCardBox>
      <SubjectArt data-testid="question-feed-subject-art">
        <SubjectArtImage data-testid="question-feed-subject-art-image">
          {cardArt}
        </SubjectArtImage>
        <SubjectArtTitle data-testid="question-feed-subject-art-title">
          {item.card.name}
        </SubjectArtTitle>
      </SubjectArt>
      <SubjectCap>
        <span className="glyph">?</span>
        <span>{subjectCaptionText}</span>
      </SubjectCap>
    </SubjectCardBox>
  );

  // The one card panel the candidate question renders (issue #707) - the attribute-chip panel
  // no longer replaces this with a ring-around-card composition; it renders separately in
  // QPanel (identificationBody / the "Same art, but..." follow-up below) instead, so the
  // pinned reference card (Subject, A2) is never swapped out or occluded by it.
  const plainCardPanel = (
    <CardPanel data-testid="question-feed-card-panel">{subjectCard}</CardPanel>
  );

  let cardNode: React.ReactNode;
  let questionsNode: React.ReactNode;

  if (isCandidateType) {
    if (level3Active) {
      cardNode = plainCardPanel;
      questionsNode = (
        <div data-testid="question-feed-level3">
          <QHead>
            <ShapePill className="easy">
              &#10003; matched &middot; one more thing
            </ShapePill>
            <Prompt>Anything else true of this card?</Prompt>
          </QHead>
          <QHint>
            Auto-tagged from your pick; adjust only what&apos;s wrong, then
            continue.
          </QHint>
          {EXCLUSION_GROUPS.filter((group) =>
            group.chips.some((chip) => chip.tagName in level3ChipStates)
          ).map((group) => (
            <div key={group.id}>
              <GroupLabel>{group.label}</GroupLabel>
              <TriStateChipRow>
                {group.chips.map((chip) => {
                  const state = level3ChipStates[chip.tagName] ?? "untouched";
                  return (
                    <TriStateChip
                      key={chip.tagName}
                      className={state === "positive" ? "pos" : ""}
                      disabled={submitting}
                      onClick={() => tapLevel3Chip(group, chip.tagName)}
                      data-testid={`question-feed-level3-chip-${chip.tagName}`}
                    >
                      {state === "positive" && <span>&#10003;</span>}
                      {chip.label}
                    </TriStateChip>
                  );
                })}
              </TriStateChipRow>
            </div>
          ))}
          <ActionRow>
            <Btn
              className="primary"
              disabled={submitting}
              onClick={confirmLevel3}
              data-testid="question-feed-level3-confirm"
            >
              Confirm &amp; continue
            </Btn>
            <Btn
              className="ghost"
              disabled={submitting}
              // Issue #715 - route through the guarded skip() rather than a raw advance():
              // a double-tap on this button must not skip two cards.
              onClick={skip}
              data-testid="question-feed-level3-skip"
            >
              Skip this question
            </Btn>
          </ActionRow>
        </div>
      );
    } else {
      // The single candidate question (issue #728 - the level1/level2 ladder is gone): the
      // candidate grid, or (isOpenEndedShape) the dashed "tricky one" framing for a
      // zero-candidate identify_printing item (shape d, ANNEX B). The suggested candidate
      // (when present) renders in its own slot above the grid and never as a tile.
      cardNode = plainCardPanel;
      // Shared by both the illustration-clustered and flat/ungrouped rendering below - keeps
      // the tile markup (and its data-card-* attributes / mpc:card-selected event / testids)
      // byte-for-byte identical regardless of which grid a candidate ends up in. `onSelect`
      // defaults to the ungrouped path (selectCandidate, unchanged since before C2); illustration
      // clusters (below) pass selectIllustrationGroup instead, per #503 phase C2 - see that
      // function's own comment for why grouped and ungrouped tiles submit through different
      // endpoints despite sharing this exact markup.
      const renderCandidateTile = (
        candidate: PrintingCandidate,
        onSelect: () => void = () => selectCandidate(candidate, false),
        // Illustration clusters (below) pass false: the cluster now carries its own
        // ArtistSupportLink credit above the grid, so repeating the same name on every tile
        // inside it is redundant. Ungrouped tiles have no cluster-level credit, so they keep
        // this caption at its default (true) - the only place a candidate's artist is still
        // shown at all for that grid.
        showArtistCaption: boolean = true,
        // Illustration clusters (below) pass candidate.artCropUrl, falling back to the full
        // scan when a candidate's metadata sidecar has none - see this function's own comment
        // on showArtistCaption for why grouped tiles diverge from the ungrouped default here.
        imageUrl: string = candidate.mediumThumbnailUrl,
        // Issue #746 - an illustration crop isn't card-shaped, so illustration clusters (below)
        // pass IllustrationArtPlaceholder instead of the card-ratio ArtPlaceholder every
        // ungrouped (full-scan) tile keeps by default.
        Frame: typeof ArtPlaceholder = ArtPlaceholder
      ) => {
        // Issue #748 - a rejected Level 1 suggestion stays in the grid as a de-emphasised tile
        // that is still fully selectable: tap it to reconsider and cast it as a real pick (the
        // recover path for a mis-tapped "Not this art").
        const isRejected = rejectedCandidateIds.has(candidate.identifier);
        return (
          <CandidateButton
            key={candidate.identifier}
            className={isRejected ? "rejected" : undefined}
            data-rejected={isRejected ? "true" : undefined}
            disabled={submitting}
            onClick={onSelect}
            {...getPrintingCandidateDataAttributes(item.card.name, candidate)}
          >
            <Frame data-testid="question-feed-candidate-art-frame">
              <MysteryCard />
              <ZoomableThumbnail>
                <img
                  src={imageUrl}
                  alt={`${candidate.expansionCode} ${candidate.collectorNumber}`}
                />
              </ZoomableThumbnail>
              {submitting && selectedCandidateId === candidate.identifier && (
                <div
                  data-testid={`question-feed-candidate-submitting-${candidate.identifier}`}
                >
                  <Spinner size={1.5} zIndex={2} positionAbsolute />
                </div>
              )}
            </Frame>
            <CandidateCaption>
              <div className="cn">
                <SetIcon expansionCode={candidate.expansionCode} />{" "}
                {candidate.expansionCode.toUpperCase()}{" "}
                {candidate.collectorNumber}
              </div>
              {isRejected && (
                <div
                  className="rej"
                  data-testid="question-feed-rejected-tile-note"
                >
                  you said no &middot; tap to reconsider
                </div>
              )}
              {showArtistCaption && (
                <div className="cs">{candidate.artist}</div>
              )}
            </CandidateCaption>
          </CandidateButton>
        );
      };
      // Problem 2 (owner report, 2026-08-04): a not-official-printing reason (the artwork is
      // genuine, this scan just isn't one of the listed printings) means the remaining
      // question - which printing - is still answerable from this same item's own candidate
      // list, so this returns to the candidate grid with its filter panel already expanded
      // instead of skipping to the next item, reusing the existing chip narrowing
      // (filterCandidatesByChipStates) rather than any new selector or vote shape.
      // A not-official-art reason (custom-art/ai-art/external-ip) has nothing left to narrow
      // towards - that axis keeps advancing straight through, unchanged.
      const onNoMatchReasonDone = (chosenTagName?: string) => {
        const isNotOfficialPrinting =
          chosenTagName != null &&
          (
            NO_MATCH_REASON_TAG_GROUPS["not-official-printing"]
              .tagNames as readonly string[]
          ).includes(chosenTagName);
        if (isNotOfficialPrinting && gridCandidates.length > 0) {
          setFollowUp("none");
          setFilterExpanded(true);
          return;
        }
        advance();
      };
      // The candidate-grid identification question - shared by identify_printing's own item
      // type and confirm_suggestion's "Not this art" follow-up (rejectedContext renders the
      // "you said not this one" line above the prompt in the latter case, null in the former).
      const identificationBody = (rejectedContext: React.ReactNode) => (
        <>
          <QHead>
            <ShapePill
              className={isOpenEndedShape ? "hard" : "pick"}
              data-testid="question-feed-tier-badge"
            >
              Needs identification
            </ShapePill>
          </QHead>
          {rejectedContext}
          <Prompt>Which printing is this?</Prompt>
          {isOpenEndedShape && (
            <QHint>
              No strong machine candidate. This is one of the harder ones - take
              your time.
            </QHint>
          )}
          {filterExpanded && (
            <FilterPanelWrap data-testid="question-feed-filter-panel">
              <AttributeChipPanel
                backendURL={backendURL}
                cardIdentifier={item.card.identifier}
                tagConfidence={item.tagConfidence ?? {}}
                chipStates={chipStates}
                onChipStatesChange={setChipStates}
                onRateLimited={() => setRateLimited(true)}
                pruneContradicted
              />
            </FilterPanelWrap>
          )}
          {hiddenCount > 0 && (
            <p
              className="text-muted small"
              data-testid="question-feed-hidden-count"
            >
              {hiddenCount} hidden by your tags -{" "}
              <a
                href="#"
                data-testid="question-feed-clear-filters"
                onClick={(event) => {
                  event.preventDefault();
                  setChipStates(initialChipStates());
                }}
              >
                clear
              </a>
            </p>
          )}
          <div className="mb-2">
            <Btn
              className="ghost"
              onClick={() => setFilterExpanded((previous) => !previous)}
              data-testid="question-feed-filter-toggle"
            >
              {filterExpanded ? "Hide filters" : "Filter by attribute"}
            </Btn>
          </div>
          {illustrationGroups.length > 0 && (
            <IllustrationGroupFlow data-testid="question-feed-illustration-groups">
              {illustrationGroups.map((group) => {
                // Every member of `group` shares one illustrationId, i.e. one artwork - artist
                // should be identical across them too, but source data can disagree, so take the
                // first non-blank rather than assuming group[0] is always populated.
                const illustrationArtist = group
                  .map((candidate) => candidate.artist)
                  .find((artist) => artist.trim() !== "");
                // selectIllustrationGroup already submits one illustrationId for the whole
                // cluster (see that function's own comment), so one tile fully represents what
                // is being voted on - showing every member here just repeats the same artwork
                // up to N times. Prefer a member with an art crop, the same signal a tile's own
                // image already prefers (renderCandidateTile's imageUrl default below), and fall
                // back to the first member so the same data always picks the same tile.
                const representative =
                  group.find((candidate) => candidate.artCropUrl) ?? group[0];
                return (
                  <IllustrationGroup
                    key={group[0].illustrationId}
                    data-testid="question-feed-illustration-group"
                    data-illustration-id={group[0].illustrationId}
                  >
                    <IllustrationGroupLabel>
                      {group.length > 1
                        ? `Same illustration - ${group.length} printings`
                        : "Illustration"}
                    </IllustrationGroupLabel>
                    {illustrationArtist != null && (
                      <IllustrationCredit data-testid="question-feed-illustration-credit">
                        <ArtistSupportLink artistName={illustrationArtist} />
                      </IllustrationCredit>
                    )}
                    <CandidateGrid>
                      {renderCandidateTile(
                        representative,
                        () =>
                          // every member of `group` shares this non-null illustrationId - see
                          // the grouping logic above, which only clusters candidates that have
                          // one - so submitting the representative's illustrationId is
                          // identical to submitting any other member's, whatever the group size.
                          selectIllustrationGroup(
                            representative.illustrationId as string,
                            representative
                          ),
                        false,
                        representative.artCropUrl ||
                          representative.mediumThumbnailUrl,
                        // Only the illustration-crop image is landscape-shaped - the
                        // mediumThumbnailUrl fallback above is still a full card scan, so it
                        // keeps the card-ratio frame.
                        representative.artCropUrl
                          ? IllustrationArtPlaceholder
                          : ArtPlaceholder
                      )}
                    </CandidateGrid>
                  </IllustrationGroup>
                );
              })}
            </IllustrationGroupFlow>
          )}
          {ungroupedCandidates.length > 0 && (
            <CandidateGrid data-testid="question-feed-candidate-grid-ungrouped">
              {ungroupedCandidates.map((candidate) =>
                renderCandidateTile(candidate)
              )}
            </CandidateGrid>
          )}
          {followUp === "no-match-reason" && (
            // Shape (c) - quick-negative (SPEC-wtc-rebuild.md's "negative wrapper"/"negative
            // header" rows) - danger-framed (WD7: visibly not a confirm), wrapping the
            // existing NoMatchReasonStrip unforked (its own ChipCard chips get the matching
            // "danger" frame via that component's own additive `variant` prop).
            <NegWrap
              className="mt-3"
              data-testid="question-feed-quick-negative"
            >
              <QHead>
                <ShapePill className="neg">not a printing</ShapePill>
              </QHead>
              <NoMatchReasonStrip
                backendURL={backendURL}
                cardIdentifier={item.card.identifier}
                onDone={onNoMatchReasonDone}
                onRateLimited={() => setRateLimited(true)}
              />
            </NegWrap>
          )}
          {followUp === "none" && (
            <ActionRow>
              <Btn
                className="secondary"
                disabled={submitting}
                onClick={() => selectCandidate(undefined, true)}
                data-testid="question-feed-no-match"
              >
                {submitting && selectedCandidateId === "no-match" ? (
                  <Spinner size={1} />
                ) : (
                  "None of these"
                )}
              </Btn>
              <Btn
                className="secondary"
                disabled={submitting}
                onClick={classifyAsCustomArt}
                data-testid="question-feed-custom-art"
              >
                {submitting && selectedCandidateId === "custom-art" ? (
                  <Spinner size={1} />
                ) : (
                  "This is custom art"
                )}
              </Btn>
              <Btn
                className="ghost"
                disabled={submitting}
                onClick={skip}
                data-testid="question-feed-skip"
              >
                Skip
              </Btn>
            </ActionRow>
          )}
        </>
      );

      const spinnerNode = (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      );

      if (item.type === "confirm_suggestion") {
        if (notThisArtActive) {
          // "Not this art" - the suggestion slot gives way to the same candidate-grid
          // identification question identify_printing uses, carrying the #748 reconsider-tile
          // mechanic above a "you said not this one" context line.
          const rejectedContext = item.suggestedPrinting != null && (
            <>
              <Prompt data-testid="question-feed-suggestion-prompt">
                Got it - let&apos;s find the actual printing.
              </Prompt>
              <div
                className="d-flex align-items-center gap-2 my-2 opacity-50"
                data-testid="question-feed-rejected-context"
              >
                <div style={{ width: 40, flexShrink: 0 }}>
                  <img
                    src={item.suggestedPrinting.mediumThumbnailUrl}
                    alt=""
                    style={{ width: "100%" }}
                  />
                </div>
                <div className="text-muted small">
                  You said: not{" "}
                  <SetIcon
                    expansionCode={item.suggestedPrinting.expansionCode}
                  />{" "}
                  {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                  {item.suggestedPrinting.collectorNumber}
                </div>
              </div>
            </>
          );
          questionsNode = !revealed ? (
            spinnerNode
          ) : (
            <div data-testid="question-feed-candidate-question">
              {identificationBody(rejectedContext)}
            </div>
          );
        } else if (sameArtButActive) {
          // "Same art, but..." follow-up - the illustration (and derived artist) vote already
          // landed on tap (markSameArtBut); these chips narrow what actually differs, each
          // casting its own real CardTagVote as it's tapped (useTagVoting, same as every other
          // AttributeChipPanel caller). There is no candidate grid here to filter, so the panel
          // renders standalone rather than inside FilterPanelWrap's grid-adjacent framing.
          questionsNode = !revealed ? (
            spinnerNode
          ) : (
            <div data-testid="question-feed-same-art-but">
              <QHead>
                <ShapePill className="easy">same art</ShapePill>
                <Prompt>What actually differs?</Prompt>
              </QHead>
              <QHint>
                Tap whichever of these are true - narrows the printing without
                confirming the wrong one.
              </QHint>
              <AttributeChipPanel
                backendURL={backendURL}
                cardIdentifier={item.card.identifier}
                tagConfidence={item.tagConfidence ?? {}}
                chipStates={chipStates}
                onChipStatesChange={setChipStates}
                onRateLimited={() => setRateLimited(true)}
              />
              <ActionRow>
                <Btn
                  className="primary"
                  onClick={finishSameArtBut}
                  data-testid="question-feed-same-art-but-continue"
                >
                  Continue
                </Btn>
              </ActionRow>
            </div>
          );
        } else {
          // The fresh confirm_suggestion question - subject card (cardNode above), the
          // suggested printing, and exactly its own answer set. No chip panel, no candidate
          // grid - any answer besides Yes summons its own follow-up above instead of
          // pre-rendering here.
          questionsNode = !revealed ? (
            spinnerNode
          ) : (
            <div data-testid="question-feed-candidate-question">
              <QHead>
                <ShapePill
                  className="easy"
                  data-testid="question-feed-tier-badge"
                >
                  Suggested match
                </ShapePill>
              </QHead>
              {item.suggestedPrinting != null && (
                <>
                  <SuggestedCard>
                    <SuggestedThumb data-testid="question-feed-suggestion-reference-image">
                      <ArtPlaceholder>
                        <MysteryCard />
                        <ZoomableThumbnail>
                          <img
                            src={item.suggestedPrinting.mediumThumbnailUrl}
                            alt={`${item.suggestedPrinting.expansionCode} ${item.suggestedPrinting.collectorNumber}`}
                          />
                        </ZoomableThumbnail>
                      </ArtPlaceholder>
                    </SuggestedThumb>
                    <SuggestedMeta>
                      <SuggestedName>{item.card.name}</SuggestedName>
                      <SuggestedSet>
                        <SetIcon
                          expansionCode={item.suggestedPrinting.expansionCode}
                        />{" "}
                        {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                        {item.suggestedPrinting.collectorNumber}
                      </SuggestedSet>
                      <ConfidencePill data-testid="question-feed-suggestion-prompt">
                        <i />
                        Is this the <ExactWord>EXACT</ExactWord> printing?
                      </ConfidencePill>
                      {item.suggestedPrinting.artist.trim() !== "" && (
                        <ArtistSupportLink
                          artistName={item.suggestedPrinting.artist}
                          className="mt-1"
                        />
                      )}
                    </SuggestedMeta>
                  </SuggestedCard>
                  <ActionStack>
                    <Btn
                      className="primary"
                      disabled={submitting}
                      onClick={() =>
                        item.suggestedPrinting != null &&
                        selectCandidate(item.suggestedPrinting, false)
                      }
                      data-testid="question-feed-suggestion-yes"
                    >
                      {submitting ? (
                        <Spinner size={1} />
                      ) : (
                        "Yes — that's the one"
                      )}
                    </Btn>
                    <ActionGrid>
                      <Btn
                        className="secondary"
                        disabled={submitting}
                        onClick={markSameArtBut}
                        data-testid="question-feed-suggestion-same-art-but"
                      >
                        Same art, but…
                      </Btn>
                      <Btn
                        className="secondary"
                        disabled={submitting}
                        onClick={markNotThisArt}
                        data-testid="question-feed-suggestion-not-this-art"
                      >
                        Not this art
                      </Btn>
                      <Btn
                        className="ghost"
                        disabled={submitting}
                        onClick={() => abstainAndAdvance()}
                        data-testid="question-feed-suggestion-skip"
                      >
                        Skip
                      </Btn>
                    </ActionGrid>
                  </ActionStack>
                  {landed && (
                    <LandedFeedback data-testid="question-feed-landed">
                      ✓ Tagged — nice. Next card loading…
                    </LandedFeedback>
                  )}
                </>
              )}
            </div>
          );
        }
      } else {
        // identify_printing - unchanged shape: the candidate-grid identification question,
        // dashed "tricky one" framing (isOpenEndedShape) for a zero-candidate item.
        questionsNode = !revealed ? (
          spinnerNode
        ) : isOpenEndedShape ? (
          <div data-testid="question-feed-candidate-question">
            <OpenWrap>{identificationBody(null)}</OpenWrap>
          </div>
        ) : (
          <div data-testid="question-feed-candidate-question">
            {identificationBody(null)}
          </div>
        );
      }
    }
  } else {
    // Artist / tag question types - the plain reference image these have always used moves
    // into the shared subject slot as-is, with no reveal treatment added. Artist questions
    // substitute the Scryfall art crop when the item carries one (see subjectImageSrc).
    cardNode = (
      <SubjectCardBox>
        <SubjectArt data-testid="question-feed-subject-art">
          <SubjectArtImage
            $landscape={item.type === "artist"}
            data-testid="question-feed-subject-art-image"
          >
            <img
              ref={cardImageRef}
              src={subjectImageSrc}
              alt={item.card.name}
              data-testid={
                item.type === "artist" ? "question-feed-artist-art" : undefined
              }
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onLoad={() => onCardImageSettled(false)}
              onError={() =>
                onCardImageSettled(item.card.mediumThumbnailUrl !== "")
              }
            />
          </SubjectArtImage>
          <SubjectArtTitle data-testid="question-feed-subject-art-title">
            {item.card.name}
          </SubjectArtTitle>
        </SubjectArt>
      </SubjectCardBox>
    );
    questionsNode = (
      <>
        {item.type === "artist" && (
          <>
            <QHead>
              <ShapePill className="pick">artist</ShapePill>
              <Prompt>Who made this art?</Prompt>
            </QHead>
            <ArtistVotePicker
              backendURL={backendURL}
              cardIdentifier={item.card.identifier}
              confidentlyKnownArtistName={item.confidentlyKnownArtistName}
              onRateLimited={() => setRateLimited(true)}
              voteSurface="question-feed"
              onArtistConfirmed={(name) => {
                bumpSessionCount();
                setConfirmedArtistName(name);
              }}
            />
            {confirmedArtistName != null && (
              <ArtistCredit
                className="mt-2"
                data-testid="question-feed-artist-support"
              >
                <ArtistSupportLink artistName={confirmedArtistName} />
              </ArtistCredit>
            )}
            <ActionRow>
              <Btn className="ghost" onClick={skip}>
                Skip
              </Btn>
            </ActionRow>
          </>
        )}
        {item.type === "tag" && item.tagName != null && (
          <>
            <QHead>
              <ShapePill className="pick">attribute</ShapePill>
            </QHead>
            <QueueTagQuestion
              backendURL={backendURL}
              cardIdentifier={item.card.identifier}
              tagName={item.tagName}
              onAnswered={() => {
                bumpSessionCount();
                advance();
              }}
              onRateLimited={() => setRateLimited(true)}
            />
          </>
        )}
        {item.type === "border" && (
          <>
            <QHead>
              <ShapePill className="pick">border</ShapePill>
              <Prompt>Which border colour is this?</Prompt>
            </QHead>
            <BorderColorQuestion
              backendURL={backendURL}
              cardIdentifier={item.card.identifier}
              tagConfidence={item.tagConfidence ?? {}}
              chipStates={chipStates}
              onChipStatesChange={setChipStates}
              onRateLimited={() => setRateLimited(true)}
            />
            <ActionRow>
              <Btn
                className="ghost"
                onClick={() => abstainAndAdvance("cannot-tell")}
                data-testid="question-feed-cant-tell"
              >
                Can&apos;t tell from this scan.
              </Btn>
              <Btn className="ghost" onClick={() => abstainAndAdvance()}>
                Skip
              </Btn>
            </ActionRow>
          </>
        )}
        {item.type === "illustration" && (
          <>
            <QHead>
              <ShapePill className="pick">artwork</ShapePill>
              <Prompt>Is this the artwork?</Prompt>
            </QHead>
            <IllustrationQuestion
              item={item}
              backendURL={backendURL}
              onAnswered={() => {
                bumpSessionCount();
                advance();
              }}
              onRateLimited={() => setRateLimited(true)}
            />
            <ActionRow>
              <Btn className="ghost" onClick={() => abstainAndAdvance()}>
                Skip
              </Btn>
            </ActionRow>
          </>
        )}
      </>
    );
  }

  return (
    <FeedRoot data-testid="question-feed">
      <WtcHead>
        <WhatsThatWords />
        <SolvedPill
          data-testid="question-feed-session-counter"
          title="quiet resolved-count - not a score or streak"
        >
          <SolvedDots>
            {[0, 1, 2, 3].map((index) => (
              <i
                key={index}
                className={index < Math.min(sessionTaggedCount, 4) ? "f" : ""}
              />
            ))}
          </SolvedDots>
          <span>
            <b>{sessionTaggedCount}</b> tagged this session
          </span>
        </SolvedPill>
      </WtcHead>
      <WtcHero data-testid="question-feed-current-item">
        <Subject data-testid="question-feed-hero-card-area">{cardNode}</Subject>
        <QPanel data-testid="question-feed-questions-area">
          {rateLimited && (
            // Persistent (not a self-dismissing toast) and dismissible - a rate-limit pause is
            // an expected, honest condition in a one-tap funnel, not a failure.
            <Alert
              variant="warning"
              dismissible
              onClose={() => setRateLimited(false)}
              data-testid="question-feed-rate-limited"
            >
              You&apos;re on fire &mdash; take a short breather before voting
              again.
            </Alert>
          )}
          {questionsNode}
          {counts != null && (
            <StatsLine data-testid="question-feed-stats">
              {counts.confirmable} ready &middot; {counts.total} in catalog
              &middot; {counts.contested} contested
            </StatsLine>
          )}
        </QPanel>
      </WtcHero>
    </FeedRoot>
  );
}
