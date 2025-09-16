from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:  # Optional dependency used only when explicitly enabled
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

logger = logging.getLogger("finance-mcp")

_DEFAULT_ALLOWED_HOSTS = {
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "news.google.com",
    "feeds.reuters.com",
    "feeds.a.dj.com",
    "rss.hankyung.com",
    "file.mk.co.kr",
    "www.yna.co.kr",
    "api.stlouisfed.org",
    "ecos.bok.or.kr",
    "opendart.fss.or.kr",
    "dart.fss.or.kr",
}


def _additional_hosts_from_env() -> set[str]:
    extra = os.getenv("FINANCE_NEWS_ALLOWED_HOSTS", "")
    hosts = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return hosts


ALLOWED_HOSTS = _DEFAULT_ALLOWED_HOSTS | _additional_hosts_from_env()
STRICT_SECURITY = os.getenv("FINANCE_NEWS_STRICT_SECURITY", "1") != "0"
ENABLE_CACHE = os.getenv("FINANCE_NEWS_ENABLE_CACHE", "0") == "1"


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("https_required")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("invalid_url")
    if STRICT_SECURITY and host not in ALLOWED_HOSTS:
        raise ValueError(f"host_not_allowed:{host}")


def _build_session() -> requests.Session:
    """Build an HTTP session with retry logic and optional caching."""
    if ENABLE_CACHE and requests_cache:
        try:
            requests_cache.install_cache("http_cache", expire_after=180)
            logger.info("requests-cache enabled (TTL=180s)")
        except Exception:
            logger.warning("failed_to_enable_cache", exc_info=True)
    s = requests.Session()
    s.trust_env = False  # ignore proxy/system settings unless explicitly configured
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.headers.update(
        {
            "User-Agent": "finnews-mcp/1.0 (+https://github.com/openai/codex-cli)",
            "Accept": "*/*",
        }
    )
    return s


SESSION = _build_session()


def _http_get(url: str, *, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    """HTTP GET using the shared session with strict URL validation."""
    _validate_url(url)
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


__all__ = ["SESSION", "_http_get", "_build_session"]
