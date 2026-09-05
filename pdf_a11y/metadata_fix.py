"""Document-level metadata fixes: language, title, and title display."""

from __future__ import annotations

import logging

import pikepdf
from pikepdf import Dictionary, Name, String

logger = logging.getLogger(__name__)


def set_language(pdf: pikepdf.Pdf, lang: str) -> bool:
    """Set the catalog /Lang so assistive technology picks the right voice."""
    current = pdf.Root.get("/Lang")
    if current is not None and str(current) == lang:
        return False
    pdf.Root.Lang = String(lang)
    return True


def set_display_doc_title(pdf: pikepdf.Pdf) -> bool:
    """Make readers announce the document title instead of the filename."""
    preferences = pdf.Root.get("/ViewerPreferences")
    if preferences is None:
        pdf.Root.ViewerPreferences = pdf.make_indirect(
            Dictionary(DisplayDocTitle=True)
        )
        return True
    if bool(preferences.get("/DisplayDocTitle", False)):
        return False
    preferences.DisplayDocTitle = True
    return True


def set_title(pdf: pikepdf.Pdf, title: str) -> bool:
    """Write the title to both the XMP metadata and the document info dict.

    Readers prefer XMP; older tools read the info dictionary. Writing one and
    not the other leaves the two disagreeing, which validators flag.
    """
    if not title.strip():
        return False

    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=True) as meta:
        if meta.get("dc:title") == title:
            existing_info = pdf.docinfo.get("/Title")
            if existing_info is not None and str(existing_info) == title:
                return False
        meta["dc:title"] = title

    pdf.docinfo[Name.Title] = String(title)
    return True


def apply_metadata_fixes(pdf: pikepdf.Pdf, lang: str, title: str) -> dict[str, bool]:
    """Apply every document-level fix, reporting which ones changed anything."""
    return {
        "lang": set_language(pdf, lang),
        "title": set_title(pdf, title),
        "display_doc_title": set_display_doc_title(pdf),
    }


def declare_pdfua_conformance(pdf: pikepdf.Pdf, part: int = 1) -> bool:
    """Add the PDF/UA identification schema to the XMP metadata.

    Only call this once the document really is tagged. The identifier is a
    claim of conformance, and a false claim is worse than none: assistive
    technology and validators both take it at face value.
    """
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
        if meta.get("pdfuaid:part") == str(part):
            return False
        meta["pdfuaid:part"] = str(part)
    return True
