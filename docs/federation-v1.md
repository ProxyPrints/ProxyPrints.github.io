# Federation verdict exchange — format v1 (spec; implementation pending)

Instances share **resolved consensus verdicts** (never raw votes) as signed
JSON. Each importing instance ingests peer verdicts as `source='federated'`
votes, subject to its own consensus thresholds and admin override. Instances
export only locally-resolved consensus — never re-broadcast federated votes
(no transitive trust / echo amplification).

## Participation modes

Three roles, not one monolithic "federation" switch:

- **SUBSCRIBER** — read-only. Consumes peer verdict feeds (signature
  verification + import), emits nothing of its own. Zero trust
  configuration beyond the peer's pinned public key, zero Sybil surface —
  a subscriber can't poison anyone else's catalog, only choose (badly)
  what it trusts for its own display/search boost. The lowest-risk, most
  generically useful half of this whole program — see "Consumer
  component" below.
- **PUBLISHER** — emits signed verdicts (export command + keygen),
  consumes nothing. Requires the full vote/consensus/human-gate stack
  this fork already has (`docs/features/printing-tags.md`) — nothing new
  to build on the export side beyond signing and the file format itself.
- **FULL PEER** — both. The eventual steady state for a mature,
  mutually-trusting pair of instances, not a v1 target.

**v1 launch posture for ProxyPrints: PUBLISHER-ONLY.** We emit verdicts,
we consume none. This proves the protocol out — a real signed export
file, a real peer able to verify and read it — with **zero
catalog-integrity risk** on our side: nothing a bad or buggy peer
publishes can ever reach our own `Card`/vote tables, because we never
import. Consuming is a strictly later, separate decision, gated on both
having a peer worth trusting _and_ fixing the gate issue documented
below — not before either.

**Expected onboarding path for any new participant: subscriber-first.**
A prospective peer should be able to point at our export feed, verify our
signature, and get real value (badge display, search-boost, whatever
their own instance does with imported verdicts) before ever standing up
their own publish side. Publishing is the higher-trust, higher-effort
commitment; nobody should have to build it just to find out whether
federation is worth doing at all.

### Consumer component — the upstream-shaped chunk

The subscriber half specifically — a verdict table keyed on
`content_hash` (once the cross-instance join logic lands, see
"Interchange keys" below), perceptual-hash tooling (`Card.content_phash`
already exists locally), signature verification (ed25519, no dependency
beyond what signing itself needs), and a display badge surfacing "N peer
instances agree" — is deliberately dependency-free: no vote system, no
consensus engine, no moderation stack required. Any mpc-autofill instance
could subscribe to a verdict feed and show peer-agreement badges without
adopting anything else this fork has built. That makes it the _only_
plausibly upstream-shaped piece of the whole federation program —
everything on the publisher side assumes the vote/consensus/moderation
stack this fork built that upstream doesn't have. Tracked as a deferred
entry (Tier 6) on `docs/upstreaming/readiness-audit.md`'s ladder, gated
on federation actually having a live peer to subscribe to — there's
nothing real to extract or offer before that exists to prove the format
against.

## File shape

    {
      "schema_version": 1,
      "instance": "<hostname>",
      "public_key": "<ed25519 pubkey, base64>",
      "generated_at": "<ISO 8601>",
      "game": "MTG",
      "verdicts": [
        {
          "image": {
            "drive_id": "<Google Drive file id — the join key>",
            "content_hash": null,          // perceptual hash (imagehash.phash, hash_size=8,
                                            // 64-bit) - now backed by Card.content_phash
                                            // (docs/features/printing-tags.md's hash-at-ingest
                                            // section, 2026-07-16); still v1 nullable, since not
                                            // every instance's backfill will be complete
            "name": "<card name, advisory only>"
          },
          "kind": "printing" | "artist" | "tag",
          "outcome": "scryfall:<uuid>" | "no_match"
                    | "artist:<canonical artist name>" | "artist:unknown"
                    | "tag:<tag name>:apply" | "tag:<tag name>:reject",
          "resolved_at": "<ISO 8601>",
          "vote_weight": <float — total weight behind the verdict>,
          "human_votes": <int — count of votes NOT from a machine-derived
                          source (VoteSource.DEDUCTION or VoteSource.OCR —
                          the single umbrella VoteSource.AI value this
                          interchange format was designed against was split
                          into these two 2026-07-15, same weight/gate
                          treatment; see cardpicker/models.py's VoteSource
                          docstring). Importers MUST treat human_votes >= 1
                          as the condition for the imported vote to be
                          human-backed for gate purposes>
        }
      ],
      "signature": "<ed25519 over canonical JSON (sorted keys, no whitespace)
                     of all fields above except signature>"
    }

