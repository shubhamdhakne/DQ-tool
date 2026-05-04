# DQ-tool

Pandas-first data quality profiling with **Excel reports** and a **Streamlit** web dashboard. Optional **PySpark** profiler for large data.

## Metrics

- Row count, column count, total cells  
- Null counts per column and overall null %  
- Data types (pandas dtypes or Spark types)  
- Min / max (numeric, datetime, boolean, string)  
- Unique counts per column  
- In-memory size (pandas deep estimate); file size and file type when loading from disk  

## Setup

```bash
cd "c:\project\DQ tool\DQ-tool"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## CLI → Excel

```bash
python -m dq_tool path\to\data.csv -o report.xlsx
```

If you omit `-o`, reports are written under the repo’s **`report/`** folder (created automatically), e.g. `report/<input_stem>_dq_report.xlsx`.

### Multiple files (mixed CSV/JSON/Parquet)

```bash
python -m dq_tool data1.csv data2.csv logs.json events.parquet -o dq_batch_report.xlsx
```

You can also pass folders; supported files inside are auto-detected recursively.
Use `--hide-paths` to avoid showing source file paths in output sheets.

### Single command: generate + open dashboard

```bash
python -m dq_tool path\to\data.csv --open-dashboard
```

This generates the Excel report and launches Streamlit with the report auto-loaded.

For multiple files:

```bash
python -m dq_tool folder_csv folder_json folder_parquet --open-dashboard
```

This creates a combined `report/dq_batch_report.xlsx` (default) and opens it directly in dashboard.

Privacy mode example:

```bash
python -m dq_tool file1.csv file2.csv a.json b.json c.parquet --hide-paths --open-dashboard
```

## Web dashboard

```bash
python -m streamlit run dashboard/app.py
```

Upload CSV / Excel / Parquet / JSON or enter a **local file path**. Download the multi-sheet Excel report from the page.

### Cloud connections (AWS / Azure / Snowflake / Fabric SQL)

The dashboard sidebar now includes a **Cloud connections** panel where you can:

- Choose provider: AWS, Azure Blob, Snowflake, or **Microsoft Fabric** (SQL endpoint / warehouse)
- Enter credentials and **Save profile**
- **Load profile** later from saved profile files
- **Test connection** before using it in pipelines
- Edit credential JSON files directly when needed

Install optional cloud SDKs:

```bash
pip install -r requirements-cloud.txt
```

Credential storage behavior:

- Stored in project folder: `credentials/<cloud>/<profile>.json`
- Separate folders per cloud (`aws`, `azure`, `snowflake`, `fabric`)
- Profiles are editable for adding/updating other accounts

**AWS and Azure use the same pattern** (only JSON field names differ):

| Cloud    | Folder              | Example file              | Fields |
|----------|---------------------|---------------------------|--------|
| AWS      | `credentials/aws/`  | `credentials/aws/default.json` | `access_key_id`, `secret_access_key`, `region`, `session_token` (optional) |
| Azure    | `credentials/azure/` | `credentials/azure/default.json` | `connection_string` |
| Fabric (SQL) | `credentials/fabric/` | `credentials/fabric/default.json` | `authentication`, `sql_connection_string` — see `credentials/fabric/README.md` |

All secret profiles live only under **`credentials/`** (JSON is gitignored). Use the dashboard **Save profile** or create files next to each cloud’s `README.md` there.

**Fabric SQL** needs [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) (or 17) on the machine, plus `pip install pyodbc` (included in `requirements-cloud.txt`). Paste the full SQL connection string from Fabric into `sql_connection_string`. See `credentials/fabric/README.md`.

Or use the dashboard **Save profile** — it writes to the same paths as AWS.

### Microsoft Fabric SQL (all tables in a schema, e.g. BRONZE)

Uses `credentials/fabric/<profile>.json` (same fields as the dashboard). Profiles each **base table** in the schema with `SELECT TOP (n) *` (default 50k rows per table), writes one batch Excel under `report/`, optional dashboard.

```bash
pip install -r requirements-cloud.txt
python -m dq_tool --fabric-profile fabric --fabric-database YOUR_SQL_DATABASE_NAME --fabric-schema BRONZE --hide-paths --open-dashboard
```

`YOUR_SQL_DATABASE_NAME` is the **Initial Catalog** from Fabric (same as a `"database"` field in the profile JSON). Omit `--fabric-schema` to keep the default **`BRONZE`**. Use `--fabric-max-tables 10` for a quick subset.

### AWS S3 pipeline (no copy under project)

Objects are downloaded only to the **system temp** folder while profiling, then removed. Output is the Excel report (and optional dashboard).

```bash
pip install -r requirements-cloud.txt
python -m dq_tool --s3-bucket YOUR_BUCKET --s3-prefix optional/prefix/ --aws-profile default -o s3_dq_report.xlsx --hide-paths --open-dashboard
```

**All buckets in the account** (same optional prefix applied in each bucket; needs `s3:ListAllMyBuckets` and list/read per bucket):

```bash
python -m dq_tool --s3-all-buckets --s3-prefix data/incoming/ --aws-profile default
```

- **`--s3-max-objects`** — cap total objects across all buckets (default **2000**). Use **`0`** for no limit (can be slow or hit API limits on huge accounts).
- Default report if `-o` omitted: `report/s3_all_buckets_dq_batch_report.xlsx`

- `--aws-profile` reads `credentials/aws/<PROFILE>.json`
- Single-bucket default if `-o` omitted: `report/s3_dq_batch_report.xlsx` (under the repo root)

### Azure Blob pipeline (profile e.g. `azure_account_2`)

Uses `credentials/azure/<PROFILE>.json` (`connection_string`). Blobs are downloaded only to **system temp**, then removed — same idea as S3.

```bash
pip install -r requirements-cloud.txt
# Container name is NOT the storage account name — list containers first:
python -m dq_tool --azure-list-containers --azure-profile azure_account_2
python -m dq_tool --azure-container YOUR_CONTAINER --azure-profile azure_account_2 --azure-blob-prefix optional/prefix/ -o azure_dq_report.xlsx --hide-paths --open-dashboard
```

- **`--azure-profile`** — file name without `.json` under `credentials/azure/` (e.g. `azure_account_2` → `azure_account_2.json`)
- **Dashboard:** Cloud connections → Azure → **Saved profiles** → `azure_account_2` → **Load profile** → **Test connection** (checks storage only; DQ run is via CLI above)

Default report if `-o` omitted: `report/azure_dq_batch_report.xlsx` (under the repo root).

### Excel sheets

- **Overview** — dataset summary  
- **Column_Details** — per-column metrics  
- **Dtype_Summary** — count of columns per dtype  
- **Sample_Data** — first N rows per source. Single-file reports use a **wide** table. **Batch** (multi-file / S3 / Azure) uses a **long tidy** layout: `table_name`, `source_path`, `sample_row`, `column_name`, `cell_value`, so different column sets do not produce one sparse, misaligned sheet.  

## PySpark (optional)

```bash
pip install pyspark
python -m dq_tool.spark_profiler path\to\folder_or_file.parquet -o spark_report.xlsx
```

If you omit `-o`, output defaults to `report/spark_dq_report.xlsx`. Uses Spark aggregations (multiple passes); sample rows in the report are limited for cost control.

## Package layout

- `dq_tool/profiler.py` — load + pandas profile  
- `dq_tool/report_paths.py` — default `report/` output directory under repo root  
- `dq_tool/excel_export.py` — Excel writer  
- `dq_tool/spark_profiler.py` — PySpark profile + Excel  
- `dq_tool/connections.py` — credential storage + cloud connection tests  
- `dq_tool/s3_batch.py` — S3 list + temp download (no project copy)  
- `dq_tool/azure_batch.py` — Azure Blob list + temp download (no project copy)  
- `dashboard/app.py` — Streamlit UI  

