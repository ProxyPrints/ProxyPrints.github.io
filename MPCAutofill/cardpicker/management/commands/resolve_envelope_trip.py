"""
Stage E Phase 1 - the RESUME action for a tripped operating envelope (docs/proposals/stage-e-
streaming.md §3 decision (5)/§10(a) - "resume requires a fresh owner action... no self-resume in
every case above"). Thin CLI wrapper around `cardpicker.operating_envelope.acknowledge_trip` - see
that function's own docstring for the full mechanism this enforces.

`--acknowledge-trip <trip-id>` is mandatory (no default, no bare "resume everything" mode) so an
operator must name the SPECIFIC trip they're clearing, and `--note` is likewise mandatory - this
command is the only code path in the codebase permitted to set `EnvelopeTrip.acknowledged_at`,
matching this pipeline's existing `--skip-dryrun-check`-style posture (#373): an override/resume
is always explicit, always logged (durably, on the trip row itself - not just to stdout), never a
silent or default action. This command never dispatches any work itself - clearing a trip only
removes it from `operating_envelope.current_trip()`'s result; a phase-2 streaming dispatcher's own
poll loop is what actually resumes issuing micro-batches once it next observes the envelope clear.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cardpicker.models import EnvelopeTrip
from cardpicker.operating_envelope import acknowledge_trip


class Command(BaseCommand):
    help = (
        "Acknowledge (resume) a tripped Stage E operating-envelope bar (docs/proposals/stage-e-"
        "streaming.md §3 decision (5)/§10(a)) - the only code path permitted to clear an "
        "EnvelopeTrip. Requires an explicit --note explaining why it's safe to resume now; never "
        "resumes silently or by default. See docs/features/stage-e-operations.md for the full "
        "trip/resume runbook."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--acknowledge-trip",
            type=str,
            required=True,
            metavar="TRIP_ID",
            help="The EnvelopeTrip.trip_id to acknowledge - see the streaming daemon's own halt "
            "message, or `EnvelopeTrip.objects.filter(acknowledged_at__isnull=True)`, for the "
            "exact id of whatever is currently open.",
        )
        parser.add_argument(
            "--note",
            type=str,
            required=True,
            help="Mandatory, non-empty, human-readable reason this trip is safe to resume now "
            "(e.g. 'host load back under 3.0, confirmed via top' or 'RSS bar was a false alarm "
            "from a co-tenant process, not this run'). Stored verbatim on the trip's own "
            "acknowledged_note field - never optional, matching this pipeline's "
            "--skip-dryrun-check discipline of never resuming/overriding silently.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        trip_id: str = options["acknowledge_trip"]
        note: str = options["note"].strip()
        if not note:
            raise CommandError("--note must be a non-empty, human-readable reason - never resumed silently.")

        try:
            trip = acknowledge_trip(trip_id, note)
        except EnvelopeTrip.DoesNotExist:
            raise CommandError(f"No EnvelopeTrip found with trip_id={trip_id!r}.")
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            f"ACKNOWLEDGED trip_id={trip.trip_id} bar={trip.bar} tripped_at={trip.tripped_at.isoformat()} "
            f"note={note!r}"
        )
