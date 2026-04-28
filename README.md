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

## Web dashboard

```bash
streamlit run dashboard/app.py
```

Upload CSV / Excel / Parquet / JSON or enter a **local file path**. Download the multi-sheet Excel report from the page.

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
- `dashboard/app.py` — Streamlit UI  

