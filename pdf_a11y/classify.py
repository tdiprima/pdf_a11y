"""Pure classification logic: text lines in, structure roles out.

No filesystem, no PDF library. Everything here is testable in isolation.
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import median
from dataclasses import dataclass
from enum import Enum

# Marker glyphs Word and its PDF exporters emit for bullets, plus the plain
# ASCII substitutes authors type by hand.
_BULLET_MARKERS = "•●▪◦‣⁃·"
_LIST_PATTERN = re.compile(
    rf"^\s*(?:[{_BULLET_MARKERS}]|-{{1,3}}|\*|–|—|\d{{1,3}}[.)]|[a-zA-Z][.)])\s+"
)

# A heading is set larger than body text. These multipliers separate a true
# display heading from a section heading from ordinary prose.
H1_SIZE_RATIO = 1.5
H2_SIZE_RATIO = 1.15

# A bold run at body size is only a heading if it is short and unpunctuated.
MAX_HEADING_CHARS = 70
_SENTENCE_END = (".", ",", ";", ":")

# Ignore whitespace-only lines when deciding what the body size is.
MIN_BODY_SAMPLE_CHARS = 1


class Role(str, Enum):
    """Standard PDF structure types this tool can assign."""

    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    P = "P"
    LBODY = "LBody"


@dataclass(frozen=True)
class TextLine:
    """One visual line of text on a page."""

    page_index: int
    baseline_y: float
    text: str
    max_size: float
    is_bold: bool

    @property
    def stripped(self) -> str:
        return self.text.strip()

    @property
    def is_blank(self) -> bool:
        return not self.stripped


def body_size(lines: list[TextLine]) -> float:
    """Return the dominant font size, weighted by how much text uses it.

    Weighting by character count stops a handful of large title words from
    being mistaken for the body size of the document.
    """
    weights: Counter[float] = Counter()
    for line in lines:
        if line.is_blank:
            continue
        characters = len(line.stripped)
        if characters < MIN_BODY_SAMPLE_CHARS:
            continue
        weights[round(line.max_size, 1)] += characters

    if not weights:
        return 0.0
    return weights.most_common(1)[0][0]


def is_list_item(text: str) -> bool:
    """True when the line opens with a bullet or an enumerator."""
    return bool(_LIST_PATTERN.match(text))


def _is_bold_heading(line: TextLine, dominant: float) -> bool:
    """A short, bold, unpunctuated line at body size reads as a subheading."""
    if not line.is_bold:
        return False
    if line.max_size < dominant * 0.95:
        return False
    stripped = line.stripped
    if len(stripped) > MAX_HEADING_CHARS:
        return False
    return not stripped.endswith(_SENTENCE_END)


def classify_line(line: TextLine, dominant: float) -> Role:
    """Assign one structure role to one line."""
    if dominant <= 0:
        return Role.P
    # An empty heading is itself a validator failure, so blank lines stay
    # paragraphs no matter how they happen to be styled.
    if line.is_blank:
        return Role.P

    if line.max_size >= dominant * H1_SIZE_RATIO:
        return Role.H1
    if line.max_size >= dominant * H2_SIZE_RATIO:
        return Role.H2
    if is_list_item(line.stripped):
        return Role.LBODY
    if _is_bold_heading(line, dominant):
        return Role.H3
    return Role.P


def classify_lines(lines: list[TextLine]) -> list[Role]:
    """Assign a role to every line, using the document-wide body size."""
    dominant = body_size(lines)
    return [classify_line(line, dominant) for line in lines]


def demote_duplicate_h1(roles: list[Role]) -> list[Role]:
    """Keep a single H1 per document; later oversized lines become H2.

    Two top-level headings is a common WCAG review finding, and a document
    exported from Word rarely means to have more than one title.
    """
    seen_h1 = False
    result: list[Role] = []
    for role in roles:
        if role is not Role.H1:
            result.append(role)
            continue
        if seen_h1:
            result.append(Role.H2)
        else:
            seen_h1 = True
            result.append(Role.H1)
    return result


# A line that continues the previous one sits no further below it than this
# multiple of the page's usual line spacing.
CONTINUATION_GAP_RATIO = 1.5

# Punctuation that ends a thought. A line ending here starts a new block.
_BLOCK_ENDING = ".!?:;"


@dataclass(frozen=True)
class Block:
    """One structure element: a role plus the lines it covers."""

    role: Role
    line_indices: tuple[int, ...]


def typical_line_gap(lines: list[TextLine]) -> float:
    """Return the median vertical distance between consecutive lines.

    A true median matters here: picking the upper of two middle values lets a
    single large paragraph break define "normal" spacing on a short page, and
    every block then merges into one.
    """
    gaps = [
        abs(lines[index + 1].baseline_y - lines[index].baseline_y)
        for index in range(len(lines) - 1)
    ]
    gaps = [gap for gap in gaps if gap > 0.1]
    if not gaps:
        return 0.0
    return median(gaps)


def _continues(
    previous: TextLine,
    previous_role: Role,
    current: TextLine,
    current_role: Role,
    gap_limit: float,
) -> bool:
    """True when `current` is a wrapped continuation of `previous`.

    Word exports break a paragraph into one text run per visual line. Without
    rejoining them a screen reader announces every line as its own paragraph.
    """
    if previous.page_index != current.page_index:
        return False
    if gap_limit > 0 and abs(current.baseline_y - previous.baseline_y) > gap_limit:
        return False
    if previous.stripped.endswith(tuple(_BLOCK_ENDING)):
        return False
    # A new bullet always starts a new item, however the previous line ended.
    if is_list_item(current.stripped):
        return False

    if current_role is Role.P and previous_role in (Role.P, Role.LBODY):
        return True
    return current_role is previous_role and current_role in (Role.H1, Role.H2, Role.H3)


def group_into_blocks(lines: list[TextLine], roles: list[Role]) -> list[Block]:
    """Merge wrapped lines so each block is one paragraph, heading or item."""
    if not lines:
        return []

    gap_limit = typical_line_gap(lines) * CONTINUATION_GAP_RATIO
    blocks: list[Block] = []
    current_indices = [0]
    current_role = roles[0]

    for index in range(1, len(lines)):
        if _continues(
            lines[index - 1], roles[index - 1], lines[index], roles[index], gap_limit
        ):
            current_indices.append(index)
            continue
        blocks.append(Block(current_role, tuple(current_indices)))
        current_indices = [index]
        current_role = roles[index]

    blocks.append(Block(current_role, tuple(current_indices)))
    return blocks


# Heading roles, shallowest first. Used to close gaps in the heading outline.
_HEADING_ORDER = (Role.H1, Role.H2, Role.H3)


def normalize_heading_levels(roles: list[Role]) -> list[Role]:
    """Close gaps in the heading outline so no level is skipped.

    PDF/UA requires the first heading to be H1 and forbids jumping from H1
    straight to H3. Font size alone often produces exactly that gap, so the
    levels actually used are remapped onto a contiguous run starting at H1.
    """
    used = [role for role in _HEADING_ORDER if role in roles]
    if not used:
        return list(roles)

    remap = {role: _HEADING_ORDER[index] for index, role in enumerate(used)}
    return [remap.get(role, role) for role in roles]
