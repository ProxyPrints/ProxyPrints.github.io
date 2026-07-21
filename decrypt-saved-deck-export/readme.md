# decrypt-saved-deck-export

Standalone decrypt tool for a ProxyPrints saved-decks export file
(docs/proposals/proposal-g-user-accounts-saved-decks.md, "PR-6, post-v1: deck
portability"). This is the trust anchor for the claim "if this site vanishes
tomorrow, your decks are still yours" — it runs without ProxyPrints, this
codebase, or any server existing at all. Zero npm dependencies: it uses only
Node's own built-in `node:crypto` WebCrypto implementation, the exact same
primitives (AES-256-GCM, PBKDF2-SHA256) the browser itself used to encrypt
your decks in the first place.

**Status**: works today, standalone. The "Export my decks" button that
produces the file this tool reads is `frontend/src/features/savedDecks/MyDecksPage.tsx`'s
Export action.

## Requirements

Node.js 20 or later (needs `node:crypto`'s `webcrypto` export). Nothing else
— no `npm install` required for the tool itself. `node --test` (built into
Node, no dependency) runs this directory's own test suite.

## Usage

```
node decrypt.mjs <export.json> --passphrase "your passphrase"
```

```
node decrypt.mjs <export.json> --recovery-key "your-recovery-key-base64"
```

```
node decrypt.mjs <export.json>
# prompts for a passphrase interactively if neither flag is given
```

Prints every decrypted deck as one JSON array to stdout. Add `--out <dir>` to
write one `<deck name>.json` file per deck into `<dir>` instead.

Run the test suite:

```
node --test tests/decrypt.test.mjs
```

## The export format (public, versioned)

This is the actual portability contract — documented here specifically so a
fork, or a completely independent reimplementation, can read a ProxyPrints
saved-decks export without needing this codebase at all. The file is one
JSON object:

```jsonc
{
  "formatVersion": 1,
  "exportedAt": "2026-01-02T00:00:00.000Z",
  "cryptoProfile": {
    "salt": "<base64>",
    "kdfIterations": 600000,
    "passphraseWrappedMasterKey": "<base64>",
    "passphraseWrappedMasterKeyNonce": "<base64>",
    "recoveryWrappedMasterKey": "<base64>",
    "recoveryWrappedMasterKeyNonce": "<base64>"
  },
  "decks": [
    {
      "key": "<opaque server-assigned id>",
      "kind": "deck", // or "snapshot"
      "ciphertext": "<base64>",
      "ciphertextNonce": "<base64>",
      "wrappedDek": "<base64>",
      "wrappedDekNonce": "<base64>",
      "createdAt": "2026-01-01",
      "updatedAt": "2026-01-02"
    }
    // ...
  ]
}
```

Every field here is exactly the same opaque bytes the ProxyPrints server
itself stores — nothing in this outer envelope is ever plaintext deck
content. `formatVersion` is this bundle's own public wire-format version,
distinct from the PRIVATE per-deck `version` field described below (which
only exists once decrypted, inside the ciphertext).

### Unwrapping the master key

Exactly one of `passphrase` or `recoveryKeyBase64` is used:

- **Passphrase**: PBKDF2-SHA256 over the passphrase, using `salt` and
  `kdfIterations` above, produces an AES-256-GCM key. That key unwraps
  `passphraseWrappedMasterKey` (AES-GCM, IV = `passphraseWrappedMasterKeyNonce`)
  to recover the master key.
- **Recovery key**: the recovery key IS the key material already (no KDF) —
  import it directly as a raw AES-256-GCM key, then unwrap
  `recoveryWrappedMasterKey` (IV = `recoveryWrappedMasterKeyNonce`) the same
  way.

### Decrypting each deck

For every entry in `decks`:

1. Unwrap `wrappedDek` (AES-GCM, IV = `wrappedDekNonce`) using the master key
   from above, to get that deck's DEK (Data Encryption Key).
2. Decrypt `ciphertext` (AES-GCM, IV = `ciphertextNonce`) using the DEK.
3. The result is UTF-8 JSON text — a `DeckPayload` object:

```jsonc
// v1 (legacy, pre "Revision tracking")
{
  "version": 1,
  "name": "...",
  "members": [
    /* ... */
  ],
  "cardback": null,
  "manualOverrides": {},
  "finishSettings": { "cardstock": "...", "foil": false }
}
```

```jsonc
// v2 (current - adds revision tracking)
{
  "version": 2,
  "name": "...",
  "members": [
    /* ... */
  ],
  "cardback": null,
  "manualOverrides": {},
  "finishSettings": { "cardstock": "...", "foil": false },
  "revision": 3,
  "modifiedAt": "2026-01-01T00:00:00.000Z"
}
```

`revision` (an integer, incremented on every save of that same row) and
`modifiedAt` (an ISO 8601 timestamp) make an export/import round-trip
self-describing: comparing an imported bundle's `revision`/`modifiedAt`
against a server's current copy of "the same" deck (if you're tracking that
manually — ProxyPrints itself never matches decks by name or key on import,
see the main feature doc) tells you which copy is newer, without either side
needing to compare plaintext.

A future version (`version: 3`, PR-7 "art provenance") is expected to add an
optional per-slot provenance record to each member; this tool's own
`decrypt.mjs` doesn't special-case any particular version — it just decrypts
the ciphertext and returns whatever JSON comes out, so it will keep working
unmodified once that ships.

## Design notes

- **No key material ever touches disk** beyond what's already in the export
  file itself — this tool holds the master key and each DEK in memory only,
  for the duration of one run.
- **A wrong passphrase or recovery key fails loudly** (an AES-GCM
  authentication error) — this tool never silently returns corrupted or
  wrong plaintext.
- **An exported file is offline-attackable** by design (same exposure a
  server breach of ProxyPrints' own database already has) — its real
  protection is passphrase strength plus PBKDF2 at a high iteration count.
  Treat an export file with the same care you'd give a password manager
  export.
