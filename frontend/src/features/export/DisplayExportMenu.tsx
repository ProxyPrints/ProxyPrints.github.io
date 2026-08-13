import React from "react";
import Dropdown from "react-bootstrap/Dropdown";

import { RightPaddedIcon } from "@/components/icon";
import { DisplayExportPDF } from "@/features/export/DisplayExportPDF";
import { ExportDecklist } from "@/features/export/ExportDecklist";
import { ExportImages } from "@/features/export/ExportImages";
import { ExportXML } from "@/features/export/ExportXML";
import { DisplaySheetExportSettings } from "@/features/pdf/displayPdfProps";

export interface DisplayExportMenuProps {
  sheetSettings: DisplaySheetExportSettings;
}

// Issue #241 (design doc §5's export-beyond-PDF row) - the last of the three toolbar-parity
// findings from the 2026-07-20 feature-parity audit against /editor. Composes the same three
// unchanged Dropdown.Items Export.tsx (the classic editor's own "Download" dropdown) already
// mounts - same hooks (useDownloadXML/useDoImageDownload/useDownloadDecklist), same gating
// selectors (selectIsProjectEmpty/selectAnyImagesDownloadable) baked into each item itself. A
// separate, smaller component rather than reusing Export.tsx directly because ExportPDF.tsx
// (the classic editor's own item) dispatches showModal("PDFGenerator") to open the classic
// export modal - not what this page wants. This page's own PDF item is DisplayExportPDF.tsx
// instead: it downloads straight from the sheet's own live settings via displayPdfProps.ts,
// with no modal and no preview of its own (see that component's own module comment).
export function DisplayExportMenu({ sheetSettings }: DisplayExportMenuProps) {
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
        <DisplayExportPDF sheetSettings={sheetSettings} />
      </Dropdown.Menu>
    </Dropdown>
  );
}
