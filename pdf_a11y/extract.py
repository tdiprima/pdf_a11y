"""Read text geometry out of a PDF with PyMuPDF."""

from __future__ import annotations

import re

import fitz

from .classify import TextLine

# PyMuPDF sets bit 4 of a span's flags when the glyphs are bold.
_BOLD_FLAG = 1 << 4

# Baselines within this many points are treated as the same visual line.
BASELINE_TOLERANCE = 0.6

_WHITESPACE = re.compile(r"\s+")


def _span_is_bold(span: dict) -> bool:
    """Bold is reported either in the flags bitfield or in the font name."""
    if span["flags"] & _BOLD_FLAG:
        return True
    return "bold" in span["font"].lower()


def extract_page_lines(page: fitz.Page, page_index: int) -> list[TextLine]:
    """Return the page's text lines in content-stream order.

    Order matters: it is what lets the tagger line these up with the marked
    content it injects. `sort` stays off so the natural order is preserved.
    """
    lines: list[TextLine] = []
    page_dict = page.get_text("dict", sort=False)

    for block in page_dict["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            if not spans:
                continue
            text = "".join(span["text"] for span in spans)
            lines.append(
                TextLine(
                    page_index=page_index,
                    baseline_y=round(line["bbox"][3], 1),
                    text=text,
                    max_size=max(span["size"] for span in spans),
                    is_bold=any(_span_is_bold(span) for span in spans),
                )
            )
    return lines


def extract_lines(doc: fitz.Document) -> list[list[TextLine]]:
    """Return one list of text lines per page."""
    return [extract_page_lines(page, index) for index, page in enumerate(doc)]


def guess_title(pages: list[list[TextLine]], fallback: str) -> str:
    """Pick a human-readable document title.

    The largest text on the first page is almost always the document title in
    a Word export. If nothing usable is found, the caller's fallback (derived
    from the filename) is used instead.
    """
    if not pages or not pages[0]:
        return fallback

    candidates = [line for line in pages[0] if not line.is_blank]
    if not candidates:
        return fallback

    largest = max(candidates, key=lambda line: line.max_size)
    title = _WHITESPACE.sub(" ", largest.stripped)

    # A single oversized letter, or a run of body text, is not a title.
    if len(title) < 3 or len(title) > 200:
        return fallback
    return title


def filename_to_title(stem: str) -> str:
    """Turn a filename stem into a readable title as a last resort."""
    spaced = re.sub(r"[_\-]+", " ", stem)
    spaced = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", spaced)
    return _WHITESPACE.sub(" ", spaced).strip() or stem
