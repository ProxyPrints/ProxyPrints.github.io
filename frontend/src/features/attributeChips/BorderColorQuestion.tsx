// The "border" question type's answer surface (docs/features/wtc-question-model.md §7): the
// border-colour axis rendered as chips, standing alone as the question. Built on the §7
// principle that "chips are the answer surface for an axis, not a filter panel parked on a
// question with nothing to narrow" (see the "frame / attribute narrowing" section).
//
// Deliberately a purpose-built sibling of AttributeChipPanel rather than the panel itself:
// the panel renders EVERY axis + the standalone toggles + the legend for the identify_printing
// follow-up, while a border question needs exactly the four BORDER_COLOR_GROUP chips, the
// FULL_ART_CHIP, and FRAME_TREATMENT_GROUP's two chips (§5 rule 1: "render only what the
// current question needs"). Full Art is not a border colour - it co-occurs with every border
// value (§7), so it renders here as the "No border — full art." answer, a standalone toggle
// alongside the exclusive axis.
//
// FRAME_TREATMENT_GROUP (Showcase / Extended Art) was added here because this question is
// ONLY ever served when the card's own candidates split on `borderColor`
// (`_candidates_split_on_border`, question_feed.py's only call site for `_border_item`) - and a
// live sample of that served population found candidates that share a `borderColor` and differ
// solely on `isExtendedArt`/`isShowcase` (e.g. a plain black-border printing vs. its
// extended-art reprint, both `border_color: black` on Scryfall). Neither is describable by the
// four colours or Full Art, so the four-colour set alone cannot separate them even though the
// question is worth asking. Both treatments clear the same "a lay voter can recognise it by
// sight" bar §7.7 used to rule the set-symbol question OUT (running artwork to the card edge,
// vs. the bordered accent frame, are both plainly visible on the scan) - the same reasoning
// that ruled symbol out is what admits these in. Showcase is included alongside Extended Art,
// not just Extended Art alone: the same live sample found candidates split on `isShowcase`
// too, and the two chips are already one `ExclusionGroup` (co-occurring in 0 of 113,224
// printings per that group's own comment), so rendering the pair costs nothing extra and keeps
// the mutual-exclusion (implied-negative) styling `isChipContradicted` already derives from
// `FRAME_TREATMENT_GROUP` membership. The vote machinery is shared, not forked - every chip
// here, including these two, casts the same CardTagVote through the same APISubmitTagVote
// "question-feed" surface every other WTC chip casts (useTagVoting), so a border answer is a
// first-class vote on an existing axis, not a new vote model. The only schema addition
// anywhere on this surface is the optional `reason` on the existing abstention write that the
// "Can't tell from this scan." ActionRow answer sends - not a new vote model, endpoint, or chip.
import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  ChipRow,
  renderAttributeChip,
} from "@/features/attributeChips/attributeChipRender";
import {
  BORDER_COLOR_GROUP,
  ChipVoteState,
  FRAME_TREATMENT_GROUP,
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
      {FRAME_TREATMENT_GROUP.chips.map((chip) =>
        renderAttributeChip(chipArgs, chip.tagName, chip.label)
      )}
    </ChipRow>
  );
}
