"""Structure tagging must be atomic across the whole document."""

from __future__ import annotations

import fitz
import pikepdf
from pikepdf import Dictionary, String

from pdf_a11y import tag_fix
from pdf_a11y.extract import extract_lines


def test_unsupported_page_preserves_existing_tree_and_all_content(tmp_path, monkeypatch):
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    for text in ("First page", "Second page"):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()

    with fitz.open(path) as doc:
        pages_lines = extract_lines(doc)

    calls = 0
    real_plan_page = tag_fix.plan_page

    def fail_second_page(instructions, page_lines):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise tag_fix.TaggingUnsupported("existing marked content")
        return real_plan_page(instructions, page_lines)

    monkeypatch.setattr(tag_fix, "plan_page", fail_second_page)

    with pikepdf.open(path) as pdf:
        original_tree = Dictionary(Sentinel=String("keep"))
        pdf.Root.StructTreeRoot = original_tree
        first_stream_before = pikepdf.unparse_content_stream(
            list(pikepdf.parse_content_stream(pdf.pages[0]))
        )

        counts = tag_fix.tag_document(pdf, pages_lines, "en-US")

        assert counts == {"tagged_pages": 0, "skipped_pages": 2}
        assert str(pdf.Root.StructTreeRoot.Sentinel) == "keep"
        first_stream_after = pikepdf.unparse_content_stream(
            list(pikepdf.parse_content_stream(pdf.pages[0]))
        )
        assert first_stream_after == first_stream_before
        assert pdf.Root.get("/MarkInfo") is None
