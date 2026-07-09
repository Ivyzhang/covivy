from __future__ import annotations

import ast
from html import escape
from typing import Optional

from app.models import (
    CoverageReportRow,
    PrAnnotation,
    PrFileAnnotation,
    PrFileLineAnnotation,
    PullRequest,
    Repository,
)


def percent(value: float) -> str:
    return "%.2f%%" % (value * 100)


def status_icon(passed: bool) -> str:
    if passed:
        return '<span class="status-pass">✓</span>'
    return '<span class="status-fail">✗</span>'


def trend_icon(current: float, base: Optional[float]) -> str:
    if base is None:
        return ""
    if current >= base:
        return '<span class="trend-up">↑</span>'
    return '<span class="trend-down">↓</span>'


def signed_percent(value: Optional[float]) -> str:
    if value is None:
        return "Base unavailable"
    return "%+.2f%%" % (value * 100)


def app_page_html(title: str, body: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>" + escape(title) + "</title>"
        "<style>"
        ":root{--bg:#f4f6fb;--card:#fff;--ink:#16143d;--muted:#5e6175;--line:#d8deea;"
        "--green:#2edca8;--pink:#ee2b6c;--soft:#eef1f7}"
        "*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px}"
        "a{color:var(--pink);font-weight:700;text-decoration:none}.app-shell{max-width:1180px;margin:0 auto;padding:20px}"
        ".app-header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:18px}"
        ".app-brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-size:24px;font-weight:850}"
        ".app-brand-mark{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#20dfa2,#8cead5);"
        "display:grid;place-items:center;color:#fff}.app-nav{display:flex;flex-wrap:wrap;gap:10px;align-items:center}"
        ".nav-chip{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:6px 10px;color:var(--ink);font-weight:700}"
        ".nav-chip.disabled{opacity:.6;background:var(--soft);cursor:not-allowed}.chip-form{margin:0}.logout-chip{font:inherit;cursor:pointer}"
        ".dashboard-hero{background:var(--card);border-radius:12px;box-shadow:0 2px 10px rgba(20,20,50,.08);padding:18px 22px;margin-bottom:14px}"
        ".dashboard-hero h1{font-size:22px;line-height:1.18;margin:0 0 7px}.dashboard-hero p{margin:0;color:var(--muted);font-size:13px;line-height:1.45}"
        ".eyebrow{color:var(--pink)!important;text-transform:uppercase;font-weight:850;font-size:11px!important;letter-spacing:.06em;margin-bottom:7px!important}"
        ".dashboard-card,.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:0 2px 10px rgba(20,20,50,.06);margin-bottom:12px}"
        ".dashboard-card h2,.panel h2{margin:0 0 10px;font-size:16px}table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card)}"
        "th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:11px;color:var(--muted);text-transform:uppercase}"
        ".metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.summary-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;box-shadow:0 2px 10px rgba(20,20,50,.05)}"
        ".summary-card .label{color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:850}.summary-card .value{font-size:20px;font-weight:850;margin-top:6px}.summary-card .sub{margin-top:3px;color:var(--muted);font-size:12px}"
        ".status-pass,.trend-up,.positive{color:#1a7f37;font-weight:850}.status-fail,.trend-down,.negative{color:#cf222e;font-weight:850}"
        ".tabs{display:flex;gap:16px;border-bottom:1px solid var(--line);margin:12px 0}.tab{padding:8px 0;font-weight:850;color:var(--ink)}.tab.active{border-bottom:3px solid var(--ink)}"
        ".coverage-subtabs{display:flex;gap:18px;border-bottom:1px solid var(--line);margin:0 -14px 10px;padding:0 14px}.coverage-subtabs span{padding:8px 0;color:var(--muted);font-weight:700}.coverage-subtabs .active{color:var(--ink);border-bottom:3px solid var(--ink)}.coverage-legend{display:flex;gap:8px;margin:0 -14px 10px;padding:0 14px 8px;border-bottom:1px solid var(--line);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.legend-missing,.legend-partial,.legend-covered{padding:2px 10px}.legend-missing{background:#ffebe9}.legend-partial{background:#fff8c5}.legend-covered{background:#dafbe1}"
        ".coverage-actions{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.coverage-button{border-radius:10px;background:var(--green);color:var(--ink);padding:9px 13px;display:inline-block}"
        ".coverage-split{display:grid;grid-template-columns:minmax(360px,.82fr) minmax(0,1.18fr);gap:14px;align-items:start}.coverage-split>.dashboard-card{min-width:0;margin-bottom:0}.coverage-details{max-height:calc(100vh - 160px);overflow:auto;position:sticky;top:14px}"
        ".back-to-top{position:fixed;right:22px;bottom:22px;z-index:20;border-radius:999px;background:var(--green);color:var(--ink);padding:10px 14px;box-shadow:0 6px 18px rgba(20,20,50,.16)}"
        ".files-summary{display:none}.changed-files-table{table-layout:fixed}.changed-files-table th:first-child{width:52%}.changed-files-table th:nth-child(2){width:13%}.changed-files-table th:nth-child(3){width:15%}.changed-files-table th:nth-child(4){width:13%}.changed-files-table th:nth-child(5){width:7%}.changed-files-table td:first-child{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.changed-files-table td{overflow-wrap:anywhere}.changed-files-table tr.selected-file td{background:#f6f8fa;font-weight:850}"
        ".file-diff-report{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:12px 0;background:var(--card)}.file-diff-report h3{padding:10px 12px;margin:0;font-size:14px}"
        ".file-diff-header{display:grid;grid-template-columns:minmax(0,1fr) 52px 76px 76px 44px;gap:8px;align-items:center;padding:9px 10px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:#fff;font-weight:850}"
        ".file-diff-header .file-name{min-width:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.file-diff-header .num{text-align:right}.diff-hunk{background:#f6f8fa;color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;padding:5px 10px;border-bottom:1px solid var(--line)}"
        ".diff-line{display:grid;grid-template-columns:56px 24px minmax(0,1fr);align-items:start;min-height:24px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;border-bottom:1px solid #eef1f4}.diff-line-number{color:#57606a;text-align:right;padding:4px 8px;border-right:1px solid var(--line);background:#f6f8fa}.diff-marker{text-align:center;padding:4px 0;color:#57606a}.diff-code{display:block;min-width:0;white-space:pre-wrap;padding:4px 8px;overflow-wrap:anywhere;word-break:break-word}.diff-line-covered{background:#dafbe1}.diff-line-missing{background:#ffebe9}.diff-line-context{background:#fff}.diff-line-covered .diff-marker{color:#1a7f37;font-weight:850}.diff-line-missing .diff-marker{color:#cf222e;font-weight:850}"
        "button,.configure-link{border:0;border-radius:10px;background:var(--green);color:var(--ink);font-weight:850;padding:9px 13px;cursor:pointer;display:inline-block}"
        ".chip.disabled{opacity:.65;background:var(--soft);cursor:not-allowed;border:1px solid var(--line);border-radius:999px;padding:6px 10px;color:var(--muted)}"
        "input,textarea{border:1px solid #cfd6e6;border-radius:8px;padding:10px 12px;font:inherit}label{display:grid;gap:8px;margin-bottom:14px}"
        "@media(max-width:900px){.coverage-split{grid-template-columns:1fr}.coverage-details{max-height:none;overflow:visible;position:static}}"
        "@media(max-width:760px){.app-shell{padding:14px}.app-header{display:block}.app-nav{margin-top:12px}.dashboard-hero{padding:18px}.metric-grid,.files-summary{grid-template-columns:1fr}table{font-size:12px}.back-to-top{right:14px;bottom:14px}}"
        "</style></head><body>" + body + "</body></html>"
    )


