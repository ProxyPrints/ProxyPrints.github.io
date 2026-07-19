/**
 * The tri-state tap -> optimistic update -> APISubmitTagVote -> reconcile-or-revert cycle
 * AttributeChipPanel.tsx originally owned inline. Extracted (Proposal H pane migration,
 * left-panel unification) so the display page's rail Attributes section
 * (features/display/AttributesSection.tsx) can cast the exact same votes through the exact
 * same call, rather than a second, drifting copy of this logic living next to a differently-
 * laid-out chip grid - the design doc's §5 component-mapping table calls this out explicitly:
 * "the tri-state cycling and vote-submission logic is unchanged," only the surrounding layout
 * (ring around a card vs. a plain vertical stack) differs between the two callers.
 *
 * AttributeChipPanel itself now delegates to this hook instead of carrying the logic directly -
 * its own public props/behavior (and therefore AttributeChipPanel.test.tsx) are unchanged.
 */
import { useEffect, useState } from "react";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useAppDispatch } from "@/common/types";
import {
  CHIP_POLARITY,
  ChipVoteState,
  nextChipState,
} from "@/features/attributeChips/attributeChips";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

export interface UseTagVotingArgs {
  backendURL: string;
  cardIdentifier: string;
  /** tagName -> weighted net polarity in [-1, 1] - the caller's own initial/refreshed reading
   * (QuestionFeed.tsx's feed-item payload; the rail's own APIGetTagConsensus fetch). */
  tagConfidence: Record<string, number>;
  /** Controlled explicit vote state per tagName - lifted to the caller, same contract
   * AttributeChipPanel already required of its own callers. */
  chipStates: Record<string, ChipVoteState>;
  onChipStatesChange: (next: Record<string, ChipVoteState>) => void;
  /** Called instead of the usual error toast when a submission is rejected with 429. */
  onRateLimited?: () => void;
}

export interface UseTagVotingResult {
  /** Live-updating tagName -> net polarity, seeded from tagConfidence and reconciled against
   * each vote's own server response - what a caller renders as chip fill. */
  confidence: Record<string, number>;
  /** The tagName currently mid-submission (disables every chip until it settles), or null. */
  submittingTagName: string | null;
  /** Cycles the given tag's state (untouched -> positive -> negative -> untouched) and casts
   * exactly one real vote for that tap. */
  tap: (tagName: string) => void;
}

export function useTagVoting({
  backendURL,
  cardIdentifier,
  tagConfidence,
  chipStates,
  onChipStatesChange,
  onRateLimited,
}: UseTagVotingArgs): UseTagVotingResult {
  const dispatch = useAppDispatch();
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );
  const [confidence, setConfidence] =
    useState<Record<string, number>>(tagConfidence);

  useEffect(() => {
    setConfidence(tagConfidence);
  }, [tagConfidence]);

  const tap = (tagName: string) => {
    const previousState = chipStates[tagName] ?? "untouched";
    const previousConfidence = confidence[tagName] ?? 0;
    const nextState = nextChipState(previousState);
    const polarity = CHIP_POLARITY[nextState];

    // optimistic: nudge the fill toward the tapped direction immediately, and update the
    // explicit state right away - both get reconciled with the server response below
    onChipStatesChange({ ...chipStates, [tagName]: nextState });
    setConfidence((previous) => ({
      ...previous,
      [tagName]: polarity === 0 ? 0 : polarity,
    }));
    setSubmittingTagName(tagName);

    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      polarity,
      "same-origin",
      "question-feed"
    )
      .then((response) => {
        setConfidence((previous) => ({
          ...previous,
          [tagName]: response.netPolarity,
        }));
      })
      .catch((error) => {
        // revert both the explicit state and the optimistic fill on failure - the vote
        // genuinely wasn't recorded regardless of which branch below fires
        onChipStatesChange({ ...chipStates, [tagName]: previousState });
        setConfidence((previous) => ({
          ...previous,
          [tagName]: previousConfidence,
        }));
        if (isRateLimited(error) && onRateLimited) {
          onRateLimited();
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
      .finally(() => setSubmittingTagName(null));
  };

  return { confidence, submittingTagName, tap };
}
