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

Status: format committed ahead of code. Export/import commands, keygen, and
the peer registry are future work; the schema stub (source='federated',
peer field, weight setting, is_human_backed plumbing) ships now.
