import asyncio
import contextlib
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from rfeed import Feed, Image, Item, Guid, Enclosure, iTunes, iTunesItem

from .client import DemoClient
from .config import Config

STORY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,40}$")

DEFAULT_TITLE = "Demo"
DEFAULT_DESCRIPTION = "Demo — nyheter uten støy"
# Demo's "D" logo (the site favicon) rendered by Sanity as a 1400×1400 JPG on white
DEFAULT_IMAGE_URL = (
    "https://cdn.sanity.io/images/p4ow0o3m/production/"
    "d86890ee99c38fc26af10c8737a7583d152c463d-192x192.svg?w=1400&h=1400&fm=jpg&bg=ffffff&q=90"
)


# --- Client context manager ---

@contextlib.asynccontextmanager
async def get_demo_client(config: Config):
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = DemoClient(config, session)
        await client.login()
        yield client


# --- Path helpers ---

def build_feed_dir(config: Config, slug: str) -> Path:
    return Path(config.yield_dir) / slug


def build_feed_path(config: Config, slug: str, alias: Optional[str] = None) -> Path:
    base = config.feeds[slug].feed_name
    filename = f"{base}-{alias}.xml" if alias else f"{base}.xml"
    return build_feed_dir(config, slug) / filename


def build_episode_file_path(config: Config, slug: str, episode_id: str) -> Path:
    return build_feed_dir(config, slug) / f"{episode_id}.mp3"


def build_episode_meta_path(config: Config, slug: str, episode_id: str) -> Path:
    return build_feed_dir(config, slug) / f"{episode_id}.json"


def build_channel_meta_path(config: Config, slug: str) -> Path:
    return build_feed_dir(config, slug) / ".channel.json"


def get_secret_query_parameter(config: Config) -> str:
    if config.secret is None:
        return ""
    return f"?secret={config.secret}"


def harvested_episode_ids(config: Config, slug: str) -> list[str]:
    feed_dir = build_feed_dir(config, slug)
    if not feed_dir.is_dir():
        return []
    return [
        f.stem
        for f in feed_dir.iterdir()
        if f.is_file() and f.suffix == ".mp3" and not f.stem.endswith("_interim")
    ]


# --- Story parsing ---

def image_url(config: Config, image: Optional[dict], square: bool = False) -> Optional[str]:
    if not image:
        return None
    url = image.get("url") or (image.get("image") or {}).get("url")
    if not url:
        return None
    size = "w=1400&h=1400&fit=crop&crop=focalpoint" if square else "w=1400"
    return f"{config.api.image_base_url}/{url}?{size}&auto=format"


def extract_audio_url(story: dict) -> Optional[str]:
    # Only the story's own audio; `audio_paywall` holds a teaser for non-members
    files = (((story.get("story_content") or {}).get("meta") or {}).get("audioFiles")) or []
    return next((f for f in files if f.lower().split("?")[0].endswith(".mp3")), None)


def story_series_ids(story: dict) -> set[str]:
    ids = set(story.get("series_ids") or [])
    if story.get("series_id"):
        ids.add(story["series_id"])
    return ids


def story_authors(story: dict) -> str:
    names = []
    for a in story.get("authors") or ([story["author"]] if story.get("author") else []):
        c = a.get("author_content") or {}
        name = " ".join(p for p in (c.get("firstname"), c.get("lastname")) if p)
        if name:
            names.append(name)
    return " og ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else "".join(names)


def markdown_to_html(text: str) -> str:
    """The small Markdown dialect used in Demo's text blocks → show-notes HTML."""
    text = html.escape(text, quote=False)
    text = re.sub(r"\{\{(.+?)\}\}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", text)
    parts = []
    for para in re.split(r"\n\s*\n", text.strip()):
        heading = re.match(r"^#{1,6}\s+(.*?)(?:\n(.*))?$", para, re.S)
        if heading:
            parts.append(f"<h3>{heading.group(1).strip()}</h3>")
            para = heading.group(2) or ""
        if para.strip():
            parts.append("<p>" + para.strip().replace("\n", "<br>") + "</p>")
    return "".join(parts)


def story_body_html(content: dict) -> str:
    blocks = ((content.get("body") or {}).get("blocks")) or []
    return "".join(
        markdown_to_html(b["data"]["text"])
        for b in blocks
        if b.get("type") == "advtext" and (b.get("data") or {}).get("text")
    )


