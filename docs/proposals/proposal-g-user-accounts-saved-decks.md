As of: 2026-07-18
What this is: survey + HOLD proposal for opening the existing Discord login to
ordinary users and letting any logged-in user save/load named decks
server-side.
HOLD — build not started. Proposal G; queue position, nav placement, sharing,
deck cap, LocalFile handling, and auth framing all confirmed (see Decisions).
The authed vote-tier weighting (§7) is scoped but deliberately gated as its
own later, separate build — not part of this HOLD's core scope.

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
- **Per-user cap — resolved**: a generous, configurable soft cap (env-driven
  setting, default `100` decks/user, same `env(..., default=...)` idiom as
  `MODERATORS_GROUP_NAME`/`CARD_REPORT_RATE`) enforced in `2/saveDeck/`'s
  create path only (rename/update never blocked by it). This is purely an
  abuse guard, not a storage concern — at 15–35 KB/deck even 100 decks/user
  is negligible — so it exists to stop a runaway script from becoming a
  moderation problem, not to manage disk. At-cap create attempts return a
  friendly, specific error ("You've reached the 100 saved deck limit —
  delete an old one to save a new one") rather than a generic 400.
- **`LocalFile`-sourced slots — resolved (warn, never block)**: `state`
  marks any slot whose `selectedImage` came from a `LocalFile` source with a
  `deviceLocal: true` flag at save time (a data convention within the
  existing JSONField, not a schema/column change). On load, a slot flagged
  `deviceLocal` renders an honest "this slot's image lived on the original
  device — re-pick" placeholder instead of attempting (and failing) to
  resolve the image, rather than showing a broken tile. See §4 for the
  save-time warning and §2 for the underlying gap this addresses.

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

**Auth framing — resolved**: the button reads **"Sign in"**, benefit-framed
(e.g. "Sign in to save decks & track your confirmations"), not "Sign in with
Discord" — Discord is presented as the *method*, surfaced at the auth step
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
*current* project. "Save deck" stays in the editor's action cluster near the
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
    new snapshot"** — a choice of *where* the safety copy goes, not
    *whether* it happens.
  - If the current content was never saved: auto-snapshot it as
    **"Backup — {date}"**, with an inline rename affordance (the only
    prompt is ever "what do you want to call this," pre-filled with a sane
    default). Skipping the snapshot is not an available choice for a
    logged-in user. Only once the snapshot completes does the requested
    deck load in.
  - Both snapshot paths reuse `2/saveDeck/` verbatim (§3) — no new endpoint.
- **Editor dirty + logged out** → today's existing confirm-overwrite
  warning, unchanged (there's nowhere to snapshot *to* without an account).
  This asymmetry — logged-in users never lose work to a load, logged-out
  users get a plain "are you sure" — is a deliberate, natural sign-in
  incentive, not an oversight to fix later.
- **Load entry point**: one tap from the "My Decks" page — an **"Open in
  editor"** action per row, which runs the flow above and then navigates to
  `/editor`.
- **Reverse breadcrumb**: the editor's action cluster (next to "Save")
  shows which saved deck, if any, the current editor content represents —
  e.g. "Editing: {deck name}" when loaded from/last saved as a specific
  `SavedDeck`, or "Unsaved project" otherwise. Updates on every Save/Load/
  rename, so it's always an accurate answer to "is this one of my saved
  decks, and which."

Not designed here: the exact prompt component/copy, and whether
"Backup — {date}" auto-snapshots should count against the 100-deck soft cap
(§3/decision 4) — leaning yes, a snapshot is an ordinary `SavedDeck` row —
but not decided in this pass (see Decisions).

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

## 7. Authed vote tier (new — build gated separately from saved decks)

Once ordinary users log in to save decks, an authenticated-but-non-moderator
vote is distinguishable from a fully anonymous one for free —
`AbstractWeightedVote.user` already exists, nullable, populated whenever a
session exists (§1). This section designs the weight consequence of that
distinction. It is deliberately a **separate, later build** from §3's
saved-decks endpoints — its own migration and consensus-math change, own PR,
own review — not bundled with this HOLD's core scope.

**Proposed tiers** (mirrors the existing three-tier shape already implicit
in the consensus model — `source`/`is_privileged`/`privileged_weight`,
`cardpicker/moderation.py`):
- anonymous: **1.0** (today's implicit baseline for an ordinary USER-source
  vote, unchanged)
- authenticated, not moderator: **~1.5–2.0** — exact value is an owner call
  at doc review, not resolved here; the range, not a single number, is what
  this doc commits to
- moderator: **5.0** (matches the existing `VOTE_PRIVILEGED_WEIGHT` default,
  `docs/features/moderation.md:91-94`)

**One derivation function**: `authed_vote_weight(user)` (proposed alongside
`is_moderator`/`privileged_weight` in `cardpicker/moderation.py`) returns the
constant tier value above today, but is designed as the single hook point
for anything richer later — account age, saved-deck count, vote history.
Explicitly named as the **Dawid-Skene per-source-reliability hook**:
`docs/theory.md:292-299` already frames this whole pipeline as treating
"every source... as having some unknown, per-source reliability" and
estimating the true label jointly with it — today's weights (including this
one) are fixed/hand-set, and `authed_vote_weight()` is exactly where a
future *estimated* (not hand-set) per-user reliability would plug in without
restructuring the surrounding consensus math.

**Resolution-gate analysis — tradeoffs presented, nothing decided**: does an
anonymous solo vote still get to resolve a machine suggestion once an authed
tier exists?
- **Status quo**: any single vote clearing today's weight/share/human-backed
  thresholds resolves, anonymous or not — unchanged. Zero new risk, but the
  authed tier becomes purely a tie-breaker weight among disagreeing voters,
  never a gate on anything.
- **Authed-required**: a winning consensus with no authenticated (or better)
  vote in the winning group parks `pending_approval`, reusing
  `require_privileged`'s existing `PENDING_PRIVILEGED` sentinel mechanism
  verbatim but with an "authenticated" bar instead of "moderator." Same code
  shape as the existing sensitive-tag gate (reuse, not new machinery), but a
  far bigger behavior change — it touches every ordinary vote, not just
  sensitive tags — and needs its own abuse-model thinking first (see Sybil
  note below) before it's safe to flip.
- **Anonymous-below-threshold**: anonymous votes keep weight 1.0 and can
  still resolve alone, but the resolution gets flagged e.g.
  "resolved-by-anonymous-only" for visibility/audit (a candidate future
  `docs/proposals/proposal-f-public-stats-page.md`-style aggregate) without
  blocking anything — a soft signal, not a gate.

This doc takes no position among the three — flagged as the single biggest
open question this section raises (see Decisions).

**Cast-time recording, not resolution-time**: unlike `is_moderator` (checked
at resolution/request time, so revoking a moderator retroactively
de-privileges every past vote — §1, `docs/features/moderation.md:27-28`),
the tier behind this weight should be **recorded on the vote at cast time**
— a new field, e.g. `AbstractWeightedVote.account_tier`, alongside
`user`/`source`/`vote_surface` — not recomputed later. Deliberate contrast:
what the voter's authenticated status *was at the moment of voting* is the
fact worth preserving, whereas moderator privilege is revocable authority
that should retroactively apply or un-apply. Recomputing this one instead
would let a since-deleted account's past votes silently reweight down over
time, or let a promoted/demoted moderator's past *ordinary* votes silently
reweight — both wrong for what this tier is meant to represent.

**Sybil-honesty note**: Discord accounts are trivially mintable — no
verification beyond `SOCIALACCOUNT_AUTO_SIGNUP` (§1). This tier is
**convenience-trust** (distinguishing "bothered to log in" from "did not"),
never identity-trust, and must not be treated as a Sybil defense on its own.
Security continues to rest on the two mechanisms this pipeline already has:
machine cross-checks (independent OCR/phash/deduction engines) and cohort
revocation (`purge_machine_votes`'s existing `run_id`-scoped pattern,
already noted in `docs/theory.md:279-286` as generalizing to a suspect
*human* cohort scoped by a `created_at`/`anonymous_id` window). An
authenticated tier changes vote weight; it never changes what happens once
a cohort turns out to be bad.

## Effort estimate

| Piece | Estimate | Why |
|---|---|---|
| `SavedDeck` model + migration | Small | One additive migration, no data backfill |
| `require_authenticated` decorator + 5 endpoints | Small–Medium | Near-boilerplate CRUD; closely mirrors `require_moderator`/the moderation views' existing shape, no consensus logic needed |
| Backend tests | Small–Medium | Mirrors `test_moderation_views.py`'s ownership/403 pattern (owner-only access is the only real logic to test) |
| Navbar login relocation + "Sign in" copy change | Small | `AuthWidget` already exists and works; mount-point + label change, not new UI |
| "My Decks" top-level nav entry + page | Medium | New nav item + new page/panel + RTK Query endpoints (list/rename/delete/open-in-editor) — promoted out of the Import dropdown per §4's revised placement |
| Save UX (action-cluster button + name prompt + local-file warning) | Small–Medium | New modal-ish prompt beside the existing Download controls, gated on whoami's authenticated flag |
| Load-into-editor safety flow (auto-snapshot + reverse breadcrumb) | Small–Medium | New logic layered on the load path; snapshot creation reuses `2/saveDeck/` verbatim, no new endpoint |
| Anonymous→login adopt-prompt toast | Small | Reuses existing `Toasts` system |
| Frontend↔backend state-shape schema validation | Small | Extends the existing quicktype `Convert`/schema pattern already used for `localStorage` |

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
   at-cap message rather than a bare 400. See §3 for the enforcement point.
   Whether auto-snapshots from §4's load flow count against this cap is
   still open (leaning yes, not decided).
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

**Still genuinely open** (deliberately undecided, not oversights):
- §7's resolution-gate choice — status quo vs. authed-required vs.
  anonymous-below-threshold — is presented with tradeoffs and left
  unresolved on purpose; it's the single biggest open question this spec
  raises.
- §7's exact authed-tier weight value (range given: ~1.5–2.0) is an owner
  call at doc review, not fixed here.
- Whether load-flow auto-snapshots (§4) count against the 100-deck cap
  (§3/decision 4) — leaning yes, not decided.
