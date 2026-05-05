"""Write data quality profile to a multi-sheet Excel workbook."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from dq_tool.profiler import DatasetProfile

# Files_Overview column order (table_name immediately after source_path).
_FILES_OVERVIEW_COL_ORDER = [
    "source_path",
    "table_name",
    "file_type",
    "file_extension",
    "file_size_bytes",
    "file_size_human",
    "row_count",
    "column_count",
    "empty_column_count",
    "total_null_cells",
    "table_null_pct",
    "memory_usage_bytes",
    "memory_usage_human",
]


def append_profile_to_batch(
    prof: DatasetProfile,
    *,
    display_source: str,
    table_name: str,
    summaries: list[dict[str, Any]],
    all_column_rows: list[dict[str, Any]],
    all_dtype_rows: list[dict[str, Any]],
) -> None:
    """Append one profile's summary, per-column rows (with table-level ``empty_column_count``), and dtype rows to batch lists."""
    summary = prof.summary_dict()
    summary["source_path"] = display_source
    summary["table_name"] = table_name
    summaries.append(summary)
    empty_count = int(summary.get("empty_column_count") or 0)
    for col in prof.columns:
        row = col.as_dict()
        row["source_path"] = display_source
        row["table_name"] = table_name
        row["empty_column_count"] = empty_count
        all_column_rows.append(row)
    dtype_counts = json.loads(prof.dtypes_json)
    for dtype, count in dtype_counts.items():
        all_dtype_rows.append(
            {
                "source_path": display_source,
                "table_name": table_name,
                "dtype": dtype,
                "count": int(count),
            }
        )


def _order_files_overview_columns(df: pd.DataFrame) -> pd.DataFrame:
    front = [c for c in _FILES_OVERVIEW_COL_ORDER if c in df.columns]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest] if front else df


