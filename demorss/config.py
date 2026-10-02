from dataclasses import dataclass, field
from io import TextIOWrapper
from typing import Optional

from dataclass_wizard import YAMLWizard


@dataclass
class Auth:
    # Log in with email + password (Supabase password grant) ...
    email: Optional[str] = None
    password: Optional[str] = None
    # ... or seed with a refresh token (for accounts using Google/Apple/Facebook login).
    # Refresh tokens rotate; the newest one is kept in yield_dir/.tokens/.
    refresh_token: Optional[str] = None
    # Public Supabase endpoint and publishable key used by demodemo.no itself
    supabase_url: str = "https://db.demodemo.no"
    supabase_key: str = "sb_publishable_v01jY7bCEJq6wKEwD6CZcA_924EtzMo"

    @property
    def configured(self) -> bool:
        return bool((self.email and self.password) or self.refresh_token)


@dataclass
class Feed:
    # Series UUID from demodemo.no/serie/<series_id>. Omit to include all stories with audio
    # (requires auth).
    series_id: Optional[str] = None
    # Series to leave out — only used when series_id is omitted
    exclude_series_ids: list[str] = field(default_factory=list)
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    feed_name: str = "feed"
    most_recent_episodes_limit: Optional[int] = 30


@dataclass
class ApiConfig:
    base_url: str = "https://api.demodemo.no"
    image_base_url: str = "https://demodemo.imgix.net"
    max_concurrent_downloads: int = 3


@dataclass
class User:
    alias: str
    secret: str


@dataclass
class Config(YAMLWizard):
    host: str
    feeds: dict[str, Optional[Feed]]
    auth: Auth = field(default_factory=Auth)
    yield_dir: str = "yield"
    secret: Optional[str] = None
    disable_index: bool = False
    users: list[User] = field(default_factory=list)
    api: ApiConfig = field(default_factory=ApiConfig)

    def __post_init__(self):
        self.feeds = {k: (v if v is not None else Feed()) for k, v in self.feeds.items()}


def config_from_stream(stream: TextIOWrapper) -> Config:
    return Config.from_yaml(stream)
