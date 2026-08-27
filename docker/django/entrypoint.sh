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

# Seed the tag taxonomies (default descriptors, attribute chips, no-match reasons, sensitive
# tags) - cheap, local-only get_or_create calls against a DB already migrated above, so this
# is safe on every boot, not just a fresh instance. Without this, a vote channel whose Tag row
# was never manually seeded raises RuntimeError, which stage_e_dispatch's caster loop catches
# and turns into a silently-zero counter rather than a startup failure - so a missed seed looks
# like a deployed, inert channel instead of an obvious error. seed_sensitive_tags runs last
# because it upgrades moderation_class on tags that may already exist, including ones the
# seeders above just created (see its own docstring's "future seeding-order change" note).
# Non-fatal despite `set -e`: an un-seeded tag degrades one advisory channel, but a container
# that won't boot over it takes the whole API down - a strictly worse outcome for a cosmetic
# gap. Migrations above keep their existing blocking behaviour; this is intentionally weaker.
echo "Seed tag taxonomies..."
python3 manage.py seed_default_tags || echo "seed_default_tags failed (non-fatal - see docker/django/entrypoint.sh)"
python3 manage.py seed_attribute_tags || echo "seed_attribute_tags failed (non-fatal - see docker/django/entrypoint.sh)"
python3 manage.py seed_no_match_reason_tags || echo "seed_no_match_reason_tags failed (non-fatal - see docker/django/entrypoint.sh)"
python3 manage.py seed_sensitive_tags || echo "seed_sensitive_tags failed (non-fatal - see docker/django/entrypoint.sh)"

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
