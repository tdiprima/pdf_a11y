"""Build a heuristic structure tree for an untagged PDF.

Two things have to happen together for tagging to mean anything:

1. The page content stream must mark each run of text with an MCID, and mark
   decorative graphics as artifacts.
2. A structure tree must point at those MCIDs, so a screen reader can walk
   headings, paragraphs and lists in order.

This module does both, and refuses to do either when the page contains
constructs it cannot reason about. A file left untagged is recoverable; a
file tagged with a wrong reading order is worse than where it started.
"""

from __future__ import annotations

import logging

import pikepdf
from pikepdf import Array, ContentStreamInstruction, Dictionary, Name, Operator, String

from .classify import (
    Block,
    Role,
    TextLine,
    classify_lines,
    demote_duplicate_h1,
    group_into_blocks,
    normalize_heading_levels,
)

logger = logging.getLogger(__name__)

# Baselines within this many points belong to the same visual line.
BASELINE_TOLERANCE = 0.6

# Fraction of consecutive line pairs whose vertical ordering must agree
# between the two extraction paths before tagging is trusted.
MIN_ORDER_AGREEMENT = 0.9

# How far a link rectangle's baseline may sit from a text line's, in points,
# before the link is treated as unattached to that line.
LINK_BASELINE_TOLERANCE = 6.0

_PATH_CONSTRUCTION = frozenset({"m", "l", "c", "v", "y", "h", "re"})
_PATH_CLIPPING = frozenset({"W", "W*"})
_PATH_PAINTING = frozenset({"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"})

# Constructs whose accessible meaning cannot be inferred automatically.
# Their presence means a human has to tag the file.
_UNSUPPORTED = frozenset({"Do", "sh", "BI", "BDC", "BMC", "EMC", "MP", "DP"})


class TaggingUnsupported(RuntimeError):
    """Raised when a page cannot be tagged safely and must be left alone.

    Subclasses RuntimeError so that a failure escaping the per-page guard
    aborts the whole file rather than writing a half-tagged document.
    """


def _text_object_baselines(instructions: list) -> list[float]:
    """Return the baseline Y of every BT/ET text object, in stream order."""
    baselines: list[float] = []
    pending: float | None = None
    depth = 0

    for instruction in instructions:
        operator = str(instruction.operator)

        if operator in _UNSUPPORTED:
            raise TaggingUnsupported(f"unsupported operator {operator}")

        if operator == "BT":
            depth += 1
            pending = None
        elif operator in ("Tm", "Td", "TD") and depth:
            operands = [float(value) for value in instruction.operands]
            pending = operands[-1]
        elif operator == "ET":
            depth -= 1
            baselines.append(pending if pending is not None else 0.0)
            pending = None

    if depth != 0:
        raise TaggingUnsupported("unbalanced BT/ET nesting")
    return baselines


def _group_baselines(baselines: list[float]) -> list[list[int]]:
    """Group text objects that share a baseline into visual lines.

    Groups are returned in first-appearance order so they stay aligned with
    the reading order the text extractor reports.
    """
    groups: list[list[int]] = []
    group_of: dict[float, int] = {}

    for index, baseline in enumerate(baselines):
        match = None
        for known in group_of:
            if abs(known - baseline) <= BASELINE_TOLERANCE:
                match = known
                break
        if match is None:
            group_of[baseline] = len(groups)
            groups.append([index])
        else:
            groups[group_of[match]].append(index)

    return groups


def _order_agreement(page_lines: list[TextLine], group_baselines: list[float]) -> float:
    """Compare the two extractions' vertical ordering, pair by pair.

    PDF user space counts upward and the text extractor counts downward, so
    agreement means the two disagree in sign on every consecutive pair.
    """
    comparable = 0
    agreeing = 0

    for index in range(len(page_lines) - 1):
        extractor_delta = page_lines[index + 1].baseline_y - page_lines[index].baseline_y
        stream_delta = group_baselines[index + 1] - group_baselines[index]
        if abs(extractor_delta) < 0.1 or abs(stream_delta) < 0.1:
            continue
        comparable += 1
        if (extractor_delta > 0) != (stream_delta > 0):
            agreeing += 1

    if comparable == 0:
        return 1.0
    return agreeing / comparable


def plan_page(instructions: list, page_lines: list[TextLine]) -> list[list[int]]:
    """Return the text-object groups for a page, or refuse to tag it."""
    baselines = _text_object_baselines(instructions)
    if not baselines:
        return []

    groups = _group_baselines(baselines)

    if len(groups) != len(page_lines):
        raise TaggingUnsupported(
            f"line count mismatch: {len(groups)} content-stream groups "
            f"vs {len(page_lines)} extracted lines"
        )

    group_baselines = [baselines[group[0]] for group in groups]
    agreement = _order_agreement(page_lines, group_baselines)
    if agreement < MIN_ORDER_AGREEMENT:
        raise TaggingUnsupported(f"reading order agreement only {agreement:.0%}")

    return groups


