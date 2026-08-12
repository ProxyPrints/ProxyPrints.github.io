// The "border" question type's answer surface (docs/features/wtc-question-model.md §7): the
// border-colour axis rendered as chips, standing alone as the question. Built on the §7
// principle that "chips are the answer surface for an axis, not a filter panel parked on a
// question with nothing to narrow" (see the "frame / attribute narrowing" section).
//
// Deliberately a purpose-built sibling of AttributeChipPanel rather than the panel itself:
// the panel renders EVERY axis + the standalone toggles + the legend for the identify_printing
// follow-up, while a border question needs exactly the four BORDER_COLOR_GROUP chips plus the
// FULL_ART_CHIP (§5 rule 1: "render only what the current question needs"). Full Art is not a
// border colour - it co-occurs with every border value (§7), so it renders here as the "No
// border — full art." answer, a standalone toggle alongside the exclusive axis. The vote
// machinery is shared, not forked - these chips cast the same CardTagVote through the same
// APISubmitTagVote "question-feed" surface every other WTC chip casts (useTagVoting), so a
// border answer is a first-class vote on an existing axis, not a new vote model. The only
// schema addition anywhere on this surface is the optional `reason` on the existing
// abstention write that the "Can't tell from this scan." ActionRow answer sends - not a new
// vote model, endpoint, or chip.
import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  ChipRow,
  renderAttributeChip,
} from "@/features/attributeChips/attributeChipRender";
import {
  BORDER_COLOR_GROUP,
  ChipVoteState,
  FULL_ART_CHIP,
} from "@/features/attributeChips/attributeChips";
import { useTagVoting } from "@/features/attributeChips/useTagVoting";

interface BorderColorQuestionProps {
  backendURL: string;
  cardIdentifier: string;
  /** tagName -> weighted net polarity in [-1, 1] - seeded from the feed item's
   * tagConfidence, same contract AttributeChipPanel requires of its own callers. */
  tagConfidence: Record<string, number>;
  /** Controlled explicit vote state per tagName - lifted to QuestionFeed.tsx, which resets it
   * to initialChipStates() whenever a new item lands. */
  chipStates: Record<string, ChipVoteState>;
  onChipStatesChange: (next: Record<string, ChipVoteState>) => void;
  /** Called instead of the usual error toast when a submission is rejected with 429. */
  onRateLimited?: () => void;
}

export function BorderColorQuestion({
  backendURL,
  cardIdentifier,
  tagConfidence,
  chipStates,
  onChipStatesChange,
  onRateLimited,
}: BorderColorQuestionProps) {
  const getTagDisplayName = useTagDisplayName();
  const { confidence, submittingTagName, tap } = useTagVoting({
    backendURL,
    cardIdentifier,
    tagConfidence,
    chipStates,
    onChipStatesChange,
    onRateLimited,
  });

  const chipArgs = {
    confidence,
    chipStates,
    submittingTagName,
    tap,
    getTagDisplayName,
  };

  return (
    <ChipRow data-testid="question-feed-border-chips">
      {BORDER_COLOR_GROUP.chips.map((chip) =>
        renderAttributeChip(chipArgs, chip.tagName, chip.label)
      )}
      {renderAttributeChip(
        chipArgs,
        FULL_ART_CHIP.tagName,
        FULL_ART_CHIP.label
      )}
    </ChipRow>
  );
}
