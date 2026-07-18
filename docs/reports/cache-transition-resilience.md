As of: 2026-07-18
Task: Cache-transition resilience investigation (post-deploy stale-bundle symptom)
Branch: `claude/cache-transition-resilience` (based on `master`, orthogonal to the Proposal B stack)

## Symptom investigated

Post-deploy, a returning browser with a stale cached bundle showed "No Server Configured" (this
app's actual `NoBackendDefault` "remote" case title - the closest literal text to the user's
paraphrase "no source server found") until a hard refresh; fresh sessions were fine.

## Findings

### (a) Stale-HTML-references-purged-chunks window: real, and was completely unhandled

Confirmed via code search - there was no `ChunkLoadError`/chunk-failure handling anywhere in the
frontend (`_app.tsx`, `_error.tsx`, `Layout.tsx`, no global `window.onerror`/`unhandledrejection`
listener, no `router.events.on("routeChangeError", ...)`). This app is a Next.js **static
export** (`next.config.js`: `output: "export"`) deployed to **GitHub Pages**
(`.github/workflows/deploy-frontend.yml`) - there's no server, so a new deploy simply overwrites
`_next/static/...` in place; GitHub Pages doesn't version old build artifacts. Multiple real pages
exist (`index`, `editor`, `new`, `explore`, `contributions`, `whatsthat`, `about`,
`printingQueue`), navigated between via `next/link` (`Navbar.tsx`) - genuine client-side,
webpack-chunk-loading transitions, not full page loads. A browser holding an already-loaded shell
from before a deploy (or one that revisits a cached `index.html` referencing old, now-deleted
chunk hashes) hits a 404 on the next chunk fetch - Next.js's webpack runtime throws this as
`ChunkLoadError`, and with nothing catching it, the failed transition just leaves whatever
state was already on screen (matches "stuck until hard refresh" exactly - a hard refresh forces a
fresh document fetch with correct chunk references, not a code fix).

**Fix, shipped**: `frontend/src/common/chunkErrorRecovery.ts` (pure `isChunkLoadError`/
`shouldAttemptReload`/`reloadOnceForChunkError`) + `frontend/src/common/useChunkErrorRecovery.ts`
(the React hook wiring it to real browser events), mounted once in `Layout.tsx` alongside the
existing app-init effect. Listens for:
- `window.addEventListener("error", ...)` and `("unhandledrejection", ...)` - catches a chunk
  failure however it surfaces (thrown synchronously or as a rejected dynamic `import()`).
- `router.events.on("routeChangeError", ...)` - Next.js's own client-side-navigation error event
  (skips `err.cancelled`, which fires for a normal superseded navigation, not a real failure).

