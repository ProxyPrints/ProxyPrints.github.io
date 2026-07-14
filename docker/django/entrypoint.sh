#!/bin/bash
set -e

# Wait for postgres to come up
echo "Waiting for Postgres..."
sleep 10
while ! nc -z postgres 5432; do
    echo "Still waiting for Postgres..."
    sleep 5
done

# Wait for elasticsearch to come up
echo "Waiting for Elasticsearch..."
sleep 10
until curl --silent --output /dev/null http://elasticsearch:9200/_cat/health?h=st; do
    echo "Still waiting for Elasticsearch..."
    sleep 5
done

# Gather static files
python3 manage.py collectstatic --noinput

# Schema migrations are the only step allowed to block gunicorn binding - always run,
# regardless of whether anything's pending (a no-op migrate is fast and safe).
echo "Migrate Django database..."
python3 manage.py migrate

# Cheap, local-only (no network calls) - keeps Source rows in sync with drives.csv on
# every boot. Catalog content itself (update_database/update_dfcs) is deliberately NOT
# run here: it's covered by the pre-existing daily/weekly django-q schedules (see
# migrations 0043/0048) plus an async bootstrap guard inside import_sources for a
# genuinely fresh instance. Rescanning ~250+ sources against Google Drive can take
# many minutes to hours and must never block the API from coming up - see
# docs/infrastructure.md's "Startup vs. scheduled catalog sync" section.
echo "Read drives from CSV..."
python3 manage.py import_sources

exec "$@"
