/**
 * The display page rail's Attributes accordion section (Proposal H pane migration, left-panel
 * unification - see docs/proposals/proposal-h-unified-display-page.md §5's component-mapping
 * table). Reuses attributeChips.ts's taxonomy and useTagVoting's tap/vote-submission logic
 * verbatim - only the arrangement differs from AttributeChipPanel.tsx's ring-around-a-card
 * layout, since the rail has no card slot to ring around, just a plain vertical stack (matching
 * ChipRing's own existing "collapses to vertical stack below 576px" behavior, always-on here
 * rather than viewport-conditional - see the design doc's §1 citation of that same CSS rule).
 *
 * tagConfidence/initial chipStates aren't handed down from a question-feed item payload here (the
 * rail has no such payload) - this component fetches them itself via APIGetTagConsensus, the same
 * per-card consensus lookup bleedPriorResolution.ts already uses for the export-time bleed prior,
 * scoped down to just the attribute-chip taxonomy's own tag names.
 */
import React, { useEffect, useState } from "react";

import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  ChipRow,
  hasAttributeLean,
  renderAttributeChip,
} from "@/features/attributeChips/attributeChipRender";
import {
  ALL_ATTRIBUTE_CHIPS,
  ChipVoteState,
  EXCLUSION_GROUPS,
  STANDALONE_CHIPS,
} from "@/features/attributeChips/attributeChips";
import { useTagVoting } from "@/features/attributeChips/useTagVoting";
import { APIGetTagConsensus } from "@/store/api";

const ATTRIBUTE_TAG_NAMES = new Set(
  ALL_ATTRIBUTE_CHIPS.map((chip) => chip.tagName)
);

function initialChipStates(): Record<string, ChipVoteState> {
  return Object.fromEntries(
    ALL_ATTRIBUTE_CHIPS.map((chip) => [chip.tagName, "untouched"])
  );
}

interface AttributesSectionProps {
  backendURL: string;
  /** The selected slot's currently selected image identifier - undefined when the slot has no
   * art selected yet, in which case there's no card to vote on. */
  cardIdentifier: string | undefined;
}

export function AttributesSection({
  backendURL,
  cardIdentifier,
}: AttributesSectionProps) {
  const getTagDisplayName = useTagDisplayName();
  const [status, setStatus] = useState<"loading" | "loaded" | "error">(
    "loading"
  );
  const [tagConfidence, setTagConfidence] = useState<Record<string, number>>(
    {}
  );
  const [chipStates, setChipStates] = useState<Record<string, ChipVoteState>>(
    initialChipStates()
  );

  useEffect(() => {
    if (cardIdentifier == null) {
      return;
    }
    let cancelled = false;
    setStatus("loading");
    APIGetTagConsensus(backendURL, cardIdentifier)
      .then((response) => {
        if (cancelled) {
          return;
        }
        const confidence: Record<string, number> = {};
        const states = initialChipStates();
        response.tags.forEach((tag) => {
          if (!ATTRIBUTE_TAG_NAMES.has(tag.tagName)) {
            // The consensus endpoint returns every tag this card has votes on (e.g.
            // "appropriate-bleed", Proposal B's own tag) - only the attribute-chip taxonomy's
            // own tags are relevant here.
            return;
          }
          confidence[tag.tagName] = tag.netPolarity;
          if (tag.resolvedPolarity === 1) {
            states[tag.tagName] = "positive";
          } else if (tag.resolvedPolarity === -1) {
            states[tag.tagName] = "negative";
          }
        });
        setTagConfidence(confidence);
        setChipStates(states);
        setStatus("loaded");
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, cardIdentifier]);

  const { confidence, submittingTagName, tap } = useTagVoting({
    backendURL,
    cardIdentifier: cardIdentifier ?? "",
    tagConfidence,
    chipStates,
    onChipStatesChange: setChipStates,
  });

  if (cardIdentifier == null) {
    return (
      <p className="text-muted small mb-0">
        Select an image for this slot first - attribute votes apply to the
        specific printing shown, not the slot in the abstract.
      </p>
    );
  }

  if (status === "loading") {
    return <p className="text-muted small mb-0">Loading attribute data…</p>;
  }

  if (status === "error") {
    return (
      <p className="text-muted small mb-0">
        Couldn&apos;t load attribute data for this card - try again shortly.
      </p>
    );
  }

  const chipArgs = {
    confidence,
    chipStates,
    submittingTagName,
    tap,
    getTagDisplayName,
  };
  const [borderColorGroup, frameStyleGroup] = EXCLUSION_GROUPS;

  return (
    <div data-testid="display-attributes-section">
      {hasAttributeLean(confidence) && (
        <p className="text-muted small mb-2">
          Chip color shows how community + machine votes lean - not a confirmed
          fact.
        </p>
      )}
      <ChipRow className="mb-2">
        {STANDALONE_CHIPS.map((chip) =>
          renderAttributeChip(chipArgs, chip.tagName, chip.label)
        )}
      </ChipRow>
      {borderColorGroup != null && (
        <>
          <div className="text-muted small">{borderColorGroup.label}</div>
          <ChipRow className="mb-2">
            {borderColorGroup.chips.map((chip) =>
              renderAttributeChip(chipArgs, chip.tagName, chip.label)
            )}
          </ChipRow>
        </>
      )}
      {frameStyleGroup != null && (
        <>
          <div className="text-muted small">{frameStyleGroup.label}</div>
          <ChipRow>
            {frameStyleGroup.chips.map((chip) =>
              renderAttributeChip(chipArgs, chip.tagName, chip.label)
            )}
          </ChipRow>
        </>
      )}
    </div>
  );
}
