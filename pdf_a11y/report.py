"""Batch reporting: JSON for machines, CSV for triage in a spreadsheet."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .audit import AuditResult
from .pipeline import RemediationResult

_AUDIT_COLUMNS = ["path", "pages", "blockers", "warnings", "codes", "error"]
_REMEDIATION_COLUMNS = [
    "source",
    "output",
    "blockers_before",
    "links_added",
    "tagged_pages",
    "skipped_pages",
    "manual_work",
    "error",
]


def _audit_row(result: AuditResult) -> dict[str, object]:
    return {
        "path": result.path,
        "pages": result.pages,
        "blockers": result.blockers,
        "warnings": result.warnings,
        "codes": ";".join(finding.code for finding in result.findings),
        "error": result.error or "",
    }


def _remediation_row(result: RemediationResult) -> dict[str, object]:
    changes = result.changes
    return {
        "source": result.source,
        "output": result.output or "",
        "blockers_before": result.audit_before.blockers if result.audit_before else "",
        "links_added": changes.get("links_added", ""),
        "tagged_pages": changes.get("tagged_pages", ""),
        "skipped_pages": changes.get("skipped_pages", ""),
        "manual_work": " | ".join(result.manual_work),
        "error": result.error or "",
    }


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    """Write a report as CSV, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    """Write a report as indented JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def write_audit_report(directory: Path, results: Iterable[AuditResult]) -> None:
    """Emit audit.json and audit.csv for a batch of audited files."""
    collected = list(results)
    write_json(directory / "audit.json", [asdict(item) for item in collected])
    write_csv(
        directory / "audit.csv",
        [_audit_row(item) for item in collected],
        _AUDIT_COLUMNS,
    )


def write_remediation_report(
    directory: Path, results: Iterable[RemediationResult]
) -> None:
    """Emit remediation.json and remediation.csv for a batch of fixed files."""
    collected = list(results)
    write_json(directory / "remediation.json", [asdict(item) for item in collected])
    write_csv(
        directory / "remediation.csv",
        [_remediation_row(item) for item in collected],
        _REMEDIATION_COLUMNS,
    )
