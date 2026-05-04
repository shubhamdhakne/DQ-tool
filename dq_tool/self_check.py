"""Sanity checks for profiling + Excel round-trip + chart-safe dtypes.

Run from repo root:
  python -m dq_tool.self_check
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from dq_tool.excel_export import profile_to_excel
from dq_tool.profiler import profile_file


def _coerce_numeric_columns(df: pd.DataFrame, *column_names: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for name in column_names:
        if name in out.columns:
            out[name] = pd.to_numeric(out[name], errors="coerce")
    return out


def main() -> None:
    # 1) Same coercion logic as dashboard — nlargest must not raise on object dtypes
    weird = pd.DataFrame(
        {
            "column": ["x", "y", "z"],
            "null_pct": ["12.5", "3", "40.1"],
            "memory_bytes": ["100", "200", "50"],
        }
    )
    fixed = _coerce_numeric_columns(weird, "null_pct", "memory_bytes")
    _ = fixed.nlargest(2, "null_pct")
    _ = fixed.nlargest(2, "memory_bytes")
    print("coercion + nlargest: OK")

    # 2) Single-file workbook → read_excel often yields object — same path as dashboard charts
    p = Path(tempfile.gettempdir()) / "dq_self_check.csv"
    p.write_text("a,b\n1,\n2,3\n", encoding="utf-8")
    df, prof = profile_file(p)
    out_x = Path(tempfile.gettempdir()) / "dq_self_check_report.xlsx"
    profile_to_excel(
        prof,
        out_x,
        report_context={"data_source_type": "self_check"},
    )
    sheets = pd.read_excel(out_x, sheet_name=None)
    cd = sheets.get("Column_Details")
    assert cd is not None and "column_null_pct" in cd.columns
    cd2 = _coerce_numeric_columns(cd, "column_null_pct", "memory_bytes")
    _ = cd2.nlargest(min(10, len(cd2)), "column_null_pct")
    print(f"xlsx round-trip + nlargest on Column_Details: OK ({len(cd)} rows)")

    dtype_df = sheets.get("Dtype_Summary")
    if dtype_df is not None and "count" in dtype_df.columns:
        d2 = _coerce_numeric_columns(dtype_df, "count")
        _ = d2.groupby("dtype", as_index=False)["count"].sum()
        print("dtype count coercion + groupby: OK")

    p.unlink(missing_ok=True)
    out_x.unlink(missing_ok=True)
    print("dq_tool.self_check: all passed")


if __name__ == "__main__":
    main()
