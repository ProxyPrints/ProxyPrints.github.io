import { CardType } from "@/common/schema_types";
import { cardDocument1, cardDocument12 } from "@/common/test-constants";
import { SlotProjectMembers } from "@/common/types";
import { generateXML } from "@/features/download/downloadXML";

import { parseXmlImport } from "./ImportXML";

function buildSlot(
  id: string,
  frontIdentifier: string | undefined
): SlotProjectMembers {
  return {
    id,
    front:
      frontIdentifier != null
        ? {
            query: { query: null, cardType: CardType.Card },
            selectedImage: frontIdentifier,
            selected: false,
          }
        : null,
    back: null,
  };
}

const finishSettings = {
  cardstock: "(S30) Standard Smooth" as const,
  foil: false,
};

const XML_1_0 = `<?xml version="1.0"?>
<order>
  <details>
    <quantity>1</quantity>
    <stock>(S30) Standard Smooth</stock>
    <foil>false</foil>
  </details>
  <fronts>
    <card>
      <id>abc123</id>
      <sourceType>google_drive</sourceType>
      <slots>0</slots>
      <name>Lightning Bolt.png</name>
      <query>lightning bolt</query>
    </card>
  </fronts>
  <cardback></cardback>
</order>`;

describe("parseXmlImport", () => {
  it("a 1.0 file (no set/collectorNumber elements) is unaffected - expansionCode/collectorNumber stay undefined", () => {
    const { members } = parseXmlImport(XML_1_0, 0, null, true);
    expect(members[0].front?.selectedImage).toBe("abc123");
    expect(members[0].front?.query.expansionCode).toBeUndefined();
    expect(members[0].front?.query.collectorNumber).toBeUndefined();
  });

  it("reads set/collectorNumber from a 2.0 file into the parsed SearchQuery", () => {
    const xml = generateXML(
      [buildSlot("slot-1", cardDocument12.identifier)],
      { [cardDocument12.identifier]: cardDocument12 },
      null,
      1,
      finishSettings
    );

    const { members } = parseXmlImport(xml, 0, null, true);

    expect(members[0].front?.selectedImage).toBe(cardDocument12.identifier);
    expect(members[0].front?.query.expansionCode).toBe(
      cardDocument12.canonicalCard?.expansionCode
    );
    expect(members[0].front?.query.collectorNumber).toBe(
      cardDocument12.canonicalCard?.collectorNumber
    );
  });

  it("round-trips: export a card with no resolved canonicalCard, reimport, still no expansionCode/collectorNumber", () => {
    const xml = generateXML(
      [buildSlot("slot-1", cardDocument1.identifier)],
      { [cardDocument1.identifier]: cardDocument1 },
      null,
      1,
      finishSettings
    );

    const { members } = parseXmlImport(xml, 0, null, true);

    expect(members[0].front?.selectedImage).toBe(cardDocument1.identifier);
    expect(members[0].front?.query.expansionCode).toBeUndefined();
    expect(members[0].front?.query.collectorNumber).toBeUndefined();
  });

  it("still reads stock/foil finish settings from the file, unchanged", () => {
    const { stock, foil } = parseXmlImport(XML_1_0, 0, null, true);
    expect(stock).toBe("(S30) Standard Smooth");
    expect(foil).toBe(false);
  });
});

// Foreign-order resilience Phase 1 (issue #324) - the reported symptom: an order XML
// referencing a Drive file ID this catalog never indexed. parseXmlImport already read raw
// <id>/<query> text verbatim before this feature landed - what's under test here is that this
// stays true even for an ID with no catalog match, INCLUDING the exact "b:null" back-face shape
// from the owner's screenshot (an empty <query> element on the back, i.e. no name text at all).
// The actual fix (not clearing/invalidating an unresolved-but-plausible identifier) lives in
// listenerMiddleware.ts and cardDocumentsSlice.ts - this only covers the parser's own half.
describe("foreign-order resilience Phase 1 - unindexed identifiers (issue #324)", () => {
  const orphanId = "1LrVX0pUcye9n_0RtaDNVl2xPrQgn7CYf";

  it("reads a front <id> the catalog doesn't know about, unchanged", () => {
    const xml = `<?xml version="1.0"?>
<order>
  <details>
    <quantity>1</quantity>
    <stock>(S30) Standard Smooth</stock>
    <foil>false</foil>
  </details>
  <fronts>
    <card>
      <id>${orphanId}</id>
      <sourceType>google_drive</sourceType>
      <slots>0</slots>
      <name>Kharn.png</name>
      <query>kharn</query>
    </card>
  </fronts>
  <cardback></cardback>
</order>`;
    const { members } = parseXmlImport(xml, 0, null, true);
    expect(members[0].front?.selectedImage).toBe(orphanId);
    expect(members[0].front?.query.query).toBe("kharn");
  });

  it("also surfaces the file's own root <cardback> text via the return value's `cardback` field (regardless of catalog/orphan status), for the caller to propagate into state.project.cardback", () => {
    // Follow-up fix (owner-observed 2026-07-23): parseXmlImport previously only ever fed the
    // file's own <cardback> into each individual backless front's own per-slot fallback - never
    // back out to the caller for state.project.cardback itself, which is why the "Common
    // Cardback" panel (CommonCardback.tsx) kept showing "Card not found" after an XML import
    // instead of the file's actual cardback (orphan or not) - see ImportXML.tsx's own
    // parseXMLFile comment for the caller-side half of this fix.
    const xml = `<?xml version="1.0"?>
<order>
  <details>
    <quantity>1</quantity>
    <stock>(S30) Standard Smooth</stock>
    <foil>false</foil>
  </details>
  <fronts>
    <card>
      <id>abc123</id>
      <sourceType>google_drive</sourceType>
      <slots>0</slots>
      <name>Kharn.png</name>
      <query>kharn</query>
    </card>
  </fronts>
  <cardback>${orphanId}</cardback>
</order>`;
    const { cardback } = parseXmlImport(xml, 0, null, true);
    expect(cardback).toBe(orphanId);
  });

  it("`cardback` is undefined when the file has no <cardback> element (or an empty one) at all", () => {
    const { cardback } = parseXmlImport(XML_1_0, 0, null, true);
    expect(cardback).toBeUndefined();
  });

  it("reads an unindexed <cardback> as the implicit back face (the reported b:null case), unchanged", () => {
    // The owner's screenshot showed an Invalid Cards row "Back | b:null | <id>" -
    // stringifySearchQuery renders "b:null" specifically when query.query is the literal JS
    // `null`, which only happens via THIS path: a front slot with no matching <backs> entry
    // falls back to the order's own root-level <cardback> element (parseXmlImport's own
    // `newMembers[slot].back == null` branch), carrying `query: { query: null, cardType:
    // Cardback }` - not an empty/blank query string.
    const xml = `<?xml version="1.0"?>
<order>
  <details>
    <quantity>1</quantity>
    <stock>(S30) Standard Smooth</stock>
    <foil>false</foil>
  </details>
  <fronts>
    <card>
      <id>abc123</id>
      <sourceType>google_drive</sourceType>
      <slots>0</slots>
      <name>Kharn.png</name>
      <query>kharn</query>
    </card>
  </fronts>
  <cardback>${orphanId}</cardback>
</order>`;
    const { members } = parseXmlImport(xml, 0, null, true);
    expect(members[0].back?.selectedImage).toBe(orphanId);
    expect(members[0].back?.query.query).toBeNull();
  });
});
