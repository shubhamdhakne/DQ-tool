"""Azure Blob: list supported blobs and download to system temp only (no project copy)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING

from dq_tool.s3_batch import SUPPORTED_SUFFIXES

if TYPE_CHECKING:
    from azure.storage.blob import BlobServiceClient


def list_container_names(service: "BlobServiceClient") -> list[str]:
    """Return blob container names in the storage account."""
    return sorted(c.name for c in service.list_containers())


def list_supported_blob_names(container_client, name_prefix: str) -> list[str]:
    names: list[str] = []
    prefix = name_prefix or ""
    for blob in container_client.list_blobs(name_starts_with=prefix):
        name = blob.name
        if name.endswith("/"):
            continue
        suf = Path(name).suffix.lower()
        if suf in SUPPORTED_SUFFIXES:
            names.append(name)
    return sorted(names)


def download_blob_to_temp(blob_client, blob_name: str) -> Path:
    suffix = Path(blob_name).suffix.lower() or ".bin"
    fd, path = tempfile.mkstemp(prefix="dq_az_", suffix=suffix)
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            downloader = blob_client.download_blob()
            for chunk in downloader.chunks():
                fh.write(chunk)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return Path(path)
