import styled from "@emotion/styled";
import { useMemo } from "react";
import Form from "react-bootstrap/Form";

import { Printing, Unknown } from "@/common/constants";
import { getKeyruneChar } from "@/common/keyrune";
import { StyledDropdownTreeSelect } from "@/common/StyledDropdownTreeSelect";
import { useAppSelector } from "@/common/types";
import { selectCardDocumentsByIdentifiers } from "@/store/slices/cardDocumentsSlice";

// Renders the Keyrune set-symbol glyph embedded in each printing row's label (see
// common/keyrune.ts) - scoped to just this dropdown instance, not the shared
// StyledDropdownTreeSelect, since every other filter using that component has plain-text
// labels with no Keyrune glyph characters at all.
const PrintingDropdownTreeSelect = styled(StyledDropdownTreeSelect)`
  .node-label,
  .tag {
    font-family: "Keyrune", sans-serif;
  }
`;

/**
 * Resolve the flat list of selected printing-dropdown nodes into a deduplicated array of
 * Printing objects. Each node's value is either the Unknown sentinel or
 * "${expansionCode} ${collectorNumber}" - the dropdown is a flat list (one row per
 * printing), not a tree, so there's no parent/child expansion to resolve here.
 */
export function resolveSelectedPrintings(
  selectedNodes: Array<{ value: string }>
): Array<Printing> {
  const printingMap = new Map<string, Printing>();
  for (const node of selectedNodes) {
    const value = node.value as string;
    if (value === Unknown) {
      printingMap.set(`${Unknown}|${Unknown}`, {
        expansionCode: Unknown,
        collectorNumber: Unknown,
      });
      continue;
    }
    const spaceIdx = value.indexOf(" ");
    if (spaceIdx !== -1) {
      const expansionCode = value.substring(0, spaceIdx);
      const collectorNumber = value.substring(spaceIdx + 1);
      printingMap.set(`${expansionCode}|${collectorNumber}`, {
        expansionCode,
        collectorNumber,
      });
    }
  }
  return Array.from(printingMap.values());
}

interface CanonicalCardFilterProps {
  imageIdentifiers: Array<string>;
  printings: Array<Printing>;
  setPrintings: (printings: Array<Printing>) => void;
  artists: Array<string>;
  setArtists: (printings: Array<string>) => void;
}

export const CanonicalCardFilter = ({
  imageIdentifiers,
  printings,
  setPrintings,
  artists,
  setArtists,
}: CanonicalCardFilterProps) => {
  const cardDocumentsByIdentifier = useAppSelector((state) =>
    selectCardDocumentsByIdentifiers(state, imageIdentifiers)
  );
  const availableArtists = useMemo(() => {
    const artistSet = new Set<string>();
    let hasUnknown = false;
    Object.values(cardDocumentsByIdentifier).forEach((card) => {
      if (card == null) return;
      if (card.canonicalArtist == null) {
        hasUnknown = true;
      } else {
        artistSet.add(card.canonicalArtist.name);
      }
    });
    const sorted = Array.from(artistSet).sort();
    if (hasUnknown) sorted.push(Unknown);
    return sorted;
  }, [cardDocumentsByIdentifier]);

  // Stable structure: expansion -> { name, collector numbers }; only recomputes when card documents change
  const availablePrintingExpansions = useMemo(() => {
    const expansionMap = new Map<
      string,
      { name: string; code: string; numbers: Set<string> }
    >();
    let hasUnknown = false;
    Object.values(cardDocumentsByIdentifier).forEach((card) => {
      if (card == null) return;
      if (card.canonicalCard == null) {
        hasUnknown = true;
      } else {
        const { expansionCode, expansionName, collectorNumber } =
          card.canonicalCard;
        if (!expansionMap.has(expansionCode)) {
          expansionMap.set(expansionCode, {
            name: expansionName,
            code: expansionCode,
            numbers: new Set(),
          });
        }
        expansionMap.get(expansionCode)!.numbers.add(collectorNumber);
      }
    });
    return { expansionMap, hasUnknown };
  }, [cardDocumentsByIdentifier]);

  const includesPrinting = (printing: Printing): boolean =>
    printings.some(
      (value) =>
        printing.expansionCode === value.expansionCode &&
        printing.collectorNumber === value.collectorNumber
    );

  // Flat list of dropdown rows (one per printing), not a tree - each row's label is
  // "{Keyrune glyph}[SET] 123" for a compact, uniform look regardless of how long the
  // expansion's full name is; the full name is only shown via the native `title` tooltip
  // on hover. Sorted by expansion name, then collector number, so same-set printings sit
  // together despite there being no parent node to group them under any more.
  const availablePrintingOptions = useMemo(() => {
    const { expansionMap, hasUnknown } = availablePrintingExpansions;
    const nodes = Array.from(expansionMap.values())
      .flatMap(({ name, code, numbers }) =>
        Array.from(numbers).map((collectorNumber) => ({
          name,
          code,
          collectorNumber,
        }))
      )
      .sort(
        (a, b) =>
          a.name.localeCompare(b.name) ||
          a.collectorNumber.localeCompare(b.collectorNumber)
      )
      .map(({ name, code, collectorNumber }) => ({
        label: `${getKeyruneChar(
          code
        )} [${code.toUpperCase()}] ${collectorNumber}`,
        value: `${code} ${collectorNumber}`,
        title: name,
        checked: includesPrinting({ expansionCode: code, collectorNumber }),
      }));
    if (hasUnknown) {
      nodes.push({
        label: Unknown,
        value: Unknown,
        title: Unknown,
        checked: printings.some(
          (p) => p.expansionCode === Unknown && p.collectorNumber === Unknown
        ),
      });
    }
    return nodes;
  }, [availablePrintingExpansions, printings]);

  return (
    <>
      {availablePrintingOptions.filter((printing) => printing.label !== Unknown)
        .length > 0 && (
        <div data-testid="printing-filter">
          <Form.Label>Canonical card printings</Form.Label>
          <PrintingDropdownTreeSelect
            data={availablePrintingOptions}
            onChange={(_currentNode, selectedNodes) =>
              setPrintings(resolveSelectedPrintings(selectedNodes))
            }
            searchPredicate={(node, searchTerm) =>
              `${node.label} ${node.title ?? ""}`
                .toLowerCase()
                .includes(searchTerm)
            }
            inlineSearchInput
          />
        </div>
      )}
      {availableArtists.filter((artist) => artist !== Unknown).length > 0 && (
        <div data-testid="artist-filter">
          <Form.Label>Canonical card artists</Form.Label>
          <StyledDropdownTreeSelect
            data={availableArtists.map((artist) => ({
              label: artist,
              value: artist,
              checked: artists.includes(artist),
            }))}
            onChange={(_currentNode, selectedNodes) =>
              setArtists(selectedNodes.map((node) => node.value))
            }
            inlineSearchInput
          />
        </div>
      )}
    </>
  );
};
