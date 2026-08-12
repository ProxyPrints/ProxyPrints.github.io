import styled from "@emotion/styled";
import React, { useState } from "react";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { PrintingCandidate, QuestionFeedItem } from "@/common/schema_types";
import { useAppDispatch } from "@/common/types";
import {
  CandidateButton,
  IllustrationArtPlaceholder,
  ZoomableThumbnail,
} from "@/features/printingTags/cardPanel";
import {
  APISubmitIllustrationRejection,
  APISubmitIllustrationVote,
} from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface IllustrationQuestionProps {
  item: QuestionFeedItem;
  backendURL: string;
  onAnswered: () => void;
  onRateLimited?: () => void;
}

const IllustrationGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  padding: 16px 0;
`;

const IllustrationTileWrapper = styled.div`
  position: relative;
`;

const IllustrationTile = styled(CandidateButton)`
  overflow: hidden;
`;

const RejectButton = styled.button`
  position: absolute;
  top: 4px;
  right: 4px;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;

  &:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
`;

export function IllustrationQuestion({
  item,
  backendURL,
  onAnswered,
  onRateLimited,
}: IllustrationQuestionProps) {
  const dispatch = useAppDispatch();
  const [submitting, setSubmitting] = useState(false);

  if (
    !item.illustrationCandidates ||
    item.illustrationCandidates.length === 0
  ) {
    return null;
  }

  const handleSelectIllustration = async (candidate: PrintingCandidate) => {
    if (submitting || !candidate.illustrationId) return;

    setSubmitting(true);
    try {
      await APISubmitIllustrationVote(
        backendURL,
        item.card.identifier,
        getOrCreateAnonymousId(),
        candidate.illustrationId!,
        false,
        "question-feed"
      );
      onAnswered();
    } catch (error: unknown) {
      if (isRateLimited(error)) {
        onRateLimited?.();
      } else {
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
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRejectIllustration = async (candidate: PrintingCandidate) => {
    if (submitting || !candidate.illustrationId) return;

    setSubmitting(true);
    try {
      await APISubmitIllustrationRejection(
        backendURL,
        item.card.identifier,
        getOrCreateAnonymousId(),
        candidate.illustrationId!
      );
      onAnswered();
    } catch (error: unknown) {
      if (isRateLimited(error)) {
        onRateLimited?.();
      } else {
        dispatch(
          setNotification([
            Math.random().toString(),
            errorToNotification(error, {
              name: "Rejection failed",
              message:
                "Something went wrong recording that this isn't the artwork - please try again.",
            }),
          ])
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <IllustrationGrid data-testid="question-feed-illustration-grid">
      {item.illustrationCandidates!.map((candidate) => (
        <IllustrationTileWrapper key={candidate.illustrationId || "unknown"}>
          <IllustrationTile
            as="button"
            data-testid={`question-feed-illustration-${candidate.illustrationId}`}
            onClick={() => handleSelectIllustration(candidate)}
            disabled={submitting}
            title={`${candidate.expansionName} (${candidate.expansionCode}) - ${candidate.artist}`}
          >
            {candidate.artCropUrl ? (
              <ZoomableThumbnail>
                <img
                  src={candidate.artCropUrl}
                  alt={`${candidate.expansionName} art`}
                />
              </ZoomableThumbnail>
            ) : (
              <IllustrationArtPlaceholder />
            )}
          </IllustrationTile>
          <RejectButton
            type="button"
            data-testid={`question-feed-illustration-reject-${candidate.illustrationId}`}
            title="Not this art"
            aria-label="Not this art"
            disabled={submitting}
            onClick={() => handleRejectIllustration(candidate)}
          >
            <i className="bi bi-x-circle-fill" />
          </RejectButton>
        </IllustrationTileWrapper>
      ))}
    </IllustrationGrid>
  );
}
