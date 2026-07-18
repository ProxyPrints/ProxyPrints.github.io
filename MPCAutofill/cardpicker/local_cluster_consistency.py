"""
Cluster-consistency check (docs/theory.md §6's "free contradiction detector" carve-out,
2026-07-18): report-only, read-only, never human-volume gated - see the readiness re-check at
docs/reports/2026-07-18-dawid-skene-readiness-recheck.md for why the other three Sybil/bad-actor
detectors in that section stay unbuilt while this one doesn't.

d=0 phash clusters (Card.content_phash exact match) are, by construction, the SAME uploaded
image (see cardpicker.local_clustering's own d=0 semantics - identical reasoning here, this
module just reads the same signal from a DB-wide angle instead of a single run's selected pool).
Two cluster members that both carry a resolved printing identification
(Card.printing_tag_status == RESOLVED, Card.inferred_canonical_card set) but resolved to
DIFFERENT printings are an internal contradiction: the same image cannot correctly BE two
different printings. No new machinery is needed to detect this - it's a plain GROUP BY over
already-persisted columns.

Doubles as the federation export's pre-flight audit: a divergent cluster is exactly the kind of
record federation must never publish (docs/federation-v1.md's content_hash verdict-exchange
format assumes one printing per hash), so this same query is the audit gate for that future work,
not a separate check to build twice.
"""

import collections
from dataclasses import dataclass

from cardpicker.models import Card, PrintingTagStatus


@dataclass(frozen=True)
class DivergentCluster:
    content_phash: int
    # (card_id, printing_id) pairs for every RESOLVED member of this d=0 cluster - printing_id
    # is CanonicalCard.pk, not re-fetched here (the caller already has the printing_tag_status/
    # inferred_canonical_card columns needed; no join to CanonicalCard's own fields is needed
    # for a report that only needs to prove IDs differ, not describe the printings by name).
    members: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ClusterConsistencyResult:
    # Every d=0 cluster (2+ members, all RESOLVED) that was checked - the denominator.
    clusters_checked: int
    # Total RESOLVED, hashed cards considered (context for clusters_checked - most resolved
    # cards are singletons with no d=0 sibling at all, and never enter clusters_checked).
    resolved_cards_considered: int
    divergent: tuple[DivergentCluster, ...]


def find_cluster_printing_divergences() -> ClusterConsistencyResult:
    """
    Pure DB read, zero writes. Groups every RESOLVED, hashed Card by content_phash (exact d=0
    match); for each group with 2+ members, flags it if the members' inferred_canonical_card_id
    values are not all identical. A group of size 1 is trivially consistent (nothing to compare
    against) and is excluded from clusters_checked entirely, matching local_clustering's own
    "representative + others, len>=2 only" convention for what counts as a cluster at all.
    """
    rows = Card.objects.filter(
        printing_tag_status=PrintingTagStatus.RESOLVED,
        content_phash__isnull=False,
        inferred_canonical_card__isnull=False,
    ).values_list("id", "content_phash", "inferred_canonical_card_id")

    members_by_hash: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    resolved_cards_considered = 0
    for card_id, content_phash, printing_id in rows:
        # content_phash__isnull=False in the filter above guarantees this isn't None; the ORM's
        # column-level nullability still leaks into values_list()'s inferred element type.
        assert content_phash is not None
        resolved_cards_considered += 1
        members_by_hash[content_phash].append((card_id, printing_id))

    clusters_checked = 0
    divergent: list[DivergentCluster] = []
    for content_phash, members in members_by_hash.items():
        if len(members) < 2:
            continue
        clusters_checked += 1
        distinct_printings = {printing_id for _card_id, printing_id in members}
        if len(distinct_printings) > 1:
            divergent.append(DivergentCluster(content_phash=content_phash, members=tuple(members)))

    return ClusterConsistencyResult(
        clusters_checked=clusters_checked,
        resolved_cards_considered=resolved_cards_considered,
        divergent=tuple(divergent),
    )


__all__ = [
    "DivergentCluster",
    "ClusterConsistencyResult",
    "find_cluster_printing_divergences",
]
