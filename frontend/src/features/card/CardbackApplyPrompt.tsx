/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2/§E.2, OWNER AMENDMENT 2/OQ-B) - the shared
 * inline "Apply to all card backs" + "Set as my default cardback" prompt, rendered from BOTH
 * cardback-pick entries (the toolbar's project-wide `GridSelectorModal` footer, and the rail's
 * per-slot picker) - one component, so the two surfaces can't drift (§C.2's own binding
 * requirement). Never a second stacked modal - always rendered inline by its caller.
 *
 * Token table E.2 (BINDING, #302 palette): `.cbprompt` panel `#22303f` / `1px #16202b` border +
 * left `3px #df6919`; `.applybtn` primary-tinted (`#df6919` border / `#ffb27d` text, hover fills
 * `#df6919`/`#fff`, done state `#5cb85c`/`#8fe08f`); `.defbtn` info-tinted (`#5bc0de` border /
 * `#8fd7ea` text, hover fills `#5bc0de`/`#062430`, same done state); `.trapnote` `#ffd76a`
 * (rail only); `.skip` `#8fa0b0` underline link (toolbar only, since the rail per-slot picker
 * already IS the "no modal, ever" surface - leaving the section collapsed is itself "not now").
 */
import styled from "@emotion/styled";
import React, { useState } from "react";

import { CustomBackSlotThumbnail } from "@/features/card/cardbackApply";

const Panel = styled.div`
  background: #22303f;
  border: 1px solid #16202b;
  border-left: 3px solid #df6919;
  padding: 10px 12px;
  margin-top: 12px;
`;

const Title = styled.div`
  font-size: 13px;
  font-weight: 700;
  color: #ebebeb;
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
`;

const Intro = styled.div`
  font-size: 12px;
  color: #8fa0b0;
  margin-bottom: 10px;
`;

const Choice = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid #16202b;

  &:first-of-type {
    border-top: none;
  }
`;

const ChoiceLabel = styled.div`
  flex: 1;
  min-width: 0;

  .h {
    font-size: 13px;
    color: #ebebeb;
  }

  .s {
    font-size: 11px;
    color: #8fa0b0;
  }
`;

const ApplyButton = styled.button<{ $done: boolean }>`
  background: transparent;
  border: 1px solid ${(props) => (props.$done ? "#5cb85c" : "#df6919")};
  color: ${(props) => (props.$done ? "#8fe08f" : "#ffb27d")};
  font-family: inherit;
  font-size: 13px;
  padding: 4px 10px;
  cursor: ${(props) => (props.$done ? "default" : "pointer")};
  border-radius: 0;
  white-space: nowrap;
  pointer-events: ${(props) => (props.$done ? "none" : "auto")};

  &:hover {
    background: ${(props) => (props.$done ? "transparent" : "#df6919")};
    color: ${(props) => (props.$done ? "#8fe08f" : "#fff")};
  }
`;

const DefaultButton = styled.button<{ $done: boolean }>`
  background: transparent;
  border: 1px solid ${(props) => (props.$done ? "#5cb85c" : "#5bc0de")};
  color: ${(props) => (props.$done ? "#8fe08f" : "#8fd7ea")};
  font-family: inherit;
  font-size: 13px;
  padding: 4px 10px;
  cursor: ${(props) => (props.$done ? "default" : "pointer")};
  border-radius: 0;
  white-space: nowrap;
  pointer-events: ${(props) => (props.$done ? "none" : "auto")};

  &:hover {
    background: ${(props) => (props.$done ? "transparent" : "#5bc0de")};
    color: ${(props) => (props.$done ? "#8fe08f" : "#062430")};
  }
`;

const SkipRow = styled.div`
  margin-top: 8px;
  text-align: right;

  a {
    color: #8fa0b0;
    font-size: 12px;
    text-decoration: underline;
    cursor: pointer;
  }
`;

const TrapNote = styled.div`
  font-size: 11px;
  color: #ffd76a;
  margin-top: 8px;
  display: flex;
  gap: 5px;
  align-items: flex-start;
`;

const ThumbGrid = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
`;

const ThumbPair = styled.div`
  display: flex;
  align-items: center;
  gap: 3px;
  background: #16202b;
  border: 1px solid rgba(235, 235, 235, 0.15);
  padding: 3px;
`;

const ThumbImg = styled.div<{ $url: string | undefined }>`
  width: 32px;
  aspect-ratio: 63 / 88;
  background-color: #2a2320;
  background-image: ${(props) =>
    props.$url != null ? `url(${props.$url})` : "none"};
  background-size: cover;
  background-position: center;
`;

const ThumbLabel = styled.div`
  font-size: 9px;
  color: #8fa0b0;
  max-width: 90px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

export interface CardbackApplyPromptProps {
  /** Toolbar = project-wide canonical copy + a "Not now" skip link; rail = per-slot copy + the
   * never-pre-checked trap-guard line instead of a skip link (§C.2's own two-entry split). */
  entry: "toolbar" | "rail";
  /** How many back faces "Apply to all" would touch, including custom ones - the prompt's own
   * "Apply to all (N)" count (`countBackFacesAffectedByApplyAll`). */
  affectedCount: number;
  /** OWNER AMENDMENT 2/OQ-B - thumbnails (front + current custom back) of every slot "Apply to
   * all" would override, rendered ABOVE the count line. Empty when nothing is currently custom. */
  customBackThumbnails: Array<CustomBackSlotThumbnail>;
  onApplyAll: () => void;
  onSetDefault: () => void;
  /** Toolbar only - see this file's own header comment for why the rail entry has no skip link. */
  onDismiss?: () => void;
}

export function CardbackApplyPrompt({
  entry,
  affectedCount,
  customBackThumbnails,
  onApplyAll,
  onSetDefault,
  onDismiss,
}: CardbackApplyPromptProps) {
  const [applyDone, setApplyDone] = useState(false);
  const [defaultDone, setDefaultDone] = useState(false);

  const handleApplyAll = () => {
    onApplyAll();
    setApplyDone(true);
  };
  const handleSetDefault = () => {
    onSetDefault();
    setDefaultDone(true);
  };

  const isPerSlot = entry === "rail";

  return (
    <Panel data-testid="cardback-apply-prompt">
      <Title>✓ Cardback selected</Title>
      <Intro>
        {isPerSlot
          ? "Applied to this slot’s back only. Two optional next steps — both independent, both skippable:"
          : "Set as this project’s cardback. Two optional next steps — both independent, both skippable:"}
      </Intro>
      {customBackThumbnails.length > 0 && (
        <ThumbGrid data-testid="cardback-apply-prompt-thumbnails">
          {customBackThumbnails.map((thumbnail) => (
            <ThumbPair key={thumbnail.slotLabel} title={thumbnail.slotLabel}>
              <ThumbImg
                $url={thumbnail.frontThumbnailUrl}
                aria-label={`${thumbnail.slotLabel} front`}
              />
              <ThumbImg
                $url={thumbnail.backThumbnailUrl}
                aria-label={`${thumbnail.slotLabel} current custom back`}
              />
              <ThumbLabel>{thumbnail.slotLabel}</ThumbLabel>
            </ThumbPair>
          ))}
        </ThumbGrid>
      )}
      <Choice>
        <ChoiceLabel>
          <div className="h">Apply to all card backs in this deck</div>
          <div className="s">
            {isPerSlot
              ? "opt-in — nothing changes unless you tap"
              : `also overrides ${customBackThumbnails.length} card${
                  customBackThumbnails.length === 1 ? "" : "s"
                } with a custom back`}
          </div>
        </ChoiceLabel>
        <ApplyButton
          type="button"
          $done={applyDone}
          onClick={handleApplyAll}
          data-testid="cardback-apply-all-button"
        >
          {applyDone ? "Applied to all ✓" : `Apply to all (${affectedCount})`}
        </ApplyButton>
      </Choice>
      <Choice>
        <ChoiceLabel>
          <div className="h">Set as my default cardback</div>
          <div className="s">used for new projects &amp; new slots</div>
        </ChoiceLabel>
        <DefaultButton
          type="button"
          $done={defaultDone}
          onClick={handleSetDefault}
          data-testid="cardback-set-default-button"
        >
          {defaultDone ? "Default set ✓" : "Set default"}
        </DefaultButton>
      </Choice>
      {isPerSlot ? (
        <TrapNote data-testid="cardback-apply-prompt-trapnote">
          <span aria-hidden="true">⚠</span>
          <span>
            Per-slot pick stays per-slot. &quot;Apply to all&quot; is never
            pre-checked — a single-slot choice can&apos;t silently rewrite the
            deck.
          </span>
        </TrapNote>
      ) : (
        onDismiss != null && (
          <SkipRow>
            <a
              onClick={onDismiss}
              data-testid="cardback-apply-prompt-not-now"
              role="button"
              tabIndex={0}
            >
              Not now
            </a>
          </SkipRow>
        )
      )}
    </Panel>
  );
}
