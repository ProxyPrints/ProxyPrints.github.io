/**
 * This component is the XML-based entrypoint for cards into the project editor.
 * Projects which have been previously exported as XML can be re-uploaded through
 * this component and their cards will be added to the current project state.
 * A dropzone is exposed for the user to either drag-and-drop or select their file with.
 * The user will be prompted on whether they want to use their uploaded file's
 * finish settings (e.g. foil/nonfoil, the selected cardstock) or retain the project's
 * finish settings.
 *
 * XML 2.0 import (closes downloadXML.ts's export-only half of the round trip - see that
 * module's own header comment for the full design rationale): the optional `<set>`/
 * `<collectorNumber>` elements a 2.0 file may carry per `<card>` are read into that card's
 * `SearchQuery.expansionCode`/`collectorNumber`, alongside the `<id>` element 1.0 already
 * read (unchanged - `<id>` still wins as the exact-image selection whenever it resolves). The
 * value of also carrying the printing-level fields: if that exact image later turns out to be
 * dead (source removed, no longer indexed - see `recordInvalidIdentifier`'s existing fallback
 * path in `listenerMiddleware.ts`), the fallback search this app already runs stays
 * constrained to the correct set + collector number instead of silently widening to "any
 * printing of this name." `<scryfallId>` is deliberately left unread - there is no
 * `SearchQuery` field to hold a printing UUID, and expansionCode + collectorNumber already
 * fully specify search intent (the same reasoning that declined a scryfallId text token for
 * plaintext decklist export). A 1.0 file simply has no `<set>`/`<collectorNumber>` elements to
 * find, so this is purely additive - `getElementsByTagName` on a 1.0 `<card>` just returns an
 * empty collection and `[0]` is `undefined`, same as it always was for any other optional field.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Dropdown from "react-bootstrap/Dropdown";
import Modal from "react-bootstrap/Modal";
// @ts-ignore: https://github.com/arnthor3/react-bootstrap-toggle/issues/21
import Toggle from "react-bootstrap-toggle";

import {
  Cardback,
  Cardstocks,
  ProjectMaxSize,
  ProjectName,
  ToggleButtonHeight,
} from "@/common/constants";
import { TextFileDropzone } from "@/common/dropzone";
import { processSearchQuery } from "@/common/processing";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { Cardstock, SearchQuery, SlotProjectMembers } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { MakePlayingCardsLink } from "@/components/MakePlayingCardsLink";
import { setCardstock, setFoil } from "@/store/slices/finishSettingsSlice";
import {
  addMembers,
  selectProjectCardback,
  selectProjectSize,
  setSelectedCardback,
} from "@/store/slices/projectSlice";

export interface ParsedXmlImport {
  members: Array<Omit<SlotProjectMembers, "id">>;
  stock?: string;
  foil?: boolean;
  /** The file's own root-level `<cardback>` text, verbatim - `undefined` when the file carries
   * no `<cardback>` element (or an empty one) at all, distinct from the internal
   * `xmlCardback` variable below (which additionally falls back to the CURRENT project
   * cardback, purely for populating each backless front's own per-slot fallback). Foreign-order
   * resilience Phase 1 (issue #324) follow-up: the caller (`ImportXML`'s `parseXMLFile`) uses
   * this to initialise `state.project.cardback` when the project doesn't have one selected yet -
   * see that call site's own comment for why, and why it's gated on the project's own cardback
   * still being unset. */
  cardback?: string;
}

/**
 * Merge a `<card>` element's optional XML 2.0 `<set>`/`<collectorNumber>` elements into an
 * already-parsed `searchQuery`, if both are present. Both-or-neither: `downloadXML.ts` only
 * ever emits these two together (gated on a resolved `canonicalCard`), so a file carrying only
 * one would already be malformed - requiring both here means a partial/corrupted pair is
 * silently ignored rather than applied half-specified.
 */
function applyXml2PrintingInfo(
  searchQuery: SearchQuery,
  cardElement: Element
): SearchQuery {
  const expansionCode = cardElement.getElementsByTagName("set")[0]?.textContent;
  const collectorNumber =
    cardElement.getElementsByTagName("collectorNumber")[0]?.textContent;
  return expansionCode != null && collectorNumber != null
    ? { ...searchQuery, expansionCode, collectorNumber }
    : searchQuery;
}

