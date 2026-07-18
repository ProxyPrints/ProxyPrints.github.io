/**
 * This module contains functionality for generating an XML representation of the project,
 * suitable for re-uploading into the frontend or uploading to MakePlayingCards
 * through the desktop tool CLI.
 *
 * XML 2.0 (see the held print-preview design task's proposal artifact for the full findings):
 * a `version="2.0"` attribute on the root `<order>` element, plus optional `<set>`/
 * `<collectorNumber>`/`<scryfallId>` elements per `<card>`, populated from that card's
 * *community-confirmed* `canonicalCard` (not the slot's own search query, which is only a
 * declared import intent, not a verified identity - see docs/features/printing-tags.md's
 * Level 0 section for why those are kept distinct). A card without a resolved canonicalCard
 * simply omits the new elements, same as it always omitted `data-card-set-code` in the DOM API.
 *
 * Both additions are structurally invisible to the desktop tool's existing 1.0 parser -
 * verified by reading `desktop-tool/src/order.py` and `utils.py` directly: `unpack_element`
 * builds its dict from an element's *actual* children merged over expected-tag defaults, so an
 * unrecognised child tag just becomes an unread dict entry, and no code path anywhere in
 * `order.py` reads `Element.attrib` at all, on any element, ever - so `version` is invisible to
 * it structurally, not just by convention. An unmodified 1.0 desktop-tool install reads a 2.0
 * file exactly as if these additions didn't exist.
 */

import formatXML from "xml-formatter";

import { Back, Front, ReversedCardTypePrefixes } from "@/common/constants";
import { SourceType } from "@/common/schema_types";
import { useAppDispatch, useAppStore } from "@/common/types";
import {
  CardDocuments,
  FinishSettingsState,
  SlotProjectMembers,
} from "@/common/types";
import { bracket } from "@/common/utils";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { downloadFile, useDoFileDownload } from "@/features/download/download";
import { selectFinishSettings } from "@/store/slices/finishSettingsSlice";
import {
  selectProjectMembers,
  selectProjectSize,
} from "@/store/slices/projectSlice";
import { setNotification } from "@/store/slices/toastsSlice";
import { AppDispatch, RootState } from "@/store/store";

import { useLocalFilesDirectoryHandle } from "../clientSearch/clientSearchHooks";

interface SlotsByIdentifier {
  [identifier: string]: Set<number>;
}
interface SlotsByIdentifierAndFace {
  front: SlotsByIdentifier;
  back: SlotsByIdentifier;
}

/**
 * Aggregate cards in project by (face, selected image) => a list of slots.
 */
function aggregateSlotsByIdentifierAndFace(
  projectMembers: Array<SlotProjectMembers>,
  cardback: string | null
): SlotsByIdentifierAndFace {
  const orderMap: SlotsByIdentifierAndFace = { front: {}, back: {} };
  for (const [slot, projectMember] of projectMembers.entries()) {
    for (const face of [Front, Back]) {
      const projectMemberAtFace = projectMember[face];
      if (projectMemberAtFace != null) {
        const selectedImage = projectMemberAtFace.selectedImage;
        if (selectedImage != null && selectedImage !== cardback) {
          // add to `orderMap`, initialising if necessary
          if (orderMap[face][selectedImage] == null) {
            orderMap[face][selectedImage] = new Set([slot]);
          } else {
            orderMap[face][selectedImage].add(slot);
          }
        }
      }
    }
  }
  return orderMap;
}

/**
 * Create an XML element representing the card `identifier`, which is included in the project at `slots`.
 */
function createCardElement(
  cardDocuments: CardDocuments,
  doc: XMLDocument,
  identifier: string,
  slots: Set<number>
): Element | null {
  const maybeCardDocument = cardDocuments[identifier];
  if (maybeCardDocument == null) {
    return null;
  }
  const cardElement = doc.createElement("card");

  const identifierElement = doc.createElement("id");
  identifierElement.appendChild(doc.createTextNode(identifier));
  cardElement.appendChild(identifierElement);

  const sourceTypeElement = doc.createElement("sourceType");
  sourceTypeElement.appendChild(
    doc.createTextNode(
      cardDocuments[identifier].sourceType ?? SourceType.GoogleDrive
    )
  );
  cardElement.appendChild(sourceTypeElement);

  const slotsElement = doc.createElement("slots");
  slotsElement.appendChild(
    doc.createTextNode(
      Array.from(slots)
        .sort((a, b) => a - b)
        .toString()
    )
  );
  cardElement.appendChild(slotsElement);

  const nameElement = doc.createElement("name");
  nameElement.appendChild(
    doc.createTextNode(
      `${maybeCardDocument.name}.${maybeCardDocument.extension}`
    )
  );
  cardElement.append(nameElement);

  const queryElement = doc.createElement("query");
  queryElement.appendChild(
    doc.createTextNode(
      ReversedCardTypePrefixes[maybeCardDocument.cardType] +
        maybeCardDocument.searchq
    )
  );
  cardElement.append(queryElement);

  // XML 2.0 additions - optional, additive, invisible to a 1.0 parser (see this module's own
  // header comment for the compat evidence). Only emitted for a card whose canonicalCard is
  // actually populated - i.e. a community-confirmed printing, not merely an imported search
  // query's declared intent (see the header comment for why those two are kept distinct).
  const canonicalCard = maybeCardDocument.canonicalCard;
  if (canonicalCard != null) {
    const setElement = doc.createElement("set");
    setElement.appendChild(doc.createTextNode(canonicalCard.expansionCode));
    cardElement.append(setElement);

    const collectorNumberElement = doc.createElement("collectorNumber");
    collectorNumberElement.appendChild(
      doc.createTextNode(canonicalCard.collectorNumber)
    );
    cardElement.append(collectorNumberElement);

    const scryfallIdElement = doc.createElement("scryfallId");
    scryfallIdElement.appendChild(doc.createTextNode(canonicalCard.identifier));
    cardElement.append(scryfallIdElement);
  }

  return cardElement;
}

