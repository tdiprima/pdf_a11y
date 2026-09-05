"""Per-file remediation pipeline.

Two stages, because the two libraries are each better at one half of the job:

1. PyMuPDF places link annotations, because it can resolve text to rectangles.
2. pikepdf writes metadata, link descriptions and the structure tree, because
   it can edit content streams and object graphs directly.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pikepdf

from .audit import AuditResult, audit_file
from .config import Config
from .extract import extract_lines, filename_to_title, guess_title
from .link_fix import (
    add_link_annotations,
    apply_link_alt_text,
    set_annotation_tab_order,
)
from .metadata_fix import apply_metadata_fixes, declare_pdfua_conformance
from .tag_fix import tag_document

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


@dataclass
class RemediationResult:
    """What happened to one file."""

    source: str
    output: str | None = None
    changes: dict[str, object] = field(default_factory=dict)
    manual_work: list[str] = field(default_factory=list)
    error: str | None = None
    audit_before: AuditResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class UnreadablePdf(Exception):
    """Raised when a candidate file is not a usable PDF."""


def validate_source(path: Path, max_bytes: int) -> None:
    """Reject anything that is not a plausible PDF before opening it."""
    if not path.is_file():
        raise UnreadablePdf(f"not a regular file: {path}")

    size = path.stat().st_size
    if size == 0:
        raise UnreadablePdf(f"file is empty: {path}")
    if size > max_bytes:
        raise UnreadablePdf(f"file is {size} bytes, over the {max_bytes} byte limit")

    with path.open("rb") as handle:
        if handle.read(len(PDF_MAGIC)) != PDF_MAGIC:
            raise UnreadablePdf(f"missing %PDF- header: {path}")


def _resolve_output(source: Path, output_dir: Path, input_root: Path) -> Path:
    """Mirror the input tree under the output directory."""
    try:
        relative = source.relative_to(input_root)
    except ValueError:
        relative = Path(source.name)
    destination = output_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _collect_manual_work(audit: AuditResult, tag_counts: dict[str, int]) -> list[str]:
    """List what a human still has to do after the automated pass."""
    remaining: list[str] = []

    codes = {finding.code for finding in audit.findings}
    if "images_need_alt" in codes:
        remaining.append("Write alternative text for images; this cannot be generated.")
    if "no_text_layer" in codes:
        remaining.append("Run OCR: one or more pages have no text layer.")
    if tag_counts.get("skipped_pages"):
        remaining.append(
            f"{tag_counts['skipped_pages']} page(s) could not be tagged automatically."
        )
    if tag_counts.get("tagged_pages"):
        remaining.append(
            "Spot-check the generated heading levels and reading order in a validator."
        )
    remaining.append("Confirm tables, if any, have header cells; this tool cannot infer them.")
    return remaining


def remediate_file(
    source: Path,
    output_dir: Path,
    input_root: Path,
    config: Config,
    enable_tagging: bool,
    title_override: str | None = None,
) -> RemediationResult:
    """Repair one PDF, writing the result into the output directory."""
    result = RemediationResult(source=str(source))

    try:
        validate_source(source, config.max_file_bytes)
        result.audit_before = audit_file(source)
        if result.audit_before.error:
            raise UnreadablePdf(result.audit_before.error)

        destination = _resolve_output(source, output_dir, input_root)

        with fitz.open(source) as doc:
            pages_lines = extract_lines(doc)
            links_added, unresolved = add_link_annotations(doc)
            title = title_override or guess_title(
                pages_lines, filename_to_title(source.stem)
            )
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                staged = Path(handle.name)
            doc.save(str(staged), garbage=3, deflate=True)

        try:
            with pikepdf.open(staged) as pdf:
                metadata_changes = apply_metadata_fixes(pdf, config.lang, title)
                alt_texts = apply_link_alt_text(pdf)
                tab_order_pages = set_annotation_tab_order(pdf)

                tag_counts = {"tagged_pages": 0, "skipped_pages": len(pdf.pages)}
                if enable_tagging:
                    tag_counts = tag_document(pdf, pages_lines, config.lang)

                # The conformance claim is only honest when the whole document
                # was tagged; a partially tagged file must not assert PDF/UA.
                fully_tagged = (
                    enable_tagging
                    and tag_counts["tagged_pages"] == len(pdf.pages)
                    and tag_counts["skipped_pages"] == 0
                )
                if fully_tagged:
                    declare_pdfua_conformance(pdf)

                pdf.save(str(destination), linearize=False)
        finally:
            staged.unlink(missing_ok=True)

        result.output = str(destination)
        result.changes = {
            "title": title,
            "language": config.lang,
            "links_added": links_added,
            "link_descriptions_added": alt_texts,
            "tab_order_pages": tab_order_pages,
            "declared_pdfua": fully_tagged,
            "unresolved_addresses": unresolved,
            **metadata_changes,
            **tag_counts,
        }
        result.manual_work = _collect_manual_work(result.audit_before, tag_counts)

    except (UnreadablePdf, pikepdf.PdfError, RuntimeError, ValueError, OSError) as error:
        result.error = f"{type(error).__name__}: {error}"
        logger.error(
            "remediation_failed",
            extra={"source": str(source), "reason": result.error},
        )

    return result
