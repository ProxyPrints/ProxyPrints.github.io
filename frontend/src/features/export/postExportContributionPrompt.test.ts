import { FileDownload } from "@/common/types";
import {
  hasShownPostExportContributionPromptThisSession,
  markPostExportContributionPromptShown,
  resetPostExportContributionPromptSessionFlag,
  shouldShowPostExportContributionPrompt,
  wasMostRecentCardsPdfDownloadSuccessful,
} from "@/features/export/postExportContributionPrompt";

describe("shouldShowPostExportContributionPrompt", () => {
  test("shows when nothing has been shown yet this session", () => {
    expect(shouldShowPostExportContributionPrompt(false)).toBe(true);
  });

  test("does not show again once already shown this session", () => {
    expect(shouldShowPostExportContributionPrompt(true)).toBe(false);
  });
});

describe("session flag (sessionStorage-backed)", () => {
  afterEach(() => {
    resetPostExportContributionPromptSessionFlag();
  });

  test("starts unset", () => {
    expect(hasShownPostExportContributionPromptThisSession()).toBe(false);
  });

  test("persists across reads once marked", () => {
    markPostExportContributionPromptShown();
    expect(hasShownPostExportContributionPromptThisSession()).toBe(true);
    // A second read (simulating a re-render, not a new tab) still sees it - this is the whole
    // point of sessionStorage over an in-memory-only flag.
    expect(hasShownPostExportContributionPromptThisSession()).toBe(true);
  });

  test("resets cleanly (test-only helper, mirrors a fresh tab)", () => {
    markPostExportContributionPromptShown();
    resetPostExportContributionPromptSessionFlag();
    expect(hasShownPostExportContributionPromptThisSession()).toBe(false);
  });
});

const cardsPdfDownload = (
  overrides: Partial<FileDownload> = {}
): FileDownload => ({
  name: "cards.pdf",
  type: "pdf",
  enqueuedTimestamp: new Date(0).toString(),
  startedTimestamp: new Date(0).toString(),
  completedTimestamp: new Date(0).toString(),
  status: "success",
  ...overrides,
});

describe("wasMostRecentCardsPdfDownloadSuccessful", () => {
  test("false when there are no downloads at all", () => {
    expect(wasMostRecentCardsPdfDownloadSuccessful([])).toBe(false);
  });

  test("false when no cards.pdf download has completed yet (still in flight)", () => {
    const inFlight = cardsPdfDownload({
      status: undefined,
      completedTimestamp: undefined,
    });
    expect(wasMostRecentCardsPdfDownloadSuccessful([inFlight])).toBe(false);
  });

  test("true when the only cards.pdf download succeeded", () => {
    expect(wasMostRecentCardsPdfDownloadSuccessful([cardsPdfDownload()])).toBe(
      true
    );
  });

  test("false when the only cards.pdf download failed (e.g. cancelled on image failure)", () => {
    expect(
      wasMostRecentCardsPdfDownloadSuccessful([
        cardsPdfDownload({ status: "failed" }),
      ])
    ).toBe(false);
  });

  test("ignores downloads with a different name (e.g. an SCM export or another file type)", () => {
    const otherDownload = cardsPdfDownload({
      name: "cards.xml",
      status: "success",
    });
    expect(wasMostRecentCardsPdfDownloadSuccessful([otherDownload])).toBe(
      false
    );
  });

  // The core "don't fire on a stale success" correctness requirement: a user who exported
  // successfully earlier, then exported again and that later attempt was cancelled/failed,
  // must NOT have the prompt fire off the earlier stale success.
  test("keys off the MOST RECENT completed cards.pdf download, not just any success in the list", () => {
    const earlierSuccess = cardsPdfDownload({
      completedTimestamp: new Date(1_000).toString(),
      status: "success",
    });
    const laterFailure = cardsPdfDownload({
      completedTimestamp: new Date(2_000).toString(),
      status: "failed",
    });
    expect(
      wasMostRecentCardsPdfDownloadSuccessful([earlierSuccess, laterFailure])
    ).toBe(false);
  });

  test("keys off the most recent even when the success is the later entry", () => {
    const earlierFailure = cardsPdfDownload({
      completedTimestamp: new Date(1_000).toString(),
      status: "failed",
    });
    const laterSuccess = cardsPdfDownload({
      completedTimestamp: new Date(2_000).toString(),
      status: "success",
    });
    expect(
      wasMostRecentCardsPdfDownloadSuccessful([earlierFailure, laterSuccess])
    ).toBe(true);
  });
});
