/**
 * "Why no match?" follow-up shown in PrintingTagQueue.tsx immediately after a user submits
 * an explicit "No match" printing vote (not shown for a still-contested candidate pick -
 * that case keeps using the general AttributeVotingPanel, see the call site). One tap on a
 * reason chip casts a single positive CardTagVote for that reason and advances; Skip
 * advances without voting. Deliberately not the full TagVotePicker grid - this is a
 * narrower, faster "why" prompt matched to the moment right after a no-match tap, not a
 * general tagging surface.
 *
 * Keep the tagName values below in sync with cardpicker/reason_tags.py (seeded via the
 * `seed_no_match_reason_tags` management command, not a migration - see that module's
 * header comment for why) - and see the same file for why these are a separate taxonomy
 * from cardpicker.default_tags.DEFAULT_TAGS and why renaming any of them is a breaking
 * change. Chip labels are NOT hardcoded here - they're the seeded `display_name` for each
 * tag, looked up dynamically (useTagDisplayName), so editing a display_name in admin changes
 * what's shown here without a frontend deploy.
 *
 * WTC phase B (2026-07-28): the seven reason chips actually answer two DIFFERENT questions,
 * conflated into one flat wall of chips until now - see NO_MATCH_REASON_TAG_GROUPS below,
 * the single source of truth for the split, rendered here as two headed chip groups within
 * the same strip (not a two-step choose-axis-then-reason flow: the whole taxonomy is only
 * seven tags, so a second tap-through step would cost more than the one flat strip it
 * replaces, and grouped headers already make the two questions legible at a glance). This
 * component still only ever casts ONE positive CardTagVote per tap, through the same
 * endpoint, regardless of which group the tapped chip is in - the split is presentational
 * plus a shared routing constant, not a new vote shape.
 *
 * Graceful degradation for an instance where that command hasn't been run yet: filters the
 * chips down to whichever tags `useGetTagsQuery` (the existing, already-cached `2/tags/`
 * query used elsewhere for the search-filter tag tree - no new endpoint/fetch introduced
 * here) actually reports. While that query is still loading, shows all of them optimistically
 * rather than flashing an empty strip - a stale-positive chip just fails the same way an
 * unseeded one always would (a caught, toasted "Vote failed"), it's not a worse outcome than
 * today's baseline. Once loaded, unseeded chips are hidden entirely rather than shown
 * disabled, since there's nothing useful for a voter to do with one that will only ever 400.
 * Applies per-group here too: a group with zero visible chips (once loaded) renders nothing,
 * not an empty header.
 */

import React, { useRef, useState } from "react";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch } from "@/common/types";
import { ActionButton } from "@/features/attributeVoting/ActionButton";
import { ChipCard } from "@/features/attributeVoting/ChipCard";
import { APISubmitTagVote, useGetTagsQuery } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

const APPLY = 1;

/**
 * The two-way partition of the no-match reason taxonomy, exported so downstream consumers
 * (the phase-C illustration funnel: not-official-*printing* cards stay in it, not-official-
 * *art* cards drop out) import this instead of re-deriving which chips mean "the art itself
 * isn't official" - see reason_tags.py's docstring for the same split documented backend-side
 * and the owner-decided rationale in docs/features/printing-tags.md.
 *
 * Exhaustive over the current seven-tag taxonomy - asserted by a test in
 * NoMatchReasonStrip.spec.ts (union covers every tag, no overlap) specifically so a future
 * tag added to reason_tags.py without a corresponding entry here fails loudly instead of
 * silently missing from the UI (and from phase C's routing).
 *
 * - "not-official-printing": the artwork is genuine, the physical card is not. The artwork
 *   question stays ANSWERABLE for these cards.
 * - "not-official-art": the artwork itself isn't from any official card. The artwork
 *   question is UNANSWERABLE for these cards.
 */
export const NO_MATCH_REASON_TAG_GROUPS = {
  "not-official-printing": {
    label: "Not an official printing",
    hint: "The art is genuine - this copy of the card isn't.",
    tagNames: ["altered-frame", "upscaled", "no-collector-line", "non-english"],
  },
  "not-official-art": {
    label: "Not official art",
    hint: "The artwork itself isn't from any official card.",
    tagNames: ["custom-art", "ai-art", "external-ip"],
  },
} as const;

export type NoMatchReasonGroupKey = keyof typeof NO_MATCH_REASON_TAG_GROUPS;

// Derived from NO_MATCH_REASON_TAG_GROUPS above (the source of truth), not hand-maintained.
// Exported (rather than kept file-private like before the phase B split) since a flat "every
// no-match reason tag name" list is still the right shape for a couple of things: the
// exhaustiveness test in NoMatchReasonStrip.spec.ts, and any future caller that wants "is
// this tag a no-match reason at all" without caring which axis.
export const NO_MATCH_REASON_TAG_NAMES: Array<string> = (
  Object.keys(NO_MATCH_REASON_TAG_GROUPS) as Array<NoMatchReasonGroupKey>
).flatMap((groupKey) => [...NO_MATCH_REASON_TAG_GROUPS[groupKey].tagNames]);

interface NoMatchReasonStripProps {
  backendURL: string;
  cardIdentifier: string;
  /** Called once a reason has been submitted (with the chosen tagName), or the user skips
   * (with no argument) - the caller uses the tagName to route not-official-printing answers
   * back to the candidate grid instead of straight to the next item, see QuestionFeed.tsx's
   * own onNoMatchReasonDone. */
  onDone: (chosenTagName?: string) => void;
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
  // Issue #715 - same synchronous in-flight guard as the other funnel components: the visual
  // `disabled` lags a fast double-tap by a render, so the ref drops the second chip tap (and
  // the second Skip) before a vote can be cast twice.
  const inFlightRef = useRef<boolean>(false);
  const { data: existingTags } = useGetTagsQuery();
  const existingTagNames =
    existingTags != null ? new Set(existingTags.map((tag) => tag.name)) : null;
  const isVisible = (tagName: string) =>
    existingTagNames == null || existingTagNames.has(tagName);

  const choose = (tagName: string) => {
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
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
      .then(() => onDone(tagName))
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
        setSubmittingTagName(null);
      });
  };

  return (
    <div data-testid="no-match-reason-strip">
      <h6>Why no match?</h6>
      {(
        Object.keys(NO_MATCH_REASON_TAG_GROUPS) as Array<NoMatchReasonGroupKey>
      ).map((groupKey) => {
        const group = NO_MATCH_REASON_TAG_GROUPS[groupKey];
        const visibleTagNames = group.tagNames.filter(isVisible);
        if (visibleTagNames.length === 0) {
          // Graceful degradation applies per-group too (see file header comment) - a group
          // with nothing visible in it renders no header at all rather than a bare label.
          return null;
        }
        return (
          <div
            key={groupKey}
            className="mb-3"
            data-testid={`no-match-reason-group-${groupKey}`}
          >
            <div className="small text-uppercase text-muted fw-bold mb-1">
              {group.label}
            </div>
            <div className="small text-muted mb-2">{group.hint}</div>
            <Row className="g-2" xs={2} md={3}>
              {visibleTagNames.map((tagName) => (
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
          </div>
        );
      })}
      <div className="mt-2">
        <ActionButton
          className="ghost"
          disabled={submittingTagName != null}
          onClick={() => {
            if (inFlightRef.current) {
              return;
            }
            inFlightRef.current = true;
            onDone();
          }}
          data-testid="no-match-reason-skip"
        >
          Skip
        </ActionButton>
      </div>
    </div>
  );
}
