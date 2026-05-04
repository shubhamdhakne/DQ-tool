"""Pandas-based data quality profiling: counts, nulls, types, min/max, size."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


def _file_extension(path: str | Path) -> str:
    return Path(path).suffix.lower().lstrip(".") or "unknown"


def _detect_file_type(path: str | Path) -> str:
    ext = _file_extension(path)
    mapping = {
        "csv": "CSV",
        "tsv": "TSV",
        "txt": "Text",
        "parquet": "Parquet",
        "pq": "Parquet",
        "json": "JSON",
        "jsonl": "JSON Lines",
        "ndjson": "JSON Lines",
        "xlsx": "Excel",
        "xls": "Excel",
        "feather": "Feather",
        "orc": "ORC",
    }
    return mapping.get(ext, ext.upper() if ext else "Unknown")


def load_dataframe(path: str | Path, **read_kwargs: Any) -> pd.DataFrame:
    """Load a DataFrame from a file path based on extension."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, **read_kwargs)
    if ext == ".tsv" or ext == ".txt":
        return pd.read_csv(path, sep="\t", **read_kwargs)
    if ext in (".parquet", ".pq"):
        return pd.read_parquet(path, **read_kwargs)
    if ext == ".json":
        return pd.read_json(path, **read_kwargs)
    if ext in (".jsonl", ".ndjson"):
        return pd.read_json(path, lines=True, **read_kwargs)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, **read_kwargs)
    if ext == ".feather":
        return pd.read_feather(path, **read_kwargs)
    if ext == ".orc":
        return pd.read_orc(path, **read_kwargs)

    raise ValueError(f"Unsupported file extension for auto-load: {ext}")


def _safe_min_max(series: pd.Series) -> tuple[Any, Any]:
    s = series.dropna()
    if s.empty:
        return None, None
    if pd.api.types.is_numeric_dtype(s):
        return float(s.min()), float(s.max())
    if pd.api.types.is_datetime64_any_dtype(s):
        return str(s.min()), str(s.max())
    if pd.api.types.is_bool_dtype(s):
        return bool(s.min()), bool(s.max())
    # strings / objects: lexical min/max on string conversion
    try:
        ss = s.astype(str)
        return ss.min(), ss.max()
    except (TypeError, ValueError):
        return None, None


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    min_value: Any
    max_value: Any
    memory_bytes: int

    def as_dict(self) -> dict[str, Any]:
        nn = self.non_null_count
        uniq_ratio = (self.unique_count / nn) if nn > 0 else 0.0
        flags: list[str] = []
        if self.null_pct >= 90:
            flags.append("SEVERE_NULL")
        elif self.null_pct >= 50:
            flags.append("HIGH_NULL")
        elif self.null_pct >= 20:
            flags.append("ELEVATED_NULL")
        if nn > 20 and uniq_ratio < 0.05:
            flags.append("LOW_UNIQUENESS")
        if nn > 0 and self.unique_count == 1:
            flags.append("CONSTANT_VALUE")
        dq_flags = "; ".join(flags) if flags else ""
        return {
            "column": self.name,
            "dtype": self.dtype,
            "non_null_count": self.non_null_count,
            "null_count": self.null_count,
            "null_pct": round(self.null_pct, 4),
            "unique_count": self.unique_count,
            "uniqueness_ratio": round(uniq_ratio, 6),
            "min": self.min_value,
            "max": self.max_value,
            "memory_bytes": self.memory_bytes,
            "dq_flags": dq_flags,
        }


@dataclass
class DatasetProfile:
    source_path: str | None
    file_type: str
    file_extension: str
    file_size_bytes: int | None
    row_count: int
    column_count: int
    empty_column_count: int  # columns 100% null when row_count > 0
    total_cells: int
    total_nulls: int
    overall_null_pct: float
    memory_usage_bytes: int
    dtypes_json: str
    columns: list[ColumnProfile] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path or "",
            "file_type": self.file_type,
            "file_extension": self.file_extension,
            "file_size_bytes": self.file_size_bytes,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "empty_column_count": self.empty_column_count,
            "total_cells": self.total_cells,
            "total_nulls": self.total_nulls,
            "overall_null_pct": round(self.overall_null_pct, 4),
            "memory_usage_bytes": self.memory_usage_bytes,
            "dtypes_summary": self.dtypes_json,
        }


