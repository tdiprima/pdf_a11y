"""Read-only accessibility audit. Reports findings, changes nothing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pikepdf

from .link_fix import place_addresses

# Severity ranks used to sort a batch report by how much work each file needs.
BLOCKER = "blocker"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One accessibility defect."""

    code: str
    severity: str
    criterion: str
    detail: str


@dataclass
class AuditResult:
    """Everything the audit learned about one file."""

    path: str
    pages: int = 0
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None

    @property
    def blockers(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == BLOCKER)

    @property
    def warnings(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == WARNING)


def _check_structure(pdf: pikepdf.Pdf) -> list[Finding]:
    findings: list[Finding] = []
    root = pdf.Root

    if root.get("/StructTreeRoot") is None:
        findings.append(
            Finding(
                "untagged",
                BLOCKER,
                "WCAG 1.3.1 (A)",
                "No /StructTreeRoot: the document has no headings, lists or reading order.",
            )
        )
    mark_info = root.get("/MarkInfo")
    if mark_info is None or not bool(mark_info.get("/Marked", False)):
        findings.append(
            Finding(
                "not_marked",
                BLOCKER,
                "PDF/UA (ISO 14289-1)",
                "/MarkInfo /Marked is absent or false.",
            )
        )
    if root.get("/Lang") is None:
        findings.append(
            Finding(
                "no_lang",
                BLOCKER,
                "WCAG 3.1.1 (A)",
                "No catalog /Lang: assistive technology cannot pick a voice.",
            )
        )

    preferences = root.get("/ViewerPreferences")
    if preferences is None or not bool(preferences.get("/DisplayDocTitle", False)):
        findings.append(
            Finding(
                "no_display_doc_title",
                BLOCKER,
                "WCAG 2.4.2 (A)",
                "/ViewerPreferences /DisplayDocTitle is not true; readers announce the filename.",
            )
        )
    return findings


def _check_title(pdf: pikepdf.Pdf, path: Path) -> list[Finding]:
    title = pdf.docinfo.get("/Title")
    text = str(title).strip() if title is not None else ""

    if not text:
        return [
            Finding("no_title", BLOCKER, "WCAG 2.4.2 (A)", "Document has no /Title.")
        ]
    if text == path.stem:
        return [
            Finding(
                "filename_title",
                WARNING,
                "WCAG 2.4.2 (A)",
                f"Title is the filename ({text!r}), not a human-readable title.",
            )
        ]
    return []


def _check_links(doc: fitz.Document) -> list[Finding]:
    plain_text_addresses = 0
    unlocated_addresses = 0
    undescribed_links = 0

    for page in doc:
        undescribed_links += len(page.get_links())
        for placement in place_addresses(page):
            if not placement.located:
                unlocated_addresses += 1
            elif placement.unlinked_rects:
                plain_text_addresses += 1

    findings: list[Finding] = []
    if plain_text_addresses:
        findings.append(
            Finding(
                "unlinked_urls",
                BLOCKER,
                "WCAG 2.4.4 (A)",
                f"{plain_text_addresses} URL or email address(es) are plain text, not links.",
            )
        )
    if unlocated_addresses:
        findings.append(
            Finding(
                "unlocated_urls",
                WARNING,
                "WCAG 2.4.4 (A)",
                f"{unlocated_addresses} address(es) appear in the text but could not be "
                "located on the page, usually because they wrap; check them by hand.",
            )
        )
    if undescribed_links:
        findings.append(
            Finding(
                "raw_url_link_text",
                WARNING,
                "WCAG 2.4.4 (A)",
                f"{undescribed_links} existing link(s) should be checked for descriptive text.",
            )
        )
    return findings


def _check_images(doc: fitz.Document) -> list[Finding]:
    images = sum(len(page.get_images(full=True)) for page in doc)
    if not images:
        return []
    return [
        Finding(
            "images_need_alt",
            BLOCKER,
            "WCAG 1.1.1 (A)",
            f"{images} image(s) need human-written alternative text.",
        )
    ]


def _check_text_layer(doc: fitz.Document) -> list[Finding]:
    empty_pages = sum(1 for page in doc if not page.get_text().strip())
    if not empty_pages:
        return []
    return [
        Finding(
            "no_text_layer",
            BLOCKER,
            "WCAG 1.4.5 (AA)",
            f"{empty_pages} page(s) have no extractable text; the file likely needs OCR.",
        )
    ]


def audit_file(path: Path) -> AuditResult:
    """Run every read-only check against one PDF."""
    result = AuditResult(path=str(path))
    try:
        with pikepdf.open(path) as pdf, fitz.open(path) as doc:
            result.pages = len(pdf.pages)
            result.findings.extend(_check_structure(pdf))
            result.findings.extend(_check_title(pdf, path))
            result.findings.extend(_check_text_layer(doc))
            result.findings.extend(_check_links(doc))
            result.findings.extend(_check_images(doc))
    except (pikepdf.PdfError, RuntimeError, ValueError, OSError) as error:
        result.error = f"{type(error).__name__}: {error}"
    return result
