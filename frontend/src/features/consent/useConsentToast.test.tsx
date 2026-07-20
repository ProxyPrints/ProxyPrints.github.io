import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { resetConsentDecisionSessionFlag } from "@/features/consent/consentToast";
import { useConsentToast } from "@/features/consent/useConsentToast";

// Harness pattern mirrors cryptoSession.test.tsx's own precedent for testing a hook's stateful
// behaviour through the real component tree rather than a bare renderHook call, since
// requestConsent's resolution depends on the ConsentToast element it returns actually being
// mounted and clicked.
function Harness({ permissionKey }: { permissionKey: string }) {
  const { element, requestConsent } = useConsentToast();
  const [result, setResult] = React.useState<string>("pending");

  const ask = () => {
    setResult("pending");
    requestConsent({
      key: permissionKey,
      title: "Help identify this printing?",
      message: "We'd like to check your card image against known printings.",
    }).then((accepted) => setResult(accepted ? "accepted" : "declined"));
  };

  return (
    <div>
      <span data-testid="result">{result}</span>
      <button data-testid="ask" onClick={ask}>
        Ask
      </button>
      {element}
    </div>
  );
}

describe("useConsentToast", () => {
  afterEach(() => {
    resetConsentDecisionSessionFlag("phash-contribution");
    resetConsentDecisionSessionFlag("some-other-permission");
  });

  test("shows the toast with the caller-supplied request and resolves true on accept", async () => {
    render(<Harness permissionKey="phash-contribution" />);

    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ask"));

    const toast = await screen.findByTestId("consent-toast");
    expect(toast).toHaveTextContent("Help identify this printing?");

    fireEvent.click(screen.getByTestId("consent-toast-accept"));
    expect(await screen.findByText("accepted")).toBeInTheDocument();
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
  });

  test("resolves false on decline", async () => {
    render(<Harness permissionKey="phash-contribution" />);

    fireEvent.click(screen.getByTestId("ask"));
    await screen.findByTestId("consent-toast");
    fireEvent.click(screen.getByTestId("consent-toast-decline"));

    expect(await screen.findByText("declined")).toBeInTheDocument();
  });

  test("does not re-prompt within the same session once a decision is made for that key", async () => {
    render(<Harness permissionKey="phash-contribution" />);

    fireEvent.click(screen.getByTestId("ask"));
    await screen.findByTestId("consent-toast");
    fireEvent.click(screen.getByTestId("consent-toast-accept"));
    await screen.findByText("accepted");

    // Asking again for the SAME key resolves immediately with the remembered decision, no
    // toast shown.
    fireEvent.click(screen.getByTestId("ask"));
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
    expect(await screen.findByText("accepted")).toBeInTheDocument();
  });

  test("a decision for one permission key never affects another (scoped, not global)", async () => {
    render(<Harness permissionKey="some-other-permission" />);

    fireEvent.click(screen.getByTestId("ask"));
    await screen.findByTestId("consent-toast");
    fireEvent.click(screen.getByTestId("consent-toast-decline"));
    await screen.findByText("declined");

    // A separate key with its own request should still prompt fresh.
    render(<Harness permissionKey="phash-contribution" />);
    const askButtons = screen.getAllByTestId("ask");
    fireEvent.click(askButtons[askButtons.length - 1]);
    expect(await screen.findByTestId("consent-toast")).toBeInTheDocument();
  });

  test("dismissing via Escape counts as decline and is remembered for the rest of the session", async () => {
    render(<Harness permissionKey="phash-contribution" />);

    fireEvent.click(screen.getByTestId("ask"));
    await screen.findByTestId("consent-toast");
    fireEvent.keyDown(screen.getByTestId("consent-toast-wrapper"), {
      key: "Escape",
    });
    expect(await screen.findByText("declined")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("ask"));
    expect(screen.queryByTestId("consent-toast")).not.toBeInTheDocument();
    expect(await screen.findByText("declined")).toBeInTheDocument();
  });
});
