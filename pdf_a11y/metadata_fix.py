"""Document-level metadata fixes: language, title, and title display."""

from __future__ import annotations

import logging

import pikepdf
from pikepdf import Dictionary, Name, String

logger = logging.getLogger(__name__)


def set_language(pdf: pikepdf.Pdf, lang: str, overwrite: bool = False) -> bool:
    """Set a missing catalog /Lang, or replace it when explicitly requested."""
    current = pdf.Root.get("/Lang")
    if current is not None and str(current).strip():
        if not overwrite or str(current) == lang:
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


def set_title(pdf: pikepdf.Pdf, title: str, overwrite: bool = False) -> bool:
    """Write the title to both the XMP metadata and the document info dict.

    Readers prefer XMP; older tools read the info dictionary. Writing one and
    not the other leaves the two disagreeing, which validators flag.
    """
    if not title.strip():
        return False

    existing_info = pdf.docinfo.get("/Title")
    info_title = str(existing_info).strip() if existing_info is not None else ""

    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=True) as meta:
        metadata_title = str(meta.get("dc:title") or "").strip()
        effective_title = title if overwrite else metadata_title or info_title or title
        if metadata_title == effective_title and info_title == effective_title:
            return False
        meta["dc:title"] = effective_title

    pdf.docinfo[Name.Title] = String(effective_title)
    return True


def apply_metadata_fixes(
    pdf: pikepdf.Pdf,
    lang: str,
    title: str,
    *,
    overwrite_language: bool = False,
    overwrite_title: bool = False,
) -> dict[str, bool]:
    """Apply every document-level fix, reporting which ones changed anything."""
    return {
        "lang": set_language(pdf, lang, overwrite_language),
        "title_changed": set_title(pdf, title, overwrite_title),
        "display_doc_title": set_display_doc_title(pdf),
    }
