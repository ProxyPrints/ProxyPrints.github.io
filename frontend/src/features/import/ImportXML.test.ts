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
