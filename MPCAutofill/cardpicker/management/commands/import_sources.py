import csv
import os
from typing import Any

from bulk_sync import bulk_sync
from django_q.tasks import async_task

from django.core.management.base import BaseCommand

from cardpicker.models import Card, Source


def read_sources_csv() -> list[Source]:
    def _read_rows(path: str) -> list[dict[str, str]]:
        with open(path, newline="") as csvfile:
            return list(csv.DictReader(csvfile, delimiter=","))

    def _key_from_name(name: str) -> str:
        return name.strip().replace(" ", "_").translate(str.maketrans("", "", "!\"#$%&'()*+,./:;<=>?@[\]^`{|}~"))

    public_rows = _read_rows("drives.csv")

    private_rows: list[dict[str, str]] = []
    if os.path.exists("drives.private.csv"):
        private_rows = _read_rows("drives.private.csv")

    # Private wins on duplicate key; warn for each collision.
    private_keys = {_key_from_name(row["name"]) for row in private_rows}
    merged_rows = []
    for row in public_rows:
        if _key_from_name(row["name"]) in private_keys:
            print(
                f"Warning: duplicate source '{row['name'].strip()}' in drives.private.csv overrides drives.csv entry."
            )
        else:
            merged_rows.append(row)
    merged_rows += private_rows

    sources = [
        Source(
            key=_key_from_name(row["name"]),
            name=row["name"].strip(),
            identifier=row["drive_id"],
            external_link="https://drive.google.com/open?id=" + row["drive_id"]
            if str(row["drive_public"]).lower() != "false"
            else None,
            description=row["description"],
            ordinal=i,
        )
        for i, row in enumerate(merged_rows)
    ]

    print("Read CSV file{} and found {} sources.".format("s" if private_rows else "", len(sources)))
    return sources


def sync_sources(sources: list[Source]) -> None:
    key_fields = ("key",)
    bulk_sync(new_models=sources, key_fields=key_fields, filters=None, db_class=Source)


def maybe_trigger_bootstrap_scan() -> None:
    """
    Fresh-instance safety net: the daily `update_database` django-q schedule (seeded by
    migrations 0043/0048 with next_run=now()) already self-triggers an async first scan on
    a brand-new instance, so this isn't strictly required - but if that first firing ever
    loses the race against this command (scans before any Source rows exist), the next
    opportunity is a full 24h later. Sources existing with zero Cards is the real,
    narrow signal for "never scanned yet" - not a BOOTSTRAP env var - and only fires once
    since it becomes false as soon as any Card exists. Queued via async_task, not called
    directly, so it can never block gunicorn from binding.
    """
    if Source.objects.exists() and not Card.objects.exists():
        async_task("django.core.management.call_command", "update_database")


class Command(BaseCommand):
    # set up help line to print the available drive options
    help = "Synchronises Google Drives from drives.csv (and drives.private.csv if present) to database."

    def handle(self, *args: Any, **kwargs: dict[str, Any]) -> None:
        sources = read_sources_csv()
        if sources:
            sync_sources(sources)
            print("All sources imported from CSV to database.")
        else:
            print("No sources imported to database because none were found.")
        maybe_trigger_bootstrap_scan()
