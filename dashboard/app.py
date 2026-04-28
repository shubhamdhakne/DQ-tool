"""
Streamlit web UI for data quality: upload or path, metrics, charts, Excel download.
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from dq_tool.excel_export import format_bytes, profile_to_excel
from dq_tool.profiler import load_dataframe, profile_dataframe

st.set_page_config(page_title="DQ Tool", layout="wide", initial_sidebar_state="expanded")

st.title("Data quality dashboard")
st.caption("Row/column counts, nulls, dtypes, min/max, file and memory size — export to Excel.")

with st.sidebar:
    st.header("Data source")
    mode = st.radio("Load data", ["Upload file", "Local file path"], horizontal=False)
    uploaded = None
    local_path = ""
    if mode == "Upload file":
        uploaded = st.file_uploader(
            "CSV, Excel, Parquet, JSON",
            type=["csv", "tsv", "txt", "parquet", "pq", "xlsx", "xls", "json", "jsonl"],
        )
    else:
        local_path = st.text_input("Absolute path to data file", placeholder=r"C:\data\file.csv")

    sample_rows = st.slider("Sample rows in Excel", 0, 100, 10)


@st.cache_data(show_spinner=False)
def _profile_from_uploaded(name: str, data: bytes) -> tuple[pd.DataFrame, object]:
    suffix = Path(name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        df = load_dataframe(tmp_path)
        prof = profile_dataframe(df, source_path=name)
        return df, prof
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_dashboard() -> None:
    df: pd.DataFrame | None = None
    prof = None
    err = None

    try:
        if mode == "Upload file" and uploaded is not None:
            raw = uploaded.getvalue()
            df, prof = _profile_from_uploaded(uploaded.name, raw)
        elif mode == "Local file path" and local_path.strip():
            p = Path(local_path.strip())
            df = load_dataframe(p)
            prof = profile_dataframe(df, source_path=str(p))
    except Exception as e:  # noqa: BLE001 — show user-friendly error in UI
        err = str(e)

    if err:
        st.error(err)
        return

    if df is None or prof is None:
        st.info("Upload a file or enter a valid local path to see the dashboard.")
        return

    s = prof.summary_dict()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{s['row_count']:,}")
    c2.metric("Columns", f"{s['column_count']:,}")
    c3.metric("Total nulls", f"{s['total_nulls']:,}")
    c4.metric("Null % (all cells)", f"{s['overall_null_pct']:.2f}%")
    c5.metric("Memory (deep)", format_bytes(s["memory_usage_bytes"]))

    st.subheader("File details")
    fd1, fd2, fd3, fd4 = st.columns(4)
    fd1.write(f"**Path / name:** `{s.get('source_path') or 'upload'}`")
    fd2.write(f"**File type:** {prof.file_type}")
    fd3.write(f"**Extension:** `{prof.file_extension or '—'}`")
    fs = prof.file_size_bytes
    fd4.write(f"**File size:** {format_bytes(fs) if fs is not None else 'N/A (upload)'}")

    with st.expander("Dtype summary (JSON)"):
        st.code(s.get("dtypes_summary", ""), language="json")

    col_df = pd.DataFrame([c.as_dict() for c in prof.columns])
    col_df["memory_human"] = col_df["memory_bytes"].apply(format_bytes)

    tab1, tab2, tab3 = st.tabs(["Column metrics", "Nulls chart", "Data preview"])
    with tab1:
        st.dataframe(col_df, use_container_width=True, hide_index=True)
    with tab2:
        chart_df = col_df.nlargest(min(50, len(col_df)), "null_pct")[["column", "null_pct"]]
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("column"))
        else:
            st.write("No columns to chart.")
    with tab3:
        st.dataframe(df.head(50), use_container_width=True)

    buf_xlsx = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    buf_path = Path(buf_xlsx.name)
    buf_xlsx.close()
    try:
        profile_to_excel(prof, df, buf_path, sample_rows=sample_rows)
        data = buf_path.read_bytes()
        st.download_button(
            label="Download Excel report",
            data=data,
            file_name="dq_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    finally:
        buf_path.unlink(missing_ok=True)


run_dashboard()