def episode_meta(config: Config, story: dict, audio_url: str) -> dict:
    content = (story.get("story_content") or {}).get("content") or {}
    teaser = (
        content.get("audio_description")
        or story.get("subhead")
        or content.get("emailPreview")
        or ""
    ).strip()
    description = (f"<p><strong>{html.escape(teaser)}</strong></p>" if teaser else "") + story_body_html(content)
    context = [c for c in (story.get("context") or []) if c]
    return {
        "id": story["story_id"],
        "title": (story.get("title") or "").strip() or story["story_id"],
        "description": description,
        "published_at": story.get("published_at"),
        "duration": story.get("audio_length") or 0,
        "author": story_authors(story) or (context[-1] if context else ""),
        "image_url": image_url(config, story.get("story_image") or story.get("cover_image")),
        "link": story.get("url") or f"https://www.demodemo.no/historie/{story['story_id']}",
        "audio_url": audio_url,
    }


def channel_meta_from_story(config: Config, story: dict, series_id: str) -> Optional[dict]:
    for s in story.get("series") or []:
        if s.get("series_id") == series_id:
            return {
                "title": s.get("name"),
                "description": s.get("description"),
                "image_url": image_url(config, s.get("cover_image"), square=True),
                "link": f"https://www.demodemo.no/serie/{series_id}",
            }
    return None


# --- Download ---

async def download_file(session: aiohttp.ClientSession, url: str, path: Path):
    interim = path.with_name(path.stem + "_interim.mp3")
    async with session.get(url) as response:
        response.raise_for_status()
        with interim.open("wb") as f:
            async for chunk in response.content.iter_chunked(65536):
                f.write(chunk)
    interim.rename(path)
    print(f"[INFO] Downloaded {path.name}")


# --- Feed builder ---

def load_episodes(config: Config, slug: str) -> list[dict]:
    episodes = []
    for episode_id in harvested_episode_ids(config, slug):
        try:
            episodes.append(json.loads(build_episode_meta_path(config, slug, episode_id).read_text()))
        except Exception as e:
            print(f"[WARN] Missing or unreadable metadata for '{slug}/{episode_id}': {e}")
    return episodes


def load_channel_meta(config: Config, slug: str) -> dict:
    feed_config = config.feeds[slug]
    try:
        meta = json.loads(build_channel_meta_path(config, slug).read_text())
    except Exception:
        meta = {}
    return {
        "title": feed_config.title or meta.get("title") or DEFAULT_TITLE,
        "description": feed_config.description or meta.get("description") or DEFAULT_DESCRIPTION,
        "image_url": feed_config.image_url or meta.get("image_url") or DEFAULT_IMAGE_URL,
        "link": meta.get("link") or "https://www.demodemo.no",
    }


def build_feed(config: Config, slug: str, episodes: list[dict], channel: dict, secret: Optional[str] = None) -> str:
    secret_query_param = f"?secret={secret}" if secret is not None else get_secret_query_parameter(config)
    unavailable_ids = {f.stem for f in build_feed_dir(config, slug).glob("*.unavailable")}
    items = []
    for e in episodes:
        episode_id = e["id"]
        title = f"[Ikke tilgjengelig] {e['title']}" if episode_id in unavailable_ids else e["title"]
        try:
            # rfeed always prints "GMT", so the date must actually be in UTC
            pub_date = datetime.fromisoformat(e["published_at"]).astimezone(timezone.utc)
        except Exception:
            pub_date = datetime.now(timezone.utc)
        try:
            file_size = build_episode_file_path(config, slug, episode_id).stat().st_size
        except FileNotFoundError:
            file_size = 0
        description = e.get("description") or ""
        if e.get("link"):
            description += f'<p><a href="{e["link"]}">Les på demodemo.no</a></p>'

        items.append(
            Item(
                title=title,
                description=description,
                link=e.get("link"),
                guid=Guid(episode_id, isPermaLink=False),
                enclosure=Enclosure(
                    url=f"{config.host}/{slug}/{episode_id}{secret_query_param}",
                    type="audio/mpeg",
                    length=file_size,
                ),
                pubDate=pub_date,
                extensions=[
                    iTunesItem(
                        author=e.get("author") or "Demo",
                        duration=e.get("duration") or 0,
                        image=e.get("image_url"),
                    )
                ],
            )
        )

    feed = Feed(
        title=channel["title"],
        link=channel["link"],
        description=channel["description"],
        language="no",
        image=Image(url=channel["image_url"], title=channel["title"], link=channel["link"]),
        items=sorted(items, key=lambda i: i.pubDate, reverse=True),
        extensions=[iTunes(author="Demo", image=channel["image_url"] or None, block="Yes")],
    )
    # rfeed's iTunesItem writes <itunes:order> even when unset
    return feed.rss().replace("<itunes:order>None</itunes:order>", "")


