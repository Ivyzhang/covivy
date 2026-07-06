from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def store_upload(storage_root: str, repository_id: int, commit_sha: str, filename: str, data: bytes) -> str:
    safe_name = Path(filename or "coverage").name
    upload_id = "up_" + uuid4().hex
    directory = Path(storage_root) / "uploads" / str(repository_id) / commit_sha
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%s_%s" % (upload_id, safe_name))
    path.write_bytes(data)
    return str(path)

