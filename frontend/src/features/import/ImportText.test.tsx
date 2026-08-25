import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, localBackendURL } from "@/common/test-constants";
import { defaultHandlers, dfcPairsServerError } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { ImportText } from "./ImportText";

function buildRoute(path: string): string {
  return `${localBackendURL}/${path}`;
}

const dfcPairsPending = http.get(buildRoute("2/DFCPairs/"), async () => {
  await delay("infinite");
  return HttpResponse.json({ dfcPairs: {} });
});
const dfcPairsMatchingDelver = http.get(buildRoute("2/DFCPairs/"), () =>
  HttpResponse.json({
    dfcPairs: { "Delver of Secrets": "Insectile Aberration" },
  })
);
const dfcPairsNoResults = http.get(buildRoute("2/DFCPairs/"), () =>
  HttpResponse.json({ dfcPairs: {} })
);

function renderWithStore() {
  const store = setupStore({ backend: localBackend });
  render(
    <Provider store={store}>
      <ImportText />
    </Provider>
  );
  return store;
}

function submitText(text: string) {
  fireEvent.change(screen.getByLabelText("import-text"), {
    target: { value: text },
  });
  // Submits the form directly, bypassing the button's `disabled` attribute - this is what
  // the Ctrl+Enter shortcut's `form.requestSubmit()` does, so it exercises the guard inside
  // `handleSubmit` itself rather than only the Submit button's disabled state.
  fireEvent.submit(
    screen.getByLabelText("import-text-submit").closest("form")!
  );
}

describe("ImportText - DFC pairs readiness", () => {
  it("blocks submission while the DFC pairs fetch is in flight", async () => {
    server.use(dfcPairsPending, ...defaultHandlers);
    const store = renderWithStore();

    expect(screen.getByLabelText("import-text-submit")).toBeDisabled();
    submitText("Fire // Ice");
    expect(store.getState().project.members).toHaveLength(0);
  });

  it("blocks submission and surfaces a failure message when the fetch errors", async () => {
    server.use(dfcPairsServerError, ...defaultHandlers);
    const store = renderWithStore();

    await waitFor(() =>
      expect(
        screen.getByLabelText("import-text-discriminators-failed")
      ).toBeDefined()
    );
    expect(screen.getByLabelText("import-text-submit")).toBeDisabled();
    submitText("Fire // Ice");
    expect(store.getState().project.members).toHaveLength(0);
  });

  // The parser no longer decides split-vs-directive itself (see processing.ts and
  // listenerMiddleware.test.ts, which cover the layout-based back-query suppression once a
  // front query resolves): both a split card's own compound name and a genuine front/back
  // directive parse identically at submit time, as two independent queries.
  it("parses a compound-named line as two independent front/back queries at submit time", async () => {
    server.use(dfcPairsNoResults, ...defaultHandlers);
    const store = renderWithStore();

    await waitFor(() =>
      expect(screen.getByLabelText("import-text-submit")).not.toBeDisabled()
    );
    submitText("Fire // Ice");

    const members = store.getState().project.members;
    expect(members).toHaveLength(1);
    expect(members[0].front?.query.query).toBe("fire");
    expect(members[0].back?.query.query).toBe("ice");
  });

  it("resolves the back face of a real transform card (Delver of Secrets // Insectile Aberration, layout=transform) once DFC pairs have loaded", async () => {
    server.use(dfcPairsMatchingDelver, ...defaultHandlers);
    const store = renderWithStore();

    await waitFor(() =>
      expect(screen.getByLabelText("import-text-submit")).not.toBeDisabled()
    );
    submitText("Delver of Secrets");

    const members = store.getState().project.members;
    expect(members).toHaveLength(1);
    expect(members[0].front?.query.query).toBe("delver of secrets");
    expect(members[0].back?.query.query).toBe("insectile aberration");
  });
});
