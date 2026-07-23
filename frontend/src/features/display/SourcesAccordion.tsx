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
 */
import React, { useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import { ToggleButtonHeight } from "@/common/constants";
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
  const visibleRows =
    normalisedFilter.length === 0
      ? sourceRows
      : sourceRows.filter(([pk]) =>
          (sourceDocuments[pk]?.name ?? "")
            .toLowerCase()
            .includes(normalisedFilter)
        );

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
          <div
            // CSS-fidelity pass (SPEC-display-left-rail.md §4/§0, 2026-07-23) - Bootstrap's
            // plain `.border` utility renders the theme's stock gray (`--bs-border-color`, never
            // overridden by #302), not the mockup's own `.src-list{border:1px solid
            // var(--border);background:var(--raised)}` tokens (`rgba(0,0,0,.22)` /
            // `#22303f`) - set directly so this named surface matches the approved mockup.
            style={{
              maxHeight: 190,
              overflowY: "auto",
              border: "1px solid rgba(0,0,0,.22)",
              background: "#22303f",
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
                  className="d-flex align-items-center gap-2 p-2 border-bottom"
                  data-testid={`display-sources-row-${pk}`}
                >
                  <Toggle
                    on="On"
                    off="Off"
                    onstyle="primary"
                    offstyle="secondary"
                    size="md"
                    width={54 + "px"}
                    height={ToggleButtonHeight + "px"}
                    active={enabled}
                    onClick={() => setOne(pk, !enabled)}
                  />
                  <span className="flex-grow-1 small text-truncate">
                    {sourceDocument.name}
                  </span>
                  <button
                    type="button"
                    className="btn bg-transparent border-0 p-0"
                    style={{
                      minWidth: ToggleButtonHeight,
                      minHeight: ToggleButtonHeight,
                      color: pinned ? "#ffc107" : "#5b6b7b",
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
