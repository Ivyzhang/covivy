import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "upload_coverage_to_covivy.sh"


class UploadCoverageShellScriptTests(unittest.TestCase):
    def test_dry_run_reads_pull_request_event_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            event_path = root / "event.json"
            coverage_path = root / "coverage.xml"
            event_path.write_text(
                json.dumps(
                    {
                        "number": 12,
                        "pull_request": {
                            "head": {"sha": "head123", "ref": "feature-branch"},
                            "base": {"sha": "base456", "ref": "master"},
                        },
                    }
                )
            )
            coverage_path.write_text("<coverage />")

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--dry-run",
                    "--coverage-file",
                    str(coverage_path),
                    "--base-url",
                    "http://127.0.0.1:8000/",
                ],
                check=True,
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "COVIVY_UPLOAD_TOKEN": "cov_secret",
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_EVENT_PATH": str(event_path),
                    "GITHUB_REPOSITORY": "octo/demo",
                    "GITHUB_SHA": "fallback-sha",
                    "GITHUB_REF_NAME": "fallback-branch",
                },
            )

        self.assertIn("base_url=http://127.0.0.1:8000", result.stdout)
        self.assertIn("repository=octo/demo", result.stdout)
        self.assertIn("commit_sha=head123", result.stdout)
        self.assertIn("branch=feature-branch", result.stdout)
        self.assertIn("base_sha=base456", result.stdout)
        self.assertIn("base_branch=master", result.stdout)
        self.assertIn("pr_number=12", result.stdout)

    def test_dry_run_uses_push_environment_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverage_path = Path(tmpdir) / "coverage.xml"
            coverage_path.write_text("<coverage />")

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--dry-run",
                    "--coverage-file",
                    str(coverage_path),
                ],
                check=True,
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "COVIVY_UPLOAD_TOKEN": "cov_secret",
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_REPOSITORY": "octo/demo",
                    "GITHUB_SHA": "abc123",
                    "GITHUB_REF_NAME": "master",
                },
            )

        self.assertIn("repository=octo/demo", result.stdout)
        self.assertIn("commit_sha=abc123", result.stdout)
        self.assertIn("branch=master", result.stdout)
        self.assertIn("format=cobertura", result.stdout)


if __name__ == "__main__":
    unittest.main()