const selectGeneratedXML = (state: RootState): string => {
  return generateXML(
    selectProjectMembers(state),
    state.cardDocuments.cardDocuments,
    state.project.cardback,
    selectProjectSize(state),
    selectFinishSettings(state)
  );
};

/**
 * Generate an XML representation of the project, suitable for re-importing into MPC Autofill
 * and suitable for uploading through the desktop tool.
 */
export function generateXML(
  projectMembers: Array<SlotProjectMembers>,
  cardDocuments: CardDocuments,
  cardback: string | null,
  projectSize: number,
  finishSettings: FinishSettingsState
): string {
  const orderMap = aggregateSlotsByIdentifierAndFace(projectMembers, cardback);

  // top level XML doc element, attach everything to this
  const doc = document.implementation.createDocument("", "", null);
  const orderElement = doc.createElement("order");
  // An XML attribute, not an element - invisible to the 1.0 desktop-tool parser, which never
  // reads Element.attrib on any element (see this module's header comment for the evidence).
  orderElement.setAttribute("version", "2.0");

  // project details
  const detailsElement = doc.createElement("details");

  const quantityElement = doc.createElement("quantity");
  quantityElement.appendChild(doc.createTextNode(projectSize.toString()));
  detailsElement.appendChild(quantityElement);

  const stockElement = doc.createElement("stock");
  stockElement.appendChild(doc.createTextNode(finishSettings.cardstock));
  detailsElement.appendChild(stockElement);

  const foilElement = doc.createElement("foil");
  foilElement.appendChild(
    doc.createTextNode(finishSettings.foil ? "true" : "false")
  );
  detailsElement.appendChild(foilElement);

  orderElement.append(detailsElement);

  // project cards
  for (const face of [Front, Back]) {
    if (Object.keys(orderMap[face]).length > 0) {
      const faceElement = doc.createElement(`${face}s`);
      for (const [identifier, slots] of Object.entries(orderMap[face])) {
        const cardElement = createCardElement(
          cardDocuments,
          doc,
          identifier,
          slots
        );
        const cardIsProjectCardback = identifier === cardback && face === Back;
        if (cardElement != null && !cardIsProjectCardback) {
          faceElement.appendChild(cardElement);
        }
      }
      if (faceElement.children.length > 0) {
        orderElement.appendChild(faceElement);
      }
    }
  }

  // common cardback
  const cardbackElement = doc.createElement("cardback");
  if (cardback != null) {
    cardbackElement.appendChild(doc.createTextNode(cardback));
  }
  orderElement.appendChild(cardbackElement);

  doc.appendChild(orderElement);

  // serialise to XML and format nicely
  const serialiser = new XMLSerializer();
  const xml = serialiser.serializeToString(doc);

  return formatXML(xml, { collapseContent: true });
}

async function downloadXML(
  dispatch: AppDispatch,
  state: RootState,
  clientSearchService: ClientSearchService,
  directoryHandleName?: string
) {
  const generatedXML = selectGeneratedXML(state);
  await downloadFile(
    new Blob([generatedXML], { type: "text/xml;charset=utf-8" }),
    undefined,
    "cards.xml",
    clientSearchService
  );
  dispatch(
    setNotification([
      Math.random().toString(),
      {
        name: "Download Complete",
        message: `Successfully downloaded XML to ${
          directoryHandleName ?? "Downloads folder"
        }!`,
        level: "info",
      },
    ])
  );
  return true;
}

export function useDownloadXML() {
  const dispatch = useAppDispatch();
  const store = useAppStore();
  const doFileDownload = useDoFileDownload();
  const { clientSearchService } = useClientSearchContext();
  const directoryHandle = useLocalFilesDirectoryHandle();
  return () =>
    Promise.resolve(
      doFileDownload(
        "xml",
        "cards.xml",
        (): Promise<boolean> =>
          downloadXML(
            dispatch,
            store.getState(),
            clientSearchService,
            directoryHandle?.name
          )
      )
    );
}
