from __future__ import annotations

import ast
import json
import re
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class CoveredLine:
    number: int
    hits: int
    branch: bool = False
    condition_coverage: Optional[str] = None


@dataclass(frozen=True)
class CoveredFile:
    path: str
    lines: List[CoveredLine]

    @property
    def total_lines(self) -> int:
        return len(self.lines)

    @property
    def covered_lines(self) -> int:
        return sum(1 for line in self.lines if line.hits > 0)

    @property
    def line_rate(self) -> float:
        return self.covered_lines / self.total_lines if self.total_lines else 0.0


@dataclass(frozen=True)
class CoverageReport:
    files: List[CoveredFile]

    @property
    def total_lines(self) -> int:
        return sum(file.total_lines for file in self.files)

    @property
    def covered_lines(self) -> int:
        return sum(file.covered_lines for file in self.files)

    @property
    def line_rate(self) -> float:
        return self.covered_lines / self.total_lines if self.total_lines else 0.0

    def file_map(self) -> Dict[str, CoveredFile]:
        return {file.path: file for file in self.files}


@dataclass(frozen=True)
class PatchLineCoverage:
    number: int
    covered: bool


@dataclass(frozen=True)
class PatchFileCoverage:
    path: str
    patch_covered_lines: int
    patch_total_lines: int
    lines: List[PatchLineCoverage] = field(default_factory=list)

    @property
    def patch_line_rate(self) -> float:
        if self.patch_total_lines == 0:
            return 1.0
        return self.patch_covered_lines / self.patch_total_lines


@dataclass(frozen=True)
class PatchCoverageResult:
    patch_covered_lines: int
    patch_total_lines: int
    files: List[PatchFileCoverage] = field(default_factory=list)
    unmatched_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def patch_line_rate(self) -> float:
        if self.patch_total_lines == 0:
            return 1.0
        return self.patch_covered_lines / self.patch_total_lines

    def status_for_target(self, minimum: float) -> str:
        return "success" if self.patch_line_rate >= minimum else "failure"

    def description_for_target(self, minimum: float) -> str:
        if self.patch_total_lines == 0:
            return "No coverable changed lines found"
        percent = self.patch_line_rate * 100
        target = minimum * 100
        if self.patch_line_rate >= minimum:
            return "Patch coverage %.2f%% meets target %.2f%%" % (percent, target)
        return "Patch coverage %.2f%% is below target %.2f%%" % (percent, target)


def format_coverage(covered: int, total: int) -> str:
    rate = 1.0 if total == 0 else covered / total
    return "%s / %s, (%.2f%%)" % (covered, total, rate * 100)


def normalize_path(path: str, workspace_prefixes: Optional[Iterable[str]] = None) -> str:
    normalized = path.replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    prefixes = list(workspace_prefixes or [])
    for prefix in prefixes:
        prefix_normalized = re.sub(r"/+", "/", prefix.replace("\\", "/")).rstrip("/")
        if normalized == prefix_normalized:
            normalized = ""
            break
        if normalized.startswith(prefix_normalized + "/"):
            normalized = normalized[len(prefix_normalized) + 1 :]
            break
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def parse_cobertura(
    payload: bytes, workspace_prefixes: Optional[Iterable[str]] = None
) -> CoverageReport:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("invalid Cobertura XML: %s" % exc) from exc

    files: List[CoveredFile] = []
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        lines: List[CoveredLine] = []
        for line_node in class_node.findall("./lines/line"):
            try:
                number = int(line_node.attrib["number"])
                hits = int(float(line_node.attrib.get("hits", "0")))
            except (KeyError, ValueError) as exc:
                raise ValueError("invalid Cobertura line record") from exc
            lines.append(
                CoveredLine(
                    number=number,
                    hits=hits,
                    branch=line_node.attrib.get("branch", "false").lower() == "true",
                    condition_coverage=line_node.attrib.get("condition-coverage"),
                )
            )
        files.append(
            CoveredFile(
                path=normalize_path(filename, workspace_prefixes),
                lines=sorted(lines, key=lambda item: item.number),
            )
        )
    return CoverageReport(files=files)


