"""
Tests for cardpicker.process_metrics.get_process_rss_mb - shared RSS-sampling primitive for the
Stage E envelope work (docs/proposals/stage-e-streaming.md §3 decision (6)/§10(a)). Mirrors
test_run_image_evidence_cohort.py's own TestGetRssMb coverage of that command's pre-existing,
intentionally-duplicated `_get_rss_mb` (see this module's own docstring for why duplicated, not
shared).
"""

from typing import Any

import pytest

from cardpicker.process_metrics import get_process_rss_mb


class TestGetProcessRssMb:
    def test_returns_a_positive_float_on_linux(self) -> None:
        rss_mb = get_process_rss_mb()
        # This test suite only runs on Linux (the pilot venv, CI) - /proc/self/status should
        # always be readable here, so a hard None would itself be a regression worth seeing fail.
        assert rss_mb is not None
        assert rss_mb > 0

    def test_never_raises_when_proc_status_is_unreadable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_oserror(*args: Any, **kwargs: Any) -> Any:
            raise OSError("no /proc here")

        monkeypatch.setattr("builtins.open", _raise_oserror)

        assert get_process_rss_mb() is None

    def test_never_raises_on_malformed_vmrss_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io

        def _fake_open(*args: Any, **kwargs: Any) -> Any:
            return io.StringIO("VmRSS:\tnot-a-number kB\n")

        monkeypatch.setattr("builtins.open", _fake_open)

        assert get_process_rss_mb() is None

    def test_returns_none_when_vmrss_line_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io

        def _fake_open(*args: Any, **kwargs: Any) -> Any:
            return io.StringIO("VmSize:\t123456 kB\n")

        monkeypatch.setattr("builtins.open", _fake_open)

        assert get_process_rss_mb() is None
