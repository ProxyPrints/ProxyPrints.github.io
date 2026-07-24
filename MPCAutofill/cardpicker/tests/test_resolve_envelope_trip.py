"""
Tests for the resolve_envelope_trip management command - the RESUME action for a tripped Stage E
operating envelope (docs/proposals/stage-e-streaming.md §3 decision (5)/§10(a)). Covers the CLI
wiring (required flags, error surfaces) on top of operating_envelope.acknowledge_trip's own
already-tested mechanism (see test_operating_envelope.py::TestAcknowledgeTrip).
"""

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.models import EnvelopeTrip
from cardpicker.operating_envelope import EnvelopeSignals, check_envelope


class TestRequiredArguments:
    def test_missing_acknowledge_trip_raises(self, db):
        with pytest.raises(CommandError):
            call_command("resolve_envelope_trip", "--note", "some reason")

    def test_missing_note_raises(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        with pytest.raises(CommandError):
            call_command("resolve_envelope_trip", "--acknowledge-trip", trip.trip_id)

    def test_empty_note_raises(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        with pytest.raises(CommandError, match="non-empty"):
            call_command("resolve_envelope_trip", "--acknowledge-trip", trip.trip_id, "--note", "   ")


class TestAcknowledging:
    def test_acknowledges_an_open_trip(self, db, capsys):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))

        call_command(
            "resolve_envelope_trip",
            "--acknowledge-trip",
            trip.trip_id,
            "--note",
            "host load confirmed back under 3.0",
        )

        trip.refresh_from_db()
        assert trip.acknowledged_at is not None
        assert trip.acknowledged_note == "host load confirmed back under 3.0"

        out = capsys.readouterr().out
        assert "ACKNOWLEDGED" in out
        assert trip.trip_id in out

    def test_unknown_trip_id_raises_command_error(self, db):
        with pytest.raises(CommandError, match="No EnvelopeTrip found"):
            call_command("resolve_envelope_trip", "--acknowledge-trip", "envtrip-nonexistent", "--note", "x")

    def test_already_acknowledged_trip_raises_command_error(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        call_command("resolve_envelope_trip", "--acknowledge-trip", trip.trip_id, "--note", "first")

        with pytest.raises(CommandError, match="already acknowledged"):
            call_command("resolve_envelope_trip", "--acknowledge-trip", trip.trip_id, "--note", "second")

        trip.refresh_from_db()
        assert trip.acknowledged_note == "first"

    def test_acknowledging_one_trip_does_not_touch_another(self, db):
        trip_a = check_envelope(EnvelopeSignals(load_avg=8.0))
        trip_b = check_envelope(EnvelopeSignals(rss_mb_per_worker=600.0))

        call_command("resolve_envelope_trip", "--acknowledge-trip", trip_a.trip_id, "--note", "resolved a")

        trip_b.refresh_from_db()
        assert trip_b.acknowledged_at is None
        assert EnvelopeTrip.objects.filter(acknowledged_at__isnull=True).count() == 1
