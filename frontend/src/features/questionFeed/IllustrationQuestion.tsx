import styled from "@emotion/styled";
import React, { useState } from "react";

import { errorToNotification } from "@/common/apiErrors";
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

const IllustrationTile = styled(CandidateButton)`
  position: relative;
  overflow: hidden;
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
        candidate.illustrationId!,
        "positive"
      );
      onAnswered();
    } catch (error: unknown) {
      const notification = errorToNotification(error);
      if (notification?.type === "rateLimited") {
        onRateLimited?.();
      } else {
        dispatch(setNotification(notification));
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
        candidate.illustrationId!
      );
      onAnswered();
    } catch (error: unknown) {
      const notification = errorToNotification(error);
      if (notification?.type === "rateLimited") {
        onRateLimited?.();
      } else {
        dispatch(setNotification(notification));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <IllustrationGrid data-testid="question-feed-illustration-grid">
      {item.illustrationCandidates!.map((candidate) => (
        <IllustrationTile
          key={candidate.illustrationId || "unknown"}
          as="button"
          data-testid={`question-feed-illustration-${candidate.illustrationId}`}
          onClick={() => handleSelectIllustration(candidate)}
          disabled={submitting}
          title={`${candidate.expansionName} (${candidate.expansionCode}) - ${candidate.artist}`}
        >
          {candidate.artCropUrl ? (
            <ZoomableThumbnail
              src={candidate.artCropUrl}
              alt={`${candidate.expansionName} art`}
            />
          ) : (
            <IllustrationArtPlaceholder />
          )}
        </IllustrationTile>
      ))}
    </IllustrationGrid>
  );
}
