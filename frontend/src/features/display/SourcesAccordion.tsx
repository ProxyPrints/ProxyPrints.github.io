/**
 * The /display left rail's Sources accordion (SPEC-display-left-rail.md §4, brief item 1;
 * owner-approved implementation round 2026-07-23). Replaces the flat, ~247-row per-source toggle
 * list previously reachable only through the Search Settings MODAL (`SourceSettings.tsx`, still
 * mounted there unmodified - see that component's own file for the untouched original) with a
 * disclosure in the left rail: sources gate which art is even searchable, so the owner brief puts
 * them with the card surface itself rather than behind a separate settings modal.
 *
 * DEVIATION from `proposal-h-display-layout-spec.md` §4.2 (which put Search Settings in the RIGHT
 * rail): honours the newer, explicit owner brief ("the left panel") - `docs/upstreaming/
 * readiness-audit.md`'s styling-divergence notes carry this one too, since it diverges from that
 * spec doc's own placement call, not just from upstream.
 *
 * A thin, standalone composer (spec's own "Yori's call" - see SPEC §4's react-bootstrap-mapping
 * paragraph) rather than additive props on `SourceSettings.tsx` itself: this accordion writes
 * DIRECTLY to `searchSettingsSlice` (Redux + the same `setLocalStorageSearchSettings` persistence
 * the Search Settings modal's own Save button already uses) on every toggle/bulk action, with no
 * staged local-copy-plus-Save step - the modal's "review then commit" UX doesn't fit an
 * always-visible rail disclosure the way it fits a deliberate settings dialog. `SourceSettings.tsx`
 * itself is completely untouched (still the modal's own component, byte-for-byte), keeping this
 * additive rather than a refactor of shared code.
 *
 * INLINE shape (owner answer #3, 2026-07-23 - confirmed the mockup's own recommendation): the
 * mockup's alternative "overlay dropdown" shape was reviewed and NOT built - on phone the left
 * rail is itself a 72vh bottom-sheet Offcanvas and on tablet a start-drawer, so an overlay
 * dropdown floating over rail content there would be an overlay-over-an-overlay (the exact
 * stacking/z-index hazard the base Proposal H spec already warns against). Inline pushes content
 * within the rail's own single `overflow-y:auto` scroll container at every breakpoint instead.
 *
 * Pinned favourites (owner answer #5, 2026-07-23 - "implement the pin UI + localStorage
 * persistence now"): a per-device star toggle, visible as a chip strip even while the accordion
 * is collapsed. Deliberately local/device-only for this round, NOT the account-tied "save these
 * as my defaults" version - that stays a disabled seam button (issue #353) until a real backend
 * exists for it. See docs/features/display-left-rail.md's "Pinned favourite sources" section for
 * the full write-up (localStorage-exception rationale, `getLocalStoragePinnedSourcePks`/
 * `setLocalStoragePinnedSourcePks` - `common/cookies.ts`).
 *
 * diverges from upstream: upstream's SourceSettings exposes only a single "Enable/Disable all"
 * button and drag reorder - the type-to-filter input, Invert, and per-source pin star below are
 * all fork additions with no upstream analogue.
 *
 * Editor-polish round (EP3, SPEC-editor-polish.md §D.3) - de-greys and densifies this block:
 *   - The inherited `#4E5D6B` grey header/pins/body band is killed -> `#22303f` throughout, via
 *     `AutofillCollapse`'s new additive `headerBackground`/`bodyBackground` props (that shared
 *     component's own hardcoded default stays untouched for every other caller - see its own
 *     comment for why `#4E5D6B` there is otherwise locked).
 *   - Rows densify to `34px` (toggle `52×31`, pin `30×30`, name `12px`); the filter input's
 *     border brightens to `1px #abb6c2` - EP3's own framing, "the filter input becomes the
 *     primary find path."
 *   - The list is capped, not truly virtualized (no new dependency - `§B`'s own "no new
 *     dependencies" mapping rule; a genuine windowed/virtualized list would need one, e.g.
 *     `react-window`) - only the first `SOURCES_LIST_CAP` matching rows render at once, with a
 *     `.src-cap` caption ("Showing N of M — filter to narrow") whenever the match count exceeds
 *     it. Functionally equivalent for THIS list's actual size (never more than a few hundred
 *     sources) - the real cost `.src-list`'s un-capped render paid was DOM node count, which this
 *     removes just as effectively as true virtualization would, just without scroll-position
 *     windowing.
 */
