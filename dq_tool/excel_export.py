"""Write data quality profile to a multi-sheet Excel workbook."""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from dq_tool.profiler import DatasetProfile


def profile_to_excel(
    profile: DatasetProfile,
    df: pd.DataFrame | None,
    output_path: str | Path,
    sample_rows: int = 10,
) -> Path:
    """
    Create Excel report with sheets: Overview, Column_Details, Dtype_Summary, Sample_Data.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = profile.summary_dict()
    overview_df = pd.DataFrame([summary]).T
    overview_df.columns = ["value"]

    col_rows = [c.as_dict() for c in profile.columns]
    columns_df = pd.DataFrame(col_rows)

    dtype_counts = json.loads(profile.dtypes_json)
    dtype_summary = pd.Series(dtype_counts, name="count").rename_axis("dtype").reset_index()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        overview_df.to_excel(writer, sheet_name="Overview")
        columns_df.to_excel(writer, sheet_name="Column_Details", index=False)
        dtype_summary.to_excel(writer, sheet_name="Dtype_Summary", index=False)
        if df is not None and sample_rows > 0:
            head = df.head(sample_rows)
            head.to_excel(writer, sheet_name="Sample_Data", index=True)

    return output_path


def format_bytes(n: int | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"
