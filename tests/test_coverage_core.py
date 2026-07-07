import hmac
import unittest

from app.coverage import (
    compute_patch_coverage,
    format_coverage,
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

    def test_compute_patch_coverage_counts_changed_lines_missing_from_report_as_uncovered(self):
        report = parse_lcov(
            b"""SF:src/api.py
DA:10,1
DA:11,0
DA:13,1
end_of_record
"""
        )

        result = compute_patch_coverage(report, {"src/api.py": {10, 11, 12, 13}})

        self.assertEqual(result.patch_total_lines, 4)
        self.assertEqual(result.patch_covered_lines, 2)
        self.assertAlmostEqual(result.patch_line_rate, 2 / 4)
        self.assertEqual(result.status_for_target(0.8), "failure")

    def test_compute_patch_coverage_records_file_results_and_unmatched_warnings(self):
        report = parse_lcov(
            b"""SF:/home/runner/work/covivy/covivy/app/api.py
DA:10,1
DA:11,0
DA:13,1
end_of_record
SF:app/jobs.py
DA:5,1
end_of_record
"""
        )

        result = compute_patch_coverage(
            report,
            {
                "app/api.py": {10, 11, 12, 13},
                "docs/readme.md": {1, 2},
                "app/jobs.py": set(),
            },
        )

        self.assertEqual(result.patch_covered_lines, 2)
        self.assertEqual(result.patch_total_lines, 4)
        self.assertEqual(
            [(item.path, item.patch_covered_lines, item.patch_total_lines) for item in result.files],
            [("app/api.py", 2, 4), ("app/jobs.py", 0, 0)],
        )
        self.assertEqual(result.unmatched_files, ["docs/readme.md"])
        self.assertIn("docs/readme.md did not match any coverage file", result.warnings[0])

    def test_format_coverage_uses_consistent_ratio_and_percent(self):
        self.assertEqual(format_coverage(0, 0), "0 / 0, (100.00%)")
        self.assertEqual(format_coverage(14, 17), "14 / 17, (82.35%)")

    def test_compute_patch_coverage_warns_on_ambiguous_suffix_match(self):
        report = parse_lcov(
            b"""SF:pkg_a/app/api.py
DA:1,1
end_of_record
SF:pkg_b/app/api.py
DA:1,1
end_of_record
"""
        )

        result = compute_patch_coverage(report, {"app/api.py": {1}})

        self.assertEqual(result.patch_total_lines, 0)
        self.assertEqual(result.unmatched_files, ["app/api.py"])
        self.assertEqual(result.warnings, ["app/api.py matched multiple coverage files"])

    def test_compute_patch_coverage_counts_changed_source_lines_missing_from_report_as_uncovered(self):
        report = parse_lcov(
            b"""SF:app/main.py
DA:100,1
DA:101,1
end_of_record
"""
        )

        result = compute_patch_coverage(report, {"app/main.py": {386, 387, 388, 389, 395}})

        self.assertEqual(result.patch_covered_lines, 0)
        self.assertEqual(result.patch_total_lines, 5)
        self.assertEqual(result.patch_line_rate, 0.0)
        self.assertEqual(
            [(item.path, item.patch_covered_lines, item.patch_total_lines) for item in result.files],
            [("app/main.py", 0, 5)],
        )

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
