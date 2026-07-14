import csv
from typing import Any

from bulk_sync import bulk_sync
from django_q.tasks import async_task

from django.core.management.base import BaseCommand

from cardpicker.models import Card, Source


def read_sources_csv() -> list[Source]:
    sources = []

    # read CSV file for drive data
    with open("drives.csv", newline="") as csvfile:
        drivesreader = csv.DictReader(csvfile, delimiter=",")
        # order the sources by row number in CSV
        i = 0
        for row in drivesreader:
            name: str = row["name"].strip()
            key = name.replace(" ", "_").translate(str.maketrans("", "", "!\"#$%&'()*+,./:;<=>?@[\]^`{|}~"))
            sources.append(
                Source(
                    key=key,
                    name=name,
                    identifier=row["drive_id"],
                    external_link="https://drive.google.com/open?id=" + row["drive_id"]
                    if str(row["drive_public"]).lower() != "false"
                    else None,
                    description=row["description"],
                    ordinal=i,
                )
            )
            i += 1

    print("Read CSV file and found {} sources.".format(len(sources)))
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
    help = "Synchronises Google Drives from drives.csv (in root project directory) to database."

    def handle(self, *args: Any, **kwargs: dict[str, Any]) -> None:
        sources = read_sources_csv()
        if sources:
            sync_sources(sources)
            print("All sources imported from CSV to database.")
        else:
            print("No sources imported to database because none were found.")
        maybe_trigger_bootstrap_scan()
