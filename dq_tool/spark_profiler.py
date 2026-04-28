"""
Optional PySpark data quality profile → Pandas summary → same Excel pipeline.

Install: pip install pyspark
Run: spark-submit dq_tool/spark_profiler.py <path_or_table> --output report.xlsx
   or: python -m dq_tool.spark_profiler <path> -o report.xlsx

For local files, path should be CSV/Parquet/JSON (Spark read).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        NumericType,
        TimestampType,
        DateType,
        BooleanType,
    )
except ImportError:
    SparkSession = None  # type: ignore[misc, assignment]

import pandas as pd

from dq_tool.excel_export import profile_to_excel
from dq_tool.profiler import DatasetProfile, ColumnProfile


def _spark_type_name(dt) -> str:
    return dt.simpleString()


def profile_spark_dataframe(df, source_path: str | None = None) -> tuple[pd.DataFrame, DatasetProfile]:
    """Build DatasetProfile from a Spark DataFrame (collects column stats only, not full data)."""
    if SparkSession is None:
        raise RuntimeError("pyspark is not installed. pip install pyspark")

    cols = df.columns
    types_by_name = {f.name: f.dataType for f in df.schema.fields}
    row_count = df.count()
    column_count = len(cols)

    null_counts_row = df.select([F.sum(F.when(F.col(c).isNull(), 1).otherwise(0)).alias(c) for c in cols]).collect()[0]
    null_per_col = {c: int(null_counts_row[c]) for c in cols}
    total_nulls = sum(null_per_col.values())
    total_cells = row_count * column_count if column_count else 0
    overall_null_pct = (total_nulls / total_cells * 100) if total_cells else 0.0

    dtype_map = {c: _spark_type_name(types_by_name[c]) for c in cols}
    dtype_counts: dict[str, int] = {}
    for _, t in dtype_map.items():
        dtype_counts[t] = dtype_counts.get(t, 0) + 1
    dtypes_json = json.dumps(dtype_counts, indent=2)

    # Approximate deep memory is not available like pandas; use 0 or JVM estimate skip
    memory_usage_bytes = 0

    column_profiles: list[ColumnProfile] = []
    for c in cols:
        dt = types_by_name[c]
        null_count = null_per_col[c]
        non_null = row_count - null_count
        null_pct = (null_count / row_count * 100) if row_count else 0.0
        unique_count = df.select(F.countDistinct(c)).collect()[0][0]
        unique_count = int(unique_count) if unique_count is not None else 0

        vmin: object | None = None
        vmax: object | None = None
        if isinstance(dt, NumericType):
            agg = df.select(F.min(c), F.max(c)).collect()[0]
            vmin, vmax = agg[0], agg[1]
            if vmin is not None:
                vmin = float(vmin)
            if vmax is not None:
                vmax = float(vmax)
        elif isinstance(dt, (TimestampType, DateType)):
            agg = df.select(F.min(c), F.max(c)).collect()[0]
            vmin = str(agg[0]) if agg[0] is not None else None
            vmax = str(agg[1]) if agg[1] is not None else None
        elif isinstance(dt, BooleanType):
            agg = df.select(F.min(c.cast("int")), F.max(c.cast("int"))).collect()[0]
            vmin = bool(agg[0]) if agg[0] is not None else None
            vmax = bool(agg[1]) if agg[1] is not None else None
        else:
            agg = df.select(F.min(F.col(c).cast("string")), F.max(F.col(c).cast("string"))).collect()[0]
            vmin, vmax = agg[0], agg[1]

        column_profiles.append(
            ColumnProfile(
                name=c,
                dtype=dtype_map[c],
                non_null_count=non_null,
                null_count=null_count,
                null_pct=null_pct,
                unique_count=unique_count,
                min_value=vmin,
                max_value=vmax,
                memory_bytes=0,
            )
        )

    file_size = None
    ext = ""
    ftype = "Spark"
    if source_path:
        p = Path(source_path)
        ext = p.suffix.lower().lstrip(".")
        ftype = "Parquet" if ext in ("parquet", "pq") else "CSV" if ext == "csv" else ext.upper() or "Spark"
        if p.is_file():
            file_size = p.stat().st_size

    prof = DatasetProfile(
        source_path=source_path,
        file_type=ftype,
        file_extension=ext,
        file_size_bytes=file_size,
        row_count=row_count,
        column_count=column_count,
        total_cells=total_cells,
        total_nulls=total_nulls,
        overall_null_pct=overall_null_pct,
        memory_usage_bytes=memory_usage_bytes,
        dtypes_json=dtypes_json,
        columns=column_profiles,
    )

    # Small sample for Excel / inspection (limit cost)
    sample_pdf = df.limit(50).toPandas()
    return sample_pdf, prof


def main() -> None:
    if SparkSession is None:
        print("Install pyspark: pip install pyspark", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Spark DQ profile → Excel")
    parser.add_argument("input", help="Path to Parquet/CSV directory or file")
    parser.add_argument("-o", "--output", default="spark_dq_report.xlsx")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("DQTool").getOrCreate()
    path = args.input
    p = Path(path)
    if p.suffix.lower() in (".parquet", ".pq") or p.is_dir():
        sdf = spark.read.parquet(path)
    elif p.suffix.lower() == ".csv":
        sdf = spark.read.option("header", True).option("inferSchema", True).csv(path)
    elif p.suffix.lower() == ".json":
        sdf = spark.read.json(path)
    else:
        sdf = spark.read.parquet(path)

    sample_pdf, prof = profile_spark_dataframe(sdf, source_path=str(p))
    profile_to_excel(prof, sample_pdf, args.output, sample_rows=min(50, len(sample_pdf)))
    spark.stop()
    print(f"Report written: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