/**
 * Parse an uploaded XML file's contents into project members ready to add to the store, plus
 * whatever finish settings the file carries. Pure and side-effect-free (no dispatch) so it can
 * be tested directly against XML text - see `ImportXML.test.ts`.
 */
export function parseXmlImport(
  xmlString: string,
  projectSize: number,
  projectCardback: string | null | undefined,
  useXMLCardback: boolean
): ParsedXmlImport {
  const parser = new DOMParser();
  const xmlDocument = parser.parseFromString(xmlString, "application/xml");
  const rootElement = xmlDocument.getElementsByTagName("order")[0];

  const detailsElement = rootElement.getElementsByTagName("details")[0];
  const stock = detailsElement.getElementsByTagName("stock")[0]?.textContent;
  const foil =
    detailsElement.getElementsByTagName("foil")[0]?.textContent === "true";
  const frontsElement = rootElement.getElementsByTagName("fronts")[0];
  const backsElement = rootElement.getElementsByTagName("backs")[0];

  const frontCardElements = frontsElement.getElementsByTagName("card");
  const backCardElements =
    backsElement != null
      ? backsElement.getElementsByTagName("card")
      : undefined;

  // The file's own literal `<cardback>` text - `undefined` for a missing OR empty element ("" is
  // not a usable identifier - see the XML_1_0 test fixture's `<cardback></cardback>`), kept
  // separate from `xmlCardback` below (which additionally falls back to the CURRENT project
  // cardback, purely for populating each individual backless front's own per-slot fallback).
  const xmlCardbackElementText =
    rootElement.getElementsByTagName("cardback")[0]?.textContent || undefined;
  const xmlCardback = xmlCardbackElementText ?? projectCardback;

  // `newMembers` is initialised with the maximum length it might need to contain all cards
  // the project can hold, then is truncated later according to `lastNonNullSlot`
  let lastNonNullSlot = 0;
  const newMembers: Array<Omit<SlotProjectMembers, "id">> = Array.from(
    { length: ProjectMaxSize - projectSize },
    () => {
      return { front: null, back: null };
    }
  );

  // it's actually important that we iterate over the backs before the fronts
  // this way, we can determine if each card needs to be given the project cardback or not
  if (backCardElements != null) {
    // TODO: avoid copy/pasting this stuff?
    for (const backCardElement of backCardElements) {
      const slotsText =
        backCardElement.getElementsByTagName("slots")[0]?.textContent;
      if (slotsText == null) {
        continue;
      }
      const searchQuery = applyXml2PrintingInfo(
        processSearchQuery(
          backCardElement.getElementsByTagName("query")[0].textContent ?? ""
        ),
        backCardElement
      );
      slotsText
        .split(",")
        .map((slotText) => parseInt(slotText))
        .forEach((slot) => {
          newMembers[slot].back = {
            query: searchQuery,
            selectedImage:
              backCardElement.getElementsByTagName("id")[0].textContent ??
              undefined,
            selected: false,
          };

          lastNonNullSlot = Math.max(lastNonNullSlot, slot);
        });
    }
  }

  for (const frontCardElement of frontCardElements) {
    const slotsText =
      frontCardElement.getElementsByTagName("slots")[0].textContent;
    if (slotsText == null) {
      continue;
    }
    const searchQuery = applyXml2PrintingInfo(
      processSearchQuery(
        frontCardElement.getElementsByTagName("query")[0].textContent ?? ""
      ),
      frontCardElement
    );

    slotsText
      .split(",")
      .map((slotText) => parseInt(slotText))
      .forEach((slot) => {
        newMembers[slot].front = {
          query: searchQuery,
          selectedImage:
            frontCardElement.getElementsByTagName("id")[0].textContent ??
            undefined,
          selected: false,
        };

        // apply the uploaded XML's cardback if the card doesn't have a matching back
        // and if the user wants to retain the XML's cardback
        // otherwise, default to the project's cardback
        if (newMembers[slot].back == null) {
          newMembers[slot].back = {
            query: { query: null, cardType: Cardback },
            selectedImage: useXMLCardback
              ? xmlCardback ?? undefined
              : undefined,
            selected: false,
          };
        }

        lastNonNullSlot = Math.max(lastNonNullSlot, slot);
      });
  }

  return {
    members: newMembers.slice(0, lastNonNullSlot + 1),
    stock: stock ?? undefined,
    foil,
    cardback: xmlCardbackElementText,
  };
}

interface ImportXMLProps {
  onImportComplete?: () => void;
}

