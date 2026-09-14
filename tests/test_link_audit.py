"""Address placement and the audit's link check, written from the specification.

Specification: an address is "unlinked" only when no link annotation covers
the rectangle where that address is drawn. The count of links on a page says
nothing about which text they cover.
"""

from __future__ import annotations

import fitz

from pdf_a11y.audit import audit_file
from pdf_a11y.link_fix import add_link_annotations, place_addresses


def finding_codes(path) -> set[str]:
    result = audit_file(path)
    assert result.error is None, result.error
    return {finding.code for finding in result.findings}


class TestPlaceAddresses:
    def test_empty_page_yields_nothing(self, pdf_factory):
        with fitz.open(pdf_factory(text="")) as doc:
            assert place_addresses(doc[0]) == []

    def test_page_without_addresses_yields_nothing(self, pdf_factory):
        with fitz.open(pdf_factory(text="No addresses here.")) as doc:
            assert place_addresses(doc[0]) == []

    def test_plain_url_is_located_and_unlinked(self, pdf_factory):
        with fitz.open(pdf_factory(text="Visit https://example.com/page now")) as doc:
            [placement] = place_addresses(doc[0])
        assert placement.address == "https://example.com/page"
        assert placement.located
        assert placement.is_email is False
        assert len(placement.unlinked_rects) == 1

    def test_already_linked_url_has_no_unlinked_rects(self, pdf_factory):
        path = pdf_factory(
            text="Visit https://example.com/page now",
            link_rect_text="https://example.com/page",
        )
        with fitz.open(path) as doc:
            [placement] = place_addresses(doc[0])
        assert placement.located
        assert placement.unlinked_rects == ()

    def test_unrelated_link_does_not_cover_the_url(self, pdf_factory):
        path = pdf_factory(
            text="click here then https://example.com/page",
            link_rect_text="click here",
        )
        with fitz.open(path) as doc:
            [placement] = place_addresses(doc[0])
        assert len(placement.unlinked_rects) == 1

    def test_email_is_flagged_as_email(self, pdf_factory):
        with fitz.open(pdf_factory(text="Mail someone@example.org today")) as doc:
            [placement] = place_addresses(doc[0])
        assert placement.is_email
        assert placement.address == "someone@example.org"


class TestAuditLinkCheck:
    def test_unrelated_link_does_not_hide_plain_url(self, pdf_factory):
        # One link, one address: equal counts, but the address is still unlinked.
        path = pdf_factory(
            text="click here then https://example.com/page",
            link_rect_text="click here",
        )
        codes = finding_codes(path)
        assert "unlinked_urls" in codes

    def test_linked_url_is_not_reported(self, pdf_factory):
        path = pdf_factory(
            text="Visit https://example.com/page now",
            link_rect_text="https://example.com/page",
        )
        codes = finding_codes(path)
        assert "unlinked_urls" not in codes
        assert "raw_url_link_text" in codes

    def test_remediated_file_passes_the_link_check(self, pdf_factory, tmp_path):
        source = pdf_factory(text="Visit https://example.com/page now")
        fixed = tmp_path / "fixed.pdf"
        with fitz.open(source) as doc:
            added, unresolved = add_link_annotations(doc)
            doc.save(str(fixed))
        assert added == 1
        assert unresolved == []
        assert "unlinked_urls" not in finding_codes(fixed)

    def test_no_addresses_no_link_findings(self, pdf_factory):
        codes = finding_codes(pdf_factory(text="Plain prose only."))
        assert not codes & {"unlinked_urls", "unlocated_urls", "raw_url_link_text"}
