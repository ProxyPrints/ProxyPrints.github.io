"""
Process-level resident-memory sampling, shared by the Stage E observability work (docs/proposals/
stage-e-streaming.md §3 decision (6)/§10(a)'s ratified per-worker RSS bar, consumed by
`cardpicker.operating_envelope`) and available to any future caller needing the same primitive.
Deliberately NOT wired into `run_image_evidence_cohort.py`'s own pre-existing `_get_rss_mb`
(2026-07-22) - that command's tests already monkeypatch `_get_rss_mb` as a module-local attribute
by name (`cohort_command._get_rss_mb`), so replacing it with an import from here would touch a
working, tested call site for no behavioural gain; the two implementations are intentionally
duplicated (same ~10 lines), not shared, so neither module's own test suite is coupled to the
other's internals.

MEASUREMENT CHOICE: `/proc/self/status`'s `VmRSS` line, not `resource.getrusage(RUSAGE_SELF).
ru_maxrss`. `ru_maxrss` is a lifetime HIGH-WATER MARK that only ever grows (and is measured in KB
on Linux but bytes on macOS - platform-ambiguous), the wrong shape for a bar that a streaming
daemon needs to see fall back under a threshold again once memory is freed (the whole point of a
pause-then-resume envelope, not a one-way kill switch). `VmRSS` is the CURRENT, point-in-time
resident set size - already the convention `run_image_evidence_cohort.py::_get_rss_mb` established
(2026-07-22) for exactly this reason, and every environment this code ever runs in is Linux
(Docker containers on the host described in docs/infrastructure.md), so `/proc` availability is
not a portability concern here the way it would be for genuinely cross-platform code.
"""

from typing import Optional


def get_process_rss_mb() -> Optional[float]:
    """
    Best-effort CURRENT resident set size (MB) of THIS process, read from `/proc/self/status`
    (module docstring - see there for why this, not `resource.getrusage`). Deliberately never
    raises: this is a diagnostic/safety-bar input, not something a caller should fail over just
    because it's running somewhere `/proc` isn't readable (a non-Linux dev box, a locked-down
    sandbox) - returns `None` in that case, and every caller must treat `None` as "skip the
    RSS-dependent behaviour this time," never as an error (matches
    `run_image_evidence_cohort.py::_get_rss_mb`'s own documented convention).
    """
    try:
        with open("/proc/self/status") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None
