import hmac
import unittest

from app.coverage import (
    compute_patch_coverage,
    format_coverage,
    parse_cobertura,
    parse_go_coverprofile,
    parse_lcov,
    parse_report,
    parse_unified_diff_changed_line_contents,
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

    def test_parse_go_coverprofile_expands_block_ranges(self):
        content = """mode: set
github.com/acme/demo/pkg/api.go:10.2,12.4 2 1
github.com/acme/demo/pkg/api.go:15.2,15.20 1 0
"""

        report = parse_go_coverprofile(content.encode())

        self.assertEqual([file.path for file in report.files], ["github.com/acme/demo/pkg/api.go"])
        self.assertEqual(
            [(line.number, line.hits) for line in report.files[0].lines],
            [(10, 1), (11, 1), (12, 1), (15, 0)],
        )
        self.assertEqual(parse_report("go-coverprofile", content.encode()).total_lines, 4)

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

    def test_parse_unified_diff_records_changed_line_contents(self):
        patch = """@@ -10,2 +10,4 @@
+base_report = (
+    latest_report_for_commit(session, repository.id, pull_request.base_sha)
+
+)
 context
"""

        self.assertEqual(
            parse_unified_diff_changed_line_contents(patch),
            {
                10: "base_report = (",
                11: "    latest_report_for_commit(session, repository.id, pull_request.base_sha)",
                12: "",
                13: ")",
            },
        )

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
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(386, False), (387, False), (388, False), (389, False), (395, False)],
        )

    def test_compute_patch_coverage_ignores_test_files_and_blank_changed_lines(self):
        report = parse_lcov(
            b"""SF:app/main.py
DA:10,1
end_of_record
SF:tests/test_main.py
DA:5,0
end_of_record
SF:src/widget.test.ts
DA:9,0
end_of_record
"""
        )

        result = compute_patch_coverage(
            report,
            {
                "app/main.py": {10, 11},
                "tests/test_main.py": {5},
                "src/widget.test.ts": {9},
            },
            {
                "app/main.py": {10: "value = 1", 11: ""},
                "tests/test_main.py": {5: "def test_value(): pass"},
                "src/widget.test.ts": {9: "it('works', () => {})"},
            },
        )

        self.assertEqual(result.patch_covered_lines, 1)
        self.assertEqual(result.patch_total_lines, 1)
        self.assertEqual(
            [(item.path, item.patch_covered_lines, item.patch_total_lines) for item in result.files],
            [("app/main.py", 1, 1)],
        )
        self.assertEqual([(line.number, line.covered) for line in result.files[0].lines], [(10, True)])

    def test_compute_patch_coverage_treats_multiline_python_statement_as_covered_unit(self):
        report = parse_lcov(
            b"""SF:app/services.py
DA:558,1
end_of_record
"""
        )

        result = compute_patch_coverage(
            report,
            {"app/services.py": {558, 559, 560, 561, 562}},
            {
                "app/services.py": {
                    558: "base_report = (",
                    559: "    latest_report_for_commit(session, repository.id, pull_request.base_sha)",
                    560: "    if pull_request.base_sha",
                    561: "    else None",
                    562: ")",
                }
            },
        )

        self.assertEqual(result.patch_covered_lines, 5)
        self.assertEqual(result.patch_total_lines, 5)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(558, True), (559, True), (560, True), (561, True), (562, True)],
        )

    def test_compute_patch_coverage_recovers_multiline_call_inside_partial_changed_block(self):
        report = parse_lcov(
            b"""SF:app/main.py
DA:473,1
DA:474,1
DA:475,1
DA:480,1
DA:481,1
DA:482,1
end_of_record
"""
        )
        contents = {
            473: "        row_parts = []",
            474: "        for file in file_rows:",
            475: "            line_rows = session.scalars(",
            476: "                select(PrFileLineAnnotation)",
            477: "                .where(PrFileLineAnnotation.file_annotation_id == file.id)",
            478: "                .order_by(PrFileLineAnnotation.line_number)",
            479: "            ).all()",
            480: '            covered_lines = ", ".join(str(line.line_number) for line in line_rows if line.covered)',
            481: '            missing_lines = ", ".join(str(line.line_number) for line in line_rows if not line.covered)',
            482: "            row_parts.append(",
            483: '                "<tr><td>{path}</td><td>{lines}</td><td>{coverage}</td>"',
        }

        result = compute_patch_coverage(
            report,
            {"app/main.py": set(contents)},
            {"app/main.py": contents},
        )

        covered_by_line = {line.number: line.covered for line in result.files[0].lines}
        self.assertEqual(
            [(line, covered_by_line[line]) for line in [475, 476, 477, 478, 479]],
            [(475, True), (476, True), (477, True), (478, True), (479, True)],
        )

    def test_compute_patch_coverage_uses_full_python_source_for_partial_statement_changes(self):
        report = parse_lcov(
            b"""SF:app/services.py
DA:2,1
DA:9,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "def render():",
                "    lines = [",
                '        "| Covered changed lines | %s | %s |"',
                "        % (",
                "            covered_count(result.patch_covered_lines, result.patch_total_lines),",
                "            coverage_percent(result.patch_covered_lines, result.patch_total_lines) + patch_suffix,",
                "        ),",
                "    ]",
                "    file_annotation = PrFileAnnotation(",
                "        annotation_id=annotation.id,",
                "        path=file_result.path,",
                "        patch_covered_lines=file_result.patch_covered_lines,",
                "        patch_total_lines=file_result.patch_total_lines,",
                "    )",
            ]
        )
        changed_contents = {
            6: "            coverage_percent(result.patch_covered_lines, result.patch_total_lines) + patch_suffix,",
            10: "        annotation_id=annotation.id,",
            11: "        path=file_result.path,",
            12: "        patch_covered_lines=file_result.patch_covered_lines,",
            13: "        patch_total_lines=file_result.patch_total_lines,",
        }

        result = compute_patch_coverage(
            report,
            {"app/services.py": set(changed_contents)},
            {"app/services.py": changed_contents},
            {"app/services.py": source},
        )

        self.assertEqual(result.patch_covered_lines, 5)
        self.assertEqual(result.patch_total_lines, 5)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(6, True), (10, True), (11, True), (12, True), (13, True)],
        )

    def test_compute_patch_coverage_uses_typescript_semantics_and_ignores_comments(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "export function client() {",
                "  return api.request({",
                "    method: 'POST',",
                "    url: '/users',",
                "    body: { active: true },",
                "  });",
                "}",
                "",
                "// changed comment",
            ]
        )
        changed_contents = {
            3: "    method: 'POST',",
            4: "    url: '/users',",
            5: "    body: { active: true },",
            8: "",
            9: "// changed comment",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 3)
        self.assertEqual(result.patch_total_lines, 3)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(3, True), (4, True), (5, True)],
        )

    def test_compute_patch_coverage_does_not_cover_typescript_statement_from_function_block(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
DA:3,0
end_of_record
"""
        )
        source = "\n".join(
            [
                "export function f() {",
                "  covered();",
                "  missed();",
                "}",
            ]
        )

        result = compute_patch_coverage(
            report,
            {"src/client.ts": {3}},
            {"src/client.ts": {3: "  missed();"}},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 0)
        self.assertEqual(result.patch_total_lines, 1)
        self.assertEqual([(line.number, line.covered) for line in result.files[0].lines], [(3, False)])

    def test_compute_patch_coverage_keeps_unresolved_changed_lines_in_denominator(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "export function a() {",
                "  return api.request({",
                "    url: '/x',",
                "  });",
                "}",
                "export function b() {",
                "  missed();",
                "}",
            ]
        )
        changed_contents = {
            3: "    url: '/x',",
            7: "  missed();",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 1)
        self.assertEqual(result.patch_total_lines, 2)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(3, True), (7, False)],
        )

    def test_compute_patch_coverage_ignores_typescript_type_only_changes(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:7,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "import type { User } from './types';",
                "",
                "interface Options {",
                "  enabled: boolean;",
                "}",
                "",
                "export const active = true;",
            ]
        )
        changed_contents = {
            1: "import type { User } from './types';",
            3: "interface Options {",
            4: "  enabled: boolean;",
            5: "}",
            7: "export const active = true;",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 1)
        self.assertEqual(result.patch_total_lines, 1)
        self.assertEqual([(line.number, line.covered) for line in result.files[0].lines], [(7, True)])

    def test_compute_patch_coverage_counts_runtime_typescript_imports(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:3,1
end_of_record
"""
        )
        source = "\n".join(
            [
                'import { makeClient } from "./client";',
                'import type { User } from "./types";',
                "export const active = true;",
            ]
        )
        changed_contents = {
            1: 'import { makeClient } from "./client";',
            2: 'import type { User } from "./types";',
            3: "export const active = true;",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 1)
        self.assertEqual(result.patch_total_lines, 2)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(1, False), (3, True)],
        )

    def test_compute_patch_coverage_counts_side_effect_typescript_imports(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
end_of_record
"""
        )
        source = "\n".join(
            [
                'import "./polyfill";',
                "export const active = true;",
            ]
        )
        changed_contents = {
            1: 'import "./polyfill";',
            2: "export const active = true;",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 1)
        self.assertEqual(result.patch_total_lines, 2)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(1, False), (2, True)],
        )

    def test_compute_patch_coverage_counts_runtime_typescript_namespace_and_enum_members(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
DA:6,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "namespace RuntimeConfig {",
                "  export const enabled = true;",
                "}",
                "",
                "enum Mode {",
                "  Active = 1,",
                "}",
                "",
                "declare namespace AmbientConfig {",
                "  const enabled: boolean;",
                "}",
            ]
        )
        changed_contents = {
            2: "  export const enabled = true;",
            6: "  Active = 1,",
            10: "  const enabled: boolean;",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 2)
        self.assertEqual(result.patch_total_lines, 2)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(2, True), (6, True)],
        )

    def test_compute_patch_coverage_does_not_cover_missed_typescript_variable_declarator(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:1,1
DA:2,0
end_of_record
"""
        )
        source = "\n".join(
            [
                "const a = covered(),",
                "  b = missed();",
            ]
        )

        result = compute_patch_coverage(
            report,
            {"src/client.ts": {2}},
            {"src/client.ts": {2: "  b = missed();"}},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 0)
        self.assertEqual(result.patch_total_lines, 1)
        self.assertEqual([(line.number, line.covered) for line in result.files[0].lines], [(2, False)])

    def test_compute_patch_coverage_trusts_empty_typescript_compiler_decisions(self):
        report = parse_lcov(
            b"""SF:src/client.ts
DA:2,1
end_of_record
"""
        )
        source = "\n".join(
            [
                "class Client {",
                "  config = {",
                "    missed: true,",
                "  };",
                "}",
            ]
        )
        changed_contents = {
            3: "    missed: true,",
        }

        result = compute_patch_coverage(
            report,
            {"src/client.ts": set(changed_contents)},
            {"src/client.ts": changed_contents},
            {"src/client.ts": source},
        )

        self.assertEqual(result.patch_covered_lines, 0)
        self.assertEqual(result.patch_total_lines, 1)
        self.assertEqual([(line.number, line.covered) for line in result.files[0].lines], [(3, False)])

    def test_compute_patch_coverage_supports_go_coverprofile_and_ignores_comments(self):
        report = parse_go_coverprofile(
            b"""mode: count
github.com/acme/demo/pkg/api.go:4.2,8.3 3 1
github.com/acme/demo/pkg/api.go:11.2,11.18 1 0
"""
        )
        source = "\n".join(
            [
                "package api",
                "",
                "func Build() string {",
                "    return strings.Join([]string{",
                '        "a",',
                '        "b",',
                "    }, \",\")",
                "}",
                "",
                "// changed comment",
                "func Missed() string { return \"x\" }",
            ]
        )
        changed_contents = {
            5: '        "a",',
            6: '        "b",',
            10: "// changed comment",
            11: 'func Missed() string { return "x" }',
        }

        result = compute_patch_coverage(
            report,
            {"github.com/acme/demo/pkg/api.go": set(changed_contents)},
            {"github.com/acme/demo/pkg/api.go": changed_contents},
            {"github.com/acme/demo/pkg/api.go": source},
        )

        self.assertEqual(result.patch_covered_lines, 2)
        self.assertEqual(result.patch_total_lines, 3)
        self.assertEqual(
            [(line.number, line.covered) for line in result.files[0].lines],
            [(5, True), (6, True), (11, False)],
        )

    def test_compute_patch_coverage_ignores_go_structural_brace_lines(self):
        report = parse_go_coverprofile(
            b"""mode: set
github.com/acme/demo/pkg/api.go:4.2,8.3 3 1
"""
        )
        source = "\n".join(
            [
                "package api",
                "",
                "func Build() string {",
                "    return strings.Join([]string{",
                '        "a",',
                '        "b",',
                "    }, \",\")",
                "}",
            ]
        )

        result = compute_patch_coverage(
            report,
            {"github.com/acme/demo/pkg/api.go": {8}},
            {"github.com/acme/demo/pkg/api.go": {8: "}"}},
            {"github.com/acme/demo/pkg/api.go": source},
        )

        self.assertEqual(result.patch_covered_lines, 0)
        self.assertEqual(result.patch_total_lines, 0)
        self.assertEqual(result.files[0].lines, [])

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
