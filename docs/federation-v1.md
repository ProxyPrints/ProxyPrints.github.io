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

## Known gate issue (tracked, not built)

**The bug**: `cardpicker/vote_consensus.py`'s `is_human_backed_source()`
checks membership in `_MACHINE_DERIVED_SOURCES = {VoteSource.DEDUCTION, VoteSource.OCR}` — `VoteSource.FEDERATED` is _not_ in that set, so
`is_human_backed_source(VoteSource.FEDERATED)` returns `True` today
(verified directly against current code at `vote_consensus.py:31`,
2026-07-19 — not just asserted). If federation import is ever built by
following the existing per-source-wrapper pattern naively, a single
imported federated verdict could singlehandedly clear the "at least one
human-backed vote" resolution gate — contradicting this document's own
contract that federated verdicts arrive as suggestions into the
importing instance's own review gate, not as a vote that can clear it
alone.

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

**Status: flagged, not built.** Consuming federated votes at all is
gated on having a live peer in the first place (see "Participation
modes" above) — this fix needs to land before that happens, not before.
Recorded here so it isn't rediscovered from scratch whenever import
actually gets built.

Status: format committed ahead of code. Export/import commands, keygen, and
the peer registry are future work; the schema stub (source='federated',
peer field, weight setting, is_human_backed plumbing) ships now.
