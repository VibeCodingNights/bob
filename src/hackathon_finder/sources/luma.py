"""Luma scraper — uses internal discovery API (api2.luma.com)."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

# Luma's internal API — no auth needed, used by the frontend SPA
BOOTSTRAP_URL = "https://api2.luma.com/discover/bootstrap-page"
# SF place ID from the discover page
SF_PLACE_ID = "discplace-BDj7GNbGlsF7Cka"


def _parse_luma_event(event: dict) -> Hackathon | None:
    """Convert a Luma event API entry to our canonical model."""
    ev = event.get("event", {})
    if not ev:
        return None

    name = ev.get("name", "")
    if not name:
        return None

    url = f"https://luma.com/{ev.get('url', ev.get('api_id', ''))}"

    # Dates
    start = None
    if ev.get("start_at"):
        try:
            start = datetime.fromisoformat(ev["start_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    end = None
    if ev.get("end_at"):
        try:
            end = datetime.fromisoformat(ev["end_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

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
    hosts = event.get("hosts", [])
    organizer = ", ".join(h.get("name", "") for h in hosts[:3] if h.get("name"))

    return Hackathon(
        name=name,
        url=url,
        source="luma",
        format=fmt,
        location=location_str,
        start_date=start,
        end_date=end,
        organizer=organizer,
        registration_status=RegistrationStatus.OPEN,
        image_url=ev.get("cover_url", ""),
        description=ev.get("description_short", ""),
    )


def _is_hackathon(h: Hackathon) -> bool:
    """Heuristic: does this event look like a hackathon?"""
    text = f"{h.name} {h.description} {' '.join(h.themes)}".lower()
    keywords = ("hackathon", "hack night", "hack day", "hackon", "buildathon", "codeathon",
                "code jam", "code fest", "devjam", "build day", "build night", "hacking")
    return any(kw in text for kw in keywords)


class LumaSource(Source):
    name = "luma"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch SF events from bootstrap API
            try:
                resp = await client.get(BOOTSTRAP_URL, params={
                    "featured_place_api_id": SF_PLACE_ID,
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
