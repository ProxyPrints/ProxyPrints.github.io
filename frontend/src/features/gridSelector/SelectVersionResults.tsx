/**
 * The unified display page's Select Version section body (issue #167,
 * docs/proposals/proposal-h-unified-display-page.md §4.4′) - the embedded-only replacement for
 * GridSelectorResults/CardResultSet inside DisplayPage.tsx's "Choose Image" accordion section.
 * `GridSelectorModal.tsx`'s own modal variant (used by CardSlot.tsx's editor grid, unchanged by
 * this task per its own scope) is untouched - this component is mounted from exactly one place,
 * DisplayPage.tsx's ChooseImageSection.
 *
 * Structure follows the spec's three ordered groups (canonical grouped-by-printing, non-canonical
 * grouped-by-reason-tag, unknown) via selectVersionGrouping.ts's pure grouping function, plus the
 * spec's three verification moments woven into browsing:
 *   (a) Suggested-printing representatives carry the same DeckbuilderConfirmAffordance already
 *       mounted in the rail header (2b) - reused verbatim, not forked, via a SearchQuery
 *       synthesized from the representative's own suggestedCanonicalCard (see the module comment
 *       on synthesizeSearchQuery for why that makes the component's existing gate condition just
 *       work with no changes to it).
 *   (b) A plain filter-chip bar (NOT AttributeChipPanel's vote-casting ring - a new, thin
 *       component per the spec's own component table) built on attributeChips.ts's existing
 *       taxonomy, filtering the whole section down to cards matching every active tag. A
 *       "More like this" action on any tile seeds the filter from that card's own resolved tags.
 *   (c) A one-tap inline confirm chip on the just-selected card when an active filter tag is only
 *       "suggested" (not yet resolved) for that specific card - casts one real APISubmitTagVote,
 *       never required.
 *
 * DEVIATION from the spec's literal text (documented, not silent): the spec's Data-dependencies
 * table describes moment (b)'s filter as running "against Card.tags" alone, but moment (c) can
 * only ever fire (a filtered-in card whose matching tag is merely "suggested") if the filter's
 * own match criterion allows a "suggested" match through, not just a resolved one - otherwise a
 * tag that passed the filter is by definition already resolved on that card, and the confirm-chip
 * scenario the spec describes could never actually occur. This implementation's filter therefore
 * matches on resolved OR suggested per active tag (see filterByActiveAttributeTags below), which
 * is the only reading that makes both spec passages internally consistent - flagged in this
 * task's own report rather than silently picked.
 */