def rewrite_content(
    pdf: pikepdf.Pdf,
    page: pikepdf.Page,
    instructions: list,
    groups: list[list[int]],
    roles: list[Role],
) -> None:
    """Inject marked content into the page's content stream.

    Every text object gets its own MCID. Text objects on the same visual line
    share a structure element, which holds their MCIDs as an array. Painted
    paths are wrapped as artifacts so they stay out of the reading order.
    """
    mcid_of_text_object: dict[int, int] = {}
    tag_of_text_object: dict[int, Name] = {}

    next_mcid = 0
    for group, role in zip(groups, roles):
        for text_object_index in group:
            mcid_of_text_object[text_object_index] = next_mcid
            tag_of_text_object[text_object_index] = Name(f"/{role.value}")
            next_mcid += 1

    output: list[ContentStreamInstruction] = []
    text_object_index = 0
    in_path = False

    def close_artifact() -> None:
        nonlocal in_path
        if in_path:
            output.append(ContentStreamInstruction([], Operator("EMC")))
            in_path = False

    for instruction in instructions:
        operator = str(instruction.operator)

        if operator in _PATH_CONSTRUCTION and not in_path:
            output.append(
                ContentStreamInstruction([Name.Artifact], Operator("BMC"))
            )
            in_path = True
        elif operator in ("BT", "q", "Q") and in_path:
            # Defensive: a path should always be painted before these appear.
            close_artifact()

        if operator == "BT":
            mcid = mcid_of_text_object.get(text_object_index)
            if mcid is not None:
                output.append(
                    ContentStreamInstruction(
                        [tag_of_text_object[text_object_index], Dictionary(MCID=mcid)],
                        Operator("BDC"),
                    )
                )

        output.append(instruction)

        if operator == "ET":
            if mcid_of_text_object.get(text_object_index) is not None:
                output.append(ContentStreamInstruction([], Operator("EMC")))
            text_object_index += 1
        elif operator in _PATH_PAINTING and in_path:
            close_artifact()

    close_artifact()

    page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(output))


def _make_element(
    pdf: pikepdf.Pdf, role: str, parent: pikepdf.Object
) -> pikepdf.Object:
    """Create an empty structure element of the given standard type."""
    return pdf.make_indirect(
        Dictionary(Type=Name.StructElem, S=Name(f"/{role}"), P=parent, K=Array())
    )


def _append(parent: pikepdf.Object, child: pikepdf.Object) -> None:
    parent.K.append(child)


def _build_page_elements(
    pdf: pikepdf.Pdf,
    document: pikepdf.Object,
    page: pikepdf.Page,
    groups: list[list[int]],
    blocks: list[Block],
) -> tuple[list[pikepdf.Object], list[pikepdf.Object]]:
    """Create structure elements for one page.

    Returns the element owning each MCID, plus the element for each line, so
    link annotations can later be nested where they actually appear.
    """
    mcid_start: list[int] = []
    running = 0
    for group in groups:
        mcid_start.append(running)
        running += len(group)

    by_mcid: list[pikepdf.Object | None] = [None] * running
    by_line: list[pikepdf.Object | None] = [None] * len(groups)
    current_list: pikepdf.Object | None = None

    for block in blocks:
        if block.role is Role.LBODY:
            if current_list is None:
                current_list = _make_element(pdf, "L", document)
                _append(document, current_list)
            item = _make_element(pdf, "LI", current_list)
            _append(current_list, item)
            element = _make_element(pdf, "LBody", item)
            _append(item, element)
        else:
            current_list = None
            element = _make_element(pdf, block.role.value, document)
            _append(document, element)

        element.Pg = page.obj
        for line_index in block.line_indices:
            by_line[line_index] = element
            for offset in range(len(groups[line_index])):
                mcid = mcid_start[line_index] + offset
                element.K.append(mcid)
                by_mcid[mcid] = element

    return by_mcid, by_line


def _link_uri(annotation: pikepdf.Object) -> str:
    action = annotation.get("/A")
    if action is None:
        return ""
    uri = action.get("/URI")
    return str(uri) if uri is not None else ""


def _page_height(page: pikepdf.Page) -> float:
    box = page.obj.get("/MediaBox")
    if box is None:
        return 792.0
    return float(box[3]) - float(box[1])


