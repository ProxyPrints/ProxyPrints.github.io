from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.filename_candidates import run_filename_candidate_narrowing


class Command(BaseCommand):
    help = (
        "Casts machine-weight (source=deduction) CardPrintingTag votes for cards whose filename "
        "resolves to MORE THAN ONE CanonicalCard name match - the case deductive_backfill's D1/D2 "
        "tiers discard as 'ambiguous, no match' (see cardpicker/filename_candidates.py). Every "
        "candidate is kept and weighted by how many of expansion_hint/canonical_artist_id/"
        "treatment-tag signals corroborate it, rather than collapsing the card to no-match. "
        "These are suggestions, never resolutions - the human-backed gate in vote_consensus."
        "resolve_weighted_consensus means machine-only votes can never resolve a card by "
        "themselves. Idempotent: a card that already has a vote from this command, or from "
        "deductive_backfill (which is exact where it applies), is never revisited. DRY-RUN BY "
        "DEFAULT - --write is required to actually cast anything."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the number of cards considered in this invocation. Useful for staged "
            "rollout or a bounded --dry-run sample.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually cast the identified votes. Default is dry-run: report every counter "
            "below without writing anything or running the gate check.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="CardPrintingTag rows per purge-and-write batch. Default: 500 (smaller than "
            "deductive_backfill's 2000 - this module writes several rows per card, not one, so "
            "the same row-count batch covers fewer cards).",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        limit = kwargs["limit"]
        write = kwargs["write"]
        batch_size = kwargs["batch_size"]
        dry_run = not write

        mode = "DRY RUN" if dry_run else "WRITE"
        print(f"[{mode}] filename_candidate_narrowing --limit={limit} --batch-size={batch_size}")

        result = run_filename_candidate_narrowing(limit=limit, dry_run=dry_run, batch_size=batch_size)

        print(f"Cards considered: {result.cards_considered}")
        print(f"Cards with a candidate set: {result.cards_with_candidates}")
        print(f"Cards abstained (no name match): {result.cards_abstained_no_name_match}")
        print(f"Cards abstained (contradiction): {result.cards_abstained_contradiction}")
        print(f"Votes written: {result.votes_written}")
        print("Candidate-set size distribution:")
        for size in sorted(result.candidate_set_size_histogram):
            print(f"  {size} candidate(s): {result.candidate_set_size_histogram[size]} card(s)")
        if result.contradiction_examples:
            print(f"Contradiction examples (up to {len(result.contradiction_examples)}):")
            for example in result.contradiction_examples:
                print(f"  {example}")

        if dry_run:
            print("Dry run - nothing written, gate check not run.")
            return

        if result.gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) resolved after a machine-only "
                f"vote, which should be structurally impossible - STOP and investigate before "
                f"continuing this backfill. Affected card pks: {result.gate_violations[:50]}"
                + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        print(f"Gate check passed: 0/{result.votes_written} affected cards resolved.")
