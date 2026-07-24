/**
 * The /display left rail's promoted D14 confidence element (SPEC-display-left-rail.md §3,
 * HARD CONSTRAINT - locked owner decision, #271 c.2026-07-21; owner-approved implementation
 * round 2026-07-23). Supersedes the old `DeckbuilderConfirmAffordance` mount that used to
 * co-render in `RailHeader` (DisplayPage.tsx) - that mount is REMOVED entirely (see
 * DisplayPage.tsx's `RailHeader` for the removal note); `DeckbuilderConfirmAffordance` itself is
 * untouched and still used elsewhere (CardSlot.tsx's editor grid, `SelectVersionResults.tsx`'s
 * suggested-printing confirm ribbon).
 *
 * The SET SYMBOL is the confidence anchor (Keyrune glyph via `SetIcon`), with a small corner
 * overlay carrying the actual signal:
 *   - human-confirmed (`canonicalCard != null`) -> a green check badge, "Confirmed" pill, no
 *     number (a resolved printing is a settled fact, not a probability).
 *   - not confirmed (only `suggestedCanonicalCard`) -> a numeric confidence score badge IF the
 *     backend has actually supplied one (see the D14 numeric-score honesty note below), else the
 *     qualitative "Suggested" pill the shipped placeholder already used.
 *
 * Editor-polish round (EP9, SPEC-editor-polish.md §D.1 `.compare`/§D.2 `.statepill.cmp`) - the
 * compare-reference TRIGGER moves off the set icon and onto the Confirmed/`% confident` pill
 * itself (owner ask); the pill LOOK is untouched (LOCKED, D14/#271/owner answer #2), only its
 * behaviour gains a hover/focus/tap toggle. The reveal itself no longer renders as a `Popover`
 * anchored to this component's own DOM position - it's lifted to the rail HEAD, beside the
 * 116px subject image (`RailHeader` in DisplayPage.tsx), since that's a different component in
 * the tree. `compareOpen`/`onCompareToggle`/`onCompareHover` are the lifted-state seam: omitted
 * (every caller before this round), this component behaves exactly as before - the pill is
 * plain, non-interactive text, zero behaviour change (shared-component "additive only" rule).
 * `buildScryfallReferenceImageUrl` itself is unchanged, reused verbatim - still zero backend
 * seam, still nothing fetched/stored beyond the one `<img src>` pointed at Scryfall's own CDN
 * (governing premise + #271).
 *
 * "✗ not this printing" casts a REAL vote (`APISubmitPrintingTag` with `isNoMatch: true`) - the
 * same printing-tag vote schema `DeckbuilderConfirmAffordance`'s own YES/NO already uses, just
 * the "no known printing matches this card's current image" half of it (see that component's own
 * `handleNo` comment for why a narrower "this ONE candidate is wrong" vote doesn't exist in the
 * schema - that constraint is about disputing one candidate among several in a picker; D14's ✗ is
 * about the card's OWN currently-attached printing, which `isNoMatch` models correctly). Owner
 * answer #2 (2026-07-23): stays visible - de-emphasised via CSS opacity, not hidden - on an
 * already-`confirmed` printing too, consistent with D1's "explicit human dissent opens a
 * human-vs-human contest" semantics; casts the exact same vote call in both states. Editor-polish
 * round (EP8, §D.2 `.notthis`) restyles this from a flat `btn-outline-danger` bar to the
 * pre-#413 `DeckbuilderConfirmAffordance` pill idiom (tinted, rounded `10px`) - see this file's
 * own `NotThisPrintingButton` styled component for the exact token source (git history: commit
 * before #413's rail-delegacy round removed the grey accordion look).
 *
 * D14 numeric-score honesty note (owner answer #1, 2026-07-23): the backend does not expose a
 * calibrated confidence score today - `suggestedCanonicalCard` is a machine-cast VOTE, not a %.
 * This component reads `cardDocument.suggestedCanonicalCardConfidence` (a new, currently-always-
 * `undefined` SEAM field - see that field's own doc comment in `schema_types.ts` for the exact
 * expected shape/name so a future backend PR can populate it without any frontend rework) and
 * falls back to the qualitative "Suggested" pill whenever it's absent - never a fabricated number.
 *
 * diverges from upstream: fork-only confidence element (#271); no upstream counterpart.
 */
