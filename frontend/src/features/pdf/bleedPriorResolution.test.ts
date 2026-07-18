import {
  APPROPRIATE_BLEED_TAG_NAME,
  resolveBleedPriors,
} from "@/features/pdf/bleedPriorResolution";
import { APIGetTagConsensus } from "@/store/api";

jest.mock("../../store/api", () => ({
  APIGetTagConsensus: jest.fn(),
}));

const mockAPIGetTagConsensus = APIGetTagConsensus as jest.Mock;

const consensusWithBleedEntry = (netPolarity: number) => ({
  tags: [
    { tagName: APPROPRIATE_BLEED_TAG_NAME, netPolarity, tally: [] },
    { tagName: "Full Art", netPolarity: 0, tally: [] },
  ],
});

describe("resolveBleedPriors", () => {
  beforeEach(() => {
    mockAPIGetTagConsensus.mockReset();
  });

  it("maps a clearly positive netPolarity to 'bleed'", async () => {
    mockAPIGetTagConsensus.mockResolvedValue(consensusWithBleedEntry(0.8));
    const priors = await resolveBleedPriors("http://backend", ["card-1"]);
    expect(priors["card-1"]).toBe("bleed");
  });

  it("maps a clearly negative netPolarity to 'trimmed'", async () => {
    mockAPIGetTagConsensus.mockResolvedValue(consensusWithBleedEntry(-0.6));
    const priors = await resolveBleedPriors("http://backend", ["card-1"]);
    expect(priors["card-1"]).toBe("trimmed");
  });

  it("maps a zero netPolarity to 'unresolved'", async () => {
    mockAPIGetTagConsensus.mockResolvedValue(consensusWithBleedEntry(0));
    const priors = await resolveBleedPriors("http://backend", ["card-1"]);
    expect(priors["card-1"]).toBe("unresolved");
  });

  it("maps a missing appropriate-bleed entry to 'unresolved'", async () => {
    mockAPIGetTagConsensus.mockResolvedValue({
      tags: [{ tagName: "Full Art", netPolarity: 0.9, tally: [] }],
    });
    const priors = await resolveBleedPriors("http://backend", ["card-1"]);
    expect(priors["card-1"]).toBe("unresolved");
  });

  it("degrades a single failed lookup to 'unresolved' without failing the whole batch", async () => {
    mockAPIGetTagConsensus.mockImplementation((_backendURL, identifier) => {
      if (identifier === "card-fails") {
        return Promise.reject(new Error("network blip"));
      }
      return Promise.resolve(consensusWithBleedEntry(0.5));
    });
    const priors = await resolveBleedPriors("http://backend", [
      "card-fails",
      "card-ok",
    ]);
    expect(priors["card-fails"]).toBe("unresolved");
    expect(priors["card-ok"]).toBe("bleed");
  });

  it("deduplicates repeated identifiers, calling the API once per unique card", async () => {
    mockAPIGetTagConsensus.mockResolvedValue(consensusWithBleedEntry(0.5));
    const priors = await resolveBleedPriors("http://backend", [
      "card-1",
      "card-1",
      "card-2",
    ]);
    expect(Object.keys(priors).sort()).toEqual(["card-1", "card-2"]);
    expect(mockAPIGetTagConsensus).toHaveBeenCalledTimes(2);
  });

  it("resolves an empty identifier list to an empty map without calling the API", async () => {
    const priors = await resolveBleedPriors("http://backend", []);
    expect(priors).toEqual({});
    expect(mockAPIGetTagConsensus).not.toHaveBeenCalled();
  });
});
