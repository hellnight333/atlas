"""One command that says what the machine and its jobs are doing.

Written for the moment after reconnecting, when the only thing that matters is
whether anything broke while nobody could see. Everything is read from the
machine at the moment of asking; nothing is cached, because the process holding
a cache may not have survived the gap either.

Deliberately tolerant. A status command that fails because one probe failed is
useless exactly when it is needed, so each probe degrades to a blank rather than
raising — and a blank is visible in the output rather than silently absent.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .models import HealthReport
from .runner import JobRunner

#: What the control plane consists of. A unit missing from this list is not
#: watched, so the list is the definition rather than a convenience.
SERVICES = ("qevik-api", "postgresql", "caddy", "qevik-market-scan.timer", "qevik-backup.timer")

API_HEALTH_URL = "http://127.0.0.1:8080/health"
SITE_HOST_URL = "http://127.0.0.1/"


def _run(argv: list[str], timeout: float = 10.0) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        return done.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _services() -> dict[str, str]:
    return {name: _run(["systemctl", "is-active", name]) or "unknown" for name in SERVICES}


def _memory() -> tuple[int, int]:
    """Used and total MB, from /proc rather than by parsing `free`.

    MemAvailable is the honest number: "free" excludes cache the kernel would
    reclaim on demand, and reading it as pressure produces alarm at idle.
    """
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            values[key] = int(rest.strip().split()[0]) // 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return max(0, total - available), total
    except (OSError, ValueError, IndexError):
        return 0, 0


def _load() -> float:
    try:
        return round(float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0]), 2)
    except (OSError, ValueError, IndexError):
        return 0.0


def _disk_percent(path: str = "/") -> int:
    try:
        import shutil

        usage = shutil.disk_usage(path)
        return round(usage.used * 100 / usage.total)
    except (OSError, ZeroDivisionError):
        return 0


def _process_count() -> int:
    try:
        return sum(1 for p in Path("/proc").iterdir() if p.name.isdigit())
    except OSError:
        return 0


def _browser_count() -> int:
    """Chromium processes actually running.

    Counted by reading /proc rather than shelling out to pgrep, which matches
    its own command line and reported two browsers on a freshly booted host that
    had none — a false alarm that cost real time.
    """
    count = 0
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                name = (entry / "comm").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if name in ("chrome", "chromium", "headless_shell", "chrome_crashpad"):
                count += 1
    except OSError:
        return 0
    return count


def _http_status(url: str) -> int:
    try:
        import httpx

        return httpx.get(url, timeout=5.0).status_code
    except Exception:  # noqa: BLE001 - any failure means "did not answer"
        return 0


def collect(runner: JobRunner | None = None) -> HealthReport:
    """Assemble the report. Never raises."""
    runner = runner or JobRunner()
    used, total = _memory()

    try:
        jobs_active = runner.active()
        jobs_failed = runner.failed()[:5]
        last = runner.last_completed()
    except Exception:  # noqa: BLE001 - a broken job store must not hide the host
        jobs_active, jobs_failed, last = [], [], None

    return HealthReport(
        hostname=_run(["hostname"]) or "",
        uptime=_run(["uptime", "-p"]) or "",
        services=_services(),
        api_healthy=_http_status(API_HEALTH_URL) == 200,
        site_host_status=_http_status(SITE_HOST_URL),
        memory_used_mb=used,
        memory_total_mb=total,
        load_1min=_load(),
        disk_used_percent=_disk_percent(),
        process_count=_process_count(),
        browser_count=_browser_count(),
        active_jobs=jobs_active,
        failed_jobs=jobs_failed,
        last_completed=last,
    )
