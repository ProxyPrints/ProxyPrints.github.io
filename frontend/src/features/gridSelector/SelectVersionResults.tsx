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
 * SETTLED/SUGGESTED purely from `card.tags`/`card.tagVoteStatuses` (Tag-consensus data), which is
 * still a `votesOn`-gated read (the "suggested" half is only ever consulted when a `voteLayer` is
 * supplied) - so F5's votes-off guarantee (no SUGGESTED chip, no vote-derived filtering) holds
 * exactly as specified, just implemented against the real available data rather than a
 * `PrintingCandidate`-shaped one.
 */
import styled from "@emotion/styled";
import React, { Ref, useEffect, useMemo, useRef, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";
import ToggleButton from "react-bootstrap/ToggleButton";
import ToggleButtonGroup from "react-bootstrap/ToggleButtonGroup";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import {
  ALL_ATTRIBUTE_CHIPS,
  AttributeChipDef,
  candidateSatisfiesAttributeTag,
  ChipMembershipState,
  chipMembershipState,
  FUNNEL_AXES,
  FunnelAxis,
} from "@/features/attributeChips/attributeChips";
import { MemoizedEditorCard } from "@/features/card/Card";
import { DeckbuilderConfirmAffordance } from "@/features/card/DeckbuilderConfirmAffordance";
import { GridSelectorFilters } from "@/features/gridSelector/GridSelectorFilters";
import {
  groupSelectVersionCandidates,
  RequestedPrinting,
  SelectVersionPrintingGroup,
  SelectVersionReasonTagGroup,
} from "@/features/gridSelector/selectVersionGrouping";
import { GridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
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

const FUNNEL_TIER_TILE_WIDTH_REM: Record<
  Exclude<FunnelDisclosureTier, "none">,
  number
> = {
  dense: 4.5,
  medium: 6.5,
  hero: 9.4,
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

//# region F2/F3 - per-axis segmented chips

interface FunnelAxisRowProps {
  axis: FunnelAxis;
  activeTagNames: Set<string>;
  membershipByTagName: Record<string, ChipMembershipState>;
  onAxisChange: (axis: FunnelAxis, nextValue: string | string[]) => void;
  getTagDisplayName: (tagName: string) => string;
}

function FunnelAxisRow({
  axis,
  activeTagNames,
  membershipByTagName,
  onAxisChange,
  getTagDisplayName,
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
      className="d-flex align-items-center flex-wrap gap-2 mb-1"
      data-testid={`funnel-axis-${axis.id}`}
    >
      <span
        className="text-muted text-uppercase"
        style={{ minWidth: 62, fontSize: "0.7rem", letterSpacing: "0.03em" }}
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
            <ToggleButton
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
            </ToggleButton>
          );
        })}
      </ToggleButtonGroup>
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
}: SelectVersionTileProps) {
  const hasFilterableTags =
    card != null &&
    card.tags.some((tagName) => ATTRIBUTE_TAG_NAMES.has(tagName));

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
      data-testid={`select-version-tile-${identifier}`}
    >
      <MemoizedEditorCard
        imageIdentifier={identifier}
        cardHeaderTitle={headerLabel}
        cardOnClick={() => onSelect(identifier)}
        noResultsFound={false}
        highlight={identifier === selectedImage}
        compressed={compressed}
      />
      {/* F3 - a survivor tile whose ONLY reason for surviving the active chips is a suggested
          (unconfirmed) tag gets the same dashed/"unconfirmed" treatment as its chip - mirrors
          funnel-mockup.html's `.sug-badge`. */}
      {showSuggestedBadge && (
        <div
          className="text-center small"
          style={{ color: "#df6919" }}
          data-testid={`select-version-suggested-badge-${identifier}`}
        >
          ⌇ suggested
        </div>
      )}
      {showConfirmAffordance && card != null && (
        <DeckbuilderConfirmAffordance
          cardIdentifier={identifier}
          searchQuery={synthesizeSuggestedPrintingQuery(card)}
          // No separate grid/modal to open from here - this tile IS already inside the picker
          // (see the module comment). NO still marks the affordance resolved-for-this-session
          // via the component's own unchanged logic; there is simply nothing further to open.
          onOpenGridSelector={() => undefined}
        />
      )}
      {hasFilterableTags && (
        <div className="text-center">
          <Button
            size="sm"
            variant="link"
            className="p-0 small"
            onClick={() => onMoreLikeThis(identifier)}
            data-testid={`select-version-more-like-this-${identifier}`}
          >
            More like this
          </Button>
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

  const applyMoreLikeThis = (identifier: string) => {
    const card = cardDocumentsByIdentifier[identifier];
    if (card == null) {
      return;
    }
    setActiveAttributeTags(
      new Set(card.tags.filter((tagName) => ATTRIBUTE_TAG_NAMES.has(tagName)))
    );
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

  const filteredIdentifiers = useMemo(
    () =>
      layout === "stacked"
        ? filterByChipsVotesGated(
            search.sortedFilteredIdentifiers,
            cardDocumentsByIdentifier,
            activeAttributeTags,
            votesOn
          )
        : filterByActiveAttributeTags(
            search.sortedFilteredIdentifiers,
            cardDocumentsByIdentifier,
            activeAttributeTags
          ),
    [
      layout,
      search.sortedFilteredIdentifiers,
      cardDocumentsByIdentifier,
      activeAttributeTags,
      votesOn,
    ]
  );

  // F1/D21 - the count-proportional disclosure tier, derived from the same survivor count the
  // funnel already computes above - no new state.
  const tier: FunnelDisclosureTier = funnelDisclosureTier(
    filteredIdentifiers.length
  );

  // D21 - "many (>8)" auto-expands the advanced Filters disclosure once, the first time the
  // tier becomes dense; a user who manually re-collapses it afterwards is respected (this effect
  // only depends on `tier`, so it won't re-fire while `tier` stays "dense").
  useEffect(() => {
    if (layout === "stacked" && tier === "dense") {
      search.setSettingsVisible(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, tier]);

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
      const survivorsExcludingAxis = filterByChipsVotesGated(
        search.sortedFilteredIdentifiers,
        cardDocumentsByIdentifier,
        tagsFromOtherAxes,
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
  const handleSelect = (identifier: string) => {
    onSelectImage(identifier);
    if (layout !== "stacked" || voteLayer == null) {
      return;
    }
    const card = cardDocumentsByIdentifier[identifier];
    const supportTagNames =
      card == null
        ? []
        : Array.from(activeAttributeTags).filter(
            (tagName) =>
              card.tagVoteStatuses?.[tagName] === "suggested" &&
              !card.tags.includes(tagName)
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
    };
  };

  const renderPrintingGroup = (group: SelectVersionPrintingGroup) => {
    const label = `${group.expansionCode.toUpperCase()} ${
      group.collectorNumber
    }`;
    const expanded = expandedGroupKeys.has(group.key);
    return (
      <div
        key={group.key}
        className="mb-2"
        data-testid={`select-version-printing-group-${group.key}`}
        data-status={group.status}
        data-requested={group.isRequestedPrinting}
      >
        {/* Fix round (owner live-review, "oversized dropdowns") - tiles wrap into a row
            instead of each stacking on its own full-width line, now that SelectVersionTile
            itself carries a real fixed width (see that component's own comment) rather than a
            no-op `width: auto`. */}
        <div className="d-flex flex-wrap gap-2">
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
            <Button
              size="sm"
              variant="link"
              className="p-0 small"
              onClick={() => toggleGroupExpanded(group.key)}
              data-testid={`select-version-expand-${group.key}`}
            >
              {expanded
                ? "Show fewer"
                : `+${group.rest.length} more of this printing`}
            </Button>
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
        className="mb-2"
        data-testid={`select-version-reason-group-${group.tagName}`}
      >
        <div className="d-flex flex-wrap gap-2">
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
            <Button
              size="sm"
              variant="link"
              className="p-0 small"
              onClick={() => toggleGroupExpanded(group.tagName)}
              data-testid={`select-version-expand-${group.tagName}`}
            >
              {expanded ? "Show fewer" : `+${group.rest.length} more`}
            </Button>
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
      // the sidebar (modal/browse) callers are unaffected.
      hiddenSections={layout === "stacked" ? ["view"] : undefined}
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
          className="d-flex flex-wrap gap-2"
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
    // F1 - only axes with >=1 visible chip actually render (FunnelAxisRow itself returns null
    // otherwise); D21 - axes stay visible while narrowing is still useful (dense/medium tiers),
    // collapsing to the head's active-pill summary at hero/none (nothing left worth partitioning
    // at that point).
    const showAxes = tier === "dense" || tier === "medium";
    return (
      <div data-testid="select-version-section" data-funnel-tier={tier}>
        {/* A. funnel head - count, active-tag pills (always shown, any tier, so the user can
            still see/clear a filter even once the axis rows themselves collapse), the Filters
            disclosure toggle. */}
        <div
          className="d-flex align-items-center gap-2 flex-wrap mb-2"
          data-testid="funnel-head"
        >
          <span className="text-muted small" data-testid="funnel-count">
            {filteredIdentifiers.length.toLocaleString()} version
            {filteredIdentifiers.length !== 1 ? "s" : ""}
          </span>
          {activeAttributeTags.size > 0 && (
            <div
              className="d-flex flex-wrap gap-1"
              data-testid="funnel-active-pills"
            >
              {Array.from(activeAttributeTags).map((tagName) => (
                <span
                  key={tagName}
                  role="button"
                  className="badge rounded-pill text-bg-secondary"
                  onClick={() => toggleAttributeTag(tagName)}
                  data-testid={`funnel-active-pill-${tagName}`}
                >
                  {getTagDisplayName(tagName)} ×
                </span>
              ))}
            </div>
          )}
          <Button
            variant="outline-primary"
            size="sm"
            className="ms-auto"
            onClick={() => search.setSettingsVisible((v) => !v)}
            data-testid="funnel-filters-toggle"
          >
            <i
              className={`bi bi-chevron-${
                search.settingsVisible ? "left" : "right"
              }`}
            />{" "}
            Filters
          </Button>
        </div>

        {/* B. per-axis segmented chips (F2/F3). */}
        {showAxes && (
          <div className="mb-1" data-testid="funnel-axes">
            {FUNNEL_AXES.map((axis) => (
              <FunnelAxisRow
                key={axis.id}
                axis={axis}
                activeTagNames={activeAttributeTags}
                membershipByTagName={membershipByTagName}
                onAxisChange={handleAxisChange}
                getTagDisplayName={getTagDisplayName}
              />
            ))}
          </div>
        )}

        {/* B'. advanced filters (E4, unchanged) - full-width, stacked, in the rail's own scroll
            container. */}
        {search.settingsVisible && (
          <div className="sv-filters border-bottom mb-2 pb-2">
            {filtersElement}
          </div>
        )}

        {/* C. implicit-vote awareness line (F4a) - votes-on + >=1 active chip only. */}
        {votesOn && voteLayer != null && activeAttributeTags.size > 0 && (
          <AwarenessLine
            className="small mb-2"
            data-testid="funnel-awareness-line"
          >
            <span style={{ color: "#df6919", fontWeight: 700 }}>ⓘ</span>{" "}
            {voteLayer.awarenessCopy(Array.from(activeAttributeTags))}
          </AwarenessLine>
        )}

        {/* post-pick ack (F4c). */}
        {votesOn && justSupportedTags != null && (
          <AckLine
            className="small mb-2"
            aria-live="polite"
            data-testid="funnel-support-ack"
          >
            ✓ Supported {justSupportedTags.map(getTagDisplayName).join(" · ")} —
            filters cleared
          </AckLine>
        )}

        {/* D. survivors grid, count-proportional (F1/D21). */}
        {tier === "none" ? (
          <div
            className="text-center text-muted small py-3"
            data-testid="funnel-empty-state"
          >
            No versions match your filters.
            {activeAttributeTags.size > 0 && (
              <div className="mt-1">
                <Button
                  size="sm"
                  variant="link"
                  className="p-0 small"
                  onClick={() => setActiveAttributeTags(new Set())}
                  data-testid="funnel-clear-filters"
                >
                  Clear filters
                </Button>
              </div>
            )}
          </div>
        ) : (
          resultsElement
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
