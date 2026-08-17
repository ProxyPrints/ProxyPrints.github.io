```
TASK: WTC feed latency fix — branch `fix/wtc-feed-latency` (worktree `/tmp/opencode/wt-wtc-latency`),
      commit `76b92202`, PR https://github.com/ProxyPrints/ProxyPrints.github.io/pull/836

WHAT SHIPPED:
1. Precomputed information-gain scoring at warm time (the dominant cost): every pool builder in
   `question_feed_pools.py` now stores `_precomputed_information_gain_score` on `PoolEntry.score`;
   `_iter_windowed_from_random_offset` sorts its bounded window by that precomputed value, with a
   `_live_information_gain_score` fallback for entries whose builder did not precompute one (a v1
   pool still in the shared cache while this change deploys). The draw no longer performs any
   vote-query scoring on the request path. Served items stay byte-for-byte identical for the same
   voter/state; the `_CANDIDATE_SCORING_WINDOW` bounded-sort semantic and the random-offset
   anti-convergence property are unchanged.
2. Cached `get_contested_card_ids` (`printing_consensus.py`) on the cross-process `"shared"` cache:
   single stable key `contested-card-ids:v1`, 300s TTL, hit returns a fresh list copy (a mutating
   caller cannot poison the cached value), read-side degradation to live compute on a pre-#543
   environment (never a 500). Because the set is a pure function of persisted votes, the TTL is the
   whole invalidation policy, same convention as the remaining-estimate counts. This also stabilises
   `get_remaining_estimate`'s digest key (the view path passes the now-cached resolved set), so its
   ~9.2s cold body is paid at most once per contested-ids TTL instead of churning per vote change.
3. Removed the vestigial bare `get_contested_artist_card_ids()` call in `question_feed.py`
   `get_next_question_feed_item`'s contested lane (a pre-pool-waterfall leftover, ~23ms/9-10
   queries of pure waste on every contested serve). The contested lane's artist half already relies
   on a per-candidate read-time `artist_vote_status=CONTESTED` filter in `draw_contested_entry` —
   the same "still CONTESTED right now" staleness guarantee the printing half's
   `_fetch_unresolved_printing_card` documents — so resolution-after-warm is excluded at draw time
   regardless. The function itself stays: `_tier_2_contested` and the contested pool builder still
   consume it.
4. Tests: contested-ids cache hit/clear/mutation-safety; warm-time scoring (draw performs zero
   scoring; precomputed == fallback == direct `_question_information_gain_score` for the same
   state); contested-artist-resolved-since-warm draw regression (locks the removal in (3) to the
   read-time staleness check); score-stripped pool-membership assertions in the builder tests.

DEVIATIONS: none from spec. The fix that previously "sounded right after diagnosis" — precomputing
   scores at warm time rather than caching scored draws — was the one implemented, per the decided
   plan. One knock-on during verification: `Optional` was not imported in `printing_consensus.py`
   (my new helper's annotation needed it); added to the typing import, re-ran the scoped suite.

VERIFICATION:
   - `/home/ubuntu/.venvs/mpcautofill-pilot/bin/python -m pytest cardpicker/tests/test_question_feed.py cardpicker/tests/test_question_feed_pools.py cardpicker/tests/test_md5_group_pooling.py -q`
     → 223 passed
   - `/home/ubuntu/.venvs/mpcautofill-pilot/bin/python -m pytest . -q` → 3908 passed, 8 skipped
   - `py_compile` on all 5 changed files clean; pre-commit (ruff/isort/black/mypy/prettier) green on
     commit; `gh pr view` → OPEN, MERGEABLE, base master, exactly the 5 intended files
   - Baseline measurements (2026-08-16, prod container, read-only): draws 288-791 queries /
     9.1-9.6s; `get_contested_card_ids` 520-686ms / 8-9 queries; remaining-estimate cold 9.2s /
     25 queries, warm 2.9ms / 1 query; dead contested-artist call 23-26ms / 9-10 queries.
   - DEFERRED: re-measuring the post-change request path against live prod — the container runs a
     baked image with only `scryfall_cache` mounted, so worktree edits are invisible inside it and
     `docker cp` is unavailable; the after numbers are asserted via the test suite
     (`test_draw_of_a_warm_pool_performs_no_scoring` asserts zero `_question_information_gain_score`
     calls on the draw) rather than re-timed against prod. PR test-plan checkbox notes this.

OPEN ITEMS / DECISIONS NEEDED:
1. Owner to review/merge PR #836 (or request changes).
2. After merge: deploy; then a one-off live re-timing of the endpoint (draw + remaining-estimate
   cold path) is the remaining confirmation the container limitation deferred.
3. Warm-time scoring query cost during pool warm: the builders now pay the per-entry scoring the
   draws used to pay. This is once per warm per lane (5-240min cadence, off the request path), but
   no live query-count re-measure of a full warm was taken this session — see (2).

LIVE STATE: branch `fix/wtc-feed-latency` pushed to origin (`76b92202`); PR #836 OPEN against
   master, not merged. No background tasks, servers, or deployments left running. Worktree remains
   at `/tmp/opencode/wt-wtc-latency` for follow-up work.
```
