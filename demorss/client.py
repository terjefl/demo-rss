import json
from pathlib import Path
from time import time
from typing import AsyncIterator, Optional

import aiohttp

from .config import Config

USER_AGENT = "demorss/0.1 (+private RSS feed for a paying member)"


class DemoAuthError(Exception):
    pass


class DemoClient:
    """
    Minimal client for the API behind demodemo.no (api.demodemo.no).

    Series libraries and single stories are readable without auth; the full
    story stream (`stories/page`) needs a Supabase access token as Bearer.
    """

    def __init__(self, config: Config, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.access_token: Optional[str] = None

    # --- Auth (Supabase) ---

    def _token_path(self) -> Path:
        return Path(self.config.yield_dir) / ".tokens" / "demo.json"

    def _load_tokens(self) -> dict:
        try:
            return json.loads(self._token_path().read_text())
        except Exception:
            return {}

    def _save_tokens(self, data: dict):
        path = self._token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token"),
                    "expires_at": data.get("expires_at") or time() + data.get("expires_in", 3600),
                }
            )
        )
        path.chmod(0o600)

    async def _supabase_token(self, grant_type: str, body: dict) -> dict:
        auth = self.config.auth
        async with self.session.post(
            f"{auth.supabase_url}/auth/v1/token",
            params={"grant_type": grant_type},
            headers={"apikey": auth.supabase_key, "Content-Type": "application/json"},
            json=body,
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or "access_token" not in data:
                msg = data.get("error_description") or data.get("msg") or data.get("error") or response.status
                raise DemoAuthError(f"Supabase {grant_type} grant failed: {msg}")
            return data

    async def login(self):
        auth = self.config.auth
        if not auth.configured:
            return
        cached = self._load_tokens()
        if cached.get("access_token") and cached.get("expires_at", 0) > time() + 120:
            self.access_token = cached["access_token"]
            return

        refresh_token = cached.get("refresh_token") or auth.refresh_token
        data = None
        if refresh_token:
            try:
                data = await self._supabase_token("refresh_token", {"refresh_token": refresh_token})
            except DemoAuthError as e:
                print(f"[WARN] Token refresh failed, falling back to password: {e}")
        if data is None:
            if not (auth.email and auth.password):
                raise DemoAuthError("No valid refresh token and no email/password configured")
            print("[INFO] Authenticating with Demo...")
            data = await self._supabase_token("password", {"email": auth.email, "password": auth.password})
            print("[INFO] Authentication successful, token cached")
        self._save_tokens(data)
        self.access_token = data["access_token"]

    # --- API ---

    async def _get(self, path: str, params: Optional[dict] = None, auth: bool = False) -> dict:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        elif auth:
            raise DemoAuthError(f"{path} requires auth, but no credentials are configured")
        async with self.session.get(
            f"{self.config.api.base_url}/{path.lstrip('/')}", params=params, headers=headers
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _paginate(self, path: str, limit: Optional[int], auth: bool = False) -> AsyncIterator[dict]:
        cursor = None
        count = 0
        while True:
            data = await self._get(path, {"cursor": cursor} if cursor else None, auth=auth)
            for story in data.get("stories", []):
                yield story
                count += 1
                if limit is not None and count >= limit:
                    return
            cursor = data.get("cursor")
            if not data.get("has_more") or not cursor:
                return

    def series_library(self, series_id: str, limit: Optional[int] = None) -> AsyncIterator[dict]:
        return self._paginate(f"api/v1/consume/series/{series_id}/library", limit)

    def all_stories(self, limit: Optional[int] = None) -> AsyncIterator[dict]:
        return self._paginate("api/v1/consume/stories/page", limit, auth=True)

    async def story(self, story_id: str) -> dict:
        return await self._get(f"api/v1/consume/stories/{story_id}")