import styled from "@emotion/styled";
import React, { Ref, useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import {
  ALL_ATTRIBUTE_CHIPS,
  AttributeChipDef,
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
import { selectCompressed } from "@/store/slices/viewSettingsSlice";

const ATTRIBUTE_TAG_NAMES = new Set(
  ALL_ATTRIBUTE_CHIPS.map((chip) => chip.tagName)
);

/**
 * Matches on resolved OR suggested per active tag - see this file's own module comment for why
 * a resolved-only filter would make moment (c)'s confirm chip unreachable.
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

//# region moment (b) - plain filter-chip bar

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

//# region moment (c) - filtered-selection confirm chip

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

//# region shared tile

interface SelectVersionTileProps {
  identifier: string;
  headerLabel: string;
  card: CardDocument | undefined;
  selectedImage: string | undefined;
  compressed: boolean;
  onSelect: (identifier: string) => void;
  showConfirmAffordance: boolean;
  activeAttributeTags: Set<string>;
  dismissedConfirmChipKeys: Set<string>;
  onDismissConfirmChip: (key: string) => void;
  onMoreLikeThis: (identifier: string) => void;
  backendURL: string;
}

function SelectVersionTile({
  identifier,
  headerLabel,
  card,
  selectedImage,
  compressed,
  onSelect,
  showConfirmAffordance,
  activeAttributeTags,
  dismissedConfirmChipKeys,
  onDismissConfirmChip,
  onMoreLikeThis,
  backendURL,
}: SelectVersionTileProps) {
  const hasFilterableTags =
    card != null &&
    card.tags.some((tagName) => ATTRIBUTE_TAG_NAMES.has(tagName));

  // moment (c): only for the just-selected card, only for active filter tags this specific card
  // hasn't already resolved (a resolved match wouldn't need confirming), and only once per
  // card+tag until dismissed/cast this component's own lifetime (local state, not persisted -
  // see the module comment on why this deliberately isn't the module-level session Set
  // DeckbuilderConfirmAffordance itself uses).
  const suggestedActiveTagNames =
    card != null && selectedImage === identifier
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
      style={{ width: compressed ? "auto" : undefined }}
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
}

export function SelectVersionResults({
  imageIdentifiers,
  selectedImage,
  onSelectImage,
  focusRef,
  search,
  requestedPrinting,
  backendURL,
}: SelectVersionResultsProps) {
  const getTagDisplayName = useTagDisplayName();
  const compressed = useAppSelector(selectCompressed);
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

  const filteredIdentifiers = useMemo(
    () =>
      filterByActiveAttributeTags(
        search.sortedFilteredIdentifiers,
        cardDocumentsByIdentifier,
        activeAttributeTags
      ),
    [
      search.sortedFilteredIdentifiers,
      cardDocumentsByIdentifier,
      activeAttributeTags,
    ]
  );

  const groups = useMemo(
    () =>
      groupSelectVersionCandidates(
        filteredIdentifiers,
        cardDocumentsByIdentifier,
        requestedPrinting
      ),
    [filteredIdentifiers, cardDocumentsByIdentifier, requestedPrinting]
  );

  const tileProps = (
    identifier: string,
    headerLabel: string,
    showConfirmAffordance: boolean
  ) => ({
    identifier,
    headerLabel,
    card: cardDocumentsByIdentifier[identifier],
    selectedImage,
    compressed,
    onSelect: onSelectImage,
    showConfirmAffordance,
    activeAttributeTags,
    dismissedConfirmChipKeys,
    onDismissConfirmChip: dismissConfirmChip,
    onMoreLikeThis: applyMoreLikeThis,
    backendURL,
  });

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
        <SelectVersionTile
          {...tileProps(
            group.representative,
            label,
            group.status === "suggested"
          )}
        />
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
        {expanded &&
          group.rest.map((identifier) => (
            <SelectVersionTile
              key={identifier}
              {...tileProps(identifier, label, false)}
            />
          ))}
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
        <SelectVersionTile {...tileProps(group.representative, label, false)} />
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
        {expanded &&
          group.rest.map((identifier) => (
            <SelectVersionTile
              key={identifier}
              {...tileProps(identifier, label, false)}
            />
          ))}
      </div>
    );
  };

  const noResults =
    groups.canonical.length === 0 &&
    groups.nonCanonical.length === 0 &&
    groups.unknown.length === 0;

  return (
    <Row className="g-0" data-testid="select-version-section">
      {search.settingsVisible && (
        <Col lg={3} sm={4} xs={6} className="border-end p-0">
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
          />
        </Col>
      )}
      <Col
        lg={search.settingsVisible ? 9 : 12}
        sm={search.settingsVisible ? 8 : 12}
        xs={search.settingsVisible ? 6 : 12}
        className="p-0"
      >
        <FilterChipBar
          activeTagNames={activeAttributeTags}
          onToggle={toggleAttributeTag}
        />
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
          <div data-testid="select-version-group-unknown">
            {groups.unknown.map((identifier) => {
              // No printing/reason-tag identity to label this tile with (the "honest residue" -
              // see selectVersionGrouping.ts) - falls back to the same "Option N" numbering the
              // flat grid this section replaces always used (search.originalIndexMap, the same
              // map GridSelectorResults/CardResultSet already thread through for consistent
              // numbering), rather than inventing a new, less informative label.
              const originalIndex = search.originalIndexMap.get(identifier);
              const label =
                originalIndex != null
                  ? `Option ${originalIndex + 1}`
                  : "Unknown";
              return (
                <SelectVersionTile
                  key={identifier}
                  {...tileProps(identifier, label, false)}
                />
              );
            })}
          </div>
        )}
        {noResults && (
          <GenericErrorPage
            title="No results :("
            text={["Your filters didn't match any results."]}
          />
        )}
      </Col>
    </Row>
  );
}
