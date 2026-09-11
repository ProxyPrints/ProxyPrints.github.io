TASK: Make #980 green again and rewrite PR body to match current code
Branch: feat/frame-family-identifiers
PR: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/980

WHAT SHIPPED:

1. stage_e_dispatch.py:879 — changed `if candidate_frame_families:` to `if candidate_frame_families is not None:` with updated comment
2. test_stage_e_dispatch.py — added `candidate_frame_families=None` to `_stub_compute_card_evidence_ok`, `_recording_stub`, and both `fake_compute` stubs
3. test_stage_e_shakedown.py — added `candidate_frame_families=None` to `_stub_compute`
4. test_stream_full_catalog.py — added `candidate_frame_families=None` to `_stub_compute`
5. PR body rewritten with measured population table and accurate test plan

DEVIATIONS from spec:

- makemigrations --check failed with pre-existing staticfiles manifest error (missing cardpicker/favicon.ico), unrelated to this change
- None other

VERIFICATION:

- Full test suite: 4215 passed, 11 skipped (610.71s)
- test_local_identify_printing_tags.py: included in full run
- test_local_layout_class_cast.py: included in full run
- Pre-commit hooks: all passed (ruff, isort, black, mypy, prettier)
- Commit: bc9a07f2

OPEN ITEMS / DECISIONS NEEDED:

1. CI not watched per dispatch convention — owner to verify GitHub Actions pass

LIVE STATE:

- Branch feat/frame-family-identifiers pushed to origin
- PR #980 updated with new body
- No local state left behind
