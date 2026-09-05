"""Tests for the pure classification logic, written from the specification."""

from __future__ import annotations

import pytest

from pdf_a11y.classify import (
    Role,
    TextLine,
    body_size,
    classify_line,
    classify_lines,
    demote_duplicate_h1,
    group_into_blocks,
    normalize_heading_levels,
    is_list_item,
    typical_line_gap,
)


def line(text: str, size: float = 12.0, bold: bool = False, y: float = 0.0, page: int = 0) -> TextLine:
    return TextLine(page_index=page, baseline_y=y, text=text, max_size=size, is_bold=bold)


class TestBodySize:
    def test_empty_document_has_no_body_size(self):
        assert body_size([]) == 0.0

    def test_blank_lines_are_ignored(self):
        assert body_size([line("   "), line("")]) == 0.0

    def test_weights_by_character_count_not_line_count(self):
        # Three short title lines must not outvote one long paragraph.
        lines = [line("Big", 28.0), line("Big", 28.0), line("Big", 28.0)]
        lines.append(line("x" * 200, 12.0))
        assert body_size(lines) == 12.0

    def test_single_line_document(self):
        assert body_size([line("hello", 10.5)]) == 10.5


class TestListDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "• Homeworks 40 pts",
            "- dash item",
            "-- double dash item",
            "* asterisk item",
            "1. numbered item",
            "12) parenthesised number",
            "a. lettered item",
            "– en dash item",
        ],
    )
    def test_recognises_markers(self, text):
        assert is_list_item(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "Ordinary prose.",
            "1.5 million records",
            "e.g. this is prose",
            "-no space after the dash",
        ],
    )
    def test_rejects_non_lists(self, text):
        assert is_list_item(text) is False


class TestClassifyLine:
    def test_large_text_is_h1(self):
        assert classify_line(line("Title", 28.0), 12.0) is Role.H1

    def test_moderately_large_text_is_h2(self):
        assert classify_line(line("Section", 15.0), 12.0) is Role.H2

    def test_short_bold_line_is_h3(self):
        assert classify_line(line("Academic Integrity", 12.0, bold=True), 12.0) is Role.H3

    def test_bold_sentence_is_not_a_heading(self):
        text = "This bold line ends like a sentence and is therefore prose."
        assert classify_line(line(text, 12.0, bold=True), 12.0) is Role.P

    def test_long_bold_line_is_not_a_heading(self):
        assert classify_line(line("word " * 30, 12.0, bold=True), 12.0) is Role.P

    def test_blank_line_never_becomes_an_empty_heading(self):
        # An empty heading is itself an accessibility failure.
        assert classify_line(line("   ", 28.0, bold=True), 12.0) is Role.P

    def test_bullet_beats_bold(self):
        assert classify_line(line("• Item", 12.0, bold=True), 12.0) is Role.LBODY

    def test_degenerate_body_size_falls_back_to_paragraph(self):
        assert classify_line(line("anything", 28.0, bold=True), 0.0) is Role.P

    def test_negative_size_is_handled(self):
        assert classify_line(line("odd", -5.0), 12.0) is Role.P


class TestDemoteDuplicateH1:
    def test_keeps_first_h1_and_demotes_the_rest(self):
        roles = [Role.H1, Role.P, Role.H1, Role.H1]
        assert demote_duplicate_h1(roles) == [Role.H1, Role.P, Role.H2, Role.H2]

    def test_empty_input(self):
        assert demote_duplicate_h1([]) == []

    def test_leaves_other_roles_untouched(self):
        roles = [Role.P, Role.LBODY, Role.H3]
        assert demote_duplicate_h1(roles) == roles


class TestNormalizeHeadingLevels:
    def test_closes_a_gap_in_the_outline(self):
        # PDF/UA forbids jumping H1 -> H3, which font size alone produces.
        roles = [Role.H1, Role.P, Role.H3, Role.H3]
        assert normalize_heading_levels(roles) == [Role.H1, Role.P, Role.H2, Role.H2]

    def test_document_without_an_h1_starts_at_h1(self):
        assert normalize_heading_levels([Role.H3, Role.P, Role.H3]) == [
            Role.H1,
            Role.P,
            Role.H1,
        ]

    def test_contiguous_outline_is_unchanged(self):
        roles = [Role.H1, Role.H2, Role.H3]
        assert normalize_heading_levels(roles) == roles

    def test_document_with_no_headings_is_unchanged(self):
        assert normalize_heading_levels([Role.P, Role.LBODY]) == [Role.P, Role.LBODY]

    def test_empty_input(self):
        assert normalize_heading_levels([]) == []

    def test_non_heading_roles_are_never_remapped(self):
        roles = [Role.H2, Role.LBODY, Role.P, Role.H3]
        result = normalize_heading_levels(roles)
        assert result[1] is Role.LBODY and result[2] is Role.P


