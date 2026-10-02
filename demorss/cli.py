import logging
import pprint
from typing import Optional, Annotated

import typer
import uvicorn

from . import api
from .api import api as api_app, api_config
from .async_cli import AsyncTyper
from .config import config_from_stream
from .logging_utils import LogRedactSecretFilter
from .main import get_demo_client, harvest_feed, sync_slug_feed

cli = AsyncTyper()


@cli.command()
async def harvest(
    feed_slugs: Annotated[
        Optional[list[str]],
        typer.Argument(metavar="[FEED_SLUG]..."),
    ] = None,
    config_stream: Annotated[
        Optional[typer.FileText],
        typer.Option("--config-file", "-c", encoding="utf-8", help="Configuration file"),
    ] = "config.yaml",
):
    """
    Download new audio stories from Demo
    """
    config = config_from_stream(config_stream)
    async with get_demo_client(config) as client:
        slugs = list(config.feeds.keys()) if feed_slugs is None else feed_slugs
        for slug in slugs:
            try:
                await harvest_feed(client, config, slug)
            except Exception as exc:
                print(f"[FAIL] Harvest of '{slug}' failed: {exc}")


@cli.command("sync")
def sync_feeds(
    feed_slugs: Annotated[
        Optional[list[str]],
        typer.Argument(metavar="[FEED_SLUG]..."),
    ] = None,
    config_stream: Annotated[
        Optional[typer.FileText],
        typer.Option("--config-file", "-c", encoding="utf-8", help="Configuration file"),
    ] = "config.yaml",
):
    """
    Regenerate RSS feeds from downloaded episodes
    """
    config = config_from_stream(config_stream)
    for slug in config.feeds.keys() if feed_slugs is None else feed_slugs:
        sync_slug_feed(config, slug)


@cli.command(
    name="serve",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def serve_api(
    ctx: typer.Context,
    config_stream: Annotated[
        Optional[typer.FileText],
        typer.Option("--config-file", "-c", encoding="utf-8", help="Configuration file"),
    ] = "config.yaml",
):
    """
    Serve RSS feeds and episode audio files

    Wrapper around uvicorn; supports passing additional options to uvicorn.run().
    """
    ctx.args.insert(0, f"{api.__name__}:api")
    config = config_from_stream(config_stream)
    api_app.dependency_overrides[api_config] = lambda: config

    secrets_to_redact = []
    if config.secret is not None:
        secrets_to_redact.append(config.secret)
    if config.users:
        secrets_to_redact.extend(u.secret for u in config.users)
    if secrets_to_redact:
        secret_filter = LogRedactSecretFilter(secrets_to_redact)
        logging.getLogger("uvicorn.access").addFilter(secret_filter)
        logging.getLogger("uvicorn.error").addFilter(secret_filter)

    uvicorn.main.main(args=ctx.args)


@cli.command(name="config")
def print_config(
    config_stream: Annotated[
        Optional[typer.FileText],
        typer.Option("--config-file", "-c", encoding="utf-8", help="Configuration file"),
    ] = "config.yaml",
):
    """
    Print the parsed configuration
    """
    pprint.pprint(config_from_stream(config_stream))


@cli.callback()
def callback():
    """
    Download Demo audio stories and serve them as private RSS feeds
    """
