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

Default output: `<input_stem>_dq_report.xlsx` next to the input file.

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

This creates a combined `dq_batch_report.xlsx` and opens it directly in dashboard.

Privacy mode example:

```bash
python -m dq_tool file1.csv file2.csv a.json b.json c.parquet --hide-paths --open-dashboard
```

## Web dashboard

```bash
python -m streamlit run dashboard/app.py
```

Upload CSV / Excel / Parquet / JSON or enter a **local file path**. Download the multi-sheet Excel report from the page.

### Cloud connections (AWS / Azure / Snowflake)

The dashboard sidebar now includes a **Cloud connections** panel where you can:

- Choose provider: AWS, Azure Blob, or Snowflake
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
- Separate folders per cloud (`aws`, `azure`, `snowflake`)
- Profiles are editable for adding/updating other accounts

### AWS S3 pipeline (no copy under project)

Objects are downloaded only to the **system temp** folder while profiling, then removed. Output is the Excel report (and optional dashboard).

```bash
pip install -r requirements-cloud.txt
python -m dq_tool --s3-bucket YOUR_BUCKET --s3-prefix optional/prefix/ --aws-profile default -o s3_dq_report.xlsx --hide-paths --open-dashboard
```

- `--aws-profile` reads `credentials/aws/<PROFILE>.json`
- Default report path if `-o` omitted: `s3_dq_batch_report.xlsx` in the current directory

### Excel sheets

- **Overview** — dataset summary  
- **Column_Details** — per-column metrics  
- **Dtype_Summary** — count of columns per dtype  
- **Sample_Data** — first N rows  

## PySpark (optional)

```bash
pip install pyspark
python -m dq_tool.spark_profiler path\to\folder_or_file.parquet -o spark_report.xlsx
```

Uses Spark aggregations (multiple passes); sample rows in the report are limited for cost control.

## Package layout

- `dq_tool/profiler.py` — load + pandas profile  
- `dq_tool/excel_export.py` — Excel writer  
- `dq_tool/spark_profiler.py` — PySpark profile + Excel  
- `dq_tool/connections.py` — credential storage + cloud connection tests  
- `dq_tool/s3_batch.py` — S3 list + temp download (no project copy)  
- `dashboard/app.py` — Streamlit UI  

