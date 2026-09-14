"""Shared fixtures: small PDFs generated on the fly so no binaries live in git."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def make_pdf(path: Path, text: str = "", link_rect_text: str | None = None) -> Path:
    """Write a one-page PDF containing text, optionally linking one phrase."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontsize=12)
    if link_rect_text:
        rects = page.search_for(link_rect_text)
        assert rects, f"fixture phrase not found on page: {link_rect_text!r}"
        page.insert_link(
            {"kind": fitz.LINK_URI, "uri": "https://example.org/other", "from": rects[0]}
        )
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_factory(tmp_path: Path):
    def factory(name: str = "doc.pdf", **kwargs) -> Path:
        return make_pdf(tmp_path / name, **kwargs)

    return factory
