/**
 * The unified "What's That Card?" question feed - replaces the old printing/artist/tag tab
 * switcher (PrintingTagQueue.tsx + GenericVoteQueue.tsx, both deleted alongside this file)
 * with a single `GET 2/questionFeed/`-driven stream of one question at a time, typed per
 * cardpicker.question_feed's three-tier ranked union. See docs/features/printing-tags.md's
 * questionFeed section and journal/2026-07-14-queue-question-feed-design.md for the full
 * design writeup (chip taxonomy grounding, layout rationale, starvation-risk tradeoff).
 *
 * Candidate-type items (confirm_suggestion / identify_printing) now run through three stages
 * instead of one grid screen - see the funnel proposal artifact (PR-E's HOLD) for the mocks
 * and state diagram this implements:
 *   Level 1 - a single suggested printing, YES / NOT SURE / NO / SKIP, no grid. Only reached
 *     for confirm_suggestion items that actually carry a suggestedPrinting.
 *   Level 2 - the candidate grid (identify_printing lands here directly; confirm_suggestion
 *     lands here on NOT SURE/NO). The attribute-chip ring is now an opt-in, collapsed-by-
 *     default "Filter by attribute" disclosure rather than always-on chrome around the card -
 *     picking a candidate ignores filter state entirely (filters are navigation, never
 *     votes). Two classified exits sit below the grid: "None of these" (unchanged - still
 *     followed by the reason strip) and "Art matches, not an official printing" (a single
 *     pre-classified tap: isNoMatch printing vote + a positive custom-art tag vote, no reason
 *     strip since the tap already said why).
 *   Level 3 - conditional. Selecting a candidate auto-casts a positive tag vote for every
 *     attribute chip the candidate's own data derives (see attributeChips.ts's
 *     getAutoTagChips) - most of the time that's everything, and the feed advances straight
 *     to the next card. Level 3 only renders when a genuinely open question survives (an
 *     exclusion group whose candidate value doesn't match any of that group's chips - see
 *     getOpenExclusionGroups), presenting just those groups as a real single-select lock
 *     (picking one deselects its alternates), distinct from Level 2's filter panel, which
 *     keeps the funnel's usual independent tri-state cycling.
 *
 * Re-composition, not a rewrite: the sticky starburst card panel, reveal animation, and
 * candidate-grid mechanics are the exact same code as the old PrintingTagQueue, now shared
 * via cardPanel.tsx. ArtistVotePicker and QueueTagQuestion are reused directly for their
 * question types, unforked.
 */