def report_app_header() -> str:
    return (
        '<header class="app-header">'
        '<a class="app-brand" href="/"><span class="app-brand-mark">C</span><span>Covivy</span></a>'
        '<nav class="app-nav"><a class="nav-chip" href="/dashboard">Dashboard</a></nav>'
        "</header>"
    )


def metric_card(label: str, value: str, sub: str = "", class_name: str = "") -> str:
    return (
        '<section class="summary-card {class_name}"><div class="label">{label}</div>'
        '<div class="value">{value}</div><div class="sub">{sub}</div></section>'
    ).format(class_name=class_name, label=escape(label), value=value, sub=sub)


def pr_header(repository: Repository, pull: PullRequest) -> str:
    return (
        '<div><p class="eyebrow">Coverage report</p>'
        "<h1>{repo} · PR #{number}: {title}</h1>"
        "<p>{state}</p></div>"
    ).format(
        repo=escape(repository.full_name),
        number=pull.github_pr_number,
        title=escape(pull.title or ""),
        state=escape(pull.state),
    )


def summary_metrics_html(
    annotation: Optional[PrAnnotation],
    report: Optional[CoverageReportRow],
    base_report: Optional[CoverageReportRow],
    target: float,
) -> str:
    if report is None:
        return '<div class="panel">No coverage report for the current PR yet.</div>'
    patch_value = "No patch data"
    patch_sub = ""
    patch_class = ""
    if annotation is not None:
        patch_passed = annotation.patch_line_rate >= target
        patch_value = "%s %s" % (percent(annotation.patch_line_rate), status_icon(patch_passed))
        patch_sub = "%s / %s changed lines" % (
            annotation.patch_covered_lines,
            annotation.patch_total_lines,
        )
        patch_class = "pass" if patch_passed else "fail"
    project_delta = report.line_rate - base_report.line_rate if base_report is not None else None
    project_delta_class = (
        "positive" if project_delta is not None and project_delta >= 0 else "negative"
    )
    return ('<div class="metric-grid">{patch_card}{project_card}{change_card}</div>').format(
        patch_card=metric_card("Changed lines", patch_value, patch_sub, patch_class),
        project_card=metric_card(
            "Project coverage",
            "%s %s"
            % (
                percent(report.line_rate),
                trend_icon(report.line_rate, base_report.line_rate if base_report else None),
            ),
            "%s / %s covered lines" % (report.covered_lines, report.total_lines),
        ),
        change_card=metric_card(
            "Coverage change",
            '<span class="{class_name}">{value}</span>'.format(
                class_name=project_delta_class,
                value=escape(signed_percent(project_delta)),
            ),
            "Compared with base report" if base_report is not None else "Base report unavailable",
        ),
    )


