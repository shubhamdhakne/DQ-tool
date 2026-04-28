"""CLI: profile a file and emit Excel report."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from dq_tool.excel_export import profile_to_excel
from dq_tool.profiler import profile_file

SUPPORTED_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".pq",
    ".json",
    ".jsonl",
    ".ndjson",
    ".xlsx",
    ".xls",
    ".feather",
    ".orc",
}


def _is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _collect_input_files(inputs: list[str], recursive: bool = True) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_file():
            if _is_supported_file(p):
                files.append(p.resolve())
            else:
                print(f"Skipping unsupported file: {p}")
            continue
        if p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            matched = [f.resolve() for f in iterator if _is_supported_file(f)]
            if not matched:
                print(f"No supported files found in directory: {p}")
            files.extend(matched)
            continue
        print(f"Path not found, skipping: {p}")

    # unique + stable order
    seen: set[str] = set()
    unique_files: list[Path] = []
    for f in files:
        key = str(f).lower()
        if key not in seen:
            seen.add(key)
            unique_files.append(f)
    return unique_files


def _write_batch_report(
    files: list[Path],
    output: Path,
    sample_rows: int,
    hide_paths: bool,
    source_labels: list[str] | None = None,
) -> Path:
    summaries: list[dict[str, object]] = []
    all_columns: list[dict[str, object]] = []
    all_dtypes: list[dict[str, object]] = []
    all_samples: list[pd.DataFrame] = []
    success_count = 0
    skipped_count = 0

    for idx, file_path in enumerate(files):
        try:
            df, prof = profile_file(file_path)
        except (OSError, ValueError, TypeError) as exc:
            skipped_count += 1
            print(f"Skipping unreadable file: {file_path} ({exc})")
            continue

        success_count += 1
        display_source = ""
        if not hide_paths:
            if source_labels is not None and idx < len(source_labels):
                display_source = source_labels[idx]
            else:
                display_source = str(file_path)

        summary = prof.summary_dict()
        summary["source_path"] = display_source
        summaries.append(summary)

        for col in prof.columns:
            row = col.as_dict()
            row["source_path"] = display_source
            all_columns.append(row)

        dtype_counts = json.loads(prof.dtypes_json)
        for dtype, count in dtype_counts.items():
            all_dtypes.append(
                {
                    "source_path": display_source,
                    "dtype": dtype,
                    "count": int(count),
                }
            )

        if sample_rows > 0:
            sample = df.head(sample_rows).copy()
            source_value = display_source
            sample_source_col = "__dq_source_path"
            if sample_source_col in sample.columns:
                sample_source_col = "__dq_source_file"
            sample.insert(0, sample_source_col, source_value)
            all_samples.append(sample)

    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(summaries).to_excel(writer, sheet_name="Files_Overview", index=False)
        pd.DataFrame(all_columns).to_excel(writer, sheet_name="All_Column_Details", index=False)
        pd.DataFrame(all_dtypes).to_excel(writer, sheet_name="All_Dtype_Summary", index=False)
        if all_samples:
            pd.concat(all_samples, ignore_index=True).to_excel(writer, sheet_name="Sample_Data", index=False)

    if success_count == 0:
        raise RuntimeError("No readable files found to profile.")

    if skipped_count:
        print(f"Files skipped: {skipped_count}")

    return output


def _run_s3_pipeline(
    bucket: str,
    prefix: str,
    aws_profile: str,
    output: Path,
    sample_rows: int,
    hide_paths: bool,
) -> Path:
    """Download S3 objects only to OS temp, profile, write Excel, delete temps."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("Install AWS SDK: pip install boto3") from exc

    from dq_tool.connections import load_profile
    from dq_tool.s3_batch import download_s3_object_to_temp, list_supported_s3_keys

    ok, creds, msg = load_profile("aws", aws_profile)
    if not ok:
        raise RuntimeError(msg)

    session = boto3.session.Session(
        aws_access_key_id=creds.get("access_key_id") or None,
        aws_secret_access_key=creds.get("secret_access_key") or None,
        aws_session_token=creds.get("session_token") or None,
        region_name=creds.get("region") or None,
    )
    client = session.client("s3")
    keys = list_supported_s3_keys(client, bucket, prefix)
    if not keys:
        raise FileNotFoundError(f"No supported objects under s3://{bucket}/{prefix}")

    temp_paths: list[Path] = []
    labels = [f"s3://{bucket}/{k}" for k in keys]
    try:
        for key in keys:
            temp_paths.append(download_s3_object_to_temp(client, bucket, key))
        _write_batch_report(
            temp_paths,
            output,
            sample_rows,
            hide_paths,
            source_labels=labels,
        )
    finally:
        for p in temp_paths:
            p.unlink(missing_ok=True)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Data quality profile to Excel")
    parser.add_argument(
        "input",
        nargs="*",
        default=[],
        type=str,
        help="File/folder paths (CSV, JSON, Parquet, Excel, etc.). Omit when using --s3-bucket.",
    )
    parser.add_argument(
        "--s3-bucket",
        default="",
        metavar="NAME",
        help="S3 bucket: list supported objects, download to temp only, profile, no copy under project.",
    )
    parser.add_argument(
        "--s3-prefix",
        default="",
        metavar="PREFIX",
        help="Optional key prefix inside the bucket (e.g. data/incoming/).",
    )
    parser.add_argument(
        "--aws-profile",
        default="default",
        metavar="PROFILE",
        help="AWS credential profile name (JSON under credentials/aws/<PROFILE>.json).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="",
        help="Output .xlsx path (default: single=<input_stem>_dq_report.xlsx, multi=dq_batch_report.xlsx)",
    )
    parser.add_argument("--sample-rows", type=int, default=10, help="Rows in Sample_Data sheet")
    parser.add_argument(
        "--open-dashboard",
        action="store_true",
        help="After report generation, launch Streamlit dashboard and auto-load this report.",
    )
    parser.add_argument(
        "--hide-paths",
        action="store_true",
        help="Do not include source file paths in generated report sheets.",
    )
    args = parser.parse_args()

    if args.s3_bucket:
        if args.input:
            parser.error("Do not pass local paths together with --s3-bucket.")
        out = Path(args.output) if args.output else Path.cwd() / "s3_dq_batch_report.xlsx"
        _run_s3_pipeline(
            args.s3_bucket.strip(),
            args.s3_prefix.strip(),
            args.aws_profile.strip(),
            out,
            sample_rows=args.sample_rows,
            hide_paths=args.hide_paths,
        )
        print(f"S3 batch report written: {out.resolve()}")
    elif args.input:
        files = _collect_input_files(args.input, recursive=True)
        if not files:
            raise FileNotFoundError("No supported input files found.")

        if len(files) == 1:
            inp = files[0]
            out = Path(args.output) if args.output else inp.with_name(f"{inp.stem}_dq_report.xlsx")
            df, prof = profile_file(inp)
            if args.hide_paths:
                prof.source_path = ""
            profile_to_excel(prof, df, out, sample_rows=args.sample_rows)
            print(f"Report written: {out.resolve()}")
        else:
            out = Path(args.output) if args.output else Path.cwd() / "dq_batch_report.xlsx"
            _write_batch_report(files, out, sample_rows=args.sample_rows, hide_paths=args.hide_paths)
            print(f"Batch report written: {out.resolve()}")
            print(f"Total files profiled: {len(files)}")
    else:
        parser.error("Provide file/folder paths or --s3-bucket.")

    if args.open_dashboard:
        dashboard_app = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        env = os.environ.copy()
        env["DQ_AUTO_REPORT_PATH"] = str(out.resolve())
        env["DQ_HIDE_PATHS"] = "1" if args.hide_paths else "0"
        print("Opening dashboard with generated report...")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dashboard_app)],
            check=True,
            env=env,
        )


if __name__ == "__main__":
    main()