import styled from "@emotion/styled";
import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { CardDocument, useAppDispatch } from "@/common/types";
import { SetIcon } from "@/components/SetIcon";
import { APISubmitPrintingTag } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

// EP8 (SPEC-editor-polish.md §D.2 `.notthis`, REV of the post-#413 look) - restores the
// pre-#413 `DeckbuilderConfirmAffordance` pill idiom: a tinted, rounded (radius 10px) danger
// pill, instead of the bland full-width `btn-outline-danger` bar the rail-delegacy round left
// behind. Owner answer #2's opacity-.6-on-confirmed de-emphasis is preserved via the
// `data-confirmed` attribute selector, same mechanism as before this round.
const NotThisPrintingButton = styled(Button)`
  margin-left: auto;
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
  border-radius: 10px;
  background: rgba(var(--bs-danger-rgb), 0.12);
  color: #f0b3b1;
  border: 1px solid rgba(var(--bs-danger-rgb), 0.55);

  &:hover:not(:disabled),
  &:focus:not(:disabled) {
    background: var(--bs-danger);
    /* Tokyo-11 ink flip: danger is a light red (6.46:1 with dark ink vs. 2.65:1 with white) -
       see styles.scss's own $color-contrast-dark note. */
    color: var(--theme-btn-ink);
    border-color: var(--bs-danger);
  }

  &[data-confirmed="true"] {
    opacity: 0.6;
  }
`;

// EP9 - the pill's compare-trigger affordance: `role=button tabIndex=0` only when a toggle
// handler is actually supplied (additive, behaviour-preserving otherwise). Pill LOOK (colour/
// border/radius) is untouched - LOCKED - this only adds cursor/interaction, never overrides the
// `.statepill.confirmed`/`.statepill.suggested` colour rules already on the plain `<span>` below.
const ComparePill = styled.span`
  cursor: zoom-in;
`;

// EP9 (§G a11y note - "the D14 pill compare-trigger is... a `tap-toggle` under (pointer:coarse)
// (no hover)") - a coarse pointer (touch-primary) has no meaningful hover state at all, so its
// tap must ITSELF toggle the reveal; a fine pointer (mouse) already gets show/hide for free from
// hover/focus, so wiring a click-toggle there TOO would immediately re-hide the reveal the
// instant a real mouse click follows the hover that already opened it (mouse interaction always
// hovers before it clicks) - this hook is what keeps the two mechanisms from fighting each
// other, matching the spec's own explicit "(no hover)" qualifier for the coarse-pointer path.
function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || window.matchMedia == null) {
      return;
    }
    const mediaQuery = window.matchMedia("(pointer: coarse)");
    setCoarse(mediaQuery.matches);
    const handleChange = (event: MediaQueryListEvent) =>
      setCoarse(event.matches);
    mediaQuery.addEventListener?.("change", handleChange);
    return () => mediaQuery.removeEventListener?.("change", handleChange);
  }, []);
  return coarse;
}

interface ConfidenceElementProps {
  cardDocument: CardDocument | undefined;
  backendURL: string;
  /** EP9 - lifted compare-reveal state (owned by `Rail` in DisplayPage.tsx, since the reveal
   * itself renders in a sibling component, beside the subject image). All three omitted
   * (default) keeps the pill a plain, non-interactive `<span>` - zero behaviour change for any
   * caller that doesn't opt in. */
  compareOpen?: boolean;
  onCompareToggle?: () => void;
  onCompareShow?: () => void;
  onCompareHide?: () => void;
}