# --- Sync feeds ---

def sync_slug_feed(config: Config, slug: str):
    if slug not in config.feeds:
        print(f"[FAIL] The slug '{slug}' did not match any feeds in the config file")
        return
    feed_dir = build_feed_dir(config, slug)
    feed_dir.mkdir(parents=True, exist_ok=True)
    episodes = load_episodes(config, slug)
    channel = load_channel_meta(config, slug)
    count = f"{len(episodes)} episode{'s' if len(episodes) != 1 else ''}"

    if config.users:
        for user in config.users:
            rss = build_feed(config, slug, episodes, channel, secret=user.secret)
            build_feed_path(config, slug, alias=user.alias).write_text(rss, encoding="utf-8")
        print(f"[INFO] '{slug}' feed written for {len(config.users)} user{'s' if len(config.users) != 1 else ''} ({count})")
    else:
        build_feed_path(config, slug).write_text(build_feed(config, slug, episodes, channel), encoding="utf-8")
        print(f"[INFO] '{slug}' feed now serving {count}")


# --- Harvest ---

async def list_feed_stories(client: DemoClient, config: Config, slug: str) -> list[dict]:
    feed_config = config.feeds[slug]
    limit = feed_config.most_recent_episodes_limit
    if feed_config.series_id:
        source = client.series_library(feed_config.series_id)
    else:
        source = client.all_stories()
    excluded = set(feed_config.exclude_series_ids)

    stories = []
    async for story in source:
        if not story.get("has_audio") or not STORY_ID_PATTERN.match(story.get("story_id") or ""):
            continue
        if not feed_config.series_id and story_series_ids(story) & excluded:
            continue
        stories.append(story)
        if limit is not None and len(stories) >= limit:
            break
    return stories


async def harvest_feed(client: DemoClient, config: Config, slug: str):
    if slug not in config.feeds:
        print(f"[FAIL] The slug '{slug}' did not match any feeds in the config file")
        return

    feed_config = config.feeds[slug]
    print(f"[INFO] Fetching story list for '{slug}'...")
    stories = await list_feed_stories(client, config, slug)
    if not stories:
        print(f"[WARN] No stories with audio found for '{slug}'")
        return

    feed_dir = build_feed_dir(config, slug)
    feed_dir.mkdir(parents=True, exist_ok=True)
    for f in feed_dir.glob("*_interim.mp3"):
        print(f"[INFO] Removing stale interim file: {f.name}")
        f.unlink()

    existing_ids = set(harvested_episode_ids(config, slug))
    to_harvest = [s for s in stories if s["story_id"] not in existing_ids]

    limit = feed_config.most_recent_episodes_limit
    limit_note = f" (only looking at {limit} most recent)" if limit is not None else ""
    if not to_harvest:
        print(f"[INFO] Nothing new from '{slug}', all available episodes already harvested{limit_note}")
        sync_slug_feed(config, slug)
        return
    print(
        f"[INFO] Found {len(to_harvest)} new episode{'s' if len(to_harvest) != 1 else ''}"
        f" of '{slug}' ready to harvest{limit_note}"
    )

    placeholder = Path(__file__).parent.parent / "episode_not_available.mp3"
    sem = asyncio.Semaphore(config.api.max_concurrent_downloads)
    channel_meta = None

    async def download_one(listed: dict):
        nonlocal channel_meta
        episode_id = listed["story_id"]
        path = build_episode_file_path(config, slug, episode_id)
        async with sem:
            try:
                story = await client.story(episode_id)
                if feed_config.series_id and channel_meta is None:
                    channel_meta = channel_meta_from_story(config, story, feed_config.series_id)
                audio_url = extract_audio_url(story)
                if not audio_url:
                    raise ValueError("no MP3 in story")
                build_episode_meta_path(config, slug, episode_id).write_text(
                    json.dumps(episode_meta(config, story, audio_url), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                await download_file(client.session, audio_url, path)
            except Exception as exc:
                print(f"[WARN] Download failed for {episode_id}: {exc}")
                if path.exists():
                    path.unlink()
                if placeholder.exists() and build_episode_meta_path(config, slug, episode_id).exists():
                    shutil.copy2(placeholder, path)
                    path.with_suffix(".unavailable").touch()
                    print(f"[INFO] Placed unavailable-episode placeholder at {path.name}")

    await asyncio.gather(*[download_one(s) for s in to_harvest])

    if channel_meta:
        build_channel_meta_path(config, slug).write_text(
            json.dumps(channel_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    sync_slug_feed(config, slug)
