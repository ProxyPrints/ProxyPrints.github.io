import { errorToNotification, isRateLimited } from "@/common/apiErrors";

const FALLBACK = { name: "Vote failed", message: "Generic fallback message." };

describe("isRateLimited", () => {
  it("is true for a shaped 429 error", () => {
    expect(
      isRateLimited({ name: "Rate limited", message: "slow down", status: 429 })
    ).toBe(true);
  });

  it("is false for a shaped non-429 error", () => {
    expect(
      isRateLimited({ name: "Bad Request", message: "oops", status: 400 })
    ).toBe(false);
  });

  it("is false for an error with no status at all", () => {
    expect(isRateLimited({ name: "Vote failed", message: "oops" })).toBe(false);
  });

  it("is false for a message-less network failure", () => {
    expect(isRateLimited(new TypeError("Failed to fetch"))).toBe(false);
  });

  it("is false for a non-object thrown value", () => {
    expect(isRateLimited("some string")).toBe(false);
    expect(isRateLimited(null)).toBe(false);
    expect(isRateLimited(undefined)).toBe(false);
  });
});

describe("errorToNotification", () => {
  it("surfaces the backend's own name/message for a shaped error", () => {
    expect(
      errorToNotification(
        {
          name: "Rate limited",
          message: "Too many tag vote submissions - please slow down.",
        },
        FALLBACK
      )
    ).toStrictEqual({
      name: "Rate limited",
      message: "Too many tag vote submissions - please slow down.",
      level: "error",
    });
  });

  it("falls back to the generic copy for a message-less network failure", () => {
    expect(
      errorToNotification(new TypeError("Failed to fetch"), FALLBACK)
    ).toStrictEqual({
      name: FALLBACK.name,
      message: FALLBACK.message,
      level: "error",
    });
  });

  it("falls back to the generic copy when the error shape has null name/message", () => {
    expect(
      errorToNotification({ name: null, message: null }, FALLBACK)
    ).toStrictEqual({
      name: FALLBACK.name,
      message: FALLBACK.message,
      level: "error",
    });
  });

  it("always sets level to error regardless of the shaped error's own fields", () => {
    const result = errorToNotification(
      { name: "X", message: "Y", status: 500 },
      FALLBACK
    );
    expect(result.level).toBe("error");
  });
});
