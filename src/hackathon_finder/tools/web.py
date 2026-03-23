"""Shared web tools for fetching and inspecting pages.

Provides fetch_page and check_link tool definitions and executors,
page metadata extraction, retry logic, and an optional response cache.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# --- SSRF protection ---


def _validate_url(url: str) -> str | None:
    """Return an error string if *url* is unsafe to fetch, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Blocked: only http/https allowed"
    hostname = parsed.hostname
    if not hostname:
        return "Blocked: no hostname in URL"
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return f"Blocked: cannot resolve hostname {hostname}"
    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_unspecified:
            return f"Blocked: {hostname} resolves to private/reserved address {addr}"
    return None


# --- Redirect-safe fetch helpers ---

_MAX_REDIRECTS = 5


async def _safe_get(url: str, http_client: httpx.AsyncClient) -> httpx.Response:
    """GET with manual redirect following — validates every hop."""
    err = _validate_url(url)
    if err:
        raise ValueError(err)
    original_scheme = urlparse(url).scheme
    current_url = url
    for _ in range(_MAX_REDIRECTS):
        resp = await http_client.get(current_url, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                return resp
            # Resolve relative redirects against the response URL
            from urllib.parse import urljoin
            current_url = urljoin(str(resp.url), location)
            if original_scheme == "https" and not current_url.startswith("https://"):
                raise ValueError("Redirect blocked: HTTPS to HTTP downgrade")
            err = _validate_url(current_url)
            if err:
                raise ValueError(f"Redirect blocked: {err}")
            continue
        return resp
    raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS}) starting from {url}")


async def _safe_head(url: str, http_client: httpx.AsyncClient) -> httpx.Response:
    """HEAD with manual redirect following — validates every hop."""
    err = _validate_url(url)
    if err:
        raise ValueError(err)
    original_scheme = urlparse(url).scheme
    current_url = url
    for _ in range(_MAX_REDIRECTS):
        resp = await http_client.head(current_url, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                return resp
            from urllib.parse import urljoin
            current_url = urljoin(str(resp.url), location)
            if original_scheme == "https" and not current_url.startswith("https://"):
                raise ValueError("Redirect blocked: HTTPS to HTTP downgrade")
            err = _validate_url(current_url)
            if err:
                raise ValueError(f"Redirect blocked: {err}")
            continue
        return resp
    raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS}) starting from {url}")


# --- Page metadata extraction ---


@dataclass
class PageMeta:
    """Metadata extracted from an event's actual page."""
    url: str
    title: str = ""
    og_title: str = ""
    og_description: str = ""
    og_type: str = ""
    meta_description: str = ""
    json_ld: dict = field(default_factory=dict)
    status_code: int = 0
    error: str = ""


_OG_RE = {
    "og_title": re.compile(r'<meta\s+(?:property|name)=["\']og:title["\']\s+content=["\'](.*?)["\']', re.I),
    "og_description": re.compile(r'<meta\s+(?:property|name)=["\']og:description["\']\s+content=["\'](.*?)["\']', re.I),
    "og_type": re.compile(r'<meta\s+(?:property|name)=["\']og:type["\']\s+content=["\'](.*?)["\']', re.I),
}
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.I)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.DOTALL,
)

# Regex to strip HTML tags for readable text extraction
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _extract_page_meta(url: str, html: str, status_code: int) -> PageMeta:
    """Extract metadata from HTML."""
    meta = PageMeta(url=url, status_code=status_code)
    head = html[:10_000]

    m = _TITLE_RE.search(head)
    if m:
        meta.title = m.group(1).strip()

    for attr, regex in _OG_RE.items():
        m = regex.search(head)
        if m:
            setattr(meta, attr, m.group(1).strip())

    m = _META_DESC_RE.search(head)
    if m:
        meta.meta_description = m.group(1).strip()

    for m in _JSON_LD_RE.finditer(html[:100_000]):
        try:
            ld = json.loads(m.group(1))
            if isinstance(ld, dict) and ld.get("@type") == "Event":
                meta.json_ld = ld
                break
            if isinstance(ld, list):
                for item in ld:
                    if isinstance(item, dict) and item.get("@type") == "Event":
                        meta.json_ld = item
                        break
                if meta.json_ld:
                    break
        except json.JSONDecodeError:
            continue

    return meta