def parse_lcov(
    payload: bytes, workspace_prefixes: Optional[Iterable[str]] = None
) -> CoverageReport:
    text = payload.decode("utf-8", errors="replace")
    files: List[CoveredFile] = []
    current_path: Optional[str] = None
    current_lines: List[CoveredLine] = []

    def flush() -> None:
        nonlocal current_path, current_lines
        if current_path is not None:
            files.append(
                CoveredFile(
                    path=normalize_path(current_path, workspace_prefixes),
                    lines=sorted(current_lines, key=lambda item: item.number),
                )
            )
        current_path = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            flush()
            current_path = line[3:]
        elif line.startswith("DA:"):
            if current_path is None:
                raise ValueError("LCOV DA record appeared before SF record")
            values = line[3:].split(",", 1)
            if len(values) != 2:
                raise ValueError("invalid LCOV DA record")
            try:
                current_lines.append(CoveredLine(number=int(values[0]), hits=int(values[1])))
            except ValueError as exc:
                raise ValueError("invalid LCOV DA values") from exc
        elif line == "end_of_record":
            flush()
    flush()
    return CoverageReport(files=files)


def parse_go_coverprofile(
    payload: bytes, workspace_prefixes: Optional[Iterable[str]] = None
) -> CoverageReport:
    text = payload.decode("utf-8", errors="replace")
    lines_by_file: Dict[str, Dict[int, int]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("mode:"):
            continue
        match = _GO_COVER_RE.match(line)
        if not match:
            raise ValueError("invalid Go coverprofile record")
        path = normalize_path(match.group("path"), workspace_prefixes)
        start_line = int(match.group("start_line"))
        end_line = int(match.group("end_line"))
        count = int(match.group("count"))
        file_lines = lines_by_file.setdefault(path, {})
        for line_number in range(start_line, end_line + 1):
            file_lines[line_number] = max(file_lines.get(line_number, 0), count)
    return CoverageReport(
        files=[
            CoveredFile(
                path=path,
                lines=[
                    CoveredLine(number=line_number, hits=hits)
                    for line_number, hits in sorted(file_lines.items())
                ],
            )
            for path, file_lines in lines_by_file.items()
        ]
    )


_HUNK_RE = re.compile(r"@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")
_GO_COVER_RE = re.compile(
    r"^(?P<path>.+):(?P<start_line>\d+)\.(?P<start_col>\d+),"
    r"(?P<end_line>\d+)\.(?P<end_col>\d+)\s+"
    r"(?P<statements>\d+)\s+(?P<count>\d+)$"
)
_TYPESCRIPT_ANALYZER = (
    Path(__file__).resolve().parent.parent / "scripts" / "typescript_semantic_analyzer.mjs"
)


def parse_unified_diff_changed_lines(patch: str) -> Set[int]:
    changed: Set[int] = set()
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    for raw_line in patch.splitlines():
        match = _HUNK_RE.match(raw_line)
        if match:
            old_line = int(match.group("old"))
            new_line = int(match.group("new"))
            continue
        if old_line is None or new_line is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            changed.add(new_line)
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return changed


def parse_unified_diff_changed_line_contents(patch: str) -> Dict[int, str]:
    contents: Dict[int, str] = {}
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    for raw_line in patch.splitlines():
        match = _HUNK_RE.match(raw_line)
        if match:
            old_line = int(match.group("old"))
            new_line = int(match.group("new"))
            continue
        if old_line is None or new_line is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            contents[new_line] = raw_line[1:]
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return contents


def is_test_path(path: str) -> bool:
    normalized = normalize_path(path)
    parts = normalized.split("/")
    filename = parts[-1] if parts else normalized
    return (
        "tests" in parts
        or "__tests__" in parts
        or "testdata" in parts
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith("_tests.py")
        or filename.endswith("_test.go")
        or filename.endswith(".test.js")
        or filename.endswith(".test.jsx")
        or filename.endswith(".test.ts")
        or filename.endswith(".test.tsx")
        or filename.endswith(".spec.js")
        or filename.endswith(".spec.jsx")
        or filename.endswith(".spec.ts")
        or filename.endswith(".spec.tsx")
    )


def source_lines(source: str) -> Dict[int, str]:
    if not source:
        return {}
    return {index: line for index, line in enumerate(source.splitlines(), start=1)}


def non_code_lines_from_source(path: str, source: str) -> Set[int]:
    lines = source_lines(source)
    non_code: Set[int] = set()
    in_block_comment = False
    for line_number, line in lines.items():
        stripped = line.strip()
        if not stripped:
            non_code.add(line_number)
            continue
        if in_block_comment:
            non_code.add(line_number)
            if "*/" in stripped:
                in_block_comment = False
                after = stripped.split("*/", 1)[1].strip()
                if after:
                    non_code.discard(line_number)
            continue
        if path.endswith(".py") and stripped.startswith("#"):
            non_code.add(line_number)
            continue
        if path.endswith((".go", ".js", ".jsx", ".ts", ".tsx")):
            if stripped.startswith("//"):
                non_code.add(line_number)
                continue
            if path.endswith(".go"):
                code_part = stripped.split("//", 1)[0].strip()
                if code_part in {"}", "{", "})", "};"}:
                    non_code.add(line_number)
                    continue
            block_start = stripped.find("/*")
            if block_start != -1:
                before = stripped[:block_start].strip()
                block_end = stripped.find("*/", block_start + 2)
                after = stripped[block_end + 2 :].strip() if block_end != -1 else ""
                if not before and (block_end == -1 or not after):
                    non_code.add(line_number)
                if block_end == -1:
                    in_block_comment = True
                continue
    return non_code


def jsts_statement_coverage_from_source(
    path: str,
    source: str,
    changed_lines: Set[int],
    hits_by_line: Dict[int, int],
) -> Dict[int, bool]:
    if not path.endswith((".js", ".jsx", ".ts", ".tsx")) or not source:
        return {}
    spans: List[Tuple[int, int]] = []
    stack: List[Tuple[str, int]] = []
    pairs = {"(": ")", "[": "]"}
    closing = {")", "]", "}"}
    in_string: Optional[str] = None
    escaped = False
    in_block_comment = False
    for line_number, line in enumerate(source.splitlines(), start=1):
        index = 0
        while index < len(line):
            char = line[index]
            nxt = line[index : index + 2]
            if in_block_comment:
                if nxt == "*/":
                    in_block_comment = False
                    index += 2
                    continue
                index += 1
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
                index += 1
                continue
            if nxt == "//":
                break
            if nxt == "/*":
                in_block_comment = True
                index += 2
                continue
            if char in {"'", '"', "`"}:
                in_string = char
            elif char == "{":
                previous = line[:index].rstrip()
                if previous.endswith(("(", "[", "=", ":", ",", "return")):
                    stack.append(("}", line_number))
            elif char in pairs:
                stack.append((pairs[char], line_number))
            elif char in closing and stack:
                expected, start_line = stack.pop()
                if char == expected and start_line != line_number:
                    spans.append((start_line, line_number))
            index += 1
    decisions: Dict[int, bool] = {}
    for line_number in changed_lines:
        containing_spans = [
            span for span in spans if span[0] <= line_number <= span[1]
        ]
        for start, end in sorted(containing_spans, key=lambda span: (span[1] - span[0], span[0])):
            statement_hits = [
                hits
                for statement_line, hits in hits_by_line.items()
                if start <= statement_line <= end
            ]
            if statement_hits:
                decisions[line_number] = any(hits > 0 for hits in statement_hits)
                break
    return decisions


def typescript_semantic_analysis_from_source(
    path: str,
    source: str,
    changed_lines: Set[int],
    hits_by_line: Dict[int, int],
) -> Tuple[Dict[int, bool], Set[int], bool]:
    if not path.endswith((".js", ".jsx", ".ts", ".tsx")) or not source:
        return {}, set(), False
    if not _TYPESCRIPT_ANALYZER.exists():
        return {}, set(), False
    payload = {
        "path": path,
        "source": source,
        "changedLines": sorted(changed_lines),
        "hitsByLine": {str(line): hits for line, hits in hits_by_line.items()},
    }
    try:
        completed = subprocess.run(
            ["node", str(_TYPESCRIPT_ANALYZER)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        result = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}, set(), False
    decisions = {
        int(line): bool(covered)
        for line, covered in (result.get("lineDecisions") or {}).items()
    }
    non_code_lines = {int(line) for line in result.get("nonCodeLines") or []}
    return decisions, non_code_lines, True


def semantic_statement_coverage_from_source(
    path: str,
    source: str,
    changed_lines: Set[int],
    hits_by_line: Dict[int, int],
) -> Dict[int, bool]:
    if path.endswith(".py"):
        return python_statement_coverage_from_source(path, source, changed_lines, hits_by_line)
    return {}


def cover_multiline_python_statements(
    path: str,
    changed_line_contents: Dict[int, str],
    exactly_covered_lines: Set[int],
) -> Set[int]:
    if not path.endswith(".py") or not changed_line_contents:
        return set()
    covered: Set[int] = set()

    def covered_statement_lines(line_numbers: List[int]) -> Set[int]:
        source = "\n".join(changed_line_contents[number] for number in line_numbers)
        try:
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:
            return set()
        first_line = line_numbers[0]
        changed_lines = set(line_numbers)
        statement_covered: Set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt) or not hasattr(node, "lineno"):
                continue
            start = first_line + node.lineno - 1
            end = first_line + getattr(node, "end_lineno", node.lineno) - 1
            statement_lines = set(range(start, end + 1)) & changed_lines
            if statement_lines & exactly_covered_lines:
                statement_covered.update(statement_lines)
        return statement_covered

    current_group: List[int] = []
    groups: List[List[int]] = []
    for line_number in sorted(changed_line_contents):
        if current_group and line_number != current_group[-1] + 1:
            groups.append(current_group)
            current_group = []
        current_group.append(line_number)
    if current_group:
        groups.append(current_group)
    for line_numbers in groups:
        group_covered = covered_statement_lines(line_numbers)
        if group_covered:
            covered.update(group_covered)
            continue
        for index, line_number in enumerate(line_numbers):
            if line_number not in exactly_covered_lines:
                continue
            for end_index in range(index, len(line_numbers)):
                window_covered = covered_statement_lines(line_numbers[index : end_index + 1])
                if window_covered:
                    covered.update(window_covered)
                    break
    return covered


def python_statement_coverage_from_source(
    path: str,
    source: str,
    changed_lines: Set[int],
    hits_by_line: Dict[int, int],
) -> Dict[int, bool]:
    if not path.endswith(".py") or not source:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    spans: List[Tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or not hasattr(node, "lineno"):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        spans.append((start, end))

    decisions: Dict[int, bool] = {}
    for line_number in changed_lines:
        containing_spans = [
            span for span in spans if span[0] <= line_number <= span[1]
        ]
        if not containing_spans:
            continue
        start, end = min(containing_spans, key=lambda span: (span[1] - span[0], span[0]))
        statement_hits = [
            hits
            for statement_line, hits in hits_by_line.items()
            if start <= statement_line <= end
        ]
        if statement_hits:
            decisions[line_number] = any(hits > 0 for hits in statement_hits)
    return decisions


def compute_patch_coverage(
    report: CoverageReport,
    changed_lines_by_file: Dict[str, Set[int]],
    changed_line_contents_by_file: Optional[Dict[str, Dict[int, str]]] = None,
    source_by_file: Optional[Dict[str, str]] = None,
) -> PatchCoverageResult:
    covered = 0
    total = 0
    file_results: List[PatchFileCoverage] = []
    unmatched_files: List[str] = []
    warnings: List[str] = []
    coverage_by_file = {normalize_path(file.path): file for file in report.files}
    normalized_paths = list(coverage_by_file)
    changed_line_contents_by_file = changed_line_contents_by_file or {}
    source_by_file = source_by_file or {}
    for path, changed_lines in changed_lines_by_file.items():
        normalized_path = normalize_path(path)
        if is_test_path(normalized_path):
            continue
        line_contents = changed_line_contents_by_file.get(path) or changed_line_contents_by_file.get(normalized_path) or {}
        source = source_by_file.get(path) or source_by_file.get(normalized_path) or ""
        source_content_by_line = source_lines(source)
        non_code_lines = non_code_lines_from_source(normalized_path, source)
        covered_file = coverage_by_file.get(normalized_path)
        if covered_file is None:
            suffix_matches = [
                item for item in normalized_paths if item.endswith("/" + normalized_path)
            ]
            if len(suffix_matches) == 1:
                covered_file = coverage_by_file[suffix_matches[0]]
            elif len(suffix_matches) > 1:
                unmatched_files.append(path)
                warnings.append("%s matched multiple coverage files" % path)
                continue
        hits_by_line = (
            {line.number: line.hits for line in covered_file.lines}
            if covered_file is not None
            else {}
        )
        typescript_line_decisions: Dict[int, bool] = {}
        typescript_analyzer_available = False
        if normalized_path.endswith((".js", ".jsx", ".ts", ".tsx")):
            typescript_line_decisions, typescript_non_code_lines, typescript_analyzer_available = (
                typescript_semantic_analysis_from_source(
                    normalized_path,
                    source,
                    set(changed_lines),
                    hits_by_line,
                )
            )
            non_code_lines.update(typescript_non_code_lines)
        coverable_changed_lines = set(changed_lines)
        if line_contents or source_content_by_line:
            coverable_changed_lines = {
                line_number
                for line_number in changed_lines
                if (
                    line_contents.get(line_number, source_content_by_line.get(line_number, "")).strip()
                )
                and line_number not in non_code_lines
            }
        if covered_file is None:
            if coverable_changed_lines:
                unmatched_files.append(path)
                warnings.append("%s did not match any coverage file" % path)
            continue
        exactly_covered_lines = {
            line_number
            for line_number in coverable_changed_lines
            if hits_by_line.get(line_number, 0) > 0
        }
        if normalized_path.endswith((".js", ".jsx", ".ts", ".tsx")):
            source_line_decisions = {
                line: covered
                for line, covered in typescript_line_decisions.items()
                if line in coverable_changed_lines
            }
            if not typescript_analyzer_available:
                source_line_decisions = jsts_statement_coverage_from_source(
                    normalized_path,
                    source,
                    coverable_changed_lines,
                    hits_by_line,
                )
        else:
            source_line_decisions = semantic_statement_coverage_from_source(
                normalized_path,
                source,
                coverable_changed_lines,
                hits_by_line,
            )
        inferred_covered_lines = cover_multiline_python_statements(
            normalized_path,
            {line: line_contents[line] for line in coverable_changed_lines if line in line_contents},
            exactly_covered_lines,
        )
        file_covered = 0
        file_total = 0
        line_results: List[PatchLineCoverage] = []
        for line_number in sorted(coverable_changed_lines):
            file_total += 1
            line_covered = (
                source_line_decisions.get(line_number, False)
                or line_number in exactly_covered_lines
                or line_number in inferred_covered_lines
            )
            if line_covered:
                file_covered += 1
            line_results.append(PatchLineCoverage(number=line_number, covered=line_covered))
        covered += file_covered
        total += file_total
        file_results.append(
            PatchFileCoverage(
                path=path,
                patch_covered_lines=file_covered,
                patch_total_lines=file_total,
                lines=line_results,
            )
        )
    return PatchCoverageResult(
        patch_covered_lines=covered,
        patch_total_lines=total,
        files=file_results,
        unmatched_files=unmatched_files,
        warnings=warnings,
    )


def parse_report(format_name: str, payload: bytes) -> CoverageReport:
    lowered = format_name.lower()
    if lowered == "cobertura":
        return parse_cobertura(payload)
    if lowered == "lcov":
        return parse_lcov(payload)
    if lowered in {"go-coverprofile", "go", "coverprofile"}:
        return parse_go_coverprofile(payload)
    raise ValueError("unsupported coverage format: %s" % format_name)
