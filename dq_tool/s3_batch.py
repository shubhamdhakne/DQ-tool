"""S3: list supported objects and download to system temp only (no project copy)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

SUPPORTED_SUFFIXES = {
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


def list_supported_s3_keys(client, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix or ""):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if key.endswith("/"):
                continue
            suf = Path(key).suffix.lower()
            if suf in SUPPORTED_SUFFIXES:
                keys.append(key)
    return sorted(keys)


def download_s3_object_to_temp(client, bucket: str, key: str) -> Path:
    suffix = Path(key).suffix.lower() or ".bin"
    fd, path = tempfile.mkstemp(prefix="dq_s3_", suffix=suffix)
    os.close(fd)
    try:
        client.download_file(bucket, key, path)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return Path(path)
