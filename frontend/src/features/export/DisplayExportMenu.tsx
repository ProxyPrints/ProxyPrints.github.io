import React from "react";
import Dropdown from "react-bootstrap/Dropdown";

import { RightPaddedIcon } from "@/components/icon";
import { DisplayExportPDF } from "@/features/export/DisplayExportPDF";
import { DisplayExportPrintshops } from "@/features/export/DisplayExportPrintshops";
import { ExportDecklist } from "@/features/export/ExportDecklist";
import { ExportImages } from "@/features/export/ExportImages";
import { ExportXML } from "@/features/export/ExportXML";
import { DisplaySheetExportSettings } from "@/features/pdf/displayPdfProps";

export interface DisplayExportMenuProps {
  sheetSettings: DisplaySheetExportSettings;
  /** Forwarded to `DisplayExportPDF`'s own `runExportGate` prop - see that component's own
   * comment. */
  runExportGate: (proceed: () => void) => void;
}

// Issue #241 (design doc §5's export-beyond-PDF row) - the last of the three toolbar-parity
// findings from the 2026-07-20 feature-parity audit against /editor. Three standalone download
// items (XML/Card Images/Decklist), each owning its own hooks (useDownloadXML/
// useDoImageDownload/useDownloadDecklist) and gating selectors (selectIsProjectEmpty/
// selectAnyImagesDownloadable) baked into the item itself. The PDF item is DisplayExportPDF.tsx:
// it downloads straight from the sheet's own live settings via displayPdfProps.ts, with no
// modal and no preview of its own (see that component's own module comment).
// DisplayExportPrintshops.tsx rounds out the menu with the three printshop ordering guides
// (PringlePrints/MakePlayingCards/NotMPC), relocated here from the retired `/print` "Print!"
// tab so printshop orders stay reachable from the editor - see its own module comment.
export function DisplayExportMenu({
  sheetSettings,
  runExportGate,
}: DisplayExportMenuProps) {
  return (
    <Dropdown>
      <Dropdown.Toggle
        variant="outline-primary"
        id="display-export-menu-toggle"
        data-testid="display-export-menu-toggle"
      >
        <RightPaddedIcon bootstrapIconName="cloud-arrow-down" /> Export
      </Dropdown.Toggle>
      <Dropdown.Menu data-testid="display-export-menu">
        <ExportXML />
        <ExportImages />
        <ExportDecklist />
        <DisplayExportPDF
          sheetSettings={sheetSettings}
          runExportGate={runExportGate}
        />
        <DisplayExportPrintshops />
      </Dropdown.Menu>
    </Dropdown>
  );
}
