# Federation verdict exchange — format v1 (spec; implementation pending)

Instances share **resolved consensus verdicts** (never raw votes) as signed
JSON. Each importing instance ingests peer verdicts as `source='federated'`
votes, subject to its own consensus thresholds and admin override. Instances
export only locally-resolved consensus — never re-broadcast federated votes
(no transitive trust / echo amplification).

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
            "content_hash": null,          // reserved: perceptual hash, v1 nullable
            "name": "<card name, advisory only>"
          },
          "kind": "printing" | "artist" | "tag",
          "outcome": "scryfall:<uuid>" | "no_match"
                    | "artist:<canonical artist name>" | "artist:unknown"
                    | "tag:<tag name>:apply" | "tag:<tag name>:reject",
          "resolved_at": "<ISO 8601>",
          "vote_weight": <float — total weight behind the verdict>,
          "human_votes": <int — non-AI vote count; importers MUST treat
                          human_votes >= 1 as the condition for the imported
                          vote to be human-backed for gate purposes>
        }
      ],
      "signature": "<ed25519 over canonical JSON (sorted keys, no whitespace)
                     of all fields above except signature>"
    }

## Interchange keys & stability contract

- Images join across instances by `drive_id` (Google Drive file id).
  `content_hash` is the planned upgrade path for surviving re-uploads.
- Artists travel by canonical name; tags by `Tag.name`. **Tag names are
  therefore a cross-instance contract: renaming a Tag is a breaking data
  migration, not an edit.**

## Import rules (normative for future implementation)

- Verify signature against a pinned per-peer public key (out-of-band
  exchange; no open enrollment).
- One voice per peer per (image, kind[, tag]): re-import replaces that
  peer's prior vote, never stacks.
- Weight: settings.VOTE_FEDERATED_WEIGHT, per-peer override permitted.
- Skip verdicts whose artist/tag can't be matched locally.

Status: format committed ahead of code. Export/import commands, keygen, and
the peer registry are future work; the schema stub (source='federated',
peer field, weight setting, is_human_backed plumbing) ships now.
