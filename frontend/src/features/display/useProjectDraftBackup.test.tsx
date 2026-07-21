/**
 * Proposal H ADDENDUM D9(1)/F1 - useProjectDraftBackup.ts's own test suite. Exercises the hook
 * through a real component tree (Harness) against a real redux store (setupStore), mirroring
 * SavedDeckPanel.test.tsx/useConsentToast.test.tsx's own precedent for testing a stateful hook
 * this way rather than a bare renderHook call - restoreDraft/dismissRestoreDraft both need to be
 * driven by real clicks against the hook's own returned callbacks.
 */
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, projectSelectedImage1 } from "@/common/test-constants";
import {
  clearStoredProjectDraftForTests,
  useProjectDraftBackup,
} from "@/features/display/useProjectDraftBackup";
import { loadProject } from "@/store/slices/projectSlice";
import { selectToastsNotifications } from "@/store/slices/toastsSlice";
import { setupStore } from "@/store/store";

function Harness() {
  const backup = useProjectDraftBackup();
  return (
    <div>
      <span data-testid="has-backed-up">
        {String(backup.hasBackedUpThisSession)}
      </span>
      <span data-testid="restorable">
        {backup.restorableDraft != null
          ? JSON.stringify(backup.restorableDraft)
          : "none"}
      </span>
      <button data-testid="flush" onClick={backup.flushDraftNow}>
        flush
      </button>
      <button data-testid="restore" onClick={backup.restoreDraft}>
        restore
      </button>
      <button data-testid="dismiss" onClick={backup.dismissRestoreDraft}>
        dismiss
      </button>
      <button
        data-testid="notify-pre-print"
        onClick={backup.notifyPromoteDraftPrePrint}
      >
        notify
      </button>
    </div>
  );
}

function renderHarness(preloadedState: Parameters<typeof setupStore>[0]) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <Harness />
    </Provider>
  );
  return store;
}

const DRAFT_STORAGE_KEY = "mpc-autofill-project-draft";

afterEach(() => {
  clearStoredProjectDraftForTests();
});

test("does not write a draft while the project is empty", () => {
  renderHarness({ backend: localBackend });

  fireEvent.click(screen.getByTestId("flush"));

  expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull();
  expect(screen.getByTestId("has-backed-up")).toHaveTextContent("false");
});

test("flushDraftNow writes indexes/settings only, never image pixels, and flips hasBackedUpThisSession", () => {
  renderHarness({ backend: localBackend, project: projectSelectedImage1 });

  fireEvent.click(screen.getByTestId("flush"));

  expect(screen.getByTestId("has-backed-up")).toHaveTextContent("true");
  const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
  expect(raw).not.toBeNull();
  const stored = JSON.parse(raw as string);
  expect(stored.draftVersion).toBe(1);
  expect(stored.payload.members).toHaveLength(1);
  expect(stored.payload.members[0].front.query.query).toBe("my search query");
  expect(stored.payload.members[0].front.selectedImage).toBe(
    projectSelectedImage1.members[0].front?.selectedImage
  );
  // Governing premise (CLAUDE.md "we index, we do not store images") - the serialized draft
  // never contains anything resembling image byte data, only the identifier/query index.
  expect(raw).not.toMatch(/data:image/);
});

test("the debounced auto-write eventually persists without an explicit flush", async () => {
  renderHarness({ backend: localBackend, project: projectSelectedImage1 });

  expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull();

  await waitFor(
    () => expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).not.toBeNull(),
    { timeout: 2_000 }
  );
});

test("a restorable draft from a prior session surfaces once the project is empty again", async () => {
  // First "session": a populated project backs itself up.
  renderHarness({ backend: localBackend, project: projectSelectedImage1 });
  fireEvent.click(screen.getByTestId("flush"));
  expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).not.toBeNull();

  // Second "session": a fresh mount against an EMPTY project (localStorage persists across
  // mounts in a real browser, and jsdom's own localStorage is shared across renders in this
  // same test file the same way).
  renderHarness({ backend: localBackend });

  await waitFor(() =>
    expect(screen.getAllByTestId("restorable").at(-1)).not.toHaveTextContent(
      "none"
    )
  );
  expect(screen.getAllByTestId("restorable").at(-1)).toHaveTextContent(
    '"memberCount":1'
  );
});

test("restoreDraft rehydrates the project from the stored draft", async () => {
  renderHarness({ backend: localBackend, project: projectSelectedImage1 });
  fireEvent.click(screen.getByTestId("flush"));

  const store = renderHarness({ backend: localBackend });
  await waitFor(() =>
    expect(screen.getAllByTestId("restorable").at(-1)).not.toHaveTextContent(
      "none"
    )
  );

  fireEvent.click(screen.getAllByTestId("restore").at(-1)!);

  expect(store.getState().project.members).toHaveLength(1);
  expect(store.getState().project.members[0].front?.selectedImage).toBe(
    projectSelectedImage1.members[0].front?.selectedImage
  );
  await waitFor(() =>
    expect(screen.getAllByTestId("restorable").at(-1)).toHaveTextContent("none")
  );
});

test("dismissRestoreDraft hides the banner without deleting the underlying draft", async () => {
  renderHarness({ backend: localBackend, project: projectSelectedImage1 });
  fireEvent.click(screen.getByTestId("flush"));

  renderHarness({ backend: localBackend });
  await waitFor(() =>
    expect(screen.getAllByTestId("restorable").at(-1)).not.toHaveTextContent(
      "none"
    )
  );

  fireEvent.click(screen.getAllByTestId("dismiss").at(-1)!);

  await waitFor(() =>
    expect(screen.getAllByTestId("restorable").at(-1)).toHaveTextContent("none")
  );
  // The safety net itself is untouched - only this session's banner was hidden.
  expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).not.toBeNull();
});

test("the post-import promotion nudge fires once, the moment the project flips from empty to populated", async () => {
  const store = renderHarness({ backend: localBackend });

  expect(
    Object.values(selectToastsNotifications(store.getState()))
  ).toHaveLength(0);

  act(() => {
    store.dispatch(loadProject(projectSelectedImage1));
  });

  await waitFor(() => {
    const notifications = selectToastsNotifications(store.getState());
    expect(
      Object.values(notifications).some((n) => n.name === "Backed up locally")
    ).toBe(true);
  });
});

test("notifyPromoteDraftPrePrint dispatches the same promotion toast on demand", async () => {
  const store = renderHarness({
    backend: localBackend,
    project: projectSelectedImage1,
  });

  fireEvent.click(screen.getByTestId("notify-pre-print"));

  await waitFor(() => {
    const notifications = selectToastsNotifications(store.getState());
    expect(
      Object.values(notifications).some((n) => n.name === "Backed up locally")
    ).toBe(true);
  });
});