def _owning_element(
    annotation: pikepdf.Object,
    page: pikepdf.Page,
    page_lines: list[TextLine],
    by_line: list[pikepdf.Object | None],
    fallback: pikepdf.Object,
) -> pikepdf.Object:
    """Find the structure element for the line this annotation sits on.

    Annotation rectangles are in PDF user space, which counts up from the
    bottom; the text extractor counts down from the top.
    """
    rect = annotation.get("/Rect")
    if rect is None or not page_lines:
        return fallback

    baseline_from_top = _page_height(page) - float(rect[1])

    best_index = min(
        range(len(page_lines)),
        key=lambda index: abs(page_lines[index].baseline_y - baseline_from_top),
    )
    if abs(page_lines[best_index].baseline_y - baseline_from_top) > LINK_BASELINE_TOLERANCE:
        return fallback

    element = by_line[best_index] if best_index < len(by_line) else None
    return element if element is not None else fallback


def _attach_links(
    pdf: pikepdf.Pdf,
    document: pikepdf.Object,
    page: pikepdf.Page,
    page_lines: list[TextLine],
    by_line: list[pikepdf.Object | None],
    next_key: int,
    nums: list,
) -> int:
    """Add a /Link structure element for each link annotation on the page."""
    annotations = page.obj.get("/Annots")
    if annotations is None:
        return next_key

    for annotation in annotations:
        if annotation.get("/Subtype") != Name.Link:
            continue

        parent = _owning_element(annotation, page, page_lines, by_line, document)
        element = _make_element(pdf, "Link", parent)
        _append(parent, element)
        element.Pg = page.obj
        element.K.append(
            pdf.make_indirect(
                Dictionary(Type=Name.OBJR, Obj=annotation, Pg=page.obj)
            )
        )

        uri = _link_uri(annotation)
        if uri:
            element.Alt = String(uri)

        annotation[Name.StructParent] = next_key
        nums.append(next_key)
        nums.append(element)
        next_key += 1

    return next_key


def tag_document(
    pdf: pikepdf.Pdf, pages_lines: list[list[TextLine]], lang: str
) -> dict[str, int]:
    """Tag every page that can be tagged safely.

    A page that cannot be handled is left exactly as it was: a file left
    untagged is recoverable, a file tagged with a wrong reading order is not.
    """
    all_lines = [line for page_lines in pages_lines for line in page_lines]
    all_roles = normalize_heading_levels(demote_duplicate_h1(classify_lines(all_lines)))

    roles_by_page: list[list[Role]] = []
    cursor = 0
    for page_lines in pages_lines:
        roles_by_page.append(all_roles[cursor : cursor + len(page_lines)])
        cursor += len(page_lines)

    struct_root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
    document = pdf.make_indirect(
        Dictionary(Type=Name.StructElem, S=Name.Document, P=struct_root, K=Array())
    )
    struct_root.K = document

    nums: list = []
    pending_links: list[tuple] = []
    tagged_pages = 0
    skipped_pages = 0

    for page_index, page in enumerate(pdf.pages):
        page_lines = pages_lines[page_index] if page_index < len(pages_lines) else []
        try:
            instructions = list(pikepdf.parse_content_stream(page))
            groups = plan_page(instructions, page_lines)
        except (TaggingUnsupported, pikepdf.PdfError) as error:
            logger.warning(
                "page_not_tagged", extra={"page": page_index + 1, "reason": str(error)}
            )
            skipped_pages += 1
            continue

        if not groups:
            skipped_pages += 1
            continue

        roles = roles_by_page[page_index]
        blocks = group_into_blocks(page_lines, roles)

        # Every text object on a line carries its block's role as its tag.
        role_per_line: list[Role] = [Role.P] * len(groups)
        for block in blocks:
            for line_index in block.line_indices:
                role_per_line[line_index] = block.role

        rewrite_content(pdf, page, instructions, groups, role_per_line)
        page.obj[Name.StructParents] = page_index

        by_mcid, by_line = _build_page_elements(pdf, document, page, groups, blocks)
        if any(item is None for item in by_mcid):
            raise TaggingUnsupported(
                f"page {page_index + 1}: marked content is not fully covered by the tree"
            )
        nums.append(page_index)
        nums.append(pdf.make_indirect(Array(by_mcid)))
        pending_links.append((page, page_lines, by_line))
        tagged_pages += 1

    if tagged_pages == 0:
        return {"tagged_pages": 0, "skipped_pages": skipped_pages}

    next_key = len(pdf.pages)
    for page, page_lines, by_line in pending_links:
        next_key = _attach_links(
            pdf, document, page, page_lines, by_line, next_key, nums
        )

    struct_root.ParentTree = pdf.make_indirect(Dictionary(Nums=Array(nums)))
    struct_root.ParentTreeNextKey = next_key
    pdf.Root[Name.StructTreeRoot] = struct_root
    pdf.Root[Name.MarkInfo] = pdf.make_indirect(Dictionary(Marked=True))

    return {"tagged_pages": tagged_pages, "skipped_pages": skipped_pages}
