/**
 * The unified display page's Select Version section body (issue #167,
 * docs/proposals/proposal-h-unified-display-page.md §4.4′) - the embedded-only replacement for
 * GridSelectorResults/CardResultSet inside DisplayPage.tsx's "Choose Image" accordion section.
 * `GridSelectorModal.tsx`'s own modal variant (used by CardSlot.tsx's editor grid, unchanged by
 * this task per its own scope) is untouched - this component is mounted from exactly one place,
 * DisplayPage.tsx's SelectVersionSection.
 *
 * Structure follows the spec's three ordered groups (canonical grouped-by-printing, non-canonical
 * grouped-by-reason-tag, unknown) via selectVersionGrouping.ts's pure grouping function.
 *
 * Owner fix round (2026-07-23, "keep the ordering, but drop the separator please"): the DOM
 * ordering canonical -> non-canonical -> unknown is UNCHANGED (still selectVersionGrouping.ts's
 * own ordering, untouched) - only the `mb-2` bottom margin each per-group wrapper div
 * (`renderPrintingGroup`/`renderReasonTagGroup`, below) used to carry between one group and the
 * next was dropped, so the rail reads as one continuous grid with no visible gap/seam at a group
 * boundary. No aria/role grouping semantics existed on these wrapper divs to begin with (checked
 * directly - they carry only `data-testid`/`data-status`/`data-requested`, no `role="group"` or
 * `aria-label`), so there was nothing accessibility-bearing to preserve in an invisible form.
 *
 * FUNNEL round (funnel-spec.md F1-F7, D20-D24) - the `layout="stacked"` branch is now the
 * left-rail art-picker FUNNEL: one vertical column of head (F1) -> per-axis segmented chips
 * (F2/F3) -> advanced filters (E4, unchanged) -> implicit-vote awareness line (F4a) -> the
 * count-proportional survivors grid (F1/D21). The `layout="sidebar"` branch (today's one other
 * theoretical caller, the /editor GridSelectorModal - not actually wired anywhere today per the
 * spec's own ground-truth note) is BYTE-FOR-BYTE UNCHANGED: same flat FilterChipBar, same
 * two-tap ConfirmChip moment (c), no axis chips, no voteLayer effects at all - so if a future
 * caller ever passes `layout="sidebar"` (or omits `layout`), it gets exactly today's behavior.
 *
 * DEVIATION (documented, not silent - see this task's own report): the funnel spec's ground-truth
 * section describes chip filtering/membership as reading raw Scryfall fields via
 * `chip.matches()`/`filterCandidatesByChipStates` (attributeChips.ts), claiming this needs "ZERO
 * vote data." In this component's actual data (`CardDocument`, not `PrintingCandidate`), there is
 * no `borderColor`/`frame`/`fullArt`/etc field at all - see attributeChips.ts's own
 * `chipMembershipState` comment for the full explanation. Every axis chip here is therefore
 * SETTLED from `card.tags` and SUGGESTED from `card.suggestedFilterTagNames` (Tag-consensus
 * data), which is still a `votesOn`-gated read (the "suggested" half is only ever consulted
 * when a `voteLayer` is supplied) - so F5's votes-off guarantee (no SUGGESTED chip, no
 * vote-derived filtering) holds exactly as specified, just implemented against the real
 * available data rather than a `PrintingCandidate`-shaped one.
 *
 * FIX ROUND (owner-ratified condition 6, Tron's PR #329 review): the SUGGESTED read specifically
 * moved from `card.tagVoteStatuses` to `card.suggestedFilterTagNames` - `tagVoteStatuses` is a
 * source-agnostic collapse (both CONTESTED and UNRESOLVED read `"suggested"`, no implicit
 * exclusion, no weight floor), which let an implicit-only signal seed MORE implicit votes for
 * itself via F4b's cast-on-pick. `suggestedFilterTagNames` is the compliant, implicit-excluded,
 * floor-gated source - see attributeChips.ts's `chipMembershipState` comment for the full
 * reasoning. The SETTLED read (`card.tags`) is unaffected - resolved facts carry no such loop
 * risk.
 */
