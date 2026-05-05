"""Microsoft Fabric SQL: list tables in a schema and profile full source data (all rows per table by default)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from dq_tool.connections import build_fabric_odbc_connection_string, load_profile


def _sql_bracket_ident(part: str) -> str:
    return "[" + part.replace("]", "]]") + "]"


def _safe_schema_name(schema: str) -> str:
    s = (schema or "").strip()
    if not s or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
        raise ValueError(f"Invalid SQL schema name: {schema!r}")
    return s


def list_user_tables_in_schema(conn, schema: str) -> list[str]:
    """Return base table names for a schema (INFORMATION_SCHEMA)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE UPPER(TABLE_SCHEMA) = UPPER(?)
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """,
            (schema,),
        )
        return [str(r[0]) for r in cur.fetchall() if r and r[0] is not None]
    finally:
        cur.close()


def run_fabric_schema_pipeline(
    fabric_profile: str,
    output: Path,
    *,
    schema: str = "BRONZE",
    database: str = "",
    hide_paths: bool = False,
    max_rows_per_table: int | None = None,
    max_tables: int = 0,
) -> Path:
    """
    Connect to Fabric SQL using ``credentials/fabric/<profile>.json``,
    list ``BASE TABLE`` in ``schema``, profile each with ``SELECT *`` (full table).

    ``max_rows_per_table``: if a positive integer, use ``SELECT TOP (n) *`` instead.

    ``max_tables`` 0 means no limit.

    ``database``: optional override / supplement when the profile JSON omits it
    (same value as Fabric **Initial Catalog** / SQL database name).

    Profiles each table in memory (no per-table Parquet round-trip) for faster runs.
    """
    from dq_tool.cli import _finalize_batch_workbook
    from dq_tool.excel_export import append_profile_to_batch, logical_table_name, redact_source_uri
    from dq_tool.profiler import profile_dataframe

    schema_clean = _safe_schema_name(schema)
    ok, loaded, msg = load_profile("fabric", fabric_profile.strip())
    if not ok:
        raise FileNotFoundError(msg)

    creds: dict[str, str] = {k: str(v) for k, v in loaded.items()}
    db_override = (database or "").strip()
    if db_override:
        creds["database"] = db_override

    ok_odbc, odbc_or_err = build_fabric_odbc_connection_string(creds)
    if not ok_odbc:
        hint = (
            ' Pass --fabric-database "YOUR_SQL_DATABASE_NAME" '
            '(Initial Catalog from Fabric), or add a "database" key to the profile JSON.'
        )
        raise ValueError(odbc_or_err + (hint if "database" in odbc_or_err.lower() else ""))

    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "Install pyodbc: pip install pyodbc (and ODBC Driver 18 for SQL Server)."
        ) from exc

    conn = pyodbc.connect(odbc_or_err, timeout=120)
    summaries: list[dict[str, object]] = []
    all_columns: list[dict[str, object]] = []
    all_dtypes: list[dict[str, object]] = []
    skipped_count = 0
    try:
        names = list_user_tables_in_schema(conn, schema_clean)
        if not names:
            raise FileNotFoundError(
                f"No BASE TABLE found in schema {schema_clean!r}. "
                "Check spelling (e.g. BRONZE) and permissions."
            )
        if max_tables and max_tables > 0:
            names = names[: int(max_tables)]

        sch = _sql_bracket_ident(schema_clean)
        row_cap: int | None = None
        if max_rows_per_table is not None and int(max_rows_per_table) > 0:
            row_cap = int(max_rows_per_table)

        success_count = 0
        for tname in names:
            tq = _sql_bracket_ident(tname)
            sql = (
                f"SELECT TOP ({row_cap}) * FROM {sch}.{tq}"
                if row_cap is not None
                else f"SELECT * FROM {sch}.{tq}"
            )
            try:
                df = pd.read_sql(sql, conn)
            except (ValueError, TypeError, OSError) as exc:
                skipped_count += 1
                print(f"Skipping {schema_clean}.{tname}: {exc}")
                continue

            success_count += 1
            label = f"fabric://{fabric_profile.strip()}/{schema_clean}/{tname}"
            canonical = label
            display_source = canonical if not hide_paths else redact_source_uri(canonical)
            table_name = logical_table_name(canonical) or logical_table_name(display_source)
            if not table_name:
                table_name = f"dataset_{success_count}"

            prof = profile_dataframe(df, source_path=label)
            append_profile_to_batch(
                prof,
                display_source=display_source,
                table_name=table_name,
                summaries=summaries,
                all_column_rows=all_columns,
                all_dtype_rows=all_dtypes,
            )

        if not summaries:
            raise RuntimeError("No tables could be read; check errors above.")

        _finalize_batch_workbook(
            summaries,
            all_columns,
            all_dtypes,
            output,
            hide_paths=hide_paths,
            skipped_count=skipped_count,
            report_context={
                "data_source_type": "Microsoft Fabric SQL",
                "cloud_provider": "fabric",
                "fabric_schema": schema_clean,
                "credential_profile": fabric_profile.strip(),
                "fabric_table_count": len(summaries),
                "fabric_max_rows_per_table": row_cap if row_cap is not None else "all",
            },
        )
    finally:
        conn.close()

    return output
