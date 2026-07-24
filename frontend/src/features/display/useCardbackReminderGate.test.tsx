/**
 * Cardback flow round (SPEC-cardback-pdfwait.md §C.1, `PKG1a`) - hook-level coverage for
 * `useCardbackReminderGate`, exercised directly (not only indirectly via
 * `PrePrintSaveGate.test.tsx`/an E2E Playwright spec) since it's now composed into TWO
 * independent call sites (`usePrePrintSaveGate`'s own `startPrintFlow`, and `PDFGenerator.tsx`'s
 * classic direct "Generate PDF"/"Save PDF to Google Drive" buttons - see this hook's own module
 * comment) - a single shared unit test is the one place both call sites' shared semantics
 * (dismiss-continues, once-per-session suppression) are verified without duplicating a full E2E
 * flow for each entry point.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { CardType, Project, SlotProjectMembers } from "@/common/types";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { clientSearchService } from "@/features/clientSearch/clientSearchService";
import {
  resetCardbackReminderSuppressionForTests,
  UNSAVED_PROJECT_SUPPRESSION_KEY,
} from "@/features/display/cardbackReminderSuppression";
import { useCardbackReminderGate } from "@/features/display/useCardbackReminderGate";
import { setupStore } from "@/store/store";

const oneMember: SlotProjectMembers = {
  id: "t-0",
  front: {
    query: { query: "my card", cardType: "CARD" as CardType },
    selectedImage: "front-image",
    selected: false,
  },
  back: null,
};

function baseProject(overrides: Partial<Project> = {}): Project {
  return {
    members: [oneMember],
    nextMemberId: 1,
    cardback: null,
    mostRecentlySelectedSlot: null,
    manualOverrides: {},
    cardbackExplicitlySet: false,
    ...overrides,
  };
}

function TestHarness({ project }: { project: Project }) {
  const gate = useCardbackReminderGate();
  const [proceeded, setProceeded] = React.useState(0);
  return (
    <>
      <button onClick={() => gate.guard(() => setProceeded((n) => n + 1))}>
        start print flow
      </button>
      <div data-testid="proceeded-count">{proceeded}</div>
      {gate.element}
    </>
  );
}

function renderHarness(project: Project) {
  const store = setupStore({ project });
  render(
    <Provider store={store}>
      <ClientSearchContextProvider
        value={{
          clientSearchService,
          forceUpdate: () => undefined,
          forceUpdateValue: 0,
        }}
      >
        <TestHarness project={project} />
      </ClientSearchContextProvider>
    </Provider>
  );
}

describe("useCardbackReminderGate (SPEC-cardback-pdfwait.md §C.1)", () => {
  afterEach(() => {
    resetCardbackReminderSuppressionForTests(UNSAVED_PROJECT_SUPPRESSION_KEY);
  });

  test("does not appear at all once a cardback has been explicitly chosen - guard proceeds straight through", async () => {
    const user = userEvent.setup();
    renderHarness(
      baseProject({ cardback: "chosen", cardbackExplicitlySet: true })
    );

    await user.click(screen.getByText("start print flow"));

    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("1");
  });

  test("appears for a project still riding the untouched default cardback, and blocks the guarded action until resolved", async () => {
    const user = userEvent.setup();
    renderHarness(baseProject());

    await user.click(screen.getByText("start print flow"));

    expect(screen.getByTestId("pre-print-cardback-gate")).toBeInTheDocument();
    // Blocked - the guarded action hasn't run yet.
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("0");
  });

  test("'Use current & continue' proceeds and suppresses the gate for the rest of the session (CB1)", async () => {
    const user = userEvent.setup();
    renderHarness(baseProject());

    await user.click(screen.getByText("start print flow"));
    await user.click(screen.getByTestId("cardback-gate-use-current"));

    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("1");

    // A second print attempt in the same session is silent (CB1 - "at most once per session").
    await user.click(screen.getByText("start print flow"));
    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("2");
  });

  test("OWNER AMENDMENT 1 - dismissing the gate (Esc/backdrop/✕, all routed through Modal's onHide) proceeds, it does NOT cancel", async () => {
    const user = userEvent.setup();
    renderHarness(baseProject());

    await user.click(screen.getByText("start print flow"));
    expect(screen.getByTestId("pre-print-cardback-gate")).toBeInTheDocument();

    // The header's own close (X) button - react-bootstrap Modal routes this through onHide,
    // exactly like Esc/backdrop would.
    await user.click(screen.getByLabelText("Close"));

    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    // Dismiss is NOT cancel (Amendment 1 supersedes the spec's own OQ-A recommendation) - the
    // guarded action still ran.
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("1");
  });

  test("'Choose a cardback' opens the project-wide grid selector instead of the reminder, and closing it (with or without a pick) proceeds", async () => {
    const user = userEvent.setup();
    renderHarness(baseProject());

    await user.click(screen.getByText("start print flow"));
    await user.click(screen.getByTestId("cardback-gate-choose"));

    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    expect(screen.getByTestId("cardback-grid-selector")).toBeInTheDocument();
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("0");

    // Closing the grid selector (its own header X) resumes the guarded print/export action -
    // no genuine cancel path exists anywhere in this gate (Amendment 1).
    const grid = screen.getByTestId("cardback-grid-selector");
    await user.click(
      grid.querySelector('button[aria-label="Close"]') as HTMLElement
    );

    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("1");
  });

  test("never fires for an empty project (nothing to print)", async () => {
    const user = userEvent.setup();
    renderHarness(baseProject({ members: [] }));

    await user.click(screen.getByText("start print flow"));

    expect(screen.queryByTestId("pre-print-cardback-gate")).toBeNull();
    expect(screen.getByTestId("proceeded-count")).toHaveTextContent("1");
  });
});
