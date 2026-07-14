import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { cardDocument1, localBackend } from "@/common/test-constants";
import {
  reportCardRateLimited,
  reportCardSuccess,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { ReportCardPanel } from "./ReportCardPanel";

// minimal local render helper - the repo has no shared RTL store wrapper (Playwright is the
// primary UI-test harness); this is deliberately just enough store for the component's
// backendURL selector and toast dispatch
function renderWithStore() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <ReportCardPanel cardDocument={cardDocument1} />
    </Provider>
  );
  return store;
}

describe("ReportCardPanel", () => {
  it("expands the flag button into all five reason chips", () => {
    renderWithStore();
    fireEvent.click(screen.getByTestId("report-card-button"));
    for (const label of [
      "NSFW",
      "Low quality",
      "Wrong card info",
      "Broken image",
      "Other…",
    ]) {
      expect(screen.getByText(label)).toBeDefined();
    }
  });

  it("submits a chip reason and collapses into a thank-you line", async () => {
    server.use(reportCardSuccess);
    renderWithStore();
    fireEvent.click(screen.getByTestId("report-card-button"));
    fireEvent.click(screen.getByTestId("report-chip-nsfw"));
    await waitFor(() =>
      expect(screen.getByTestId("report-card-thanks")).toBeDefined()
    );
    expect(screen.queryByTestId("report-card-panel")).toBeNull();
  });

  it("Other reveals a bounded textarea and disables submit until text is entered", () => {
    renderWithStore();
    fireEvent.click(screen.getByTestId("report-card-button"));
    fireEvent.click(screen.getByTestId("report-chip-other"));
    const textarea = screen.getByTestId("report-other-text");
    expect(textarea.getAttribute("maxlength")).toBe("280");
    const submit = screen.getByTestId(
      "report-submit-other"
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(textarea, { target: { value: "something is wrong" } });
    expect(submit.disabled).toBe(false);
  });

  it("surfaces the rate limit as a warning toast and keeps the panel open", async () => {
    server.use(reportCardRateLimited);
    const store = renderWithStore();
    fireEvent.click(screen.getByTestId("report-card-button"));
    fireEvent.click(screen.getByTestId("report-chip-nsfw"));
    await waitFor(() => {
      const notifications = Object.values(store.getState().toasts.notifications);
      expect(notifications).toHaveLength(1);
      expect(notifications[0].level).toBe("warning");
      expect(notifications[0].name).toBe("Report limit reached");
    });
    expect(screen.queryByTestId("report-card-thanks")).toBeNull();
    expect(screen.getByTestId("report-card-panel")).toBeDefined();
  });
});