import styled from "@emotion/styled";
import React, { useEffect, useRef, useState } from "react";
import Alert from "react-bootstrap/Alert";
import Badge from "react-bootstrap/Badge";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

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
import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import { NoMatchReasonStrip } from "@/features/attributeVoting/NoMatchReasonStrip";
import { QueueTagQuestion } from "@/features/attributeVoting/QueueTagQuestion";
import {
  ArtPlaceholder,
  BurstSvg,
  CandidateButton,
  CARD_ASPECT_RATIO,
  CardPanel,
  CardPulseWrapper,
  HoverBurst,
  randomFlavorText,
  RevealOverlay,
  RevealWrapper,
  StaticCardPanel,
  useStarburstFrame,
  ZoomableThumbnail,
} from "@/features/printingTags/cardPanel";
import {
  STARBURST_INNER_COLOR,
  STARBURST_INNER_FRAMES,
  STARBURST_OUTER_COLOR,
  STARBURST_OUTER_FRAMES,
  STARBURST_VIEWBOX,
} from "@/features/printingTags/starburstShape";
import { WhatsThatWords } from "@/features/questionFeed/WhatsThatWords";
import {
  APIGetQuestionFeed,
  APISubmitPrintingTag,
  APISubmitTagVote,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

type FollowUp = "none" | "no-match-reason";
type CandidateStage = "level1" | "level2" | "level3";

// Mobile funnel pass (thumb-native tap targets): Bootstrap's own default .btn height is
// ~38px (0.375rem vertical padding + 1.5 line-height + border) - short of the 44px minimum
// both Apple's HIG and WCAG 2.5.5 (Target Size, AA) call for. Every stacked full-width action
// button in the funnel (Level 1's YES/NOT SURE/NO, Level 2's None of these/Art matches/Skip,
// Level 3's Confirm & continue/Skip) goes through this wrapper instead of bare react-bootstrap
// Button - one place enforcing the floor rather than a min-height style prop repeated at every
// call site (and one place to revisit if the target size guidance ever changes). flex centering
// keeps short labels ("No", "Skip") vertically centered once the box is taller than its text,
// rather than leaving them pinned to the button's own top-padding baseline.
const ThumbButton = styled(Button)`
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
`;

// "Filter by attribute" / "Hide filters" - a variant="link" toggle, not one of the stacked
// action buttons above (ThumbButton doesn't apply here; it isn't full-width or button-styled).
// The plain-link version used p-0 (zero padding), collapsing its tap target to just the text's
// own line-height (~24px, measured) - well under the 44px floor despite being the ONLY way to
// reach the attribute-chip filter on Level 2. Padding restores a real hit area without
// resembling a filled button (still variant="link" - text + underline, no background/border).
const FilterToggleButton = styled(Button)`
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 0;
`;

// Level 3's per-attribute chip picker (a wrapped row of inline pills, not stacked full-width -
// ThumbButton's flex-stack styling doesn't fit here). Was Button size="sm", the smallest
// Bootstrap variant - shorter still than the already-under-target default. min-height alone
// (not ThumbButton's display/alignment) since these need to stay inline-sized to their own
// label, wrapping naturally in the row.
const ThumbChip = styled(Button)`
  min-height: 44px;
`;

// ---------------------------------------------------------------------------------------
// Quiz-reveal hero (issue #305, wtc-redesign-spec.md) - one grid-area map per breakpoint:
// "card words" / "card questions" at >= md (the card spans both rows on the left; words sit
// over the questions on the right); "words words" / "card questions" below md (words stays
// full-width up top, unchanged from before this fix round, but the card now sits in its own
// compact LEFT column beside the questions instead of stacking above/below them - see the
// mobile-row fix round below for why).
//
// Owner addendum to the approved design: the reference card must stay fully visible while
// the user works through the questions, not scroll away with them. At >= md the whole hero
// is bounded to one viewport-height row (leaving the page's own outer scroll - see
// ContentContainer in Layout.tsx - with nothing to do while answering) and only
// HeroQuestionsArea below scrolls internally; the card's own grid cell never scrolls, so
// there's no sticky/negative-z-index mechanism left to run (see CardPanel's own comment in
// cardPanel.tsx for what this replaces).
//
// Fix round (PR #305/#308 owner review): this used to bound itself via its own
// `max-height: calc(100dvh - NavbarHeight - 2rem)` - wrong on two independent counts. (1) the
// static NavbarHeight constant regularly undercounts the navbar's real rendered height (issue
// #250), and (2) even with an accurate navbar height, the flat "2rem" guess ignored
// StarburstBackground's own real padding/margin (4.5rem, not 2rem) AND Footer's entire height
// below it - so the true total page content routinely exceeded the space actually available,
// forcing Layout.tsx's ContentContainer to scroll as a whole and breaking the "hero stays
// pinned" invariant live despite passing CI (a scrollTop-only assertion on the inner questions
// box never exercised that outer container). Replaced with `flex: 1; min-height: 0` below -
// FeedRoot/StarburstContent (whatsthat.tsx) now do this arithmetic structurally instead of via
// a hand-maintained calc, so this can't drift out of sync with either figure again.
//
// Fix round (owner live-review, "the card covers the questions on scroll") - below md, this
// used to collapse to a single column ("words" "card" "questions" stacked top-to-bottom) with
// HeroCardArea's own `position: sticky` bar riding ON TOP of HeroQuestionsArea (z-index: 5) as
// the page scrolled - the two areas shared the same horizontal space by design, so the sticky
// card was ALWAYS going to paint over whatever text had scrolled up underneath it (confirmed
// live: a real wheel-scroll + getBoundingClientRect() diff in this task's own report showed
// the card's box fully nested inside the questions box's own bounds post-scroll - not a fluke,
// the geometry guaranteed it). Below md now mirrors >= md's own "card beside, not above/below,
// the questions" shape instead - a real, disjoint grid COLUMN for the card (see
// grid-template-columns below), so the two areas structurally cannot overlap regardless of
// scroll position or either one's own height, the same invariant >= md already had. See
// HeroCardArea's own comment for the compact column width and MobileButtonRow/MobileChipRow/
// MobileCandidateScroller (below) for how the answer options fill the narrower remaining
// width without wrapping into an unreadable number of rows.
// ---------------------------------------------------------------------------------------

const HeroGrid = styled.div`
  display: grid;
  gap: 0.75rem 0.5rem;
  grid-template-columns: minmax(0, 7.5rem) minmax(0, 1fr);
  grid-template-areas: "words words" "card questions";

  @media (min-width: 768px) {
    /* Row-gap trimmed from 1.5rem to 1rem, then to 0.5rem on rebase onto #313's taller
       three-tier Footer (fix round, owner blocker) - purely spacing between the words/
       questions rows, not approved content, and every pixel of it also comes straight out of
       HeroQuestionsArea's own budget the same way the words row's own height does (see the
       Word component's own comment in WhatsThatWords.tsx for the full arithmetic). Column gap
       (2.5rem) is untouched - that's the card/questions horizontal gutter HeroQuestionsArea's
       own bleed math already accounts for. */
    gap: 0.5rem 2.5rem;
    grid-template-columns: minmax(0, 42%) minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    grid-template-areas: "card words" "card questions";
    flex: 1;
    min-height: 0;
  }
`;

// QuestionFeed's own root - `flex: 1; min-height: 0` at >= md opts into StarburstContent's
// `display: flex; flex-direction: column; height: 100%` (whatsthat.tsx) so HeroGrid's own
// `flex: 1` above has a real, resolvable height to consume. Only meaningful when this is a
// direct flex child of a flex parent with a definite height - true for the common,
// non-moderator render path (StarburstContent renders this directly), but NOT for the
// moderator Tab.Container/Tab.Content/Tab.Pane switcher (whatsthat.tsx), which isn't part of
// that flex chain - this deliberately falls back to auto/natural height there instead
// (unchanged from before this fix round), rather than extending the flex chain through three
// more react-bootstrap wrapper components for a small, privileged audience.
const FeedRoot = styled.div`
  @media (min-width: 768px) {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }
`;

const HeroCardArea = styled.div`
  grid-area: card;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;

  // Phone interpretation of the pinning intent (owner addendum, mobile-row fix round) - the
  // card's own grid COLUMN (HeroGrid's minmax(0, 7.5rem) track, above) is what keeps it
  // compact now, not a max-width override here; this area simply fills that track. Still
  // position: sticky; top: 0 so the card stays in view if the questions column ever grows
  // tall enough to need page scroll (PageColumn/StarburstContent still let the whole page
  // scroll below md - unchanged) - safe to keep unconditionally now, unlike the SUPERSEDED
  // sticky bar this replaces: that one shared its horizontal space with HeroQuestionsArea (a
  // single stacked column) and needed z-index: 5 specifically to paint over it, which is
  // exactly what let it obscure scrolled-under text. This one lives in its own disjoint grid
  // column beside HeroQuestionsArea (see HeroGrid's grid-template-areas above) - sticky here
  // only ever competes for space with the empty column gap, never with the questions column's
  // own content, so no elevated z-index/opaque backdrop is needed to protect anything.
  @media (max-width: 767.98px) {
    position: sticky;
    top: 0;
    align-self: start;
  }

  @media (min-width: 768px) {
    height: 100%;
    min-height: 0;
  }
`;

// Below md, the "answer options" for whichever stage is active (Level 1's four stacked
// buttons, Level 2's candidate grid, Level 3's exclusion-group chips) render in a single
// horizontally-scrollable row beside the compact card instead of stacking/wrapping to fit the
// narrower remaining width (owner's live-review layout proposal) - the direct fix for the
// "the card covers the questions" bug: rather than trying to squeeze full-width stacked
// controls into whatever's left beside a ~7.5rem card column (unreadably narrow, or forcing
// the card back into shared/overlapping space to get room back), the controls keep a
// comfortable minimum width each and the row scrolls sideways for any overflow. `-webkit-
// overflow-scrolling: touch` + a visible (not hidden - see HeroQuestionsArea's own comment on
// why a scrollable region should still look scrollable) thin themed scrollbar match the
// desktop candidate column's existing scrollbar treatment for visual consistency. Reverts to
// normal (no horizontal scroll, no forced row) at >= md - untouched, each call site's own
// pre-existing desktop layout (flex-column button stack, Bootstrap Row/Col grid, wrapped chip
// row) is unaffected there.
//
// Deliberately NOT applied to the artist/tag question types (ArtistVotePicker/
// QueueTagQuestion) - those are search/autocomplete-shaped UI, not a set of discrete "pick
// one" options, and forcing them into a horizontal filmstrip would make them harder to use,
// not easier; they keep their existing normal vertical stacking at every width. See this
// task's own PR body for the explicit per-stage mapping this scopes to.
// Shared scrollbar treatment (visible, not hidden - see HeroQuestionsArea's own comment on why
// a scrollable region should still look scrollable) for all three mobile-row variants below -
// factored out as a plain string rather than a fourth wrapper component, since each variant's
// own base (column-stack vs. already-a-row vs. Bootstrap grid) differs too much to share a
// single styled-component base beyond this.
const mobileScrollbarCSS = `
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.25) transparent;

  &::-webkit-scrollbar {
    height: 8px;
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
  &::-webkit-scrollbar-thumb {
    background-color: rgba(255, 255, 255, 0.25);
    border-radius: 4px;
  }
`;

// Level 1's YES/NOT SURE/NO/SKIP - a plain vertical button stack at every width today (matches
// Bootstrap's own `d-flex flex-column gap-2` exactly at >= md, so desktop is byte-for-byte
// unaffected), switching to a horizontal nowrap row below md instead of stacking full-width
// beside the now-narrow card column.
const MobileButtonRow = styled.div`
  display: flex;
  flex-direction: column;
  gap: 0.5rem;

  @media (max-width: 767.98px) {
    flex-direction: row;
    flex-wrap: nowrap;
    align-items: stretch;
    overflow-x: auto;
    padding-bottom: 0.5rem;
    ${mobileScrollbarCSS}

    > * {
      flex: 0 0 auto;
      min-width: 8.75rem;
    }
  }
`;

// Level 3's exclusion-group chip picker - already a wrapping row at every width
// (`d-flex flex-wrap gap-2`); below md this only needs `flex-wrap` swapped for
// `nowrap`/`overflow-x: auto` rather than a direction change.
const MobileChipRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;

  @media (max-width: 767.98px) {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 0.5rem;
    ${mobileScrollbarCSS}

    > * {
      flex: 0 0 auto;
    }
  }
`;

// Level 2's candidate grid - the one case still built on Bootstrap's `Row`/`Col` (`xs={3}
// md={4}`, unchanged for >= md) rather than a plain flex row, so this targets the SAME
// classes (`.row`/`.col`) via nested selectors instead of restyling this wrapper's own box:
// `.row`'s own `flex-wrap: wrap` is overridden to `nowrap`, and each Bootstrap `.col`'s
// percentage flex-basis (from `xs={3}`) is overridden to a fixed width, so the row's overflow
// becomes horizontal scroll on THIS wrapper instead of Bootstrap's own multi-row wrap.
const MobileCandidateScroller = styled.div`
  @media (max-width: 767.98px) {
    overflow-x: auto;
    padding-bottom: 0.5rem;
    ${mobileScrollbarCSS}

    .row {
      flex-wrap: nowrap;
      width: max-content;
    }
    .row > [class*="col"] {
      flex: 0 0 6.5rem;
      width: 6.5rem;
      max-width: 6.5rem;
    }
  }
`;

const HeroWordsArea = styled.div`
  grid-area: words;

  @media (min-width: 768px) {
    align-self: end;
  }
`;

// Subtle themed scrollbar (owner addendum) - not the browser's default chrome, but not
// hidden either: a hidden scrollbar on a genuinely-scrollable region is its own usability
// trap, since "scrolling locks to the box" should still visibly look scrollable.
// Owner review (fix round, PR #305/#308): the candidate grid's hover-zoom (ZoomableThumbnail)
// and hover-burst (HoverBurst, cardPanel.tsx) were both deliberately built with no
// `overflow: hidden` of their own, specifically so the enlarged art/glow could pop out
// uncropped (see cardPanel.tsx's own comments on both, and docs/lessons.md's "a new wrapper
// placed around an existing effect can silently fight that effect's own CSS" entry for the
// exact prior incident this repeats) - this box's overflow-y: auto (needed for the pinning fix
// above) forces overflow-x: auto too per the CSS spec's own "visible computes to auto once the
// other axis isn't visible" rule (confirmed via getComputedStyle in this task's own debug
// pass), re-clipping both hover effects right at this box's left/right edges - worst on the
// left, where the first column sits flush with zero buffer at all.
//
// `margin: 0 -2.5rem` + matching `padding` bleeds this box's own clip boundary (its border/
// padding edge - where overflow: auto actually clips, not wherever its children happen to be
// positioned) 2.5rem past its grid-assigned track on each side, into the real empty space
// already there (the grid's own 2.5rem column gap on the left; the page's own outer margin -
// StarburstContent's max-width cap plus the full-bleed background beyond it - on the right,
// measured at >= 130px in this task's own debug pass, comfortably more than needed). The
// padding exactly cancels the bleed for layout purposes (content still starts/ends at the
// exact same x-position as before - verified via boundingBox() diff), so this is purely
// additional clip headroom, not a visible resting-layout change. HoverBurst's own edge-column
// variant (cardPanel.tsx's $edge prop) targets the remaining gap this alone doesn't cover -
// its 331.2%-wide glow needs more room than 2.5rem gives on either side.
const HeroQuestionsArea = styled.div`
  grid-area: questions;
  min-width: 0;

  @media (min-width: 768px) {
    overflow-y: auto;
    min-height: 0;
    margin: 0 -2.5rem;
    padding: 0 calc(2.5rem + 0.75rem) 0 2.5rem;
    scrollbar-width: thin;
    scrollbar-color: rgba(255, 255, 255, 0.25) transparent;

    &::-webkit-scrollbar {
      width: 8px;
    }
    &::-webkit-scrollbar-track {
      background: transparent;
    }
    &::-webkit-scrollbar-thumb {
      background-color: rgba(255, 255, 255, 0.25);
      border-radius: 4px;
    }
  }
`;

// Artist/tag question types never had a starburst-backed CardPanel (their card is a plain
// reference image, not the silhouette-reveal "mystery card" the candidate-type items use) -
// wtc-redesign-spec.md's "reposition, don't redesign" instruction keeps that unchanged, just
// relocated into the shared hero card slot. This wrapper only supplies the same width/
// centering contract CardPanel/StaticCardPanel give their own callers.
const PlainHeroCard = styled.div`
  width: 100%;
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

function initialStage(item: QuestionFeedItem | null): CandidateStage {
  return item?.type === "confirm_suggestion" && item?.suggestedPrinting != null
    ? "level1"
    : "level2";
}

export function QuestionFeed() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const starburstFrame = useStarburstFrame();

  const [item, setItem] = useState<QuestionFeedItem | null>(null);
  const [counts, setCounts] = useState<QuestionFeedCounts | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [caughtUp, setCaughtUp] = useState<boolean>(false);
  const [fetchError, setFetchError] = useState<boolean>(false);
  const [flavorText, setFlavorText] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<boolean>(false);
  // Fix round (owner blocker, "the pulse doesn't sync with the pop") - the reveal fade, the
  // WHAT'S/THAT/CARD? pop sequence, and the hero card's own pulse used to all fire the moment
  // their elements mounted, with no regard for whether the subject card's own <img> had
  // actually finished loading - on a slow connection this could reveal (or pop/pulse against)
  // a still-loading or half-painted image. `imageLoaded`/`imageErrored` below, together with
  // `cardImageRef`'s mount-time `.complete` check (mirrors Card.tsx's own cached-image
  // workaround - see that component's comment), gate all three animations (via each one's own
  // `$playing`/`playing` prop - RevealOverlay/CardPulseWrapper in cardPanel.tsx, WhatsThatWords
  // itself) on one single real load-complete moment instead of three independent mount timers.
  const [imageLoaded, setImageLoaded] = useState<boolean>(false);
  // A failed load never gets a legitimate "reveal" moment to sync to - the cover stays up
  // permanently (below) with no animation at all, rather than fading onto a broken image only
  // to sit there un-animated forever anyway. See onCardImageSettled below for how `revealed`
  // still unblocks the rest of the question UI regardless, so a failed image can't strand the
  // user on an infinite spinner.
  const [imageErrored, setImageErrored] = useState<boolean>(false);
  // Bumped unconditionally alongside the reset above, on EVERY fetch resolution - not just
  // ones that land on a genuinely different card. Two consecutive feed items can legitimately
  // share the same identifier (the fetch effect's own comment above explains why, and dev-mode
  // React Strict Mode's double effect-invocation makes a duplicate resolution routine even
  // outside that case), and a duplicate resolution still unconditionally resets `imageLoaded`
  // back to false here - a `.complete`/`naturalWidth` catch-up effect keyed on the identifier
  // alone would silently miss that second reset (no dependency change to re-trigger it on),
  // permanently stranding the UI on "Loading..." with nothing left to ever flip `revealed`
  // back to true. Keying that effect on this counter instead guarantees it re-runs every time
  // this reset block runs, with no dependency on whether the identifier text itself changed.
  const [imageGeneration, setImageGeneration] = useState<number>(0);
  const cardImageRef = useRef<HTMLImageElement>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null
  );
  const [chipStates, setChipStates] = useState<Record<string, ChipVoteState>>(
    initialChipStates()
  );
  const [followUp, setFollowUp] = useState<FollowUp>("none");
  // Candidate identifiers the user has explicitly said NO to (Level 1 only - "Not sure" is
  // genuine uncertainty, not a rejection, and deliberately never adds here) within THIS item's
  // flow - reset on every new item below. Design rule (owner-directed): a candidate the user
  // has just rejected is never re-presented as a selectable answer at a later level within the
  // same item - see rejectSuggestion below and the filtered candidate list this feeds.
  const [rejectedCandidateIds, setRejectedCandidateIds] = useState<Set<string>>(
    new Set()
  );
  const [fetchToken, setFetchToken] = useState<number>(0);
  // Artist Support Links v1 - set once the user casts a real (non-"Unknown") artist vote on an
  // "artist"-type item, via ArtistVotePicker's onArtistConfirmed below. Drives the post-answer
  // "Art by <Name> - support them" banner (see the artist item's render block) - reset on every
  // new item alongside the other per-question state, so it can't bleed into the next question.
  const [confirmedArtistName, setConfirmedArtistName] = useState<string | null>(
    null
  );
  // A 429 from any vote-casting call below (printing, tag, artist) sets this instead of firing
  // the usual error toast - see the banner rendered near the top of the item below. In a
  // one-tap funnel, a rate-limit pause is an expected, honest condition, not a failure, so it
  // gets a persistent inline notice rather than a transient, alarm-toned toast.
  const [rateLimited, setRateLimited] = useState<boolean>(false);

  const [stage, setStage] = useState<CandidateStage>("level2");
  // Collapsed by default (decision: chip-as-filter survives on Level 2, but off-path for the
  // common case - see the held funnel proposal's open-decisions section). Selecting a
  // candidate below ignores this entirely; it only ever narrows which tiles are shown.
  const [filterExpanded, setFilterExpanded] = useState<boolean>(false);
  // Level 3 only ever asks about groups an already-selected candidate left open - keyed by
  // tagName, but only ever contains chips from getOpenExclusionGroups(pendingCandidate).
  const [level3ChipStates, setLevel3ChipStates] = useState<
    Record<string, ChipVoteState>
  >({});

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
        // (and revealed/selectedCandidateId/etc) over from the previous card. That's exactly
        // what produced the real-device symptom of the candidate grid rendering empty (chip
        // states left over from a previous card filtering out every candidate of the new one)
        // until the user tapped a chip - the only other thing that ever updated chipStates,
        // which incidentally "fixed" it by replacing the stale filter. Resetting here instead
        // makes the reset unconditional on every new item, with no dependency array to miss.
        setRevealed(false);
        setImageLoaded(false);
        setImageErrored(false);
        setImageGeneration((previous) => previous + 1);
        // A genuinely empty configured URL (this test suite's own fixture convention - real
        // cards always carry a real CDN URL) has nothing to load at all, so it's settled right
        // here rather than waiting on any image event - see onCardImageSettled's own comment
        // for why relying on the img's real onError event alone for this specific case was
        // flaky under load. Everything else routes through the `imageGeneration`-keyed catch-up
        // effect below instead (needs the new `<img>` to have actually mounted first).
        if (newItem != null && newItem.card.mediumThumbnailUrl === "") {
          onCardImageSettled(false);
        }
        setChipStates(initialChipStates());
        setFollowUp("none");
        setRejectedCandidateIds(new Set());
        setSelectedCandidateId(null);
        setConfirmedArtistName(null);
        setRateLimited(false);
        setFilterExpanded(false);
        setLevel3ChipStates({});
        setStage(initialStage(newItem));
      })
      .catch(() => {
        setItem(null);
        setFetchError(true);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, fetchToken]);

  // The one moment every animation in the hero (RevealOverlay's fade, WhatsThatWords' pop,
  // CardPulseWrapper's pulse) is anchored to - see each of their own comments. Two cases skip
  // the animated queue entirely and jump straight to `revealed`, for different reasons:
  // reduced motion (nothing should ever visibly pop/fade, so there's no animationend event to
  // wait for) and a failed load (no legitimate image to reveal - see the cover's own "stays up
  // forever" behavior below, driven by `imageErrored` rather than this function). Shared by
  // both the `<img>`'s own onLoad/onError below AND the `.complete` catch-up effect below it -
  // the reduced-motion shortcut has to apply on EITHER path, or a reduced-motion session that
  // happens to hit the catch-up path (a cached image, or - only in tests - an empty-string
  // fixture URL that never fires load/error at all) would never flip `revealed` at all, since
  // reduced motion also means RevealOverlay's fade never plays and therefore never fires the
  // `onAnimationEnd` that flips it the normal way. That gap is exactly what the reduced-motion
  // Playwright spec (WhatsThatWordsAnimation.spec.ts) caught empirically.
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

  // Catches a genuinely cached REAL image - Next.js/the browser sometimes never fires onLoad
  // for a cache hit (see Card.tsx's own, older workaround for the identical gotcha). Checks
  // `naturalWidth > 0`, not just `.complete` - `.complete` alone is `true` for a FAILED load
  // too, so a plain `.complete` check would risk overwriting a genuine `imageErrored` back to
  // a false "success" for an already-failed real URL. (The empty-URL fast path lives directly
  // in the fetch handler above, not here - it needs no DOM access at all.)
  //
  // Deliberately keyed on `imageGeneration`, NOT `item?.card.identifier` - two consecutive
  // feed items can legitimately share the same identifier (see the fetch handler's own
  // comment on `imageGeneration`), and an identifier-keyed effect would silently skip re-
  // running on a duplicate resolution, permanently stranding `revealed` at the `false` that
  // resolution's own reset left behind. `imageGeneration` bumps on every single resolution
  // unconditionally, so this effect always re-runs in lockstep with the reset that needs it
  // to. This exact gap - found empirically via a Playwright run that got stuck on
  // "Loading..." forever, not by inspection - is why the reset's own comment already warns
  // about this class of bug for `chipStates`; this effect walked into the same trap once
  // before this fix.
  //
  // Routes through onCardImageSettled (not a bare setImageLoaded(true)) so the reduced-motion
  // shortcut there applies here too. Runs after the new item's own `<img>` has mounted, so
  // `cardImageRef.current` is always the CURRENT item's image by the time this checks it.
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
  // actually matches (see attributeChips.ts's getAutoTagChips / Finding 2). If that leaves a
  // group genuinely undecided (the candidate's own value doesn't match any of that group's
  // chips - getOpenExclusionGroups), Level 3 renders to ask just about that; otherwise the
  // feed advances straight to the next card.
  const selectCandidate = (
    candidate: PrintingCandidate | undefined,
    isNoMatch: boolean
  ) => {
    if (backendURL == null || item == null) {
      return;
    }
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
            setStage("level3");
          } else {
            advance();
          }
        } else {
          advance();
        }
      })
      .catch(reportVoteFailed)
      .finally(() => {
        setSubmitting(false);
        setSelectedCandidateId(null);
      });
  };

  // The pre-classified exit for "this is real art, just not an official printing" - one tap
  // instead of "None of these" -> the reason strip, since the tap already told us why (see
  // reason_tags.py's existing seeded "custom-art" tag - no new endpoint).
  const classifyAsCustomArt = () => {
    if (backendURL == null || item == null) {
      return;
    }
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
        setSubmitting(false);
        setSelectedCandidateId(null);
      });
  };

  // Real single-select lock (decision: scoped to Level 3 only) - picking one option in a group
  // resets any other member of the same group back to untouched, unlike the funnel's usual
  // independent tri-state cycling that Level 2's optional filter panel keeps.
  const tapLevel3Chip = (group: ExclusionGroup, tagName: string) => {
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
      .then(() => advance())
      .catch(reportVoteFailed)
      .finally(() => setSubmitting(false));
  };

  const skip = () => advance();

  // Level 1's NO. In the general case this casts no vote itself - there's no backend concept of
  // "reject just this one candidate specifically," only a positive vote for a specific printing
  // or a generic isNoMatch for the whole set (see selectCandidate above) - so it purely records
  // the rejection client-side so Level 2's candidate list (below) excludes it, then falls
  // through to the SAME setStage("level2") transition as before.
  //
  // EXCEPTION - the singleton case (owner-reported dedup bug, docs/features/printing-tags.md's
  // questionFeed section): when the suggested printing is the card's ONLY candidate, rejecting
  // it leaves nothing else to ask - "No" IS the terminal answer for this surface, not a detour
  // to a different question. Before this fix, the singleton screen still required an explicit
  // extra tap ("None of these") before any vote was written; if that second tap never happened
  // (the user read "No" as final and moved on, hit the generic "Skip" instead, closed the tab),
  // no CardPrintingTag row existed for this (card, anonymous_id) pair at all, so
  // question_feed.py's tier-1 exclusion (`.exclude(printing_tags__anonymous_id=...)`) had
  // nothing to match against - the exact same question resurfaced on the next feed fetch. This
  // is the "dedup doesn't work" bug: the fix isn't the exclusion logic (already correct - see
  // test_tier_1_excludes_cards_this_voter_already_voted_on in test_question_feed.py), it's that
  // no vote was ever recorded here to exclude on. Detecting the singleton case and immediately
  // calling the same isNoMatch vote "None of these" casts closes that gap: the vote persists at
  // the moment "No" is tapped, with or without any further tap. The "Got it - not that one..."
  // follow-up screen (below) still renders while/after this submits, unchanged.
  const rejectSuggestion = () => {
    if (item?.suggestedPrinting == null) {
      setStage("level2");
      return;
    }
    const rejectedIdentifier = item.suggestedPrinting.identifier;
    setRejectedCandidateIds((previous) =>
      new Set(previous).add(rejectedIdentifier)
    );
    setStage("level2");

    const remainingCandidates = (item.candidates ?? []).filter(
      (candidate) => candidate.identifier !== rejectedIdentifier
    );
    if (remainingCandidates.length === 0) {
      selectCandidate(undefined, true);
    }
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
        <ThumbButton
          variant="outline-secondary"
          onClick={fetchNext}
          data-testid="question-feed-retry"
        >
          Try again
        </ThumbButton>
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
  // Excludes anything the user rejected at Level 1 ("No" - see rejectSuggestion) BEFORE the
  // chip filter applies, so a rejected candidate is never offered again as a selectable tile
  // for the rest of this item's flow, regardless of chip state. hiddenCount below is computed
  // against this (not allCandidates) so "N hidden by your tags" doesn't conflate a rejection
  // with a filter - they're excluded for different reasons and the copy should stay accurate.
  const nonRejectedCandidates = allCandidates.filter(
    (candidate) => !rejectedCandidateIds.has(candidate.identifier)
  );
  const visibleCandidates = filterCandidatesByChipStates(
    nonRejectedCandidates,
    chipStates
  );
  const hiddenCount = nonRejectedCandidates.length - visibleCandidates.length;
  // The singleton case (or any rejection that happens to empty the remaining set): Level 2
  // renders with zero grid tiles either way (visibleCandidates is simply empty), but this
  // drives the contextual copy/rejected-candidate-context swap below rather than showing the
  // generic "Which of these is it?" prompt over a blank grid.
  const suggestionRejectedWithNoneLeft =
    item.type === "confirm_suggestion" &&
    item.suggestedPrinting != null &&
    rejectedCandidateIds.has(item.suggestedPrinting.identifier) &&
    nonRejectedCandidates.length === 0;

  // Fix round (owner live-review, "the subject card renders the full-size source image") -
  // this used to put `item.card.mediumThumbnailUrl` straight into the hero `<img>` - a raw
  // backend field that (per cardpicker/sources/source_types.py's GoogleDrive.
  // get_medium_thumbnail_url) resolves DIRECTLY to `drive.google.com/thumbnail?...`, entirely
  // bypassing our own image-CDN Worker (cdn.proxyprints.ca, R2-cached) every other real
  // surface in the app prefers - confirmed live via a real Network-tab capture in this task's
  // own report (the hero request landed on drive.google.com, not cdn.proxyprints.ca). Every
  // other card-image call site (Card.tsx's useImageSrc, SharedDeckViewer.tsx,
  // downloadImages.ts) resolves through `getWorkerImageURL` first and only falls back to the
  // raw field when the worker genuinely isn't configured for this source type - this hero image
  // now does the same, via the exact same helper, instead of being the one remaining surface
  // that talks to Google Drive directly. "small" (400px, common/image.ts's ImageSize enum) is
  // the right tier here, not "large" (800px) - CardPulseWrapper caps this hero at 320px CSS
  // width even on desktop (and far less on the mobile compact column), so "small" already
  // comfortably covers a >2x-retina render at that size with less than half the bytes "large"
  // would cost for no visible gain.
  //
  // Guarded on the RAW field being non-empty (not just "did getWorkerImageURL return
  // something") so this test suite's own "empty mediumThumbnailUrl means nothing to load, skip
  // straight to the settled fast-path" fixture convention (see the fetch effect's own
  // `newItem.card.mediumThumbnailUrl === ""` check above, and onError below) keeps working
  // unchanged - getWorkerImageURL would otherwise happily build a real-looking (but bogus) CDN
  // URL for a GoogleDrive-sourceType fixture even when neither thumbnail field is genuinely
  // configured, since it only checks sourceType/env config, not whether the underlying
  // identifier is real.
  const heroImageSrc =
    item.card.mediumThumbnailUrl === ""
      ? ""
      : getWorkerImageURL(item.card, "small") ?? item.card.smallThumbnailUrl;

  // BurstSvg renders alongside (not inside) RevealWrapper deliberately - RevealWrapper has
  // overflow: hidden (it clips the silhouette-reveal animation to the card's own box), which
  // would also clip the burst's intentional bleed if it were a descendant instead of a
  // sibling. Both size themselves against whichever positioned ancestor contains them -
  // AttributeChipPanel's CardArea when the filter panel is expanded, CardPanel directly
  // otherwise - so the burst centers on and scales with the card's own rendered width
  // specifically, not a wider ring around it. `$hero` (cardPanel.tsx) enlarges the burst to
  // dominate the hero's left column (wtc-redesign-spec.md §7/owner addendum) - every
  // candidate-type stage shares this one hero card, so the enlargement is unconditional here
  // rather than special-cased per level.
  const cardImage = (
    <>
      <BurstSvg $hero viewBox={STARBURST_VIEWBOX}>
        <polygon
          points={STARBURST_OUTER_FRAMES[starburstFrame]}
          fill={STARBURST_OUTER_COLOR}
        />
        <polygon
          points={STARBURST_INNER_FRAMES[starburstFrame]}
          fill={STARBURST_INNER_COLOR}
        />
      </BurstSvg>
      <RevealWrapper>
        <img
          ref={cardImageRef}
          src={heroImageSrc}
          alt={item.card.name}
          style={{ width: "100%", aspectRatio: CARD_ASPECT_RATIO }}
          onLoad={() => onCardImageSettled(false)}
          // A genuinely empty configured URL (this test suite's own fixture convention - real
          // cards always carry a real CDN URL) still fires a real browser `error` event -
          // confirmed empirically: an `<img src="">` resolves the empty relative reference
          // against the CURRENT PAGE's own URL (per the URL spec's "empty string" case), and
          // fetching THAT as an image predictably fails to decode. That's a test-fixture
          // artifact, not a genuine failed load, so it's excluded here rather than triggering
          // the "keep the cover, no animation" failed-load treatment for every existing test.
          onError={() =>
            onCardImageSettled(item.card.mediumThumbnailUrl !== "")
          }
        />
        {/* Fix round (owner blocker) - visible while not yet revealed (unchanged), OR
            permanently once the load has errored (imageErrored), regardless of `revealed` -
            `revealed` itself still flips true on error (see onCardImageSettled) so the rest
            of the question UI (badge/buttons/etc, gated on `revealed` elsewhere in this file)
            isn't stranded behind a cover that will never legitimately animate away. */}
        {(!revealed || imageErrored) && (
          <RevealOverlay
            data-testid="question-feed-reveal-overlay"
            $playing={imageLoaded && !imageErrored}
            onAnimationEnd={() => setRevealed(true)}
          >
            ?
          </RevealOverlay>
        )}
      </RevealWrapper>
      <div className="text-center mt-1">{item.card.name}</div>
    </>
  );

  // Plain card panel, no chip ring - Level 2's default while its filter disclosure is
  // collapsed (i.e. the common case). Real device evidence (the funnel proposal's evidence
  // section) found the always-on chip ring wedging the thumbnail between two flanking chip
  // columns and burying the card beneath a full screen of chips before it was even visible -
  // this is what that fix looks like at the call site. Level 1 uses level1CardPanel below
  // instead, not this - see StaticCardPanel's comment in cardPanel.tsx for why.
  const plainCardPanel = (
    <CardPanel data-testid="question-feed-card-panel">{cardImage}</CardPanel>
  );

  // Level 1 only - see StaticCardPanel's own comment (cardPanel.tsx) for why this compact
  // single-card screen deliberately doesn't reuse plainCardPanel above. Carries its own test
  // id (distinct from the card <img> itself) so a layout regression test can assert against
  // the card's full box - art plus name caption - not just the image, since the real-device
  // bug this guards against overlapped the caption too, not only the artwork.
  const level1CardPanel = (
    <StaticCardPanel data-testid="question-feed-level1-card-panel">
      {cardImage}
    </StaticCardPanel>
  );

  // The chip-ring version, only mounted when Level 2's "Filter by attribute" disclosure is
  // open - same AttributeChipPanel as before, just no longer unconditional chrome.
  const filterCardPanel = (
    <CardPanel data-testid="question-feed-card-panel">
      <AttributeChipPanel
        backendURL={backendURL}
        cardIdentifier={item.card.identifier}
        tagConfidence={item.tagConfidence ?? {}}
        chipStates={chipStates}
        onChipStatesChange={setChipStates}
        cardSlot={cardImage}
        onRateLimited={() => setRateLimited(true)}
      />
    </CardPanel>
  );

  // The hero grid (below) has exactly one card slot and one questions slot per stage/type -
  // wtc-redesign-spec.md's axis flip (W1) plus the owner's "one persistent hero card, only the
  // questions swap on the right" reading of the mockup's stage-switcher demo. Each branch below
  // sets both variables instead of returning its own two-column JSX, so every stage shares the
  // exact same HeroGrid/HeroCardArea/HeroWordsArea/HeroQuestionsArea composition (rendered once,
  // after this if-chain) rather than re-implementing the split per stage.
  let cardNode: React.ReactNode;
  let questionsNode: React.ReactNode;

  if (isCandidateType) {
    if (stage === "level1" && item.suggestedPrinting != null) {
      cardNode = level1CardPanel;
      questionsNode = (
        <div data-testid="question-feed-level1">
          {!revealed ? (
            <div className="text-center py-4">
              <Spinner size={2} />
            </div>
          ) : (
            <>
              <div className="text-center">
                <Badge
                  bg="info"
                  data-testid="question-feed-tier-badge"
                  className="my-2"
                >
                  Suggested match
                </Badge>
                {/* The Scryfall reference render for the suggested printing - dropped when
                    Level 1 was introduced (a regression, not an intentional text-only design;
                    every other stage still shows one per candidate). Restored using the exact
                    same mechanism Level 2's grid already uses correctly: mediumThumbnailUrl
                    straight into a plain <img>, no new URL construction.
                    Fix round (owner blocker, post-#310) - maxWidth trimmed from 160 to 140.
                    This is a SEPARATE, smaller lever from the word-stack/row-gap/padding trims
                    above (WhatsThatWords.tsx's Word component has the full arithmetic) - those
                    alone left only a single-digit-px safety margin at 1400x900 once Level 1's
                    own content height is measured directly (not just via the scrollHeight/
                    clientHeight equality, which reports equal once content fits - by
                    definition scrollHeight can't read BELOW clientHeight even with room to
                    spare, so it doesn't surface a shrinking margin on its own). Trimmed again
                    (140 -> 95) on rebase onto #313's taller three-tier Footer, which ate
                    further into HeroGrid's own budget than this fix's first pass anticipated.
                    95px is a genuinely noticeable size cut from Level 2's own per-candidate
                    grid tiles (~171px at 1400px wide, four columns - roughly 55% of that
                    width, not merely "modestly smaller") - a real, visible size difference,
                    traded deliberately for real, measured margin under the hard no-scroll
                    assertion rather than shipping a fix that only barely clears it by
                    construction. Still legible (it's a small comparison thumbnail, not the
                    primary card - the big reveal-card on the left carries that job), but this
                    is a named tradeoff, not a free one. */}
                <div
                  className="mx-auto mb-2"
                  style={{ maxWidth: 95 }}
                  data-testid="question-feed-level1-reference-image"
                >
                  <ArtPlaceholder>
                    <ZoomableThumbnail>
                      <img
                        src={item.suggestedPrinting.mediumThumbnailUrl}
                        alt={`${item.suggestedPrinting.expansionCode} ${item.suggestedPrinting.collectorNumber}`}
                      />
                    </ZoomableThumbnail>
                  </ArtPlaceholder>
                </div>
                <p data-testid="question-feed-suggestion-prompt">
                  Is it this one?{" "}
                  <SetIcon
                    expansionCode={item.suggestedPrinting.expansionCode}
                  />{" "}
                  {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                  {item.suggestedPrinting.collectorNumber}
                </p>
              </div>
              <MobileButtonRow>
                <ThumbButton
                  variant="success"
                  disabled={submitting}
                  onClick={() =>
                    item.suggestedPrinting != null &&
                    selectCandidate(item.suggestedPrinting, false)
                  }
                  data-testid="question-feed-level1-yes"
                >
                  {submitting ? <Spinner size={1} /> : "Yes, that's it"}
                </ThumbButton>
                <ThumbButton
                  variant="outline-secondary"
                  disabled={submitting}
                  onClick={() => setStage("level2")}
                  data-testid="question-feed-level1-not-sure"
                >
                  Not sure
                </ThumbButton>
                <ThumbButton
                  variant="outline-danger"
                  disabled={submitting}
                  onClick={rejectSuggestion}
                  data-testid="question-feed-level1-no"
                >
                  No
                </ThumbButton>
                <ThumbButton
                  variant="link"
                  disabled={submitting}
                  onClick={skip}
                  data-testid="question-feed-level1-skip"
                >
                  Skip
                </ThumbButton>
              </MobileButtonRow>
            </>
          )}
        </div>
      );
    } else if (stage === "level3") {
      // Reuses the shared hero card (cardNode) instead of Level 3's old inline 48px
      // thumbnail+name row - the redesign gives every stage one persistent hero card, so a
      // second, smaller rendering of the same art here would be redundant, not additive.
      cardNode = plainCardPanel;
      questionsNode = (
        <div data-testid="question-feed-level3">
          <p className="text-muted small">
            Anything else you can tell us about this printing?
          </p>
          {EXCLUSION_GROUPS.filter((group) =>
            group.chips.some((chip) => chip.tagName in level3ChipStates)
          ).map((group) => (
            <div key={group.id} className="mb-3">
              <div className="text-muted small mb-1">{group.label}</div>
              <MobileChipRow>
                {group.chips.map((chip) => {
                  const state = level3ChipStates[chip.tagName] ?? "untouched";
                  return (
                    <ThumbChip
                      key={chip.tagName}
                      variant={
                        state === "positive" ? "primary" : "outline-secondary"
                      }
                      onClick={() => tapLevel3Chip(group, chip.tagName)}
                      data-testid={`question-feed-level3-chip-${chip.tagName}`}
                    >
                      {chip.label}
                    </ThumbChip>
                  );
                })}
              </MobileChipRow>
            </div>
          ))}
          <div className="mt-3 d-flex flex-column flex-sm-row gap-2">
            <ThumbButton
              variant="primary"
              disabled={submitting}
              onClick={confirmLevel3}
              data-testid="question-feed-level3-confirm"
              className="flex-fill"
            >
              Confirm &amp; continue
            </ThumbButton>
            <ThumbButton
              variant="outline-secondary"
              disabled={submitting}
              onClick={() => advance()}
              data-testid="question-feed-level3-skip"
              className="flex-fill"
            >
              Skip this question
            </ThumbButton>
          </div>
        </div>
      );
    } else {
      // Level 2.
      cardNode = filterExpanded ? filterCardPanel : plainCardPanel;
      questionsNode = !revealed ? (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      ) : (
        <>
          <Badge
            bg={item.type === "confirm_suggestion" ? "info" : "secondary"}
            data-testid="question-feed-tier-badge"
            className="mb-2"
          >
            {item.type === "confirm_suggestion"
              ? "Suggested match"
              : "Needs identification"}
          </Badge>
          {item.type === "confirm_suggestion" &&
            item.suggestedPrinting != null &&
            (suggestionRejectedWithNoneLeft ? (
              <>
                {/* Singleton-rejection case (task: eliminate double-asking) - the suggested
                    printing was the ONLY candidate, so there's nothing left to pick from a
                    grid. Skips straight to the classified-exit choice below, with the rejected
                    candidate kept as grayed, non-interactive context (never a button) rather
                    than vanishing without explanation. */}
                <p data-testid="question-feed-suggestion-prompt">
                  Got it - not that one. Is it any official printing at all?
                </p>
                <div
                  className="d-flex align-items-center gap-2 mb-3 opacity-50"
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
            ) : (
              <p data-testid="question-feed-suggestion-prompt">
                Which of these is it?{" "}
                <SetIcon expansionCode={item.suggestedPrinting.expansionCode} />{" "}
                {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                {item.suggestedPrinting.collectorNumber} was suggested
              </p>
            ))}
          {!suggestionRejectedWithNoneLeft && (
            <div className="mb-2">
              <FilterToggleButton
                variant="link"
                onClick={() => setFilterExpanded((previous) => !previous)}
                data-testid="question-feed-filter-toggle"
              >
                {filterExpanded ? "Hide filters" : "Filter by attribute"}
              </FilterToggleButton>
            </div>
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
          <MobileCandidateScroller>
            <Row className="g-2" xs={3} md={4}>
              {/* Row is 4-wide at >= md (the only breakpoint HeroQuestionsArea's overflow-y:
                  auto, and therefore its hover-clip risk, applies at - see that component's own
                  comment) - every 1st/4th candidate in a row sits flush against the scroll box's
                  own left/right edge, where even the added bleed room isn't enough for
                  HoverBurst's full-size bloom (see that component's own $edge comment). Below
                  md, MobileCandidateScroller overrides this Row to a single non-wrapping,
                  horizontally-scrollable line instead (owner's live-review layout proposal) -
                  xs={3} is inert there (never gets a chance to actually wrap), kept only so >=
                  md's md={4} value has a real xs fallback per react-bootstrap's own Row API. */}
              {visibleCandidates.map((candidate, index) => (
                <Col key={candidate.identifier}>
                  <CandidateButton
                    variant="outline-secondary"
                    className={`w-100 p-1 border-0${
                      item.type === "confirm_suggestion" &&
                      item.suggestedPrinting?.identifier ===
                        candidate.identifier
                        ? " highlighted"
                        : ""
                    }`}
                    disabled={submitting}
                    onClick={() => selectCandidate(candidate, false)}
                    {...getPrintingCandidateDataAttributes(
                      item.card.name,
                      candidate
                    )}
                  >
                    <HoverBurst
                      className="hover-burst"
                      viewBox={STARBURST_VIEWBOX}
                      $edge={index % 4 === 0 || index % 4 === 3}
                    >
                      <polygon
                        points={STARBURST_OUTER_FRAMES[starburstFrame]}
                        fill={STARBURST_OUTER_COLOR}
                      />
                      <polygon
                        points={STARBURST_INNER_FRAMES[starburstFrame]}
                        fill={STARBURST_INNER_COLOR}
                      />
                    </HoverBurst>
                    <ArtPlaceholder>
                      <ZoomableThumbnail>
                        <img
                          src={candidate.mediumThumbnailUrl}
                          alt={`${candidate.expansionCode} ${candidate.collectorNumber}`}
                        />
                      </ZoomableThumbnail>
                      {/* Tied to this specific candidate's identifier, not just `submitting` -
                        the old dimmed-all-buttons treatment gave no way to tell which of
                        several candidates you actually tapped under any real latency. */}
                      {submitting &&
                        selectedCandidateId === candidate.identifier && (
                          <div
                            data-testid={`question-feed-candidate-submitting-${candidate.identifier}`}
                          >
                            <Spinner size={1.5} zIndex={2} positionAbsolute />
                          </div>
                        )}
                    </ArtPlaceholder>
                    <div>
                      <SetIcon expansionCode={candidate.expansionCode} />{" "}
                      {candidate.expansionCode.toUpperCase()}{" "}
                      {candidate.collectorNumber}
                    </div>
                    <div className="text-muted small">{candidate.artist}</div>
                  </CandidateButton>
                </Col>
              ))}
            </Row>
          </MobileCandidateScroller>
          {followUp === "no-match-reason" && (
            <div className="mt-3">
              <hr />
              <NoMatchReasonStrip
                backendURL={backendURL}
                cardIdentifier={item.card.identifier}
                onDone={advance}
                onRateLimited={() => setRateLimited(true)}
              />
            </div>
          )}
          {followUp === "none" && (
            <div className="mt-3 d-flex flex-column gap-2">
              <ThumbButton
                variant="outline-secondary"
                disabled={submitting}
                onClick={() => selectCandidate(undefined, true)}
                data-testid="question-feed-no-match"
              >
                {submitting && selectedCandidateId === "no-match" ? (
                  <Spinner size={1} />
                ) : (
                  "None of these"
                )}
              </ThumbButton>
              <ThumbButton
                variant="outline-secondary"
                disabled={submitting}
                onClick={classifyAsCustomArt}
                data-testid="question-feed-custom-art"
              >
                {submitting && selectedCandidateId === "custom-art" ? (
                  <Spinner size={1} />
                ) : (
                  "\u{1F3A8} Art matches, not an official printing"
                )}
              </ThumbButton>
              <ThumbButton
                variant="outline-secondary"
                disabled={submitting}
                onClick={skip}
                data-testid="question-feed-skip"
              >
                Skip
              </ThumbButton>
            </div>
          )}
        </>
      );
    }
  } else {
    // Artist / tag question types - "reposition, not redesign" (wtc-redesign-spec.md's own
    // instruction): the plain reference image these have always used moves into the shared
    // hero card slot as-is, with no burst/reveal treatment added (those question units, and
    // this simple image alongside them, are unforked from before this redesign).
    cardNode = (
      <PlainHeroCard>
        <img
          ref={cardImageRef}
          src={heroImageSrc}
          alt={item.card.name}
          style={{ width: "100%" }}
          onLoad={() => onCardImageSettled(false)}
          // See cardImage's own identical onError above for why an empty configured URL is
          // excluded from the "genuine failure" treatment.
          onError={() =>
            onCardImageSettled(item.card.mediumThumbnailUrl !== "")
          }
        />
        <div className="text-center mt-1">{item.card.name}</div>
      </PlainHeroCard>
    );
    questionsNode = (
      <>
        {item.type === "artist" && (
          <>
            <h6>Who&apos;s the artist?</h6>
            <ArtistVotePicker
              backendURL={backendURL}
              cardIdentifier={item.card.identifier}
              confidentlyKnownArtistName={item.confidentlyKnownArtistName}
              onRateLimited={() => setRateLimited(true)}
              voteSurface="question-feed"
              onArtistConfirmed={setConfirmedArtistName}
            />
            {confirmedArtistName != null && (
              <div
                className="mt-2 text-muted small"
                data-testid="question-feed-artist-support"
              >
                <ArtistSupportLink artistName={confirmedArtistName}>
                  Art by {confirmedArtistName} - support them
                </ArtistSupportLink>
              </div>
            )}
            <div className="mt-3">
              <ThumbButton variant="outline-secondary" onClick={skip}>
                Skip
              </ThumbButton>
            </div>
          </>
        )}
        {item.type === "tag" && item.tagName != null && (
          <QueueTagQuestion
            backendURL={backendURL}
            cardIdentifier={item.card.identifier}
            tagName={item.tagName}
            onAnswered={advance}
            onRateLimited={() => setRateLimited(true)}
          />
        )}
      </>
    );
  }

  return (
    <FeedRoot data-testid="question-feed">
      <HeroGrid data-testid="question-feed-current-item">
        <HeroCardArea data-testid="question-feed-hero-card-area">
          {/* Keyed on the card identifier so both the pop-in-sync-with-THAT pulse (below) and
              WhatsThatWords' own ripple (HeroWordsArea) remount - and therefore replay their
              CSS animation from frame zero - on every new card (wtc-redesign-spec.md W9 /
              owner addendum). `$playing` (fix round, owner blocker) additionally gates WHEN
              that replayed animation actually starts - see cardPanel.tsx's own comment - to
              the moment `imageLoaded` confirms this card's own image has settled, not just to
              this remount. */}
          <CardPulseWrapper
            key={item.card.identifier}
            $playing={imageLoaded && !imageErrored}
            data-testid="question-feed-card-pulse"
          >
            {cardNode}
          </CardPulseWrapper>
        </HeroCardArea>
        <HeroWordsArea>
          <WhatsThatWords
            animationKey={item.card.identifier}
            playing={imageLoaded && !imageErrored}
          />
        </HeroWordsArea>
        <HeroQuestionsArea data-testid="question-feed-questions-area">
          {rateLimited && (
            // Persistent (not a self-dismissing toast) and dismissible - a rate-limit pause is
            // an expected, honest condition in a one-tap funnel, not a failure, so it gets its
            // own calm inline notice instead of competing with the transient error/success
            // toast stream. The backend's 429 response doesn't include a retry-after value, so
            // this deliberately doesn't promise a specific wait time - Skip and browsing the
            // current item both still work while this is shown; only vote submission is
            // affected.
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
          {/* Fix round (PR #305/#308 owner review, "Maybe the old text should go?") - the
              intro paragraph, "N quick confirmations ready" headline, and "N in catalog · N
              contested" subcounts line used to sit ABOVE the question, eating into the vertical
              budget that pulls the suggested-match card + answer buttons up beside the
              reference card at eye level (the L1 case must fit entirely above the fold at
              1400x900 - see this task's own screenshots). The underlying counts are still
              useful, just not at the cost of that space - a single small, muted line tucked
              at the bottom of this column (after the question itself, never part of the
              scroll budget a user has to clear before answering) keeps the information without
              the vertical cost. */}
          {counts != null && (
            <p
              className="text-muted small mt-3 mb-0"
              data-testid="question-feed-stats"
            >
              {counts.confirmable} ready &middot; {counts.total} in catalog
              &middot; {counts.contested} contested
            </p>
          )}
        </HeroQuestionsArea>
      </HeroGrid>
    </FeedRoot>
  );
}
