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
 * Hovering/focusing the set icon opens a `Popover` showing the printing's Scryfall reference
 * image, straight from Scryfall's own CDN (`buildScryfallReferenceImageUrl` -
 * `scryfallReference.ts`) - display-only, nothing fetched/stored by this catalog (governing
 * premise + #271).
 *
 * "✗ not this printing" casts a REAL vote (`APISubmitPrintingTag` with `isNoMatch: true`) - the
 * same printing-tag vote schema `DeckbuilderConfirmAffordance`'s own YES/NO already uses, just
 * the "no known printing matches this card's current image" half of it (see that component's own
 * `handleNo` comment for why a narrower "this ONE candidate is wrong" vote doesn't exist in the
 * schema - that constraint is about disputing one candidate among several in a picker; D14's ✗ is
 * about the card's OWN currently-attached printing, which `isNoMatch` models correctly). Owner
 * answer #2 (2026-07-23): stays visible - de-emphasised via CSS opacity, not hidden - on an
 * already-`confirmed` printing too, consistent with D1's "explicit human dissent opens a
 * human-vs-human contest" semantics; casts the exact same vote call in both states.
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
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import OverlayTrigger from "react-bootstrap/OverlayTrigger";
import Popover from "react-bootstrap/Popover";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { CardDocument, useAppDispatch } from "@/common/types";
import { SetIcon } from "@/components/SetIcon";
import { buildScryfallReferenceImageUrl } from "@/features/display/scryfallReference";
import { APISubmitPrintingTag } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface ConfidenceElementProps {
  cardDocument: CardDocument | undefined;
  backendURL: string;
}

export function ConfidenceElement({
  cardDocument,
  backendURL,
}: ConfidenceElementProps) {
  const dispatch = useAppDispatch();
  const [submitting, setSubmitting] = useState(false);

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
  const imageUrl = buildScryfallReferenceImageUrl(
    printing.expansionCode,
    printing.collectorNumber
  );

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

  const popover = (
    <Popover
      id={`display-confidence-popover-${cardDocument.identifier}`}
      data-testid="display-confidence-popover"
    >
      <Popover.Body>
        {imageUrl != null ? (
          <img
            src={imageUrl}
            alt={`Scryfall reference image for ${idLabel}`}
            style={{ width: "100%", display: "block" }}
          />
        ) : (
          <span className="text-muted small">
            No reference image available.
          </span>
        )}
        <div className="text-muted small mt-1">
          Scryfall CDN · display-only, nothing stored
        </div>
      </Popover.Body>
    </Popover>
  );

  return (
    <div className="d14" data-testid="display-confidence-element">
      <OverlayTrigger
        trigger={["hover", "focus"]}
        placement="right"
        overlay={popover}
      >
        <span
          className="seticon"
          role="button"
          tabIndex={0}
          aria-label={`Show reference image for ${idLabel}`}
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
      </OverlayTrigger>
      <span className="idtext">
        {printing.expansionCode.toUpperCase()} · {printing.collectorNumber}
      </span>
      {status === "confirmed" ? (
        <span className="statepill confirmed" aria-label="confirmed printing">
          Confirmed
        </span>
      ) : (
        <span
          className="statepill suggested"
          aria-label={
            confidenceScore != null
              ? `machine-suggested, ${confidenceScore} percent confidence`
              : "machine-suggested printing"
          }
        >
          {confidenceScore != null
            ? `${confidenceScore}% confident`
            : "Suggested"}
        </span>
      )}
      <Button
        size="sm"
        variant="outline-danger"
        className="notthis"
        disabled={submitting}
        onClick={castNotThisPrinting}
        aria-label={`Vote: this is not printing ${idLabel}`}
        data-testid="display-confidence-not-this-printing"
        data-confirmed={status === "confirmed"}
      >
        ✗ not this printing
      </Button>
    </div>
  );
}