def file_diff_anchor(file: PrFileAnnotation) -> str:
    return "file-coverage-%s" % file.id


CONTEXT_LINES = 10
MAX_RENDERED_CONTEXT_LINES = 120


def semantic_context_ranges(
    path: str, source: str, changed_lines: set[int], context: int = CONTEXT_LINES
) -> list[tuple[int, int]]:
    if not changed_lines:
        return []
    source_lines = source.splitlines()
    max_line = len(source_lines)
    if max_line == 0:
        return []
    windows = {
        line: (max(1, line - context), min(max_line, line + context))
        for line in changed_lines
        if line <= max_line
    }
    ranges = list(windows.values())
    if path.endswith(".py"):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            nodes = []
            for node in ast.walk(tree):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start is not None and end is not None:
                    nodes.append((start, end))
            for line, (window_start, window_end) in windows.items():
                containing_nodes = [
                    (start, end)
                    for start, end in nodes
                    if start <= line <= end
                    and start >= window_start
                    and end <= window_end
                ]
                if containing_nodes:
                    ranges.append(max(containing_nodes, key=lambda item: item[1] - item[0]))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def capped_context_ranges(
    path: str,
    source: str,
    line_rows: list[PrFileLineAnnotation],
    context: int = CONTEXT_LINES,
    max_rendered_lines: int = MAX_RENDERED_CONTEXT_LINES,
) -> list[tuple[int, int]]:
    changed_lines = {line.line_number for line in line_rows}
    ranges = semantic_context_ranges(path, source, changed_lines, context)
    if sum(end - start + 1 for start, end in ranges) <= max_rendered_lines:
        return ranges

    source_line_count = len(source.splitlines())
    if source_line_count == 0:
        return []
    missing_lines = [line.line_number for line in line_rows if not line.covered]
    covered_lines = [line.line_number for line in line_rows if line.covered]
    anchors = sorted(missing_lines) + sorted(covered_lines)
    capped_ranges = []
    for line in anchors:
        if line > source_line_count:
            continue
        start = max(1, line - context)
        end = min(source_line_count, line + context)
        candidate_ranges = capped_ranges + [(start, end)]
        candidate_ranges.sort()
        merged = []
        for candidate_start, candidate_end in candidate_ranges:
            if not merged or candidate_start > merged[-1][1] + 1:
                merged.append((candidate_start, candidate_end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], candidate_end))
        rendered = sum(candidate_end - candidate_start + 1 for candidate_start, candidate_end in merged)
        if rendered > max_rendered_lines:
            break
        capped_ranges = merged
    return capped_ranges


