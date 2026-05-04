"""Default folder for generated Excel reports (repo `report/`)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

REPORT_DIRNAME = "report"


def utc_timestamp_for_report_filename() -> str:
    """UTC compact timestamp safe for filenames (no colons). Milliseconds disambiguate same-second runs."""
    t = datetime.now(timezone.utc)
    ms = t.microsecond // 1000
    return t.strftime("%Y%m%dT%H%M%S") + f"{ms:03d}Z"


def unique_report_basename(filename: str) -> str:
    """Insert UTC timestamp before the extension, e.g. ``dq_batch_report.xlsx`` → ``dq_batch_report_20260504T120000000Z.xlsx``."""
    p = Path(filename)
    return f"{p.stem}_{utc_timestamp_for_report_filename()}{p.suffix}"


def project_root() -> Path:
    """Repository root (directory that contains the `dq_tool` package)."""
    return Path(__file__).resolve().parents[1]


def reports_dir() -> Path:
    p = project_root() / REPORT_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_report_file(filename: str) -> Path:
    """Resolved path under ``report/`` with a unique UTC timestamp in the basename (unless ``-o`` is used)."""
    return reports_dir() / unique_report_basename(filename)
