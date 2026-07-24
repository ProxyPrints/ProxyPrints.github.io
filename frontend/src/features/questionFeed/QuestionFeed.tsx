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
 *   - Preserved verbatim: Level 1/2/3 flows, `getAutoTagChips` auto-tagging on candidate pick,
 *     no-re-presentation (`rejectedCandidateIds`), the singleton-NO terminal vote, per-item
 *     state reset inside the fetch `.then()` (not a keyed `useEffect` - the stale-filter fix),
 *     the rate-limit banner, `data-card-*` attributes + the `mpc:card-selected` event (via
 *     `getPrintingCandidateDataAttributes`, unchanged), every `data-testid` this file's own
 *     Playwright/jest coverage keys off of.
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
import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import { NoMatchReasonStrip } from "@/features/attributeVoting/NoMatchReasonStrip";
import { QueueTagQuestion } from "@/features/attributeVoting/QueueTagQuestion";
import {
  ArtPlaceholder,
  CandidateButton,
  CandidateCaption,
  CandidateGrid,
  CARD_ASPECT_RATIO,
  CardPanel,
  MysteryCard,
  randomFlavorText,
  RevealWrapper,
  StaticCardPanel,
  ZoomableThumbnail,
} from "@/features/printingTags/cardPanel";
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
  max-width: 1180px;
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
  max-width: 1180px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: clamp(12px, 2.2cqi, 22px);
  align-items: start;
`;

const Subject = styled.div`
  flex: 1 1 300px;
  min-width: 0;
  max-width: clamp(240px, 30cqi, 340px);

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

const SubjectArt = styled.div`
  aspect-ratio: ${CARD_ASPECT_RATIO};
  position: relative;

  @container hero (max-width: 560px) {
    flex: 0 0 132px;
    width: 132px;
    aspect-ratio: auto;
  }
`;

