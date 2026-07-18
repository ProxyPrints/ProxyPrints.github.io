"""
Two-threshold clustering over `Card.content_phash` (docs/features/printing-tags.md's
hash-at-ingest architecture, 2026-07-16): replaces the disabled, fetch-based
`compute_own_image_clusters` pre-pass entirely (see local_identify_printing_tags.py's own
"DISABLED" comment at its old call site). Since content_phash is now persisted at ingest/backfill
time (see local_phash.compute_content_phash_for_card, sources.update_database.
hash_newly_created_cards, the local_backfill_content_phash management command), clustering a
run's selected pool is a pure DB-column read + in-memory compute step - no network fetch, no
sequential pre-pass, no observability gap. The pre-pass's own fixed ~21.6h sequential cost (the
reason it was disabled) simply doesn't exist in this design.

Two tiers, two different trust levels - NOT the same operation at two thresholds, genuinely
different semantics:

- d=0 (exact 64-bit hash match): sound entailment, identical reasoning to the original pre-pass
  - a distance-0 match among OUR OWN uploaded images most plausibly means a duplicate/
  shared-source image, not independent depictions that coincidentally look alike (that's the
  *candidate* art-crop matching problem local_phash.find_best_match already handles separately,
  via a real DEFAULT_DISTANCE_THRESHOLD=20). An accepted vote on the representative propagates
  identically to every distance-0 member - see local_identify_printing_tags.run_pilot's write
  loop, unchanged from before.

- 0 < d <= 2: NOT entailment - a prior only, used to NARROW (never auto-vote) a member's own
  candidate list toward printings its near-duplicate cluster-mates are already candidates for.
  Same safety line as _narrow_candidates_by_expansion_hint (never narrows to empty, never
  touches select_candidates' ordering or the uncovered-printings-closed metric). Threshold
  justified two ways: (1) the LAION-scale precedent of d<=2 as the standard near-duplicate
  cutoff (see "Prior-art read" in docs/features/printing-tags.md); (2) this repo's own measured
  small-size-hashing drift test, where a real true-duplicate pair landed at exactly d=2 - see
  "Phash accuracy at small CDN sizes" in the same doc. d<=2 is REQUIRED, not optional, if
  small-size hashing is used for content_phash (which it is - see local_phash.
  INGEST_HASH_FETCH_DPI) - a d=0-only design would silently miss that class of true duplicate.

Neighbor search: chunked numpy XOR + popcount (numpy.bitwise_count, numpy>=2.0), NOT a Python
pairwise loop and NOT one all-at-once O(N^2) memory allocation - prior MTG card-detector
projects hit exactly the O(N*M) wall a naive implementation would (see "Prior-art read"'s
brute-force-linear-scan note). Chosen over a BK-tree because the access pattern here is BATCH,
not incremental: `run_pilot` computes clusters once per invocation for its whole selected pool,
not one query at a time as new cards trickle in - a BK-tree earns its keep for the opposite
pattern (repeated single-point nearest-neighbor lookups against a mostly-static corpus), which
isn't what this call site does. Chunking over ROWS (not columns) keeps peak memory at
chunk_size x N instead of N x N - at N~166k (the full-catalog run's own selected-pool size),
N x N as even 1-byte-per-distance would be ~27GB; chunk_size=2000 keeps each chunk under 350MB.

**d=0 and d<=2 are computed as two INDEPENDENT steps, not one pass split afterward** - a
deliberate robustness choice (advisor review, 2026-07-16), not an accident of implementation
order. d=0 exact-match grouping is a plain dict grouping (measured: 0.13s at N=166,422 real
scale, no numpy needed at all - equality doesn't need a distance computation). The d<=2
near-duplicate scan is the genuinely expensive part (measured: ~2-3 minutes at the same N,
contended with this box's own concurrently-running full-catalog job at benchmark time - still a
~500-650x win over the disabled pre-pass's ~21.6h, and it's pure in-memory compute, not network,
so it doesn't compete for the same shared CDN request budget the old pre-pass did). Keeping
these two steps independent means the safety-critical, already-proven vote-propagation tier
(d=0) can NEVER be slowed down, blocked, or made incorrect by a bug or performance regression in
the newer, less-battle-tested near-duplicate narrowing tier (d<=2) - if the latter ever needs to
be disabled or reworked, the former is untouched.
"""

