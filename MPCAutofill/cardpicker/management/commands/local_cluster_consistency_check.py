from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.local_cluster_consistency import find_cluster_printing_divergences

SAMPLE_SIZE = 20


class Command(BaseCommand):
    help = (
        "Cluster-consistency check (docs/theory.md §6): report-only, read-only, zero writes. "
        "Flags d=0 phash clusters (Card.content_phash exact match) where 2+ RESOLVED members "
        "resolved to DIFFERENT printings - an internal contradiction, since a d=0 cluster is by "
        "construction the same uploaded image. Also the federation export's pre-flight audit: "
        "divergent clusters are exactly the records that export must not publish. "
        "Exits non-zero when it checked no clusters at all (see --allow-vacuous): an empty "
        "result over an empty population is not an all-clear and must not read like one."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--allow-vacuous",
            action="store_true",
            help=(
                "Exit 0 even when zero clusters were checkable. For callers that poll this "
                "command on a schedule and want the DORMANT banner reported without the run "
                "being marked failed. The banner still prints - this flag changes the exit "
                "code only, never the output."
            ),
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        result = find_cluster_printing_divergences()

        print(
            f"[cluster-consistency] resolved_cards_considered={result.resolved_cards_considered} "
            f"clusters_checked={result.clusters_checked} divergent={len(result.divergent)} "
            f"d0_groups_in_catalogue={result.d0_groups_in_catalogue}"
        )

        # DORMANCY BRANCH FIRST, before any "no divergences" line can be printed. `divergent` is
        # empty in both the vacuous and the genuinely-clean case, and this command's output is
        # the only thing an operator ever sees - so the two cases must not share a message. As of
        # 2026-07-29 this is the branch that fires in production: 4 RESOLVED cards, 0 clusters
        # checkable, 33,631 d=0 groups sitting there waiting on resolution volume.
        if result.is_vacuous:
            print(
                "[cluster-consistency] DORMANT - NOT AN ALL-CLEAR. Checked 0 clusters out of "
                f"{result.d0_groups_in_catalogue} d=0 group(s) present in the hashed catalogue. "
                "A cluster needs 2+ members that are BOTH resolved to a printing, and only "
                f"{result.resolved_cards_considered} resolved+hashed card(s) exist right now. "
                "This run proves nothing about cluster consistency; it proves there was nothing "
                "to compare. Re-run once resolution volume grows."
            )
            if kwargs.get("allow_vacuous"):
                return
            raise CommandError(
                "cluster-consistency check was vacuous (0 clusters checked) - failing loudly so a "
                "dormant check cannot be mistaken for a passing one. Pass --allow-vacuous to "
                "report the banner without failing the run."
            )

        if not result.divergent:
            print(
                f"[cluster-consistency] no divergent clusters found across "
                f"{result.clusters_checked} cluster(s) checked."
            )
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
