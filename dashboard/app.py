"""
Streamlit web UI for data quality: upload or path, metrics, charts, Excel download.
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from dq_tool.connections import credentials_root, list_profiles, load_profile, save_profile, test_connection
from dq_tool.excel_export import format_bytes, profile_to_excel
from dq_tool.profiler import load_dataframe, profile_dataframe

st.set_page_config(page_title="DQ Tool", layout="wide", initial_sidebar_state="expanded")

st.title("Data quality dashboard")
st.caption("Row/column counts, nulls, dtypes, min/max, file and memory size — export to Excel.")

auto_report_path = os.getenv("DQ_AUTO_REPORT_PATH", "").strip()
auto_report_exists = bool(auto_report_path) and Path(auto_report_path).is_file()
hide_paths_mode = os.getenv("DQ_HIDE_PATHS", "0").strip() == "1"
default_mode_index = 2 if auto_report_exists else 0


def _cloud_fields(provider: str) -> list[tuple[str, str, bool]]:
    if provider == "AWS":
        return [
            ("access_key_id", "Access Key ID", False),
            ("secret_access_key", "Secret Access Key", True),
            ("session_token", "Session Token (optional)", True),
            ("region", "Region (e.g., ap-south-1)", False),
        ]
    if provider == "Azure":
        return [
            ("connection_string", "Azure Blob Connection String", True),
        ]
    return [
        ("account", "Account", False),
        ("user", "User", False),
        ("password", "Password", True),
        ("warehouse", "Warehouse", False),
        ("database", "Database", False),
        ("schema", "Schema", False),
        ("role", "Role (optional)", False),
    ]


def _render_connections_panel() -> None:
    st.markdown("---")
    st.subheader("Cloud connections")
    provider_label = st.selectbox("Provider", ["AWS", "Azure", "Snowflake"], key="conn_provider")
    provider_key = provider_label.lower()
    existing_profiles = list_profiles(provider_key)
    selected_existing = st.selectbox(
        "Saved profiles",
        ["(new profile)"] + existing_profiles,
        key="conn_saved_profile",
    )
    if selected_existing != "(new profile)":
        st.session_state["conn_profile_name"] = selected_existing
    elif "conn_profile_name" not in st.session_state:
        st.session_state["conn_profile_name"] = "default"
    profile_name = st.text_input("Profile name", key="conn_profile_name")

    fields = _cloud_fields(provider_label)
    creds: dict[str, str] = {}
    for field_key, label, is_secret in fields:
        state_key = f"{provider_key}_{field_key}"
        creds[field_key] = st.text_input(
            label,
            value=st.session_state.get(state_key, ""),
            type="password" if is_secret else "default",
            key=state_key,
        )

    c1, c2, c3 = st.columns(3)
    if c1.button("Load profile", use_container_width=True):
        ok, loaded, msg = load_profile(provider_key, profile_name)
        if ok:
            for k, v in loaded.items():
                st.session_state[f"{provider_key}_{k}"] = v
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)

    if c2.button("Save profile", use_container_width=True):
        ok, msg = save_profile(provider_key, profile_name, creds)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    if c3.button("Test connection", use_container_width=True):
        ok, msg = test_connection(provider_key, creds)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    st.caption(f"Credentials path: `{credentials_root()}` (editable JSON files by cloud/profile)")


with st.sidebar:
    st.header("Data source")
    mode = st.radio(
        "Load mode",
        [
            "Profile raw data (upload)",
            "Profile raw data (local path)",
            "View existing DQ report (.xlsx)",
        ],
        index=default_mode_index,
        horizontal=False,
    )
    uploaded = None
    local_path = ""
    report_uploaded = None
    report_path = ""
    if mode == "Profile raw data (upload)":
        uploaded = st.file_uploader(
            "CSV, Excel, Parquet, JSON",
            type=["csv", "tsv", "txt", "parquet", "pq", "xlsx", "xls", "json", "jsonl"],
        )
    elif mode == "Profile raw data (local path)":
        local_path = st.text_input("Absolute path to data file", placeholder=r"C:\data\file.csv")
    else:
        report_uploaded = st.file_uploader("Existing DQ report", type=["xlsx"])
        report_path = st.text_input(
            "Or absolute path to report (.xlsx)",
            placeholder=r"C:\reports\dq_report.xlsx",
            value=auto_report_path if auto_report_exists else "",
        )

    sample_rows = st.slider("Sample rows in Excel", 0, 100, 10)
    _render_connections_panel()


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


@st.cache_data(show_spinner=False)
def _read_report_bytes(data: bytes) -> dict[str, pd.DataFrame]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return pd.read_excel(tmp_path, sheet_name=None)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _arrow_safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert object columns to pandas StringDtype for reliable Arrow serialization in Streamlit.
    This avoids mixed-type conversion warnings/errors (e.g., int + str in same column).
    """
    if df.empty:
        return df

    safe = df.copy()
    obj_cols = safe.select_dtypes(include=["object"]).columns
    for col in obj_cols:
        safe[col] = safe[col].astype("string")
    return safe


