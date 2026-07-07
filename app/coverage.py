from __future__ import annotations

import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set


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
class PatchFileCoverage:
    path: str
    patch_covered_lines: int
    patch_total_lines: int

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


_HUNK_RE = re.compile(r"@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")


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


def compute_patch_coverage(
    report: CoverageReport, changed_lines_by_file: Dict[str, Set[int]]
) -> PatchCoverageResult:
    covered = 0
    total = 0
    file_results: List[PatchFileCoverage] = []
    unmatched_files: List[str] = []
    warnings: List[str] = []
    coverage_by_file = {normalize_path(file.path): file for file in report.files}
    normalized_paths = list(coverage_by_file)
    for path, changed_lines in changed_lines_by_file.items():
        normalized_path = normalize_path(path)
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
        if covered_file is None:
            if changed_lines:
                unmatched_files.append(path)
                warnings.append("%s did not match any coverage file" % path)
            continue
        hits_by_line = {line.number: line.hits for line in covered_file.lines}
        file_covered = 0
        file_total = 0
        for line_number in changed_lines:
            if line_number not in hits_by_line:
                continue
            file_total += 1
            if hits_by_line[line_number] > 0:
                file_covered += 1
        covered += file_covered
        total += file_total
        file_results.append(
            PatchFileCoverage(
                path=path,
                patch_covered_lines=file_covered,
                patch_total_lines=file_total,
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
    raise ValueError("unsupported coverage format: %s" % format_name)
