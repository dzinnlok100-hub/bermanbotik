# Deployment

The bot uses Telegram **long polling**, so it doesn't need an HTTP webhook
or a public IP. Any Linux machine with Python 3.11+ (or Docker) works.

The bot needs:

- A persistent directory for `bot.db` and rendered images (~50–250 MB once
  fully populated).
- Outbound HTTPS access to `api.telegram.org`. For initial scraping &
  rendering, also outbound access to `amkbook.net` and a CDN that serves
  MathJax (`cdnjs.cloudflare.com`).

## 1. Bare-metal / VPS via systemd

```bash
# On the server
sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv git
git clone https://github.com/dzinnlok100-hub/bermanbotik.git /opt/berman-bot
cd /opt/berman-bot
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
playwright install --with-deps chromium

cp .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN and ADMIN_USER_IDS

# One-off data prep (can take several minutes for full DB):
python -m berman_bot.parser
python -m berman_bot.renderer

# Optionally extract problem statements from the Berman PDF:
python -m berman_bot.pdf_extractor --pdf /path/to/berman.pdf
```

Create `/etc/systemd/system/berman-bot.service`:

```ini
[Unit]
Description=Berman Bot
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/berman-bot
EnvironmentFile=/opt/berman-bot/.env
ExecStart=/opt/berman-bot/.venv/bin/python -m berman_bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now berman-bot
sudo systemctl status berman-bot
sudo journalctl -fu berman-bot   # tail logs
```

## 2. Docker

```bash
docker build -t berman-bot .
docker run -d --name berman-bot \
    --restart=unless-stopped \
    -e TELEGRAM_BOT_TOKEN=xxxx:yyyy \
    -e ADMIN_USER_IDS=12345678 \
    -v /srv/berman-bot/data:/app/data \
    berman-bot
```

To populate the DB before going live:

```bash
docker run --rm -v /srv/berman-bot/data:/app/data \
    -e TELEGRAM_BOT_TOKEN=dummy \
    berman-bot python -m berman_bot.parser

docker run --rm -v /srv/berman-bot/data:/app/data \
    -e TELEGRAM_BOT_TOKEN=dummy \
    berman-bot python -m berman_bot.renderer
```

## 3. Fly.io

A `fly.toml` is provided (see template below). The free tier of Fly is enough
for a small Telegram bot (long polling has minimal idle CPU usage).

```toml
app = "berman-bot"
primary_region = "fra"

[build]
  dockerfile = "Dockerfile"

[mounts]
  source = "berman_data"
  destination = "/app/data"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
```

```bash
fly launch --copy-config --no-deploy
fly secrets set TELEGRAM_BOT_TOKEN=xxxx:yyyy ADMIN_USER_IDS=12345678
fly volumes create berman_data --size 1
fly deploy
```

After deploy you'll need to seed the DB once. Either run the parser locally
and `fly volumes ssh` upload the `.db`, or `fly ssh console` and run
`python -m berman_bot.parser` in the container.

## 4. Railway, Render, Heroku-likes

The bot speaks long polling so it can run on any Docker-compatible PaaS.
Make sure persistent storage is attached at `/app/data` and that your dyno /
machine has at least 512 MB RAM (Chromium during rendering).

If your platform doesn't support persistent volumes on the free tier, render
the images locally and copy `data/` into the image at build time.

## Updating the data

```bash
# add new solutions from amkbook.net
python -m berman_bot.parser

# render any newly added problems
python -m berman_bot.renderer

# add a hand-written solution via Telegram
/add 1234 Решение: ...
```

The bot caches Telegram `file_id`s in the DB so each photo is only uploaded
once. After re-rendering an image (e.g. you fixed a typo), the bot will
re-upload it on the next request automatically.
