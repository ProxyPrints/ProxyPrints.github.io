/**
 * Requests an OAuth access token scoped for creating/uploading files in the
 * user's Drive, independent of the read-only picker flow in
 * GoogleDrivePicker.tsx (which is scoped to drive.metadata.readonly and
 * can't be reused for uploads). Mirrors the token-request half of
 * @googleworkspace/drive-picker-element's internals, minus the picker UI
 * we don't need for a plain upload.
 */

const GSI_URL = "https://accounts.google.com/gsi/client";

// The script tag itself loads fine or fails outright - there's no partial/timeout state to
// handle - so a browser blocking accounts.google.com (privacy browsers, ad/tracker blockers;
// a real occurrence, not hypothetical) surfaces here as a plain script `error` event, with no
// detail beyond "it didn't load." This custom error exists so that specific, common cause gets
// a specific, actionable message instead of the raw "Failed to load https://accounts.google.com/
// gsi/client" URL string bubbling all the way up to the save-to-Drive failure toast verbatim.
export class GSIScriptLoadError extends Error {
  constructor() {
    super(
      "Couldn't reach Google's sign-in script, so Drive can't be authorized. This usually " +
        "means a privacy browser or an ad/tracker blocker is blocking accounts.google.com - " +
        "allow that domain for this site and try again, or download your PDF instead of " +
        "saving it to Drive."
    );
    this.name = "GSIScriptLoadError";
  }
}

const injectScript = (src: string): Promise<void> =>
  new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new GSIScriptLoadError());
    document.head.appendChild(script);
  });

interface GoogleTokenResponse {
  access_token: string;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        oauth2: {
          initTokenClient: (config: {
            client_id: string;
            scope: string;
            callback: (response: GoogleTokenResponse) => void;
            error_callback: (error: unknown) => void;
          }) => { requestAccessToken: () => void };
        };
      };
    };
  }
}

export const requestGoogleDriveWriteToken = async (
  clientId: string
): Promise<string> => {
  if (window.google?.accounts?.oauth2 === undefined) {
    await injectScript(GSI_URL);
  }
  return new Promise<string>((resolve, reject) => {
    const client = window.google!.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: "https://www.googleapis.com/auth/drive.file",
      callback: (response) => resolve(response.access_token),
      error_callback: (error) =>
        reject(error instanceof Error ? error : new Error(String(error))),
    });
    client.requestAccessToken();
  });
};
