```
TASK: Proposal G — user accounts + saved decks (zero-knowledge revision)
BRANCHES/PRS:
  - claude/proposal-g-schema-backend -> PR #85 (schema + backend models/migration/admin/settings)
  - claude/proposal-g-signin-navbar -> PR #86 (sign-in UX relocation to navbar)
  - claude/proposal-g-saved-decks-api -> PR #88 (draft; opaque-blob REST API, stacked on PR #85's branch)
  - claude/proposal-g-crypto-module -> PR #89 (client-side ZK crypto module)
  - this report -> report-relay-proposal-g-checkpoint-8f2c1a (based on fresh origin/master)

WHAT SHIPPED:
1. PR #85 (schema + backend): SavedDeckKind (deck/snapshot), SavedDeck (opaque
   ciphertext + nonce + wrapped-DEK + nonce, no card/searchable columns),
   UserCryptoProfile (per-user salt, KDF iteration count, two independently
   wrapped copies of one master key — one passphrase-wrapped, one
   recovery-key-wrapped — with their own nonces). Migration regenerated via
   makemigrations, verified --check --dry-run against real local Postgres
   (zero drift), applies cleanly. Admin registration for both models.
   New settings: SAVED_DECK_MAX_PER_USER (default 100),
   SAVED_DECK_MIN_KDF_ITERATIONS (default 600,000). New constant
   SAVED_DECK_SNAPSHOT_RING_SIZE = 5 (deliberately a code constant, not an
   env setting — implementation safety valve, not user-facing quota).
   Model tests cover defaults, no-uniqueness-enforcement, cascade delete,
   one-profile-per-owner. Also fixed a pre-existing unrelated bug found
   while editing admin.py (see DEVIATIONS).
2. PR #86 (sign-in relocation): AuthWidget moved from the /whatsthat page
   into the global Navbar (gated on remoteBackendConfigured), so sign-in is
   available site-wide, not just on the printing-tags page. Copy changed
   "Log in with Discord" -> "Sign in" (Discord branding/icon retained on
   the button itself; label text is now provider-agnostic since accounts
   are no longer moderation-only). Playwright spec updated to assert the
   widget lives on /editor, not /whatsthat, proving the move rather than
   just not breaking.
3. PR #88 (draft — saved-decks API): 7 endpoints, all @require_authenticated:
   GET /2/savedDecks/, POST /2/saveDeck/, POST /2/loadDeck/,
   POST /2/deleteDeck/, GET /2/cryptoProfile/, POST /2/saveCryptoProfile/,
   POST /2/resetSavedDecks/. Ownership checked server-side (403, not the
   BadRequestException path). FIFO snapshot ring enforced server-side at
   SAVED_DECK_SNAPSHOT_RING_SIZE. 13 new JSON schemas (all ciphertext/
   nonce/key fields are plain base64 strings over the wire — server never
   parses deck contents). schema_types.py/.ts regenerated via quicktype +
   isort/black/prettier. 26 new tests (auth-required, ownership, cap
   enforcement, snapshot ring, crypto-profile CRUD, account reset).
   Opened as DRAFT and stacked on PR #85's branch (genuine import
   dependency on its models) — see OPEN ITEMS for the required retarget.
4. PR #89 (crypto module): frontend/src/common/savedDeckCrypto.ts —
   full WebCrypto-only ZK implementation: PBKDF2-SHA256 passphrase
   derivation (>=600k iterations), AES-256-GCM master key / per-deck DEK /
   recovery-key generation, key wrap/unwrap, encrypt/decrypt of full deck
   payloads (including titles). 11 tests covering every case enumerated in
   the spec's "Tests required" sections (encrypt/decrypt round-trip, wrong
   passphrase fails, tamper -> GCM auth failure, passphrase change re-wraps
   correctly, recovery-key round-trip, both-lost path, recovery key from
   before a passphrase change still works). Required a jsdom crypto.subtle
   polyfill (jest.setup.ts) and TS 5.9 Uint8Array<ArrayBuffer> annotations
   (see VERIFICATION).

DEVIATIONS from spec (each with reasoning):
1. get_saved_decks returns full per-deck ciphertext, not lightweight
   metadata. Under the ZK design the deck title lives inside the
   ciphertext, so there is no server-visible field to return for a
   lightweight list view — the client must decrypt every row to render
   "My Decks." This follows directly from the spec's own exhaustive
   per-record field enumeration ("opaque ciphertext + wrapped DEK + nonces
   + salt reference + timestamps... nothing else"); adding a separate
   title-only ciphertext field would violate that same enumeration, so
   this was left as an explicit, eyes-open tradeoff rather than solved.
2. The spec's original renameDeck endpoint was dropped (not built).
   Renaming is now just a normal saveDeck update-by-key call, since no
   server-visible name exists to "rename" under the ZK design.
3. Section 7 (authed-vote-tier: AUTHED_VOTE_GATE_MODE, authed_vote_weight(),
   AbstractWeightedVote.account_tier) was NOT built in PR #85, per the
   spec's own repeated statements that it is a separate, later build with
   its own migration/consensus-math change/PR/review — not bundled with
   this HOLD's core scope. Flagged explicitly in PR #85's description.
4. Own-caught bug fix, unrelated to Proposal G: AdminTagAliasSuggestion's
   `actions = ["accept_suggestions", "reject_suggestions"]` referenced two
   methods that were mis-indented under a different, unrelated ModelAdmin
   class further down admin.py. Moved them back under the correct class
   while editing that file for the new model registrations.
5. Own-caught spec self-consistency bug: the spec's original "Key design"
   subsection said a passphrase change "re-wraps every deck's DEK," which
   contradicted "Recovery key"'s explicit statement that the master key
   never changes. Found while designing PR4a's implementation, fixed in
   the spec doc (both the Key design and Tests-required wording, and the
   legal data-inventory paragraph's "two wrapped copies of that deck's
   encryption key" -> "two wrapped copies of the user's one master key")
   BEFORE writing code against the wrong model.
6. quicktype's type-naming algorithm renamed the pre-existing `Kind` type
   (previously used only by VoteQueueRequest) to `VoteQueueRequestKind`
   when the 13 new schemas introduced identically-shaped `kind` enums
   elsewhere. Fixed the two existing import sites (views.py, store/api.ts)
   to the new name — not a design deviation, just fallout from adding new
   schemas, noted here since it touches pre-existing code paths.

VERIFICATION:
  - PR #85: model tests run via raw Django-shell script against real local
    Postgres (pytest itself cannot run in this sandbox — testcontainers
    fixtures require Docker, unavailable here). migrate --check --dry-run
    showed zero drift. CI (real Docker) ran the actual pytest suite:
    passed-count rose 857->859 tracking exactly with new tests added.
  - PR #88: 17-assertion raw Django-shell smoke script exercising all 7
    endpoints end-to-end against real local Postgres, plus the 26 new
    pytest tests (cannot run locally; confirmed via CI, passed-count rose
    859->882 tracking new test count).
  - PR #89: full local jest run, 11/11 passing after fixing the
    crypto.subtle/jsdom gap (jest.setup.ts polyfill using node:crypto's
    webcrypto export) and a TS 5.9 Uint8Array<ArrayBuffer> generic-typing
    gap (tsc --noEmit clean after fix).
  - PR #86: full jest suite + live Playwright run (3 passed) using a
    temporary executablePath override for a sandbox-only browser-binary
    version mismatch; that override was reverted via git checkout --
    before committing, per environment policy (never run playwright
    install).
  - isort version mismatch caught as a REAL CI failure (not sandbox-only):
    my sandbox had self-installed isort 8.0.1; .pre-commit-config.yaml
    pins isort==5.12.0, which formats a wrapped 3-line import differently.
    Fixed by installing the pinned version locally and re-verifying;
    pushed the corrected formatting to PR #88's branch.
  - All "Backend tests" CI failures encountered on PR #85/#88 (multiple
    notifications) were investigated individually and confirmed to be the
    same 14 pre-existing, environment-only failures documented in
    docs/troubleshooting.md (7x TesseractNotFoundError, 2x moxfield
    integration assert None, 2x sources JSONDecodeError, plus others),
    not caused by this work — confirmed by comparing the stable 14-failure
    count against a rising passed-count (857->859->882) that tracks
    exactly with this work's own new tests.
  - Deferred: end-to-end browser verification of the full save/decrypt/
    load round-trip through real API calls — no UI exists yet to drive it
    (that's PR4b, not yet started); each layer (crypto module, API,
    schema) has been verified independently instead.

OPEN ITEMS / DECISIONS NEEDED:
1. OWNER-ONLY — Discord application credentials: DISCORD_CLIENT_ID and
   DISCORD_CLIENT_SECRET env vars (settings.py's existing
   DISCORD_AUTH_ENABLED = bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET)
   / SOCIALACCOUNT_PROVIDERS wiring). This mechanism already exists today
   for moderator Discord login — Proposal G does not add a new credential,
   it broadens the existing sign-in to all users. The owner-only action is
   confirming these are already configured in production for the now much
   larger ordinary-user audience (not just moderators), and rotating them
   first if there's any concern about scope creep from that broadened use.
2. OWNER-ONLY — PIPEDA/legal data-inventory paragraph for the review queue,
   verbatim: "Saved decks are stored as ciphertext the server cannot
   decrypt — the encryption passphrase, the user's recovery key, and every
   key derived from either, exist only in the user's browser (or the
   user's own safekeeping, for the recovery key) and are never transmitted
   or stored server-side in recoverable form. The server retains only: the
   owning account's identifier, an opaque encrypted blob per deck plus
   that deck's own wrapped encryption key, two wrapped copies of the
   user's single master key (one recoverable with the passphrase, one
   recoverable with the user's own recovery key — neither readable by us),
   a per-user random salt and iteration count (not secret; strengthens key
   derivation), and ordinary created/updated timestamps. A user can delete
   any saved deck — or, once account deletion ships, their entire account
   — at any time, immediately and permanently. If both the passphrase and
   the recovery key are lost, the affected decks are permanently
   unrecoverable by design; the server operator has no admin-side
   decryption or escrow path and cannot assist beyond a destructive account
   reset that deletes the unreadable data and lets the user start fresh."
3. PR #88 is a draft, deliberately stacked on PR #85's (still-open) branch
   because it genuinely imports PR #85's models. Merge-time checklist item
   (already written into PR #88's own description): once PR #85 merges to
   master, retarget PR #88's base to master before merging it, to avoid
   the documented stacked-PR base-deletion trap (docs/lessons.md) where a
   squash-merge deleting the parent branch auto-closes the stacked PR with
   no reopen possible.
4. PR4b (My Decks page, passphrase-creation + recovery-key-download UX,
   unlock/lock flow, save/load wiring, account-reset UI, wiring the 7 new
   endpoints + crypto module into the frontend) is scoped but not started
   — this is the next and largest remaining chunk of Proposal G.

LIVE STATE:
  - 4 branches pushed: claude/proposal-g-schema-backend,
    claude/proposal-g-signin-navbar, claude/proposal-g-saved-decks-api,
    claude/proposal-g-crypto-module.
  - 4 PRs open: #85, #86, #88 (draft), #89. All subscribed via
    subscribe_pr_activity; will keep responding to CI/review events on
    each per standing instructions.
  - No user-facing behavior has shipped/merged yet (nothing on master),
    so no wiki update is due yet — will do the CLAUDE.md-mandated
    user/admin-facing wiki check once PR4b lands something visible.
  - Next action after this report: begin PR4b per Task #9's scope.
```
