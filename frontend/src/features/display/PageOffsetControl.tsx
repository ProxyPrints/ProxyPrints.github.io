/**
 * The right rail's Page Setup "Page offset (mm)" control: independent Horizontal (X) / Vertical
 * (Y) numeric inputs that shift the whole card grid's position on the page, in mm. Extracted as
 * its own component (mirrors `CardSpacingControl.tsx`'s own precedent) for a plain unit-test
 * target without needing a full DisplayPage render.
 *
 * This is REGISTRATION COMPENSATION, not a margin: it exists for a printer whose feed lands
 * content off-centre on the physical sheet, so the whole grid needs nudging one direction to
 * land where it should. That's a materially different job from the margin profile above (which
 * shapes how much of the page the layout engine treats as printable at all) - so unlike
 * `CardSpacingControl`'s row/col values, this never feeds `computeLayout`'s fit math: it doesn't
 * change how many cards fit, doesn't touch granted bleed, and isn't clamped to whatever slack the
 * layout happens to have left over (clamping it to slack would silently turn a real correction
 * into a no-op the moment it needed to be more than a millimetre or two - see the caller's own
 * wiring for where the unclamped value is actually applied, after the fit is resolved). Positive
 * X moves right, positive Y moves down; either axis may go negative, and either may legitimately
 * push content past the page's own nominal edges - that's the printer's registration reality, not
 * a bug in this control.
 */
import React from "react";
import Form from "react-bootstrap/Form";

export interface PageOffsetControlProps {
  offsetXMM: number;
  offsetYMM: number;
  onChangeX: (value: number) => void;
  onChangeY: (value: number) => void;
}

export function PageOffsetControl({
  offsetXMM,
  offsetYMM,
  onChangeX,
  onChangeY,
}: PageOffsetControlProps) {
  return (
    <div className="mt-3" data-testid="display-page-offset-group">
      <div className="small mb-1">Page offset (mm)</div>
      <div className="d-flex gap-2 mb-1">
        <Form.Group className="flex-fill">
          <Form.Label className="small mb-1">Horizontal (X)</Form.Label>
          <Form.Control
            size="sm"
            type="number"
            step={0.1}
            value={offsetXMM}
            onChange={(event) => {
              const value = parseFloat(event.target.value);
              if (!Number.isNaN(value)) {
                onChangeX(value);
              }
            }}
            aria-label="Horizontal page offset (mm)"
            data-testid="display-page-offset-x"
          />
        </Form.Group>
        <Form.Group className="flex-fill">
          <Form.Label className="small mb-1">Vertical (Y)</Form.Label>
          <Form.Control
            size="sm"
            type="number"
            step={0.1}
            value={offsetYMM}
            onChange={(event) => {
              const value = parseFloat(event.target.value);
              if (!Number.isNaN(value)) {
                onChangeY(value);
              }
            }}
            aria-label="Vertical page offset (mm)"
            data-testid="display-page-offset-y"
          />
        </Form.Group>
      </div>
      <div className="text-muted small">
        Registration compensation for a printer whose feed lands content
        off-centre - shifts the whole sheet, never changes how many cards fit or
        how much bleed they get. Not limited to the page&apos;s own slack.
      </div>
    </div>
  );
}
