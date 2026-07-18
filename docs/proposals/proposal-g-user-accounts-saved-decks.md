As of: 2026-07-18
What this is: survey + HOLD proposal for opening the existing Discord login to
ordinary users and letting any logged-in user save/load named decks
server-side.
HOLD — build not started. Provisional letter/queue slot (see Open decisions
§1) — no visibility into a full approved proposal order from this session.

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
  checked at *resolution/request* time, never at login. "Logging in with
  Discord grants nothing by itself" (`docs/features/moderation.md:27-28`).
  Server-side enforcement is `cardpicker/security.py::require_moderator`
  (403s, not a redirect), stacked with `reject_untrusted_origin` (an
  `Origin`-header allowlist check standing in for CSRF, since every endpoint
  is `@csrf_exempt` for anonymous cross-origin clients) on every
  moderation-only view.
- **Frontend auth state**: no dedicated auth context/provider — it's one
  RTK Query cache entry. `GET 2/whoami/` → `{authenticated, username,
  moderator, discordEnabled, loginUrl, logoutUrl}` (`store/api.ts:206-218`,
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

## 2. Project state survey

**In-memory shape** — `Project` Redux slice (`store/slices/projectSlice.ts`,
type at `common/types.ts:120-144`):

```ts
export interface ProjectMember {
  query: SearchQuery;            // {cardType, query, expansionCode?, collectorNumber?}
  selectedImage?: string;        // card identifier, e.g. a Google Drive file id
  selected: boolean;             // multi-select UI state
}
export type SlotProjectMembers = { id: string } & { [face in Faces]: ProjectMember | null };
export type Project = {
  members: Array<SlotProjectMembers>;
  nextMemberId: number;           // UI bookkeeping (stable React key counter)
  cardback: string | null;
  mostRecentlySelectedSlot: Slot | null;  // transient UI state
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

**Canonical serialization to store**: exactly `{members, cardback,
finishSettings}` — the full `Project` shape minus `nextMemberId` and
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
class SavedDeck(models.Model):
    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(to=User, on_delete=models.CASCADE, related_name="saved_decks")
    name = models.CharField(max_length=100)
    state = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="saveddeck_owner_name_unique")]
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

**Endpoints** (mirrors the existing `2/<verb>/` convention; auth is `request.user.is_authenticated`,
which is a strictly weaker version of the existing `require_moderator` decorator
— propose a sibling `require_authenticated` in `cardpicker/security.py` built the
same way, stacked with `@csrf_exempt` + `@reject_untrusted_origin` exactly like
every other session-consuming endpoint today):

| Endpoint | Method | Body | Behaviour |
|---|---|---|---|
| `2/savedDecks/` | GET | — | List `{key, name, createdAt, updatedAt, approxSizeBytes}` for `request.user`, newest-updated first |
| `2/saveDeck/` | POST | `{key: string\|null, name, state}` | Upsert: `key: null` creates; existing `key` updates in place if owned by `request.user`, else 403. Name-uniqueness constraint means a rename-into-collision 400s with a clear message, surfaced client-side |
| `2/loadDeck/` | POST | `{key}` | Returns `{name, state, createdAt, updatedAt}`; 403/404 if not owned |
| `2/renameDeck/` | POST | `{key, name}` | 403 if not owned; 400 on name collision |
| `2/deleteDeck/` | POST | `{key}` | Hard delete, 403 if not owned |

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

**Save/load UX — propose explicit, not autosave**: every existing project
action (Export XML, Export PDF, Import CSV/XML/Text/URL) is an explicit,
user-triggered menu action, not automatic — autosave would be the first
background-write pattern in this frontend and introduces real edge cases for
free (debounce vs. rename races, "did I mean to overwrite my last save"
surprise, extra traffic on every keystroke-adjacent mutation). Concretely:
- **Save**: a new entry in the existing `Export.tsx` dropdown ("Save to My
  Decks"), prompting for a name (pre-filled with the current deck's name if
  loaded from one) and calling `2/saveDeck/`. If the in-memory project
  contains any `LocalFile`-sourced slots, show a one-time inline warning
  ("N cards from local files won't be restorable on another device") —
  informational, not blocking.
- **Load**: a new "My Decks" modal (same idiom as `ImportXML`'s existing
  modal-based import flow), listing `2/savedDecks/` results with
  load/rename/delete actions per row, reachable from a new nav or Import-menu
  entry (exact placement is an open decision, §Open decisions).
- **Anonymous → login handoff**: on a `whoami` transition from unauthenticated
  to authenticated while the in-memory `Project` is non-empty, surface a
  one-time toast (reusing the existing `Toasts` system) offering "Save your
  current project as a new saved deck?" — an explicit adopt-by-save prompt,
  not a silent auto-save, since login can happen mid-session and an
  unprompted write would be a surprise. Declining leaves the in-memory
  project exactly as it was (nothing is lost either way — it's still live in
  Redux, just not yet persisted server-side).

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
- **Logged-in confirmations as a future `is_established` vote dimension**:
  `docs/theory.md:287-290` already earmarks "trust tiers" as "one more
  vote-tuple dimension alongside source and confidence," not a parallel trust
  system. Once ordinary users routinely log in to save decks, an
  authenticated (but non-moderator) vote becomes distinguishable from a
  fully anonymous one for free — `AbstractWeightedVote.user` already exists
  and is already nullable-and-populated wherever a session exists (per §1).
  A future `is_established` boolint/weight nudge could reward votes cast by
  an account with some history (e.g. N+ saved decks, or account age) without
  touching the moderator-privilege gate at all — a separate axis, same
  weighted-consensus machinery. Not designed here: needs its own threshold
  and abuse-model thinking (freshly-created Discord accounts shouldn't get a
  trust bump for free).

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

**PIPEDA-relevant one-liner for the lawyer list**: *"Saved decks store only
user-provided deck contents (card selections and a user-chosen name) linked
to a Discord-authenticated account identifier; no browsing history, IP
addresses, or usage analytics are collected, and a user can delete any saved
deck — or, once account deletion ships, their entire account — at any time,
immediately and permanently."*

**Pre-existing gap surfaced by this survey, not caused by it**: the site's
Privacy Policy (`frontend/src/pages/about.tsx:91-142`) documents Google
Drive access in detail but has **no section at all for Discord/allauth
login**, which has been live for moderators since 2026-07-15. This feature
should add both a short Discord-login paragraph and a Saved Decks paragraph,
following the existing Google Drive section's "Data protection" / "Data
retention and deletion" bolded-subhead pattern (`about.tsx:115-131`) —
recommend covering the pre-existing Discord gap in the same policy update
rather than leaving it split across two changes.

## Effort estimate

| Piece | Estimate | Why |
|---|---|---|
| `SavedDeck` model + migration | Small | One additive migration, no data backfill |
| `require_authenticated` decorator + 5 endpoints | Small–Medium | Near-boilerplate CRUD; closely mirrors `require_moderator`/the moderation views' existing shape, no consensus logic needed |
| Backend tests | Small–Medium | Mirrors `test_moderation_views.py`'s ownership/403 pattern (owner-only access is the only real logic to test) |
| Navbar login relocation | Small | `AuthWidget` already exists and works; this is a mount-point change, not new UI |
| Save UX (dropdown entry + name prompt + local-file warning) | Small–Medium | New modal-ish prompt, reuses `Export.tsx`'s existing dropdown pattern |
| Load UX ("My Decks" modal + list/rename/delete) | Medium | New modal, new RTK Query endpoints, closest existing analog is `ImportXML`'s modal but with list/manage actions added |
| Anonymous→login adopt-prompt toast | Small | Reuses existing `Toasts` system |
| Frontend↔backend state-shape schema validation | Small | Extends the existing quicktype `Convert`/schema pattern already used for `localStorage` |

Overall: **backend Small–Medium, frontend Medium.**

## Open decisions

1. **Proposal letter/queue slot** — named this doc `proposal-g-*` continuing
   the `A`/`D`/`F` sequence visible in git history, but this session has no
   visibility into a full approved proposal order (only `docs/proposals/proposal-f-public-stats-page.md`
   exists on disk, noting it's "queued after Proposal E" — that ordering
   record itself isn't in a file this session can read). Confirm/reassign
   the letter and queue position.
2. **Where "Load"/"My Decks" lives** — proposed folding it into the existing
   Import dropdown to avoid new nav chrome, but a feature meant to persist
   across real sessions might deserve its own nav entry/page instead (closer
   to how `/whatsthat` gets a full page rather than a menu item). Not
   resolved here.
3. **Sharing** — the brief is private-by-default and this proposal reserves
   `is_public` but designs no sharing endpoint/UI at all. Confirm whether
   that's wanted on any timeline, since it changes whether `is_public` needs
   a companion "public decks" list endpoint eventually.
4. **Per-user deck count** — no cap proposed. At 15–35 KB/deck this is not
   storage-driven, but an unbounded "My Decks" list is a UX question (e.g. a
   soft warning past some count) — not designed here.
5. **`LocalFile`-sourced slots in a saved deck** — proposed a save-time
   warning (not a block) per §4; confirm that's the right tradeoff versus,
   e.g., excluding those slots from the save entirely.