def file_diff_html(
    file: PrFileAnnotation, line_rows: list[PrFileLineAnnotation], target: float
) -> str:
    missing = file.patch_total_lines - file.patch_covered_lines
    line_parts = []
    changed_by_line = {line.line_number: line for line in line_rows}
    source_ranges = (
        capped_context_ranges(file.path, file.source_content, line_rows)
        if file.source_content
        else []
    )
    if file.source_content and source_ranges:
        source_lines = file.source_content.splitlines()
        for range_index, (start, end) in enumerate(source_ranges):
            if range_index:
                line_parts.append('<div class="diff-hunk">...</div>')
            for index in range(start, end + 1):
                content = source_lines[index - 1] if index <= len(source_lines) else ""
                changed_line = changed_by_line.get(index)
                class_name = "diff-line-context"
                mark = ""
                if changed_line is not None:
                    class_name = (
                        "diff-line-covered" if changed_line.covered else "diff-line-missing"
                    )
                    mark = "+" if changed_line.covered else "!"
                line_parts.append(
                    '<div class="diff-line {class_name}">'
                    '<div class="diff-line-number">{line_number}</div>'
                    '<div class="diff-marker">{mark}</div>'
                    '<code class="diff-code">{content}</code></div>'.format(
                        class_name=class_name,
                        line_number=index,
                        mark=mark,
                        content=escape(content),
                    )
                )
    else:
        for line in line_rows:
            line_parts.append(
                '<div class="diff-line {class_name}">'
                '<div class="diff-line-number">{line_number}</div>'
                '<div class="diff-marker">{mark}</div>'
                '<code class="diff-code">{content}</code></div>'.format(
                    class_name="diff-line-covered" if line.covered else "diff-line-missing",
                    line_number=line.line_number,
                    mark="+" if line.covered else "!",
                    content=escape(
                        line.line_content
                        if line.line_content is not None
                        else "Line %s" % line.line_number
                    ),
                )
            )
    if not line_parts:
        line_parts.append(
            '<div class="diff-line"><div></div><div></div><code class="diff-code">No changed line coverage available.</code></div>'
        )
    return (
        '<section id="{anchor}" class="file-diff-report">'
        "<h3>{path} line coverage</h3>"
        '<div class="file-diff-header">'
        '<div class="file-name">{path}</div>'
        '<div class="num">{missing}</div>'
        '<div class="num">{patch}</div>'
        '<div class="num">{project}</div>'
        '<div class="num">{change}</div>'
        "</div>"
        '<div class="diff-hunk">{hunk_label}</div>'
        "{lines}</section>"
    ).format(
        anchor=file_diff_anchor(file),
        path=escape(file.path),
        missing=missing,
        patch=percent(file.patch_line_rate),
        project=percent(file.patch_line_rate),
        change=status_icon(file.patch_line_rate >= target),
        hunk_label=(
            "Changed lines with semantic context"
            if source_ranges
            else "Changed lines in this file"
        ),
        lines="".join(line_parts),
    )


def render_pull_summary_page(
    repository: Repository,
    pull: PullRequest,
    report: Optional[CoverageReportRow],
    base_report: Optional[CoverageReportRow],
    annotation: Optional[PrAnnotation],
    target: float,
) -> str:
    coverage_html = summary_metrics_html(annotation, report, base_report, target)
    note = ""
    if report is not None and pull.base_sha and base_report is None:
        note = '<div class="panel">Base coverage report unavailable for project trend.</div>'
    status = "No patch coverage computed yet."
    if annotation is not None:
        status = "Status: %s. Patch target: %.2f%%." % (annotation.status, target * 100)
    body = (
        '<main id="top" class="app-shell">'
        "{app_header}"
        '<section class="dashboard-hero">{header}</section>'
        '<nav class="tabs"><span class="tab active">Summary</span>'
        '<a class="tab" href="/repos/{owner}/{repo}/pulls/{number}/files">Changed files</a></nav>'
        "{coverage}{note}"
        '<section class="dashboard-card"><h2>Coverage summary</h2><p>{status}</p>'
        '<div class="coverage-actions"><a class="coverage-button" href="/repos/{owner}/{repo}/pulls/{number}/files">'
        "View changed file details</a></div></section>"
        "</main>"
    ).format(
        app_header=report_app_header(),
        header=pr_header(repository, pull),
        owner=escape(repository.owner),
        repo=escape(repository.name),
        number=pull.github_pr_number,
        coverage=coverage_html,
        note=note,
        status=escape(status),
    )
    return app_page_html("PR #%s coverage" % pull.github_pr_number, body)


