"""Turn plain-text URLs and email addresses into real link annotations."""

from __future__ import annotations

import logging
import re

import fitz
import pikepdf
from pikepdf import Name, String

logger = logging.getLogger(__name__)

# Trailing sentence punctuation is not part of the address.
_TRAILING_PUNCTUATION = ".,;:)]}>'\"" 

_URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# PyMuPDF returns one rect per line a match spans. A match broken across a
# line break yields more than one; each gets its own annotation.
MAX_RECTS_PER_MATCH = 4


def _clean(candidate: str) -> str:
    return candidate.rstrip(_TRAILING_PUNCTUATION)


def _to_uri(candidate: str, is_email: bool) -> str:
    if is_email:
        return f"mailto:{candidate}"
    if candidate.lower().startswith("www."):
        return f"https://{candidate}"
    return candidate


def _describe(candidate: str, is_email: bool) -> str:
    """Alt text a screen reader announces instead of spelling out the URL."""
    if is_email:
        return f"Email {candidate}"
    host = re.sub(r"^https?://", "", candidate, flags=re.IGNORECASE).split("/")[0]
    return f"Link to {host}"


def find_addresses(text: str) -> list[tuple[str, bool]]:
    """Return (address, is_email) pairs found in a block of text."""
    found: list[tuple[str, bool]] = []
    seen: set[str] = set()

    for match in _EMAIL_PATTERN.finditer(text):
        candidate = _clean(match.group(0))
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append((candidate, True))

    for match in _URL_PATTERN.finditer(text):
        candidate = _clean(match.group(0))
        if not candidate or candidate in seen:
            continue
        # An email inside a URL match is already handled above.
        if "@" in candidate and not candidate.lower().startswith(("http", "www")):
            continue
        seen.add(candidate)
        found.append((candidate, False))

    return found


def _existing_link_rects(page: fitz.Page) -> list[fitz.Rect]:
    return [fitz.Rect(link["from"]) for link in page.get_links()]


def _already_linked(rect: fitz.Rect, existing: list[fitz.Rect]) -> bool:
    """True when an annotation already covers most of this rectangle."""
    for other in existing:
        overlap = rect & other
        if not overlap.is_empty and overlap.get_area() > rect.get_area() * 0.5:
            return True
    return False


def add_link_annotations(doc: fitz.Document) -> tuple[int, list[str]]:
    """Add URI annotations for addresses that are currently plain text.

    Returns the number of annotations added and the addresses that could not
    be located on the page, which usually means the text wrapped mid-address.
    """
    added = 0
    unresolved: list[str] = []

    for page in doc:
        text = page.get_text()
        if not text.strip():
            continue

        existing = _existing_link_rects(page)

        for address, is_email in find_addresses(text):
            rects = page.search_for(address, quads=False)
            if not rects:
                unresolved.append(address)
                continue

            for rect in rects[:MAX_RECTS_PER_MATCH]:
                if _already_linked(rect, existing):
                    continue
                page.insert_link(
                    {
                        "kind": fitz.LINK_URI,
                        "uri": _to_uri(address, is_email),
                        "from": rect,
                    }
                )
                existing.append(rect)
                added += 1

    return added, unresolved


def _describe_uri(uri: str) -> str:
    """Alt text for an existing annotation, derived from its target."""
    if uri.lower().startswith("mailto:"):
        return _describe(uri[len("mailto:") :], True)
    return _describe(uri, False)


def apply_link_alt_text(pdf: pikepdf.Pdf) -> int:
    """Give every link annotation a /Contents description.

    PyMuPDF writes the action but not the description, and a link with no
    description is announced as its raw URL, character by character.
    """
    updated = 0
    for page in pdf.pages:
        annotations = page.obj.get("/Annots")
        if annotations is None:
            continue
        for annotation in annotations:
            if annotation.get("/Subtype") != Name.Link:
                continue
            if annotation.get("/Contents") is not None:
                continue
            action = annotation.get("/A")
            uri = str(action.get("/URI")) if action is not None and action.get("/URI") else ""
            if not uri:
                continue
            annotation[Name.Contents] = String(_describe_uri(uri))
            updated += 1
    return updated


def set_annotation_tab_order(pdf: pikepdf.Pdf) -> int:
    """Give every annotated page a structure-driven tab order.

    PDF/UA requires /Tabs = /S on any page carrying annotations, so that
    keyboard focus follows the structure tree rather than the order the
    annotations happen to sit in the array.
    """
    updated = 0
    for page in pdf.pages:
        annotations = page.obj.get("/Annots")
        if annotations is None or len(annotations) == 0:
            continue
        if page.obj.get("/Tabs") == Name.S:
            continue
        page.obj[Name.Tabs] = Name.S
        updated += 1
    return updated