const SubjectArtTitle = styled.div`
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 2;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.72));
  color: #fff;
  font-weight: 700;
  font-size: clamp(13px, 3.4cqi, 17px);
  padding: 22px 10px 8px;
  text-shadow: 0 1px 2px #000;
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

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &.big {
    font-size: 17px;
    font-weight: 800;
    padding: 10px 20px;
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

function initialStage(item: QuestionFeedItem | null): CandidateStage {
  return item?.type === "confirm_suggestion" && item?.suggestedPrinting != null
    ? "level1"
    : "level2";
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
  // "Art by <Name> - support them" banner - reset on every new item alongside the other
  // per-question state, so it can't bleed into the next question.
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
  // common case). Selecting a candidate below ignores this entirely; it only ever narrows
  // which tiles are shown.
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
  const bumpSessionCount = () =>
    setSessionTaggedCount((previous) => previous + 1);
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
        setFilterExpanded(false);
        setLevel3ChipStates({});
        setLanded(false);
        setStage(initialStage(newItem));
      })
      .catch(() => {
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
            setStage("level3");
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
      .then(() => {
        bumpSessionCount();
        advance();
      })
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
  // it leaves nothing else to ask - "No" IS the terminal answer for this surface. Detecting the
  // singleton case and immediately calling the same isNoMatch vote "None of these" casts closes
  // that gap: the vote persists at the moment "No" is tapped, with or without any further tap.
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
  // Excludes anything the user rejected at Level 1 ("No" - see rejectSuggestion) BEFORE the
  // chip filter applies, so a rejected candidate is never offered again as a selectable tile
  // for the rest of this item's flow, regardless of chip state.
  const nonRejectedCandidates = allCandidates.filter(
    (candidate) => !rejectedCandidateIds.has(candidate.identifier)
  );
  const visibleCandidates = filterCandidatesByChipStates(
    nonRejectedCandidates,
    chipStates
  );
  const hiddenCount = nonRejectedCandidates.length - visibleCandidates.length;
  const suggestionRejectedWithNoneLeft =
    item.type === "confirm_suggestion" &&
    item.suggestedPrinting != null &&
    rejectedCandidateIds.has(item.suggestedPrinting.identifier) &&
    nonRejectedCandidates.length === 0;

  // Shape (d) - open-ended (ANNEX B): an `identify_printing` item with no shortlist at all
  // (the smallest slice - cold-start/no-evidence). Framed as the "tricky one" (WD7) instead of
  // the neutral pick-grid shape.
  const isOpenEndedShape =
    isCandidateType &&
    stage === "level2" &&
    item.type === "identify_printing" &&
    allCandidates.length === 0;

  const subjectCaptionText = isOpenEndedShape
    ? "no strong machine candidate for this one"
    : "the scanned image you're identifying";

  const heroImageSrc =
    item.card.mediumThumbnailUrl === ""
      ? ""
      : getWorkerImageURL(item.card, "small") ?? item.card.smallThumbnailUrl;

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
  // "subject art title"/"subject caption" rows) - art with the card name overlaid at its own
  // bottom edge, plus a caption strip below explaining what the subject IS.
  const subjectCard = (
    <SubjectCardBox>
      <SubjectArt data-testid="question-feed-subject-art">
        {cardArt}
        <SubjectArtTitle>{item.card.name}</SubjectArtTitle>
      </SubjectArt>
      <SubjectCap>
        <span className="glyph">?</span>
        <span>{subjectCaptionText}</span>
      </SubjectCap>
    </SubjectCardBox>
  );

  // Plain card panel, no chip ring - Level 2's default while its filter disclosure is
  // collapsed (i.e. the common case).
  const plainCardPanel = (
    <CardPanel data-testid="question-feed-card-panel">{subjectCard}</CardPanel>
  );

  // Level 1 only - the compact single-card confirmation screen.
  const level1CardPanel = (
    <StaticCardPanel data-testid="question-feed-level1-card-panel">
      {subjectCard}
    </StaticCardPanel>
  );

  // The chip-ring version, only mounted when Level 2's "Filter by attribute" disclosure is
  // open - same AttributeChipPanel as before, just no longer unconditional chrome. Keeps its
  // pre-rebuild simple presentation (art + name below, no SubjectCard chrome) - the ring's own
  // CardArea box is sized differently from the default subject slot.
  const filterCardPanel = (
    <CardPanel data-testid="question-feed-card-panel">
      <AttributeChipPanel
        backendURL={backendURL}
        cardIdentifier={item.card.identifier}
        tagConfidence={item.tagConfidence ?? {}}
        chipStates={chipStates}
        onChipStatesChange={setChipStates}
        cardSlot={
          <>
            {cardArt}
            <div className="text-center mt-1">{item.card.name}</div>
          </>
        }
        onRateLimited={() => setRateLimited(true)}
      />
    </CardPanel>
  );

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
              <QHead>
                <ShapePill
                  className="easy"
                  data-testid="question-feed-tier-badge"
                >
                  Suggested match
                </ShapePill>
              </QHead>
              <SuggestedCard>
                <SuggestedThumb data-testid="question-feed-level1-reference-image">
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
                    Is it this one?
                  </ConfidencePill>
                </SuggestedMeta>
              </SuggestedCard>
              <ActionStack>
                <Btn
                  className="primary big block"
                  disabled={submitting}
                  onClick={() =>
                    item.suggestedPrinting != null &&
                    selectCandidate(item.suggestedPrinting, false)
                  }
                  data-testid="question-feed-level1-yes"
                >
                  {submitting ? <Spinner size={1} /> : "Yes — that's the one"}
                </Btn>
                <ActionGrid>
                  <Btn
                    className="secondary"
                    disabled={submitting}
                    onClick={() => setStage("level2")}
                    data-testid="question-feed-level1-not-sure"
                  >
                    Not sure
                  </Btn>
                  <Btn
                    className="secondary"
                    disabled={submitting}
                    onClick={rejectSuggestion}
                    data-testid="question-feed-level1-no"
                  >
                    No, different printing
                  </Btn>
                  <Btn
                    className="ghost"
                    disabled={submitting}
                    onClick={skip}
                    data-testid="question-feed-level1-skip"
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
    } else if (stage === "level3") {
      cardNode = plainCardPanel;
      questionsNode = (
        <div data-testid="question-feed-level3">
          <QHead>
            <ShapePill className="easy">
              &#10003; matched &middot; one more thing
            </ShapePill>
            <Prompt>Confirm the attributes</Prompt>
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
              onClick={() => advance()}
              data-testid="question-feed-level3-skip"
            >
              Skip this question
            </Btn>
          </ActionRow>
        </div>
      );
    } else {
      // Level 2 - the candidate grid, or (isOpenEndedShape) the dashed "tricky one" framing
      // for a zero-candidate identify_printing item (shape d, ANNEX B).
      cardNode = filterExpanded ? filterCardPanel : plainCardPanel;
      const shapePillClass =
        item.type === "confirm_suggestion"
          ? "easy"
          : isOpenEndedShape
          ? "hard"
          : "pick";
      const level2Body = (
        <>
          <QHead>
            <ShapePill
              className={shapePillClass}
              data-testid="question-feed-tier-badge"
            >
              {item.type === "confirm_suggestion"
                ? "Suggested match"
                : "Needs identification"}
            </ShapePill>
          </QHead>
          {item.type === "confirm_suggestion" &&
            item.suggestedPrinting != null &&
            (suggestionRejectedWithNoneLeft ? (
              <>
                <Prompt data-testid="question-feed-suggestion-prompt">
                  Got it - not that one. Is it any official printing at all?
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
            ) : (
              <Prompt data-testid="question-feed-suggestion-prompt">
                Which of these is it?{" "}
                <SetIcon expansionCode={item.suggestedPrinting.expansionCode} />{" "}
                {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                {item.suggestedPrinting.collectorNumber} was suggested
              </Prompt>
            ))}
          {item.type === "identify_printing" && (
            <Prompt>
              {isOpenEndedShape
                ? "You tell us — which printing?"
                : "Which printing is this?"}
            </Prompt>
          )}
          {isOpenEndedShape && (
            <QHint>
              No strong machine candidate. This is one of the harder ones - take
              your time.
            </QHint>
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
          {!suggestionRejectedWithNoneLeft && (
            <div className="mb-2">
              <Btn
                className="ghost"
                onClick={() => setFilterExpanded((previous) => !previous)}
                data-testid="question-feed-filter-toggle"
              >
                {filterExpanded ? "Hide filters" : "Filter by attribute"}
              </Btn>
            </div>
          )}
          <CandidateGrid>
            {visibleCandidates.map((candidate) => (
              <CandidateButton
                key={candidate.identifier}
                className={
                  item.type === "confirm_suggestion" &&
                  item.suggestedPrinting?.identifier === candidate.identifier
                    ? "highlighted"
                    : ""
                }
                disabled={submitting}
                onClick={() => selectCandidate(candidate, false)}
                {...getPrintingCandidateDataAttributes(
                  item.card.name,
                  candidate
                )}
              >
                <ArtPlaceholder>
                  <MysteryCard />
                  <ZoomableThumbnail>
                    <img
                      src={candidate.mediumThumbnailUrl}
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
                </ArtPlaceholder>
                <CandidateCaption>
                  <div className="cn">
                    <SetIcon expansionCode={candidate.expansionCode} />{" "}
                    {candidate.expansionCode.toUpperCase()}{" "}
                    {candidate.collectorNumber}
                  </div>
                  <div className="cs">{candidate.artist}</div>
                </CandidateCaption>
              </CandidateButton>
            ))}
          </CandidateGrid>
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
                onDone={advance}
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
                  "\u{1F3A8} Art matches, not an official printing"
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
      questionsNode = !revealed ? (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      ) : isOpenEndedShape ? (
        <div data-testid="question-feed-level2">
          <OpenWrap>{level2Body}</OpenWrap>
        </div>
      ) : (
        <div data-testid="question-feed-level2">{level2Body}</div>
      );
    }
  } else {
    // Artist / tag question types - the plain reference image these have always used moves
    // into the shared subject slot as-is, with no reveal treatment added.
    cardNode = (
      <SubjectCardBox>
        <SubjectArt>
          <img
            ref={cardImageRef}
            src={heroImageSrc}
            alt={item.card.name}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
            onLoad={() => onCardImageSettled(false)}
            onError={() =>
              onCardImageSettled(item.card.mediumThumbnailUrl !== "")
            }
          />
          <SubjectArtTitle>{item.card.name}</SubjectArtTitle>
        </SubjectArt>
      </SubjectCardBox>
    );
    questionsNode = (
      <>
        {item.type === "artist" && (
          <>
            <QHead>
              <ShapePill className="pick">artist</ShapePill>
              <Prompt>Who&apos;s the artist?</Prompt>
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
              <div
                className="mt-2 text-muted small"
                data-testid="question-feed-artist-support"
              >
                <ArtistSupportLink artistName={confirmedArtistName}>
                  Art by {confirmedArtistName} - support them
                </ArtistSupportLink>
              </div>
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
