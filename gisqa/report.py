"""CSV, JSON and HTML reports."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Union

from .engine import QAResult

ISSUE_COLUMNS = ["rule", "severity", "oid", "field", "value", "message"]

RULE_HELP = {
    "null_geometry": "Feature has no shape. Redraw it or delete the record.",
    "empty_geometry": "Shape has no vertices. Redraw it or delete the record.",
    "invalid_geometry": (
        "Self-intersections, bad ring order or duplicate vertices. "
        "Run Repair Geometry (ArcGIS) or make_valid (Shapely)."
    ),
    "sliver_polygon": "Tiny polygon, often left over from overlay or digitizing. Merge or delete.",
    "short_line": "Very short line, often a digitizing artifact.",
    "outside_extent": "Outside the expected area: wrong coordinate system, swapped coordinates, or a stray vertex.",
    "duplicate_geometry": "Identical shape already exists. Usually a duplicate load.",
    "duplicate_key": "The ID field should be unique.",
    "required_field": "A required value is missing.",
    "pattern": "Value isn't in the expected format (e.g. 13-digit folio, 5-digit ZIP).",
    "allowed_values": "Value isn't in the allowed list or coded domain.",
    "range": "Number outside the expected range.",
    "future_date": "Date is in the future or isn't a date.",
}


def write_reports(result: QAResult, folder: Union[str, Path], basename: str = "qa_report") -> Dict[str, Path]:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": out / f"{basename}_issues.csv",
        "json": out / f"{basename}_summary.json",
        "html": out / f"{basename}.html",
    }

    with open(paths["csv"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ISSUE_COLUMNS)
        writer.writeheader()
        writer.writerows(issue.as_row() for issue in result.issues)

    paths["json"].write_text(json.dumps(result.summary(), indent=2), encoding="utf-8")
    paths["html"].write_text(render_html(result), encoding="utf-8")
    return paths


def render_html(result: QAResult, max_rows: int = 500) -> str:
    summary = result.summary()
    status = "PASS" if result.error_count == 0 else "FAIL"
    color = "#1b7f3b" if status == "PASS" else "#b42318"
    esc = html.escape

    rule_rows = (
        "\n".join(
            f"<tr><td><code>{esc(rule)}</code></td><td class='n'>{count}</td>"
            f"<td>{esc(RULE_HELP.get(rule, ''))}</td></tr>"
            for rule, count in result.counts_by_rule().items()
        )
        or "<tr><td colspan='3'>No issues found.</td></tr>"
    )

    issue_rows = "\n".join(
        "<tr>" + "".join(f"<td>{esc(str(v))}</td>" for v in issue.as_row().values()) + "</tr>"
        for issue in result.issues[:max_rows]
    )
    truncated = (
        (f"<p>Showing the first {max_rows} of {len(result.issues)} issues. The CSV has all of them.</p>")
        if len(result.issues) > max_rows
        else ""
    )

    header = "".join(f"<th>{c}</th>" for c in ["Rule", "Severity", "OID", "Field", "Value", "Message"])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>QA report: {esc(result.config_name)}</title>
<style>
body{{font-family:Segoe UI,Roboto,Arial,sans-serif;margin:24px;color:#1f2933;max-width:1100px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-bottom:24px}}
th,td{{border-bottom:1px solid #d9e2ec;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}} .n{{text-align:right}} .status{{color:{color};font-weight:700}}
</style></head><body>
<h1>{esc(result.config_name)}</h1>
<p class="status">{status}</p>
<p>{datetime.now():%Y-%m-%d %H:%M} · {summary["records_checked"]} records checked ·
{summary["records_with_issues"]} with issues · pass rate {result.pass_rate:.1%} ·
{result.error_count} errors · {result.warning_count} warnings</p>
<h2>Issues by rule</h2>
<table><thead><tr><th>Rule</th><th class="n">Count</th><th>What it means</th></tr></thead>
<tbody>{rule_rows}</tbody></table>
<h2>Issues</h2>{truncated}
<table><thead><tr>{header}</tr></thead>
<tbody>{issue_rows}</tbody></table>
</body></html>
"""
