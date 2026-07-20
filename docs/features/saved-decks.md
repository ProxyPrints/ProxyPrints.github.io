# Saved decks (zero-knowledge)

User accounts + server-side deck persistence for signed-in users, built so
the server operator is **cryptographically unable** to read deck contents.
Spec: [`proposals/proposal-g-user-accounts-saved-decks.md`](../proposals/proposal-g-user-accounts-saved-decks.md)
(§8 is the zero-knowledge design; §4 is the frontend spec). Shipped across
5 sequenced PRs, all merged: schema+backend (#85), sign-in relocation (#86),
the opaque-blob API (#94, a recreation after #88's stacked-PR base-deletion
auto-close — see [`../lessons.md`](../lessons.md)), the client-side crypto
module (#89), and the frontend UI wiring (#93). PR-5 (per-deck share links,
the spec's own "PR-5, post-v1" section) landed as a follow-up — see "Per-deck
share links" below.

## Where it's wired in

The save cluster (`SavedDeckPanel.tsx` — reverse breadcrumb + Save button)
mounts in two places, both reading/writing the same `projectSlice` +
`savedDeckSessionSlice` state, so a save made from one surface is visible
from the other without any extra plumbing:

- `ProjectEditor.tsx`'s right-panel action cluster — the original
  placement (round 1 of the spec, §4).
- `DisplayPage.tsx`'s top toolbar (issue #165, "Proposal G save
  integration" — Proposal H's own milestone, landed after the pane
  migration, #164) — see
  [`../proposals/proposal-h-unified-display-page.md`](../proposals/proposal-h-unified-display-page.md)'s
  §5 mapping table for this row. `SavedDeckPanel` takes an optional
  `className` prop so the two callers can each supply their own spacing
  (`ProjectEditor`'s vertical stack vs. `DisplayPage`'s horizontal
  flex-wrap toolbar row) without forking the component.

The **load** side (`MyDecksPage.tsx`'s "Open in editor") still always
navigates to `/editor`, unchanged — that's the spec's own explicit binding
text (§4: "an **'Open in editor'** action per row ... navigates to
`/editor`"), not an oversight of this integration. A user working entirely
on `/display` therefore still has to detour through `/editor` once to load
a previously-saved deck (client-side nav between the two pages preserves
the in-memory project — see `DisplayPage.tsx`'s own comment — so this is a
one-time hop, not a full reload); giving `/display` its own load entry
point is unbuilt, tracked as an open item on issue #165, not silently
assumed out of scope.

## The mental model

Discord OAuth (already used for moderator login — see
[`moderation.md`](moderation.md)) is **identity only**: it tells the server
which account owns which blobs, and nothing else. Every byte of deck
content — including the deck's own title — is encrypted **in the browser**
before it's ever sent anywhere. The server stores opaque ciphertext it
cannot decrypt, by design, not by policy.

- One random AES-256-GCM **master key**, generated once at first save and
  never regenerated.
- Every saved deck gets its own random **DEK** (AES-256-GCM), wrapped by the
  master key.
- The master key itself has two independently-wrapped copies: one wrapped by
  a PBKDF2-SHA256-derived key from the user's **passphrase** (≥600,000
  iterations, per-user salt), one wrapped by a user-held, randomly-generated
  **recovery key** (shown once, download/print/copy, never stored by the
  server in recoverable form).
- A passphrase change re-wraps only the one master-key slot — it never
  touches any deck's DEK or ciphertext, since the master key never changes.
- There is no admin-side or Discord-derived decryption/escrow path,
  anywhere. Lost passphrase **and** lost recovery key means the affected
  decks are permanently unrecoverable — the only remaining action is a
  destructive account reset that deletes the unreadable data and starts
  fresh (`resetSavedDecks`, gated on an authenticated session and an
  explicit `confirm: true`, not a fresh Discord re-auth — there's no
  freshness check on the backend to justify one).

## Backend (`MPCAutofill/cardpicker/`)

- `models.py`: `SavedDeck` (opaque ciphertext + nonce + wrapped DEK + nonce,
  `kind` = `deck` or `snapshot`) and `UserCryptoProfile` (per-user salt, KDF
  iteration count, both wrapped-master-key slots + their nonces).
- `views.py` (region "Saved decks"): 7 endpoints, all behind
  `@require_authenticated` (`security.py`, mirrors `require_moderator`) —
  `GET 2/savedDecks/`, `POST 2/saveDeck/` (upsert by key), `POST 2/loadDeck/`, `POST 2/deleteDeck/`, `GET 2/cryptoProfile/`, `POST 2/saveCryptoProfile/` (upsert, covers both first-save and passphrase
  change), `POST 2/resetSavedDecks/`.
- `get_saved_decks` returns **full per-deck ciphertext**, not lightweight
  metadata — a deck's title lives inside the ciphertext, so there's no
  server-visible field for a lighter list. The frontend decrypts every row
  to render "My Decks." A deliberate, closed-eyes tradeoff, not a bug.
- No server-side name-uniqueness enforcement is possible once titles are
  encrypted — collision detection is client-side-only.
- `SAVED_DECK_MAX_PER_USER` (default 100) caps ordinary `kind=deck` rows.
  `kind=snapshot` saves (the load-safety-flow's auto-backups — see below)
  skip that cap entirely and instead prune to the newest
  `SAVED_DECK_SNAPSHOT_RING_SIZE` (5, a code constant, not a setting) after
  every snapshot insert.
- `SAVED_DECK_MIN_KDF_ITERATIONS` (default 600,000) is a defensive floor
  checked server-side against whatever `kdfIterations` a client persists.

## Frontend (`frontend/src/features/savedDecks/`)

- `cryptoSession.tsx`: a React Context (not Redux — `CryptoKey` isn't
  serializable) holding the in-memory master key and a `status`
  (`anonymous`/`loading`/`no-profile`/`locked`/`unlocked`). The master key
  is never persisted anywhere — it clears itself on reload; the explicit
  "Lock" action (My Decks page) just does that sooner.
- `deckPayload.ts`: the plaintext shape encrypted wholesale (including its
  own `name`), `encryptDeckPayloadForSave`/`decryptSavedDeckSummary` (the
  wire-format pair), and `deviceLocal` marking — a `LocalFile`-sourced
  slot's identifier is device-specific and meaningless elsewhere, so only a
  flag survives on save; the card grid's existing empty-slot/re-search UI
  is the honest "needs re-picking" placeholder on load, not a bespoke tile.
- `PassphraseSetupModal.tsx` / `UnlockModal.tsx` / `RecoveryKeyDisplay.tsx`:
  first-save passphrase creation (with the verbatim-spirit unrecoverability
  warning), once-per-session unlock, and the show-once recovery-key
  download/print/copy step shared by both flows. `UnlockModal`'s "Forgot
  your passphrase?" branch unwraps via the recovery key, sets a new
  passphrase, **and** reissues a fresh recovery key (the old one is
  superseded once actually used — an ordinary passphrase change, by
  contrast, leaves the recovery slot untouched).
- `MyDecksPage.tsx` (`/myDecks`, nav-gated on an authenticated `whoami`):
  lists every saved deck, decrypted client-side once unlocked; named decks
  and snapshots in separate groups; "Open in editor", per-deck delete, an
  explicit "Lock" action, and account reset — reachable whether locked or
  unlocked, since recovering access when unlock is impossible is its whole
  point.
- `SavedDeckPanel.tsx` / `SaveDeckModal.tsx` / `LoadSafetyModal.tsx`: the
  editor's reverse breadcrumb ("Editing: {name}" / "Unsaved project") + Save
  button (authenticated-only), the name-prompt-and-encrypt Save flow, and
  the loss-proof-by-construction load flow — a dirty, logged-in editor
  always saves a safety copy before loading a different deck (never
  skippable), offering "Update {name}" vs "Save as new snapshot" when the
  current content is itself an already-saved deck, or just an
  inline-renameable snapshot save when it was never saved.
- A one-time, informational-only toast nudges an anonymous user who signs
  in mid-session (with a non-empty project) toward the Save button — the
  shared `Toasts` system has no action-button support, so this doesn't
  embed a "save now" action in the toast itself.

## Per-deck share links (PR-5)

Key-in-URL-fragment sharing (spec's "PR-5, post-v1: per-deck share links") —
the share URL's server-side request never carries key material, since the
`shareKey` travels only in the fragment (`#...`), which no host ever
receives.

- **Backend** (`MPCAutofill/cardpicker/`): `SavedDeckShare` model (migration
  `0076`), 4 endpoints — `POST 2/createDeckShare/`, `GET 2/deckShares/`
  (owner-only, metadata: shareId/deckKey/createdAt/expiresAt, never
  ciphertext), `POST 2/revokeDeckShare/` (owner-only, hard delete), and
  `POST 2/getSharedDeck/` (the ONLY unauthenticated saved-decks endpoint —
  no session/cookie/Origin-check involved at all, by design). Sharing is
  restricted to `kind=deck` rows — snapshots can't be shared.
  `SAVED_DECK_SHARE_MAX_PER_DECK` (default 20) is the per-deck abuse-guard
  cap, mirroring `SAVED_DECK_MAX_PER_USER`'s reasoning.
- **DELIBERATE, DOCUMENTED DEVIATION from the spec's literal prose**: a
  share's `ciphertext`/`ciphertext_nonce` are a FROZEN COPY taken from the
  owning deck at share-creation time, not a live reference to the deck's
  current ciphertext (the spec's own wording — "unwraps that deck's
  existing DEK... re-wraps that same DEK with the new shareKey" — reads as
  a live-coupled design). This is forced by an already-shipped PR-4
  invariant this PR builds on top of: `encryptDeckPayloadForSave` mints a
  FRESH DEK on every ordinary save (`SaveDeckModal.tsx`'s ordinary
  "Update" path, not just first-save) — a live-referencing share would
  silently break the instant the owner made one ordinary edit to a shared
  deck, which nothing in the spec documents as an accepted limitation.
  Precedent for a frozen point-in-time copy already exists in this schema
  (`SavedDeckKind.SNAPSHOT` rows); `SavedDeckShare` applies the same idea.
  One consequence, also deliberate: rotating a deck's DEK (the "paranoid"
  option, done via the ordinary `saveDeck` path — re-decrypt client-side,
  re-encrypt under a fresh DEK, no bespoke backend endpoint needed for this)
  does **not** invalidate any other still-outstanding share on that same
  deck, since each share's snapshot is fully self-contained — a divergence
  from the spec's prose ("other shares... need re-issuing"), reasoned
  through and necessary given the shipped fresh-DEK-per-save behaviour it
  interacts with. See `cardpicker.models.SavedDeckShare`'s docstring and
  [`../troubleshooting.md`](../troubleshooting.md)'s matching entry.
- **Frontend**: `savedDeckCrypto.ts` gained `generateShareKey`/
  `wrapDeckKeyForShare`/`unwrapDeckKeyFromShare` and base64url helpers
  (`bytesToBase64Url`/`base64UrlToBytes` — the spec names base64url
  explicitly for the fragment). `features/savedDecks/deckShare.ts` composes
  these with the existing `deckPayload.ts` parser (unmodified) into
  `prepareDeckShare`/`decryptSharedDeck`. `ShareDeckModal.tsx` (owner-side:
  create + list + revoke, wired into `MyDecksPage.tsx`'s named-deck rows
  only) and `SharedDeckPage.tsx` + `SharedDeckViewer.tsx` (recipient-side,
  behind the thin `pages/shared.tsx` wrapper — same split as
  `MyDecksPage.tsx`/`pages/myDecks.tsx`) round it out. The recipient view is
  deliberately **local-state only**, never touching the app's Redux
  `project`/`cardDocuments` slices — a recipient never edits, so there's no
  need to route a shared deck through `ProjectEditor`'s live state.
- **URL shape deviation**: the spec's literal
  `/shared/<shareId>#<shareKey-base64url>` puts `shareId` in a path
  segment. This app is a Next.js static export on GitHub Pages, which has
  no wildcard route fallback — a `[shareId]` dynamic path would need every
  possible id enumerated at build time (`getStaticPaths`), impossible for
  ids created at runtime. `shareId` therefore travels as a query param
  instead (`/shared?shareId=<uuid>#<shareKey-base64url>`) — this changes
  nothing about the property that's actually security-load-bearing: the
  `shareKey` itself still travels only in the fragment.
- **Tests**: the four scenarios the spec names explicitly (share
  round-trip, a revoked share's fetch failing for all subsequent attempts,
  rotation-on-revoke, and cross-deck isolation) are implemented as this
  PR's own requirement — crypto-level in
  `frontend/src/features/savedDecks/deckShare.test.ts`, endpoint-level in
  `MPCAutofill/cardpicker/tests/test_saved_deck_share_views.py`.

## Not yet built (design-only addenda in the spec doc)

- **PR-6, deck portability**: export/import of the complete encrypted
  bundle (no unlock required to export), a versioned public format, and a
  standalone decrypt tool as the trust anchor for "if this site vanishes
  tomorrow, your decks are still yours." Nothing built.
- **PR-7, art provenance**: per-slot provenance (`driveId`, `sourceName`,
  `sourceType`, optional `contentPhash`, `indexedBy`) in a future
  `deckPayload` version, so an un-indexed slot renders a direct-from-drive
  thumbnail instead of breaking. Deliberately never flows into the
  federation verdict export ([`../federation-v1.md`](../federation-v1.md))
  — that stays conclusions-only, no drive IDs or image routes. Nothing
  built.

## Owner-only / legal

- Discord credentials (`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`) are the
  same pre-existing mechanism moderator login already uses — confirm
  they're configured in production for the now much larger ordinary-user
  audience.
- The spec's §8 "Legal data-inventory paragraph" is written for the owner's
  PIPEDA review queue and is kept current in the spec doc itself, not
  duplicated here (it changes if the schema does).
