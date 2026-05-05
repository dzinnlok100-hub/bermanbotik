"""Scraper for amkbook.net.

amkbook.net hosts a community-edited solver for the Berman problem book.
The site exposes the structure as plain HTML pages:

  /problem/source/{book}                    -> list of chapters
  /problem/source/{book}/{ch}               -> list of paragraphs
  /problem/source/{book}/{ch}/{para}        -> list of problems (Berman number + amk id)
  /problem/{amk_id}                         -> a single problem page (statement / solution / answer)

This module walks that tree and writes everything to the local SQLite DB.

Run as:

    python -m berman_bot.parser              # scrape everything
    python -m berman_bot.parser --chapter 1  # only chapter 1
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass

import aiohttp
from bs4 import BeautifulSoup, Tag
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import get_settings
from .db import Database

log = logging.getLogger(__name__)


CHAPTER_LINK_RE = re.compile(r"/problem/source/(\d+)/(\d+)$")
PARAGRAPH_LINK_RE = re.compile(r"/problem/source/(\d+)/(\d+)/(\d+)$")
PROBLEM_LINK_RE = re.compile(r"/problem/(\d+)$")
RANGE_RE = re.compile(r"№\s*(\d+)\s*[-–—]\s*№?\s*(\d+)")
TASK_NUMBER_RE = re.compile(r"Задача\s*№\s*(\d+)")


@dataclass
class ChapterMeta:
    number: int
    title: str
    range_text: str
    url: str


@dataclass
class ParagraphMeta:
    chapter_number: int
    number: int
    title: str
    range_text: str
    url: str


@dataclass
class ProblemMeta:
    chapter_number: int
    paragraph_number: int
    berman_number: int
    amk_internal_id: int
    url: str


class Scraper:
    """Async HTTP client + parser for amkbook.net."""

    def __init__(
        self,
        base_url: str,
        book_id: int,
        session: aiohttp.ClientSession,
        concurrency: int = 6,
        request_delay: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.book_id = book_id
        self.session = session
        self.semaphore = asyncio.Semaphore(concurrency)
        self.request_delay = request_delay

    async def _get(self, path: str) -> str:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(4),
            wait=wait_exponential(min=1, max=10),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            reraise=True,
        ):
            with attempt:
                async with self.semaphore:
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        resp.raise_for_status()
                        text = await resp.text()
                        if self.request_delay:
                            await asyncio.sleep(self.request_delay)
                        return text
        raise RuntimeError(f"unreachable: {url}")  # pragma: no cover

    # ---- chapters ------------------------------------------------------

    async def fetch_chapters(self) -> list[ChapterMeta]:
        html = await self._get(f"/problem/source/{self.book_id}")
        soup = BeautifulSoup(html, "lxml")
        chapters: list[ChapterMeta] = []
        for row in soup.select("table tr"):
            link = row.find("a", href=CHAPTER_LINK_RE)
            if not link or not isinstance(link, Tag):
                continue
            href = str(link.get("href") or "")
            m = CHAPTER_LINK_RE.search(href)
            if not m:
                continue
            chapter_number = int(m.group(2))
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            title = cells[1] if len(cells) >= 2 else ""
            range_text = cells[2] if len(cells) >= 3 else ""
            chapters.append(
                ChapterMeta(
                    number=chapter_number,
                    title=title,
                    range_text=range_text,
                    url=f"{self.base_url}{href}",
                )
            )
        return chapters

    # ---- paragraphs ----------------------------------------------------

    async def fetch_paragraphs(self, chapter_number: int) -> list[ParagraphMeta]:
        html = await self._get(f"/problem/source/{self.book_id}/{chapter_number}")
        soup = BeautifulSoup(html, "lxml")
        paragraphs: list[ParagraphMeta] = []
        for row in soup.select("table tr"):
            link = row.find("a", href=PARAGRAPH_LINK_RE)
            if not link or not isinstance(link, Tag):
                continue
            href = str(link.get("href") or "")
            m = PARAGRAPH_LINK_RE.search(href)
            if not m:
                continue
            paragraph_number = int(m.group(3))
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            title = cells[1] if len(cells) >= 2 else ""
            range_text = cells[2] if len(cells) >= 3 else ""
            paragraphs.append(
                ParagraphMeta(
                    chapter_number=chapter_number,
                    number=paragraph_number,
                    title=title,
                    range_text=range_text,
                    url=f"{self.base_url}{href}",
                )
            )
        return paragraphs

    # ---- problem listings ----------------------------------------------

    async def fetch_problems_in_paragraph(
        self, chapter_number: int, paragraph_number: int
    ) -> list[ProblemMeta]:
        html = await self._get(
            f"/problem/source/{self.book_id}/{chapter_number}/{paragraph_number}"
        )
        soup = BeautifulSoup(html, "lxml")
        problems: list[ProblemMeta] = []
        seen: set[int] = set()
        for link in soup.find_all("a", href=PROBLEM_LINK_RE):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href") or "")
            m = PROBLEM_LINK_RE.search(href)
            if not m:
                continue
            amk_id = int(m.group(1))
            text = link.get_text(" ", strip=True)
            tm = TASK_NUMBER_RE.search(text)
            if not tm:
                continue
            berman_number = int(tm.group(1))
            if berman_number in seen:
                continue
            seen.add(berman_number)
            problems.append(
                ProblemMeta(
                    chapter_number=chapter_number,
                    paragraph_number=paragraph_number,
                    berman_number=berman_number,
                    amk_internal_id=amk_id,
                    url=f"{self.base_url}{href}",
                )
            )
        return problems

    # ---- problem detail ------------------------------------------------

    async def fetch_problem_detail(
        self, amk_internal_id: int
    ) -> tuple[str | None, str | None, str | None]:
        """Return (statement_html, solution_html, answer_html) for a given amk problem."""
        html = await self._get(f"/problem/{amk_internal_id}")
        soup = BeautifulSoup(html, "lxml")
        statement = soup.select_one("section.problem-statement")
        solution = soup.select_one("section.problem-solution")
        answer = soup.select_one("section.problem-answer")
        return (
            _section_inner_html(statement),
            _section_inner_html(solution),
            _section_inner_html(answer),
        )


def _section_inner_html(section: Tag | None) -> str | None:
    """Return the section content with its `<h2>` heading stripped."""
    if section is None:
        return None
    for h in section.find_all(["h1", "h2", "h3"]):
        h.decompose()
    inner = section.decode_contents()
    return inner.strip()


# ---- pipeline ---------------------------------------------------------------

def _expand_paragraph_problems(
    paragraph: ParagraphMeta, scraped: list[ProblemMeta]
) -> list[tuple[int, int | None]]:
    """Return list of (berman_number, amk_internal_id_or_None) covering the
    paragraph's full range. Numbers without an amkbook solution end up with
    `amk_internal_id=None` so they still appear in navigation.
    """
    result: dict[int, int | None] = {}
    m = RANGE_RE.search(paragraph.range_text)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start <= end and end - start <= 5000:
            for n in range(start, end + 1):
                result[n] = None
    for p in scraped:
        result[p.berman_number] = p.amk_internal_id
    return sorted(result.items())


async def run_scrape(
    chapters_filter: set[int] | None = None,
    paragraphs_only: bool = False,
    statements_only: bool = False,
    concurrency: int = 3,
    request_delay: float = 0.3,
) -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    timeout = aiohttp.ClientTimeout(total=60)
    headers = {"User-Agent": "berman-bot/0.1 (+https://github.com/dzinnlok100-hub/bermanbotik)"}
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector) as s:
        scraper = Scraper(
            base_url=settings.source_base_url,
            book_id=settings.source_book_id,
            session=s,
            concurrency=concurrency,
            request_delay=request_delay,
        )

        log.info("Fetching chapter list…")
        chapters = await scraper.fetch_chapters()
        log.info("Got %d chapters", len(chapters))

        for ch in chapters:
            if chapters_filter and ch.number not in chapters_filter:
                continue
            chapter_id = db.upsert_chapter(ch.number, ch.title, ch.range_text)
            log.info("Chapter %d: %s (%s)", ch.number, ch.title, ch.range_text)

            paras = await scraper.fetch_paragraphs(ch.number)
            for p in paras:
                paragraph_id = db.upsert_paragraph(
                    chapter_id, p.number, p.title, p.range_text
                )
                log.info(
                    "  §%d.%d: %s (%s)", ch.number, p.number, p.title, p.range_text
                )
                if paragraphs_only:
                    continue
                problems = await scraper.fetch_problems_in_paragraph(ch.number, p.number)
                expanded = _expand_paragraph_problems(p, problems)
                log.info(
                    "    %d problems (%d with solution links)",
                    len(expanded),
                    sum(1 for _, amk in expanded if amk is not None),
                )
                for berman_number, amk_id in expanded:
                    db.upsert_problem(
                        berman_number=berman_number,
                        paragraph_id=paragraph_id,
                        amk_internal_id=amk_id,
                        source_url=f"{settings.source_base_url}/problem/{amk_id}" if amk_id else None,
                    )

        if statements_only or paragraphs_only:
            log.info("Skipping problem detail fetch")
            return

        log.info("Fetching problem details…")
        rows = db.problems_needing_detail()
        log.info("%d problems need detail fetch", len(rows))

        async def fetch_one(berman_number: int, amk_id: int) -> None:
            try:
                stmt, sol, ans = await scraper.fetch_problem_detail(amk_id)
            except Exception as e:
                log.warning(
                    "Failed to fetch problem %d (amk %d): %s",
                    berman_number,
                    amk_id,
                    e,
                )
                return
            db.update_problem_html(berman_number, stmt, sol, ans)

        chunk = 30
        for i in range(0, len(rows), chunk):
            batch = rows[i : i + chunk]
            await asyncio.gather(*(fetch_one(b, a) for b, a in batch))
            log.info("  fetched %d/%d problem details", min(i + chunk, len(rows)), len(rows))

    db.close()
    log.info("Done.")


# ---- CLI -------------------------------------------------------------------


def cli() -> None:
    parser = argparse.ArgumentParser(description="Scrape amkbook.net into the local SQLite DB.")
    parser.add_argument("--chapter", type=int, action="append", help="Only process this chapter (repeatable).")
    parser.add_argument(
        "--paragraphs-only",
        action="store_true",
        help="Stop after parsing chapters & paragraphs.",
    )
    parser.add_argument(
        "--statements-only",
        action="store_true",
        help="Skip fetching problem detail (statement/solution/answer).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max in-flight HTTP requests (default 3, keep low to avoid getting rate-limited).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.3,
        help="Sleep between requests (seconds, default 0.3) to stay polite to amkbook.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    chapters_filter: set[int] | None = set(args.chapter) if args.chapter else None
    asyncio.run(
        run_scrape(
            chapters_filter=chapters_filter,
            paragraphs_only=args.paragraphs_only,
            statements_only=args.statements_only,
            concurrency=args.concurrency,
            request_delay=args.request_delay,
        )
    )


if __name__ == "__main__":
    cli()
