"""Write data quality profile to a multi-sheet Excel workbook."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from dq_tool.profiler import DatasetProfile


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
    fs_df = pd.DataFrame([_enrich_summary_row(s) for s in file_summaries])
    preferred_fs_cols = [
        "source_path",
        "table_name",
        "file_type",
        "file_extension",
        "file_size_bytes",
        "file_size_human",
        "row_count",
        "column_count",
        "total_nulls",
        "overall_null_pct",
        "memory_usage_bytes",
        "memory_usage_human",
    ]
    fs_cols = [c for c in preferred_fs_cols if c in fs_df.columns]
    fs_df = fs_df[fs_cols + [c for c in fs_df.columns if c not in fs_cols]]

    col_df = pd.DataFrame(all_column_rows)
    preferred_col_order = [
        "source_path",
        "table_name",
        "column",
        "dtype",
        "non_null_count",
        "null_count",
        "null_pct",
        "unique_count",
        "uniqueness_ratio",
        "dq_flags",
        "min",
        "max",
        "memory_bytes",
    ]
    front = [c for c in preferred_col_order if c in col_df.columns]
    col_df = col_df[front + [c for c in col_df.columns if c not in front]]
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
    df: pd.DataFrame | None,
    output_path: str | Path,
    sample_rows: int = 10,
    report_context: dict[str, Any] | None = None,
    display_source_override: str | None = None,
    canonical_source_for_table_name: str | None = None,
) -> Path:
    """
    Create Excel report with sheets: Report_Context (optional), Overview, Column_Details,
    Dtype_Summary, Sample_Data. Column_Details includes uniqueness_ratio and dq_flags.
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

    overview_pairs = _enrich_summary_row(summary)
    overview_df = pd.DataFrame(list(overview_pairs.items()), columns=["metric", "value"])

    col_rows = [c.as_dict() for c in profile.columns]
    tn = summary["table_name"]
    for row in col_rows:
        row["source_path"] = summary.get("source_path") or ""
        row["table_name"] = tn

    columns_df = pd.DataFrame(col_rows)
    preferred = [
        "source_path",
        "table_name",
        "column",
        "dtype",
        "non_null_count",
        "null_count",
        "null_pct",
        "unique_count",
        "uniqueness_ratio",
        "dq_flags",
        "min",
        "max",
        "memory_bytes",
    ]
    front = [c for c in preferred if c in columns_df.columns]
    columns_df = columns_df[front + [c for c in columns_df.columns if c not in front]]
    columns_df["memory_human"] = columns_df["memory_bytes"].map(format_bytes)

    dtype_counts = json.loads(profile.dtypes_json)
    dtype_summary = pd.Series(dtype_counts, name="count").rename_axis("dtype").reset_index()

    ctx_rows = _report_context_rows(ctx)
    context_df = pd.DataFrame(ctx_rows, columns=["metric", "value"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        context_df.to_excel(writer, sheet_name="Report_Context", index=False)
        overview_df.to_excel(writer, sheet_name="Overview", index=False)
        columns_df.to_excel(writer, sheet_name="Column_Details", index=False)
        dtype_summary.to_excel(writer, sheet_name="Dtype_Summary", index=False)
        if df is not None and sample_rows > 0:
            head = df.head(sample_rows)
            head.to_excel(writer, sheet_name="Sample_Data", index=True)

    return output_path


def build_batch_sample_data_long(samples: list[pd.DataFrame]) -> pd.DataFrame | None:
    """
    Batch reports: one row per cell for the first N rows of each file.
    Readable when files have different columns (avoids a single wide, sparse concat).
    """
    if not samples:
        return None
    rows: list[dict[str, Any]] = []
    source_keys = ("__dq_source_path", "__dq_source_file", "__dq_source")
    for sdf in samples:
        if sdf is None or sdf.empty:
            continue
        src = ""
        for k in source_keys:
            if k in sdf.columns:
                v = sdf.iloc[0][k]
                src = "" if pd.isna(v) else str(v)
                break
        tn = ""
        if "__dq_table_name" in sdf.columns:
            tv = sdf.iloc[0]["__dq_table_name"]
            tn = "" if pd.isna(tv) else str(tv)
        data_cols = [c for c in sdf.columns if not str(c).startswith("__dq_")]
        for ridx in range(len(sdf)):
            row = sdf.iloc[ridx]
            for col in data_cols:
                val = row[col]
                if pd.isna(val):
                    val_s = ""
                elif hasattr(val, "isoformat"):
                    try:
                        val_s = val.isoformat()  # type: ignore[no-untyped-call]
                    except (OSError, ValueError, TypeError):
                        val_s = str(val)
                else:
                    val_s = str(val)
                rows.append(
                    {
                        "table_name": tn,
                        "source_path": src,
                        "sample_row": ridx + 1,
                        "column_name": col,
                        "cell_value": val_s,
                    }
                )
    if not rows:
        return None
    return pd.DataFrame(
        rows,
        columns=["table_name", "source_path", "sample_row", "column_name", "cell_value"],
    )


def write_batch_workbook(
    summaries: list[dict[str, Any]],
    all_column_rows: list[dict[str, Any]],
    all_dtype_rows: list[dict[str, Any]],
    samples_concat: pd.DataFrame | None,
    output_path: str | Path,
    report_context: dict[str, Any],
) -> Path:
    """Multi-file / cloud batch workbook with Report_Context, Files_Overview, combined All_Column_Details, etc."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meta = dict(report_context)
    meta.setdefault("generated_utc", _utc_now_iso())
    meta["file_count"] = len(summaries)

    fs_overview = pd.DataFrame([_enrich_summary_row(s) for s in summaries])
    dtype_df = pd.DataFrame(all_dtype_rows)

    f = len(summaries)
    meta["column_details_header_row"] = f + 3
    meta["column_details_layout"] = "file_summary_then_columns"
    if samples_concat is not None and not samples_concat.empty:
        meta["sample_data_layout"] = "long_tidy"
    ctx_df = pd.DataFrame(_report_context_rows(meta), columns=["metric", "value"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        ctx_df.to_excel(writer, sheet_name="Report_Context", index=False)
        fs_overview.to_excel(writer, sheet_name="Files_Overview", index=False)
        _write_combined_all_column_details_sheet(writer, summaries, all_column_rows)
        dtype_df.to_excel(writer, sheet_name="All_Dtype_Summary", index=False)
        if samples_concat is not None and not samples_concat.empty:
            samples_concat.to_excel(writer, sheet_name="Sample_Data", index=False)

    return output_path
