# Google Drive connect

Two separate "connect a source" features live under `Configure Sources`
(`BackendConfig.tsx`), both client-side, end-user-facing (distinct from the
backend `LOCAL_FILE` source type — see [[local-file-source.md]], which is a
catalog-admin feature):

- **Google Drive** (`GoogleDriveBackendConfig.tsx`) — OAuth via
  `@googleworkspace/drive-picker-react`, client-side search over your own
  Drive.
- **Local Folder** (`LocalFolderBackendConfig.tsx`) — browser File System
  Access API, client-side search over a folder on disk.

## Google Drive picker — render-gate bug, fixed

`isGoogleDriveAppConfigured` in `BackendConfig.tsx` gates the whole section
on `NEXT_PUBLIC_GOOGLE_DRIVE_CLIENT_ID`/`NEXT_PUBLIC_GOOGLE_DRIVE_APP_ID`
being non-empty at build time. `build-frontend.yml`/`web-ci.yml` passed
these through from repo secrets, but neither is the actual production
deployer — `deploy-frontend.yml` is (see [[../infrastructure.md]]) — and it
never set these two env vars, so the section was silently absent from the
live site in every browser. Fixed by adding both env vars to
`deploy-frontend.yml`'s build step.

That fix alone wasn't sufficient — the section still didn't render even
after deploying it, because the underlying repo secrets were themselves
unset (same "placeholder-unset" pattern as the image-cdn Google secrets).
Required a real Google Cloud Console OAuth 2.0 Web application client
(Picker API + Drive API enabled, `https://proxyprints.ca` as an authorized
JavaScript origin) — the user's own Google Cloud account, not something
fixable from this machine. Once real secrets were populated and the
workflow re-run, the "Google Drive" section rendered correctly in Configure
Sources.

**Verified up to, but not past, Google's own sign-in page**: clicking
"Choose Resources" produces a well-formed Google OAuth request — correct
client ID (project number matches the app ID), correct `origin`, correct
`drive.metadata.readonly` scope, zero console errors on load or click.
Everything on our side (client ID, app ID, origin allowlist, scope) is
confirmed wired correctly up to the point Google's sign-in page takes over.
**A real login completion has never been tested** — that needs a human
with a Google account, not something an unattended session can drive.

Ruled out, with a synthetic repro in both Firefox and Chromium: Firefox
popup-blocking timing is **not** the cause of any perceived flakiness here
(the picker library's `requestAccessToken()` lazily awaits a script inject
before opening the OAuth popup — a plausible-looking async gap between
click and popup — but real Firefox tolerated that gap fine). Don't
re-chase that theory without new evidence.

## Local Folder — working as designed, Chrome-only

Firefox has never implemented `showDirectoryPicker` (File System Access
API) — a browser-vendor gap, not fixable in this codebase. The existing
try/catch already handles this correctly: a clear "Your browser doesn't
support opening local folders" toast, and the UI already says Chrome-only.
A `<input type="file" webkitdirectory>` fallback exists in theory (Firefox
supports it) but is **read-only** — no `FileSystemDirectoryHandle`, so
downloads-into-this-folder (a core part of what the feature promises)
could never work in Firefox regardless. Would touch ~7 files for a
permanently-degraded result. Decision: leave Chrome-only rather than build
the partial fallback — re-raise this tradeoff explicitly if asked again
rather than assuming the answer has changed. The directory handle also
isn't persisted anywhere (no IndexedDB/localStorage) — only held in the
worker's memory for the current tab session, so a page reload always
requires re-choosing the folder even in Chrome; that's expected.

## Save PDF directly to Google Drive

A `drive.file` write-scope upload feature on the PDF tab, built after the
user added that scope to the OAuth consent screen (the existing Drive
picker token is `drive.metadata.readonly` and cannot upload — a
proposal to reuse it was wrong on that premise).

- `frontend/src/features/googleDrive/googleDriveAuth.ts` —
  `requestGoogleDriveWriteToken(clientId)`, a minimal standalone token
  requester using Google Identity Services
  (`google.accounts.oauth2.initTokenClient`) scoped to `drive.file`,
  independent of the Picker's read-only token. The GSI script
  (`accounts.google.com/gsi/client`) is injected lazily on first call —
  never on page load — a real zero-telemetry-posture property, not just
  perf. A real occurrence on the owner's own device (privacy
  browser/ad-tracker blockers routinely block `accounts.google.com`)
  surfaced as the raw `"Failed to load https://accounts.google.com/gsi/
  client"` string in the save-to-Drive failure toast; `injectScript`'s
  `onerror` now rejects with a dedicated `GSIScriptLoadError` carrying an
  actionable message (privacy browser/ad blocker likely cause, allow the
  domain and retry, or use the plain PDF download instead) instead of
  that raw URL bubbling up verbatim through `useSaveToDrivePDF`'s catch
  handler.
- `GoogleDriveService.uploadFile()` — multipart POST to the Drive v3 upload
  endpoint, separate from the existing `executeCall` (that method's
  retry/semaphore machinery is tailored to GET-based browsing endpoints;
  upload is a one-shot POST with a FormData body).
- `frontend/src/features/googleDrive/googleDriveConfig.ts` — extracted
  `isGoogleDriveAppConfigured()` out of `BackendConfig.tsx` so
  `PDFGenerator.tsx` can reuse the same env-var gate.
- `PDFGenerator.tsx` — "Save PDF to Google Drive" button below "Generate
  PDF" (only rendered when configured), requests a fresh write-scoped
  token on each click (not cached across clicks), renders the PDF via the
  same `pdfRenderService.renderPDF` the download path uses, uploads it as
  `cards.pdf`. Deliberately does **not** route through the navbar's
  download-manager queue/tray — that queue's semantics are for local
  downloads, not uploads; has its own local `isSavingToDrive` loading state
  instead, mirroring the existing `isDownloading` pattern.

**Verified only that the client-side request pipeline is wired correctly**
— a fake client ID correctly produced Google's `invalid_client` rejection,
confirming the flow reaches Google's server as expected. **Never verified
against a real Drive account**: no real `drive.file` OAuth completion, no
real upload, no confirmation a file actually lands in Drive.

## Key files

- `frontend/src/features/backend/GoogleDriveBackendConfig.tsx`,
  `LocalFolderBackendConfig.tsx`, `BackendConfig.tsx`
- `frontend/src/features/googleDrive/` (`googleDriveAuth.ts`,
  `googleDriveConfig.ts`, `GoogleDriveService.ts`)
- `frontend/src/features/pdf/PDFGenerator.tsx`

## Known gaps

- Google Drive picker: real OAuth login completion untested.
- Save-to-Drive: real upload against a live account untested.
- Local Folder: permanently Chrome-only by design, not a bug to fix.
