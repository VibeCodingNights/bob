"""Meetup source — extracts Apollo state from __NEXT_DATA__ on public search page."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

SF_SEARCH = (
    "https://www.meetup.com/find/"
    "?keywords=hackathon&location=San+Francisco%2C+CA&source=EVENTS"
)
ONLINE_SEARCH = (
    "https://www.meetup.com/find/"
    "?keywords=hackathon&source=EVENTS&eventType=online"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Apollo state lives inside __NEXT_DATA__ as props.pageProps.__APOLLO_STATE__
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_apollo_state(html: str) -> dict:
    """Extract Apollo state from Meetup's __NEXT_DATA__ script tag."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return {}
    try:
        next_data = json.loads(match.group(1))
        return next_data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_events(html: str, is_online: bool = False) -> list[Hackathon]:
    """Extract event data from Meetup's embedded Apollo state."""
    state = _extract_apollo_state(html)
    if not state:
        logger.debug("Meetup: no Apollo state found in __NEXT_DATA__")
        return []

    results: list[Hackathon] = []

    for key, obj in state.items():
        if not key.startswith("Event:") or not isinstance(obj, dict):
            continue

        name = obj.get("title", "")
        if not name:
            continue

        url = obj.get("eventUrl", "")

        # Event type: PHYSICAL, ONLINE, or hybrid
        event_type = (obj.get("eventType") or "").upper()
        if event_type == "ONLINE" or is_online:
            fmt = Format.VIRTUAL
            location = "Online"
        else:
            fmt = Format.IN_PERSON
            # Venue can be inline dict or a __ref
            venue = obj.get("venue") or {}
            if isinstance(venue, dict) and "__ref" in venue:
                venue = state.get(venue["__ref"], {})
            city = venue.get("city", "")
            state_code = venue.get("state", "")
            location = f"{city}, {state_code}".strip(", ") or "San Francisco, CA"

        # Group/organizer — can be inline or __ref
        group = obj.get("group") or {}
        if isinstance(group, dict) and "__ref" in group:
            group = state.get(group["__ref"], {})
        organizer = group.get("name", "")

        # Image — inline or __ref
        image_url = ""
        for img_key in ("featuredEventPhoto", "displayPhoto"):
            img = obj.get(img_key)
            if isinstance(img, dict):
                if "__ref" in img:
                    img = state.get(img["__ref"], {})
                image_url = img.get("source", "") or img.get("highResUrl", "")
                if image_url:
                    break

        results.append(Hackathon(
            name=name,
            url=url,
            source="meetup",
            format=fmt,
            location=location,
            start_date=_parse_iso(obj.get("dateTime")),
            end_date=_parse_iso(obj.get("endTime")),
            organizer=organizer,
            registration_status=RegistrationStatus.OPEN,
            image_url=image_url,
        ))

    return results


class MeetupSource(Source):
    name = "meetup"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []
        seen_urls: set[str] = set()
        headers = {"User-Agent": UA}

        async with httpx.AsyncClient(timeout=15.0) as client:
            # SF in-person hackathons
            if sf:
                try:
                    resp = await client.get(SF_SEARCH, headers=headers)
                    resp.raise_for_status()
                    for h in _extract_events(resp.text, is_online=False):
                        if h.url not in seen_urls:
                            seen_urls.add(h.url)
                            results.append(h)
                except Exception as e:
                    logger.warning(f"Meetup SF fetch failed: {e}")

            # Virtual hackathons
            if virtual:
                try:
                    resp = await client.get(ONLINE_SEARCH, headers=headers)
                    resp.raise_for_status()
                    for h in _extract_events(resp.text, is_online=True):
                        if h.url not in seen_urls:
                            seen_urls.add(h.url)
                            results.append(h)
                except Exception as e:
                    logger.warning(f"Meetup online fetch failed: {e}")

        logger.info(f"Meetup: found {len(results)} hackathons")
        return results