def _html_to_text(html: str, max_chars: int = 6000) -> str:
    """Strip HTML tags and collapse whitespace for readable text."""
    # Strip script and style blocks including content
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.DOTALL)
    text = _TAG_RE.sub(' ', html)
    text = _WS_RE.sub(' ', text).strip()
    return text[:max_chars]


def _summarize_json_ld(ld: dict) -> str:
    """Extract key fields from JSON-LD Event, avoiding huge description blobs."""
    parts = []
    if ld.get("name"):
        parts.append(f"Name: {ld['name']}")
    if ld.get("eventAttendanceMode"):
        mode = ld["eventAttendanceMode"].split("/")[-1]
        parts.append(f"Attendance Mode: {mode}")
    loc = ld.get("location", {})
    if isinstance(loc, dict):
        addr = loc.get("address", {})
        if isinstance(addr, dict):
            loc_parts = [addr.get("name", ""), addr.get("addressLocality", ""),
                         addr.get("addressRegion", ""), addr.get("streetAddress", "")]
            loc_str = ", ".join(p for p in loc_parts if p)
            if loc_str:
                parts.append(f"Location: {loc_str}")
        elif loc.get("name"):
            parts.append(f"Location: {loc['name']}")
    if ld.get("startDate"):
        parts.append(f"Start: {ld['startDate']}")
    if ld.get("endDate"):
        parts.append(f"End: {ld['endDate']}")
    # Extract venue info from description (often has "Where:" lines)
    desc = ld.get("description", "")
    if desc:
        desc_text = _TAG_RE.sub(' ', desc)
        desc_text = _WS_RE.sub(' ', desc_text).strip()
        parts.append(f"Description: {desc_text[:1500]}")
    return "\n".join(parts)


# --- Response cache ---

_cache: dict[str, tuple[float, str]] = {}
_cache_ttl: float = 0  # 0 means disabled
_MAX_CACHE_ENTRIES = 200


def enable_cache(ttl_seconds: float = 3600) -> None:
    """Enable the module-level response cache with a TTL in seconds."""
    global _cache_ttl
    _cache_ttl = ttl_seconds


def clear_cache() -> None:
    """Clear all cached responses and disable the cache."""
    global _cache_ttl
    _cache.clear()
    _cache_ttl = 0


def _cache_get(url: str, namespace: str = "") -> str | None:
    """Return cached response text if present and not expired, else None."""
    if _cache_ttl <= 0:
        return None
    key = f"{namespace}:{url}" if namespace else url
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _cache_ttl:
        del _cache[key]
        return None
    return value


def _cache_put(url: str, value: str, namespace: str = "") -> None:
    """Store a response in the cache if caching is enabled."""
    if _cache_ttl > 0:
        key = f"{namespace}:{url}" if namespace else url
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            # Evict oldest entry
            oldest_key = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest_key]
        _cache[key] = (time.monotonic(), value)


# --- Retry helper ---

_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]


