import {
  hasSuppressedCardbackReminderThisSession,
  resetCardbackReminderSuppressionForTests,
  suppressCardbackReminderThisSession,
  UNSAVED_PROJECT_SUPPRESSION_KEY,
} from "@/features/display/cardbackReminderSuppression";

describe("cardback reminder gate suppression (sessionStorage-backed, per-project)", () => {
  afterEach(() => {
    resetCardbackReminderSuppressionForTests(UNSAVED_PROJECT_SUPPRESSION_KEY);
    resetCardbackReminderSuppressionForTests("saved-deck-key-1");
    resetCardbackReminderSuppressionForTests("saved-deck-key-2");
  });

  test("starts unset for a fresh project", () => {
    expect(
      hasSuppressedCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY)
    ).toBe(false);
  });

  test("persists across reads once suppressed (CB1 - once per session)", () => {
    suppressCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY);
    expect(
      hasSuppressedCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY)
    ).toBe(true);
    expect(
      hasSuppressedCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY)
    ).toBe(true);
  });

  test("is scoped PER PROJECT - suppressing one project's key leaves another's untouched", () => {
    suppressCardbackReminderThisSession("saved-deck-key-1");
    expect(hasSuppressedCardbackReminderThisSession("saved-deck-key-1")).toBe(
      true
    );
    expect(hasSuppressedCardbackReminderThisSession("saved-deck-key-2")).toBe(
      false
    );
  });

  test("resets cleanly (test-only helper, mirrors a fresh tab)", () => {
    suppressCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY);
    resetCardbackReminderSuppressionForTests(UNSAVED_PROJECT_SUPPRESSION_KEY);
    expect(
      hasSuppressedCardbackReminderThisSession(UNSAVED_PROJECT_SUPPRESSION_KEY)
    ).toBe(false);
  });
});