import styled from "@emotion/styled";
import React, { Ref, useEffect, useMemo, useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Collapse from "react-bootstrap/Collapse";
import Form from "react-bootstrap/Form";
import Row from "react-bootstrap/Row";
import ToggleButton from "react-bootstrap/ToggleButton";
import ToggleButtonGroup from "react-bootstrap/ToggleButtonGroup";
import { createPortal } from "react-dom";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { SortByOptions } from "@/common/constants";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  CardDocument,
  SortBy,
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import {
  ALL_ATTRIBUTE_CHIPS,
  AttributeChipDef,
  candidateSatisfiesAttributeTag,
  ChipMembershipState,
  chipMembershipState,
  ChipVoteState,
  FUNNEL_AXES,
  FunnelAxis,
  nextChipState,
} from "@/features/attributeChips/attributeChips";
import { MemoizedEditorCard } from "@/features/card/Card";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { useViewportTier } from "@/features/display/useViewportTier";
import { GridSelectorFilters } from "@/features/gridSelector/GridSelectorFilters";
import {
  groupSelectVersionCandidates,
  RequestedPrinting,
  SelectVersionPrintingGroup,
  SelectVersionReasonTagGroup,
} from "@/features/gridSelector/selectVersionGrouping";
import { GridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { FilterSettings as FilterSettingsElement } from "@/features/searchSettings/FilterSettings";
import { GenericErrorPage } from "@/features/ui/GenericErrorPage";
import { APISubmitTagVote } from "@/store/api";
import { selectCardDocumentsByIdentifiers } from "@/store/slices/cardDocumentsSlice";
import { setNotification } from "@/store/slices/toastsSlice";

const ATTRIBUTE_TAG_NAMES = new Set(
  ALL_ATTRIBUTE_CHIPS.map((chip) => chip.tagName)
);

/**
 * Matches on resolved OR suggested per active tag - see this file's own module comment for why
 * a resolved-only filter would make moment (c)'s confirm chip unreachable. Sidebar/modal layout
 * only - the funnel (stacked) uses `candidateSatisfiesAttributeTag` (votesOn-gated) instead.
 */
function filterByActiveAttributeTags(
  identifiers: Array<string>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  activeTagNames: Set<string>
): Array<string> {
  if (activeTagNames.size === 0) {
    return identifiers;
  }
  return identifiers.filter((identifier) => {
    const card = cardDocumentsByIdentifier[identifier];
    if (card == null) {
      return false;
    }
    return Array.from(activeTagNames).every(
      (tagName) =>
        card.tags.includes(tagName) ||
        card.tagVoteStatuses?.[tagName] === "suggested"
    );
  });
}

/**
 * Funnel-only: identical shape to `filterByActiveAttributeTags` above but gated on `votesOn`
 * (F5) - see `candidateSatisfiesAttributeTag`'s own comment.
 */
function filterByChipsVotesGated(
  identifiers: Array<string>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  activeTagNames: Set<string>,
  votesOn: boolean
): Array<string> {
  if (activeTagNames.size === 0) {
    return identifiers;
  }
  return identifiers.filter((identifier) => {
    const card = cardDocumentsByIdentifier[identifier];
    if (card == null) {
      return false;
    }
    return Array.from(activeTagNames).every((tagName) =>
      candidateSatisfiesAttributeTag(card, tagName, votesOn)
    );
  });
}

/**
 * Unified Frame + Treatment filter (SPEC-display-left-rail.md §6, addendum item 1) - the
 * Treatment axis's tri-state EXCLUDE half. Border/Frame stay purely positive/exclusive (a radio
 * segment can only ever mean "must be this one"), so `activeAttributeTags`'s existing semantics
 * are untouched by this function entirely - this only ever narrows further by DROPPING any
 * candidate that satisfies an excluded tag, additive to whatever the positive filter already
 * kept. Stacked (funnel) layout only, same `votesOn` gating as the positive filter.
 */
function filterOutExcludedChipsVotesGated(
  identifiers: Array<string>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  excludedTagNames: Set<string>,
  votesOn: boolean
): Array<string> {
  if (excludedTagNames.size === 0) {
    return identifiers;
  }
  return identifiers.filter((identifier) => {
    const card = cardDocumentsByIdentifier[identifier];
    if (card == null) {
      return true;
    }
    return !Array.from(excludedTagNames).some((tagName) =>
      candidateSatisfiesAttributeTag(card, tagName, votesOn)
    );
  });
}

/**
 * A SearchQuery whose expansionCode/collectorNumber name the representative's OWN
 * suggestedCanonicalCard - not the slot's real search query. This is what lets
 * DeckbuilderConfirmAffordance's existing gate (`isUnconfirmedCanonicalImport`, unchanged) fire
 * correctly for a card in this grid rather than the slot's own selected image: that gate reduces
 * to "query names a printing AND getPrintingMatchLabel returns null", and getPrintingMatchLabel
 * always returns null while printingTagStatus isn't Resolved - exactly the condition that makes
 * suggestedCanonicalCard populated in the first place. No fork of the component needed.
 */
function synthesizeSuggestedPrintingQuery(card: CardDocument):
  | {
      cardType: CardDocument["cardType"];
      query: null;
      expansionCode?: string;
      collectorNumber?: string;
    }
  | undefined {
  if (card.suggestedCanonicalCard == null) {
    return undefined;
  }
  return {
    cardType: card.cardType,
    query: null,
    expansionCode: card.suggestedCanonicalCard.expansionCode,
    collectorNumber: card.suggestedCanonicalCard.collectorNumber,
  };
}

//# region moment (b) - plain filter-chip bar (sidebar/modal layout only, unchanged)

const FilterChip = styled.button<{ active: boolean }>`
  border: 2px solid rgba(0, 0, 0, 0.25);
  border-radius: 0.5rem;
  background-color: ${(props) =>
    props.active ? "rgba(13, 110, 253, 0.25)" : "transparent"};
  color: inherit;
  padding: 0.3rem 0.55rem;
  font-size: 0.8rem;
  white-space: nowrap;
  min-height: 38px;
  display: inline-flex;
  align-items: center;
`;

const FilterChipRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.5rem;
`;

interface FilterChipBarProps {
  activeTagNames: Set<string>;
  onToggle: (tagName: string) => void;
}

function FilterChipBar({ activeTagNames, onToggle }: FilterChipBarProps) {
  const getTagDisplayName = useTagDisplayName();
  return (
    <FilterChipRow data-testid="select-version-filter-chip-bar">
      {ALL_ATTRIBUTE_CHIPS.map((chip: AttributeChipDef) => (
        <FilterChip
          key={chip.tagName}
          type="button"
          active={activeTagNames.has(chip.tagName)}
          onClick={() => onToggle(chip.tagName)}
          data-testid={`select-version-filter-chip-${chip.tagName}`}
          data-active={activeTagNames.has(chip.tagName)}
        >
          {getTagDisplayName(chip.label)}
        </FilterChip>
      ))}
    </FilterChipRow>
  );
}

//# endregion

//# region moment (c) - filtered-selection confirm chip (sidebar/modal layout only, unchanged)

interface ConfirmChipProps {
  backendURL: string;
  cardIdentifier: string;
  tagName: string;
  onResolved: () => void;
}

function ConfirmChip({
  backendURL,
  cardIdentifier,
  tagName,
  onResolved,
}: ConfirmChipProps) {
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  const [submitting, setSubmitting] = useState(false);

  const cast = () => {
    setSubmitting(true);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      1,
      "same-origin",
      "select-version"
    )
      .then(() => onResolved())
      .catch((error) => {
        if (isRateLimited(error)) {
          onResolved();
          return;
        }
        dispatch(
          setNotification([
            Math.random().toString(),
            errorToNotification(error, {
              name: "Vote failed",
              message:
                "Something went wrong submitting your tag - please try again.",
            }),
          ])
        );
      })
      .finally(() => setSubmitting(false));
  };

  return (
    <div
      className="d-flex align-items-center gap-1 small mt-1"
      data-testid={`select-version-confirm-chip-${cardIdentifier}-${tagName}`}
    >
      <span>Looks {getTagDisplayName(tagName).toLowerCase()}?</span>
      <Button
        size="sm"
        variant="outline-success"
        disabled={submitting}
        onClick={cast}
        data-testid={`select-version-confirm-chip-yes-${cardIdentifier}-${tagName}`}
      >
        ✓
      </Button>
      <Button
        size="sm"
        variant="outline-secondary"
        disabled={submitting}
        onClick={onResolved}
        data-testid={`select-version-confirm-chip-dismiss-${cardIdentifier}-${tagName}`}
      >
        ✕
      </Button>
    </div>
  );
}

//# endregion

//# region F5 - the vote-layer seam (funnel/stacked layout only)

/**
 * funnel-spec.md F5/F7.2 - the single, additive, optional prop bundle the vote layer attaches
 * through. `undefined` (any caller that doesn't supply it) => the base funnel: no SUGGESTED
 * chips, no awareness line, no implicit vote on pick, no reset/ack - a complete metadata-only
 * filter UI (F5's "adoption requirement"). DisplayPage.tsx is the one caller that supplies this
 * today, wiring `onImplicitSupport` to `APICastImplicitVote`/`APIRetractImplicitVote`.
 */
export interface VoteLayerProps {
  /** F4b/c/d - called on EVERY pick while this component's layout is "stacked" (even when
   * `supportTagNames` is empty), so the caller can retract whatever it cast for the slot's
   * PREVIOUS pick (F4d) before casting `supportTagNames` for the new one (F4b). `candidate` is
   * the identifier just picked; `supportTagNames` is already restricted to the active tags this
   * specific candidate satisfies ONLY via an unconfirmed vote (not yet in `card.tags`) - the
   * exact "don't re-vote a settled fact" gate F4b describes. */
  onImplicitSupport: (candidate: string, supportTagNames: string[]) => void;
  /** F3 state-2 read - tag names `card` satisfies only via an unconfirmed, machine-suggested
   * vote (not a resolved fact). Never called at all when this layer is absent (F5). */
  suggestedTagNames: (card: CardDocument) => string[];
  /** F4a - the awareness-line copy naming the tags at stake, shown before a pick. */
  awarenessCopy: (activeTagNames: string[]) => string;
}

// D21 (owner-ratified 2026-07-22): count-proportional disclosure thresholds, shipped as named
// constants so post-launch tuning is a one-line change, not a magic number in the tier picker.
export const FUNNEL_DENSE_ABOVE = 8;
export const FUNNEL_HERO_AT_OR_BELOW = 2;

export type FunnelDisclosureTier = "dense" | "medium" | "hero" | "none";

export function funnelDisclosureTier(
  survivorCount: number
): FunnelDisclosureTier {
  if (survivorCount === 0) return "none";
  if (survivorCount > FUNNEL_DENSE_ABOVE) return "dense";
  if (survivorCount <= FUNNEL_HERO_AT_OR_BELOW) return "hero";
  return "medium";
}

// Owner fix round (2026-07-23, "the elements of the cardpicker are too large still" - issue
// #302's sitewide retheme, /display reference density): `dense` stays pinned to the
// owner-approved editor-completion mockup's own `.version-grid .card63` value (72px) - that one
// has real design-doc grounding. `medium`/`hero` had none (invented during the funnel round,
// F1/D21) and had drifted well past what the rail's own ~380px width needs for legibility -
// tightened down (104px->88px, 150px->112px) so more tiles fit per row and a `hero`-tier
// single/pair-survivor pick isn't dramatically larger than everything else in the pane.
const FUNNEL_TIER_TILE_WIDTH_REM: Record<
  Exclude<FunnelDisclosureTier, "none">,
  number
> = {
  dense: 4.5,
  medium: 5.5,
  hero: 7,
};

// F3 - dashed accent border + trailing glyph for a SUGGESTED chip; solid/plain otherwise. Reuses
// the theme accent (`#df6919`) already used everywhere else in the funnel, matching the mockup's
// reference styling (funnel-mockup.html's `.seg.suggested`).
const FUNNEL_SUGGESTED_STYLE: React.CSSProperties = {
  borderStyle: "dashed",
  borderColor: "#df6919",
};

const AckLine = styled.div`
  color: #a7e08a;
`;

const AwarenessLine = styled.div`
  border-left: 2px solid #df6919;
  padding-left: 0.5rem;
  color: #aab7c4;
`;

//# endregion

//# region owner fix round (2026-07-23, "the buttons are too big") - compact controls
//
// Every plain react-bootstrap `Button`/`ToggleButton` in the stacked (funnel) layout inherited
// Bootstrap `size="sm"`'s own padding/line-height (measured live: ~31px tall, ~21px line-height
// alone), which reads oversized next to the #302 fix round's now-compact ~72-112px tiles and the
// #302-approved reference mockup's own flat, low-chrome `.btn` controls (the mockup's "Filters"
// disclosure isn't even a bordered button - it's plain underlined text: `14 results · <u>
// Filters</u>`, `responsive-layout-2026-07-21.html` line 435). These three thin `styled()` wraps
// tighten padding/font-size/line-height to match, scoped to ONLY the specific call sites below
// (the sidebar/modal layout `GridSelectorModal.tsx` owns - a byte-for-byte-unchanged, entirely
// separate return path per this file's own top comment - never renders through these).
//
// Touch target (WCAG 2.5.5-style): shrinking a button's PAINTED box below ~40px on a touch
// breakpoint would shrink its real tap target too - instead of that, `position: relative` +
// an invisible `::after` (`inset: -12px`, no fill/border/content) pads the ACTUAL clickable box
// out to >=40px on touch breakpoints only (`max-width: 767.98px`, this file's/DisplayPage's own
// existing phone-breakpoint convention) while the visual size stays reference-sized at every
// breakpoint. Verified live (Playwright `getBoundingClientRect`/`getComputedStyle(el, "::after")`
// at a 390px viewport): the smallest painted control here (the "+N more" expand link, ~15px
// tall) reaches a ~39-40px effective tap box with this inset. The `::after` is generated content
// INSIDE the button's own box (not a sibling wrapper), so it inherits the button's click handling
// for free - no extra JS needed.
const touchExpandTapArea = `
  position: relative;

  @media (max-width: 767.98px) {
    &::after {
      content: "";
      position: absolute;
      inset: -12px;
    }
  }
`;

/** Filters disclosure toggle - the corrected mockup's own `.btn-sm` binding row (owner ruling,
 * 2026-07-23, superseding this file's earlier "the buttons are too big" shrink for THIS control
 * specifically - real Bootstrap `sm` metrics, not the smaller invented values). This styled
 * component has exactly one call site (the Filters toggle below) so the fix is already
 * component-scoped - it does NOT touch `CompactToggleButton`/`CompactLinkButton`/`TreatmentChip`
 * below, which bind to their OWN distinct, still-in-force spec rows ("Filter segment group .seg"
 * 11px, "Treatment tri-state chip" 11px) - see each one's own doc comment. */
const CompactButton = styled(Button)`
  padding: 4px 8px;
  font-size: 14px;
  line-height: 1.2;
  ${touchExpandTapArea}
`;

/** Per-axis segmented chips (FunnelAxisRow) - same treatment, kept as its own styled component
 * (rather than reusing CompactButton) since `ToggleButtonGroup` requires `ToggleButton` specifically,
 * not a plain `Button`. */
const CompactToggleButton = styled(ToggleButton)`
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  line-height: 1.2;
  ${touchExpandTapArea}
`;

/** "+N more of this printing" / "Show fewer" / "More like this" - already the reference's
 * borderless/no-background link shape (`variant="link"` + Bootstrap's `p-0` utility already
 * zeroes their padding); only the font-size needed tightening to match the reference's smaller
 * auxiliary-control scale and to stop "More like this" wrapping to two lines in a narrow tile. */
const CompactLinkButton = styled(Button)`
  font-size: 0.7rem;
  line-height: 1.2;
  ${touchExpandTapArea}
`;

/** Unified Frame + Treatment filter (§6) - a tri-state chip (untouched/include/exclude, cycled
 * via `nextChipState` - same cycle `useTagVoting.ts` already uses elsewhere, reused here for the
 * cycle order only, not the vote-submission side of that hook, since this is a pure client-side
 * FILTER, not a vote - see this file's own `TreatmentChipRow` comment). Real `<button>`, not a
 * link (§8's buttons-look-like-buttons rule - this performs an action, filtering). */
const TreatmentChip = styled.button<{ $state: ChipVoteState }>`
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border: 1px solid #6b7d8e;
  background: transparent;
  color: #ebebeb;
  display: inline-flex;
  gap: 3px;
  align-items: center;
  ${touchExpandTapArea}
  ${(props) =>
    props.$state === "positive"
      ? "border-color:#5cb85c;background:rgba(92,184,92,.22);color:#bfe6ad;"
      : props.$state === "negative"
      ? "border-color:#d9534f;background:rgba(217,83,79,.22);color:#f0b3b1;text-decoration:line-through;"
      : ""}
`;

/** A thin vertical rule separating Frame's segmented control from Treatment's chip row within
 * the one shared `.ufilter` block (§6's ASCII diagram). O1 fix round (SPEC-display-left-rail.md
 * §D.1, corrected 2026-07-23) - the mockup's own `.ufilter .divider{background:var(--divider)}`
 * maps this to the normalized `#16202b` rail-boundary hairline, not the unthemed
 * `rgba(0,0,0,.22)` this used to hardcode. */
const UnifiedFilterDivider = styled.span`
  align-self: stretch;
  width: 1px;
  background: #16202b;
  margin: 0 2px;
`;

/**
 * Rail-delegacy round (RD4/O3, SPEC-rail-delegacy.md) - the desktop/tablet Filters float panel is
 * rendered via `ReactDOM.createPortal(..., document.body)`, not a plain in-tree `position:fixed`
 * node: `LeftRailOffcanvas` (DisplayPage.tsx) is `position:sticky` at the inline `lg`+ breakpoint,
 * which unconditionally establishes its own stacking context (CSS spec - sticky positioning
 * always does, regardless of its own `z-index`) - any `position:fixed` descendant's `z-index`
 * would only be compared against ITS siblings inside that local context, not the page-level sheet
 * region, so a plain fixed node stayed BEHIND the sheet's own card tiles (caught live: Playwright
 * couldn't click through to the backdrop, the tile intercepted the click). A real portal escapes
 * every ancestor stacking context entirely, matching the spec's own "frame-level Overlay, escaping
 * the 380px rail column and the tablet drawer's own clipping" requirement literally, not just in
 * effect. Every class name below duplicates the same tokens `RailRoot`'s own `.fpanel.inline`
 * (phone, still in-tree) rule carries in DisplayPage.tsx - see `SPEC-rail-delegacy.md` §D.2, kept
 * in lockstep the same way any other two-container "shared body" pairing in this codebase is.
 */
const FloatFiltersPortalRoot = styled.div`
  .fscrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 1050;
  }
  .fpanel.float {
    position: fixed;
    left: 50%;
    top: 64px;
    transform: translateX(-50%);
    width: 440px;
    max-width: calc(100% - 32px);
    max-height: calc(100% - 96px);
    overflow-y: auto;
    z-index: 1051;
    background: #22303f;
    border: 1px solid #7f8fa0;
    box-shadow: 0 12px 34px rgba(0, 0, 0, 0.6);
    padding: 0;
  }
  .fpanel.float .fpwrap {
    padding: 12px;
  }
  .fptitle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: #4e5d6b;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    position: sticky;
    top: 0;
  }
  .fptitle button {
    background: transparent;
    border: 1px solid rgba(235, 235, 235, 0.2);
    color: #ebebeb;
    padding: 2px 8px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
  }
  .fset {
    border: none;
    margin: 0 0 9px;
    padding: 0;
  }
  .fset:last-child {
    margin-bottom: 0;
  }
  .fset > .lg {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #8fa0b0;
    margin-bottom: 4px;
  }
  .fsep {
    height: 1px;
    background: #16202b;
    margin: 9px -8px;
  }
  .implicit-note {
    font-size: 10px;
    color: #8fa0b0;
    margin-top: 7px;
    display: flex;
    gap: 5px;
    align-items: flex-start;
    line-height: 1.4;
  }
  .implicit-note .ic {
    color: #5bc0de;
    flex: 0 0 auto;
  }
`;

//# endregion

//# region continuous grid (addendum item 2) - tile-corner annotations

/** Wraps `MemoizedEditorCard` so the annotation badges below can position themselves relative to
 * the card's own image box, not the tile's outer `p-1`-padded wrapper. Stacked layout only. */
const TileImageWrap = styled.div`
  position: relative;
`;

// Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - alpha
// normalized `.9` -> `.92` matching the D.1 table's literal `rgba(...,.92)` for all three
// variants ("Tile ✓ canonical tag"/"Tile Alt tag"/"Tile ? unknown tag").
const CORNER_TAG_COLORS: Record<"canon" | "alt" | "unk", string> = {
  canon: "rgba(92,184,92,.92)",
  alt: "rgba(91,192,222,.92)",
  unk: "rgba(120,135,150,.92)",
};

/** Group-membership corner tag (canonical ✓ / non-canonical Alt / unknown ?) - replaces the old
 * between-group header row entirely (owner: "read as ONE grid," zero visual partitioning). */
const CornerTag = styled.span<{ $variant: "canon" | "alt" | "unk" }>`
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
  /* Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - was 0.5rem
     (8px); the D.1 table's own binding value for every corner tag variant is 7px. */
  font-size: 7px;
  font-weight: 800;
  letter-spacing: 0.03em;
  padding: 0 3px;
  color: #fff;
  text-transform: uppercase;
  background: ${(props) => CORNER_TAG_COLORS[props.$variant]};
`;

/** The slot's own requested printing - sorts first (selectVersionGrouping.ts); a distinct corner
 * from `CornerTag` (top-right, not top-left) so the two can coexist on the same tile without
 * colliding when the requested printing also happens to still be a suggested (unconfirmed) one. */
const ReqBadge = styled.span`
  position: absolute;
  top: 0;
  right: 0;
  z-index: 1;
  background: #df6919;
  color: #fff;
  font-size: 0.5rem;
  font-weight: 800;
  padding: 0 3px;
`;

/** F3's "survived only via a suggested/unconfirmed tag" signal - used to be a standalone
 * "⌇ suggested" text row under the tile; folded into a small corner marker instead (bottom-left,
 * the one corner `CornerTag`/`ReqBadge`/the confirm ribbon below don't already use). */
const SuggestedMarker = styled.span`
  position: absolute;
  bottom: 0;
  left: 0;
  z-index: 1;
  font-size: 0.55rem;
  color: #df6919;
  background: rgba(0, 0, 0, 0.55);
  padding: 0 3px;
`;

/** Suggested-printing confirm affordance (moment a), scaled into a bottom-right tile-corner
 * overlay instead of a full-width `Confirm?`/Y·N block below the tile. Wraps the REAL, completely
 * unmodified `DeckbuilderConfirmAffordance` (no internals touched, per this task's own file-list
 * scope) - `transform: scale()` is a pure visual shrink, its hover/click/vote behavior is
 * identical to every other mount of that component. */
const ConfirmRibbonWrap = styled.div`
  position: absolute;
  bottom: -2px;
  right: -2px;
  z-index: 2;
  transform: scale(0.72);
  transform-origin: bottom right;
`;

/** Inline ghost tile - "+N more of this printing" (collapsed) / "Show fewer" (expanded), same
 * footprint as a real candidate tile so it flows in the SAME flex-wrap grid rather than a
 * full-width row breaking it (§7's hard requirement). A real `button`, per §8. */
const GhostTile = styled.button<{ $widthRem: number }>`
  width: ${(props) => props.$widthRem}rem;
  aspect-ratio: 63 / 88;
  flex: 0 0 auto;
  background: transparent;
  outline: 1px dashed #abb6c2;
  border: none;
  color: #abb6c2;
  font-size: 0.65rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  /* Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - this is a
     real button element (buttons-look-like-buttons audit, §8/#5), so without an explicit reset
     it carries the browser's own UA-stylesheet button padding (roughly 1px 6px in Chromium)
     instead of the flush zero padding the spec's ghost tile assumes (the mockup's own demo
     markup used a plain span with role=button, which has no such UA default - not a real
     discrepancy to preserve). */
  padding: 0;
  ${touchExpandTapArea}
`;

//# endregion

//# region F2/F3 - per-axis segmented chips

interface FunnelAxisRowProps {
  axis: FunnelAxis;
  activeTagNames: Set<string>;
  membershipByTagName: Record<string, ChipMembershipState>;
  onAxisChange: (axis: FunnelAxis, nextValue: string | string[]) => void;
  getTagDisplayName: (tagName: string) => string;
  /** CSS-fidelity pass (2026-07-23) - this row div doubles as BOTH the Border axis's own
   * standalone `.ufilter .row` (mockup: `margin-bottom:5px`, since it's not the fieldset's last
   * row) AND, nested, the Frame half of the shared Frame+Treatment row (mockup: no margin of its
   * own - `frame-treatment-row`, the actual last `.row`, owns the `margin-bottom:0`). A single
   * hardcoded margin on this component would be right for one call site and wrong for the other;
   * each call site supplies its own via this optional passthrough (undefined -> 0, matching the
   * nested/nothing-to-add case). */
  rowStyle?: React.CSSProperties;
}

function FunnelAxisRow({
  axis,
  activeTagNames,
  membershipByTagName,
  onAxisChange,
  getTagDisplayName,
  rowStyle,
}: FunnelAxisRowProps) {
  const visibleChips = axis.chips.filter(
    (chip) => membershipByTagName[chip.tagName] != null
  );
  if (visibleChips.length === 0) {
    // F3 - "only axes with >=1 surviving candidate render."
    return null;
  }

  const radioValue =
    visibleChips.find((chip) => activeTagNames.has(chip.tagName))?.tagName ??
    "";
  const checkboxValue = visibleChips
    .filter((chip) => activeTagNames.has(chip.tagName))
    .map((chip) => chip.tagName);

  return (
    <div
      className="d-flex align-items-center flex-wrap"
      // CSS-fidelity pass (2026-07-23, SPEC-display-left-rail.md §6/§2) - `gap-2` (0.5rem/8px)
      // was never the mockup's actual value: `.ufilter .row{gap:6px}` - a literal px value with
      // no exact Bootstrap spacing-scale match (gap-1=4px, gap-2=8px), so it's set directly
      // rather than approximated through a utility class, same as every other exact-px value
      // already inline throughout this rail (`.d14`/`.ufilter` padding, etc).
      style={{ gap: "6px", marginBottom: 0, ...rowStyle }}
      data-testid={`funnel-axis-${axis.id}`}
    >
      <span
        className="text-muted text-uppercase"
        style={{ flex: "0 0 58px", fontSize: "10px", letterSpacing: "0.05em" }}
      >
        {axis.label}
      </span>
      <ToggleButtonGroup
        type={axis.exclusive ? "radio" : "checkbox"}
        name={`funnel-axis-${axis.id}`}
        // react-bootstrap's radio/checkbox ToggleButtonGroup value shape differs by type - both
        // are supported by the same prop, the type union just needs a cast at this call site.
        value={(axis.exclusive ? radioValue : checkboxValue) as never}
        onChange={(nextValue: string | string[]) =>
          onAxisChange(axis, nextValue)
        }
      >
        {visibleChips.map((chip) => {
          const membership = membershipByTagName[chip.tagName];
          const suggested = membership === "suggested";
          const active = activeTagNames.has(chip.tagName);
          return (
            <CompactToggleButton
              key={chip.tagName}
              id={`funnel-chip-${chip.tagName}`}
              value={chip.tagName}
              variant="outline-secondary"
              size="sm"
              data-testid={`funnel-chip-${chip.tagName}`}
              data-chip-membership={membership}
              data-active={active}
              style={suggested ? FUNNEL_SUGGESTED_STYLE : undefined}
              title={
                suggested
                  ? "Our catalog leans this way but hasn't confirmed it - picking supports it"
                  : undefined
              }
              // D23 - re-tapping the already-active segment of an EXCLUSIVE axis clears it back
              // to "any": a native radio input doesn't fire a change event for a click on an
              // already-checked option, so this has to be handled on click, ahead of (and
              // independent from) ToggleButtonGroup's own onChange.
              onClick={() => {
                if (axis.exclusive && activeTagNames.has(chip.tagName)) {
                  onAxisChange(axis, "");
                }
              }}
            >
              {getTagDisplayName(chip.tagName)}
              {suggested && (
                <span className="ms-1" aria-hidden="true">
                  ⌇
                </span>
              )}
            </CompactToggleButton>
          );
        })}
      </ToggleButtonGroup>
    </div>
  );
}

/**
 * Unified Frame + Treatment filter (§6, addendum item 1) - Treatment's own tri-state row, kept
 * as its own component (not folded into `FunnelAxisRow`) since it needs a THIRD state
 * (exclude) that axis's radio/checkbox `ToggleButtonGroup` has no notion of - a `checkbox`
 * group is binary (active or not), never tri-state. Cycle order (untouched -> include -> exclude
 * -> untouched) is `attributeChips.ts`'s own `nextChipState` - the taxonomy's single source of
 * truth for it, reused here for the cycle only (this is a pure client-side FILTER, not a vote).
 */
interface TreatmentChipRowProps {
  axis: FunnelAxis;
  activeTagNames: Set<string>;
  excludedTagNames: Set<string>;
  membershipByTagName: Record<string, ChipMembershipState>;
  onCycle: (tagName: string) => void;
  getTagDisplayName: (tagName: string) => string;
}

function TreatmentChipRow({
  axis,
  activeTagNames,
  excludedTagNames,
  membershipByTagName,
  onCycle,
  getTagDisplayName,
}: TreatmentChipRowProps) {
  const visibleChips = axis.chips.filter(
    (chip) => membershipByTagName[chip.tagName] != null
  );
  if (visibleChips.length === 0) {
    return null;
  }

  return (
    <div
      // CSS-fidelity pass (2026-07-23) - see FunnelAxisRow's own comment on the same exact-6px
      // `gap-2` (8px) mismatch; this row shares the fieldset's `.ufilter .row{gap:6px}` value.
      className="d-flex align-items-center flex-wrap"
      style={{ gap: "6px" }}
      data-testid={`funnel-axis-${axis.id}`}
    >
      <span
        className="text-muted text-uppercase"
        // Mockup's Treatment `.rl` keeps the shared `.ufilter .rl` font-size/letter-spacing but
        // overrides width to `flex:0 0 auto` (no fixed label column, unlike Border/Frame) - kept
        // as the implicit default here (no `flex` set at all).
        style={{ fontSize: "10px", letterSpacing: "0.05em" }}
      >
        {axis.label}
      </span>
      {visibleChips.map((chip) => {
        const membership = membershipByTagName[chip.tagName];
        const suggested = membership === "suggested";
        const chipState: ChipVoteState = activeTagNames.has(chip.tagName)
          ? "positive"
          : excludedTagNames.has(chip.tagName)
          ? "negative"
          : "untouched";
        const glyph =
          chipState === "positive" ? "+" : chipState === "negative" ? "−" : "·";
        const stateLabel =
          chipState === "positive"
            ? "included"
            : chipState === "negative"
            ? "excluded"
            : "not filtered";
        return (
          <TreatmentChip
            key={chip.tagName}
            type="button"
            $state={chipState}
            data-testid={`funnel-treatment-chip-${chip.tagName}`}
            data-chip-membership={membership}
            data-state={chipState}
            aria-pressed={chipState === "positive"}
            aria-label={`${getTagDisplayName(chip.tagName)}: ${stateLabel}`}
            title={
              suggested
                ? "Our catalog leans this way but hasn't confirmed it - picking supports it"
                : undefined
            }
            onClick={() => onCycle(chip.tagName)}
          >
            <span aria-hidden="true">{glyph}</span>
            {getTagDisplayName(chip.tagName)}
            {suggested && (
              <span className="ms-1" aria-hidden="true">
                ⌇
              </span>
            )}
          </TreatmentChip>
        );
      })}
    </div>
  );
}

//# endregion

//# region shared tile

interface SelectVersionTileProps {
  identifier: string;
  headerLabel: string;
  card: CardDocument | undefined;
  selectedImage: string | undefined;
  compressed: boolean;
  tileWidthRem: number | undefined;
  onSelect: (identifier: string) => void;
  showConfirmAffordance: boolean;
  showTwoTapConfirm: boolean;
  activeAttributeTags: Set<string>;
  dismissedConfirmChipKeys: Set<string>;
  onDismissConfirmChip: (key: string) => void;
  onMoreLikeThis: (identifier: string) => void;
  backendURL: string;
  showSuggestedBadge: boolean;
  /** Addendum item 2 (continuous grid) - everything below is stacked-layout-only annotation
   * data; the sidebar/modal layout never sets any of it and renders exactly as before (see each
   * prop's own render-site comment for the byte-for-byte-preserved branch). */
  layout: "sidebar" | "stacked";
  cornerTag?: { label: string; variant: "canon" | "alt" | "unk" };
  requested?: boolean;
  ariaLabel?: string;
}

function SelectVersionTile({
  identifier,
  headerLabel,
  card,
  selectedImage,
  compressed,
  tileWidthRem,
  onSelect,
  showConfirmAffordance,
  showTwoTapConfirm,
  activeAttributeTags,
  dismissedConfirmChipKeys,
  onDismissConfirmChip,
  onMoreLikeThis,
  backendURL,
  showSuggestedBadge,
  layout,
  cornerTag,
  requested,
  ariaLabel,
}: SelectVersionTileProps) {
  const hasFilterableTags =
    card != null &&
    card.tags.some((tagName) => ATTRIBUTE_TAG_NAMES.has(tagName));
  const stacked = layout === "stacked";

  // moment (c): sidebar/modal layout only (showTwoTapConfirm) - only for the just-selected card,
  // only for active filter tags this specific card hasn't already resolved (a resolved match
  // wouldn't need confirming), and only once per card+tag until dismissed/cast this component's
  // own lifetime. D20 retires this two-tap confirm on the funnel (stacked) surface - the pick
  // itself is the vote there (see onImplicitSupport in the top-level component below).
  const suggestedActiveTagNames =
    showTwoTapConfirm && card != null && selectedImage === identifier
      ? Array.from(activeAttributeTags).filter(
          (tagName) =>
            card.tagVoteStatuses?.[tagName] === "suggested" &&
            !card.tags.includes(tagName) &&
            !dismissedConfirmChipKeys.has(`${identifier}:${tagName}`)
        )
      : [];

  const hasConfirmAffordance = showConfirmAffordance && card != null;
  const confirmAffordanceElement = hasConfirmAffordance && card != null && (
    <DeckbuilderConfirmAffordance
      cardIdentifier={identifier}
      searchQuery={synthesizeSuggestedPrintingQuery(card)}
      // No separate grid/modal to open from here - this tile IS already inside the picker
      // (see the module comment). NO still marks the affordance resolved-for-this-session
      // via the component's own unchanged logic; there is simply nothing further to open.
      onOpenGridSelector={() => undefined}
    />
  );

  return (
    <div
      className="p-1"
      // Fix round (owner live-review, "Select Version has oversized dropdowns") - `width:
      // "auto"` here was a no-op: a plain block-level `<div>` in normal flow with
      // `width: auto` fills its containing block exactly the same as one with no width
      // declared at all (only flex/grid items, floats, or absolutely-positioned boxes actually
      // shrink-to-fit on `auto` - a static block never does). Since this tile's own caller
      // (renderPrintingGroup/renderReasonTagGroup/the unknown-group map, below) never wrapped
      // multiple tiles in a shared row before this fix, every tile rendered at the FULL width
      // of its rail column - confirmed live via a real screenshot + getBoundingClientRect(): a
      // single candidate tile spanning ~300px of a ~380px rail, each on its own full-width row.
      // A real fixed width fixes the tile itself regardless of what row/flex context wraps it -
      // F1/D21 (funnel round) makes this width count-proportional instead of a single constant;
      // `flex: 0 0 auto` keeps it from being stretched or shrunk if a flex-row parent (see
      // below) ever tries to redistribute space among its siblings.
      style={
        compressed || tileWidthRem != null
          ? { width: `${tileWidthRem ?? 4.5}rem`, flex: "0 0 auto" }
          : { width: undefined }
      }
      // Addendum item 2 A11y - the continuous grid is `role="list"` (see the stacked render
      // below); each tile is a `listitem` carrying an aria-label that spells out the group +
      // requested/suggested status the corner tags convey visually, so that semantics survives
      // for a screen reader even though the between-group separator rows are gone.
      role={stacked ? "listitem" : undefined}
      aria-label={stacked ? ariaLabel : undefined}
      data-testid={`select-version-tile-${identifier}`}
    >
      <TileImageWrap>
        <MemoizedEditorCard
          imageIdentifier={identifier}
          cardHeaderTitle={headerLabel}
          cardOnClick={() => onSelect(identifier)}
          noResultsFound={false}
          highlight={identifier === selectedImage}
          compressed={compressed}
        />
        {/* Addendum item 2 - group membership / requested / suggested-survivor are tile-corner
            annotations here (stacked layout only), not the separate rows the sidebar/modal
            layout below still renders. */}
        {stacked && cornerTag != null && (
          <CornerTag
            $variant={cornerTag.variant}
            data-testid={`select-version-tile-corner-${identifier}`}
          >
            {cornerTag.label}
          </CornerTag>
        )}
        {stacked && requested && (
          <ReqBadge data-testid={`select-version-tile-req-${identifier}`}>
            REQ
          </ReqBadge>
        )}
        {stacked && showSuggestedBadge && (
          <SuggestedMarker
            aria-hidden="true"
            data-testid={`select-version-suggested-badge-${identifier}`}
          >
            ⌇
          </SuggestedMarker>
        )}
        {stacked && hasConfirmAffordance && (
          <ConfirmRibbonWrap
            data-testid={`select-version-confirm-ribbon-${identifier}`}
          >
            {confirmAffordanceElement}
          </ConfirmRibbonWrap>
        )}
      </TileImageWrap>
      {/* Sidebar/modal layout only below - byte-for-byte the original rendering (full-width rows
          under the tile), since GridSelectorModal.tsx's own caller must stay unchanged. */}
      {!stacked && showSuggestedBadge && (
        <div
          className="text-center small"
          style={{ color: "#df6919" }}
          data-testid={`select-version-suggested-badge-${identifier}`}
        >
          ⌇ suggested
        </div>
      )}
      {!stacked && confirmAffordanceElement}
      {!stacked && hasFilterableTags && (
        <div className="text-center">
          <CompactLinkButton
            size="sm"
            variant="link"
            className="p-0"
            onClick={() => onMoreLikeThis(identifier)}
            data-testid={`select-version-more-like-this-${identifier}`}
          >
            More like this
          </CompactLinkButton>
        </div>
      )}
      {suggestedActiveTagNames.map((tagName) => (
        <ConfirmChip
          key={tagName}
          backendURL={backendURL}
          cardIdentifier={identifier}
          tagName={tagName}
          onResolved={() => onDismissConfirmChip(`${identifier}:${tagName}`)}
        />
      ))}
    </div>
  );
}

//# endregion

interface SelectVersionResultsProps {
  imageIdentifiers: Array<string>;
  selectedImage: string | undefined;
  onSelectImage: (identifier: string) => void;
  focusRef: Ref<HTMLInputElement>;
  search: GridSelectorSearch;
  requestedPrinting: RequestedPrinting | undefined;
  backendURL: string;
  /** Editor-completion package, E3/X3 (Bkg 2/4/5) - additive, optional layout switch. Default
   * `"sidebar"` is today's unchanged `Col lg={3}` filters-beside-results split (this component's
   * one existing caller, DisplayPage.tsx's ChooseImageSection, is about to become the rail's
   * "stacked" caller below - there is no other caller today, but the prop stays optional/
   * additive per the standing "shared components gain only additive props" discipline).
   * `"stacked"` is the funnel (funnel-spec.md F1-F7): per-axis segmented chips, count-
   * proportional disclosure, the implicit-vote mechanic. */
  layout?: "sidebar" | "stacked";
  /** F5/F7.2 - the vote layer's single attach seam. Only ever consulted when `layout==="stacked"`
   * (the funnel); `undefined` there is the complete, votes-off base funnel. Ignored entirely on
   * the sidebar/modal layout (which never had a voteLayer concept - moment (c)'s ConfirmChip is
   * its own, separate, unchanged vote path). */
  voteLayer?: VoteLayerProps;
}

export function SelectVersionResults({
  imageIdentifiers,
  selectedImage,
  onSelectImage,
  focusRef,
  search,
  requestedPrinting,
  backendURL,
  layout = "sidebar",
  voteLayer,
}: SelectVersionResultsProps) {
  const getTagDisplayName = useTagDisplayName();
  // Rail-delegacy round (RD4/O3, SPEC-rail-delegacy.md) - tier-conditional Filters panel
  // placement: phone = in-rail Collapse; desktop/tablet = a fixed-positioned panel toward the
  // viewport centre (stacked/rail layout only - the sidebar/modal layout's own GridSelectorFilters
  // AutofillCollapse is untouched).
  const viewportTier = useViewportTier();
  // Editor-completion package, E4/L9 (Bkg 4) - this component's one caller is the /display rail
  // (see this file's own module comment), which the redline pins to always-compressed tiles at
  // the dense/medium disclosure tiers; F1/D21 relaxes this to expanded (compressed=false) tiles
  // at the "hero" tier (<=2 survivors) - see `compressed` below.
  const cardDocumentsByIdentifier = useAppSelector((state) =>
    selectCardDocumentsByIdentifiers(state, search.sortedFilteredIdentifiers)
  );

  const [activeAttributeTags, setActiveAttributeTags] = useState<Set<string>>(
    new Set()
  );
  // Unified Frame + Treatment filter (§6, addendum item 1) - Treatment's own EXCLUDE half.
  // Border/Frame stay purely positive/exclusive via `activeAttributeTags`/`handleAxisChange`
  // (untouched); this is a wholly separate, additive filter dimension so the implicit-vote/
  // awareness-line logic below (which only ever reads `activeAttributeTags`) needs no changes -
  // excluding a tag is a pure negative filter action, never something a pick "supports."
  const [excludedAttributeTags, setExcludedAttributeTags] = useState<
    Set<string>
  >(new Set());
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(
    new Set()
  );
  const [dismissedConfirmChipKeys, setDismissedConfirmChipKeys] = useState<
    Set<string>
  >(new Set());
  // F4c - the last pick's cast support tags, shown as a brief fading ack; cleared automatically
  // after ~2.6s. `null` = no ack showing.
  const [justSupportedTags, setJustSupportedTags] = useState<string[] | null>(
    null
  );
  const ackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (ackTimeoutRef.current != null) {
        clearTimeout(ackTimeoutRef.current);
      }
    },
    []
  );

  const toggleAttributeTag = (tagName: string) =>
    setActiveAttributeTags((previous) => {
      const next = new Set(previous);
      if (next.has(tagName)) {
        next.delete(tagName);
      } else {
        next.add(tagName);
      }
      return next;
    });

  // F2 - one axis's segmented control changed: clear every tag belonging to that axis first
  // (so an exclusive axis never ends up with two active members), then apply the new value.
  const handleAxisChange = (axis: FunnelAxis, nextValue: string | string[]) =>
    setActiveAttributeTags((previous) => {
      const next = new Set(previous);
      axis.chips.forEach((chip) => next.delete(chip.tagName));
      if (axis.exclusive) {
        if (typeof nextValue === "string" && nextValue !== "") {
          next.add(nextValue);
        }
      } else if (Array.isArray(nextValue)) {
        nextValue.forEach((tagName) => next.add(tagName));
      }
      return next;
    });

  // §6 - Treatment's tri-state cycle (untouched/·  -> include/+ -> exclude/− -> untouched),
  // reusing `attributeChips.ts`'s own `nextChipState` for the cycle order (the taxonomy's single
  // source of truth for it - `TreatmentChipRow`'s own comment has the full rationale).
  const toggleTreatmentChip = (tagName: string) => {
    const current: ChipVoteState = activeAttributeTags.has(tagName)
      ? "positive"
      : excludedAttributeTags.has(tagName)
      ? "negative"
      : "untouched";
    const next = nextChipState(current);
    setActiveAttributeTags((previous) => {
      const nextSet = new Set(previous);
      if (next === "positive") {
        nextSet.add(tagName);
      } else {
        nextSet.delete(tagName);
      }
      return nextSet;
    });
    setExcludedAttributeTags((previous) => {
      const nextSet = new Set(previous);
      if (next === "negative") {
        nextSet.add(tagName);
      } else {
        nextSet.delete(tagName);
      }
      return nextSet;
    });
  };

  const applyMoreLikeThis = (identifier: string) => {
    const card = cardDocumentsByIdentifier[identifier];
    if (card == null) {
      return;
    }
    setActiveAttributeTags(
      new Set(card.tags.filter((tagName) => ATTRIBUTE_TAG_NAMES.has(tagName)))
    );
    // A fresh "tags like this card" set replaces whatever exclusions were active too - the old
    // active set was also fully replaced, not merged, so this keeps the same "clean slate"
    // semantics rather than leaving a stale exclusion the new active set might contradict.
    setExcludedAttributeTags(new Set());
  };

  const toggleGroupExpanded = (key: string) =>
    setExpandedGroupKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });

  const dismissConfirmChip = (key: string) =>
    setDismissedConfirmChipKeys((previous) => new Set(previous).add(key));

  const votesOn = layout === "stacked" && voteLayer != null;

  const filteredIdentifiers = useMemo(() => {
    if (layout !== "stacked") {
      return filterByActiveAttributeTags(
        search.sortedFilteredIdentifiers,
        cardDocumentsByIdentifier,
        activeAttributeTags
      );
    }
    const positiveSurvivors = filterByChipsVotesGated(
      search.sortedFilteredIdentifiers,
      cardDocumentsByIdentifier,
      activeAttributeTags,
      votesOn
    );
    // §6 - Treatment's exclude half narrows further, additive to the positive filter above.
    return filterOutExcludedChipsVotesGated(
      positiveSurvivors,
      cardDocumentsByIdentifier,
      excludedAttributeTags,
      votesOn
    );
  }, [
    layout,
    search.sortedFilteredIdentifiers,
    cardDocumentsByIdentifier,
    activeAttributeTags,
    excludedAttributeTags,
    votesOn,
  ]);

  // F1/D21 - the count-proportional disclosure tier, derived from the same survivor count the
  // funnel already computes above - no new state.
  const tier: FunnelDisclosureTier = funnelDisclosureTier(
    filteredIdentifiers.length
  );

  // Rail-delegacy round (RD4/O1, SPEC-rail-delegacy.md) - the D21 "auto-expand once dense" effect
  // is RETIRED: the funnel's axis chips now live INSIDE the same one Filters panel as the
  // advanced fieldsets (item 2/3/5 unified), which the mockup keeps closed by default at every
  // survivor count - auto-forcing it open on a busy result set would fight that calm, fully
  // user-toggled design. `search.settingsVisible` is still the one shared open/closed flag
  // (renamed "Filters" in the UI, RD2/item 2), just never force-set here any more.

  // F3 - per-axis chip membership, computed over survivors filtered by every OTHER axis's active
  // chips (never the axis's own selection - otherwise picking Black would make White/Silver
  // permanently vanish from the Border axis, since no survivor would carry them any more).
  const membershipByTagName = useMemo(() => {
    if (layout !== "stacked") {
      return {} as Record<string, ChipMembershipState>;
    }
    const result: Record<string, ChipMembershipState> = {};
    FUNNEL_AXES.forEach((axis) => {
      const axisTagNames = new Set(axis.chips.map((chip) => chip.tagName));
      const tagsFromOtherAxes = new Set(
        Array.from(activeAttributeTags).filter(
          (tagName) => !axisTagNames.has(tagName)
        )
      );
      // §6 - same "exclude own axis" pattern as the positive filter above, so a Treatment chip's
      // own exclude-state never prevents ITSELF (or its axis siblings) from continuing to render.
      const excludedFromOtherAxes = new Set(
        Array.from(excludedAttributeTags).filter(
          (tagName) => !axisTagNames.has(tagName)
        )
      );
      const survivorsExcludingAxis = filterOutExcludedChipsVotesGated(
        filterByChipsVotesGated(
          search.sortedFilteredIdentifiers,
          cardDocumentsByIdentifier,
          tagsFromOtherAxes,
          votesOn
        ),
        cardDocumentsByIdentifier,
        excludedFromOtherAxes,
        votesOn
      )
        .map((identifier) => cardDocumentsByIdentifier[identifier])
        .filter((card): card is CardDocument => card != null);
      axis.chips.forEach((chip) => {
        const state = chipMembershipState(
          survivorsExcludingAxis,
          chip.tagName,
          votesOn
        );
        if (state != null) {
          result[chip.tagName] = state;
        }
      });
    });
    return result;
  }, [
    layout,
    activeAttributeTags,
    excludedAttributeTags,
    search.sortedFilteredIdentifiers,
    cardDocumentsByIdentifier,
    votesOn,
  ]);

  const groups = useMemo(
    () =>
      groupSelectVersionCandidates(
        filteredIdentifiers,
        cardDocumentsByIdentifier,
        requestedPrinting
      ),
    [filteredIdentifiers, cardDocumentsByIdentifier, requestedPrinting]
  );

  // F4 - the funnel's own pick handler: computes the implicit support set for the picked
  // candidate, forwards the pick unchanged to the caller (onSelectImage - the slot's image is
  // always set, regardless of any vote outcome, per F4b's "the pick itself always succeeds"),
  // then (votes-on only) fires the vote-layer callback, resets the active chips, and shows the
  // fading ack - all gated on there being an actual support set to cast (an ordinary pick under
  // chips that are all already-resolved facts for this candidate casts no vote and does not
  // reset - see this file's own report for this edge case's reasoning).
  //
  // FIX ROUND (owner-ratified condition 6, Tron's PR #329 review): the support set now comes
  // from `voteLayer.suggestedTagNames(card)` (the same seam `showSuggestedBadge` above already
  // uses), NOT a raw `card.tagVoteStatuses` read - see attributeChips.ts's `chipMembershipState`
  // comment for the full "tagVoteStatuses is source-agnostic and self-seeds implicit votes"
  // reasoning. `voteLayer.suggestedTagNames` is itself sourced from `suggestedFilterTagNames`
  // (DisplayPage.tsx), which is implicit-vote-excluded and floor-gated server-side - casting
  // support only for tags that clear that bar closes the loop condition 6 forbids. The
  // `!card.tags.includes(tagName)` check is retained as a defensive belt-and-suspenders gate
  // (suggestedFilterTagNames is already documented to exclude resolved pairs server-side, but
  // this costs nothing and matches D20's own literal wording).
  const handleSelect = (identifier: string) => {
    onSelectImage(identifier);
    if (layout !== "stacked" || voteLayer == null) {
      return;
    }
    const card = cardDocumentsByIdentifier[identifier];
    const suggestedForCard =
      card == null ? [] : voteLayer.suggestedTagNames(card);
    const supportTagNames =
      card == null
        ? []
        : Array.from(activeAttributeTags).filter(
            (tagName) =>
              suggestedForCard.includes(tagName) && !card.tags.includes(tagName)
          );
    // F4d - always call through, even with an empty support set, so the caller can retract
    // whatever it cast for this slot's PREVIOUS pick.
    voteLayer.onImplicitSupport(identifier, supportTagNames);
    if (activeAttributeTags.size > 0 && supportTagNames.length > 0) {
      setActiveAttributeTags(new Set());
      setJustSupportedTags(supportTagNames);
      if (ackTimeoutRef.current != null) {
        clearTimeout(ackTimeoutRef.current);
      }
      ackTimeoutRef.current = setTimeout(
        () => setJustSupportedTags(null),
        2600
      );
    }
  };

  const compressed = tier !== "hero";
  const tileWidthRem =
    layout === "stacked" && tier !== "none"
      ? FUNNEL_TIER_TILE_WIDTH_REM[tier]
      : undefined;

  const tileProps = (
    identifier: string,
    headerLabel: string,
    showConfirmAffordance: boolean
  ) => {
    const card = cardDocumentsByIdentifier[identifier];
    const showSuggestedBadge =
      layout === "stacked" &&
      votesOn &&
      card != null &&
      voteLayer != null &&
      voteLayer.suggestedTagNames(card).length > 0;
    return {
      identifier,
      headerLabel,
      card,
      selectedImage,
      compressed: layout === "stacked" ? compressed : true,
      tileWidthRem,
      onSelect: layout === "stacked" ? handleSelect : onSelectImage,
      showConfirmAffordance,
      showTwoTapConfirm: layout !== "stacked",
      activeAttributeTags,
      dismissedConfirmChipKeys,
      onDismissConfirmChip: dismissConfirmChip,
      onMoreLikeThis: applyMoreLikeThis,
      backendURL,
      showSuggestedBadge,
      layout,
    };
  };

  // Addendum item 2 (continuous grid, "the 5 cards should be in 1 section" - owner verbatim,
  // 8f5b65ce): the group-based render below (`renderPrintingGroup`/`renderReasonTagGroup`/
  // `resultsElement`) stays completely UNCHANGED and is still what the sidebar/modal layout
  // renders - this is a SEPARATE, stacked-layout-only flattening of the exact same `groups`
  // (selectVersionGrouping.ts's own ordering is untouched, now consumed as a sort key rather
  // than a sectioning key) into ONE flat list of tiles/ghost-tiles, so the funnel can render them
  // all inside a single `d-flex flex-wrap` grid with zero between-group rows.
  type ContinuousGridEntry =
    | {
        kind: "tile";
        key: string;
        props: ReturnType<typeof tileProps>;
        cornerTag?: { label: string; variant: "canon" | "alt" | "unk" };
        requested?: boolean;
        ariaLabel: string;
      }
    | {
        kind: "ghost";
        key: string;
        label: string;
        ariaLabel: string;
        onClick: () => void;
      };

  const continuousGridEntries: ContinuousGridEntry[] = [];
  if (layout === "stacked") {
    groups.canonical.forEach((group) => {
      const label = `${group.expansionCode.toUpperCase()} ${
        group.collectorNumber
      }`;
      const expanded = expandedGroupKeys.has(group.key);
      const isSuggested = group.status === "suggested";
      const reqSuffix = group.isRequestedPrinting ? ", requested printing" : "";
      continuousGridEntries.push({
        kind: "tile",
        key: group.representative,
        props: tileProps(group.representative, label, isSuggested),
        cornerTag: isSuggested ? undefined : { label: "✓", variant: "canon" },
        requested: group.isRequestedPrinting,
        ariaLabel: `${label}${reqSuffix}, canonical printing, ${group.status}`,
      });
      if (expanded) {
        group.rest.forEach((identifier) => {
          continuousGridEntries.push({
            kind: "tile",
            key: identifier,
            props: tileProps(identifier, label, false),
            cornerTag: isSuggested
              ? undefined
              : { label: "✓", variant: "canon" },
            ariaLabel: `${label}, canonical printing, additional copy`,
          });
        });
        continuousGridEntries.push({
          kind: "ghost",
          key: `${group.key}-collapse`,
          label: "−",
          ariaLabel: `Show fewer copies of ${label}`,
          onClick: () => toggleGroupExpanded(group.key),
        });
      } else if (group.rest.length > 0) {
        continuousGridEntries.push({
          kind: "ghost",
          key: `${group.key}-expand`,
          label: `+${group.rest.length}`,
          ariaLabel: `Show ${group.rest.length} more copies of ${label}`,
          onClick: () => toggleGroupExpanded(group.key),
        });
      }
    });

    groups.nonCanonical.forEach((group) => {
      const label = getTagDisplayName(group.tagName);
      const expanded = expandedGroupKeys.has(group.tagName);
      continuousGridEntries.push({
        kind: "tile",
        key: group.representative,
        props: tileProps(group.representative, label, false),
        cornerTag: { label: "Alt", variant: "alt" },
        ariaLabel: `${label}, alternate or custom printing`,
      });
      if (expanded) {
        group.rest.forEach((identifier) => {
          continuousGridEntries.push({
            kind: "tile",
            key: identifier,
            props: tileProps(identifier, label, false),
            cornerTag: { label: "Alt", variant: "alt" },
            ariaLabel: `${label}, alternate or custom printing, additional copy`,
          });
        });
        continuousGridEntries.push({
          kind: "ghost",
          key: `${group.tagName}-collapse`,
          label: "−",
          ariaLabel: `Show fewer ${label} copies`,
          onClick: () => toggleGroupExpanded(group.tagName),
        });
      } else if (group.rest.length > 0) {
        continuousGridEntries.push({
          kind: "ghost",
          key: `${group.tagName}-expand`,
          label: `+${group.rest.length}`,
          ariaLabel: `Show ${group.rest.length} more ${label} copies`,
          onClick: () => toggleGroupExpanded(group.tagName),
        });
      }
    });

    groups.unknown.forEach((identifier) => {
      const originalIndex = search.originalIndexMap.get(identifier);
      const label =
        originalIndex != null ? `Option ${originalIndex + 1}` : "Unknown";
      continuousGridEntries.push({
        kind: "tile",
        key: identifier,
        props: tileProps(identifier, label, false),
        cornerTag: { label: "?", variant: "unk" },
        ariaLabel: `${label}, unknown printing`,
      });
    });
  }

  const continuousGridElement = (
    <div
      className="d-flex flex-wrap"
      // CSS-fidelity pass (2026-07-23, SPEC-display-left-rail.md §7/§2) - `gap-1` (0.25rem/4px)
      // was too tight; the mockup's own literal `.vgrid{gap:6px}` has no exact Bootstrap
      // spacing-scale match (`gap-1`=4px, `gap-2`=8px), so it's set directly, same as this file's
      // other exact-px values.
      style={{ gap: "6px" }}
      role="list"
      aria-label="Candidate printings"
      data-testid="select-version-continuous-grid"
    >
      {continuousGridEntries.map((entry) =>
        entry.kind === "tile" ? (
          <SelectVersionTile
            key={entry.key}
            {...entry.props}
            cornerTag={entry.cornerTag}
            requested={entry.requested}
            ariaLabel={entry.ariaLabel}
          />
        ) : (
          <GhostTile
            key={entry.key}
            type="button"
            $widthRem={tileWidthRem ?? 4.5}
            aria-label={entry.ariaLabel}
            onClick={entry.onClick}
            data-testid={`select-version-ghost-${entry.key}`}
          >
            {entry.label}
          </GhostTile>
        )
      )}
    </div>
  );

  const renderPrintingGroup = (group: SelectVersionPrintingGroup) => {
    const label = `${group.expansionCode.toUpperCase()} ${
      group.collectorNumber
    }`;
    const expanded = expandedGroupKeys.has(group.key);
    return (
      <div
        key={group.key}
        data-testid={`select-version-printing-group-${group.key}`}
        data-status={group.status}
        data-requested={group.isRequestedPrinting}
      >
        {/* Fix round (owner live-review, "oversized dropdowns") - tiles wrap into a row
            instead of each stacking on its own full-width line, now that SelectVersionTile
            itself carries a real fixed width (see that component's own comment) rather than a
            no-op `width: auto`. Owner fix round (2026-07-23, "keep the ordering, but drop the
            separator please") dropped this wrapper's own `mb-2` - see the module-level note
            near `resultsElement` for why. */}
        <div className="d-flex flex-wrap gap-1">
          <SelectVersionTile
            {...tileProps(
              group.representative,
              label,
              group.status === "suggested"
            )}
          />
          {expanded &&
            group.rest.map((identifier) => (
              <SelectVersionTile
                key={identifier}
                {...tileProps(identifier, label, false)}
              />
            ))}
        </div>
        {group.rest.length > 0 && (
          <div className="text-center">
            <CompactLinkButton
              size="sm"
              variant="link"
              className="p-0"
              onClick={() => toggleGroupExpanded(group.key)}
              data-testid={`select-version-expand-${group.key}`}
            >
              {expanded
                ? "Show fewer"
                : `+${group.rest.length} more of this printing`}
            </CompactLinkButton>
          </div>
        )}
      </div>
    );
  };

  const renderReasonTagGroup = (group: SelectVersionReasonTagGroup) => {
    const label = getTagDisplayName(group.tagName);
    const expanded = expandedGroupKeys.has(group.tagName);
    return (
      <div
        key={group.tagName}
        data-testid={`select-version-reason-group-${group.tagName}`}
      >
        <div className="d-flex flex-wrap gap-1">
          <SelectVersionTile
            {...tileProps(group.representative, label, false)}
          />
          {expanded &&
            group.rest.map((identifier) => (
              <SelectVersionTile
                key={identifier}
                {...tileProps(identifier, label, false)}
              />
            ))}
        </div>
        {group.rest.length > 0 && (
          <div className="text-center">
            <CompactLinkButton
              size="sm"
              variant="link"
              className="p-0"
              onClick={() => toggleGroupExpanded(group.tagName)}
              data-testid={`select-version-expand-${group.tagName}`}
            >
              {expanded ? "Show fewer" : `+${group.rest.length} more`}
            </CompactLinkButton>
          </div>
        )}
      </div>
    );
  };

  const noResults =
    groups.canonical.length === 0 &&
    groups.nonCanonical.length === 0 &&
    groups.unknown.length === 0;

  const filtersElement = (
    <GridSelectorFilters
      imageIdentifiers={imageIdentifiers}
      focusRef={focusRef}
      selectImage={onSelectImage}
      sortBy={search.sortBy}
      setSortBy={search.setSortBy}
      printings={search.printings}
      setPrintings={search.setPrintings}
      artists={search.artists}
      setArtists={search.setArtists}
      filterSettings={search.filterSettings}
      setFilterSettings={search.setFilterSettings}
      sourceSettings={search.sourceSettings}
      setSourceSettings={search.setSourceSettings}
      projectFilter={search.projectFilter}
      // E4/X4 (Bkg 3/4) - only the stacked (rail) caller hides "View" (Group-by/Compressed);
      // the sidebar (modal/browse) callers are unaffected. 2026-07-24 owner escalation:
      // the rail also hides the stock sources table and attribute toggle bars - the rail's
      // own SOURCES accordion and Treatment/Frame/Border chip fieldset are the designed
      // versions of both (SPEC-display-left-rail.md), and rendering the stock duplicates
      // beneath them was the "looks nothing like Quorra's spec" report.
      hiddenSections={
        layout === "stacked"
          ? ["view", "filter-sources", "filter-attributes"]
          : undefined
      }
    />
  );

  const resultsElement = (
    <>
      {layout !== "stacked" && (
        <FilterChipBar
          activeTagNames={activeAttributeTags}
          onToggle={toggleAttributeTag}
        />
      )}
      {groups.canonical.length > 0 && (
        <div data-testid="select-version-group-canonical">
          {groups.canonical.map(renderPrintingGroup)}
        </div>
      )}
      {groups.nonCanonical.length > 0 && (
        <div data-testid="select-version-group-non-canonical">
          {groups.nonCanonical.map(renderReasonTagGroup)}
        </div>
      )}
      {groups.unknown.length > 0 && (
        <div
          className="d-flex flex-wrap gap-1"
          data-testid="select-version-group-unknown"
        >
          {groups.unknown.map((identifier) => {
            // No printing/reason-tag identity to label this tile with (the "honest residue" -
            // see selectVersionGrouping.ts) - falls back to the same "Option N" numbering the
            // flat grid this section replaces always used (search.originalIndexMap, the same
            // map GridSelectorResults/CardResultSet already thread through for consistent
            // numbering), rather than inventing a new, less informative label.
            const originalIndex = search.originalIndexMap.get(identifier);
            const label =
              originalIndex != null ? `Option ${originalIndex + 1}` : "Unknown";
            return (
              <SelectVersionTile
                key={identifier}
                {...tileProps(identifier, label, false)}
              />
            );
          })}
        </div>
      )}
      {noResults && layout !== "stacked" && (
        <GenericErrorPage
          title="No results :("
          text={["Your filters didn't match any results."]}
        />
      )}
    </>
  );

  if (layout === "stacked") {
    // Rail-delegacy round (item 2/3/5, RD1/RD2/RD4, SPEC-rail-delegacy.md) - the funnel's own
    // Border/Frame/Treatment chips are no longer a separate always-visible block above the grid;
    // they're now ONE fieldset inside the SAME Filters panel as the advanced fieldsets (DPI/
    // size/languages/tags/NSFW), all gated behind the ONE `svhead` "Filters" toggle
    // (`search.settingsVisible`). `FunnelAxisRow` still self-hides an axis with no surviving
    // chips (F3, unchanged).
    const filterFieldsetsBody = (
      <>
        <fieldset
          className="fset"
          style={{ marginBottom: 0 }}
          data-testid="funnel-unified-filter"
        >
          <span className="lg">Filter versions</span>
          <legend className="visually-hidden">
            Border, frame, and treatment filters
          </legend>
          <FunnelAxisRow
            axis={FUNNEL_AXES[0]}
            activeTagNames={activeAttributeTags}
            membershipByTagName={membershipByTagName}
            onAxisChange={handleAxisChange}
            getTagDisplayName={getTagDisplayName}
            rowStyle={{ marginBottom: "5px" }}
          />
          <div
            className="d-flex align-items-center flex-wrap"
            style={{ gap: "6px" }}
            data-testid="funnel-frame-treatment-row"
          >
            <FunnelAxisRow
              axis={FUNNEL_AXES[1]}
              activeTagNames={activeAttributeTags}
              membershipByTagName={membershipByTagName}
              onAxisChange={handleAxisChange}
              getTagDisplayName={getTagDisplayName}
            />
            <UnifiedFilterDivider aria-hidden="true" />
            <TreatmentChipRow
              axis={FUNNEL_AXES[2]}
              activeTagNames={activeAttributeTags}
              excludedTagNames={excludedAttributeTags}
              membershipByTagName={membershipByTagName}
              onCycle={toggleTreatmentChip}
              getTagDisplayName={getTagDisplayName}
            />
          </div>
          {/* O1/RD1 - the implicit-vote awareness line, kept gated on >=1 active chip (unlike the
              mockup's decorative always-on demo copy): `voteLayer.awarenessCopy` names the tags
              actually at stake, which has nothing to describe with zero active chips. */}
          {votesOn && voteLayer != null && activeAttributeTags.size > 0 && (
            <div className="implicit-note" data-testid="funnel-awareness-line">
              <span className="ic" aria-hidden="true">
                ⓘ
              </span>
              <span>
                {voteLayer.awarenessCopy(Array.from(activeAttributeTags))}
              </span>
            </div>
          )}
        </fieldset>
        <div className="fsep" />
        <FilterSettingsElement
          filterSettings={search.filterSettings}
          setFilterSettings={search.setFilterSettings}
          minDPILowerBound={search.projectFilter?.minimumDPI}
          maxDPIUpperBound={search.projectFilter?.maximumDPI}
          maxSizeUpperBound={search.projectFilter?.maximumSize}
          showBoilerplate={false}
          showResolvedAttributeFilter={false}
        />
      </>
    );

    const closeFilters = () => search.setSettingsVisible(false);
    const isPhoneTier = viewportTier === "phone";

    return (
      <div data-testid="select-version-section" data-funnel-tier={tier}>
        {/* item 2 (RD2) - the SV header row: [N versions] [Sort ▾] [Filters ▾], replacing the
            old always-visible count+pills bar. */}
        <div className="svhead" data-testid="svhead">
          <span data-testid="funnel-count">
            <span className="n">
              {filteredIdentifiers.length.toLocaleString()}
            </span>{" "}
            version
            {filteredIdentifiers.length !== 1 ? "s" : ""}
          </span>
          <span style={{ flex: "1 1 auto" }} />
          {/* RD2 - a compact Form.Select of the 6 SortByOptions replaces the old
              NullableSortByFilter tree-select (O5 accepted). */}
          <Form.Select
            size="sm"
            className="sortsel"
            aria-label="Sort versions"
            value={search.sortBy ?? ""}
            onChange={(event) =>
              search.setSortBy(
                event.target.value === ""
                  ? undefined
                  : (event.target.value as SortBy)
              )
            }
            data-testid="funnel-sort-select"
          >
            <option value="">Default order</option>
            {Object.entries(SortByOptions).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Form.Select>
          {/* Owner fix round (2026-07-23, SPEC-display-left-rail.md §8 "buttons-look-like-
              buttons" audit) - a real button, not underlined text (this performs an action). */}
          <CompactButton
            variant="outline-light"
            size="sm"
            className="filtersbtn"
            aria-expanded={search.settingsVisible}
            onClick={() => search.setSettingsVisible((v) => !v)}
            data-testid="funnel-filters-toggle"
          >
            <i
              className={`bi bi-chevron-${
                search.settingsVisible ? "left" : "right"
              }`}
            />{" "}
            Filters
          </CompactButton>
        </div>

        {/* item 2/3/5 (RD4/O3) - ONE shared fieldset body, rendered tier-conditionally: phone =
            in-rail Collapse expanding IN PLACE (no overlay-over-overlay in the bottom-sheet);
            desktop inline rail + tablet drawer = a panel portaled to `document.body` and fixed-
            positioned toward the viewport centre - see `FloatFiltersPortalRoot`'s own comment for
            why a plain in-tree `position:fixed` node isn't enough (LeftRailOffcanvas's own
            `position:sticky` traps it inside a local stacking context). Only ONE of the two
            containers is ever mounted for a given `viewportTier`, so the fieldsets' own state
            (all lifted into `search`) can never drift between two simultaneously-rendered
            copies. */}
        {isPhoneTier ? (
          <Collapse in={search.settingsVisible}>
            <div>
              <div
                className="fpanel inline"
                role="group"
                aria-label="Version filters"
                data-testid="filters-panel-inline"
              >
                {filterFieldsetsBody}
              </div>
            </div>
          </Collapse>
        ) : (
          search.settingsVisible &&
          typeof document !== "undefined" &&
          createPortal(
            <FloatFiltersPortalRoot>
              <div
                className="fscrim"
                onClick={closeFilters}
                data-testid="filters-panel-scrim"
              />
              <div
                className="fpanel float"
                role="group"
                aria-label="Version filters"
                data-testid="filters-panel-float"
              >
                <div className="fptitle">
                  <span>Filters — refine versions</span>
                  <button
                    type="button"
                    onClick={closeFilters}
                    data-testid="filters-panel-close"
                  >
                    Close ✕
                  </button>
                </div>
                <div className="fpwrap">{filterFieldsetsBody}</div>
              </div>
            </FloatFiltersPortalRoot>,
            document.body
          )
        )}

        {/* post-pick ack (F4c). */}
        {votesOn && justSupportedTags != null && (
          <AckLine
            className="small mb-2 mt-2"
            aria-live="polite"
            data-testid="funnel-support-ack"
          >
            ✓ Supported {justSupportedTags.map(getTagDisplayName).join(" · ")} —
            filters cleared
          </AckLine>
        )}

        {/* survivors grid, count-proportional (F1/D21). */}
        {tier === "none" ? (
          <div
            className="text-center text-muted small py-3"
            data-testid="funnel-empty-state"
          >
            No versions match your filters.
            {(activeAttributeTags.size > 0 ||
              excludedAttributeTags.size > 0) && (
              <div className="mt-1">
                <CompactLinkButton
                  size="sm"
                  variant="link"
                  className="p-0"
                  onClick={() => {
                    setActiveAttributeTags(new Set());
                    setExcludedAttributeTags(new Set());
                  }}
                  data-testid="funnel-clear-filters"
                >
                  Clear filters
                </CompactLinkButton>
              </div>
            )}
          </div>
        ) : (
          continuousGridElement
        )}
      </div>
    );
  }

  return (
    <Row className="g-0" data-testid="select-version-section">
      {search.settingsVisible && (
        <Col lg={3} sm={4} xs={6} className="border-end p-0">
          {filtersElement}
        </Col>
      )}
      <Col
        lg={search.settingsVisible ? 9 : 12}
        sm={search.settingsVisible ? 8 : 12}
        xs={search.settingsVisible ? 6 : 12}
        className="p-0"
      >
        {resultsElement}
      </Col>
    </Row>
  );
}
