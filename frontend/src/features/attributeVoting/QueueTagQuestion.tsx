/**
 * Focused single-(card, tag)-question control for the tag-mode vote queue - deliberately not
 * a reuse of TagVotePicker.tsx's full chip grid (which shows every seeded tag at once for one
 * card - a different unit of interaction). Each queue item here is exactly one contested/
 * unresolved (card, tag) pair, so this only ever asks about that one tag: apply, not
 * applicable, or skip. Submits via the same APISubmitTagVote used by TagVotePicker.
 */

import React, { useRef, useState } from "react";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch } from "@/common/types";
import { ActionButton } from "@/features/attributeVoting/ActionButton";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface QueueTagQuestionProps {
  backendURL: string;
  cardIdentifier: string;
  tagName: string;
  /** Called once the user has answered (apply/not applicable submitted successfully) or skipped. */
  onAnswered: () => void;
  /** "include" attaches the moderator session cookie, making the vote privileged at
   * resolution time - used by the question feed's "moderation" question type (see
   * QuestionFeed.tsx), which reuses this exact component rather than forking a moderator-only
   * variant. Defaults to "same-origin" - unchanged behavior for every pre-existing caller. */
  credentials?: RequestCredentials;
  /** Called instead of the usual error toast when a submission is rejected with 429 - see
   * ArtistVotePicker.tsx's identical prop for the full rationale. This component has only one
   * caller today (QuestionFeed.tsx), so this is effectively always provided, but stays optional
   * to match the same safe-default convention as the other funnel components. */
  onRateLimited?: () => void;
}

const APPLY = 1;
const NOT_APPLICABLE = -1;

export function QueueTagQuestion({
  backendURL,
  cardIdentifier,
  tagName,
  onAnswered,
  credentials = "same-origin",
  onRateLimited,
}: QueueTagQuestionProps) {
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  const [submitting, setSubmitting] = useState<boolean>(false);
  // Issue #715 - `disabled={submitting}` only applies on the re-render React batches AFTER the
  // current handler returns, so a fast double-tap could cast the vote twice; this ref is set
  // synchronously at handler entry and drops the second entry (Skip included - a double-tap on
  // Skip must not advance two cards).
  const inFlightRef = useRef<boolean>(false);

  const submit = (polarity: number) => {
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    setSubmitting(true);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      polarity,
      credentials,
      "question-feed"
    )
      .then(() => onAnswered())
      .catch((error) => {
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
                "Something went wrong submitting your vote - please try again.",
            }),
          ])
        );
      })
      .finally(() => {
        inFlightRef.current = false;
        setSubmitting(false);
      });
  };

  return (
    <div data-testid="queue-tag-question">
      <h6>
        Does <strong>{getTagDisplayName(tagName)}</strong> apply?
      </h6>
      <div className="d-flex gap-2 mt-2">
        <ActionButton
          className="primary"
          disabled={submitting}
          onClick={() => submit(APPLY)}
        >
          Apply
        </ActionButton>
        <ActionButton
          className="secondary"
          disabled={submitting}
          onClick={() => submit(NOT_APPLICABLE)}
        >
          Not applicable
        </ActionButton>
        <ActionButton
          className="ghost"
          disabled={submitting}
          onClick={() => {
            if (inFlightRef.current) {
              return;
            }
            inFlightRef.current = true;
            onAnswered();
          }}
        >
          Skip
        </ActionButton>
      </div>
    </div>
  );
}