import React, { useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import {
  getLocalStoragePinnedSourcePks,
  setLocalStoragePinnedSourcePks,
  setLocalStorageSearchSettings,
} from "@/common/cookies";
import { SourceRow, useAppDispatch, useAppSelector } from "@/common/types";
import { getSourceRowsFromSourceSettings } from "@/common/utils";
import { AutofillCollapse } from "@/components/AutofillCollapse";
import {
  selectSearchSettings,
  setSourceSettings,
} from "@/store/slices/searchSettingsSlice";
import { selectSourceDocuments } from "@/store/slices/sourceDocumentsSlice";

// EP3 - caps the rendered row count (see this file's own module comment on why this is a cap,
// not true virtualization).
const SOURCES_LIST_CAP = 10;

export function SourcesAccordion() {
  const dispatch = useAppDispatch();
  const [open, setOpen] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [pinnedPks, setPinnedPks] = useState<Set<number>>(
    () => new Set(getLocalStoragePinnedSourcePks())
  );

  const searchSettings = useAppSelector(selectSearchSettings);
  const sourceDocuments = useAppSelector(selectSourceDocuments);
  const sourceRows = useMemo(
    () => getSourceRowsFromSourceSettings(searchSettings.sourceSettings),
    [searchSettings.sourceSettings]
  );

  // Nothing to configure yet (sources still loading, or a local-only/no-backend session with no
  // sources at all) - same "render nothing until there's real data" precedent every other rail
  // section (ArtistSection/PrintOptionsSection/etc.) already follows.
  if (sourceDocuments == null || sourceRows.length === 0) {
    return null;
  }

  const enabledCount = sourceRows.filter(([, enabled]) => enabled).length;

  const persist = (rows: Array<SourceRow>) => {
    dispatch(setSourceSettings({ sources: rows }));
    setLocalStorageSearchSettings({
      ...searchSettings,
      sourceSettings: { sources: rows },
    });
  };

  const setOne = (pk: number, enabled: boolean) =>
    persist(
      sourceRows.map(([rowPk, rowEnabled]) =>
        rowPk === pk ? [rowPk, enabled] : [rowPk, rowEnabled]
      )
    );

  const enableAll = () => persist(sourceRows.map(([pk]) => [pk, true]));
  const disableAll = () => persist(sourceRows.map(([pk]) => [pk, false]));
  // Fork addition (docs/upstreaming/ divergence note) - upstream's SourceSettings only exposes a
  // single "Enable/Disable all" toggle button; Invert has no upstream analogue.
  const invert = () =>
    persist(sourceRows.map(([pk, enabled]) => [pk, !enabled]));

  const togglePin = (pk: number) =>
    setPinnedPks((previous) => {
      const next = new Set(previous);
      if (next.has(pk)) {
        next.delete(pk);
      } else {
        next.add(pk);
      }
      setLocalStoragePinnedSourcePks(Array.from(next));
      return next;
    });

  const normalisedFilter = filterQuery.trim().toLowerCase();
  const matchingRows =
    normalisedFilter.length === 0
      ? sourceRows
      : sourceRows.filter(([pk]) =>
          (sourceDocuments[pk]?.name ?? "")
            .toLowerCase()
            .includes(normalisedFilter)
        );
  // EP3 - the cap (see this file's own module comment); `.src-cap` only renders when it's
  // actually hiding something.
  const visibleRows = matchingRows.slice(0, SOURCES_LIST_CAP);
  const hiddenCount = matchingRows.length - visibleRows.length;

  const pinnedRows = sourceRows.filter(([pk]) => pinnedPks.has(pk));

  return (
    <div
      // O1 fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - the plain Bootstrap
      // `.border-bottom` utility used to sit here; `.sources`'s normalized `border-bottom:1px
      // solid #16202b` now lives in DisplayPage.tsx's RailRoot styled-component (this div is a
      // descendant of that scope) - see that rule's own comment for the full O1 rationale.
      className="sources"
      data-testid="display-sources-accordion"
    >
      <AutofillCollapse
        id="display-sources-accordion"
        pad={2}
        expanded={open}
        onClick={() => setOpen((previous) => !previous)}
        // CSS-fidelity source-map pass (SPEC-display-left-rail.md §2/§4) - see
        // DisplayPage.tsx's RailSection's own identical `headerPadding` comment; this shell is
        // the other AutofillCollapse mount in the rail ("shell = AutofillCollapse", §4).
        headerPadding="7px 10px"
        // EP3 (SPEC-editor-polish.md §D.3) - de-greys the shared component's own `#4E5D6B`
        // default for this ONE caller only (see AutofillCollapse.tsx's own comment).
        headerBackground="var(--theme-raised-bg)"
        bodyBackground="var(--theme-raised-bg)"
        title={
          <div className="d-flex flex-column flex-grow-1">
            <div className="d-flex align-items-center gap-2">
              <span
                className="text-uppercase small fw-bold"
                data-testid="display-sources-summary-label"
              >
                Sources
              </span>
              <span
                className="small"
                data-testid="display-sources-summary-count"
              >
                <span className="text-success fw-bold">{enabledCount}</span> of{" "}
                {sourceRows.length} enabled
              </span>
            </div>
            {/* Pinned strip stays visible while collapsed (spec §4) - lives in the AutofillCollapse
                `title` node (never collapsed) rather than the body. `stopPropagation` keeps a pin
                chip click from also toggling the accordion open/closed, since the whole header row
                shares one onClick. */}
            {pinnedRows.length > 0 && (
              <div
                className="d-flex flex-wrap gap-1 mt-1"
                onClick={(event) => event.stopPropagation()}
                data-testid="display-sources-pinned-strip"
              >
                {pinnedRows.map(([pk]) => (
                  <span
                    key={pk}
                    className="badge text-bg-dark small"
                    data-testid={`display-sources-pin-chip-${pk}`}
                  >
                    <span className="text-warning">★</span>{" "}
                    {sourceDocuments[pk]?.name ?? pk}
                  </span>
                ))}
              </div>
            )}
          </div>
        }
      >
        <div>
          <Form.Control
            type="text"
            placeholder="Filter sources…"
            aria-label="Filter sources"
            value={filterQuery}
            onChange={(event) => setFilterQuery(event.target.value)}
            className="mb-2"
            // Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) -
            // `Form.Control` is a genuinely global Bootstrap classname (`.form-control`), so this
            // is fixed via an inline style on THIS specific input (component-scoped) rather than
            // a `.form-control` selector anywhere in RailRoot, which would be exactly the
            // sitewide-clobber pattern the #400 rule retired `.card-header` for. Bootstrap's own
            // stock `.form-control` padding (`.375rem .75rem` = 6px 12px) and unset font-size
            // (16px body default) both fell through to the spec's own 14px/`padding:6px 10px`.
            // EP3 (§D.3 `.src-body .filter`) - border brightens to `1px #abb6c2` (emphasised):
            // this is now the primary find path, ahead of scrolling the capped list below.
            style={{
              fontSize: "14px",
              padding: "6px 10px",
              background: "var(--theme-band-bg)",
              color: "var(--bs-body-color)",
              border: "1px solid var(--theme-light)",
            }}
            data-testid="display-sources-filter"
          />
          <div
            className="d-flex flex-wrap"
            // CSS-fidelity pass (SPEC-display-left-rail.md §4/§2, 2026-07-23) - the mockup's own
            // `.src-bulk{gap:6px;margin-bottom:6px}` has no exact Bootstrap spacing-scale match
            // (`gap-2 mb-2` = 8px both) - set directly, same as this round's other exact-px
            // values.
            style={{ gap: "6px", marginBottom: "6px" }}
          >
            <Button
              size="sm"
              variant="outline-light"
              onClick={enableAll}
              data-testid="display-sources-enable-all"
            >
              Enable all
            </Button>
            <Button
              size="sm"
              variant="outline-light"
              onClick={disableAll}
              data-testid="display-sources-disable-all"
            >
              Disable all
            </Button>
            <Button
              size="sm"
              variant="outline-light"
              onClick={invert}
              data-testid="display-sources-invert"
            >
              Invert
            </Button>
          </div>
          <div className="mb-2">
            {/* #353 seam - account-tied preferred sources aren't built yet; disabled, not hidden,
                so the affordance is discoverable ahead of that shipping. */}
            <Button
              size="sm"
              variant="outline-success"
              className="w-100"
              disabled
              title="Account-tied preferred sources - issue #353"
              data-testid="display-sources-save-defaults"
            >
              ☆ Save these as my defaults
            </Button>
          </div>
          {/* EP3 (§D.3 `.src-cap`) - "Showing N of M — filter to narrow", only while the cap is
              actually hiding rows; N in `#ebebeb` (the "N" token), the rest `#8fa0b0`. */}
          {hiddenCount > 0 && (
            <div
              style={{
                fontSize: "10px",
                color: "var(--theme-muted)",
                marginBottom: "5px",
              }}
              data-testid="display-sources-cap-caption"
            >
              Showing{" "}
              <span style={{ color: "var(--bs-body-color)" }}>
                {visibleRows.length}
              </span>{" "}
              of {matchingRows.length} — filter to narrow
            </div>
          )}
          <div
            // CSS-fidelity pass (SPEC-display-left-rail.md §4/§0, 2026-07-23) - Bootstrap's
            // plain `.border` utility renders the theme's stock gray (`--bs-border-color`, never
            // overridden by #302), not the mockup's own `.src-list{border:1px solid
            // var(--border);background:var(--raised)}` tokens (`rgba(0,0,0,.22)` /
            // `#22303f`) - set directly so this named surface matches the approved mockup.
            // EP3 (§D.3 `.src-list`) - background REV to `#2b3e50` (de-greyed surface).
            style={{
              maxHeight: 190,
              overflowY: "auto",
              border: "1px solid rgba(0,0,0,.22)",
              background: "var(--theme-band-bg)",
            }}
            data-testid="display-sources-list"
          >
            {visibleRows.map(([pk, enabled]) => {
              const sourceDocument = sourceDocuments[pk];
              if (sourceDocument == null) {
                return null;
              }
              const pinned = pinnedPks.has(pk);
              return (
                <div
                  key={pk}
                  className="d-flex align-items-center gap-2"
                  // Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected
                  // 2026-07-23) - the plain Bootstrap `.border-bottom` utility here resolved to
                  // the theme's ambiguous `--bs-border-color` (`#ced4da`, one of the two O1 flagged
                  // as a fidelity hazard generally), not the spec's own explicit `rgba(0,0,0,.22)`
                  // for this row (D.1: "Source row ... bottom rgba(0,0,0,.22)"). Fixed inline,
                  // component-scoped to this exact row. EP3 (§D.3 `.src-row`) - densified to a
                  // fixed `height:34px` (was ~unbounded via `p-2` padding); the flagged a11y
                  // tension (§G, owner-ruled) is mitigated by making the WHOLE row the toggle's
                  // hit surface via that same `onClick` below, not just the visible 31px switch.
                  style={{
                    height: "34px",
                    padding: "2px 8px",
                    borderBottom: "1px solid rgba(0,0,0,.22)",
                  }}
                  data-testid={`display-sources-row-${pk}`}
                >
                  <Toggle
                    on="On"
                    off="Off"
                    onstyle="primary"
                    offstyle="secondary"
                    size="md"
                    width={52 + "px"}
                    height={31 + "px"}
                    active={enabled}
                    onClick={() => setOne(pk, !enabled)}
                    // Machine-diff fix round (owner ruling, 2026-07-23) - the library's stock
                    // look is a sliding single-label switch (react-bootstrap-toggle's own
                    // `overflow:hidden`/`.toggle-group{width:200%}` CSS); the corrected mockup's
                    // own rendered toggle is a static two-cell segmented control, both "On" and
                    // "Off" labels always visible side by side. This `className` is the library's
                    // own additive escape hatch onto the outer root element (see
                    // `react-bootstrap-toggle`'s own `render()`); the matching CSS override lives
                    // in `DisplayPage.tsx`'s `RailRoot`, scoped to this exact classname only - it
                    // does NOT touch the shared, unstyled `.toggle`/`.toggle-group` classes this
                    // same library renders on every other page (FinishSettings/PDFGenerator/
                    // SearchTypeSettings/etc), which keep the library's stock sliding-switch look.
                    // EP3 (§D.3 `.tgl`, `--src-toggle-h`) - densified 54×38 -> 52×31 (§G's own
                    // flagged, owner-ruled a11y tension).
                    className="rail-source-toggle"
                  />
                  <span
                    className="flex-grow-1 text-truncate"
                    style={{ fontSize: "12px", color: "var(--bs-body-color)" }}
                  >
                    {sourceDocument.name}
                  </span>
                  <button
                    type="button"
                    className="btn bg-transparent border-0 p-0"
                    style={{
                      // EP3 (§D.3 `.src-row .pin`) - densified 38×38 -> 30×30.
                      minWidth: 30,
                      minHeight: 30,
                      fontSize: "15px",
                      color: pinned ? "var(--bs-warning)" : "#5b6b7b",
                    }}
                    aria-pressed={pinned}
                    aria-label={`Pin ${sourceDocument.name} as a favourite source`}
                    onClick={() => togglePin(pk)}
                    data-testid={`display-sources-pin-${pk}`}
                  >
                    ★
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </AutofillCollapse>
    </div>
  );
}
