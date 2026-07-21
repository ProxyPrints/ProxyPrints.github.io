import React from "react";
import Dropdown from "react-bootstrap/Dropdown";

import { RightPaddedIcon } from "@/components/icon";
import { ExportDecklist } from "@/features/export/ExportDecklist";
import { ExportImages } from "@/features/export/ExportImages";
import { ExportXML } from "@/features/export/ExportXML";

// Issue #241 (design doc §5's export-beyond-PDF row) - the last of the three toolbar-parity
// findings from the 2026-07-20 feature-parity audit against /editor. Composes the same three
// unchanged Dropdown.Items Export.tsx (the classic editor's own "Download" dropdown) already
// mounts - same hooks (useDownloadXML/useDoImageDownload/useDownloadDecklist), same gating
// selectors (selectIsProjectEmpty/selectAnyImagesDownloadable) baked into each item itself. A
// separate, smaller component rather than reusing Export.tsx directly because this page's
// toolbar deliberately excludes ExportPDF.tsx: that item dispatches showModal("PDFGenerator") to
// open the classic export modal, which this page's own "Generate PDF" button already bypasses by
// calling useDownloadPDF directly (see DisplayPage.tsx's own inline-export region comment) -
// wiring ExportPDF in here too would just add a second, redundant path to the same export.
export function DisplayExportMenu() {
  return (
    <Dropdown>
      <Dropdown.Toggle
        size="sm"
        variant="outline-secondary"
        id="display-export-menu-toggle"
        data-testid="display-export-menu-toggle"
      >
        <RightPaddedIcon bootstrapIconName="cloud-arrow-down" /> Export
      </Dropdown.Toggle>
      <Dropdown.Menu data-testid="display-export-menu">
        <ExportXML />
        <ExportImages />
        <ExportDecklist />
      </Dropdown.Menu>
    </Dropdown>
  );
}
