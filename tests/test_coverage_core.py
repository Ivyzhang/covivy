import hmac
import tempfile
import unittest
from pathlib import Path

from app.coverage import (
    compute_patch_coverage,
    parse_cobertura,
    parse_lcov,
    parse_unified_diff_changed_lines,
)
from app.security import hash_upload_token, verify_github_signature, verify_upload_token


class CoverageCoreTests(unittest.TestCase):
    def test_parse_cobertura_preserves_lines_and_normalizes_paths(self):
        xml = """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="app">
      <classes>
        <class filename="/workspace/project/src/api.py">
          <lines>
            <line number="10" hits="1" branch="true" condition-coverage="50% (1/2)" />
            <line number="11" hits="0" />
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

        report = parse_cobertura(xml.encode(), workspace_prefixes=["/workspace/project"])

        self.assertEqual(report.total_lines, 2)
        self.assertEqual(report.covered_lines, 1)
        self.assertEqual(report.files[0].path, "src/api.py")
        self.assertEqual(report.files[0].lines[0].number, 10)
        self.assertEqual(report.files[0].lines[0].hits, 1)
        self.assertTrue(report.files[0].lines[0].branch)
        self.assertEqual(report.files[0].lines[0].condition_coverage, "50% (1/2)")

    def test_parse_lcov_handles_multiple_records(self):
        content = """TN:
SF:src/api.py
DA:3,1
DA:4,0
end_of_record
SF:src/jobs.py
DA:8,2
end_of_record
"""

        report = parse_lcov(content.encode())

        self.assertEqual([f.path for f in report.files], ["src/api.py", "src/jobs.py"])
        self.assertEqual(report.total_lines, 3)
        self.assertEqual(report.covered_lines, 2)
        self.assertAlmostEqual(report.line_rate, 2 / 3)

    def test_parse_unified_diff_records_only_head_side_added_lines(self):
        patch = """@@ -20,6 +20,8 @@ def route():
 context
+new_line_a
+new_line_b
-old_line
 unchanged
@@ -40 +42,2 @@
+another
 context
"""

        self.assertEqual(parse_unified_diff_changed_lines(patch), {21, 22, 42})

    def test_compute_patch_coverage_ignores_non_coverable_changed_lines(self):
        report = parse_lcov(
            b"""SF:src/api.py
DA:10,1
DA:11,0
DA:13,1
end_of_record
"""
        )

        result = compute_patch_coverage(report, {"src/api.py": {10, 11, 12, 13}})

        self.assertEqual(result.patch_total_lines, 3)
        self.assertEqual(result.patch_covered_lines, 2)
        self.assertAlmostEqual(result.patch_line_rate, 2 / 3)
        self.assertEqual(result.status_for_target(0.8), "failure")

    def test_security_helpers_hash_tokens_and_verify_github_signature(self):
        token_hash = hash_upload_token("cov_secret", "pepper")

        self.assertTrue(verify_upload_token("cov_secret", "pepper", token_hash))
        self.assertFalse(verify_upload_token("cov_other", "pepper", token_hash))

        payload = b'{"action":"opened"}'
        digest = hmac.new(b"webhook-secret", payload, "sha256").hexdigest()
        self.assertTrue(
            verify_github_signature(payload, f"sha256={digest}", "webhook-secret")
        )
        self.assertFalse(
            verify_github_signature(payload, "sha256=bad", "webhook-secret")
        )


if __name__ == "__main__":
    unittest.main()