async def _retry_http(coro_factory, url: str) -> Any:
    """Retry an async HTTP call with exponential backoff.

    Args:
        coro_factory: A zero-arg callable that returns a new awaitable each call.
        url: The URL (for logging).

    Returns:
        The httpx.Response on success.

    Raises:
        The last exception after all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _BACKOFF_SECONDS[attempt]
                logger.debug("Retry %d/%d for %s after %ss: %s",
                             attempt + 1, _MAX_RETRIES, url, delay, exc)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


# --- Tool definitions ---

FETCH_PAGE_TOOL: dict = {
    "name": "fetch_page",
    "description": (
        "Fetch a URL and extract its title, OpenGraph tags, JSON-LD key fields, "
        "and a readable text snippet. Use this to verify event details. Pay close "
        "attention to the description text for venue/location info — structured "
        "metadata is often wrong."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch"},
        },
        "required": ["url"],
    },
}

CHECK_LINK_TOOL: dict = {
    "name": "check_link",
    "description": (
        "Send a HEAD request to a URL and return the HTTP status code and final "
        "redirect URL. Use this for quick link validation without downloading "
        "the full page."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to check"},
        },
        "required": ["url"],
    },
}

SEARCH_WEB_TOOL: dict = {
    "name": "search_web",
    "description": (
        "Search the web using DuckDuckGo and return titles, URLs, and snippets "
        "for the top results. Use this to discover hackathon listings, event "
        "pages, and other relevant links."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

WEB_TOOLS: list[dict] = [FETCH_PAGE_TOOL, CHECK_LINK_TOOL, SEARCH_WEB_TOOL]


# --- DuckDuckGo HTML parsing ---

_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
    re.I | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.I | re.DOTALL,
)
_DDG_URL = "https://html.duckduckgo.com/html/"


def _parse_ddg_html(html: str, max_results: int = 5) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML search results into a list of dicts."""
    # Split by result blocks
    blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*results_links[^"]*"', html)
    results: list[dict[str, str]] = []
    for block in blocks[1:]:  # skip preamble before first result
        if len(results) >= max_results:
            break
        link_m = _DDG_RESULT_RE.search(block)
        if not link_m:
            continue
        url = link_m.group(1).strip()
        title = _TAG_RE.sub('', link_m.group(2)).strip()
        snippet = ""
        snip_m = _DDG_SNIPPET_RE.search(block)
        if snip_m:
            snippet = _TAG_RE.sub('', snip_m.group(1)).strip()
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


# --- Tool execution ---


async def execute_fetch_page(url: str, http_client: httpx.AsyncClient) -> str:
    """Execute fetch_page tool — GET + extract metadata + readable text."""
    cached = _cache_get(url, namespace="fetch_page")
    if cached is not None:
        return cached

    try:
        resp = await _retry_http(lambda: _safe_get(url, http_client), url)
        meta = _extract_page_meta(url, resp.text, resp.status_code)
        readable = _html_to_text(resp.text)

        parts = [f"Status: {resp.status_code}", f"Final URL: {str(resp.url)}"]
        if meta.title:
            parts.append(f"Title: {meta.title}")
        if meta.og_title:
            parts.append(f"OG Title: {meta.og_title}")
        if meta.og_description:
            parts.append(f"OG Description: {meta.og_description}")
        if meta.meta_description:
            parts.append(f"Meta Description: {meta.meta_description}")
        if meta.json_ld:
            parts.append(f"JSON-LD Event:\n{_summarize_json_ld(meta.json_ld)}")
        if readable:
            parts.append(f"Readable text:\n{readable}")

        result = "\n".join(parts)
        _cache_put(url, result, namespace="fetch_page")
        return result
    except Exception as e:
        return f"Error fetching {url}: {e}"


async def execute_check_link(url: str, http_client: httpx.AsyncClient) -> str:
    """Execute check_link tool — HEAD request for status + redirect."""
    cached = _cache_get(url, namespace="check_link")
    if cached is not None:
        return cached

    try:
        resp = await _retry_http(lambda: _safe_head(url, http_client), url)
        result = f"Status: {resp.status_code}\nFinal URL: {str(resp.url)}"
        _cache_put(url, result, namespace="check_link")
        return result
    except Exception as e:
        return f"Error checking {url}: {e}"


async def execute_search_web(
    query: str, http_client: httpx.AsyncClient, max_results: int = 5,
) -> str:
    """Execute search_web tool — search DuckDuckGo and return formatted results."""
    max_results = min(max_results, 20)
    from urllib.parse import urlencode

    url = f"{_DDG_URL}?{urlencode({'q': query})}"
    try:
        resp = await _retry_http(
            lambda: _safe_get(url, http_client), url,
        )
        results = _parse_ddg_html(resp.text, max_results)
        if not results:
            return f"No results found for: {query}"
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines).rstrip()
    except Exception as e:
        return f"Error searching for '{query}': {e}"


async def execute_web_tool(
    name: str, input_data: dict, http_client: httpx.AsyncClient
) -> str | None:
    """Dispatch a web tool by name. Returns None if name is not a web tool."""
    if name == "fetch_page":
        return await execute_fetch_page(input_data["url"], http_client)
    elif name == "check_link":
        return await execute_check_link(input_data["url"], http_client)
    elif name == "search_web":
        return await execute_search_web(
            input_data["query"], http_client,
            max_results=input_data.get("max_results", 5),
        )
    return None
