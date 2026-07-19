As of: 2026-07-19
Task: SERVER session — Discord sign-in end-to-end diagnosis (owner
symptom: clicking the navbar "Sign in" button does nothing — no
navigation, no error page) + widget breakpoint location report + PR #99
merge. Read-only diagnosis, no fix applied per "report root cause, fix
routes to the owning session."
Branch/worktree: catalog-completion-part2 (report-only for the diagnosis
itself; PR #99 merge was a real action, detailed below)

## WHAT SHIPPED

1. **Root cause found**, confirmed via headless-browser DOM inspection
   against the live site (not the earlier direct-URL-construction test,
   which only proved the redirect_uri itself is correctly formed — the
   owner correctly flagged that as testing the wrong layer).
   `frontend/src/features/ui/Navbar.tsx` wraps `<AuthWidget />` in
   `<Nav.Link className="m-0 py-0" eventKey="auth">`. react-bootstrap's
   `Nav.Link`, when given an `eventKey` prop, renders its own anchor tag
   (`href="#"`, tab/pill-selection semantics) around its children — but
   `AuthWidget` also renders a real
   `<a href="https://api.proxyprints.ca/accounts/discord/login/...">` of
   its own (the "Sign in" / "Sign out" link). The result is genuinely
   invalid, nested `<a>` HTML, confirmed directly in the live DOM:

   ```
   <a href="#" class="nav-link">                          <!-- Nav.Link, eventKey="auth" -->
     <a href="https://api.proxyprints.ca/accounts/discord/login/?next=...">
       Sign in                                             <!-- AuthWidget's real link -->
     </a>
   </a>
   ```

   The outer `Nav.Link`'s own `href="#"`/`eventKey` click handling
   intercepts the click and prevents the inner real link's navigation —
   with zero JS errors thrown (nothing crashes, the click's default
   action is just silently swallowed), which is exactly why the owner
   sees no navigation AND no error page.

   Introduced by PR #86 ("relocate sign-in from /whatsthat to the
   navbar", `be85b515`) — confirmed via
   `git log -S 'eventKey="auth"' -- frontend/src/features/ui/Navbar.tsx`.
   Both the "Sign in" and "Sign out" branches of `AuthWidget` render
   through this same wrapper, so both are affected identically (not
   verified live for "Sign out" specifically — no authenticated session
   was available to test — but follows directly from the shared wrapper
   in the code).

2. **Diagnostic evidence gathered**, per the owner's specific asks:

   - **(a) Console errors at click time**: none. Page errors: none.
     Failed network requests: none.
   - **(b) Button's rendered href/onClick**: entirely correct —
     `<a href="https://api.proxyprints.ca/accounts/discord/login/?next=https%3A%2F%2Fproxyprints.ca%2Fwhatsthat">`,
     `target: null`, `onclick: null` (no inline handler),
     `display: inline-flex`, `pointer-events: auto`, not disabled. The
     button itself is correctly formed; the bug is purely in its DOM
     ancestry, not the button's own markup.
   - **(c) Config/whoami network calls**: only `GET /2/whoami/ → 200`
     fires (confirming `discordEnabled: true`, `loginUrl` correctly
     populated server-side). No failed config fetch of any kind — the
     click never even reaches the network layer, consistent with
     navigation being blocked client-side before any request fires.

   Confirmed the earlier redirect-URL-construction test (curl'ing the
   login URL directly, then the resulting Discord authorize URL) DID
   exercise the URL-builder correctly and NOT the button's real click
   path, exactly as the owner suspected — that test remains valid
   evidence the backend/OAuth config itself (`client_id`,
   `redirect_uri=https://api.proxyprints.ca/accounts/discord/login/callback/`,
   `scope`, `response_type`) is correctly formed and Discord's own
   authorize endpoint accepts it (200, normal app shell, not an error
   page). The bug is entirely upstream of that, in the navbar's own
   click handling — the request never leaves the browser.

3. **Widget breakpoint location report** (separate ask, owner "couldn't
   locate it"): the widget is mounted correctly, gated on
   `remoteBackendConfigured`, inside the navbar's right-aligned
   `ms-auto` nav group (alongside the download-manager and
   configure-backend buttons). `Navbar` uses `expand="lg"` (Bootstrap's
   992px breakpoint). Pinned the exact threshold live:

   | Viewport width | Widget visible?                          |
   | -------------- | ---------------------------------------- |
   | ≤991px         | No — inside the collapsed hamburger menu |
   | ≥992px         | Yes — directly in the top bar            |

   This is standard, intentional Bootstrap responsive-navbar behavior,
   not a bug — but likely explains "couldn't locate it" if the owner was
   testing on a narrower window/viewport without expanding the hamburger
   menu first.

4. **PR #99** (G's docs-only PR-6/PR-7 addenda) merged (`430a120a`) — CI
   green, mergeable clean, confirmed no dependent PRs before deleting its
   branch (`claude/proposal-g-pr6-portability-design`).

## DEVIATIONS

None — per the explicit instruction, root cause reported and NOT fixed;
routing to whichever session owns `Navbar.tsx`/#86's follow-up next.

## VERIFICATION

- Root cause confirmed via three independent signals converging: (1) DOM
  ancestry walk showing the literal nested-anchor structure, (2) zero
  console/page/network errors ruling out a crash or failed request as
  the cause, (3) `git log -S` confirming exactly which merge introduced
  the `eventKey="auth"` wrapper.
- Breakpoint threshold confirmed via direct measurement at 991px and
  992px, not inferred from the CSS alone.
- All checks run against the live production site (proxyprints.ca), via
  Playwright headless Chromium, real network calls, no mocking.

## OPEN ITEMS / DECISIONS NEEDED

1. **Fix for the owning session** (`Navbar.tsx` / whoever picks up #86's
   follow-up): the real fix is to stop wrapping `AuthWidget` in a
   `Nav.Link` with an `eventKey` — either drop `eventKey="auth"`
   (`Nav.Link` without an `eventKey` renders as a plain, non-intercepting
   anchor-or-passthrough) or replace the wrapper with a plain
   `<li className="nav-item">`/`<div>` instead of `Nav.Link`, since
   `AuthWidget` already supplies its own real `<a href>` for both the
   login and logout states and doesn't need `Nav.Link`'s tab-selection
   machinery at all.
2. Not verified live: the "Sign out" (authenticated) branch's identical
   wrapper — inferred from shared code, not click-tested (no live
   authenticated session available).

## LIVE STATE

No code changes made for the diagnosis itself. `master` is at `430a120a`
(PR #99 merged, docs-only, no deploy implications). The Discord sign-in
click bug is still live in production, unfixed, per the explicit
"report, don't fix tonight" instruction.
