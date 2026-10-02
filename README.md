# demo-rss

Download audio stories from [Demo](https://www.demodemo.no) and serve them as private RSS feeds for your own podcast app (Overcast, Pocket Casts, …).

> For paying Demo members only, for personal use. Don't share your feeds — they contain members-only journalism.

Built in the style of [pasjonsfrukt](https://github.com/terjefl/pasjonsfrukt) and [podimo](https://github.com/terjefl/podimo): episodes are downloaded and stored locally, a cron job harvests new ones, and a small FastAPI server serves the feeds and MP3s behind a secret.

### How it works

demodemo.no runs on the same platform as Zetland. Its API (`api.demodemo.no`) exposes:

| Endpoint | Auth | Used for |
|---|---|---|
| `api/v1/consume/series/<series_id>/library` | none | Episode list for a series (Morgenfugl, Demontert, …) |
| `api/v1/consume/stories/page` | Bearer | All stories, newest first |
| `api/v1/consume/stories/<story_id>` | none | Story details incl. `story_content.meta.audioFiles` (MP3) |

Login is Supabase (`db.demodemo.no`); the access token lives one hour, so the harvester logs in with email/password (or a refresh token) and caches the tokens in `yield/.tokens/`.

---

### Docker Compose

```yaml
services:
  demorss:
    image: ghcr.io/terjefl/demo-rss:latest
    container_name: demorss
    restart: unless-stopped
    ports:
      - "8300:8000"
    environment:
      - TZ=Europe/Oslo
    volumes:
      - /path/to/config.yaml:/app/config.yaml:ro
      - /path/to/crontab:/etc/cron.d/demorss-crontab:ro
      - /path/to/podcast/files:/app/yield
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/openapi.json || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

The crontab controls when harvesting runs (see [`docker/crontab.example`](docker/crontab.example)):

```cron
*/15 5-22 * * * cd /app || exit 1; PATH=$PATH:/usr/local/bin demorss harvest >> /var/log/demorss.log 2>&1
```

---

### Configuration

Copy [`config.template.yaml`](config.template.yaml) to `config.yaml` and fill in your details.

#### `host`

Public base URL of your instance, used in feed and episode links.

#### `secret` / `users`

Same as podimo: either one shared `?secret=` for everyone, or per-user secrets with a separate feed file per user.

#### `auth`

Your Demo account. Only needed for feeds without `series_id` (all stories). Either `email` + `password`, or — if you sign in with Google/Apple/Facebook — `refresh_token` from a logged-in browser session as a one-time seed (the harvester keeps the rotated token afterwards).

#### `feeds`

| Key | Description |
|---|---|
| `series_id` | UUID from `demodemo.no/serie/<series_id>`. Omit for all stories with audio. |
| `exclude_series_ids` | Series to leave out of an all-stories feed |
| `title`, `description`, `image_url` | Override the channel metadata (read from the series by default; feeds without a series get the Demo logo) |
| `feed_name` | Base filename of the RSS XML (default `feed`) |
| `most_recent_episodes_limit` | Only harvest the N newest stories (default 30, `null` for all) |

Known series:

| Series | `series_id` |
|---|---|
| Morgenfugl | `a7027044-3eb2-4e4d-9e96-18c8202d8180` |
| Demontert | `bdea66d7-d802-4814-85d5-f2952554cffa` |

---

### Usage

```
demorss harvest [FEED_SLUG]...   # download new episodes and rebuild feeds
demorss sync [FEED_SLUG]...      # rebuild feeds from what's on disk
demorss serve                    # serve feeds (wraps uvicorn)
```

Feeds are served at `<host>/<feed_slug>?secret=<secret>`, and the index page at `<host>/?secret=<secret>` has one-tap Overcast and Pocket Casts buttons.
