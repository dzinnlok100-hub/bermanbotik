"""Extract problem statements from the Berman PDF.

The PDF has a clean text layer, so problem boundaries can be detected by lines
that start with `<number>. `. The optional `◦` marker (used in the book to flag
problems with answers) is allowed before the number.

Run:

    python -m berman_bot.pdf_extractor --pdf path/to/berman.pdf
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

import fitz  # type: ignore[import-untyped]

from .config import get_settings
from .db import Database

log = logging.getLogger(__name__)


PROBLEM_START_RE = re.compile(
    r"""(?xm)
    ^
    [◦\u00B0\u2022\*]?                        # optional bullet/circle marker
    [ \t]*
    (?P<num>[1-9]\d{0,3})                     # problem number 1..9999
    \.                                        # literal dot
    \s
    """
)

# Lines that indicate boundaries we should not cross when extracting a problem
SECTION_RE = re.compile(
    r"""(?xm)
    ^(?:
        Глава\s+\d+
      | §\s*\d+\.\d+
      | \d+\.\d+\.\d+\.\s          # subsection like 1.1.1.
      | ОТВЕТЫ
      | Указания
      | Содержание
      | ПРИЛОЖЕНИ[ЕЯ]
    )
    """
)


@dataclass
class PdfProblem:
    number: int
    page: int
    text: str


def _dehyphenate(text: str) -> str:
    """Join hyphenated words split across lines: 'много-\\nугольника' -> 'многоугольника'."""
    text = re.sub(r"-\n(?=[а-яёА-ЯЁa-zA-Z])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _extract_main_body(doc: fitz.Document) -> tuple[str, list[tuple[int, int]]]:
    """Return (concatenated_text, page_offsets) from the body section of the book.

    `page_offsets` is a list of (page_index, char_offset) tuples used to map
    a character position back to a page number.
    """
    parts: list[str] = []
    page_offsets: list[tuple[int, int]] = []
    offset = 0
    for i in range(doc.page_count):
        txt = doc[i].get_text("text")
        page_offsets.append((i, offset))
        parts.append(txt)
        offset += len(txt) + 1  # +1 for the joiner newline
    return "\n".join(parts), page_offsets


def _page_for_offset(offsets: list[tuple[int, int]], pos: int) -> int:
    page = 0
    for p, off in offsets:
        if off <= pos:
            page = p
        else:
            break
    return page


def extract_problems(pdf_path: Path) -> list[PdfProblem]:
    """Walk the PDF and return a list of `PdfProblem` records.

    The function only keeps numbers that look monotonic relative to the
    previous one (allowing skips up to 50) so that random `1.` references
    inside a problem body don't get mistaken for a new problem.
    """
    doc = fitz.open(pdf_path)
    full_text, offsets = _extract_main_body(doc)

    answers_pos = full_text.find("ОТВЕТЫ")
    body = full_text[: answers_pos] if answers_pos != -1 else full_text

    matches = list(PROBLEM_START_RE.finditer(body))
    if not matches:
        return []

    problems: list[PdfProblem] = []
    last_number = 0
    for i, m in enumerate(matches):
        num = int(m.group("num"))
        # Reject implausible jumps: probably not a real problem header.
        if num <= last_number or num > last_number + 200:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end]
        # Stop at chapter/paragraph boundaries
        sect = SECTION_RE.search(chunk)
        if sect:
            chunk = chunk[: sect.start()]
        chunk = _dehyphenate(chunk).strip()
        if not chunk:
            continue
        problems.append(
            PdfProblem(number=num, page=_page_for_offset(offsets, m.start()), text=chunk)
        )
        last_number = num

    return problems


def text_to_html(text: str) -> str:
    """Wrap plain extracted text into safe HTML paragraphs."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    return "\n".join(
        "<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
    )


def import_to_db(problems: list[PdfProblem], overwrite: bool = False) -> tuple[int, int]:
    """Insert/update extracted statements into the DB.

    Returns (updated, missing_in_db). Problems whose number isn't yet in the DB
    are skipped — they belong to ranges we haven't scraped yet.
    """
    settings = get_settings()
    db = Database(settings.db_path)
    updated = 0
    missing = 0
    try:
        for p in problems:
            row = db.get_problem_by_berman_number(p.number)
            if row is None:
                missing += 1
                continue
            if row.statement_html and not overwrite:
                continue
            html = text_to_html(p.text)
            db.update_problem_html(p.number, html, None, None)
            updated += 1
    finally:
        db.close()
    return updated, missing


def cli() -> None:
    parser = argparse.ArgumentParser(description="Extract problem statements from the Berman PDF.")
    parser.add_argument("--pdf", type=Path, required=True, help="Path to berman.pdf")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing statement HTML even if amkbook already provided one.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print summary only, do not write DB.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    problems = extract_problems(args.pdf)
    log.info("Extracted %d problems from PDF", len(problems))
    if problems:
        log.info(
            "Numbers: %d .. %d",
            problems[0].number,
            problems[-1].number,
        )

    if args.dry_run:
        for p in problems[:5]:
            log.info("--- №%d (page %d) ---", p.number, p.page + 1)
            log.info(p.text[:300])
        return

    updated, missing = import_to_db(problems, overwrite=args.overwrite)
    log.info("Updated %d problem(s) in DB. %d not found in DB.", updated, missing)


if __name__ == "__main__":
    cli()
