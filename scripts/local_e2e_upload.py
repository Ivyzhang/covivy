from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_multipart(
    fields: Dict[str, str],
    filename: str,
    file_bytes: bytes,
    boundary: Optional[str] = None,
) -> Tuple[bytes, str]:
    boundary = boundary or "covivy-%s" % uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                "--%s\r\n" % boundary,
                'Content-Disposition: form-data; name="%s"\r\n\r\n' % name,
                str(value),
                "\r\n",
            ]
        )
    chunks.extend(
        [
            "--%s\r\n" % boundary,
            'Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename,
            "Content-Type: text/plain\r\n\r\n",
        ]
    )
    body = b"".join(
        item if isinstance(item, bytes) else item.encode("utf-8") for item in chunks
    )
    body += file_bytes
    body += ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    return body, "multipart/form-data; boundary=%s" % boundary


def request_json(method: str, url: str, headers: Dict[str, str], body: Optional[bytes] = None):
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local coverage upload smoke test against a running covivy API."
    )
    parser.add_argument("--base-url", default=os.getenv("COVERAGE_SERVICE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--repository", required=True, help="owner/repo")
    parser.add_argument("--commit-sha", required=True, help="PR head SHA or commit SHA")
    parser.add_argument("--branch", default="local")
    parser.add_argument("--parent-sha", default="")
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--admin-token", default=os.getenv("ADMIN_TOKEN", ""))
    parser.add_argument("--coverage-file", default="")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()

    if not args.admin_token:
        print("ADMIN_TOKEN is required via --admin-token or environment", file=sys.stderr)
        return 2

    base_url = normalize_base_url(args.base_url)
    try:
        health = request_json("GET", "%s/healthz" % base_url, {})
        if health != {"status": "ok"}:
            print("unexpected health response: %r" % health, file=sys.stderr)
            return 1

        owner, repo = args.repository.split("/", 1)
        token_response = request_json(
            "POST",
            "%s/api/v1/repos/%s/%s/upload-token" % (base_url, owner, repo),
            {"Authorization": "Bearer %s" % args.admin_token},
        )
        upload_token = token_response["upload_token"]

        if args.coverage_file:
            filename = os.path.basename(args.coverage_file)
            with open(args.coverage_file, "rb") as handle:
                coverage_bytes = handle.read()
        else:
            filename = "local-e2e-lcov.info"
            coverage_bytes = b"SF:src/local_e2e.py\nDA:1,1\nDA:2,0\nend_of_record\n"

        fields = {
            "repository": args.repository,
            "commit_sha": args.commit_sha,
            "branch": args.branch,
            "format": "lcov",
            "uploader": "local-e2e",
        }
        if args.parent_sha:
            fields["parent_sha"] = args.parent_sha
        if args.pr_number:
            fields["pr_number"] = args.pr_number
        body, content_type = build_multipart(fields, filename, coverage_bytes)
        upload = request_json(
            "POST",
            "%s/api/v1/uploads" % base_url,
            {
                "Authorization": "Bearer %s" % upload_token,
                "Content-Type": content_type,
            },
            body,
        )
        print("upload queued: %s" % upload)

        deadline = time.time() + args.timeout_seconds
        commit_url = "%s/api/v1/repos/%s/%s/commits/%s" % (
            base_url,
            owner,
            repo,
            args.commit_sha,
        )
        while time.time() < deadline:
            try:
                commit = request_json("GET", commit_url, {})
                print("coverage processed: %s" % commit)
                return 0
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                time.sleep(2)
        print("timed out waiting for worker to process upload", file=sys.stderr)
        return 1
    except (HTTPError, URLError, OSError, KeyError, ValueError) as exc:
        print("local e2e upload failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
