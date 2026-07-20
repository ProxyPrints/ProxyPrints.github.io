import {
  getStoredConsentDecision,
  resetConsentDecisionSessionFlag,
  shouldPromptForConsent,
  storeConsentDecision,
} from "@/features/consent/consentToast";

describe("shouldPromptForConsent", () => {
  test("prompts when nothing has been decided yet", () => {
    expect(shouldPromptForConsent(null)).toBe(true);
  });

  test("does not prompt again once accepted", () => {
    expect(shouldPromptForConsent("accepted")).toBe(false);
  });

  test("does not prompt again once declined", () => {
    expect(shouldPromptForConsent("declined")).toBe(false);
  });
});

describe("stored decision (sessionStorage-backed, scoped per permission key)", () => {
  afterEach(() => {
    resetConsentDecisionSessionFlag("key-a");
    resetConsentDecisionSessionFlag("key-b");
  });

  test("starts unset", () => {
    expect(getStoredConsentDecision("key-a")).toBeNull();
  });

  test("persists an accepted decision across reads", () => {
    storeConsentDecision("key-a", "accepted");
    expect(getStoredConsentDecision("key-a")).toBe("accepted");
    // A second read (simulating a re-render, not a new tab) still sees it.
    expect(getStoredConsentDecision("key-a")).toBe("accepted");
  });

  test("persists a declined decision across reads", () => {
    storeConsentDecision("key-a", "declined");
    expect(getStoredConsentDecision("key-a")).toBe("declined");
  });

  test("decisions are scoped per permission key, not global - deciding one key never affects another", () => {
    storeConsentDecision("key-a", "declined");
    expect(getStoredConsentDecision("key-b")).toBeNull();

    storeConsentDecision("key-b", "accepted");
    expect(getStoredConsentDecision("key-a")).toBe("declined");
    expect(getStoredConsentDecision("key-b")).toBe("accepted");
  });

  test("resets cleanly (test-only helper, mirrors a fresh tab)", () => {
    storeConsentDecision("key-a", "accepted");
    resetConsentDecisionSessionFlag("key-a");
    expect(getStoredConsentDecision("key-a")).toBeNull();
  });
});