import collections
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from cardpicker.local_identify_printing_tags import SelectedCard

logger = logging.getLogger(__name__)

_HASH_BITS = 64
_UNSIGNED_MASK = (1 << _HASH_BITS) - 1

# Same value local_clustering's own docstring justifies above (LAION-scale precedent + this
# repo's own d=2 true-duplicate observation) - a module-level constant so both tiers below stay
# in sync with the same number, and so a future re-tune has one place to change.
NEAR_DUPLICATE_MAX_DISTANCE = 2

# Chunk over rows to bound peak memory - see module docstring's sizing note. Not tuned beyond
# "keeps a chunk comfortably under 1GB at full-catalog scale" - a real profiling pass could
# probably push this higher.
DEFAULT_CHUNK_SIZE = 2000


@dataclass(frozen=True)
class TwoThresholdClusterResult:
    # representative card_id -> the OTHER card_ids (never including the representative itself)
    # at EXACTLY distance 0 - an accepted vote on the representative should propagate to them.
    # Same shape as the old (now-removed) ClusterResult.members_by_representative, so
    # run_pilot's existing propagation/absorption logic needs no changes to consume this.
    members_by_representative: dict[int, list[int]]
    # card_id -> the set of OTHER card_ids within NEAR_DUPLICATE_MAX_DISTANCE (INCLUDING the
    # distance-0 members above, since a d<=2 narrowing prior is still valid information even for
    # a card that's also an exact-match representative) - a prior for candidate narrowing only,
    # never auto-voted. Absent key means "no near-duplicates found" (empty prior, not narrowed).
    near_duplicate_ids_by_card_id: dict[int, set[int]]


def _unsigned_hash_array(
    card_ids: list[int], hash_by_card_id: dict[int, int]
) -> "np.ndarray[Any, np.dtype[np.uint64]]":
    return np.array([hash_by_card_id[c] & _UNSIGNED_MASK for c in card_ids], dtype=np.uint64)


