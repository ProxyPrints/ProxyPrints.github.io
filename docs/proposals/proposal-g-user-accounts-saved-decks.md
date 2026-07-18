As of: 2026-07-18
What this is: survey + HOLD proposal for opening the existing Discord login to
ordinary users and letting any logged-in user save/load named decks
server-side, encrypted client-side so the server operator cannot read deck
contents (see the zero-knowledge amendment below, decision 10 — this
supersedes §2/§3's originally-specified plaintext storage model).
**BUILT AND MERGED** — all 5 sequenced PRs landed on master: schema+backend
(#85), sign-in relocation (#86), the opaque-blob saved-decks API (#94,
recreated after #88's stacked-PR base-deletion auto-close — see
docs/lessons.md), the client-side ZK crypto module (#89), and the frontend
UI wiring (#93). **Spec CLOSED: no open decisions remain** (see Decisions).
§7 (authed vote tier) is fully specified but remains a deliberately separate,
later build — not part of this HOLD's core scope. PR-5 (share links) and
PR-6 (deck portability) are design-only, post-v1 addenda — nothing built
for either yet.

## Context — prior art outside this codebase

Proxxied's framing is the precedent this proposal matches: "start free,
optionally sign in to save projects across devices — no account required."
Login here is the same shape — never a gate on using the editor, purely an
opt-in path to persistence across sessions/devices for users who want it.

## Summary

- **No new auth to build.** Discord login via django-allauth already works
  end-to-end for any Discord user, moderator or not — `is_moderator` is a
  separate, later check (Django group membership) that grants nothing at
  login time. The entire gap is UX placement: the login widget is mounted on
  exactly one page (`/whatsthat`, the moderator-facing tool) and nowhere else
  in the app's chrome.
- **The editor's in-memory project state is already a plain, JSON-serializable
  shape** — no Blobs, DOM refs, or class instances. That JSON, not XML, should
  be the canonical stored representation; XML 2.0 / decklist exports stay
  derived, on-demand interchange snapshots, generated fresh from stored state
  every time (matches the brief's constraint directly).
- **This codebase already has a `Project`/`ProjectMember` model** for exactly
  this purpose — but it's dead code (its URLs are commented out, no REST API
  exists over it, and its normalized per-card-row schema doesn't match the
  frontend's actual project shape). Recommendation: build the new
  `SavedDeck` model fresh, per the brief, and flag the old models for
  removal rather than resurrection (see §3).
- **Size**: ~15–35 KB of JSON per 60–100-card deck (identifiers + small
  metadata only, confirmed no image bytes anywhere in the frontend project
  state) — trivial for a Postgres `JSONField` at any realistic user count.

## 1. Auth survey

**Mechanism**: `django-allauth[socialaccount]~=65.4` (`MPCAutofill/requirements.txt:6`),
not a custom OAuth flow, no DRF/JWT/token auth anywhere in the app — plain
Django cookie session auth throughout.

- `DISCORD_AUTH_ENABLED = bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET)`
  (`settings.py:169`) is the master flag; absent credentials means the
  provider app is never installed and `/accounts/discord/login/` 404s.
  `SOCIALACCOUNT_PROVIDERS` is app-in-settings config (`settings.py:173`) —
  no `SocialApp` DB row, no `django.contrib.sites`.
- `SOCIALACCOUNT_AUTO_SIGNUP = True` (`settings.py:179`) — **any** Discord
  login already auto-creates a Django `User` today, moderator or not. There
  is no signup gate, invite list, or allowlist of any kind.
- **What gates moderator-only access is a completely separate, later check**:
  `cardpicker/moderation.py::is_moderator(user)` — `user.groups.filter(name=settings.MODERATORS_GROUP_NAME).exists()`,
  checked at _resolution/request_ time, never at login. "Logging in with
  Discord grants nothing by itself" (`docs/features/moderation.md:27-28`).
  Server-side enforcement is `cardpicker/security.py::require_moderator`
  (403s, not a redirect), stacked with `reject_untrusted_origin` (an
  `Origin`-header allowlist check standing in for CSRF, since every endpoint
  is `@csrf_exempt` for anonymous cross-origin clients) on every
  moderation-only view.
- **Frontend auth state**: no dedicated auth context/provider — it's one
  RTK Query cache entry. `GET 2/whoami/` → `{authenticated, username, moderator, discordEnabled, loginUrl, logoutUrl}` (`store/api.ts:206-218`,
  `credentials: "include"`). `AuthWidget.tsx` (`features/moderation/`)
  renders nothing if Discord isn't configured or the query errored/is
  loading; otherwise shows "Signed in as **{username}**" (+ "(moderator)"
  suffix only if `moderator === true`) or a Discord-branded login button.
  It **already has a working, presentational "logged in, not a moderator"
  state** — there's even an explicit mock fixture for it
  (`whoamiSignedInNotModerator`, `frontend/src/mocks/handlers.ts:1141-1148`)
  — it's just never been exercised anywhere because `AuthWidget` is only
  mounted inside `pages/whatsthat.tsx:99`, gated by `remoteBackendConfigured`
  (not by moderator status). Every other page has zero auth awareness.
- **Cross-origin session mechanics** (relevant since the frontend is a
  static export on a different origin from the API): `SESSION_COOKIE_SAMESITE=None`,
  `SESSION_COOKIE_SECURE=True`, `CORS_ALLOW_CREDENTIALS=True` in prod
  (`settings.py:193-202`); only fetches that opt into `credentials: "include"`
  carry the cookie — today that's `whoami`, `reportCard`, and the
  moderation-queue/drives endpoints. Every anonymous vote-submission fetch
  uses `credentials: "same-origin"` and is unaffected. `FrontendRedirectAccountAdapter`
  (`accounts/adapter.py`) validates the `?next=` redirect target against
  `CORS_ALLOWED_ORIGINS` so login/logout round-trip back to whatever static
  frontend origin the user came from, already working for any user.

**Conclusion**: opening login to ordinary users is exactly the config/UX
work the brief assumes — mount the existing `AuthWidget` (or a slightly
slimmed variant, since the "(moderator)" suffix is already conditional and
harmless to leave in) somewhere every user sees it, and gate nothing new
server-side beyond "is this deck's owner the requesting session's user,"
which is a much weaker check than `require_moderator` and can reuse its
exact shape (see §3).

**Provider mechanism, for the auth-framing decision in §4**: allauth's
multi-provider support is already the mechanism `DISCORD_AUTH_ENABLED`
exploits — `SOCIALACCOUNT_PROVIDERS` (`settings.py:173`) is a plain dict
keyed by provider id (today just `"discord"`), and the provider app is only
added to `INSTALLED_APPS` conditionally (`settings.py:171`). Adding a second
provider (e.g. Google) is exactly one more dict key, one more conditional
`INSTALLED_APPS` entry (`allauth.socialaccount.providers.google`), and one
more `*_AUTH_ENABLED`-style flag mirroring `DISCORD_AUTH_ENABLED` — no new
auth framework, no change to `whoami`'s shape beyond it already being
provider-agnostic (`authenticated`/`username`/`moderator` don't care which
provider signed the user in).

## 2. Project state survey

**In-memory shape** — `Project` Redux slice (`store/slices/projectSlice.ts`,
type at `common/types.ts:120-144`):

```ts
export interface ProjectMember {
  query: SearchQuery; // {cardType, query, expansionCode?, collectorNumber?}
  selectedImage?: string; // card identifier, e.g. a Google Drive file id
  selected: boolean; // multi-select UI state
}
export type SlotProjectMembers = { id: string } & {
  [face in Faces]: ProjectMember | null;
};
export type Project = {
  members: Array<SlotProjectMembers>;
  nextMemberId: number; // UI bookkeeping (stable React key counter)
  cardback: string | null;
  mostRecentlySelectedSlot: Slot | null; // transient UI state
};
```

Plus a sibling slice, `FinishSettingsState` (`{cardstock: Cardstock, foil: boolean}`,
`store/slices/finishSettingsSlice.ts`) — cardstock/foil live outside `Project`
proper but are equally part of "the deck."

**Serializability**: already a plain, JSON-serializable data shape end to
end — strings, booleans, nested plain objects, no functions/Blobs/DOM refs/
class instances. Even locally-sourced cards (`FileSystemFileHandle` etc.)
never leak into `Project` — a local-file card is still referenced purely by
a string identifier there; the non-serializable handle lives in a separate,
unrelated client-search-index slice.

**XML 2.0 export/import gaps that make XML the wrong storage format**
(`features/download/downloadXML.ts`, `features/import/ImportXML.tsx`):

- Export re-derives the `<query>` text from the resolved card document's
  `searchq`, not the originally-stored `SearchQuery.query`/`expansionCode`/
  `collectorNumber` — reformats, doesn't round-trip byte-for-byte.
- Export writes the community-confirmed `<set>`/`<collectorNumber>`/
  `<scryfallId>` (XML 2.0's addition, from `canonicalCard`) — **import
  completely ignores them.** A save/load cycle through XML today silently
  drops printing-identity metadata on the way back in.
- Transient/UI-only fields (`nextMemberId`, `mostRecentlySelectedSlot`,
  per-member `selected`) are correctly never exported and never need to be.

**Canonical serialization to store**: exactly `{members, cardback, finishSettings}` — the full `Project` shape minus `nextMemberId` and
`mostRecentlySelectedSlot` (pure UI bookkeeping, meaningless across a
save/load boundary; `selected` inside each member is likewise reset to
`false` on every XML import today and should be dropped the same way here).
This is a strict superset, information-wise, of what XML 2.0 can currently
express — XML/decklist generation from stored state is a pure function of
this JSON, same as `generateXML()` already is a pure function of `Project` +
`cardDocuments` + `finishSettings` today. No new schema-drift risk: the
frontend already has a precedent for schema-validated JSON persisted outside
Redux (quicktype `Convert`/schema types backing `localStorage` for search
settings and favorites, `common/cookies.ts:40-123`, which already fail
gracefully to defaults on a validation mismatch) — the same pattern extends
cleanly to validating a loaded `SavedDeck.state` blob against the current
frontend's expected shape.

**Real gap worth flagging, not solving here**: a deck referencing
`LocalFile`-sourced card identifiers has no durable, backend-resolvable
identity — those images only exist as a live `FileSystemFileHandle` in the
browser that saved them. A saved deck built partly from local files will
load "successfully" (the identifiers round-trip) but those specific slots
will show as unresolvable images on a different device or after the local
folder is no longer granted. Propose a save-time warning, not a save-time
block (see §4).

**Size estimate**: no image bytes anywhere in `Project` — only string
identifiers (~30 char Drive-style ids) and small nested objects. ~250–350
bytes/populated slot → **~15–21 KB for a 60-card deck, ~25–35 KB for a
100-card deck.** Comfortably small for a Postgres `JSONField`.

## 3. Proposed model + endpoints

**Superseded by §8's zero-knowledge amendment**: the `SavedDeck` schema
below (plaintext `name`/`state` fields, server-side name-uniqueness
constraint) was the round-1 design. §8 replaces `name`+`state` with opaque
ciphertext/wrapped-key/nonce/salt-reference fields and removes the
uniqueness constraint entirely (no longer server-enforceable once titles
are encrypted). Left as-is below for the historical record of the original
survey — see §8 for what's actually being built.

**A note on prior art first**: `cardpicker/models.py:871-971` already
defines a `Project`/`ProjectMember` pair — `user` FK (CASCADE), `name`,
`cardback`, `cardstock`, normalized per-slot `ProjectMember` rows
(`card` FK, `query` CharField, `slot`, `face`). It even has a server-rendered
view and Bootstrap template (`accounts/views.py::projects`,
`accounts/templates/accounts/projects.html`). **All of it is unreachable**:
`MPCAutofill/urls.py:30` has `# path("accounts/", include("accounts.urls"))`
commented out, there is no REST API over these models at all (`cardpicker/urls.py`
has zero `Project`-related routes), and the schema itself is a poor match
for the actual frontend shape — flat `query` string vs. a structured
`SearchQuery` object, no `cardType`, no per-member `selectedImage`
distinct from `query`, foil/cardstock baked onto `Project` as columns
(migration-locked) rather than data. Extending it would mean keeping a
Django schema in lockstep with every future change to the frontend's Redux
shape. **Recommendation: build `SavedDeck` fresh as the brief specifies,
and separately flag `Project`/`ProjectMember`/the `accounts` app's dead
views for removal** (own cleanup task, out of scope for this HOLD) rather
than resurrecting them — two different "saved deck" concepts on the
backend would be a confusing, permanent wart.

```python
class SavedDeckKind(models.TextChoices):
    DECK = "deck"
    SNAPSHOT = "snapshot"


class SavedDeck(models.Model):
    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(to=User, on_delete=models.CASCADE, related_name="saved_decks")
    name = models.CharField(max_length=100)
    state = models.JSONField(default=dict, blank=True)
    kind = models.CharField(max_length=20, choices=SavedDeckKind.choices, default=SavedDeckKind.DECK)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=models.Q(kind=SavedDeckKind.DECK),
                name="saveddeck_owner_name_unique_for_decks",
            )
        ]
```

- **`on_delete=CASCADE`, not `SET_NULL`** — deliberately the opposite of
  `AbstractWeightedVote.user` (`models.py:588`, `SET_NULL`). Votes are kept
  after a user is deleted because they're catalog evidence; a saved deck has
  no value to anyone but its owner, so it should vanish with the account.
  This also means account deletion (not designed here — no self-serve
  account deletion exists anywhere in the app today, Discord or otherwise)
  gets deck cleanup for free once it ships.
- `is_public=False` default per the brief — private by default, no sharing
  surface designed or built here; the field is reserved so a future "share
  a read-only link" feature is additive, not a schema change.
- One additive migration (next is `0065`, following `0064_cardartistvote_vote_surface_and_more.py`).
- Naming: `SavedDeck` sidesteps the collision with both the frontend's own
  `Project` TypeScript type and the legacy backend `Project` model — using
  "Project" again here would have created a third meaning for the same word
  in one codebase.
- **Per-user cap — resolved**: a generous, configurable soft cap (env-driven
  setting, default `100` decks/user, same `env(..., default=...)` idiom as
  `MODERATORS_GROUP_NAME`/`CARD_REPORT_RATE`) enforced in `2/saveDeck/`'s
  create path only (rename/update never blocked by it), **counting only
  `kind=DECK` rows** — snapshot rows are entirely outside this cap (see the
  auto-snapshot bullet below for why). This is purely an abuse guard, not a
  storage concern — at 15–35 KB/deck even 100 decks/user is negligible — so
  it exists to stop a runaway script from becoming a moderation problem, not
  to manage disk. At-cap create attempts return a friendly, specific error
  ("You've reached the 100 saved deck limit — delete an old one to save a
  new one") rather than a generic 400.
- **`LocalFile`-sourced slots — resolved (warn, never block)**: `state`
  marks any slot whose `selectedImage` came from a `LocalFile` source with a
  `deviceLocal: true` flag at save time (a data convention within the
  existing JSONField, not a schema/column change). On load, a slot flagged
  `deviceLocal` renders an honest "this slot's image lived on the original
  device — re-pick" placeholder instead of attempting (and failing) to
  resolve the image, rather than showing a broken tile. See §4 for the
  save-time warning and §2 for the underlying gap this addresses.
- **Auto-snapshots — resolved: outside the deck cap, their own 5-slot FIFO
  ring per user, distinguishable in the model.** The `kind` field (above)
  is exactly this distinction: `2/saveDeck/`'s load-flow-triggered
  auto-snapshot calls (§4) pass `kind: "snapshot"` instead of the default
  `"deck"`. Rationale for keeping snapshots off the 100-deck cap entirely:
  the load-flow's safety guarantee ("skipping the snapshot is not an
  available choice for a logged-in user," §4) must be unblockable by quota
  — a user sitting at their 100-deck cap must still be able to load another
  saved deck safely — and a snapshot must never silently eat into the
  allowance the user thinks of as _their decks_. Enforcement: after any
  snapshot insert, `2/saveDeck/` prunes that owner's `kind=SNAPSHOT` rows
  down to the 5 most recently created (plain `created_at`-ordered delete of
  the rest) — a fixed, non-configurable ring, not a setting, since it's an
  implementation safety valve rather than a user-facing quota. The
  `UniqueConstraint` above is scoped to `kind=DECK` specifically so
  auto-generated snapshot names (e.g. two "Backup — {date}" saves on the
  same day) can never collide with each other or block the ring from
  filling. On "My Decks" (§4), snapshots render in their own collapsed
  group, separate from ordinary decks — visible and manageable, but never
  confused with something the user explicitly named and saved.

**Endpoints** (mirrors the existing `2/<verb>/` convention; auth is `request.user.is_authenticated`,
which is a strictly weaker version of the existing `require_moderator` decorator
— propose a sibling `require_authenticated` in `cardpicker/security.py` built the
same way, stacked with `@csrf_exempt` + `@reject_untrusted_origin` exactly like
every other session-consuming endpoint today):

| Endpoint        | Method | Body                                                          | Behaviour                                                                                                                                                                                                                                                                                                                                                                |
| --------------- | ------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `2/savedDecks/` | GET    | —                                                             | List `{key, name, kind, createdAt, updatedAt, approxSizeBytes}` for `request.user`, newest-updated first (client groups by `kind` for the collapsed snapshot section)                                                                                                                                                                                                    |
| `2/saveDeck/`   | POST   | `{key: string\|null, name, state, kind?: "deck"\|"snapshot"}` | Upsert: `key: null` creates; existing `key` updates in place if owned by `request.user`, else 403. `kind` defaults to `"deck"`; `"snapshot"` skips the 100-deck cap check and instead prunes the owner's snapshots to the newest 5 after insert. Name-uniqueness (scoped to `kind="deck"`) means a rename-into-collision 400s with a clear message, surfaced client-side |
| `2/loadDeck/`   | POST   | `{key}`                                                       | Returns `{name, state, createdAt, updatedAt}`; 403/404 if not owned                                                                                                                                                                                                                                                                                                      |
| `2/renameDeck/` | POST   | `{key, name}`                                                 | 403 if not owned; 400 on name collision                                                                                                                                                                                                                                                                                                                                  |
| `2/deleteDeck/` | POST   | `{key}`                                                       | Hard delete, 403 if not owned                                                                                                                                                                                                                                                                                                                                            |

All five are small, close to boilerplate CRUD once `require_authenticated`
exists — no consensus/moderation-style logic is needed anywhere here.

## 4. Frontend

**Login affordance placement**: mount `AuthWidget` (or a version stripped of
the moderator-suffix concern, though leaving it is harmless) inside
`ProjectNavbar` (`features/ui/Navbar.tsx`), in the existing `ms-auto` nav
group alongside the Download Manager and "Sources" buttons — gated by
`remoteBackendConfigured` exactly like those. `ProjectNavbar` is mounted once
in `Layout.tsx` and rendered on every page including `/editor`, so this is a
one-line relocation, not a new component, and immediately makes login visible
everywhere instead of only on `/whatsthat`.

**Auth framing — resolved**: the button reads **"Sign in"**, benefit-framed
(e.g. "Sign in to save decks & track your confirmations"), not "Sign in with
Discord" — Discord is presented as the _method_, surfaced at the auth step
itself (allauth's own login/consent redirect), never baked into the label.
This is a small `AuthWidget` copy change from today's Discord-branded button.
Ships Discord-only in v1, designed provider-agnostically (see §1's provider
mechanism note): Google is the noted v1.1 provider candidate, not built here.

**Save/load placement — resolved, supersedes the round-1 fold-into-Import
decision**: "My Decks" is a **top-level nav entry** in `ProjectNavbar`,
alongside Editor/Explore/Contributions/What's That Card?
(`features/ui/Navbar.tsx:78-135`) — rendered only when `whoami` reports an
authenticated session; the logged-out nav is byte-identical to today's.
Round 1 proposed folding "Load" into the Import dropdown instead; superseded
because a feature meant to persist across real sessions reads better as its
own destination (closer to how `/whatsthat` gets a full page) than as one
more entry in a menu that's otherwise about one-shot imports into the
_current_ project. "Save deck" stays in the editor's action cluster near the
existing Download controls, not in the Export dropdown — and is rendered
**only when authenticated**; a logged-out user sees nothing new in that
cluster at all (no disabled/greyed "Save" teasing a feature they can't use —
the affordance simply isn't there until they log in via the navbar widget).

**Save/load UX — propose explicit, not autosave**: every existing project
action (Export XML, Export PDF, Import CSV/XML/Text/URL) is an explicit,
user-triggered menu action, not automatic — autosave would be the first
background-write pattern in this frontend and introduces real edge cases for
free (debounce vs. rename races, "did I mean to overwrite my last save"
surprise, extra traffic on every keystroke-adjacent mutation). Concretely:

- **Save**: prompts for a name (pre-filled with the current deck's name if
  loaded from one) and calls `2/saveDeck/`. If the in-memory project
  contains any `LocalFile`-sourced slots, show a one-time inline warning
  ("N cards from local files won't be restorable on another device") —
  informational, not blocking — and stamps those slots `deviceLocal: true`
  in the saved `state` (see §3) so a later load elsewhere can render an
  honest re-pick placeholder instead of a broken tile.
- **Anonymous → login handoff**: on a `whoami` transition from unauthenticated
  to authenticated while the in-memory `Project` is non-empty, surface a
  one-time toast (reusing the existing `Toasts` system) offering "Save your
  current project as a new saved deck?" — an explicit adopt-by-save prompt,
  not a silent auto-save, since login can happen mid-session and an
  unprompted write would be a surprise. Declining leaves the in-memory
  project exactly as it was (nothing is lost either way — it's still live in
  Redux, just not yet persisted server-side).

**Load-into-editor flow — loss-proof by construction, not by dialog**:
loading a saved deck must never be able to silently discard the editor's
current content. The safety property is structural — something is always
preserved automatically — never a dialog a user can decline past. "Dirty"
means the in-memory project differs from whatever it was last loaded
from/saved as, or is simply non-empty with no prior save at all.

- **Editor empty** → load immediately, no prompt.
- **Editor dirty + logged in** → **auto-snapshot before loading,
  unconditionally**:
  - If the current content is itself an already-saved deck with unsaved
    changes: prompt offers **"Update {existing deck name}"** vs. **"Save as
    new snapshot"** — a choice of _where_ the safety copy goes, not
    _whether_ it happens.
  - If the current content was never saved: auto-snapshot it as
    **"Backup — {date}"**, with an inline rename affordance (the only
    prompt is ever "what do you want to call this," pre-filled with a sane
    default). Skipping the snapshot is not an available choice for a
    logged-in user. Only once the snapshot completes does the requested
    deck load in.
  - Both snapshot paths call `2/saveDeck/` with `kind: "snapshot"` (§3) —
    no new endpoint. Snapshots sit in their own 5-per-user FIFO ring
    entirely outside the 100-deck cap (§3), so this safety step can never
    be blocked by quota, and never eats into the user's own named-deck
    allowance.
- **Editor dirty + logged out** → today's existing confirm-overwrite
  warning, unchanged (there's nowhere to snapshot _to_ without an account).
  This asymmetry — logged-in users never lose work to a load, logged-out
  users get a plain "are you sure" — is a deliberate, natural sign-in
  incentive, not an oversight to fix later.
- **Load entry point**: one tap from the "My Decks" page — an **"Open in
  editor"** action per row, which runs the flow above and then navigates to
  `/editor`. Snapshots (`kind="snapshot"`) render in their own collapsed
  group on that page, separate from ordinary named decks (§3) — visible and
  loadable the same way, never confused with something the user explicitly
  saved.
- **Reverse breadcrumb**: the editor's action cluster (next to "Save")
  shows which saved deck, if any, the current editor content represents —
  e.g. "Editing: {deck name}" when loaded from/last saved as a specific
  `SavedDeck`, or "Unsaved project" otherwise. Updates on every Save/Load/
  rename, so it's always an accurate answer to "is this one of my saved
  decks, and which."

Not designed here: the exact prompt component/copy (the snapshot cap/kind
question from earlier rounds is resolved — see §3's auto-snapshot bullet).

## 5. Noted, not designed

- **Saved decks as Level 0's persistent substrate**: Level 0
  (`docs/features/printing-tags.md:237-261`) currently tracks "already
  resolved this printing-confirmation badge" in a module-level, non-persisted
  `Set<identifier>` that's deliberately session-scoped, not Redux, because it
  only needs to survive a page reload's worth of attention. Once a deck can
  be saved and reloaded across real sessions, that same badge-dismissal state
  becomes a natural candidate for living inside `SavedDeck.state` instead
  (per-deck, not global) — so a user's "already confirmed/declined" choices
  for a specific saved deck's slots persist the same way the deck itself
  does. Not designed here: it would need its own field in the stored state
  shape and a decision about whether dismissal state travels with XML export
  too (probably not — it's a UI aid, not deck content).
- **Logged-in confirmations as a vote-weight dimension**: elevated out of
  "noted, not designed" into its own full section this round — see §7 for
  weight tiers, the resolution-gate tradeoff analysis, cast-time recording,
  and the Sybil-honesty note. Still gated as a separate, later build from
  saved decks itself (§7's header).
- **Proposal B's per-card bleed overrides are deliberately device-local, NOT
  part of `SavedDeck` state**: `manualOverrides` (Auto/Force bleed/Force
  trimmed) lives in `projectSlice` + a keyed-by-card-identifier localStorage
  entry (`docs/proposals/proposal-b-bleed-normalization.md`), not the saved
  project JSON — it describes an image-rendering property of a card
  identifier, not a deck choice, so it doesn't travel with the deck the way
  card selections do. Folding it into `SavedDeck.state` later is possible
  (the shape is already a plain per-identifier map, trivial to embed) but
  isn't planned — noted here so this proposal's eventual builder doesn't
  re-derive the question.

## 6. Privacy

**What saving stores**: the deck name and the JSON project state (card
identifiers, search queries, cardstock/foil), tied to the Discord-derived
Django `User` row via `owner`. Nothing behavioral — no access logs, no
view/open counts, no IP address, no timestamp finer than the ordinary
`created_at`/`updated_at` bookkeeping every other model in this app already
has. Consistent with the project's existing zero-telemetry posture
(`docs/infrastructure.md:117-145` — Sentry and Google Analytics both fully
removed as a privacy decision).

**Retention/deletion**: user-deletable via `2/deleteDeck/`, hard delete —
same no-soft-delete, no-undo precedent as `moderationRemoveCard`/
`moderationRemoveDrive` (`docs/features/moderation.md:212-215`). Deleting the
underlying Discord-linked account (not built yet, for anyone) cascades to
every owned `SavedDeck` automatically via `on_delete=CASCADE` — nothing extra
to build for that case when it eventually ships.

**PIPEDA-relevant one-liner for the lawyer list**: _"Saved decks store only
user-provided deck contents (card selections and a user-chosen name) linked
to a Discord-authenticated account identifier; no browsing history, IP
addresses, or usage analytics are collected, and a user can delete any saved
deck — or, once account deletion ships, their entire account — at any time,
immediately and permanently."_

**Pre-existing gap surfaced by this survey, not caused by it**: the site's
Privacy Policy (`frontend/src/pages/about.tsx:91-142`) documents Google
Drive access in detail but has **no section at all for Discord/allauth
login**, which has been live for moderators since 2026-07-15. This feature
should add both a short Discord-login paragraph and a Saved Decks paragraph,
following the existing Google Drive section's "Data protection" / "Data
retention and deletion" bolded-subhead pattern (`about.tsx:115-131`) —
recommend covering the pre-existing Discord gap in the same policy update
rather than leaving it split across two changes.

## 7. Authed vote tier (new — build gated separately from saved decks)

Once ordinary users log in to save decks, an authenticated-but-non-moderator
vote is distinguishable from a fully anonymous one for free —
`AbstractWeightedVote.user` already exists, nullable, populated whenever a
session exists (§1). This section designs the weight consequence of that
distinction. It is deliberately a **separate, later build** from §3's
saved-decks endpoints — its own migration and consensus-math change, own PR,
own review — not bundled with this HOLD's core scope.

**Proposed tiers — resolved** (mirrors the existing three-tier shape already
implicit in the consensus model — `source`/`is_privileged`/`privileged_weight`,
`cardpicker/moderation.py`):

- anonymous: **1.0** (today's implicit baseline for an ordinary USER-source
  vote, unchanged)
- authenticated, not moderator: **1.5** — a fixed constant for v1, returned
  by `authed_vote_weight()` below. Headroom to **2.0** is explicitly
  reserved, not used yet: the range surfaced in the prior round was the
  ceiling for the _future_ account-standing extension (age/history/
  Dawid-Skene-style estimate) mentioned next, not a hint that 1.5 is
  provisional — 1.5 is the shipped value until that extension exists.
- moderator: **5.0** (matches the existing `VOTE_PRIVILEGED_WEIGHT` default,
  `docs/features/moderation.md:91-94`)

**One derivation function**: `authed_vote_weight(user)` (proposed alongside
`is_moderator`/`privileged_weight` in `cardpicker/moderation.py`) returns
**1.5** as a constant today, but is designed as the single hook point for
anything richer later — account age, saved-deck count, vote history.
Explicitly named as the **Dawid-Skene per-source-reliability hook**:
`docs/theory.md:292-299` already frames this whole pipeline as treating
"every source... as having some unknown, per-source reliability" and
estimating the true label jointly with it — today's weights (including this
one) are fixed/hand-set, and `authed_vote_weight()` is exactly where a
future _estimated_ (not hand-set) per-user reliability would plug in without
restructuring the surrounding consensus math.

**Resolution gate — resolved for v1: status quo, made config-switchable by
requirement.** Anonymous confirmations keep exactly today's behavior: any
single vote clearing the existing weight/share/human-backed thresholds
resolves, authenticated or not — the authed tier is a tie-breaker weight
among disagreeing voters this round, not a gate on anything. The two
alternatives considered (both rejected for v1, not deleted from the record):

- **Authed-required** — a winning consensus with no authenticated (or
  better) vote in the winning group parks `pending_approval`, reusing
  `require_privileged`'s existing `PENDING_PRIVILEGED` sentinel mechanism
  verbatim but with an "authenticated" bar instead of "moderator." Same code
  shape as the existing sensitive-tag gate, but a far bigger behavior
  change — it touches every ordinary vote, not just sensitive tags.
- **Anonymous-below-threshold** — anonymous votes keep weight 1.0 and can
  still resolve alone, but the resolution gets flagged e.g.
  "resolved-by-anonymous-only" for visibility/audit (a candidate future
  `docs/proposals/proposal-f-public-stats-page.md`-style aggregate) without
  blocking anything — a soft signal, not a gate.

**Required implementation constraint**: the gate mode and both tier weights
must route through `authed_vote_weight()` plus Django settings — an
env-driven flag mirroring `VOTE_PRIVILEGED_WEIGHT`'s idiom, e.g.
`AUTHED_VOTE_GATE_MODE` (`"status_quo"` / `"authed_required"` /
`"anonymous_below_threshold"`, default `"status_quo"`) and
`AUTHED_VOTE_WEIGHT` (default `1.5`) — never hand-coded branches scattered
through the consensus resolvers. This makes a future switch to either
rejected alternative a **settings/config change, not a migration or code
restructure**: the `PENDING_PRIVILEGED`-shaped machinery for
`authed_required` should exist in code, gated off by default, exactly the
way `require_privileged`'s parameter already defaults off for standard tags
today (§1).

**Revisit triggers** (not a schedule — conditions, not a date): (a) real
resolution volume once ordinary users are actually logging in in numbers —
today's status-quo choice is made with zero usage data, and should be
checked against what actually happens once saved decks ship and login
becomes common; (b) an observed manipulation attempt exploiting the
anonymous path specifically — the Sybil-honesty note below already assumes
this is _possible_; an actual instance, not a hypothetical one, is the
trigger to escalate the gate mode via the settings switch above.

**Cast-time recording, not resolution-time**: unlike `is_moderator` (checked
at resolution/request time, so revoking a moderator retroactively
de-privileges every past vote — §1, `docs/features/moderation.md:27-28`),
the tier behind this weight should be **recorded on the vote at cast time**
— a new field, e.g. `AbstractWeightedVote.account_tier`, alongside
`user`/`source`/`vote_surface` — not recomputed later. Deliberate contrast:
what the voter's authenticated status _was at the moment of voting_ is the
fact worth preserving, whereas moderator privilege is revocable authority
that should retroactively apply or un-apply. Recomputing this one instead
would let a since-deleted account's past votes silently reweight down over
time, or let a promoted/demoted moderator's past _ordinary_ votes silently
reweight — both wrong for what this tier is meant to represent.

**Sybil-honesty note**: Discord accounts are trivially mintable — no
verification beyond `SOCIALACCOUNT_AUTO_SIGNUP` (§1). This tier is
**convenience-trust** (distinguishing "bothered to log in" from "did not"),
never identity-trust, and must not be treated as a Sybil defense on its own.
Security continues to rest on the two mechanisms this pipeline already has:
machine cross-checks (independent OCR/phash/deduction engines) and cohort
revocation (`purge_machine_votes`'s existing `run_id`-scoped pattern,
already noted in `docs/theory.md:279-286` as generalizing to a suspect
_human_ cohort scoped by a `created_at`/`anonymous_id` window). An
authenticated tier changes vote weight; it never changes what happens once
a cohort turns out to be bad.

## 8. Zero-knowledge encryption amendment (2026-07-18)

**Supersedes §2's "Canonical serialization to store" and §3's `SavedDeck`
schema as originally specified.** The goal: the server maintainer must be
cryptographically unable to read saved deck contents. Discord OAuth remains
**identity only** — which account owns which blobs — and never touches key
material. This amendment replaces the plaintext-JSONField design; §2/§3's
original text above is left as-is (historical record of the round-1 survey,
per this doc's own convention of appending amendments rather than rewriting
approved text), superseded by everything below.

### Key design (client-side WebCrypto only)

- At **first save** (after Discord connect), the user creates a
  **passphrase**. Key derivation: PBKDF2-SHA256, iterations ≥600,000, a
  per-user random salt (server-stored — the salt itself is public-safe, it
  strengthens against precomputation, not secrecy; the iteration count used
  is stored alongside it so a future default increase never invalidates an
  existing user's derivation). The passphrase and every key derived from it
  **never leave the browser**.
- The **master key** is a separate, randomly-generated key (not the PBKDF2
  output itself) — generated exactly once, at first save, and never
  regenerated afterwards. The passphrase-derived key's only job is to
  **wrap** this master key (see "Recovery key" below for the second,
  independent way to wrap the same master key). Each deck gets its own
  random **DEK** (AES-256-GCM), wrapped by the master key at the time that
  deck is created. Because the master key never changes, **a passphrase
  change re-wraps only the one master key** (a single small ciphertext,
  stored on the user's crypto profile) under a freshly-derived
  passphrase key — it never touches any individual deck's DEK, and never
  re-encrypts any deck body.
- The **entire** deck payload is encrypted, **including the title** — there
  is no plaintext deck name anywhere server-side. Each server-side record
  is: opaque ciphertext + wrapped DEK + nonces (one for the payload's
  AES-GCM encryption, one for the DEK-wrap operation) + a reference to which
  per-user salt/iteration-count was used + timestamps. Nothing else.

### Recovery key (user-held, ZK-preserving)

At passphrase creation, also generate a random 256-bit **recovery key**
client-side, and wrap the _same_ master key with it — a second wrapped-key
blob, stored server-side, exactly as opaque as everything else (the server
holds a ciphertext it cannot unwrap without the recovery key, same as it
can't unwrap the passphrase-wrapped slot without the passphrase). Prompted
once: download as a text file (and shown for print/copy) with wording in
the spirit of _"Store this somewhere safe — it is the ONLY way to recover
your decks if you forget your passphrase."_ Never stored by us in
recoverable form, never re-showable after the creation prompt closes.
**Recovery flow**: paste the recovery key → unwrap the master key with it →
set a new passphrase → re-wrap **both** slots (passphrase slot and recovery
slot) under the new passphrase-derived key and a fresh recovery key
respectively — the underlying master key, and therefore every deck's DEK
and ciphertext, never changes; only what wraps the master key does. A
recovery key generated _before_ a later passphrase change still works,
because it wraps the master key directly, not anything passphrase-derived.

### Account reset (data-destroying, Discord-gated — the true last resort)

"Forgot passphrase, no recovery key" → re-authenticate via Discord (proves
account ownership, nothing more — Discord is still identity-only) →
explicit confirmation naming the actual consequence (e.g. _"this
permanently deletes your N saved decks"_) → delete every `SavedDeck` row
(ciphertext, wrapped keys, everything) → fresh start, a new passphrase/
recovery key pair on next save. **Account access is always recoverable
(via Discord); deck data never is without a user-held key (passphrase or
recovery key).** UI copy must keep this distinction sharp — losing the
passphrase never has to mean losing the _account_, only (absent a recovery
key) the _decks_.

### Explicitly rejected

Any admin-side or Discord-derived decryption/escrow path. Each would hand
the server a key path and void both the zero-knowledge guarantee and the
"ciphertext we cannot decrypt" legal posture below — there is no "moderator
override" or "owner can reset a user's passphrase" mechanism, by design,
and none should be added later without revisiting this entire amendment.

### Schema

The saved-deck table stores blobs, not structure — no card columns, no
searchable fields. Visible metadata, honestly documented: user id, blob
count/sizes, timestamps. `SavedDeck.name` (the plaintext `CharField` and
its `UniqueConstraint` from §3's original design) no longer exists — the
title lives inside the encrypted payload like everything else. A new
per-user crypto-profile record (salt, iteration count, the two wrapped
master-key slots — passphrase and recovery) is created at first save.

### UX

Passphrase set at first save, with this warning shown verbatim in spirit:
_"If you forget this passphrase, your saved decks are **permanently
unrecoverable** — we cannot reset it, by design."_ (softened in practice by
the recovery-key prompt immediately alongside it — the warning is about the
passphrase specifically, not about doom in general). Unlock prompt once per
session; unwrapped keys held in memory only (never `localStorage`, never
any persisted store); an explicit "Lock" action clears them immediately
without waiting for a session to end.

### Future work (design notes only, nothing built here)

- **Deck sharing**, if it ships, uses a **key-in-URL-fragment** scheme — the
  DEK travels in the fragment (`#...`), which browsers never send to the
  server, so a share link's server-side request never carries key material.
  Expanded into a full design below (see "PR-5, post-v1: per-deck share
  links").
- **WebAuthn passkey PRF** as an **optional additional** unwrap method
  someday — it would wrap the same master key a passphrase (or recovery
  key) does, not a separate one. Withdrawn as the primary/only mechanism;
  no survey needed now, since the passphrase + recovery-key design alone
  satisfies the goal.
- **Deck portability** (export/import, a standalone decrypt tool) as a
  formalization of what the zero-knowledge, server-unbound design already
  implies rather than a new capability. Expanded into a full design below
  (see "PR-6, post-v1: deck portability").

### PR-5, post-v1: per-deck share links (design only — owner-directed addendum, 2026-07-18; nothing built here)

Expands the "Deck sharing" future-work bullet above into a full design.
**Design only in this pass** — this section describes a later, separate
PR (PR-5); nothing here is built by the PRs in this amendment's own
sequencing (schema, sign-in relocation, API, crypto module, frontend
wiring). A new `SavedDeckShare` table (or equivalent) is additive to §3's
schema and does not require changing `SavedDeck`/`UserCryptoProfile` as
already specified above — shares reference an existing deck by id and
carry their own wrapped-key blob, so this doesn't preclude anything
already built in PR-1's schema.

- **Share creation (client-side)**: the owner picks one of their decks; the
  client generates a fresh random 256-bit `shareKey`, unwraps that deck's
  existing DEK (via the owner's already-unlocked master key), and
  re-wraps that same DEK with the new `shareKey` — a second, independent
  wrapping of the deck's DEK, alongside the owner's own master-key-wrapped
  copy. The client `POST`s a share record: `{shareId, deckRef, wrappedDEK_by_shareKey, wrapNonce, created, optional expiry}`. The
  `shareKey` itself goes **only** into the share link's URL fragment —
  `/shared/<shareId>#<shareKey-base64url>` — never in the path, query
  string, or request body, so it never reaches the server. The server
  stores one more opaque wrapped blob and learns nothing about the deck's
  contents or the owner's own keys.
- **Recipient flow (no account needed)**: opening the link, the client
  fetches ciphertext + the share's wrapped DEK by `shareId` alone (an
  unauthenticated, read-only lookup), unwraps the DEK using the fragment's
  `shareKey`, and decrypts locally. Render is read-only — a recipient
  never gets a wrapped-by-master-key copy, only the share-scoped one, so
  they can never derive the owner's master key or reach any of the
  owner's other decks.
- **Revocation**: the owner can list their own active shares per deck
  (`shareId`s + creation dates — metadata only, same honesty standard as
  the rest of this schema). Revoking a share is a `DELETE` of that share
  record — the link is dead for all future fetches immediately. A
  **paranoid option**, offered per-revoke as a checkbox, additionally
  rotates the deck's DEK: generate a fresh DEK, re-encrypt that one deck's
  ciphertext with it, and re-wrap the new DEK for the owner's own
  passphrase and recovery-key slots (any other still-active shares on that
  deck would need re-issuing too, since they wrap the old DEK — the UI
  must surface this rather than silently breaking other shares). This
  makes even already-captured key material for that share permanently
  useless. Honest limit, stated plainly in-product: revocation (with or
  without rotation) cannot recall content a recipient already viewed and
  saved elsewhere — true of every link-based sharing system, not a gap
  specific to this design.
- **Properties**: the master key never leaves its existing wrap chain (it
  is never itself shared or derivable from a share); shares are
  inherently per-deck, since they wrap that deck's DEK specifically, never
  the master key; a deck can have multiple independent, individually
  revocable shares outstanding at once; each `shareKey` is freshly random,
  **not** derived from the master key or from any other share's key, so
  leaking one share's key reveals nothing about the master key, the
  owner's other decks, or any other share.
- **Tests** (written now as the spec's requirement for PR-5, to implement
  when that PR is built): share round-trip (create → fetch by
  `shareId` + fragment key → decrypt correctly); a revoked share's fetch
  fails (or 404s) for all subsequent attempts; rotation-on-revoke renders
  a previously-captured `shareKey` unable to decrypt the rotated
  ciphertext; a leaked `shareKey` cannot decrypt or unwrap anything for
  any _other_ deck, shared or not.

### PR-6, post-v1: deck portability (design only — owner-directed addendum, 2026-07-18; nothing built here)

Formalizes what the ZK envelope already implies rather than adding new
capability: the crypto is deliberately **server-unbound** — no key
material anywhere in the wrap chain is held by, or derived from, anything
the server controls (Discord identity is identity-only; see "Key design"
above). Portability is a direct consequence of that design, embraced here
rather than something a later PR would need to retrofit or patch around.

- **Export**: an "Export my decks" action downloads the user's complete
  encrypted bundle — every `SavedDeck` row's ciphertext + wrapped DEK +
  nonces, both wrapped-master-key slots (passphrase and recovery) + their
  nonces, the salt and iteration count, and a `formatVersion` field — as
  one JSON file. Requires **no unlock**: it's the same opaque bytes the
  server already holds, so a user who has forgotten their passphrase can
  still export (they may remember it later, or still hold the recovery
  key; their data shouldn't be hostage to this site's own UI state).
- **Import**: accepts a previously-exported bundle on this instance or any
  compatible one (see "Format" below). Decryption happens entirely
  client-side, same passphrase-or-recovery-key flow as ever — the import
  step itself never needs server involvement beyond the ordinary
  `saveDeck`/`saveCryptoProfile` calls to persist what it decrypts.
  **Conflict rule for a same-instance re-import**: always import-as-new
  (each imported deck lands as its own row, snapshot-like), never silently
  overwrite an existing deck by matching key or name — there is no
  server-visible name to match against anyway (§8's Consequences), and
  overwriting would risk destroying newer data with a stale export.
- **Format**: the envelope is versioned from day one — every record
  carries `formatVersion` (starting at `1`) so a later format change
  never breaks reading an older export. The format itself is documented
  **publicly** in this spec (not just in code) specifically so that a
  fork, or a completely independent reimplementation, could read a user's
  exported bundle without needing this codebase at all. The format _is_
  the portability contract, not an implementation detail.
- **Standalone decrypt tool** (the trust anchor for this whole promise,
  mirroring the federation reference-hash tool's role for that feature): a
  tiny, single-file, dependency-minimal script — bundle in, passphrase (or
  recovery key) in, plaintext decks out — that a user can run **without
  this site, this codebase, or any server existing at all**. This is what
  makes "if this site vanishes tomorrow, your decks are still yours" a
  verifiable claim rather than a slogan. Specified now; built alongside
  PR-6.
- **Honest limits** (stated plainly, in-product and here): an exported
  bundle is offline-attackable — an attacker with the file can attempt
  unlimited offline passphrase guesses, so the bundle's real protection is
  passphrase strength plus PBKDF2 at ≥600,000 iterations. This is **not a
  new exposure** introduced by export — it's identical to what a server
  breach already exposes today (the server already stores exactly these
  same bytes); export just makes the existing exposure available to the
  user too, on purpose.
- **Explicitly rejected**: any form of server-bound key material (e.g. a
  server-held wrapping key, or tying decryption to a live session) to
  "simplify" export/import. That would introduce a new catastrophic-loss
  mode (the server becomes a single point of failure for data that's
  supposed to survive it), create hostage dynamics (the server operator
  could, even if only in principle, gate access to a user's own data), and
  directly contradict the zero-knowledge trust story this entire amendment
  is built on. Rejected outright, not just deprioritized.

### Consequences (written honestly)

- No server-side deck-derived feature is possible, ever: no deck search, no
  deck-derived stats (the public stats page,
  [`proposal-f-public-stats-page.md`](proposal-f-public-stats-page.md),
  correctly draws only from votes, never from deck contents).
- **No server-side name-uniqueness enforcement.** §3/decision 4's original
  design (a `UniqueConstraint` on `(owner, name)` scoped to `kind=deck`) is
  no longer possible once titles are encrypted — the server cannot compare
  plaintext names it never sees. Collision detection becomes a
  **client-side-only** check (the frontend decrypts its own deck list and
  can warn on a duplicate name before saving), not a data-integrity
  guarantee. This is a genuine behavior change from the original decision
  4/7, not an oversight.
- Lost passphrase **and** lost recovery key = lost data, deliberately —
  the account-reset flow above is destructive by design, not a hidden
  backdoor. There is no path that gives the server operator, an admin, or a
  moderator access to deck contents under any circumstance (see "explicitly
  rejected" above).

### Tests required

Encrypt/decrypt round-trip; wrong passphrase fails to unwrap; ciphertext
tamper → AES-GCM authentication failure (not a silent garbage decrypt);
passphrase change re-wraps the master key correctly without touching any
deck's DEK or ciphertext (the master key itself never changes — see "Key
design" above); recovery-key round-trip (forget passphrase → recover via
the recovery key → set a new passphrase); both passphrase and recovery
key lost → the account-reset flow deletes cleanly and a fresh pair issues
correctly on next save; a recovery key generated _before_ a later
passphrase change still unwraps the master key correctly (proving the
recovery slot is independent of passphrase-derived state).

### Legal data-inventory paragraph (for the owner's PIPEDA review; supersedes §6's original paragraph)

_"Saved decks are stored as ciphertext the server cannot decrypt — the
encryption passphrase, the user's recovery key, and every key derived from
either, exist only in the user's browser (or the user's own safekeeping,
for the recovery key) and are never transmitted or stored server-side in
recoverable form. The server retains only: the owning account's identifier,
an opaque encrypted blob per deck plus that deck's own wrapped encryption
key, two wrapped copies of the user's single master key (one recoverable
with the passphrase, one recoverable with the user's own recovery key —
neither readable by us), a per-user random salt and iteration count (not
secret; strengthens key derivation), and ordinary created/updated
timestamps. A user can delete any saved deck — or,
once account deletion ships, their entire account — at any time,
immediately and permanently. If both the passphrase and the recovery key
are lost, the affected decks are permanently unrecoverable by design; the
server operator has no admin-side decryption or escrow path and cannot
assist beyond a destructive account reset that deletes the unreadable data
and lets the user start fresh. Users may export their complete encrypted
data at any time (see PR-6, post-v1); the export format is public,
documented in this spec, so the user's data remains usable independent of
this site or its operator."_

## Effort estimate

| Piece                                                                                                           | Estimate     | Why                                                                                                                                                      |
| --------------------------------------------------------------------------------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SavedDeck` model + migration (incl. `kind` field + conditional unique constraint)                              | Small        | One additive migration, no data backfill                                                                                                                 |
| `require_authenticated` decorator + 5 endpoints (incl. cap check scoped to `kind=DECK` + snapshot FIFO pruning) | Small–Medium | Near-boilerplate CRUD; closely mirrors `require_moderator`/the moderation views' existing shape, no consensus logic needed                               |
| Backend tests                                                                                                   | Small–Medium | Mirrors `test_moderation_views.py`'s ownership/403 pattern, plus the FIFO-pruning and cap-scoping behavior                                               |
| Navbar login relocation + "Sign in" copy change                                                                 | Small        | `AuthWidget` already exists and works; mount-point + label change, not new UI                                                                            |
| "My Decks" top-level nav entry + page (decks + collapsed snapshot group)                                        | Medium       | New nav item + new page/panel + RTK Query endpoints (list/rename/delete/open-in-editor) — promoted out of the Import dropdown per §4's revised placement |
| Save UX (action-cluster button + name prompt + local-file warning)                                              | Small–Medium | New modal-ish prompt beside the existing Download controls, gated on whoami's authenticated flag                                                         |
| Load-into-editor safety flow (auto-snapshot + reverse breadcrumb)                                               | Small–Medium | New logic layered on the load path; snapshot creation calls `2/saveDeck/` with `kind: "snapshot"`, no new endpoint                                       |
| Anonymous→login adopt-prompt toast                                                                              | Small        | Reuses existing `Toasts` system                                                                                                                          |
| Frontend↔backend state-shape schema validation                                                                  | Small        | Extends the existing quicktype `Convert`/schema pattern already used for `localStorage`                                                                  |

Overall: **backend Small–Medium, frontend Medium.** §7 (authed vote tier) is
deliberately excluded from this table — its own migration and consensus
changes get scoped and estimated at its own, separate review, not bundled
with the saved-decks build.

## Decisions

1. **Proposal letter/queue slot — resolved.** This is **Proposal G**. Build
   order: after the current unified queue's small items land (E-1, E-2, the
   Level-2 grid fix, the audit pass, GIS error UX) and Proposal B's in-flight
   work finishes — G then builds **ahead of** C, E-3, and F, since it's
   user-facing value and those are polish. Backend (model + endpoints) is
   its own first PR; frontend is a second PR after that merges.
   **Queue cleared, 2026-07-18**: all of the above have since merged (E-1
   #61, E-2 #62, Level-2 grid fix #63, audit pass #64, GIS error UX #65,
   Proposal B core #66 + PR-1 #72, Proposal C part (a) #67) — nothing
   remains ahead of G in this build order.
2. **Where "Load"/"My Decks" lives — resolved, round 2 supersedes round 1.**
   Round 1 proposed folding it into the Import dropdown; round 2 replaces
   that with a **top-level nav entry**, rendered only when logged in (the
   logged-out nav is unchanged). "Save deck" stays in the editor's action
   cluster near Download, visible only when logged in. See §4 for the full
   placement writeup and its load-into-editor flow.
3. **Sharing — resolved.** `is_public` stays reserved in the schema,
   undesigned. No sharing ships in v1; unlisted share-links are the
   v1.1 candidate, to be revisited after the owner's legal consult — deck
   sharing has a materially different exposure profile than private
   storage, so it's deliberately not bundled into this pass.
4. **Per-user deck count — resolved.** Yes, a cap: a generous, configurable
   soft cap, default **100 decks/user**, purely as an abuse guard (not
   storage-driven — the 15–35 KB/deck math above stands), with a friendly
   at-cap message rather than a bare 400. Counts only `kind=DECK` rows (see
   decision 7) — see §3 for the enforcement point.
5. **`LocalFile`-sourced slots — resolved.** Warn at save, never block —
   the proposed tradeoff is accepted as-is. Additionally: mark such slots
   `deviceLocal: true` in the stored state so a load on another device shows
   an honest "this slot's image lived on the original device — re-pick"
   placeholder instead of a broken tile. See §3 (model) and §4 (UX) for the
   concrete mechanism.
6. **Auth framing — resolved.** The login button reads "Sign in"
   (benefit-framed), with Discord surfaced as the method at the auth step,
   not in the label. Ships Discord-only in v1; provider-agnostic by design
   (allauth's own multi-provider mechanism, §1); Google noted as the v1.1
   provider candidate, not built here.
7. **Auto-snapshots — resolved.** Outside the 100-deck cap entirely, in
   their own 5-per-user FIFO ring (oldest auto-pruned on each new snapshot),
   distinguished from ordinary decks by the model's new `kind` field
   (`SavedDeckKind.DECK`/`SNAPSHOT`). Rationale: the load-flow's safety
   snapshot (§4) must be unblockable by quota, and must never eat into the
   allowance a user thinks of as _their decks_. Snapshots list in their own
   collapsed group under "My Decks." See §3's auto-snapshot bullet and §4's
   load-into-editor flow for the concrete mechanism.
8. **Resolution gate (§7) — resolved for v1: status quo.** Anonymous
   confirmations retain today's exact gate behavior; the authed tier (see
   decision 9) is a tie-breaker weight this round, not a gate. Required so
   this doesn't calcify: the gate mode and both tier weights route through
   `authed_vote_weight()` plus settings (`AUTHED_VOTE_GATE_MODE`,
   `AUTHED_VOTE_WEIGHT`), so switching to `authed_required` or
   `anonymous_below_threshold` later is a config change, not a migration.
   Revisit triggers (conditions, not a schedule): real resolution volume
   once ordinary users are logging in at scale, or an _observed_
   manipulation attempt exploiting the anonymous path (not a hypothetical
   one). See §7 for the full tradeoff analysis kept on record.
9. **Authed vote weight (§7) — resolved: 1.5, constant.** Returned by
   `authed_vote_weight()` as a fixed value for v1. Headroom to 2.0 is
   reserved for the future account-standing extension (age/history/
   Dawid-Skene-style estimate), not a sign 1.5 is provisional.
10. **Zero-knowledge encryption (§8) — resolved, FINAL** (supersedes an
    earlier passphrase-only amendment and a subsequent passkey/PRF
    revision — both withdrawn, see §8). Saved decks are encrypted
    client-side (PBKDF2-SHA256 ≥600k iterations + per-user salt → AES-256-GCM
    master key; per-deck DEKs wrapped by it; the entire payload, including
    the title, is ciphertext server-side) so the server operator is
    cryptographically unable to read deck contents. A user-held recovery
    key (generated at passphrase creation, wraps the same master key) is
    the ZK-preserving recovery path; a Discord-gated, data-destroying
    account reset is the true last resort if both are lost. No admin-side
    or Discord-derived decryption/escrow path exists or will be added. See
    §8 for the full design, schema, UX, consequences, and required tests.

**Spec status: CLOSED.** All ten decisions above are resolved; no open
items remain in this document. §7 (authed vote tier) is fully specified but
stays a separate, later build from the saved-decks core (own migration, own
PR, own review) — it does not block Proposal G building at its queued slot.
