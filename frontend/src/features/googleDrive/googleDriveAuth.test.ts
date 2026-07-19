import {
  GSIScriptLoadError,
  requestGoogleDriveWriteToken,
} from "@/features/googleDrive/googleDriveAuth";

// The real GSI script defines `window.google.accounts.oauth2` as a side effect of loading -
// these tests fake that side effect (or its absence) via the injected <script> tag's
// load/error events, matching how a browser genuinely blocking the request behaves.
const GSI_URL = "https://accounts.google.com/gsi/client";

const flushScriptEvent = (kind: "load" | "error") => {
  const script = document.querySelector<HTMLScriptElement>(
    `script[src="${GSI_URL}"]`
  );
  expect(script).not.toBeNull();
  if (kind === "load") {
    window.google = {
      accounts: {
        oauth2: {
          initTokenClient: jest.fn().mockReturnValue({
            requestAccessToken: () => {
              const config = (
                window.google!.accounts.oauth2.initTokenClient as jest.Mock
              ).mock.calls[0][0];
              config.callback({ access_token: "fake-token" });
            },
          }),
        },
      },
    };
    script!.onload?.(new Event("load"));
  } else {
    script!.onerror?.(new Event("error"));
  }
};

describe("requestGoogleDriveWriteToken", () => {
  afterEach(() => {
    document
      .querySelectorAll(`script[src="${GSI_URL}"]`)
      .forEach((node) => node.remove());
    delete (window as { google?: unknown }).google;
  });

  it("resolves with the access token once the GSI script loads and the user grants access", async () => {
    const promise = requestGoogleDriveWriteToken("client-id");
    flushScriptEvent("load");
    await expect(promise).resolves.toBe("fake-token");
  });

  it("rejects with a GSIScriptLoadError carrying an actionable message when the GSI script fails to load", async () => {
    const promise = requestGoogleDriveWriteToken("client-id");
    flushScriptEvent("error");
    await expect(promise).rejects.toThrow(GSIScriptLoadError);
    await expect(promise).rejects.toThrow(/privacy browser|ad\/tracker/);
  });
});
