"""Render problem statement / solution / answer to a single PNG image.

The HTML on amkbook.net uses MathJax 2 with `\\(...\\)` and `\\[...\\]` delimiters.
We embed the same configuration in a tiny standalone HTML page, load it inside
a headless Chromium tab via Playwright, wait for MathJax typesetting to finish,
and screenshot the rendered article.

Run as:

    python -m berman_bot.renderer            # render every problem with a solution
    python -m berman_bot.renderer --berman 1 # render a single problem
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, Page, async_playwright

from .config import get_settings
from .db import Database, Problem

log = logging.getLogger(__name__)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Задача №{berman_number}</title>
<style>
  body {{
    margin: 0;
    padding: 24px;
    background: #ffffff;
    color: #1a1a1a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 18px;
    line-height: 1.55;
    width: 880px;
  }}
  h1 {{
    margin: 0 0 16px 0;
    font-size: 26px;
    color: #0d3b66;
    border-bottom: 2px solid #0d3b66;
    padding-bottom: 6px;
  }}
  h2 {{
    margin: 18px 0 8px 0;
    font-size: 20px;
    color: #0d3b66;
  }}
  section {{
    margin-bottom: 14px;
  }}
  .answer {{
    background: #f3f7fb;
    border-left: 4px solid #0d3b66;
    padding: 10px 14px;
    border-radius: 4px;
  }}
  p {{ margin: 6px 0; }}
  img {{ max-width: 100%; height: auto; }}
  .source {{
    margin-top: 18px;
    color: #666;
    font-size: 14px;
  }}
  .nowrap {{ white-space: nowrap; }}
</style>
<script type="text/x-mathjax-config">
  MathJax.Hub.Config({{
    showMathMenu: false,
    showProcessingMessages: false,
    messageStyle: "none",
    tex2jax: {{
      inlineMath: [["\\\\(","\\\\)"]],
      displayMath: [["\\\\[","\\\\]"]],
      processEscapes: false
    }},
    TeX: {{
      Macros: {{
        le: "\\\\leqslant",
        ge: "\\\\geqslant",
        Im: "\\\\operatorname{{Im}}",
        Re: "\\\\operatorname{{Re}}",
        arctg: "\\\\operatorname{{arctg}}",
        arcctg: "\\\\operatorname{{arcctg}}",
        tg: "\\\\operatorname{{tg}}",
        ctg: "\\\\operatorname{{ctg}}",
        rang: "\\\\operatorname{{rang}}"
      }}
    }}
  }});
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.9/MathJax.js?config=TeX-MML-AM_CHTML"></script>
</head>
<body>
<article id="root">
<h1>Задача №{berman_number}</h1>
{statement_block}
{solution_block}
{answer_block}
{source_block}
</article>
</body>
</html>
"""


def _block(title: str, html: str | None, css_class: str = "") -> str:
    if not html or not html.strip():
        return ""
    cls = f' class="{css_class}"' if css_class else ""
    return f'<section{cls}><h2>{title}</h2>{html}</section>'


def build_html(problem: Problem) -> str:
    statement_block = _block("Условие", problem.statement_html)
    solution_block = _block("Решение", problem.solution_html)
    answer_block = _block("Ответ", problem.answer_html, css_class="answer")
    if problem.source_url:
        source_block = (
            f'<div class="source">Источник: '
            f'<a href="{problem.source_url}">{problem.source_url}</a></div>'
        )
    else:
        source_block = ""
    return HTML_TEMPLATE.format(
        berman_number=problem.berman_number,
        statement_block=statement_block,
        solution_block=solution_block,
        answer_block=answer_block,
        source_block=source_block,
    )


async def _render_one(page: Page, problem: Problem, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(problem)
    await page.set_content(html, wait_until="domcontentloaded", timeout=30000)

    # Poll for MathJax to be ready, then queue a typeset and wait for the queue to drain.
    await page.wait_for_function(
        "() => window.MathJax && window.MathJax.Hub && window.MathJax.Hub.Queue",
        timeout=20000,
    )
    await page.evaluate(
        """
        () => new Promise(resolve => {
          window.MathJax.Hub.Queue(["Typeset", window.MathJax.Hub]);
          window.MathJax.Hub.Queue(resolve);
        })
        """
    )
    # Wait until MathJax has produced output spans inside the article.
    await page.wait_for_function(
        """
        () => {
          const root = document.getElementById('root');
          if (!root) return false;
          const raw = root.innerHTML.includes('\\\\(') || root.innerHTML.includes('\\\\[');
          const out = root.querySelector('.MathJax, .MathJax_Display, .MathJax_CHTML, .mjx-chtml, span[id^="MathJax-Element"]');
          return !raw || out !== null;
        }
        """,
        timeout=15000,
    )
    await page.wait_for_timeout(200)
    path = output_dir / f"{problem.berman_number}.png"
    el = await page.query_selector("article#root")
    if el is None:
        await page.screenshot(path=str(path), full_page=True)
    else:
        await el.screenshot(path=str(path))
    return path


async def render_all(
    only_berman: list[int] | None = None,
    overwrite: bool = False,
    concurrency: int = 1,
) -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    images_dir = settings.images_dir
    images_dir.mkdir(parents=True, exist_ok=True)

    if only_berman:
        problems = [
            p
            for p in (db.get_problem_by_berman_number(n) for n in only_berman)
            if p is not None
        ]
    else:
        problems = list(db.problems_without_image()) if not overwrite else _all_with_solution(db)

    log.info("Rendering %d problem(s)", len(problems))
    if not problems:
        return

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": 960, "height": 800},
                device_scale_factor=2,
            )
            try:
                if concurrency <= 1:
                    page = await context.new_page()
                    try:
                        for i, problem in enumerate(problems, 1):
                            await _render_and_store(page, problem, images_dir, db)
                            if i % 25 == 0:
                                log.info("  rendered %d/%d", i, len(problems))
                    finally:
                        await page.close()
                else:
                    sem = asyncio.Semaphore(concurrency)

                    async def render_with_own_page(problem: Problem) -> None:
                        async with sem:
                            page = await context.new_page()
                            try:
                                await _render_and_store(page, problem, images_dir, db)
                            finally:
                                await page.close()

                    await asyncio.gather(*(render_with_own_page(p) for p in problems))
            finally:
                await context.close()
        finally:
            await browser.close()

    db.close()
    log.info("Done.")


def _all_with_solution(db: Database) -> list[Problem]:
    cur = db._conn.execute(
        "SELECT * FROM problems WHERE has_solution = 1 ORDER BY berman_number"
    )
    from .db import _row_to_problem
    return [_row_to_problem(r) for r in cur.fetchall()]


async def _render_and_store(
    page: Page, problem: Problem, output_dir: Path, db: Database
) -> None:
    try:
        path = await _render_one(page, problem, output_dir)
    except Exception as e:
        log.warning("Failed to render problem %d: %s", problem.berman_number, e)
        return
    db.update_image_path(problem.id, str(path))
    # Invalidate cached telegram_file_id so that the bot re-uploads next time.
    db._conn.execute(
        "UPDATE problems SET telegram_file_id = NULL WHERE id = ?",
        (problem.id,),
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="Render problem solutions to PNG via Playwright + MathJax.")
    parser.add_argument(
        "--berman",
        type=int,
        action="append",
        help="Render only this Berman problem number (repeatable).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-render even if image_path is already set.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent renders (each opens a Chromium tab).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    asyncio.run(
        render_all(
            only_berman=args.berman,
            overwrite=args.overwrite,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    cli()
