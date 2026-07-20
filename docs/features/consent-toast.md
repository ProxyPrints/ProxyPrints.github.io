# Contextual consent toast (issue #204)

## What this is

A reusable, general-purpose consent-UX mechanism: a small, dismissible,
bottom-corner toast that asks accept/decline consent for ONE SPECIFIC
action, triggered right before that action would collect data. It is
deliberately **not** a blanket on-load "we use cookies" banner — nothing
shows until a call site explicitly asks for consent for something it's
about to do.

Built with no dependency on any consumer feature. Issue #203 (client-side
phash contribution) is the first planned consumer but is not built yet and
this mechanism does not reference it. Any future permission point (a
webcam capture, a location lookup, anything else that needs a specific
opt-in) can call the same hook with its own key and message.

## Files

- `frontend/src/features/consent/consentToast.ts` — pure logic +
  sessionStorage-backed decision storage, one entry per **permission key**
  (`consentToastDecision:<key>`). Mirrors
  `frontend/src/features/export/postExportContributionPrompt.ts`'s own
  pure-logic/storage split, generalised from a single "shown once" flag to
  a per-key accept/decline decision.
- `frontend/src/features/consent/ConsentToast.tsx` — the presentational
  toast. Built on react-bootstrap's `Alert` (not `Toast`/`ToastContainer`)
  with `transition={false}`: both `Toast` and `Alert`'s own default Fade
  transition hardcode `role="alert"` on the rendered element (verified by
  reading `node_modules/react-bootstrap/{Toast,Alert}.js` directly), which
  is wrong for a widget that requires a user decision via two buttons —
  `role="alertdialog"` is the correct ARIA role
  (https://www.w3.org/TR/wai-aria-1.1/#alertdialog), and disabling the Alert
  component's default transition is the only way a caller-supplied `role`
  prop is allowed to win over the hardcoded one. The cost is no fade
  animation, an acceptable trade for correct semantics on a component that
  exists specifically to be decided on, not glanced at.
- `frontend/src/features/consent/useConsentToast.tsx` — the reusable hook.
  Returns `{ element, requestConsent }`: render `element` once wherever the
  caller wants the toast mounted, then call
  `requestConsent({ key, title?, message, acceptLabel?, declineLabel? })`
  right before the action that needs consent. Resolves to `true`/`false`.

## API

```tsx
const { element, requestConsent } = useConsentToast();

async function doSomethingThatNeedsConsent() {
  const accepted = await requestConsent({
    key: "phash-contribution", // scopes the remembered decision to THIS permission
    title: "Help identify this printing?",
    message:
      "We'd like to check a perceptual hash of your card image against known printings.",
  });
  if (!accepted) return;
  // proceed with the actual data-collecting action
}

return (
  <>
    {element}
    {/* rest of the component */}
  </>
);
```

If the same `key` was already decided earlier this session, `requestConsent`
resolves immediately with the remembered decision and the toast never
appears — "don't re-ask on every action within the same session if already
decided" (issue #204 requirement 4). Decisions are scoped **per key, not
global**: declining one permission request never suppresses an unrelated
one.

## Design decisions worth knowing about

- **sessionStorage, not localStorage** — same reasoning as
  `postExportContributionPrompt.ts`: a consent decision must not survive a
  "clear site data"/incognito test the way a real persisted setting would,
  but does need to survive this tab's own reloads.
- **Dismiss (Escape or the header close button) counts as decline, and that
  decision is persisted for the rest of the session** — the same posture
  cookie-consent banners and `PostExportContributionPrompt.tsx`'s own
  "shown = done, whether interacted with or not" precedent both take. The
  `Promise<boolean>` contract `requestConsent` returns has no third
  "ask me again" state to resolve to. A future permission point that
  genuinely needs "ask again after a dismiss" behaviour (as opposed to an
  explicit decline) would need a new mechanism, not a variant of this one.
- **Positioned bottom-right** (`bottom-end`), deliberately the opposite
  corner from the existing global toast stack mounted in `Layout.tsx`
  (`Toasts.tsx`, `bottom-start`), so a consent request and an unrelated
  system notification never visually collide.
- Focus moves to the "Allow" button when the toast appears, since it's
  mounted unconditionally in the tree rather than opened from a click that
  already carries focus context — without this a keyboard/screen-reader
  user has no cue that a new interactive element just appeared.

## Testing

Jest/RTL component tests (matching `ArtistSupportLink.test.tsx`'s own
convention), not a Playwright e2e spec — there is no real call site yet to
mount a `.spec.ts` against, and inventing a throwaway demo route just to
get an e2e test would be exactly the kind of "parallel entry point" this
codebase's conventions avoid (see `PostExportContributionPrompt.tsx`'s own
comment on that). Once #203 (or any other consumer) wires this in for
real, that feature's own Playwright spec should cover the toast in context,
the same way `PostExportContributionPrompt.spec.ts` covers issue #166
through the real export flow rather than in isolation.

- `frontend/src/features/consent/consentToast.test.ts` — pure logic +
  per-key sessionStorage scoping.
- `frontend/src/features/consent/ConsentToast.test.tsx` — rendering,
  `alertdialog` role, focus-on-open, accept/decline/close-button/Escape
  handlers, custom labels.
- `frontend/src/features/consent/useConsentToast.test.tsx` — hook
  integration via a harness component (mirrors `cryptoSession.test.tsx`'s
  own harness pattern): show/resolve wiring, per-session no-re-ask,
  per-key scoping, dismiss-counts-as-decline.

Manually verified in a running dev server by temporarily wiring
`requestConsent` into a demo button on the homepage, screenshotting the
result, and reverting the temporary wiring before committing (no permanent
demo/dev-only route was left behind).