export function ConfidenceElement({
  cardDocument,
  backendURL,
  compareOpen,
  onCompareToggle,
  onCompareShow,
  onCompareHide,
}: ConfidenceElementProps) {
  const dispatch = useAppDispatch();
  const [submitting, setSubmitting] = useState(false);
  const coarsePointer = useCoarsePointer();

  if (cardDocument == null) {
    return null;
  }

  const resolvedPrinting = cardDocument.canonicalCard;
  const suggestedPrinting = cardDocument.suggestedCanonicalCard;
  const printing = resolvedPrinting ?? suggestedPrinting;
  if (printing == null) {
    return null;
  }

  const status: "confirmed" | "suggested" =
    resolvedPrinting != null ? "confirmed" : "suggested";
  // Only ever read for a `suggested` card - see this file's own "numeric-score honesty note."
  const confidenceScore =
    status === "suggested"
      ? cardDocument.suggestedCanonicalCardConfidence ?? null
      : null;

  const idLabel = `${printing.expansionCode.toUpperCase()} ${
    printing.collectorNumber
  }`;

  const castNotThisPrinting = () => {
    setSubmitting(true);
    APISubmitPrintingTag(
      backendURL,
      cardDocument.identifier,
      getOrCreateAnonymousId(),
      undefined,
      true,
      "display-confidence"
    )
      .catch((error) => {
        if (isRateLimited(error)) {
          return;
        }
        dispatch(
          setNotification([
            Math.random().toString(),
            errorToNotification(error, {
              name: "Vote failed",
              message:
                "Something went wrong casting this vote - please try again.",
            }),
          ])
        );
      })
      .finally(() => setSubmitting(false));
  };

  // EP9 - the pill is only interactive (compare-trigger) when the caller opted in; every prop
  // omitted keeps this a plain `<span>`, exactly as before this round.
  const compareEnabled = onCompareToggle != null;
  const compareProps = compareEnabled
    ? {
        role: "button" as const,
        tabIndex: 0,
        "aria-pressed": compareOpen ?? false,
        "aria-label": `Show Scryfall reference image for ${idLabel}`,
        // Coarse pointer (touch): tap IS the toggle, no hover wired at all (see
        // `useCoarsePointer`'s own comment). Fine pointer (mouse): hover/focus show it,
        // mouseleave/blur hide it - no click handler, so a click following the hover that
        // already opened it can never immediately re-close it.
        onClick: coarsePointer ? onCompareToggle : undefined,
        onMouseEnter: coarsePointer ? undefined : onCompareShow,
        onMouseLeave: coarsePointer ? undefined : onCompareHide,
        onFocus: coarsePointer ? undefined : onCompareShow,
        onBlur: coarsePointer ? undefined : onCompareHide,
        onKeyDown: (event: React.KeyboardEvent) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onCompareToggle?.();
          }
        },
        "data-testid": "display-confidence-compare-trigger",
      }
    : {};

  return (
    <div className="d14" data-testid="display-confidence-element">
      <span
        className="seticon"
        aria-hidden="true"
        data-testid="display-confidence-set-symbol"
      >
        <SetIcon expansionCode={printing.expansionCode} />
        {status === "confirmed" ? (
          <span className="check" aria-hidden="true">
            ✓
          </span>
        ) : (
          confidenceScore != null && (
            <span className="score" aria-hidden="true">
              {confidenceScore}%
            </span>
          )
        )}
      </span>
      <span className="idtext">
        {printing.expansionCode.toUpperCase()} · {printing.collectorNumber}
      </span>
      {status === "confirmed" ? (
        <ComparePill
          className="statepill confirmed cmp"
          aria-label="confirmed printing"
          {...compareProps}
        >
          Confirmed
        </ComparePill>
      ) : (
        <ComparePill
          className="statepill suggested cmp"
          aria-label={
            confidenceScore != null
              ? `machine-suggested, ${confidenceScore} percent confidence`
              : "machine-suggested printing"
          }
          {...compareProps}
        >
          {confidenceScore != null
            ? `${confidenceScore}% confident`
            : "Suggested"}
        </ComparePill>
      )}
      <NotThisPrintingButton
        size="sm"
        className="notthis"
        disabled={submitting}
        onClick={castNotThisPrinting}
        aria-label={`Vote: this is not printing ${idLabel}`}
        data-testid="display-confidence-not-this-printing"
        data-confirmed={status === "confirmed"}
      >
        ✗ not this printing
      </NotThisPrintingButton>
    </div>
  );
}
