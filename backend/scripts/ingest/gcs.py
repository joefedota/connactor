from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage

_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_bucket() -> storage.Bucket:
    return _get_client().bucket(os.environ["GCS_BUCKET"])


def download_to_file(blob_name: str, local_path: Path) -> bool:
    """Download blob to local_path. Returns False if blob doesn't exist."""
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        return False
    size_mb = (blob.size or 0) / 1024 / 1024
    print(f"  [GCS] Downloading {blob_name} ({size_mb:.1f} MB) ...")
    blob.download_to_filename(str(local_path), timeout=600)
    return True


def upload_from_file(local_path: Path, blob_name: str) -> None:
    size = local_path.stat().st_size
    size_mb = size / 1024 / 1024
    print(f"  [GCS] Uploading {blob_name} ({size_mb:.1f} MB) ...")
    blob = get_bucket().blob(blob_name)
    # Resumable upload: sends in 8 MB chunks, survives connection drops.
    chunk_size = 8 * 1024 * 1024
    blob.chunk_size = chunk_size
    with open(local_path, "rb") as f:
        blob.upload_from_file(f, timeout=600)
    print(f"  [GCS] Upload complete: {blob_name}")


def blob_exists(blob_name: str) -> bool:
    return get_bucket().blob(blob_name).exists()
