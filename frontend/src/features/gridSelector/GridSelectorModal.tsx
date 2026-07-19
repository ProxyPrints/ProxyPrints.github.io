/**
 * This module contains a component which allows the user to select between
 * different card versions while seeing them all at once.
 */

import React, { useRef } from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { useAppSelector } from "@/common/types";
import { GridSelectorResults } from "@/features/gridSelector/GridSelectorResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { selectJumpToVersionVisible } from "@/store/slices/viewSettingsSlice";

interface GridSelectorProps {
  title?: string;
  testId: string;
  imageIdentifiers: Array<string>;
  selectedImage?: string;
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
  onClick: {
    (identifier: string): void;
  };
  searchq?: string;
  /** When false, ignore project-level search settings and use unconstrained defaults instead. */
  applySearchSettings?: boolean;
}

export function GridSelectorModal({
  title = "Select Version",
  testId,
  imageIdentifiers,
  selectedImage,
  show,
  handleClose,
  onClick,
  searchq,
  applySearchSettings = true,
}: GridSelectorProps) {
  //# region queries and hooks

  const jumpToVersionVisible = useAppSelector(selectJumpToVersionVisible);

  //# endregion

  //# region state

  const focusRef = useRef<HTMLInputElement>(null);
  // Fallback autofocus target for when the Jump to Version section (which focusRef normally
  // targets) is collapsed - focusing a collapsed-but-still-mounted input silently does
  // nothing in a real browser (it's not "visible" per focus-eligibility rules), which used to
  // leave focus stuck on the dialog container with no visible indication it had moved at all.
  const settingsToggleRef = useRef<HTMLButtonElement>(null);

  const search = useGridSelectorSearch({
    imageIdentifiers,
    active: show,
    applySearchSettings,
  });

  const selectImage = (identifier: string) => {
    onClick(identifier);
    handleClose();
  };

  //# endregion

  const modalTitle = `${title} — ${search.resultCount.toLocaleString()} result${
    search.resultCount !== 1 ? "s" : ""
  }`;

  return (
    <Modal
      scrollable
      show={show}
      onEntered={() => {
        if (jumpToVersionVisible && focusRef.current) {
          focusRef.current.focus();
        } else {
          settingsToggleRef.current?.focus();
        }
      }}
      onHide={handleClose}
      size="xl"
      data-testid={testId}
    >
      <Modal.Header closeButton>
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <Modal.Title>{modalTitle}</Modal.Title>
          <Button
            ref={settingsToggleRef}
            variant="outline-primary"
            size="sm"
            onClick={() => search.setSettingsVisible((v) => !v)}
          >
            <i
              className={`bi bi-chevron-${
                search.settingsVisible ? "left" : "right"
              }`}
            />{" "}
            Filters
          </Button>
        </div>
      </Modal.Header>
      <Modal.Body className="p-0" style={{ overflowY: "hidden" }}>
        <GridSelectorResults
          variant="modal"
          imageIdentifiers={imageIdentifiers}
          selectedImage={selectedImage}
          onSelectImage={selectImage}
          focusRef={focusRef}
          search={search}
        />
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={handleClose}>
          Close
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