def _show_existing_report(sheets: dict[str, pd.DataFrame]) -> None:
    if not sheets:
        st.warning("No sheets found in report.")
        return

    st.subheader("Report view")
    overview = sheets.get("Overview")
    col_details = sheets.get("Column_Details")

    if overview is not None and {"Unnamed: 0", "value"}.issubset(set(overview.columns)):
        metrics = dict(zip(overview["Unnamed: 0"], overview["value"]))
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Rows", f"{int(metrics.get('row_count', 0)):,}")
        c2.metric("Columns", f"{int(metrics.get('column_count', 0)):,}")
        c3.metric("Total nulls", f"{int(metrics.get('total_nulls', 0)):,}")
        c4.metric("Null % (all cells)", f"{float(metrics.get('overall_null_pct', 0)):.2f}%")
        c5.metric("Memory (deep)", format_bytes(int(metrics.get("memory_usage_bytes", 0))))

    tab_names = [name for name in ["Overview", "Column_Details", "Dtype_Summary", "Sample_Data"] if name in sheets]
    other_tabs = [n for n in sheets.keys() if n not in tab_names]
    all_tabs = tab_names + other_tabs
    tabs = st.tabs(all_tabs)
    for i, name in enumerate(all_tabs):
        with tabs[i]:
            st.dataframe(_arrow_safe_df(sheets[name]), width="stretch", hide_index=True)

    if col_details is not None and {"column", "null_pct"}.issubset(set(col_details.columns)):
        st.subheader("Nulls chart")
        chart_df = col_details.nlargest(min(50, len(col_details)), "null_pct")[["column", "null_pct"]]
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("column"))


def run_dashboard() -> None:
    df: pd.DataFrame | None = None
    prof = None
    report_sheets: dict[str, pd.DataFrame] | None = None
    err = None

    try:
        if mode == "Profile raw data (upload)" and uploaded is not None:
            raw = uploaded.getvalue()
            df, prof = _profile_from_uploaded(uploaded.name, raw)
        elif mode == "Profile raw data (local path)" and local_path.strip():
            p = Path(local_path.strip())
            df = load_dataframe(p)
            prof = profile_dataframe(df, source_path=str(p))
        elif mode == "View existing DQ report (.xlsx)":
            if report_uploaded is not None:
                report_sheets = _read_report_bytes(report_uploaded.getvalue())
            elif report_path.strip():
                rp = Path(report_path.strip())
                report_sheets = pd.read_excel(rp, sheet_name=None)
    except (OSError, ValueError, TypeError, pd.errors.EmptyDataError) as e:
        err = str(e)

    if err:
        st.error(err)
        return

    if mode == "View existing DQ report (.xlsx)":
        if report_sheets is None:
            st.info("Upload a report or provide a valid local .xlsx report path.")
            return
        if auto_report_exists and report_path.strip() == auto_report_path:
            if hide_paths_mode:
                st.success("Auto-loaded generated report.")
            else:
                st.success(f"Auto-loaded generated report: `{auto_report_path}`")
        _show_existing_report(report_sheets)
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
        st.dataframe(_arrow_safe_df(col_df), width="stretch", hide_index=True)
    with tab2:
        chart_df = col_df.nlargest(min(50, len(col_df)), "null_pct")[["column", "null_pct"]]
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("column"))
        else:
            st.write("No columns to chart.")
    with tab3:
        st.dataframe(_arrow_safe_df(df.head(50)), width="stretch")

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