def render_pull_files_page(
    repository: Repository,
    pull: PullRequest,
    report: Optional[CoverageReportRow],
    base_report: Optional[CoverageReportRow],
    annotation: Optional[PrAnnotation],
    file_line_rows: list[tuple[PrFileAnnotation, list[PrFileLineAnnotation]]],
    target: float,
    selected_path: Optional[str] = None,
) -> str:
    summary_html = summary_metrics_html(annotation, report, base_report, target)
    row_parts = []
    file_count = 0
    failing_count = 0
    missing_count = 0
    selected: Optional[tuple[PrFileAnnotation, list[PrFileLineAnnotation]]] = None
    for file, line_rows in file_line_rows:
        if selected is None or file.path == selected_path:
            selected = (file, line_rows)
        file_count += 1
        missing_for_file = file.patch_total_lines - file.patch_covered_lines
        missing_count += missing_for_file
        if file.patch_line_rate < target:
            failing_count += 1
        row_class = "selected-file" if file.path == selected_path else ""
        if selected_path is None and selected is not None and selected[0].path == file.path:
            row_class = "selected-file"
        row_parts.append(
            '<tr class="{row_class}"><td><a href="/repos/{owner}/{repo}/pulls/{number}/files/{path_href}">› {path}</a></td><td>{lines}</td><td>{coverage} {icon}</td>'
            "<td>{missing}</td><td>{status}</td></tr>".format(
                row_class=row_class,
                owner=escape(repository.owner),
                repo=escape(repository.name),
                number=pull.github_pr_number,
                path_href=escape(file.path),
                path=escape(file.path),
                lines="%s / %s" % (file.patch_covered_lines, file.patch_total_lines),
                coverage=percent(file.patch_line_rate),
                icon=status_icon(file.patch_line_rate >= target),
                missing=missing_for_file,
                status="passed" if file.patch_line_rate >= target else "failed",
            )
        )
    rows = (
        "\n".join(row_parts) or '<tr><td colspan="5">No changed file coverage available.</td></tr>'
    )
    diff_sections = (
        file_diff_html(selected[0], selected[1], target)
        if selected is not None
        else "<p>No changed file coverage available.</p>"
    )
    passing_count = max(file_count - failing_count, 0)
    files_summary = ('<div class="files-summary">{files}{passing}{failing}{missing}</div>').format(
        files=metric_card("Files changed", str(file_count)),
        passing=metric_card("Files passing target", str(passing_count), class_name="pass"),
        failing=metric_card("Files failing target", str(failing_count), class_name="fail"),
        missing=metric_card("Missing changed lines", str(missing_count), class_name="fail"),
    )
    body = (
        '<main id="top" class="app-shell">'
        "{app_header}"
        '<section class="dashboard-hero">{header}</section>'
        '<nav class="tabs"><a class="tab" href="/repos/{owner}/{repo}/pulls/{number}">Summary</a>'
        '<span class="tab active">Changed files</span></nav>'
        '{summary}<div class="coverage-split"><section class="dashboard-card"><h2>Changed file coverage</h2>'
        '<nav class="coverage-subtabs"><span class="active">Files changed<sup>{file_count}</sup></span>'
        "<span>Indirect changes<sup>0</sup></span><span>Commits<sup>1</sup></span>"
        "<span>Flags<sup>0</sup></span><span>Components<sup>0</sup></span></nav>"
        '<div class="coverage-legend"><span class="legend-missing">Uncovered !</span>'
        '<span class="legend-partial">Partial !</span><span class="legend-covered">Covered</span></div>{files_summary}'
        '<table class="changed-files-table"><tr><th>Name</th><th>Changed lines</th>'
        "<th>Patch %</th><th>Missed lines</th><th></th></tr>{rows}</table></section>"
        '<section class="dashboard-card coverage-details"><h2>File coverage details</h2>{diff_sections}</section></div>'
        '<a class="back-to-top" href="#top">Back to top</a>'
        "</main>"
    ).format(
        app_header=report_app_header(),
        header=pr_header(repository, pull),
        owner=escape(repository.owner),
        repo=escape(repository.name),
        number=pull.github_pr_number,
        file_count=file_count,
        summary=summary_html,
        files_summary=files_summary,
        rows=rows,
        diff_sections=diff_sections,
    )
    return app_page_html("PR #%s changed files" % pull.github_pr_number, body)
