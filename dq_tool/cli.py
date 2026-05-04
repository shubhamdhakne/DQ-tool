"""CLI: profile a file and emit Excel report."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from dq_tool.excel_export import (
    append_profile_to_batch,
    logical_table_name,
    profile_to_excel,
    redact_source_uri,
    write_batch_workbook,
)
from dq_tool.profiler import profile_file
from dq_tool.report_paths import default_report_file

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


def _folder_diversity_count(source_labels: list[str]) -> int:
    """Count distinct parent folder paths (blob key parents or local file parents)."""
    folders: set[str] = set()
    for raw in source_labels:
        s = (raw or "").strip()
        key = s
        if s.startswith("s3://"):
            rest = s[5:]
            slash = rest.find("/")
            key = rest[slash + 1 :] if slash >= 0 else rest
        elif s.startswith("azure://"):
            rest = s[len("azure://") :]
            parts = rest.split("/", 2)
            key = parts[2] if len(parts) > 2 else rest
        try:
            parent = str(Path(key).parent)
        except (OSError, ValueError):
            parent = "(unknown)"
        folders.add(parent if parent not in ("", ".") else "(root)")
    return len(folders)


def _finalize_batch_workbook(
    summaries: list[dict[str, object]],
    all_columns: list[dict[str, object]],
    all_dtypes: list[dict[str, object]],
    output: Path,
    *,
    hide_paths: bool,
    skipped_count: int,
    report_context: dict[str, object] | None,
) -> Path:
    if not summaries:
        raise RuntimeError("No readable files found to profile.")

    if skipped_count:
        print(f"Files skipped: {skipped_count}")

    labels_for_folders = [str(s.get("source_path") or "") for s in summaries]
    total_fs = 0
    for s in summaries:
        b = s.get("file_size_bytes")
        try:
            if b is not None:
                total_fs += int(b)
        except (TypeError, ValueError):
            pass
    total_mem = 0
    for s in summaries:
        b = s.get("memory_usage_bytes")
        try:
            if b is not None:
                total_mem += int(b)
        except (TypeError, ValueError):
            pass

    rc: dict[str, object] = dict(report_context or {})
    rc.setdefault("data_source_type", "Local files / folders")
    rc["files_profiled_ok"] = len(summaries)
    rc["files_skipped"] = skipped_count
    rc["paths_hidden"] = hide_paths
    rc["distinct_folder_count"] = _folder_diversity_count(labels_for_folders)
    rc["total_file_size_bytes"] = total_fs
    rc["total_memory_usage_bytes"] = total_mem

    write_batch_workbook(
        summaries,
        all_columns,
        all_dtypes,
        output,
        rc,
    )
    return output


def _write_batch_report(
    files: list[Path],
    output: Path,
    hide_paths: bool,
    source_labels: list[str] | None = None,
    report_context: dict[str, object] | None = None,
) -> Path:
    summaries: list[dict[str, object]] = []
    all_columns: list[dict[str, object]] = []
    all_dtypes: list[dict[str, object]] = []
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
        raw_label = ""
        if source_labels is not None and idx < len(source_labels):
            raw_label = str(source_labels[idx]).strip()
        physical = str(file_path)
        canonical = raw_label if raw_label else physical

        if not hide_paths:
            display_source = canonical
        else:
            display_source = redact_source_uri(canonical)

        table_name = logical_table_name(canonical) or logical_table_name(display_source)
        if not table_name:
            table_name = f"dataset_{success_count}"

        append_profile_to_batch(
            prof,
            display_source=display_source,
            table_name=table_name,
            summaries=summaries,
            all_column_rows=all_columns,
            all_dtype_rows=all_dtypes,
        )

    return _finalize_batch_workbook(
        summaries,
        all_columns,
        all_dtypes,
        output,
        hide_paths=hide_paths,
        skipped_count=skipped_count,
        report_context=report_context,
    )


def _run_s3_pipeline(
    bucket: str,
    prefix: str,
    aws_profile: str,
    output: Path,
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
            hide_paths,
            source_labels=labels,
            report_context={
                "data_source_type": "AWS S3",
                "cloud_provider": "aws",
                "s3_bucket": bucket,
                "s3_prefix": prefix or "(none)",
                "credential_profile": aws_profile,
                "s3_object_count": len(keys),
            },
        )
    finally:
        for p in temp_paths:
            p.unlink(missing_ok=True)

    return output


def _run_s3_all_buckets_pipeline(
    prefix: str,
    aws_profile: str,
    output: Path,
    hide_paths: bool,
    max_objects: int | None,
) -> Path:
    """List every bucket in the account, collect supported keys (optional prefix), profile into one workbook."""
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
    resp = client.list_buckets()
    bucket_names = sorted(b["Name"] for b in (resp.get("Buckets") or []))
    if not bucket_names:
        raise FileNotFoundError("list_buckets returned no buckets (check IAM: s3:ListAllMyBuckets).")

    work: list[tuple[str, str]] = []
    for bname in bucket_names:
        try:
            keys = list_supported_s3_keys(client, bname, prefix)
        except Exception as exc:  # noqa: BLE001 — skip buckets we cannot list
            print(f"Skipping bucket (cannot list keys): {bname} ({exc})")
            continue
        for k in keys:
            work.append((bname, k))
            if max_objects is not None and len(work) >= max_objects:
                break
        if max_objects is not None and len(work) >= max_objects:
            break

    if not work:
        raise FileNotFoundError(
            f"No supported objects (.csv, .parquet, …) in any bucket with prefix {prefix!r}. "
            "Narrow or set --s3-prefix, or raise --s3-max-objects if you hit the cap."
        )

    cap_note = f" (stopped at {max_objects} objects)" if max_objects is not None and len(work) >= max_objects else ""
    print(
        f"S3 all-buckets: {len(bucket_names)} bucket(s) visible; "
        f"profiling {len(work)} object(s){cap_note}."
    )

    temp_paths: list[Path] = []
    labels = [f"s3://{bn}/{key}" for bn, key in work]
    try:
        for bn, key in work:
            temp_paths.append(download_s3_object_to_temp(client, bn, key))
        _write_batch_report(
            temp_paths,
            output,
            hide_paths,
            source_labels=labels,
            report_context={
                "data_source_type": "AWS S3 (all buckets)",
                "cloud_provider": "aws",
                "s3_bucket": "(all buckets)",
                "s3_prefix": prefix or "(none)",
                "s3_bucket_count_visible": len(bucket_names),
                "s3_object_count": len(work),
                "s3_max_objects_cap": str(max_objects) if max_objects is not None else "none",
                "credential_profile": aws_profile,
            },
        )
    finally:
        for p in temp_paths:
            p.unlink(missing_ok=True)

    return output


def _azure_list_containers(azure_profile: str) -> None:
    """Print blob container names for the given Azure profile (helps pick --azure-container)."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise RuntimeError("Install Azure SDK: pip install azure-storage-blob") from exc

    from dq_tool.azure_batch import list_container_names
    from dq_tool.connections import load_profile

    ok, creds, msg = load_profile("azure", azure_profile)
    if not ok:
        raise RuntimeError(msg)
    conn = (creds.get("connection_string") or "").strip()
    if not conn:
        raise RuntimeError("Azure connection_string missing in profile.")

    service = BlobServiceClient.from_connection_string(conn)
    names = list_container_names(service)
    acct = service.account_name or "?"
    print(f"Storage account: {acct}")
    print("Blob containers:")
    if not names:
        print("  (none)")
    else:
        for n in names:
            print(f"  - {n}")
    print()
    print("Use one container name with:")
    print(f"  python -m dq_tool --azure-container <NAME> --azure-profile {azure_profile} ...")