## Interchange keys & stability contract

- Images join across instances by `drive_id` (Google Drive file id).
  `content_hash` is the planned upgrade path for surviving re-uploads - the field itself
  (`Card.content_phash`) and its own local consumer (two-threshold dedup clustering) now exist;
  the cross-instance join logic that would actually use it for federation is still unbuilt.
- Artists travel by canonical name; tags by `Tag.name`. **Tag names are
  therefore a cross-instance contract: renaming a Tag is a breaking data
  migration, not an edit.** `Tag.name` is the immutable interchange key;
  `Tag.display_name` is local presentation only and never federates.

## Import rules (normative for future implementation)

- Verify signature against a pinned per-peer public key (out-of-band
  exchange; no open enrollment).
- One voice per peer per (image, kind[, tag]): re-import replaces that
  peer's prior vote, never stacks.
- Weight: settings.VOTE_FEDERATED_WEIGHT, per-peer override permitted.
- Skip verdicts whose artist/tag can't be matched locally.

## Known gate issue (defensive default fixed 2026-07-19; full per-peer design still not built)

**The bug (fixed)**: `cardpicker/vote_consensus.py`'s
`is_human_backed_source()` checks membership in
`_MACHINE_DERIVED_SOURCES` — `VoteSource.FEDERATED` was not in that
set, so `is_human_backed_source(VoteSource.FEDERATED)` returned `True`.
Fixed: `_MACHINE_DERIVED_SOURCES` now includes `VoteSource.FEDERATED`
(`vote_consensus.py:38`, verified directly against current code,
2026-07-19), so `is_human_backed_source(VoteSource.FEDERATED)` returns
`False` — a federated vote can no longer singlehandedly clear the "at
least one human-backed vote" resolution gate. This is the safe,
defensive default; `VoteTuple.is_human_backed` is still caller-supplied
per the existing design, so a real importer can still override this
explicitly if a peer's own review process has already made a federated
verdict genuinely human-backed. The per-peer-promotable design below
remains the eventual real mechanism and is still not built.

## Implicit-vote weight semantics (pinned 2026-07-22, not yet exported)

`VoteSource.IMPLICIT` (docs/features/printing-tags.md's implicit-vote
section, owner-ratified 2026-07-22 vote-weight scenario matrix) is a new
exported semantic that a future federation peer must know about before any
importer consuming it exists — pinned here now per the matrix's own
federation note, rather than left to be re-derived the day an importer
first encounters an implicit-sourced verdict:

- **Form shipped: low-weight + per-outcome-group cap**, not the
  "share-only" alternative form the matrix's own drafting also considered
  and explicitly rejected (that form let implicit weight either break a
  genuine human tie or veto an otherwise quorum-valid human win, depending
  on the scenario — never shipped).
- Per-vote weight `PRINTING_TAG_IMPLICIT_WEIGHT` (default 0.25) counts
  toward BOTH quorum and share, but the SUM of implicit weight within a
  single (card, tag, polarity) outcome group is hard-capped at
  `PRINTING_TAG_IMPLICIT_CAP` (default 1.0, strictly below
  `PRINTING_TAG_MIN_VOTES`) — so no volume of implicit votes on one side
  can ever supply that side's quorum weight alone.
- `is_human_backed=False` always, same treatment as `DEDUCTION`/`OCR` —
  an importer must not treat an imported implicit-sourced contribution as
  human-backed, mirroring this doc's existing FEDERATED guidance above.
