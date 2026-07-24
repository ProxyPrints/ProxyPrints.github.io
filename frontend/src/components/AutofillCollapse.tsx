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
  /** Additive, optional (SPEC-editor-polish.md §D.3, EP3 - "the grey #4E5D6B header/pins/body
   * band is killed -> dark #22303f throughout"). Overrides the header's own hardcoded `#4E5D6B`
   * ONLY for the caller that supplies this - see the header's own comment for why that value is
   * otherwise deliberately locked (owner ruling, 2026-07-23) and must not be edited in place.
   * `undefined` (every caller except `SourcesAccordion.tsx`, EP3's own revision target) keeps
   * the shared `#4E5D6B` default, byte-for-byte unchanged. */
  headerBackground?: string;
  /** Additive, optional (SPEC-editor-polish.md §D.3, same EP3 de-grey) - the body's own
   * background; `undefined` (every non-Sources caller) keeps Bootstrap Card's own stock
   * default, unchanged. */
  bodyBackground?: string;
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
  headerBackground,
  bodyBackground,
}: AutofillCollapseProps) {
  return (
    <>
      <Card style={{ position: "relative", zIndex }}>
        <Card.Header
          // Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - the
          // `border-light` Bootstrap utility used to sit here, tinting this header's own
          // bottom border `$light` (`#abb6c2`, a visibly pale line on the dark rail). No spec
          // anywhere (rail or otherwise) calls for a light-coloured header border - it was a
          // stray utility class, not a deliberate design token - so it's removed at the shared
          // component itself rather than overridden per call site.
          className={sticky ? "sticky-top" : undefined}
          onClick={onClick}
          aria-expanded={expanded}
          aria-controls={id != null ? `${id}-body` : undefined}
          style={{
            // Machine-diff fix round (owner ruling, 2026-07-23): REVERTS the #400-era
            // "correction" below - #4E5D6B is deliberate here, not a typo. Owner confirmed the
            // corrected mockup (the actual binding reference, not an approximation of it) is
            // `#4E5D6B` for THIS card-header token specifically, distinct from the `#4e5d6c`
            // `$secondary`/panel token used elsewhere in the rail (D14 seticon, Card body, etc) -
            // the two tokens are one hex digit apart by design, not by accident. Do not "fix"
            // this back to `#4e5d6c` again; see SPEC-display-left-rail.md §D.0 for the explicit
            // note distinguishing them.
            backgroundColor: headerBackground ?? "var(--theme-card-header-bg)",
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
        <Card.Body
          className={`p-0 m-0`}
          style={
            bodyBackground != null
              ? { backgroundColor: bodyBackground }
              : undefined
          }
        >
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
