"""Luma source — uses internal paginated events API (api2.luma.com)."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

# Luma's internal paginated API — no auth needed
PAGINATED_URL = "https://api2.luma.com/discover/get-paginated-events"
# SF place ID from the discover page
SF_PLACE_ID = "discplace-BDj7GNbGlsF7Cka"

_STRONG_KEYWORDS = (
    "hackathon", "hack night", "hack day", "hack week", "hackfest",
    "buildathon", "codeathon", "code jam", "devjam",
)
_SOFT_KEYWORDS = (
    "build weekend", "build day", "build night", "code fest",
    "sprint", "ship day", "hacking", "hackers",
    "challenge", "jam session",
)
_ANTI_KEYWORDS = (
    "happy hour", "after hours", "afterparty", "party", "social",
    "meetup", "talk", "lecture", "conference", "summit", "showcase",
    "exhibit", "comedy", "lounge", "pre-pour", "pitch", "demo day",
    "networking", "mixer", "brunch", "dinner", "lunch",
)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_luma_event(entry: dict) -> Hackathon | None:
    """Convert a Luma paginated API entry to our canonical model."""
    ev = entry.get("event", {})
    if not ev:
        return None

    name = ev.get("name", "")
    if not name:
        return None

    url = f"https://luma.com/{ev.get('url', ev.get('api_id', ''))}"

    # Location
    location_str = "Online"
    geo = ev.get("geo_address_info") or {}
    if geo:
        city = geo.get("city", "")
        region = geo.get("region", "")
        location_str = f"{city}, {region}".strip(", ") or "Online"
    elif ev.get("location"):
        location_str = ev["location"]

    is_online = ev.get("is_online", False) or location_str.lower() == "online"
    fmt = Format.VIRTUAL if is_online else Format.IN_PERSON

    # Host
    hosts = entry.get("hosts", [])
    organizer = ", ".join(h.get("name", "") for h in hosts[:3] if h.get("name"))

    return Hackathon(
        name=name,
        url=url,
        source="luma",
        format=fmt,
        location=location_str,
        start_date=_parse_iso(ev.get("start_at")),
        end_date=_parse_iso(ev.get("end_at")),
        organizer=organizer,
        registration_status=RegistrationStatus.OPEN,
        image_url=ev.get("cover_url", ""),
        description=ev.get("description_short", ""),
    )


def _hackathon_score(h: Hackathon) -> int:
    """Structural signal score. Higher = more likely a hackathon.

    Signals:
      +3  strong keyword in name/description ("hackathon", "hack night", ...)
      +1  soft keyword ("sprint", "challenge", "build weekend", ...)
      +2  duration > 6h (hackathons are multi-hour/multi-day)
      +1  duration > 12h (multi-day events)
      +1  weekend start (Fri evening, Sat, Sun)
      -2  anti-keyword ("happy hour", "conference", "party", ...)

    Threshold: >= 2 passes filter.
    """
    text = f"{h.name} {h.description}".lower()
    score = 0

    # Keywords
    if any(kw in text for kw in _STRONG_KEYWORDS):
        score += 3
    if any(kw in text for kw in _SOFT_KEYWORDS):
        score += 1
    if any(kw in text for kw in _ANTI_KEYWORDS):
        score -= 2

    # Duration
    if h.start_date and h.end_date:
        hours = (h.end_date - h.start_date).total_seconds() / 3600
        if hours > 6:
            score += 2
        if hours > 12:
            score += 1

    # Weekend start
    if h.start_date and h.start_date.weekday() >= 4:  # Fri=4, Sat=5, Sun=6
        score += 1

    return score


def _is_hackathon(h: Hackathon) -> bool:
    """Structural heuristic: composite score >= 2 passes."""
    return _hackathon_score(h) >= 2


class LumaSource(Source):
    name = "luma"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch SF events from paginated API
            try:
                resp = await client.get(PAGINATED_URL, params={
                    "series_mode": "series",
                    "discover_place_api_id": SF_PLACE_ID,
                    "pagination_limit": 100,
                })
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"Luma API error: {e}")
                return []

            entries = data.get("entries", [])
            for entry in entries:
                h = _parse_luma_event(entry)
                if h is None:
                    continue
                if not _is_hackathon(h):
                    continue
                if sf and h.format == Format.IN_PERSON and not h.is_sf:
                    continue
                if not virtual and h.is_virtual:
                    continue
                results.append(h)

        logger.info(f"Luma: found {len(results)} hackathons")
        return results
