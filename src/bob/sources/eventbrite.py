"""Eventbrite source — extracts __SERVER_DATA__ from public search page."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import httpx

from bob.models import Format, Hackathon, RegistrationStatus
from bob.sources.base import Source

logger = logging.getLogger(__name__)

SF_SEARCH = "https://www.eventbrite.com/d/ca--san-francisco/hackathon/"
ONLINE_SEARCH = "https://www.eventbrite.com/d/online/hackathon/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_date(date_str: str | None, time_str: str | None) -> datetime | None:
    """Parse Eventbrite date + time strings like '2026-03-24' + '18:00'."""
    if not date_str:
        return None
    combined = date_str
    if time_str:
        combined = f"{date_str}T{time_str}"
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(combined, fmt)
        except ValueError:
            continue
    return None


def _extract_server_data(html: str) -> dict:
    """Extract __SERVER_DATA__ JSON from Eventbrite search page."""
    start_marker = "__SERVER_DATA__ = "
    idx = html.find(start_marker)
    if idx < 0:
        return {}
    idx += len(start_marker)

    # Walk braces to find the end of the JSON object
    depth = 0
    for i, c in enumerate(html[idx:idx + 500_000], idx):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if depth == 0:
            try:
                return json.loads(html[idx : i + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def _extract_events(html: str, is_online: bool = False) -> list[Hackathon]:
    """Extract events from Eventbrite's embedded __SERVER_DATA__."""
    data = _extract_server_data(html)
    events = data.get("search_data", {}).get("events", {}).get("results", [])

    results: list[Hackathon] = []
    for ev in events:
        name = ev.get("name", "")
        url = ev.get("url", "")
        if not name or not url:
            continue

        # Format
        if is_online or ev.get("is_online_event"):
            fmt = Format.VIRTUAL
            location = "Online"
        else:
            fmt = Format.IN_PERSON
            venue = ev.get("primary_venue") or {}
            addr = venue.get("address") or {}
            city = addr.get("city", "")
            region = addr.get("region", "")
            location = f"{city}, {region}".strip(", ") or venue.get("name", "")

        # Image
        image = ev.get("image", {})
        image_url = image.get("url", "") if isinstance(image, dict) else ""

        results.append(Hackathon(
            name=name,
            url=url,
            source="eventbrite",
            format=fmt,
            location=location or "Online",
            start_date=_parse_date(ev.get("start_date"), ev.get("start_time")),
            end_date=_parse_date(ev.get("end_date"), ev.get("end_time")),
            registration_status=RegistrationStatus.OPEN,
            image_url=image_url,
            description=ev.get("summary", ""),
        ))

    return results


class EventbriteSource(Source):
    name = "eventbrite"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []
        seen_urls: set[str] = set()
        headers = {"User-Agent": UA}

        async with httpx.AsyncClient(timeout=15.0) as client:
            if sf:
                try:
                    resp = await client.get(SF_SEARCH, headers=headers)
                    resp.raise_for_status()
                    for h in _extract_events(resp.text, is_online=False):
                        if h.url not in seen_urls:
                            seen_urls.add(h.url)
                            results.append(h)
                except Exception as e:
                    logger.warning(f"Eventbrite SF fetch failed: {e}")

            if virtual:
                try:
                    resp = await client.get(ONLINE_SEARCH, headers=headers)
                    resp.raise_for_status()
                    for h in _extract_events(resp.text, is_online=True):
                        if h.url not in seen_urls:
                            seen_urls.add(h.url)
                            results.append(h)
                except Exception as e:
                    logger.warning(f"Eventbrite online fetch failed: {e}")

        logger.info(f"Eventbrite: found {len(results)} hackathons")
        return results