class DataQualityProfiler:
    """Compute row/column/null/type/min-max/size metrics for a DataFrame."""

    def __init__(self, df: pd.DataFrame, source_path: str | Path | None = None):
        self.df = df
        self.source_path = str(source_path) if source_path else None

    def profile(self) -> DatasetProfile:
        df = self.df
        path = self.source_path

        row_count = len(df)
        column_count = len(df.columns)
        total_cells = row_count * column_count if column_count else 0

        mem = int(df.memory_usage(deep=True).sum())
        dtype_counts = df.dtypes.astype(str).value_counts().to_dict()
        dtypes_json = json.dumps(dtype_counts, indent=2)

        file_size: int | None = None
        ext = ""
        ftype = "In-memory"
        path_str = (path or "").strip()
        # Logical URIs (Fabric, S3, Azure labels) are not filesystem paths — Path() gives wrong suffix / no size.
        if path_str and "://" in path_str:
            scheme, _, rest = path_str.partition("://")
            scheme = scheme.lower()
            if scheme == "fabric":
                ftype = "Fabric SQL"
                ext = "sql"
            elif scheme == "s3":
                ftype = "S3"
                key = rest.split("/", 1)[-1] if "/" in rest else rest
                ext = _file_extension(Path(key)) if key else ""
            elif scheme == "azure":
                ftype = "Azure Blob"
                parts = rest.split("/", 2)
                key = parts[2] if len(parts) > 2 else ""
                ext = _file_extension(Path(key)) if key else ""
            else:
                ftype = f"{scheme.upper()} (URI)"
                ext = scheme
            # No on-disk file: use in-memory footprint so Files_Overview size / human columns populate.
            file_size = int(mem)
        elif path_str:
            p = Path(path)
            ext = _file_extension(p)
            ftype = _detect_file_type(p)
            if p.is_file():
                file_size = p.stat().st_size

        columns: list[ColumnProfile] = []
        total_nulls = 0
        for col in df.columns:
            s = df[col]
            null_count = int(s.isna().sum())
            total_nulls += null_count
            non_null = row_count - null_count
            null_pct = (null_count / row_count * 100) if row_count else 0.0
            nunique = int(s.nunique(dropna=True))
            vmin, vmax = _safe_min_max(s)
            col_mem = int(s.memory_usage(deep=True))
            columns.append(
                ColumnProfile(
                    name=str(col),
                    dtype=str(s.dtype),
                    non_null_count=non_null,
                    null_count=null_count,
                    null_pct=null_pct,
                    unique_count=nunique,
                    min_value=vmin,
                    max_value=vmax,
                    memory_bytes=col_mem,
                )
            )

        overall_null_pct = (total_nulls / total_cells * 100) if total_cells else 0.0

        empty_column_count = (
            sum(1 for c in columns if c.non_null_count == 0) if row_count > 0 else 0
        )

        return DatasetProfile(
            source_path=path,
            file_type=ftype,
            file_extension=ext,
            file_size_bytes=file_size,
            row_count=row_count,
            column_count=column_count,
            empty_column_count=empty_column_count,
            total_cells=total_cells,
            total_nulls=total_nulls,
            overall_null_pct=overall_null_pct,
            memory_usage_bytes=mem,
            dtypes_json=dtypes_json,
            columns=columns,
        )


def profile_dataframe(df: pd.DataFrame, source_path: str | Path | None = None) -> DatasetProfile:
    return DataQualityProfiler(df, source_path).profile()


def profile_file(path: str | Path, **read_kwargs: Any) -> tuple[pd.DataFrame, DatasetProfile]:
    df = load_dataframe(path, **read_kwargs)
    prof = profile_dataframe(df, source_path=path)
    return df, prof
