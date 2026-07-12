import { Printing, Unknown } from "@/common/constants";

import { resolveSelectedPrintings } from "./CanonicalCardFilter";

function nodes(...values: string[]): Array<{ value: string }> {
  return values.map((v) => ({ value: v }));
}

describe("resolveSelectedPrintings", () => {
  describe("empty selection", () => {
    test("returns an empty array when no nodes are selected", () => {
      expect(resolveSelectedPrintings([])).toEqual([]);
    });
  });

  describe("Unknown node", () => {
    test("returns the Unknown printing when the Unknown node is selected", () => {
      expect(resolveSelectedPrintings(nodes(Unknown))).toEqual<Array<Printing>>(
        [{ expansionCode: Unknown, collectorNumber: Unknown }]
      );
    });

    test("selecting Unknown multiple times produces a single entry (deduplication)", () => {
      const result = resolveSelectedPrintings(nodes(Unknown, Unknown));
      expect(result).toHaveLength(1);
      expect(result[0]).toEqual<Printing>({
        expansionCode: Unknown,
        collectorNumber: Unknown,
      });
    });
  });

  describe("printing nodes", () => {
    test("selecting a printing node returns exactly that printing", () => {
      expect(resolveSelectedPrintings(nodes("xyz 001"))).toEqual<
        Array<Printing>
      >([{ expansionCode: "xyz", collectorNumber: "001" }]);
    });

    test("selecting multiple printings from the same expansion returns all selected", () => {
      const result = resolveSelectedPrintings(
        nodes("xyz 001", "xyz 002", "xyz 003")
      );
      expect(result).toHaveLength(3);
      expect(result).toContainEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "001",
      });
      expect(result).toContainEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "002",
      });
      expect(result).toContainEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "003",
      });
    });

    test("selecting printings from different expansions returns all selected", () => {
      const result = resolveSelectedPrintings(nodes("xyz 001", "abc 010"));
      expect(result).toHaveLength(2);
      expect(result).toContainEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "001",
      });
      expect(result).toContainEqual<Printing>({
        expansionCode: "abc",
        collectorNumber: "010",
      });
    });

    test("only the first space is used as the separator, preserving spaces in collector numbers", () => {
      // collector number "10 001" contains a space; node value is "xyz 10 001"
      expect(resolveSelectedPrintings(nodes("xyz 10 001"))).toEqual<
        Array<Printing>
      >([{ expansionCode: "xyz", collectorNumber: "10 001" }]);
    });

    test("a node value with no space is silently ignored", () => {
      expect(resolveSelectedPrintings(nodes("nospace"))).toEqual([]);
    });
  });

  describe("deduplication", () => {
    test("selecting the same printing node twice produces a single entry", () => {
      const result = resolveSelectedPrintings(nodes("xyz 001", "xyz 001"));
      expect(result).toHaveLength(1);
      expect(result[0]).toEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "001",
      });
    });
  });

  describe("mixed node types", () => {
    test("Unknown combined with printings from multiple expansions", () => {
      const result = resolveSelectedPrintings(
        nodes(Unknown, "xyz 001", "abc 010")
      );
      expect(result).toHaveLength(3);
      expect(result).toContainEqual<Printing>({
        expansionCode: Unknown,
        collectorNumber: Unknown,
      });
      expect(result).toContainEqual<Printing>({
        expansionCode: "xyz",
        collectorNumber: "001",
      });
      expect(result).toContainEqual<Printing>({
        expansionCode: "abc",
        collectorNumber: "010",
      });
    });
  });
});
