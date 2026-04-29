"""
Streamlit web UI for data quality: upload or path, metrics, charts, Excel download.
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from dq_tool.connections import credentials_root, list_profiles, load_profile, save_profile, test_connection
from dq_tool.excel_export import format_bytes, profile_to_excel
from dq_tool.profiler import load_dataframe, profile_dataframe

try:
    import altair as alt

    _HAS_ALT = True
except ImportError:
    _HAS_ALT = False

st.set_page_config(
    page_title="DQ Tool · Data quality",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="📊",
)

_DASHBOARD_CSS = """
<style>
  .dq-hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 45%, #0c4a6e 100%);
    color: #f8fafc;
    padding: 1.25rem 1.5rem;
    border-radius: 12px;
    margin-bottom: 1rem;
    border: 1px solid rgba(148, 163, 184, 0.25);
  }
  .dq-hero h1 { margin: 0 0 0.35rem 0; font-size: 1.55rem; font-weight: 600; letter-spacing: -0.02em; }
  .dq-hero .sub { color: #94a3b8; font-size: 0.9rem; margin: 0; }
  .dq-pill {
    display: inline-block;
    background: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 999px;
    padding: 0.2rem 0.75rem;
    font-size: 0.78rem;
    margin: 0.15rem 0.35rem 0 0;
    color: #e2e8f0;
  }
  div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
</style>
"""

st.markdown(_DASHBOARD_CSS, unsafe_allow_html=True)

st.title("Data quality dashboard")
st.caption("Profiling, nulls, dtypes, uniqueness, and export to Excel — cloud-aware summaries when reports include run context.")

auto_report_path = os.getenv("DQ_AUTO_REPORT_PATH", "").strip()
auto_report_exists = bool(auto_report_path) and Path(auto_report_path).is_file()
hide_paths_mode = os.getenv("DQ_HIDE_PATHS", "0").strip() == "1"
default_mode_index = 2 if auto_report_exists else 0
_cloud_hint_raw = os.getenv("DQ_CLOUD_SUMMARY_JSON", "").strip()


def _cloud_hint() -> dict[str, str]:
    if not _cloud_hint_raw:
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(_cloud_hint_raw).items()}
    except (json.JSONDecodeError, TypeError):
        return {}


def _df_to_context_map(df: pd.DataFrame | None) -> dict[str, str]:
    if df is None or df.empty:
        return {}
    lower = {str(c).lower(): c for c in df.columns}
    if "metric" in lower and "value" in lower:
        m, v = lower["metric"], lower["value"]
        out: dict[str, str] = {}
        for k, val in zip(df[m], df[v]):
            out[str(k).strip()] = "" if pd.isna(val) else str(val)
        return out
    return {}


def _overview_to_metrics(overview: pd.DataFrame | None) -> dict[str, object]:
    if overview is None or overview.empty:
        return {}
    cols = {str(c).lower(): c for c in overview.columns}
    if "metric" in cols and "value" in cols:
        m, v = cols["metric"], cols["value"]
        return dict(zip(overview[m], overview[v]))
    if "unnamed: 0" in cols and "value" in cols:
        u, v = cols["unnamed: 0"], cols["value"]
        return dict(zip(overview[u], overview[v]))
    return {}


def _parse_combined_all_column_sheet(raw: pd.DataFrame, hr_1based: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Split raw grid (header=None) into file-summary table and column-metrics table."""
    try:
        hr = int(hr_1based)
    except (TypeError, ValueError):
        hr = 1
    if raw is None or raw.empty or hr < 2:
        return None, None
    i = hr - 1
    if i >= len(raw):
        return None, None
    upper = raw.iloc[:i].copy()
    upper.columns = [str(c).strip() if not pd.isna(c) else f"_c{j}" for j, c in enumerate(upper.iloc[0])]
    upper = upper.iloc[1:].reset_index(drop=True)
    upper = upper.dropna(how="all")
    hdr = raw.iloc[i]
    lower = raw.iloc[i + 1 :].copy()
    lower.columns = [str(c).strip() if not pd.isna(c) else f"_c{j}" for j, c in enumerate(hdr.values)]
    lower = lower.dropna(how="all")
    return upper, lower


def _reload_all_column_details_raw(path: str | None, data: bytes | None) -> pd.DataFrame | None:
    try:
        src = path if path else io.BytesIO(data or b"")
        return pd.read_excel(src, sheet_name="All_Column_Details", header=None)
    except (ValueError, OSError, TypeError):
        return None


def _coerce_numeric_columns(df: pd.DataFrame, *column_names: str) -> pd.DataFrame:
    """Excel and mixed exports often load metrics as object; nlargest needs numeric dtypes."""
    if df is None or df.empty:
        return df
    out = df.copy()
    for name in column_names:
        if name in out.columns:
            out[name] = pd.to_numeric(out[name], errors="coerce")
    return out


def _bar_chart(df: pd.DataFrame, x: str, y: str, title: str, x_title: str = "") -> None:
    if df.empty or x not in df.columns or y not in df.columns:
        st.info("Not enough data for this chart.")
        return
    plot_df = df[[x, y]].dropna().copy()
    if plot_df.empty:
        st.info("Not enough data for this chart.")
        return
    if _HAS_ALT:
        chart = (
            alt.Chart(plot_df)
            .mark_bar(cornerRadiusEnd=4, color="#0369a1")
            .encode(
                x=alt.X(f"{y}:Q", title=y.replace("_", " ").title()),
                y=alt.Y(f"{x}:N", sort="-x", title=x_title or x),
                tooltip=[x, y],
            )
            .properties(height=min(420, 24 + len(plot_df) * 18), title=title)
            .configure_axis(labelFontSize=11, titleFontSize=12)
            .configure_title(fontSize=14, anchor="start", color="#0f172a")
        )
        st.altair_chart(chart, width="stretch")
    else:
        st.bar_chart(plot_df.set_index(x)[y])


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
    if c1.button("Load profile", width="stretch"):
        ok, loaded, msg = load_profile(provider_key, profile_name)
        if ok:
            for k, v in loaded.items():
                st.session_state[f"{provider_key}_{k}"] = v
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)

    if c2.button("Save profile", width="stretch"):
        ok, msg = save_profile(provider_key, profile_name, creds)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    if c3.button("Test connection", width="stretch"):
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
            placeholder=r"report\dq_batch_report.xlsx",
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
    if df.empty:
        return df
    safe = df.copy()
    obj_cols = safe.select_dtypes(include=["object"]).columns
    for col in obj_cols:
        safe[col] = safe[col].astype("string")
    return safe


