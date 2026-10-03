"""Shared HTTP helpers for providers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

CACHE_DIR = Path(os.environ.get("FFBOT_CACHE_DIR", Path.home() / ".cache" / "ffbot"))
USER_AGENT = "ffbot/0.1 (personal fantasy football assistant)"


class ProviderError(RuntimeError):
    pass


def get_json(url: str, *, params=None, cookies=None, headers=None, timeout: int = 30):
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        resp = requests.get(url, params=params, cookies=cookies, headers=hdrs, timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(f"Network error calling {url}: {e}") from e
    if resp.status_code in (401, 403):
        raise ProviderError(
            f"{url} returned {resp.status_code}. For private ESPN leagues, check espn_s2 and SWID."
        )
    if not resp.ok:
        raise ProviderError(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def cached_json(name: str, max_age_hours: float, fetch):
    """Return fetch() result, caching it on disk for max_age_hours."""
    path = CACHE_DIR / f"{name}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return json.loads(path.read_text())
    data = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data
