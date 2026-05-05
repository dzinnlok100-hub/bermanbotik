"""Playwright-based fallback scraper for amkbook.net.

The plain aiohttp scraper in :mod:`berman_bot.parser` is fast but does not
execute JavaScript — when amkbook is fronted by an interstitial "Browser
check" challenge it cannot get past the gate. This module runs the same
extraction logic inside a real Chromium browser so the cookie issued by
the challenge is honoured for the rest of the session.

Run as::

    python -m berman_bot.browser_parser           # fetch missing problem details
    python -m berman_bot.browser_parser -v        # debug logging
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from bs4 import BeautifulSoup

from .config import get_settings
from .db import Database
from .parser import _section_inner_html

log = logging.getLogger(__name__)


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def _wait_past_browser_check(page, timeout_ms: int = 30_000) -> None:
    """Wait until the page is past the "Browser check" interstitial."""
    with contextlib.suppress(Exception):
        await page.wait_for_function(
            'document && document.title && '
            '!document.title.toLowerCase().includes("browser")',
            timeout=timeout_ms,
        )


def _parse_problem_html(html: str) -> tuple[str | None, str | None, str | None]:
    soup = BeautifulSoup(html, "lxml")
    statement = soup.select_one("section.problem-statement")
    solution = soup.select_one("section.problem-solution")
    answer = soup.select_one("section.problem-answer")
    return (
        _section_inner_html(statement),
        _section_inner_html(solution),
        _section_inner_html(answer),
    )


async def fetch_missing_via_browser(
    request_delay: float = 0.4,
    headless: bool = True,
    limit: int | None = None,
) -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    rows = db.problems_needing_detail()
    if limit is not None:
        rows = rows[:limit]
    log.info("Need to fetch %d problem details via browser", len(rows))
    if not rows:
        return

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()
            warm_url = f"{settings.source_base_url.rstrip('/')}/problem/source/{settings.source_book_id}"
            log.info("Warming up browser session via %s", warm_url)
            await page.goto(warm_url, timeout=60_000)
            await _wait_past_browser_check(page)
            log.info("Page title after challenge: %s", await page.title())

            ok = 0
            for idx, (berman_number, amk_id) in enumerate(rows, 1):
                url = f"{settings.source_base_url.rstrip('/')}/problem/{amk_id}"
                try:
                    await page.goto(url, timeout=45_000)
                    await _wait_past_browser_check(page, timeout_ms=15_000)
                    html = await page.content()
                    stmt, sol, ans = _parse_problem_html(html)
                    db.update_problem_html(berman_number, stmt, sol, ans)
                    ok += 1
                except Exception as e:
                    log.warning(
                        "Failed №%d (amk %d) at %s: %s",
                        berman_number,
                        amk_id,
                        url,
                        e,
                    )
                if idx % 25 == 0 or idx == len(rows):
                    log.info("  %d/%d (%d ok)", idx, len(rows), ok)
                if request_delay:
                    await asyncio.sleep(request_delay)
        finally:
            await browser.close()
    db.close()
    log.info("Done.")


def cli() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--request-delay",
        type=float,
        default=0.4,
        help="Sleep between requests (default 0.4s).",
    )
    p.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium with a visible window (debugging).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after fetching this many problems (for smoke tests).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(
        fetch_missing_via_browser(
            request_delay=args.request_delay,
            headless=not args.headed,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    cli()