export function ImportXML({ onImportComplete }: ImportXMLProps) {
  const dispatch = useAppDispatch();
  const projectCardback = useAppSelector(selectProjectCardback);
  const projectSize = useAppSelector(selectProjectSize);

  const [useXMLCardback, setUseXMLCardback] = useState<boolean>(true);
  const [useXMLFinishSettings, setUseXMLFinishSettings] =
    useState<boolean>(false);

  const parseXMLFile = (fileContents: string | ArrayBuffer | null) => {
    if (typeof fileContents !== "string") {
      alert("invalid CSV file uploaded");
      // TODO: error messaging to the user that they've uploaded an invalid file
      return;
    }

    // TODO: throw a user-visible error if the xml doc is malformed
    const { members, stock, foil, cardback } = parseXmlImport(
      fileContents,
      projectSize,
      projectCardback,
      useXMLCardback
    );
    dispatch(addMembers({ members }));

    // Foreign-order resilience Phase 1 (issue #324) follow-up (owner-observed 2026-07-23): a
    // BRAND NEW project (state.project.cardback still null - nothing auto-selected yet, e.g. the
    // catalog has zero indexed cardbacks at all) never got state.project.cardback initialised
    // from the very XML file just imported, even when the user opted to use that file's own
    // cardback - so the "Common Cardback" panel (CommonCardback.tsx, the classic editor's right
    // panel - a SEPARATE, project-wide concept from any individual slot's own back, see
    // cardDocumentsSlice.ts's own comment on that distinction) kept showing "Card not found"
    // right next to a perfectly-rendered orphan back-face slot tile, independent of whether the
    // file's own cardback identifier is a real catalog cardback or an orphan Drive file ID this
    // catalog has never indexed. Deliberately gated on `projectCardback == null` (the value
    // already read above, before this import): an EXISTING non-null project cardback must stay
    // untouched by a later XML import even with useXMLCardback=true - that's a real, deliberate,
    // already-tested distinction (ImportXML.spec.ts's "import an XML and use its cardback" -
    // useXMLCardback only ever governed each backless front's OWN per-slot fallback, never this
    // project-wide setting) which this fix must not regress.
    if (useXMLCardback && cardback != null && projectCardback == null) {
      dispatch(setSelectedCardback({ selectedImage: cardback }));
    }

    if (
      useXMLFinishSettings &&
      stock != null &&
      Cardstocks.includes(stock as Cardstock) &&
      foil != null
    ) {
      dispatch(setCardstock(stock as Cardstock));
      dispatch(setFoil(foil));
    }

    onImportComplete?.();
  };

  return (
    <>
      <p>Upload an XML file of cards to add to the project.</p>
      <p>
        The {ProjectName} website can generate an XML file representing your
        project, and the {ProjectName} desktop tool which auto-fills your order
        into <MakePlayingCardsLink /> expects a file in this format.
      </p>
      <div className="px-0">
        <Toggle
          onClick={() => setUseXMLCardback(!useXMLCardback)}
          on="Use XML Cardback"
          onClassName="flex-centre"
          off="Use Project Cardback"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={useXMLCardback}
        />
      </div>
      <div className="pt-3">
        <Toggle
          onClick={() => setUseXMLFinishSettings(!useXMLFinishSettings)}
          on="Use XML Finish Settings"
          onClassName="flex-centre"
          off="Retain Selected Finish Settings"
          offClassName="flex-centre"
          onstyle="success"
          offstyle="info"
          width={100 + "%"}
          size="md"
          height={ToggleButtonHeight + "px"}
          active={useXMLFinishSettings}
        />
      </div>
      <hr />
      <TextFileDropzone
        mimeTypes={{ "text/xml": [".xml"] }}
        fileUploadCallback={parseXMLFile}
        label="import-xml"
        disabled={false} // this importer has no DFC integration so there's no need to wait for anything
      />
    </>
  );
}

export function ImportXMLButton() {
  const [show, setShow] = useState<boolean>(false);

  return (
    <>
      <Dropdown.Item onClick={() => setShow(true)}>
        <RightPaddedIcon bootstrapIconName="file-code" /> XML
      </Dropdown.Item>
      <Modal
        scrollable
        show={show}
        onHide={() => setShow(false)}
        data-testid="import-xml"
      >
        <Modal.Header closeButton>
          <Modal.Title>Add Cards — XML</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <ImportXML onImportComplete={() => setShow(false)} />
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShow(false)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}
