import React, { ReactElement } from "react";
import Card from "react-bootstrap/Card";
import Collapse from "react-bootstrap/Collapse";
import Container from "react-bootstrap/Container";
import Stack from "react-bootstrap/Stack";

interface AutofillCollapseProps {
  expanded: boolean;
  onClick: () => void;
  zIndex?: number;
  title: ReactElement | string;
  subtitle?: string;
  children: ReactElement;
  sticky?: boolean;
  pad?: number;
  /** Additive, optional (SPEC-display-left-rail.md §4's Sources accordion a11y requirement -
   * "summary row is a button, aria-expanded/aria-controls") - when supplied, pairs a real
   * `aria-controls` on the header with a matching `id` on the collapsible body. `undefined`
   * (every pre-existing caller) renders exactly as before, just gaining the always-safe
   * `aria-expanded` below. */
  id?: string;
  /** Additive, optional (CSS-fidelity source-map pass, SPEC-display-left-rail.md §2/§9 -
   * "AutofillCollapse header in rail: Superhero's stock `.card-header` `0.5rem 1rem` (8/16) ->
   * rail-scoped `padding:7px 10px`"). Component-scoped replacement for what used to be a
   * `RailRoot`-level `.card-header{padding:7px 10px}` descendant-selector override living two
   * files away from the `Card.Header` it targeted (DisplayPage.tsx's own RailRoot, clobbering
   * Bootstrap's global `card.scss` rule by selector specificity, not by scope) - see that
   * commit's own note in SPEC-display-left-rail.md's "Source map addendum" for why that pattern
   * is the recurrence signature this prop retires. `undefined` (every pre-existing caller, and
   * every non-rail caller of this shared component - CardDetailedViewBody/PDFGenerator/
   * JumpToVersion/CardResultSet/GridSelectorFilters) renders with Bootstrap's own stock padding,
   * byte-for-byte unchanged. */
  headerPadding?: string;
}

/**
 * bit of a shitty component name sorry
 * @param children Children to render in the body of this collapsible man
 * @param expanded Whether this collapsible man is expanded
 * @param onClick What to do when trying to expand this man
 * @param zIndex The base z-index of this man
 * @param title The title of this man
 * @param subtitle Optionally, the subtitle of this man
 * @param sticky Whether or not the man's collapse bar is sticky
 * @constructor
 */
export function AutofillCollapse({
  children,
  expanded,
  onClick,
  zIndex = 0,
  title,
  subtitle,
  sticky = false,
  pad = 0,
  id,
  headerPadding,
}: AutofillCollapseProps) {
  return (
    <>
      <Card style={{ position: "relative", zIndex }}>
        <Card.Header
          className={`border-light${sticky ? " sticky-top" : ""}`}
          onClick={onClick}
          aria-expanded={expanded}
          aria-controls={id != null ? `${id}-body` : undefined}
          style={{
            // CSS-fidelity source-map pass (SPEC-display-left-rail.md §0) - was "#4E5D6B" (a
            // hand-typed literal one hex digit off the real theme token in the blue channel,
            // 0x6B vs 0x6C - imperceptible but never actually sourced from the theme). Corrected
            // to the exact `$secondary`/`$card-bg` value (#4e5d6c) SPEC-display-left-rail.md §0
            // documents.
            backgroundColor: "#4e5d6c",
            zIndex: zIndex + 1,
            cursor: "pointer",
            ...(headerPadding != null ? { padding: headerPadding } : {}),
          }}
        >
          <Stack direction="horizontal" gap={2} className="d-flex px-0">
            {title}
            {subtitle && (
              <h6 className="text-primary prevent-select">{subtitle}</h6>
            )}
            <button className="ms-auto bg-transparent border-0">
              <h5
                className={`bi bi-chevron-left rotate-${
                  expanded ? "" : "neg"
                }90`}
                style={{ transition: "all 0.25s 0s", color: "white" }}
              />
            </button>
          </Stack>
        </Card.Header>
        <Card.Body className={`p-0 m-0`}>
          <Collapse in={expanded}>
            {/* https://react-bootstrap.netlify.app/docs/utilities/transitions/#collapse */}
            <div id={id != null ? `${id}-body` : undefined}>
              <Container className={`p-${pad} m-0`}>{children}</Container>
            </div>
          </Collapse>
        </Card.Body>
      </Card>
    </>
  );
}
