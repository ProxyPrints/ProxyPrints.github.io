# Moderation layer (stage 1)

Sensitive-content moderation built ON the shipped vote-consensus system
([[printing-tags.md]]) — extended, not forked. Four pieces: Discord-authenticated
moderators, a sensitive-tag class whose resolution requires a privileged
co-sign, a card report button feeding an audit trail, and a moderator-only
approval queue. One deliberately small consequence: cards resolved as NSFW
stay out of search by default, with a visible opt-in toggle.

## The mental model

Ordinary voting is untouched. Anyone can still vote on any tag, anonymously,
exactly as before — including the sensitive ones. What changes is what a
crowd's consensus is allowed to _do_: for a tag marked sensitive, a consensus
that clears every normal threshold parks as **`pending_approval`** instead of
resolving, until a privileged vote (a moderator's or an admin's) backs the
winning side. Approval isn't a special action — it's an ordinary vote that
happens to be privileged, so the pending → resolved transition runs through
the exact same consensus pass, `Card.tags` merge, and Elasticsearch reindex
as any other resolution.

## Who is a moderator

Membership of the **`MODERATORS_GROUP_NAME`** Django auth group (default
`"Moderators"`) — that's the entire definition, checked at _resolution_ time
(`cardpicker/moderation.py`), so revoking a moderator retroactively
de-privileges every vote they ever cast. Logging in with Discord grants
nothing by itself.

The grant mechanism is deliberately pluggable — everything consumes the group
through `is_moderator` / `get_moderator_user_ids`. The sketched follow-up for
a federation-wide moderator roster: add the `guilds.members.read` OAuth scope
and sync group membership from a role (e.g. `@Moderator`) in the project's
Discord server at login, so every instance independently verifies the same
authority and granting/revoking is one Discord role assignment. The portable
identity is the Discord user id, which allauth already stores in
`SocialAccount.uid` — no schema work needed when that lands. Note the
complementary path: cross-instance moderation _effects_ travel via federated
verdict exchange ([[../federation-v1.md]], v1.1), which needs no cross-instance
logins at all.

## Auth (django-allauth + Discord)

- Configured entirely from env: `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`.
  Absent (e.g. dev) = the provider app isn't installed, `/accounts/discord/login/`
  404s, whoami reports `discordEnabled: false`, nothing crashes. App-in-settings
  credentials (`SOCIALACCOUNT_PROVIDERS`) — no `SocialApp` DB row, no
  `django.contrib.sites`.
- `GET 2/whoami/` → `{authenticated, username, moderator, discordEnabled, loginUrl, logoutUrl}`. Frontend gating is presentation only; the moderation
  endpoint enforces the group server-side.
- Login/logout links carry `?next=<frontend URL>` and round-trip back;
  `accounts/adapter.py::FrontendRedirectAccountAdapter` validates `next`
  against the hosts in `CORS_ALLOWED_ORIGINS`, so the redirect allowlist can
  never drift from the CORS one. `ACCOUNT_LOGOUT_ON_GET=True` is a deliberate
  tradeoff: logout works as a plain link (needed for the round-trip), and the
  worst a hostile page can do is force a logout — a nuisance, not an
  escalation.