- `resolve_weighted_consensus`'s [no-machine-tipping and
  machine-dissent-never-de-resolves mechanisms](features/printing-tags.md#human-contest-machine-weight-drop)
  (see that function's own
  docstring, and docs/features/printing-tags.md's "Consensus" bullet)
  additionally guarantee implicit weight can never decide a live
  human-vs-human contest nor de-resolve an already-quorum-valid human
  winner — the same guarantee DEDUCTION/OCR/FEDERATED weight now gets.
- **Not yet exported**: no federation verdict currently carries an
  implicit-sourced contribution (implicit votes are a purely local
  `/editor` filter-chip signal today, cast via `POST 2/castImplicitVote/`).
  If/when a verdict export ever aggregates implicit weight into a
  `vote_weight`/`human_votes` figure, the exported verdict must carry
  enough information for an importer to reconstruct (or at minimum
  respect) the cap above under the peer's own thresholds — exporting a
  raw, uncapped implicit sum would let cross-peer share arithmetic diverge
  from what this instance itself would have resolved.

## Future work: contributor nodes (design note, 2026-07-19 — NOT built)

The pieces already landing for local, non-federated reasons compose
into something bigger than any one of them was designed for. Three
Stage C/lazy-mode primitives, put together:

1. **The per-card callable work unit** (`cardpicker/image_evidence.py`'s
   `extract_card_evidence`/`persist_evidence` split, task #145) —
   fetch → extract → evidence → discard, independent of the bulk
   runner by construction (FINAL POSTURE item 8a).
2. **Manifest-mode segmentation** (task #99, still deferred) — running
   the pipeline against a bounded, caller-supplied card set rather
   than the whole catalog.
3. **Evidence keyed by content hash, not by who computed it**
   (`ImageEvidence`'s `(card, content_hash)` key) — the store doesn't
   care whether the hash/OCR/geometry for a given image came from our
   own harvest or from somewhere else, only that it's correctly keyed.

Together these describe a **self-hosted contributor node**: a user
imports their own deck → the node fetches THEIR OWN images (their own
IP, their own Google throttle budget, no shared quota, no API key of
ours required — the exact "pull" mode task #161's lazy-identification
design note already names) → runs the same extractors locally → phones
home with **evidence only** (hashes, OCR text, geometry/quality
classes — never image bytes, posture-clean in _both_ directions, not
just ours: the contributor's images never cross the wire either) → the
federation verdict-exchange format above (once a subscriber side
exists) is the natural transport for that evidence back to us. The
phash-cache/evidence-exchange machinery already being built for peer
federation doubles as this contributor node's bootstrap protocol — no
second transport to design.

This is the lazy-mode principle (task #161: "identification capacity
scales with usage, not hardware") taken one step further:
**identification capacity scales with USERS, not our hardware.** Every
deck import is a potential free extraction pass on cards we'd
otherwise have to harvest ourselves, paced by real user traffic
instead of a bulk job competing for our one shared Google quota.

**Hardware floor**: a Steam-Deck-class x86 Linux machine (real CPU,
real Python/Tesseract/Pillow support) is a full contributor node,
capable of the whole fetch→extract pipeline. A phone is not — it's a
confirmation client only (views evidence, casts votes), not a compute
contributor. Any pitch or implementation plan for this should account
for that split rather than assuming uniform client capability.

**One sentence for the pitch, next time it's edited**: "the
architecture already permits your users to be the compute."

Not built. Depends on: task #161 (lazy identification mode) landing
first, a real subscriber-side federation implementation (this doc's
"Consumer component" is currently spec-only), and its own dedicated
design pass for node auth/trust (a contributor node is a much higher-
Sybil-risk actor than a pinned-key peer instance — evidence from an
anonymous contributor node cannot carry the same weight as our own
harvest or a trusted peer's signed verdict without a real trust model,
not sketched here).

**The fix (design only, not implemented)**: route federated gate
treatment through a settings-driven mode, `FEDERATED_VOTE_GATE_MODE`
(default `"suggestion"` — contributes weight, does **not** count toward
the human-backed gate; promotable to a gate-clearing mode later),
mirroring Proposal G's `AUTHED_VOTE_GATE_MODE` idiom exactly: an
env-driven flag plus a dedicated weight/treatment function, never a
hand-coded branch scattered through the consensus resolvers (see
`docs/proposals/proposal-g-user-accounts-saved-decks.md` §7 — verified
current, not assumed: `AUTHED_VOTE_GATE_MODE` is actually shipped
(resolved for v1 as `"status_quo"` default, a real setting routed through
`authed_vote_weight()`), so this is a live pattern to mirror, not just a
design precedent still waiting to land). Promotion should be **per-peer**,
not one global switch:
once a specific peer's verdicts have measured reliability — `docs/theory.md`'s
"Relation to Dawid-Skene reliability estimation" section already frames a
federation peer as exactly the kind of noisy source that model applies
to — that peer's federated votes could be promoted to gate-clearing while
an unmeasured new peer stays suggestion-tier by default. Same
"defaults off, config not migration" shape `require_privileged` and the
proposed `AUTHED_VOTE_GATE_MODE` both already use.

**Status: defensive default shipped (2026-07-19), full per-peer design
not built.** Consuming federated votes at all is gated on having a live
peer in the first place (see "Participation modes" above) — the
per-peer promotion mechanism needs to land before that happens, not
before. Recorded here so it isn't rediscovered from scratch whenever
import actually gets built.

Status: format committed ahead of code. Export/import commands, keygen, and
the peer registry are future work; the schema stub (source='federated',
peer field, weight setting, is_human_backed plumbing) ships now.
