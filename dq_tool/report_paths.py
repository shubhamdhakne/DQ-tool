"""Default folder for generated Excel reports (repo `report/`)."""

from __future__ import annotations

from pathlib import Path

REPORT_DIRNAME = "report"


def project_root() -> Path:
    """Repository root (directory that contains the `dq_tool` package)."""
    return Path(__file__).resolve().parents[1]


def reports_dir() -> Path:
    p = project_root() / REPORT_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_report_file(filename: str) -> Path:
    """Resolved path under `report/<filename>`."""
    return reports_dir() / filename
