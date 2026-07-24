/**
 * "Why no match?" follow-up shown in PrintingTagQueue.tsx immediately after a user submits
 * an explicit "No match" printing vote (not shown for a still-contested candidate pick -
 * that case keeps using the general AttributeVotingPanel, see the call site). One tap on a
 * reason chip casts a single positive CardTagVote for that reason and advances; Skip
 * advances without voting. Deliberately not the full TagVotePicker grid - this is a
 * narrower, faster "why" prompt matched to the moment right after a no-match tap, not a
 * general tagging surface.
 *
 * Keep the six tagName values below in sync with cardpicker/reason_tags.py (seeded via the
 * `seed_no_match_reason_tags` management command, not a migration - see that module's
 * header comment for why) - and see the same file for why these are a separate taxonomy
 * from cardpicker.default_tags.DEFAULT_TAGS and why renaming any of them is a breaking
 * change. Chip labels are NOT hardcoded here - they're the seeded `display_name` for each
 * tag, looked up dynamically (useTagDisplayName), so editing a display_name in admin changes
 * what's shown here without a frontend deploy.
 *
 * Graceful degradation for an instance where that command hasn't been run yet: filters the
 * six chips down to whichever tags `useGetTagsQuery` (the existing, already-cached `2/tags/`
 * query used elsewhere for the search-filter tag tree - no new endpoint/fetch introduced
 * here) actually reports. While that query is still loading, shows all six optimistically
 * rather than flashing an empty strip - a stale-positive chip just fails the same way an
 * unseeded one always would (a caught, toasted "Vote failed"), it's not a worse outcome than
 * today's baseline. Once loaded, unseeded chips are hidden entirely rather than shown
 * disabled, since there's nothing useful for a voter to do with one that will only ever 400.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch } from "@/common/types";
import { ChipCard } from "@/features/attributeVoting/ChipCard";
import { APISubmitTagVote, useGetTagsQuery } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

const APPLY = 1;

const NO_MATCH_REASON_TAG_NAMES: Array<string> = [
  "custom-art",
  "altered-frame",
  "upscaled",
  "ai-art",
  "no-collector-line",
  "non-english",
];

interface NoMatchReasonStripProps {
  backendURL: string;
  cardIdentifier: string;
  /** Called once a reason has been submitted, or the user skips. */
  onDone: () => void;
  /** Called instead of the usual error toast when a submission is rejected with 429 - see
   * ArtistVotePicker.tsx's identical prop for the full rationale. This component has only one
   * caller today (QuestionFeed.tsx), so this is effectively always provided, but stays optional
   * to match the same safe-default convention as the other funnel components. */
  onRateLimited?: () => void;
}

export function NoMatchReasonStrip({
  backendURL,
  cardIdentifier,
  onDone,
  onRateLimited,
}: NoMatchReasonStripProps) {
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );
  const { data: existingTags } = useGetTagsQuery();
  const existingTagNames =
    existingTags != null ? new Set(existingTags.map((tag) => tag.name)) : null;
  const visibleReasonTagNames = NO_MATCH_REASON_TAG_NAMES.filter(
    (tagName) => existingTagNames == null || existingTagNames.has(tagName)
  );

  const choose = (tagName: string) => {
    setSubmittingTagName(tagName);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      APPLY,
      "same-origin",
      "question-feed"
    )
      .then(() => onDone())
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
      .finally(() => setSubmittingTagName(null));
  };

  return (
    <div data-testid="no-match-reason-strip">
      <h6>Why no match?</h6>
      <Row className="g-2" xs={2} md={3}>
        {visibleReasonTagNames.map((tagName) => (
          <Col key={tagName}>
            <ChipCard
              label={getTagDisplayName(tagName)}
              disabled={submittingTagName != null}
              onClick={() => choose(tagName)}
              data-testid={`no-match-reason-${tagName}`}
              variant="danger"
            />
          </Col>
        ))}
      </Row>
      <div className="mt-2">
        <Button
          variant="outline-secondary"
          disabled={submittingTagName != null}
          onClick={onDone}
          data-testid="no-match-reason-skip"
        >
          Skip
        </Button>
      </div>
    </div>
  );
}