def reorder_column_details_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Column-metrics display order for dashboards and exports.
    Puts ``empty_column_count`` immediately after ``dtype``; supports both raw profiler names and Excel renames.
    """
    cols = list(df.columns)
    pref = [
        "source_path",
        "table_name",
        "column_name",
        "column",
        "dtype",
        "empty_column_count",
        "column_non_null_count",
        "non_null_count",
        "column_null_count",
        "null_count",
        "column_null_pct",
        "null_pct",
        "unique_count",
        "uniqueness_ratio",
        "dq_flags",
        "min",
        "max",
        "memory_bytes",
        "memory_human",
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for p in pref:
        if p in cols and p not in seen:
            ordered.append(p)
            seen.add(p)
    for c in cols:
        if c not in seen:
            ordered.append(c)
            seen.add(c)
    return df[ordered]


# Clearer Excel headers for null metrics (dataset vs column grain).
_EXCEL_SUMMARY_METRIC_RENAMES = {
    "total_nulls": "total_null_cells",
    "overall_null_pct": "table_null_pct",
}
_EXCEL_COLUMN_RENAMES = {
    "column": "column_name",
    "null_count": "column_null_count",
    "null_pct": "column_null_pct",
    "non_null_count": "column_non_null_count",
}


def _summary_dict_for_excel(summary: dict[str, Any]) -> dict[str, Any]:
    """Copy summary with renamed null keys for workbook readability."""
    out: dict[str, Any] = {}
    for k, v in summary.items():
        out[_EXCEL_SUMMARY_METRIC_RENAMES.get(k, k)] = v
    return out


def _rename_column_metrics_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    renames = {k: v for k, v in _EXCEL_COLUMN_RENAMES.items() if k in df.columns}
    return df.rename(columns=renames) if renames else df


def logical_table_name(canonical_source: str | None, *, fallback_index: int | None = None) -> str:
    """
    Short dataset name from a blob URI or file path: basename without extension
    (e.g. azure://.../sales.csv -> sales). Used to tie columns to a logical table/file.
    """
    s = (canonical_source or "").strip().replace("\\", "/")
    if not s:
        return f"dataset_{fallback_index}" if fallback_index is not None else ""
    key_part = s
    if "://" in s:
        rest = s.split("://", 1)[-1]
        parts = rest.split("/", 1)
        key_part = parts[1] if len(parts) > 1 else parts[0]
    base = key_part.rstrip("/").rsplit("/", 1)[-1] if key_part else ""
    base = base.split("?")[0].strip()
    if not base:
        return f"dataset_{fallback_index}" if fallback_index is not None else "dataset"
    stem = Path(base).stem
    return stem if stem else base


def redact_source_uri(uri_or_path: str) -> str:
    """Privacy-friendly location string: keeps cloud bucket/account/container + filename; local shows basename only."""
    s = (uri_or_path or "").strip().replace("\\", "/")
    if not s:
        return ""
    if s.startswith("s3://"):
        rest = s[5:]
        slash = rest.find("/")
        if slash < 0:
            return "s3://***/(object)"
        bucket, key = rest[:slash], rest[slash + 1 :]
        name = key.rsplit("/", 1)[-1] if key else ""
        return f"s3://{bucket}/***/{name}" if name else f"s3://{bucket}/***(hidden)"
    if s.startswith("azure://"):
        rest = s[len("azure://") :]
        parts = rest.split("/", 2)
        if len(parts) < 3:
            return "azure://***(hidden)"
        acct, container, blob = parts[0], parts[1], parts[2]
        name = blob.rsplit("/", 1)[-1] if blob else ""
        return f"azure://{acct}/{container}/***/{name}" if name else f"azure://{acct}/{container}/***(hidden)"
    base = s.rsplit("/", 1)[-1]
    return f"local:***/{base}" if base else "local:***(hidden)"


def format_bytes(n: int | None) -> str:
    if n is None:
        return ""
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(x) < 1024.0:
            return f"{x:.2f} {unit}"
        x /= 1024.0
    return f"{x:.2f} PB"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_context_rows(meta: dict[str, Any]) -> list[tuple[str, Any]]:
    """Flatten report context for a two-column Metric / Value sheet."""
    rows: list[tuple[str, Any]] = []
    for k, v in meta.items():
        if v is None:
            v = ""
        rows.append((str(k), v))
    return rows


def _enrich_summary_row(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    fs = out.get("file_size_bytes")
    if fs is None and out.get("memory_usage_bytes") is not None:
        try:
            fs = int(out["memory_usage_bytes"])
            out["file_size_bytes"] = fs
        except (TypeError, ValueError):
            fs = None
    try:
        out["file_size_human"] = format_bytes(int(fs)) if fs is not None else ""
    except (TypeError, ValueError):
        out["file_size_human"] = ""
    mem = out.get("memory_usage_bytes")
    try:
        out["memory_usage_human"] = format_bytes(int(mem)) if mem is not None else ""
    except (TypeError, ValueError):
        out["memory_usage_human"] = ""
    return out


def _write_combined_all_column_details_sheet(
    writer: pd.ExcelWriter,
    file_summaries: list[dict[str, Any]],
    all_column_rows: list[dict[str, Any]],
) -> int:
    """
    One sheet: top = per-file summary table, gap, then column-level metrics (all files).
    Returns 1-based Excel row number of the column-metrics header row (for dashboard parsing).
    """
    fs_df = pd.DataFrame([_enrich_summary_row(_summary_dict_for_excel(s)) for s in file_summaries])
    fs_cols = [c for c in _FILES_OVERVIEW_COL_ORDER if c in fs_df.columns]
    fs_df = fs_df[fs_cols + [c for c in fs_df.columns if c not in fs_cols]]

    col_df = _rename_column_metrics_for_excel(pd.DataFrame(all_column_rows))
    col_df = reorder_column_details_df(col_df)
    if "memory_bytes" in col_df.columns:
        col_df["memory_human"] = col_df["memory_bytes"].map(format_bytes)

    # 0-based start row for second table: header + f data rows + one blank row
    f = len(fs_df)
    col_start_0 = f + 2
    excel_header_row_1based = col_start_0 + 1

    fs_df.to_excel(writer, sheet_name="All_Column_Details", startrow=0, index=False)
    col_df.to_excel(writer, sheet_name="All_Column_Details", startrow=col_start_0, index=False)
    return excel_header_row_1based


def profile_to_excel(
    profile: DatasetProfile,
    output_path: str | Path,
    report_context: dict[str, Any] | None = None,
    display_source_override: str | None = None,
    canonical_source_for_table_name: str | None = None,
) -> Path:
    """
    Create Excel report with sheets: Report_Context, Overview, Column_Details, Dtype_Summary.
    Column_Details uses column_name, column_null_count, column_null_pct (share of rows null
    in that column), table_null_pct / total_null_cells, and empty_column_count (columns that
    are 100% null when the table has at least one row).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ctx: dict[str, Any] = dict(report_context) if report_context else {}
    ctx.setdefault("data_source_type", "Local file")
    ctx.setdefault("generated_utc", _utc_now_iso())
    ctx.setdefault("file_count", 1)
    ctx["column_details_layout"] = "single_table"
    ctx["column_details_header_row"] = 1

    summary = profile.summary_dict()
    if display_source_override is not None:
        summary["source_path"] = display_source_override
    canon = (canonical_source_for_table_name or profile.source_path or summary.get("source_path") or "").strip()
    summary["table_name"] = (
        logical_table_name(canon)
        or logical_table_name(str(summary.get("source_path") or "").strip())
        or "dataset"
    )

    overview_pairs = _enrich_summary_row(_summary_dict_for_excel(summary))
    overview_df = pd.DataFrame(list(overview_pairs.items()), columns=["metric", "value"])

    col_rows = [c.as_dict() for c in profile.columns]
    tn = summary["table_name"]
    empty_count = int(summary.get("empty_column_count") or 0)
    for row in col_rows:
        row["source_path"] = summary.get("source_path") or ""
        row["table_name"] = tn
        row["empty_column_count"] = empty_count

    columns_df = _rename_column_metrics_for_excel(pd.DataFrame(col_rows))
    columns_df["memory_human"] = columns_df["memory_bytes"].map(format_bytes)
    columns_df = reorder_column_details_df(columns_df)

    dtype_counts = json.loads(profile.dtypes_json)
    dtype_summary = pd.Series(dtype_counts, name="count").rename_axis("dtype").reset_index()

    ctx_rows = _report_context_rows(ctx)
    context_df = pd.DataFrame(ctx_rows, columns=["metric", "value"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        context_df.to_excel(writer, sheet_name="Report_Context", index=False)
        overview_df.to_excel(writer, sheet_name="Overview", index=False)
        columns_df.to_excel(writer, sheet_name="Column_Details", index=False)
        dtype_summary.to_excel(writer, sheet_name="Dtype_Summary", index=False)

    return output_path


def write_batch_workbook(
    summaries: list[dict[str, Any]],
    all_column_rows: list[dict[str, Any]],
    all_dtype_rows: list[dict[str, Any]],
    output_path: str | Path,
    report_context: dict[str, Any],
) -> Path:
    """Multi-file / cloud batch workbook with Report_Context, Files_Overview, combined All_Column_Details, etc."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meta = dict(report_context)
    meta.setdefault("generated_utc", _utc_now_iso())
    meta["file_count"] = len(summaries)

    fs_overview = pd.DataFrame([_enrich_summary_row(_summary_dict_for_excel(s)) for s in summaries])
    fs_overview = _order_files_overview_columns(fs_overview)
    dtype_df = pd.DataFrame(all_dtype_rows)

    f = len(summaries)
    meta["column_details_header_row"] = f + 3
    meta["column_details_layout"] = "file_summary_then_columns"
    ctx_df = pd.DataFrame(_report_context_rows(meta), columns=["metric", "value"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        ctx_df.to_excel(writer, sheet_name="Report_Context", index=False)
        fs_overview.to_excel(writer, sheet_name="Files_Overview", index=False)
        _write_combined_all_column_details_sheet(writer, summaries, all_column_rows)
        dtype_df.to_excel(writer, sheet_name="All_Dtype_Summary", index=False)

    return output_path