def _render_report_hero(ctx: dict[str, str], files_df: pd.DataFrame | None, hint: dict[str, str]) -> None:
    src = ctx.get("data_source_type") or hint.get("cloud") or "Report"
    pills: list[str] = [f"Source: {src}"]
    if ctx.get("cloud_provider"):
        pills.append(f"Provider: {ctx['cloud_provider']}")
    if ctx.get("s3_bucket"):
        pills.append(f"Bucket: {ctx['s3_bucket']}")
    if ctx.get("s3_prefix"):
        pills.append(f"Prefix: {ctx['s3_prefix']}")
    if ctx.get("storage_account"):
        pills.append(f"Storage account: {ctx['storage_account']}")
    if ctx.get("blob_container"):
        pills.append(f"Container: {ctx['blob_container']}")
    if ctx.get("blob_prefix"):
        pills.append(f"Blob prefix: {ctx['blob_prefix']}")
    if ctx.get("credential_profile"):
        pills.append(f"Profile: {ctx['credential_profile']}")
    if hint.get("report_path") and not hide_paths_mode:
        pills.append(f"Report: {Path(hint['report_path']).name}")

    n_files = 0
    if files_df is not None and not files_df.empty and "row_count" in files_df.columns:
        n_files = len(files_df)
    elif ctx.get("files_profiled_ok"):
        try:
            n_files = int(float(ctx["files_profiled_ok"]))
        except (TypeError, ValueError):
            n_files = 0
    if n_files:
        pills.append(f"Files profiled: {n_files}")

    tfb = ctx.get("total_file_size_bytes", "")
    if tfb:
        try:
            pills.append(f"Total file size: {format_bytes(int(float(tfb)))}")
        except (TypeError, ValueError):
            pass
    tmb = ctx.get("total_memory_usage_bytes", "")
    if tmb:
        try:
            pills.append(f"Total in-memory (sum): {format_bytes(int(float(tmb)))}")
        except (TypeError, ValueError):
            pass
    if ctx.get("distinct_folder_count"):
        pills.append(f"Distinct folders/prefixes: {ctx['distinct_folder_count']}")
    if ctx.get("s3_object_count"):
        pills.append(f"S3 objects: {ctx['s3_object_count']}")
    if ctx.get("blob_object_count"):
        pills.append(f"Blobs: {ctx['blob_object_count']}")
    if ctx.get("generated_utc"):
        pills.append(f"Generated: {ctx['generated_utc']}")

    def _esc(t: str) -> str:
        return (
            t.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    pill_html = "".join(f'<span class="dq-pill">{_esc(p)}</span>' for p in pills[:14])
    st.markdown(
        f'<div class="dq-hero"><h1>DQ report overview</h1>'
        f'<p class="sub">Run context, file inventory, column analytics, and data-quality flags.</p>'
        f'<div>{pill_html}</div></div>',
        unsafe_allow_html=True,
    )


def _show_existing_report(
    sheets: dict[str, pd.DataFrame],
    raw_excel_path: str | None = None,
    raw_excel_bytes: bytes | None = None,
) -> None:
    if not sheets:
        st.warning("No sheets found in report.")
        return

    ctx = _df_to_context_map(sheets.get("Report_Context"))
    hint = _cloud_hint()
    layout = ctx.get("column_details_layout", "")
    acd_raw = None
    if layout == "file_summary_then_columns" and (raw_excel_path or raw_excel_bytes):
        acd_raw = _reload_all_column_details_raw(raw_excel_path, raw_excel_bytes)
    try:
        hr = int(float(ctx.get("column_details_header_row", 1) or 1))
    except (TypeError, ValueError):
        hr = 1
    file_sources_df, col_details = _parse_combined_all_column_sheet(acd_raw, hr) if acd_raw is not None else (None, None)
    if col_details is None:
        col_details = sheets.get("All_Column_Details")
        if col_details is None:
            col_details = sheets.get("Column_Details")

    files_over = sheets.get("Files_Overview")
    if file_sources_df is None and files_over is not None:
        file_sources_df = files_over

    _render_report_hero(ctx, file_sources_df, hint)

    overview = sheets.get("Overview")
    metrics = _overview_to_metrics(overview)

    if files_over is not None and not files_over.empty and "row_count" in files_over.columns:
        try:
            total_rows = int(pd.to_numeric(files_over["row_count"], errors="coerce").fillna(0).sum())
        except (TypeError, ValueError, KeyError):
            total_rows = 0
        try:
            total_nulls = int(pd.to_numeric(files_over["total_nulls"], errors="coerce").fillna(0).sum())
        except (TypeError, ValueError, KeyError):
            total_nulls = int(metrics.get("total_nulls", 0) or 0)
        cols_max = int(pd.to_numeric(files_over["column_count"], errors="coerce").max() or 0)
        total_cells = 0
        try:
            rc = pd.to_numeric(files_over["row_count"], errors="coerce").fillna(0)
            cc = pd.to_numeric(files_over["column_count"], errors="coerce").fillna(0)
            total_cells = int((rc * cc).sum())
        except (TypeError, ValueError, KeyError):
            total_cells = 0
        onull = (total_nulls / total_cells * 100) if total_cells else 0.0
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total rows (all files)", f"{total_rows:,}")
        m2.metric("Max columns (any file)", f"{cols_max:,}")
        m3.metric("Total nulls (all files)", f"{total_nulls:,}")
        m4.metric("Weighted null % (cells)", f"{onull:.2f}%")
        if "memory_usage_bytes" in files_over.columns:
            tm = int(pd.to_numeric(files_over["memory_usage_bytes"], errors="coerce").fillna(0).sum())
            m5.metric("Memory sum (deep)", format_bytes(tm))
        else:
            m5.metric("Memory (deep)", format_bytes(int(metrics.get("memory_usage_bytes", 0) or 0)))
    elif metrics:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Rows", f"{int(float(metrics.get('row_count', 0) or 0)):,}")
        c2.metric("Columns", f"{int(float(metrics.get('column_count', 0) or 0)):,}")
        c3.metric("Total nulls", f"{int(float(metrics.get('total_nulls', 0) or 0)):,}")
        c4.metric("Null % (all cells)", f"{float(metrics.get('overall_null_pct', 0) or 0):.2f}%")
        c5.metric("Memory (deep)", format_bytes(int(float(metrics.get("memory_usage_bytes", 0) or 0))))
    else:
        st.info("Open a report generated by this tool (includes Overview or Files_Overview).")

    tab_summary, tab_columns, tab_charts, tab_flags, tab_raw = st.tabs(
        ["Summary & files", "Column details", "Charts", "Flags & metadata", "All sheets"]
    )

    with tab_summary:
        st.subheader("Files / sources")
        if file_sources_df is not None and not file_sources_df.empty:
            st.dataframe(_arrow_safe_df(file_sources_df), width="stretch", hide_index=True)
        else:
            st.caption("No per-file summary in this workbook (older report format).")
        st.subheader("Report context (key / value)")
        rc_df = sheets.get("Report_Context")
        if rc_df is not None and not rc_df.empty:
            st.dataframe(_arrow_safe_df(rc_df), width="stretch", hide_index=True)
        else:
            st.caption("No Report_Context sheet — regenerate with the latest CLI for cloud and run metadata.")

    with tab_columns:
        if col_details is not None and not col_details.empty:
            st.dataframe(_arrow_safe_df(col_details), width="stretch", hide_index=True)
        else:
            st.warning("No column details found.")

    with tab_charts:
        cd_num = (
            _coerce_numeric_columns(col_details, "null_pct", "memory_bytes")
            if col_details is not None and not col_details.empty
            else col_details
        )
        if cd_num is not None and {"column", "null_pct"}.issubset(cd_num.columns):
            sub = cd_num.nlargest(min(40, len(cd_num)), "null_pct")[["column", "null_pct"]].copy()
            _bar_chart(sub, "column", "null_pct", "Top columns by null %", "Column")
        if cd_num is not None and {"column", "memory_bytes"}.issubset(cd_num.columns):
            sub2 = cd_num.nlargest(min(25, len(cd_num)), "memory_bytes")[["column", "memory_bytes"]].copy()
            if not sub2.empty:
                st.divider()
                _bar_chart(sub2, "column", "memory_bytes", "Largest columns by memory (bytes)", "Column")
        dtype_df = sheets.get("All_Dtype_Summary")
        if dtype_df is None:
            dtype_df = sheets.get("Dtype_Summary")
        if dtype_df is not None and not dtype_df.empty and "dtype" in dtype_df.columns and "count" in dtype_df.columns:
            dtype_df = _coerce_numeric_columns(dtype_df, "count")
            agg = dtype_df.groupby("dtype", as_index=False)["count"].sum().sort_values("count", ascending=False)
            st.divider()
            _bar_chart(agg, "dtype", "count", "Dtype distribution (column count)", "Dtype")
        if file_sources_df is not None and "file_size_bytes" in file_sources_df.columns:
            fs = file_sources_df.copy()
            label_col = "source_path" if "source_path" in fs.columns else fs.columns[0]
            fs["__label"] = fs[label_col].astype(str).str.replace(r".*/", "", regex=True).str.slice(0, 40)
            fs["file_size_bytes"] = pd.to_numeric(fs["file_size_bytes"], errors="coerce").fillna(0)
            subf = fs.nlargest(min(30, len(fs)), "file_size_bytes")[["__label", "file_size_bytes"]]
            st.divider()
            _bar_chart(subf, "__label", "file_size_bytes", "Largest files by size on disk", "File")

    with tab_flags:
        st.markdown("**Automated flags** (HIGH_NULL, LOW_UNIQUENESS, etc.) come from profiling thresholds.")
        if col_details is not None and "dq_flags" in col_details.columns:
            flagged = col_details[col_details["dq_flags"].astype(str).str.len() > 0]
            st.metric("Columns with at least one flag", len(flagged))
            if not flagged.empty:
                st.dataframe(_arrow_safe_df(flagged), width="stretch", hide_index=True)
            else:
                st.success("No columns exceeded the flag thresholds in this report.")
        else:
            st.info("No `dq_flags` column — regenerate the report with the current dq_tool version.")
        st.divider()
        st.markdown("**Dtypes summary (JSON)** from the latest profiled dataset (single-file Overview).")
        if metrics.get("dtypes_summary"):
            st.code(str(metrics.get("dtypes_summary")), language="json")
        else:
            st.caption("Not available for this workbook.")

    with tab_raw:
        for name, df in sheets.items():
            with st.expander(name, expanded=False):
                st.dataframe(_arrow_safe_df(df), width="stretch", hide_index=True)


def run_dashboard() -> None:
    df: pd.DataFrame | None = None
    prof = None
    report_sheets: dict[str, pd.DataFrame] | None = None
    report_raw_bytes: bytes | None = None
    report_raw_path: str | None = None
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
                report_raw_bytes = report_uploaded.getvalue()
                report_sheets = _read_report_bytes(report_raw_bytes)
            elif report_path.strip():
                rp = Path(report_path.strip())
                report_raw_path = str(rp)
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
        _show_existing_report(report_sheets, raw_excel_path=report_raw_path, raw_excel_bytes=report_raw_bytes)
        return

    if df is None or prof is None:
        st.info("Upload a file or enter a valid local path to see the dashboard.")
        return

    s = prof.summary_dict()
    st.markdown(
        '<div class="dq-hero"><h1>Live profile</h1>'
        '<p class="sub">Local path or upload · metrics refresh when the source changes.</p></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{s['row_count']:,}")
    c2.metric("Columns", f"{s['column_count']:,}")
    c3.metric("Total nulls", f"{s['total_nulls']:,}")
    c4.metric("Null % (all cells)", f"{s['overall_null_pct']:.2f}%")
    c5.metric("Memory (deep)", format_bytes(s["memory_usage_bytes"]))

    fd1, fd2, fd3, fd4 = st.columns(4)
    fd1.markdown(f"**Source** · `{s.get('source_path') or 'upload'}`")
    fd2.markdown(f"**Type** · {prof.file_type}")
    fd3.markdown(f"**Extension** · `{prof.file_extension or '—'}`")
    fs = prof.file_size_bytes
    fd4.markdown(f"**File size** · {format_bytes(fs) if fs is not None else 'N/A (upload)'}")

    col_df = pd.DataFrame([c.as_dict() for c in prof.columns])
    col_df["memory_human"] = col_df["memory_bytes"].map(format_bytes)
    col_df_num = _coerce_numeric_columns(col_df, "null_pct", "memory_bytes")

    t1, t2, t3 = st.tabs(["Column metrics", "Charts", "Data preview"])
    with t1:
        st.dataframe(_arrow_safe_df(col_df), width="stretch", hide_index=True)
    with t2:
        if not col_df_num.empty and "null_pct" in col_df_num.columns:
            sub = col_df_num.nlargest(min(40, len(col_df_num)), "null_pct")[["column", "null_pct"]]
            _bar_chart(sub, "column", "null_pct", "Top columns by null %", "Column")
        if not col_df_num.empty and "memory_bytes" in col_df_num.columns:
            sub2 = col_df_num.nlargest(min(25, len(col_df_num)), "memory_bytes")[["column", "memory_bytes"]]
            st.divider()
            _bar_chart(sub2, "column", "memory_bytes", "Largest columns by memory", "Column")
    with t3:
        st.dataframe(_arrow_safe_df(df.head(200)), width="stretch")

    buf_xlsx = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    buf_path = Path(buf_xlsx.name)
    buf_xlsx.close()
    try:
        live_ctx = {
            "data_source_type": "Live profile (dashboard)",
            "paths_hidden": False,
            "input_path": str(s.get("source_path") or "upload"),
        }
        profile_to_excel(prof, df, buf_path, sample_rows=sample_rows, report_context=live_ctx)
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
