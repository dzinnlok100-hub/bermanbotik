# Berman Bot

Telegram bot serving solutions to problems from Берман, "Сборник задач по курсу математического анализа"
(4400 problems across 14 chapters).

Solutions are sourced from [amkbook.net](https://amkbook.net/problem/source/1) and rendered as
PNG images so MathJax formulas display perfectly inside Telegram.

See [README full content below](#features) for setup, parsing, and deployment instructions.

## Features

- Browse: chapters → paragraphs → problems via inline keyboards.
- Search: send a Berman problem number (e.g. `1234`) to get the solution instantly.
- Solutions are sent as pre-rendered PNG photos with MathJax formulas.
- Telegram CDN caching: each photo is uploaded once, then served via `file_id`.
- Admin commands to fill in missing solutions over time.

## Quick start (development)

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
playwright install --with-deps chromium

cp .env.example .env
# edit .env and set TELEGRAM_BOT_TOKEN

# 1. Scrape source site (chapters, paragraphs, problems, HTML)
python -m berman_bot.parser

# 2. Render PNG images for all parsed solutions
python -m berman_bot.renderer

# 3. Run the bot
python -m berman_bot
```

## Project layout

- `src/berman_bot/` — application source.
  - `bot.py` — aiogram entrypoint.
  - `parser.py` — scrapes amkbook.net.
  - `renderer.py` — renders solution HTML to PNG via Playwright + MathJax.
  - `db.py` — SQLite storage.
  - `handlers/` — Telegram handlers (navigation, search, admin, start).
- `data/` — runtime state (gitignored).
  - `bot.db` — SQLite database.
  - `images/` — rendered PNGs.

## Deployment

The bot uses long polling, so any Linux host with Python 3.11+ works.
A `Dockerfile` is provided for containerised deployments.

See [DEPLOY.md](DEPLOY.md) for VPS, Fly.io, and Railway recipes.
