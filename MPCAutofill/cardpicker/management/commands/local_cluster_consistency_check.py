from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.local_cluster_consistency import find_cluster_printing_divergences

SAMPLE_SIZE = 20


class Command(BaseCommand):
    help = (
        "Cluster-consistency check (docs/theory.md §6): report-only, read-only, zero writes. "
        "Flags d=0 phash clusters (Card.content_phash exact match) where 2+ RESOLVED members "
        "resolved to DIFFERENT printings - an internal contradiction, since a d=0 cluster is by "
        "construction the same uploaded image. Also the federation export's pre-flight audit: "
        "divergent clusters are exactly the records that export must not publish."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        result = find_cluster_printing_divergences()

        print(
            f"[cluster-consistency] resolved_cards_considered={result.resolved_cards_considered} "
            f"clusters_checked={result.clusters_checked} divergent={len(result.divergent)}"
        )

        if not result.divergent:
            print("[cluster-consistency] no divergent clusters found.")
            return

        print(f"[cluster-consistency] flagged cluster content_phash values ({len(result.divergent)} total):")
        for cluster in result.divergent:
            print(f"  content_phash={cluster.content_phash} member_count={len(cluster.members)}")

        print(f"[cluster-consistency] sample (first {SAMPLE_SIZE}):")
        for cluster in result.divergent[:SAMPLE_SIZE]:
            members_str = ", ".join(
                f"card={card_id} printing={printing_id}" for card_id, printing_id in cluster.members
            )
            print(f"  content_phash={cluster.content_phash}: {members_str}")
