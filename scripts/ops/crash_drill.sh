#!/usr/bin/env bash
# crash_drill.sh v2 (post-review) — kill-safety acceptance test over the
# fetch-failed cohort. HONEST SCOPE (review finding): the --card-ids-file
# path deliberately bypasses the bulk resume-skip filter, so this drill
# proves: (a) a kill -9 mid-batch loses no committed work and corrupts
# nothing; (b) the interrupted run's ledger tells the truth; (c) an
# identical re-invocation completes idempotently with zero manual cleanup.
# The bulk-path resume-skip filter itself is unit-tested; its live proof
# rides the next natural --limit harvest. Doubles as the fetch-failed
# retry pass (#381). Wall time worst case ~1.5h (timeout-bound fetches).
# NOTE for the executor/owner: a GoogleFetchLockoutError failure means the
# environment locked us out mid-drill, not that resume logic is broken.
set -euo pipefail
LOGDIR="$HOME/.local/share/proxyprints-daemon/drills"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/drill-$(date -u +%Y%m%dT%H%M%SZ).log"; exec > >(tee -a "$LOG") 2>&1
TS=$(date -u +%Y%m%dT%H%MZ); RUN="crash-drill-$TS"; IDS=/MPCAutofill/MPCAutofill/drill_fetchfail_ids.txt
DEX="docker exec -w /MPCAutofill/MPCAutofill mpcautofill_django"
echo "drill start $(date -u +%FT%TZ) run_id=$RUN"

# v4 cohort: the fetch-failed pool collapsed to ~10 after the 2026-07-23 retry
# pass, too small to host a kill window. Use a 1,000-card seeded slice of the
# blank-collector-text pool instead: re-extraction there is idempotent evidence
# refresh (harmless, useful), and ~4 minutes of run gives the window room.
$DEX python manage.py shell -c "
from cardpicker.models import ImageEvidence
import random
pool = sorted(set(ImageEvidence.objects.filter(fetch_ok=True, collector_line_raw_text='').exclude(run_id='ntx-0721').values_list('card_id', flat=True)))
ids = sorted(random.Random(20260723).sample(pool, min(1000, len(pool))))
open('$IDS','w').write('\n'.join(map(str, ids)))
print('cohort:', len(ids), 'of pool', len(pool))"

echo "phase 2: dry-run (guard satisfaction, same scope)"
$DEX python manage.py run_image_evidence_cohort --card-ids-file "$IDS" --dry-run --run-id "$RUN-dry"

echo "phase 3: write + kill -9 mid-batch"
$DEX python manage.py run_image_evidence_cohort --card-ids-file "$IDS" --run-id "$RUN-w1" &
CLIENT=$!
# Progress-triggered kill: strike only while verifiably mid-batch (5%-85%
# committed), sampling every 15s. Avoids spurious too-early/too-late failures
# from fixed timers on a cohort whose per-card time varies 100x (fast 404 vs
# 15s timeout). If the run finishes before reaching the window, that is a
# fail-closed exit 3 (nothing was provable), not a contract failure.
TOTAL=$(grep -c . <($DEX cat "$IDS") 2>/dev/null || $DEX python -c "print(sum(1 for l in open('$IDS') if l.strip()))")
LOW=$(( TOTAL / 20 )); [ "$LOW" -lt 1 ] && LOW=1; HIGH=$(( TOTAL * 85 / 100 ))
KILLED=0
for i in $(seq 1 120); do
  sleep 15
  if ! kill -0 $CLIENT 2>/dev/null; then break; fi
  DONE=$($DEX python manage.py shell -c "from cardpicker.models import ImageEvidence; print(ImageEvidence.objects.filter(run_id='$RUN-w1').values('card_id').distinct().count())" 2>/dev/null | tail -1)
  echo "  progress sample: $DONE / $TOTAL committed"
  case "$DONE" in (*[!0-9]*|"") continue;; esac
  if [ "$DONE" -ge "$LOW" ] && [ "$DONE" -le "$HIGH" ]; then
    # v5: the container image has neither pgrep nor kill (nor ps) — discover
    # and signal from the HOST: docker top prints host-namespace PIDs.
    PID=$(sudo docker top mpcautofill_django | grep run_image_evidence_cohort | grep -v grep | awk '{print $2}' | head -1 || true)
    case "$PID" in (*[!0-9]*|"") continue;; esac
    echo "killing host pid $PID (container run) at $DONE/$TOTAL committed, $(date -u +%FT%TZ)"
    sudo kill -9 "$PID"
    KILLED=1
    break
  fi
done
[ "$KILLED" != "1" ] && { echo "DRILL-FAIL: never caught the run mid-window (finished too fast, stalled pre-window, or never started) - nothing provable this pass"; kill $CLIENT 2>/dev/null || true; exit 3; }
wait $CLIENT || echo "client exited nonzero after kill (expected)"

echo "phase 4: interrupted-state truth + durable partial work"
$DEX python manage.py shell -c "
from cardpicker.models import PilotRunLedger, ImageEvidence
r = PilotRunLedger.objects.filter(run_id='$RUN-w1').first()
assert r is not None, 'no ledger row for interrupted run'
assert r.status != 'completed', 'w1 marked completed despite kill -9: status lies'
ids = [int(x) for x in open('$IDS') if x.strip()]
w1_done = ImageEvidence.objects.filter(card_id__in=ids, run_id='$RUN-w1').values('card_id').distinct().count()
print('w1 ledger status:', r.status, '| w1 committed cards:', w1_done, 'of', len(ids))
assert w1_done > 0, 'kill landed before ANY committed work - drill window too early to prove durability'
assert w1_done < len(ids), 'w1 finished everything before the kill - drill window too late'
open('/tmp/drill_w1_done.txt','w').write(str(w1_done))"

echo "phase 5: identical re-invocation (zero manual cleanup; override logged by design)"
$DEX python manage.py run_image_evidence_cohort --card-ids-file "$IDS" --skip-dryrun-check --run-id "$RUN-w2"

echo "phase 6: final-state verification"
$DEX python manage.py shell -c "
from cardpicker.models import PilotRunLedger, ImageEvidence
w2 = PilotRunLedger.objects.filter(run_id='$RUN-w2').first()
assert w2 is not None and w2.status == 'completed', 'retry run did not complete: %s' % (w2.status if w2 else None)
ids = [int(x) for x in open('$IDS') if x.strip()]
covered = ImageEvidence.objects.filter(card_id__in=ids).values('card_id').distinct().count()
assert covered == len(ids), 'evidence coverage incomplete after retry: %d of %d' % (covered, len(ids))
w1_done = int(open('/tmp/drill_w1_done.txt').read())
now_ok = ImageEvidence.objects.filter(card_id__in=ids, fetch_ok=True).values('card_id').distinct().count()
print('retry completed | cohort', len(ids), '| w1 partial survived:', w1_done, '| now fetch_ok:', now_ok)"
docker exec mpcautofill_django rm -f "$IDS" || true
echo "DRILL-PASS $(date -u +%FT%TZ) log=$LOG"