- Cross-origin session: the cookie must ride from the frontend origin to
  `api.proxyprints.ca`, so production needs `SESSION_COOKIE_SAMESITE=None`,
  `SESSION_COOKIE_SECURE=True`, `CORS_ALLOW_CREDENTIALS=True` (defaults suit
  same-site localhost dev). Only fetches that opt into `credentials:'include'`
  are affected — whoami, reportCard, and every moderationQueue/moderationDrives\*/
  moderationRemoveCard/moderationRemoveDrive call (plus the moderation
  queue's approve/reject votes); every anonymous surface is byte-identical.

## CSRF: why csrf_exempt stays, and what replaces it

Every API endpoint here is `@csrf_exempt` because the primary clients are
anonymous cross-origin browsers with no Django CSRF cookie to round-trip —
votes are keyed by a client-generated `anonymous_id`, not a session. That was
safe while nothing read `request.user`. The moderator session changes that:
a `SameSite=None` cookie plus `csrf_exempt` POSTs would let any website forge
privileged votes from a logged-in moderator's browser.

`cardpicker/security.py::reject_untrusted_origin` closes exactly that hole:
browsers unconditionally attach an `Origin` header to cross-origin POSTs and
a page cannot forge it, so POSTs whose Origin is present but not in
`CORS_ALLOWED_ORIGINS` (∪ the backend's own origin) are rejected with 403.
Applied to every session-consuming POST (the three vote submit views,
`reportCard`, `moderationQueue`, `moderationDrives`, `moderationDriveCards`,
`moderationRemoveCard`, `moderationRemoveDrive`). Non-browser clients send no Origin at all
and keep exactly today's trust level; GET endpoints (whoami) change no state
and need nothing.

## The gate (vote plumbing)

- `AbstractWeightedVote.user` — nullable FK set (alongside `anonymous_id`,
  never instead of it) when the submitting request carried an authenticated
  session. One additive migration covers all three vote tables.
- `VoteTuple.is_privileged` mirrors the `is_human_backed` pattern: computed by
  the tag-consensus wrappers as "source==admin OR vote.user currently in the
  moderators group". Privileged votes weigh `VOTE_PRIVILEGED_WEIGHT`
  (default = the admin weight, 5) via max() with their source weight — a lone
  moderator clears the threshold like a lone admin.
- `resolve_weighted_consensus(..., require_privileged=True)`: a winner that
  clears weight/share/human-backed but has no privileged vote **in the winning
  group** returns the `PENDING_PRIVILEGED` sentinel instead of the key.
  In-group, not merely present-among-the-votes: a moderator voting _against_
  the crowd must not count as the co-sign that lets the crowd's outcome
  through (their heavier vote usually flips or contests the result through
  the normal math anyway). Persisted as `pending_approval` in
  `Card.tag_vote_statuses`; `Card.tags` untouched, so pending has zero search
  consequences.
- Wired only for `Tag.moderation_class == "sensitive"` and through **both**
  resolution paths: the interactive one (`resolve_tag` /
  `resolve_and_persist_tag_votes`) and the batched re-scan overlay
  (`get_resolved_tag_overlay`) — skipping the second would let a scheduled
  `update_database` re-scan apply the very change the interactive path held
  for approval. Standard tags are byte-identical (the gate parameter defaults
  off; no pre-existing test file was modified — the untouched consensus suites
  are the regression proof).
- Privileged _weight_ is wired for tag consensus only this stage; printing and
  artist votes record `user` (the field lives on the shared abstract base) but
  their weight math is untouched. Extending them later needs no migration.

## Sensitive taxonomy

`Tag.moderation_class` (`standard` | `sensitive`, default standard).
`manage.py seed_sensitive_tags` seeds five (command, not data migration —
same rationale as the other taxonomies, see [[printing-tags.md]]):

| name                | display name        | report reason |
| ------------------- | ------------------- | ------------- |
| `NSFW`              | NSFW                | `nsfw`        |
| `low-res`           | Low quality         | `low_quality` |
| `incorrect-info`    | Incorrect card info | `wrong_card`  |
| `appropriate-bleed` | Appropriate Bleed   | — (no chip)   |
| `AI-Generated`      | AI-Generated        | — (no chip)   |

`appropriate-bleed` is deliberately the **positive** framing ("verified to
include the full bleed margin required for printing") rather than a negative
"missing-bleed": upstream drives require appropriate bleed on every card, so
the state worth verifying is the positive one — an untagged card reads as
"not yet verified", and a definitive "lacks bleed" verdict is still
expressible as the tag resolving REJECT through the same vote mechanics.
It's sensitive because that verification is exactly a moderator co-sign: the
crowd votes it via the card modal's tag picker, consensus parks as
`pending_approval`, and a moderator confirms it in the queue. No report-button
chip (it's a verification workflow, not a complaint) and no search consequence;
drive-level checks can select verified cards via the existing `includesTags`
filter.

`NSFW` deliberately reuses the pre-existing `cardpicker.constants.NSFW` name:
filename-bracket tagging (`[NSFW]`) and the frontend's default
`excludesTags: ["NSFW"]` already speak that exact string, and a lowercase twin
would split mature-content state across two names. Once seeded, the real row
replaces the synthetic pseudo-tag in the tag matcher (real rows win the
lowercased key). Seeding upgrades a pre-existing standard row to sensitive but
never clobbers a manually edited `display_name`. Names are immutable
federation contracts.

`AI-Generated` (public issue #261, 2026-07-21) was upgraded to sensitive from
its pre-existing `standard` row (seeded by `cardpicker.default_tags. DEFAULT_TAGS` for a different, orthogonal reason — filename-bracket tagging,
e.g. `[Midjourney]`, applies it directly at import time, exactly like
`[NSFW]` above, untouched by this change). The upgrade exists because
`cardpicker.local_detect_ai_art` now casts real machine votes for it — a
calculator that scans already-stored OCR evidence (artist credit line, legal
line, collector line) for known AI-generator marker strings (Midjourney,
DALL-E, Stable Diffusion, SDXL, Gemini, Imagen, Adobe Firefly, Leonardo AI,
NightCafe, Bing Image Creator, "AI art"/"AI generated" — deliberately
excluding generator-SITE/tool names like CardConjurer, which indicate a
rendering tool usable with ordinary human art, not AI provenance) under its
own machine identity (`ai-art-detector-v1`, `VoteSource.OCR`). Same
`appropriate-bleed` logic applies here, doubled: a lone machine vote can
never resolve any tag at all (the shared human-backed gate), and even a
confident crowd consensus on this one specifically still needs a moderator
co-sign before it goes live — publicly labelling a real human artist's work
as AI-generated is a reputational harm serious enough to warrant the same
"machine can flag it, human must confirm it" treatment as the mature-content
and quality tags above, not just the ordinary crowd threshold. Positive-
detection only: a missing marker proves nothing, so this calculator never
casts a negative vote, only `APPLY`.

Two knock-ons worth knowing: the seeded tags become visible/votable in the
card modal's tag grid for everyone (intended — votes accumulate as pending),
and filename-bracket `[NSFW]` tagging at scan time remains ungated (the gate
governs vote-driven changes; the overlay exclusion means a crowd can't
_remove_ a filename NSFW without a moderator either).

## Report button

Flag button on the card detail modal → chips: NSFW / Low quality / Wrong card
info / Broken image / Other (+free text ≤280 chars). `POST 2/reportCard/`
always writes a **`CardReport`** audit row (card, anonymous_id, nullable user,
reason, text, created_at — ModelAdmin filterable by reason/date, searchable by
card); the three tag-mapped reasons also cast a positive `CardTagVote` through
the same write path as `2/submitTagVote/` (extracted helper — the two entry
points cannot drift), in one transaction. Unseeded tag = report still lands,
vote skipped. Broken image / Other are report-row-only. Rate limit:
`CARD_REPORT_RATE` (default `10/d`) per anonymous_id, polite 429 in the UI.

## Moderation tab

`whatsthat.tsx` (`ModerationTab.tsx`) grows a **Moderation** tab alongside the
ordinary Question Feed tab, rendered only when whoami says moderator
(presentation; every endpoint below 403s non-moderators server-side via
`require_moderator`). It has two independent sub-tabs — **Reports** and
**Drives** — switched with a plain `Tab.Container`, the same idiom the
pre-redesign printing/artist/tag tab switcher used.

Report review used to be injected into the single-question feed itself as a
moderator-only "tier 3" (between contested and fresh-unresolved), which meant
any pending report displaced a moderator's ordinary tagging work for as long
as it stayed pending. Reverted — `cardpicker/question_feed.py`'s
`get_next_question_feed_item` never serves a `pending_approval` pair any
more, for any role; see that module's docstring for the full history. Report
review now lives only in the Moderation tab, so the two are always
switchable, never one hijacking the other.

### Reports (`ReportsPanel.tsx`)

`POST 2/moderationQueue/` serves `pending_approval` pairs most-reported first
(count of matching-reason CardReports; oldest first report breaks ties;
organically-pending pairs last), each item: card image + tag + report count +
up to three newest free-text excerpts + **Approve / Reject / Skip**. Approve
and Reject are ordinary `2/submitTagVote/` calls (polarity +1/−1) sent with
credentials, so the vote records the moderator's user and the pair resolves —
or not — through the normal pass. Pending pairs are excluded from the public
tag queue.

### Drives (`DrivesPanel.tsx`)

A browse-and-manage view over `Source` rows, for spotting and removing a bad
or spammy drive (or an individual card within an otherwise-fine one) —
unrelated to report review; nothing here requires a `CardReport` to exist.

- `POST 2/moderationDrives/` lists every Source, newest-first (ordered by
  `-pk` — `Source` has no creation timestamp of its own; one existed briefly
  in 2021 and was removed in favour of per-`Card` dates, see migration
  `0004_auto_20210214_1126` — pk insertion order is a reliable enough proxy
  for "recently added" without a new migration), each with its
  card/cardback/token counts.
- `POST 2/moderationDriveCards/` drills into one drive's individual cards
  (paginated) so a specific card can be targeted.
- `POST 2/moderationRemoveCard/` and `POST 2/moderationRemoveDrive/`
  permanently delete a card or an entire drive (cascading onto every card it
  contributed via `Card.source`'s `on_delete=CASCADE`) — irreversible, no
  soft-delete, confirmed client-side via `window.confirm` since there's no
  undo. Both remove from Elasticsearch first (`ELASTICSEARCH_DSL_AUTOSYNC = False` in settings.py means deletes are never automatic — a card-delete
  reindexes via `CardSearch().update([card], action="delete")`, a drive-
  delete bulk-removes by the indexed `source_pk` field in one
  `delete_by_query` rather than one ES call per card) before the Postgres
  delete; Postgres stays authoritative even if the ES side fails (same
  swallow-and-log rationale as `reindex_card_safely` in documents.py).

## Consequence: NSFW hidden from search by default

Already true mechanically (default `excludesTags: ["NSFW"]`); this stage makes
it visible: a **Show Mature Content** toggle in search filter settings that
adds/removes the NSFW entry in `excludesTags` — the same state the tag filter
edits, one source of truth. No other consequences this stage (nothing hides
for low-res / incorrect-info yet).

## Server deployment checklist (one-time, in order)

0. **SSL cert must exist before nginx is first started.** `nginx.conf`
   hardcodes `ssl_certificate /etc/nginx/certs/origin.pem` /
   `origin.key` for the (single) `listen 443` server block with no HTTP-only
   fallback — if those files aren't present at `docker/nginx/certs/` when
   the `nginx` container starts, nginx fails to load its config and the
   **entire site** goes down, not just OAuth. On a brand-new server,
   provision the Cloudflare origin cert and drop it in
   `docker/nginx/certs/` (gitignored, never committed — see "Never commit")
   before the first `docker compose up`/rebuild of `nginx`. Steps 1–7 below
   assume this is already done.
1. Discord developer portal: create an application, add redirect URI
   `https://api.proxyprints.ca/accounts/discord/login/callback/`.
2. Env (`docker/.env`): `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
   `SESSION_COOKIE_SAMESITE=None`, `SESSION_COOKIE_SECURE=True`,
   `CORS_ALLOW_CREDENTIALS=True`. Optional: `VOTE_PRIVILEGED_WEIGHT`,
   `CARD_REPORT_RATE`, `MODERATORS_GROUP_NAME`. **`docker/.env` alone does
   not inject these into the containers** — Compose only passes through
   vars explicitly listed in a service's `environment:` block. All five are
   already wired into both `django` and `worker` in
   `docker-compose.prod.yml` as of 2026-07-15 (found missing during the
   first live setup — a fresh checkout has this for free now, but a new
   OAuth/session var still needs a matching line added there).
3. `pip install -r requirements.txt` (adds `django-allauth[socialaccount]`),
   rebuild/restart django + worker containers (and nginx — see the
   stale-upstream gotcha in [[../infrastructure.md]]).
4. `manage.py migrate` — cardpicker 0057–0059 (all additive) plus allauth's
   own `account`/`socialaccount` migrations. (If Django's checks ever demand
   the sites framework, add `django.contrib.sites` + `SITE_ID = 1` — not
   needed with allauth 65.x app-in-settings config.)
5. `manage.py seed_sensitive_tags` (idempotent; without it, reports still land
   but cast no votes and nothing can go pending).
6. Django admin: create the `Moderators` group
   (`/admin/auth/group/add/`). After each moderator's first Discord login, add
   their auto-created user to the group.
7. Live OAuth round-trip test: from proxyprints.ca, click "Moderator login
   (Discord)" on the What's That Card? page → authorize → land back on the
   page → whoami shows `moderator: true` → the Moderation tab appears → cast
   one Approve on a test pending pair and verify the card's tags + ES search
   update; reverse the test votes afterwards (the cast-verify-reverse
   discipline from [[printing-tags.md]]). If this 404s, or Discord rejects
   the redirect, see "nginx routing and proxy headers for `/accounts/`"
   below before re-checking Discord portal config — both live bugs on the
   first production attempt were server-side plumbing, not Discord config.

### nginx routing and proxy headers for `/accounts/`

Two more gaps found live during the first production OAuth attempt
(2026-07-15), both now baked into the checked-in `docker/nginx/nginx.conf`
and `MPCAutofill/MPCAutofill/settings.py` so a fresh checkout gets them automatically —
documented here so the reasoning survives if either file is ever touched:

- **Missing `/accounts/` proxy route.** `nginx.conf` only had `location`
  blocks for `/2/`, `/3/`, `/admin/`, `/static/`; every allauth URL
  (`/accounts/discord/login/`, the OAuth callback, logout) fell through to
  the static-file `location /` block and 404'd even with
  `DISCORD_AUTH_ENABLED=True` server-side. Fixed by an explicit
  `location /accounts/ { proxy_pass http://django-api; }` block.
- **`redirect_uri` built from the wrong host/scheme.** nginx's
  `proxy_pass` defaults the `Host` header it forwards to `$proxy_host` (the
  upstream container's own name, `django-api`) rather than the original
  client's `Host`, and Django never learns the original request was HTTPS
  without being told. Together this made django-allauth construct
  `http://django-api/accounts/discord/login/callback/` as the OAuth
  `redirect_uri` — an internal-only, plain-HTTP URL Discord's registered
  callback can never match, so Discord silently rejected the login. Fixed
  with `proxy_set_header Host $host;` and
  `proxy_set_header X-Forwarded-Proto $scheme;` at the nginx server-block
  level (inherited by every `location` below it), paired with
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` in
  `settings.py` — without the Django-side setting, `request.is_secure()`
  ignores the forwarded header and still reads `False`. Verified by
  manually walking the flow with `curl` (GET the login page for a CSRF
  token, POST it, inspect the 302 `Location` header) rather than a full
  browser round-trip.

## Key files

- Backend: `cardpicker/vote_consensus.py` (the gate),
  `cardpicker/tag_consensus.py`, `cardpicker/moderation.py`,
  `cardpicker/security.py`, `cardpicker/sensitive_tags.py` (+ management
  command), `cardpicker/models.py` (user FK, `TagModerationClass`,
  `CardReport`, `TagVoteStatus.PENDING_APPROVAL`), `cardpicker/question_feed.py`
  (report review deliberately absent - see "Moderation tab" above),
  `cardpicker/views.py` (whoami / reportCard / moderationQueue /
  moderationDrives / moderationDriveCards / moderationRemoveCard /
  moderationRemoveDrive), `accounts/adapter.py`, `MPCAutofill/MPCAutofill/settings.py`.
- Frontend: `features/reporting/ReportCardPanel.tsx`,
  `features/moderation/AuthWidget.tsx` (Discord-branded login button) +
  `ModerationTab.tsx` (Reports/Drives sub-tab switcher) + `ReportsPanel.tsx`
  - `DrivesPanel.tsx`, `features/filters/MatureContentFilter.tsx`,
    `pages/whatsthat.tsx` (Question Feed/Moderation tab switcher, moderator-
    only), `store/api.ts` (whoami query + credentialed fetches).
- Tests: `cardpicker/tests/test_moderation_gate.py`,
  `test_moderation_views.py`, `test_sensitive_tags.py`, `test_question_feed.py`
  (asserts pending-approval pairs never surface in the ordinary feed);
  `frontend/src/features/reporting/ReportCardPanel.test.tsx`;
  `frontend/tests/{ReportCard,ModerationQueue,ModerationTab,MatureContentToggle}.spec.ts`.

## Known gaps / follow-ups

- Discord guild-role sync for a federation-wide moderator roster (see "Who is
  a moderator").
- Federation export/import of moderation verdicts is v1.1
  ([[../federation-v1.md]]) — explicitly out of scope here.
- No consequences yet for resolved `low-res` / `incorrect-info`.
- The rate limiter shares the existing single-gunicorn-worker in-process-cache
  caveat (documented as a code comment on `post_submit_printing_tag`,
  `cardpicker/views.py:860-863` — not currently written up in any doc).

**Verified, not a gap**: live Discord OAuth working end-to-end in production
2026-07-15 (server-side plumbing via `curl` simulation, then a real
moderator's browser round-trip) — see "nginx routing and proxy headers for
`/accounts/`" above.