def _find_pairs_within_distance(
    hashes: "np.ndarray[Any, np.dtype[np.uint64]]", max_distance: int, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> list[tuple[int, int, int]]:
    """
    Returns (i, j, distance) triples with i < j (array indices into `hashes`, not card ids) and
    distance <= max_distance. Chunks over rows: for each block of `chunk_size` hashes, XORs the
    whole block against the FULL array in one vectorized op, then popcounts the result - avoids
    both a Python-level O(N^2) loop and an O(N^2) all-at-once allocation (see module docstring).
    """
    n = len(hashes)
    pairs: list[tuple[int, int, int]] = []
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        block = hashes[start:end]  # shape (b,)
        xor = block[:, None] ^ hashes[None, :]  # shape (b, n)
        distances = np.bitwise_count(xor)  # shape (b, n)
        for local_i in range(end - start):
            i = start + local_i
            # only j > i: avoids self-pairs (distance 0 to itself) and double-counting (i, j)
            # and (j, i) as separate entries.
            row = distances[local_i, i + 1 :]
            # .tolist() before iterating: a plain Python list's iterability doesn't depend on
            # which numpy-stubs version mypy happens to resolve for np.nonzero's return type
            # (a real cross-environment mypy failure this hit once already - numpy isn't pinned
            # anywhere, so different environments can resolve different versions/stubs).
            close_local_js = np.nonzero(row <= max_distance)[0].tolist()
            for local_j in close_local_js:
                j = i + 1 + int(local_j)
                pairs.append((i, j, int(row[local_j])))
    return pairs


def _compute_exact_match_clusters(hash_by_card_id: dict[int, int]) -> dict[int, list[int]]:
    """d=0 tier: group by exact hash value - a direct dict grouping, not the vectorized scan
    below (equality doesn't need a distance computation at all). Measured 0.13s at N=166,422 -
    effectively free, independent of how expensive the d<=2 tier is or ever becomes."""
    card_ids_by_hash: dict[int, list[int]] = collections.defaultdict(list)
    for card_id, h in hash_by_card_id.items():
        card_ids_by_hash[h].append(card_id)

    members_by_representative: dict[int, list[int]] = {}
    for same_hash_card_ids in card_ids_by_hash.values():
        if len(same_hash_card_ids) < 2:
            continue
        representative_id = min(same_hash_card_ids)
        others = [c for c in same_hash_card_ids if c != representative_id]
        members_by_representative[representative_id] = others
    return members_by_representative


def _compute_near_duplicate_hints(hash_by_card_id: dict[int, int]) -> dict[int, set[int]]:
    """d<=2 tier: the vectorized chunked scan - the genuinely expensive part (~2-3 minutes at
    N=166,422 real scale, see module docstring). A deliberately separate function from the d=0
    tier above, called independently by compute_two_threshold_clusters - see module docstring's
    "computed as two INDEPENDENT steps" note for why that separation matters."""
    card_ids = list(hash_by_card_id.keys())
    hashes = _unsigned_hash_array(card_ids, hash_by_card_id)
    pairs = _find_pairs_within_distance(hashes, NEAR_DUPLICATE_MAX_DISTANCE)

    near_duplicate_ids_by_card_id: dict[int, set[int]] = collections.defaultdict(set)
    for i, j, _distance in pairs:
        card_i, card_j = card_ids[i], card_ids[j]
        near_duplicate_ids_by_card_id[card_i].add(card_j)
        near_duplicate_ids_by_card_id[card_j].add(card_i)
    return dict(near_duplicate_ids_by_card_id)


def compute_two_threshold_clusters(selected: list["SelectedCard"]) -> TwoThresholdClusterResult:
    """
    The stored-hash replacement for the old fetch-based compute_own_image_clusters - see module
    docstring for the full d=0/d<=2 semantics. Cards with a NULL content_phash (not yet
    hashed - see local_phash.compute_content_phash_for_card and the backfill command) are
    excluded from clustering entirely, treated as always-singleton (same safe fallback the
    disabled pre-pass had for a failed fetch) - this function does no fetching or hashing of its
    own, purely reads whatever's already on `s.card.content_phash`.
    """
    hash_by_card_id: dict[int, int] = {
        s.card.pk: s.card.content_phash for s in selected if s.card.content_phash is not None
    }
    if len(hash_by_card_id) < 2:
        return TwoThresholdClusterResult(members_by_representative={}, near_duplicate_ids_by_card_id={})

    members_by_representative = _compute_exact_match_clusters(hash_by_card_id)
    try:
        near_duplicate_ids_by_card_id = _compute_near_duplicate_hints(hash_by_card_id)
    except Exception:
        # The d<=2 tier is a NARROWING PRIOR, never entailment (see module docstring) - a
        # failure here must never take down d=0's already-proven vote propagation. Falls back
        # to "no near-duplicate hints available this run", not a crash.
        logger.exception("Near-duplicate (d<=2) scan failed - continuing with d=0 clusters only")
        near_duplicate_ids_by_card_id = {}

    return TwoThresholdClusterResult(
        members_by_representative=members_by_representative,
        near_duplicate_ids_by_card_id=near_duplicate_ids_by_card_id,
    )


__all__ = [
    "NEAR_DUPLICATE_MAX_DISTANCE",
    "DEFAULT_CHUNK_SIZE",
    "TwoThresholdClusterResult",
    "compute_two_threshold_clusters",
]