class TestTypicalLineGap:
    def test_single_line_has_no_gap(self):
        assert typical_line_gap([line("only")]) == 0.0

    def test_identical_baselines_are_ignored(self):
        assert typical_line_gap([line("a", y=100.0), line("b", y=100.0)]) == 0.0

    def test_returns_the_median_gap(self):
        lines = [line("a", y=0.0), line("b", y=14.0), line("c", y=28.0), line("d", y=100.0)]
        assert typical_line_gap(lines) == 14.0


class TestGroupIntoBlocks:
    def test_empty_document(self):
        assert group_into_blocks([], []) == []

    def test_wrapped_paragraph_becomes_one_block(self):
        lines = [
            line("The class is for students with no background", y=0.0),
            line("of computation and prepares them for work.", y=14.0),
        ]
        blocks = group_into_blocks(lines, [Role.P, Role.P])
        assert len(blocks) == 1
        assert blocks[0].line_indices == (0, 1)

    def test_sentence_end_starts_a_new_block(self):
        lines = [line("First thought.", y=0.0), line("Second thought.", y=14.0)]
        blocks = group_into_blocks(lines, [Role.P, Role.P])
        assert len(blocks) == 2

    def test_large_gap_starts_a_new_block(self):
        lines = [
            line("a continuing line", y=0.0),
            line("still continuing", y=14.0),
            line("far away line", y=200.0),
        ]
        blocks = group_into_blocks(lines, [Role.P, Role.P, Role.P])
        assert [block.line_indices for block in blocks] == [(0, 1), (2,)]

    def test_wrapped_list_item_stays_in_the_item(self):
        lines = [
            line("• a bullet that wraps", y=0.0),
            line("onto a second line", y=14.0),
        ]
        blocks = group_into_blocks(lines, [Role.LBODY, Role.P])
        assert len(blocks) == 1
        assert blocks[0].role is Role.LBODY

    def test_new_bullet_always_starts_an_item(self):
        lines = [line("• first item", y=0.0), line("• second item", y=14.0)]
        blocks = group_into_blocks(lines, [Role.LBODY, Role.LBODY])
        assert len(blocks) == 2

    def test_bullet_line_never_merges_even_when_rolled_as_prose(self):
        # group_into_blocks must not rely on its caller having classified the
        # line correctly: a visible bullet always starts a new item.
        lines = [
            line("• first item with no closing period", y=0.0),
            line("• second item", y=14.0),
        ]
        blocks = group_into_blocks(lines, [Role.LBODY, Role.P])
        assert len(blocks) == 2

    def test_blocks_never_span_a_page_break(self):
        lines = [
            line("trailing text with no period", y=700.0, page=0),
            line("opening text of the next page", y=700.0, page=1),
        ]
        blocks = group_into_blocks(lines, [Role.P, Role.P])
        assert len(blocks) == 2

    def test_heading_does_not_absorb_following_prose(self):
        lines = [line("A Heading", y=0.0, bold=True), line("body text", y=14.0)]
        blocks = group_into_blocks(lines, [Role.H3, Role.P])
        assert [block.role for block in blocks] == [Role.H3, Role.P]

    def test_every_line_appears_in_exactly_one_block(self):
        lines = [line(f"line {index}", y=index * 14.0) for index in range(25)]
        roles = classify_lines(lines)
        covered = [
            index for block in group_into_blocks(lines, roles) for index in block.line_indices
        ]
        assert covered == list(range(25))


class TestAdversarialInput:
    def test_very_long_line_does_not_break_classification(self):
        assert classify_line(line("x" * 100_000, 12.0, bold=True), 12.0) is Role.P

    def test_bidi_override_character_is_treated_as_text(self):
        assert classify_line(line("‮ evil", 12.0), 12.0) is Role.P

    def test_regex_metacharacters_in_text_are_literal(self):
        # A crafted line must not be able to influence marker matching.
        assert is_list_item("(.*)+$ not a list") is False

    def test_thousands_of_lines_are_grouped_without_error(self):
        lines = [line("continuing text", y=index * 14.0) for index in range(5000)]
        blocks = group_into_blocks(lines, [Role.P] * 5000)
        assert sum(len(block.line_indices) for block in blocks) == 5000
