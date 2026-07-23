import { synthesizeOrphanCardDocument } from "@/common/orphanCard";
import { CardType } from "@/common/schema_types";
import { cardDocument1, cardDocument12 } from "@/common/test-constants";
import { SlotProjectMembers } from "@/common/types";

import { generateXML } from "./downloadXML";

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

describe("generateXML", () => {
  it('emits a version="2.0" attribute on the root <order> element', () => {
    const xml = generateXML([], {}, null, 0, finishSettings);
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    expect(doc.documentElement.tagName).toBe("order");
    expect(doc.documentElement.getAttribute("version")).toBe("2.0");
  });

  it("omits set/collectorNumber/scryfallId for a card with no resolved canonicalCard", () => {
    const xml = generateXML(
      [buildSlot("slot-1", cardDocument1.identifier)],
      { [cardDocument1.identifier]: cardDocument1 },
      null,
      1,
      finishSettings
    );
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    const card = doc.querySelector("fronts > card");
    expect(card).not.toBeNull();
    expect(card?.querySelector("set")).toBeNull();
    expect(card?.querySelector("collectorNumber")).toBeNull();
    expect(card?.querySelector("scryfallId")).toBeNull();
  });

  it("emits set/collectorNumber/scryfallId from canonicalCard for a resolved printing", () => {
    const xml = generateXML(
      [buildSlot("slot-1", cardDocument12.identifier)],
      { [cardDocument12.identifier]: cardDocument12 },
      null,
      1,
      finishSettings
    );
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    const card = doc.querySelector("fronts > card");
    expect(card?.querySelector("set")?.textContent).toBe(
      cardDocument12.canonicalCard?.expansionCode
    );
    expect(card?.querySelector("collectorNumber")?.textContent).toBe(
      cardDocument12.canonicalCard?.collectorNumber
    );
    expect(card?.querySelector("scryfallId")?.textContent).toBe(
      cardDocument12.canonicalCard?.identifier
    );
  });

  it("still produces every 1.0 element unchanged - the additions are purely additive", () => {
    const xml = generateXML(
      [buildSlot("slot-1", cardDocument12.identifier)],
      { [cardDocument12.identifier]: cardDocument12 },
      null,
      1,
      finishSettings
    );
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    const card = doc.querySelector("fronts > card");
    expect(card?.querySelector("id")?.textContent).toBe(
      cardDocument12.identifier
    );
    expect(card?.querySelector("sourceType")?.textContent).toBe(
      cardDocument12.sourceType
    );
    expect(card?.querySelector("slots")?.textContent).toBe("0");
    expect(card?.querySelector("name")?.textContent).toBe(
      `${cardDocument12.name}.${cardDocument12.extension}`
    );
    expect(card?.querySelector("query")).not.toBeNull();
  });

  // Foreign-order resilience Phase 1 (issue #324) - the round-trip requirement: an orphan
  // (a synthesized CardDocument for a Drive file ID the catalog never indexed) must still
  // export with its raw <id> preserved, since createCardElement previously returned null
  // entirely for any identifier missing from cardDocuments.
  it("re-exports an orphan's raw <id>, unchanged", () => {
    const orphanId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
    const orphanCard = synthesizeOrphanCardDocument(orphanId, {
      name: "Kharn",
      cardType: CardType.Card,
    });
    const xml = generateXML(
      [buildSlot("slot-1", orphanId)],
      { [orphanId]: orphanCard },
      null,
      1,
      finishSettings
    );
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    const card = doc.querySelector("fronts > card");
    expect(card?.querySelector("id")?.textContent).toBe(orphanId);
    expect(card?.querySelector("query")?.textContent).toBe("Kharn");
  });
});