On a detected chunk error, reloads the page exactly once via `window.location.reload()`, guarded
by a `sessionStorage` timestamp (10s window) so a genuinely broken deploy (or a reload that
doesn't fix it) can't loop forever - not a retry budget, just loop prevention.

### (b) Backend/source-server config persistence: NOT actually at risk - already tolerant everywhere it matters

Checked every localStorage-backed piece of config in `common/cookies.ts`:
- `getLocalStorageSearchSettings` - JSON-parsed via quicktype's `Convert`, wrapped in try/catch,
  falls back to `getDefaultSearchSettings` on any schema mismatch. Already tolerant.
- `getLocalStorageFavorites` - `JSON.parse` + a manual shape check, falls back to `{}`. Already
  tolerant.
- `getLocalStorageManualOverrides` (Proposal B PR-2, this session) - same pattern, falls back to
  `{}`. Already tolerant.
- `getLocalStorageBackendURL` - **not JSON at all**: `localStorage.getItem(BackendURLKey)`, a raw
  string get with no parsing step. Structurally cannot "fail to parse" the way a JSON blob can -
  it can only be missing (`null`), which the app already handles via `NoBackendDefault`'s "remote"
  case (the very page the symptom shows).

So every value that goes through `JSON.parse` in this codebase already has the
malformed-data-tolerance pattern the task description was worried about; the one value that
doesn't (`backendURL`) isn't a JSON-parse candidate, so there's nothing to add there. **No code
change made for (b)** - the concern is real as a general pattern, but this specific codebase
already follows it everywhere it applies. Flagging as a confirmed non-issue rather than silently
skipping it.

### Assessment: (a) is the far more likely actual cause of the reported symptom

A stuck "No Server Configured" screen with no visible error report is a much closer match for a
JS-execution-failure class of bug (a route transition failing partway through hydration, part of
the app shell never running its own `dispatch(setURL(...))` effect) than for a config-corruption
class of bug (which this codebase already guards against everywhere it could occur, and which
would more likely present as a caught error or a silently-reset-to-default setting, not a blank
transition state).

## What shipped

- `frontend/src/common/chunkErrorRecovery.ts` (new) - pure detection/guard/reload logic.
- `frontend/src/common/useChunkErrorRecovery.ts` (new) - the mounting hook.
- `frontend/src/features/ui/Layout.tsx` - two-line wire-up (`useChunkErrorRecovery()` call).
- No change for (b) - confirmed not needed, see above.

## Verification

- `npx tsc --noEmit`: clean.
- `npx eslint` on all new/changed files: 0 errors (1 pre-existing, unrelated warning on
  `Layout.tsx`'s mount effect, present before this change too).
- Full `npx jest --runInBand`: **293/293 passing** (9 new: `isChunkLoadError` across
  `ChunkLoadError`-by-name, the webpack message format, a CSS-chunk message, a plain string
  reason, an unrelated error, and null/undefined; `shouldAttemptReload`'s guard-window math).
- New `frontend/tests/chunkErrorRecovery.spec.ts`, **4/4 passing** against the real, live-mounted
  app (not just the pure functions) - dispatches a synthetic `ChunkLoadError`-shaped `error` event
  and confirms a real `window.location.reload()` request fires (intercepted and aborted via
  `page.route` on the page's own URL, so the test can observe it without the navigation
  destroying Playwright's execution context mid-assertion); same for `unhandledrejection`; an
  unrelated error confirmed to NOT trigger a reload; two chunk errors in quick succession confirmed
  to only trigger one reload attempt (the loop guard, exercised for real, not just via the pure
  unit test).

### A real testing dead-end worth flagging

Two earlier approaches to this Playwright test failed for reasons unrelated to the fix itself:
(1) triggering a *real* chunk-load failure via `page.route` aborting the dev-mode page bundle
during an actual `next/link` client-side navigation - abandoned because the app never advanced
past a loading state, likely because Next dev mode's own HMR/error-overlay machinery intercepts
this differently than a production build would, and dev-mode chunk-naming isn't something this
test should be coupled to anyway. (2) stubbing `window.location.reload` via
`Object.defineProperty(window.location, "reload", {...})` to observe it without a real navigation
- silently ineffective (`Location` is a legacy platform object Chromium doesn't allow script to
override that way), and the real reload it triggered destroyed the page's JS execution context
before the test's follow-up assertion could run (`"Execution context was destroyed, most likely
because of a navigation"`). The approach that worked: dispatch the synthetic error directly
(bypassing real chunk-loading internals entirely) and intercept+abort the resulting reload's own
network request via `page.route(page.url(), ...)` - this observes a genuinely real
`location.reload()` call without ever letting the navigation complete.

## Deviations

None from the authorized investigation scope. (b) resulted in "confirmed non-issue, no code
change" rather than a fix, per the findings above.

## Open items

None blocking - this is a complete, isolated, small PR per the authorization ("small PR if a fix
is warranted"). Not stacked on the Proposal B branch chain (`claude/e2`.../`e3`.../`e4`...) since
it's unrelated/orthogonal work; based directly on `master`.