def _run_azure_pipeline(
    container: str,
    blob_prefix: str,
    azure_profile: str,
    output: Path,
    hide_paths: bool,
) -> Path:
    """Download Azure blobs only to OS temp, profile, write Excel, delete temps."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise RuntimeError("Install Azure SDK: pip install azure-storage-blob") from exc

    from dq_tool.azure_batch import download_blob_to_temp, list_supported_blob_names
    from dq_tool.connections import load_profile

    ok, creds, msg = load_profile("azure", azure_profile)
    if not ok:
        raise RuntimeError(msg)

    conn = (creds.get("connection_string") or "").strip()
    if not conn:
        raise RuntimeError("Azure connection_string missing in profile.")

    service = BlobServiceClient.from_connection_string(conn)
    container = container.strip()
    cc = service.get_container_client(container)
    account_name = service.account_name or "your-account"
    if not cc.exists():
        raise FileNotFoundError(
            f"Blob container not found: '{container}'. "
            f"This must be a container inside storage account '{account_name}', "
            f"not the account name itself (you used the account name if container matches AccountName in the portal). "
            f"List valid container names: python -m dq_tool --azure-list-containers --azure-profile {azure_profile}"
        )
    names = list_supported_blob_names(cc, blob_prefix.strip())
    if not names:
        raise FileNotFoundError(
            f"No supported blobs in container '{container}' with prefix '{blob_prefix or '(none)'}'"
        )

    account_label = service.account_name or "account"
    temp_paths: list[Path] = []
    labels = [f"azure://{account_label}/{container}/{n}" for n in names]
    try:
        for name in names:
            bc = cc.get_blob_client(name)
            temp_paths.append(download_blob_to_temp(bc, name))
        _write_batch_report(
            temp_paths,
            output,
            hide_paths,
            source_labels=labels,
            report_context={
                "data_source_type": "Azure Blob Storage",
                "cloud_provider": "azure",
                "storage_account": account_label,
                "blob_container": container,
                "blob_prefix": blob_prefix.strip() or "(none)",
                "credential_profile": azure_profile,
                "blob_object_count": len(names),
            },
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
        help="File/folder paths (CSV, JSON, Parquet, Excel, etc.). Omit when using cloud options.",
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
        help="Optional key prefix inside the bucket (e.g. data/incoming/). With --s3-all-buckets, applied in every bucket.",
    )
    parser.add_argument(
        "--s3-all-buckets",
        action="store_true",
        help="Profile supported objects across all S3 buckets in the account (needs s3:ListAllMyBuckets). Use --s3-prefix to limit keys. Mutually exclusive with --s3-bucket.",
    )
    parser.add_argument(
        "--s3-max-objects",
        type=int,
        default=2000,
        metavar="N",
        help="With --s3-all-buckets: stop after N objects total (default 2000). Use 0 for no limit (can be slow/costly).",
    )
    parser.add_argument(
        "--aws-profile",
        default="default",
        metavar="PROFILE",
        help="AWS credential profile name (JSON under credentials/aws/<PROFILE>.json).",
    )
    parser.add_argument(
        "--azure-container",
        default="",
        metavar="NAME",
        help="Azure Blob *container* name (not the storage account name). List names: --azure-list-containers.",
    )
    parser.add_argument(
        "--azure-blob-prefix",
        default="",
        metavar="PREFIX",
        help="Optional blob name prefix inside the container (e.g. incoming/).",
    )
    parser.add_argument(
        "--azure-profile",
        default="default",
        metavar="PROFILE",
        help="Azure credential profile name (JSON under credentials/azure/<PROFILE>.json).",
    )
    parser.add_argument(
        "--azure-list-containers",
        action="store_true",
        help="List blob container names for this profile, then exit (use to pick --azure-container).",
    )
    parser.add_argument(
        "--fabric-profile",
        default="",
        metavar="PROFILE",
        help="Microsoft Fabric SQL: credential JSON under credentials/fabric/<PROFILE>.json; profiles all BASE TABLE in --fabric-schema.",
    )
    parser.add_argument(
        "--fabric-schema",
        default="BRONZE",
        metavar="NAME",
        help="SQL schema to scan (default BRONZE). Only letters, digits, underscore.",
    )
    parser.add_argument(
        "--fabric-database",
        default="",
        metavar="NAME",
        help="Fabric SQL database / Initial Catalog when not set (or incomplete) in the profile JSON.",
    )
    parser.add_argument(
        "--fabric-max-rows",
        type=int,
        default=50_000,
        metavar="N",
        help="Max rows per table via SELECT TOP (default 50000).",
    )
    parser.add_argument(
        "--fabric-max-tables",
        type=int,
        default=0,
        metavar="N",
        help="Max tables to profile (default 0 = all tables in schema).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="",
        help="Output .xlsx path (default: under repo report/ with UTC timestamp in the filename so runs do not overwrite)",
    )
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

    if args.azure_list_containers:
        if (
            args.input
            or args.s3_bucket
            or args.s3_all_buckets
            or args.azure_container
            or args.open_dashboard
            or args.fabric_profile
        ):
            parser.error(
                "--azure-list-containers: use only with --azure-profile (no paths, --open-dashboard, or other cloud flags)."
            )
        _azure_list_containers(args.azure_profile.strip())
        return

    fabric_on = bool(args.fabric_profile and args.fabric_profile.strip())
    cloud_modes = (
        (1 if args.s3_bucket else 0)
        + (1 if args.azure_container else 0)
        + (1 if args.s3_all_buckets else 0)
        + (1 if fabric_on else 0)
    )
    if cloud_modes > 1:
        parser.error(
            "Use only one of --s3-bucket, --s3-all-buckets, --azure-container, or --fabric-profile."
        )

    if args.s3_all_buckets:
        if args.input:
            parser.error("Do not pass local paths together with --s3-all-buckets.")
        max_obs = None if args.s3_max_objects == 0 else int(args.s3_max_objects)
        out = Path(args.output) if args.output else default_report_file("s3_all_buckets_dq_batch_report.xlsx")
        _run_s3_all_buckets_pipeline(
            args.s3_prefix.strip(),
            args.aws_profile.strip(),
            out,
            hide_paths=args.hide_paths,
            max_objects=max_obs,
        )
        print(f"S3 all-buckets report written: {out.resolve()}")
    elif args.s3_bucket:
        if args.input:
            parser.error("Do not pass local paths together with --s3-bucket.")
        out = Path(args.output) if args.output else default_report_file("s3_dq_batch_report.xlsx")
        _run_s3_pipeline(
            args.s3_bucket.strip(),
            args.s3_prefix.strip(),
            args.aws_profile.strip(),
            out,
            hide_paths=args.hide_paths,
        )
        print(f"S3 batch report written: {out.resolve()}")
    elif args.azure_container:
        if args.input:
            parser.error("Do not pass local paths together with --azure-container.")
        out = Path(args.output) if args.output else default_report_file("azure_dq_batch_report.xlsx")
        _run_azure_pipeline(
            args.azure_container.strip(),
            args.azure_blob_prefix.strip(),
            args.azure_profile.strip(),
            out,
            hide_paths=args.hide_paths,
        )
        print(f"Azure batch report written: {out.resolve()}")
    elif fabric_on:
        if args.input:
            parser.error("Do not pass local paths together with --fabric-profile.")
        from dq_tool.fabric_pipeline import run_fabric_schema_pipeline

        schema_slug = "".join(
            ch if ch.isalnum() else "_" for ch in args.fabric_schema.strip().lower()
        ).strip("_")[:48] or "schema"
        out = (
            Path(args.output)
            if args.output
            else default_report_file(f"fabric_{schema_slug}_dq_batch_report.xlsx")
        )
        run_fabric_schema_pipeline(
            args.fabric_profile.strip(),
            out,
            schema=args.fabric_schema.strip(),
            database=args.fabric_database.strip(),
            hide_paths=args.hide_paths,
            max_rows_per_table=int(args.fabric_max_rows),
            max_tables=int(args.fabric_max_tables),
        )
        print(f"Fabric SQL batch report written: {out.resolve()}")
    elif args.input:
        files = _collect_input_files(args.input, recursive=True)
        if not files:
            raise FileNotFoundError("No supported input files found.")

        if len(files) == 1:
            inp = files[0]
            out = Path(args.output) if args.output else default_report_file(f"{inp.stem}_dq_report.xlsx")
            df, prof = profile_file(inp)
            canonical = str(inp.resolve())
            if args.hide_paths:
                prof.source_path = ""
            rctx: dict[str, object] = {
                "data_source_type": "Local file",
                "paths_hidden": args.hide_paths,
            }
            if not args.hide_paths:
                rctx["input_path"] = canonical
            profile_to_excel(
                prof,
                out,
                report_context=rctx,
                display_source_override=redact_source_uri(canonical) if args.hide_paths else None,
                canonical_source_for_table_name=canonical,
            )
            print(f"Report written: {out.resolve()}")
        else:
            out = Path(args.output) if args.output else default_report_file("dq_batch_report.xlsx")
            _write_batch_report(
                files,
                out,
                hide_paths=args.hide_paths,
                report_context={"data_source_type": "Local files / folders"},
            )
            print(f"Batch report written: {out.resolve()}")
            print(f"Total files profiled: {len(files)}")
    else:
        parser.error(
            "Provide file/folder paths, --s3-bucket, --s3-all-buckets, --azure-container, or --fabric-profile."
        )

    if args.open_dashboard:
        dashboard_app = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        env = os.environ.copy()
        env["DQ_AUTO_REPORT_PATH"] = str(out.resolve())
        env["DQ_HIDE_PATHS"] = "1" if args.hide_paths else "0"
        hint: dict[str, object] = {"report_path": str(out.resolve())}
        if args.s3_bucket:
            hint.update(
                {
                    "cloud": "AWS S3",
                    "bucket": args.s3_bucket.strip(),
                    "prefix": args.s3_prefix.strip(),
                    "profile": args.aws_profile.strip(),
                }
            )
        elif args.s3_all_buckets:
            hint.update(
                {
                    "cloud": "AWS S3 (all buckets)",
                    "prefix": args.s3_prefix.strip(),
                    "profile": args.aws_profile.strip(),
                }
            )
        elif args.azure_container:
            hint.update(
                {
                    "cloud": "Azure Blob",
                    "container": args.azure_container.strip(),
                    "prefix": args.azure_blob_prefix.strip(),
                    "profile": args.azure_profile.strip(),
                }
            )
        elif fabric_on:
            hint.update(
                {
                    "cloud": "Microsoft Fabric SQL",
                    "fabric_profile": args.fabric_profile.strip(),
                    "fabric_schema": args.fabric_schema.strip(),
                    "fabric_database": (args.fabric_database or "").strip(),
                }
            )
        else:
            hint["cloud"] = "Local"
        env["DQ_CLOUD_SUMMARY_JSON"] = json.dumps(hint)
        print("Opening dashboard with generated report...")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dashboard_app)],
            check=True,
            env=env,
        )


if __name__ == "__main__":
    main()
