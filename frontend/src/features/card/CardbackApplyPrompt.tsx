/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.2/§E.2, OWNER AMENDMENT 2/OQ-B) - the shared
 * inline "Apply to all card backs" + "Set as my default cardback" prompt, rendered from BOTH
 * cardback-pick entries (the toolbar's project-wide `GridSelectorModal` footer, and the rail's
 * per-slot picker) - one component, so the two surfaces can't drift (§C.2's own binding
 * requirement). Never a second stacked modal - always rendered inline by its caller.
 *
 * Token table E.2 (BINDING, #302 palette; re-themed to Tokyo-11, 2026-07-24 - see
 * docs/features/theming.md - tokens and spec tables move together, same discipline
 * DisplayLeftRailFidelity.spec.ts's own re-theme pass used): `.cbprompt` panel
 * $theme-raised-bg / `1px` $theme-divider border + left `3px` $primary; `.applybtn`
 * primary-tinted ($primary border/text, hover fills $primary/$theme-btn-ink - Tokyo-11's
 * primary is light, so the filled-hover state needs the dark ink, not white -, done state
 * $success/$success); `.defbtn` info-tinted ($info border/text, hover fills $info/
 * $theme-btn-ink, same done state); `.trapnote` $warning (rail only); `.skip` $theme-muted
 * underline link (toolbar only, since the rail per-slot picker already IS the "no modal,
 * ever" surface - leaving the section collapsed is itself "not now"). Unlike the #302 palette,
 * Tokyo-11's primary/info/success tokens are all light enough to use directly as text colour -
 * no separate hand-picked tint literal is needed the way `#ffb27d`/`#8fd7ea` were.
 */
import styled from "@emotion/styled";
import React, { useState } from "react";

import { CustomBackSlotThumbnail } from "@/features/card/cardbackApply";

const Panel = styled.div`
  background: var(--theme-raised-bg);
  border: 1px solid var(--theme-divider);
  border-left: 3px solid var(--bs-primary);
  padding: 10px 12px;
  margin-top: 12px;
`;

const Title = styled.div`
  font-size: 13px;
  font-weight: 700;
  color: var(--bs-body-color);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
`;

const Intro = styled.div`
  font-size: 12px;
  color: var(--theme-muted);
  margin-bottom: 10px;
`;

const Choice = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid var(--theme-divider);

  &:first-of-type {
    border-top: none;
  }
`;

const ChoiceLabel = styled.div`
  flex: 1;
  min-width: 0;

  .h {
    font-size: 13px;
    color: var(--bs-body-color);
  }

  .s {
    font-size: 11px;
    color: var(--theme-muted);
  }
`;

const ApplyButton = styled.button<{ $done: boolean }>`
  background: transparent;
  border: 1px solid
    ${(props) => (props.$done ? "var(--bs-success)" : "var(--bs-primary)")};
  color: ${(props) =>
    props.$done ? "var(--bs-success)" : "var(--bs-primary)"};
  font-family: inherit;
  font-size: 13px;
  padding: 4px 10px;
  cursor: ${(props) => (props.$done ? "default" : "pointer")};
  border-radius: 0;
  white-space: nowrap;
  pointer-events: ${(props) => (props.$done ? "none" : "auto")};

  &:hover {
    background: ${(props) =>
      props.$done ? "transparent" : "var(--bs-primary)"};
    /* Tokyo-11 ink flip - primary is light, so the filled-hover state needs dark ink, not
       white (was #fff under the #302 palette). */
    color: ${(props) =>
      props.$done ? "var(--bs-success)" : "var(--theme-btn-ink)"};
  }
`;

const DefaultButton = styled.button<{ $done: boolean }>`
  background: transparent;
  border: 1px solid
    ${(props) => (props.$done ? "var(--bs-success)" : "var(--bs-info)")};
  color: ${(props) => (props.$done ? "var(--bs-success)" : "var(--bs-info)")};
  font-family: inherit;
  font-size: 13px;
  padding: 4px 10px;
  cursor: ${(props) => (props.$done ? "default" : "pointer")};
  border-radius: 0;
  white-space: nowrap;
  pointer-events: ${(props) => (props.$done ? "none" : "auto")};

  &:hover {
    background: ${(props) => (props.$done ? "transparent" : "var(--bs-info)")};
    /* Tokyo-11 ink flip - info is light too (was #062430 dark-navy-on-cyan under #302; the
       new $theme-btn-ink token is the same idea, generalised across every filled-light role). */
    color: ${(props) =>
      props.$done ? "var(--bs-success)" : "var(--theme-btn-ink)"};
  }
`;

const SkipRow = styled.div`
  margin-top: 8px;
  text-align: right;

  a {
    color: var(--theme-muted);
    font-size: 12px;
    text-decoration: underline;
    cursor: pointer;
  }
`;

const TrapNote = styled.div`
  font-size: 11px;
  color: var(--bs-warning);
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
  background: var(--theme-divider);
  border: 1px solid rgba(var(--bs-body-color-rgb), 0.15);
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
  color: var(--theme-muted);
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
