/**
 * A modal which allows users to control how the backend searches the database in various ways:
 *   a) Select precise or fuzzy (forgiving) search type
 *   b) Configure the allowable range for DPI and maximum file size
 *   c) Re-order the Sources to search and choose which Sources are active.
 * The classic editor's right-hand panel shows the default full-width `"button"` trigger; the
 * unified display page's search box mounts the compact `"icon"` variant instead (see
 * `SearchSettingsProps` below) - either way opens the same Modal.
 */

import React, { useCallback, useState } from "react";
import Badge from "react-bootstrap/Badge";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { setLocalStorageSearchSettings } from "@/common/cookies";
import {
  FilterSettings,
  SearchTypeSettings,
  SourceSettings,
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import { Icon, RightPaddedIcon } from "@/components/icon";
import { useCountSearchSettingsVaryingFromDefault } from "@/features/searchSettings/comparison";
import { FilterSettings as FilterSettingsElement } from "@/features/searchSettings/FilterSettings";
import { SearchTypeSettings as SearchTypeSettingsElement } from "@/features/searchSettings/SearchTypeSettings";
import { SourceSettings as SourceSettingsElement } from "@/features/searchSettings/SourceSettings";
import { selectRemoteBackendConfigured } from "@/store/slices/backendSlice";
import {
  selectSearchSettings,
  setFilterSettings,
  setSearchTypeSettings,
  setSourceSettings,
} from "@/store/slices/searchSettingsSlice";

export interface SearchSettingsProps {
  /**
   * Right-rail density pass - the display page attaches this trigger directly to its search
   * box (a settings cog on the control that changes searching, not a full-width button buried
   * in the rail) rather than mounting the default block-level `"button"` variant. The Modal
   * below - the actual overlay this whole component exists to open - is byte-for-byte identical
   * either way; only the trigger markup differs, so ProjectEditor's own unmodified `<SearchSettings />`
   * call (the default) is untouched by this addition.
   */
  variant?: "button" | "icon";
  /** Merged onto the icon variant's trigger button - lets a caller visually attach it to an
   * adjacent control (see DisplayPage.tsx's `SearchBoxWithCog`). No effect on `"button"`. */
  className?: string;
}

export function SearchSettings({
  variant = "button",
  className,
}: SearchSettingsProps = {}) {
  const dispatch = useAppDispatch();
  const [show, setShow] = useState<boolean>(false);
  const remoteBackendConfigured = useAppSelector(selectRemoteBackendConfigured);

  // global state managed in redux
  const globalSearchSettings = useAppSelector(selectSearchSettings);

  // component-level copies of redux state
  const [localSearchTypeSettings, setLocalSearchTypeSettings] =
    useState<SearchTypeSettings>(globalSearchSettings.searchTypeSettings);
  const [localSourceSettings, setLocalSourceSettings] =
    useState<SourceSettings>(globalSearchSettings.sourceSettings);
  const [localFilterSettings, setLocalFilterSettings] =
    useState<FilterSettings>(globalSearchSettings.filterSettings);

  const countSearchSettingsVaryingFromDefault =
    useCountSearchSettingsVaryingFromDefault();

  // modal management functions
  const handleClose = () => setShow(false);

  const handleShow = useCallback(() => {
    // set up the component-level state with the current redux state
    setLocalSearchTypeSettings(globalSearchSettings.searchTypeSettings);
    setLocalFilterSettings(globalSearchSettings.filterSettings);
    setLocalSourceSettings(globalSearchSettings.sourceSettings);

    setShow(true);
  }, [globalSearchSettings]);
  const handleSave = () => {
    // copy component-level state into redux state and into local storage
    setLocalStorageSearchSettings({
      searchTypeSettings: localSearchTypeSettings,
      sourceSettings: localSourceSettings,
      filterSettings: localFilterSettings,
    });
    dispatch(setSearchTypeSettings(localSearchTypeSettings));
    dispatch(setSourceSettings(localSourceSettings));
    dispatch(setFilterSettings(localFilterSettings));

    handleClose();
  };

  const trigger =
    variant === "icon" ? (
      <Button
        variant="outline-light"
        size="sm"
        onClick={handleShow}
        aria-label="Search Settings"
        title="Search Settings"
        className={["position-relative", className].filter(Boolean).join(" ")}
        data-testid="display-search-settings-cog"
      >
        <Icon bootstrapIconName="gear" />
        {countSearchSettingsVaryingFromDefault !== 0 && (
          <Badge
            bg="success"
            pill
            className="position-absolute top-0 start-100 translate-middle"
          >
            {countSearchSettingsVaryingFromDefault}
          </Badge>
        )}
      </Button>
    ) : (
      <div className="d-grid gap-0">
        <Button variant="primary" onClick={handleShow}>
          <RightPaddedIcon bootstrapIconName="gear" />
          Search Settings
          {countSearchSettingsVaryingFromDefault !== 0 && (
            <>
              {" "}
              <Badge bg="success" pill>
                {countSearchSettingsVaryingFromDefault}
              </Badge>
            </>
          )}
        </Button>
      </div>
    );

  return (
    <>
      {trigger}

      <Modal
        scrollable
        show={show}
        onHide={handleSave}
        data-testid="search-settings"
      >
        <Modal.Header closeButton>
          <Modal.Title>Search Settings</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <SearchTypeSettingsElement
            searchTypeSettings={localSearchTypeSettings}
            setSearchTypeSettings={setLocalSearchTypeSettings}
          />
          <hr />
          <FilterSettingsElement
            filterSettings={localFilterSettings}
            setFilterSettings={setLocalFilterSettings}
          />
          {remoteBackendConfigured && (
            <>
              <hr />
              <SourceSettingsElement
                sourceSettings={localSourceSettings}
                setSourceSettings={setLocalSourceSettings}
              />
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={handleClose}>
            Close Without Saving
          </Button>
          <Button variant="primary" onClick={handleSave}>
            Save Changes
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
