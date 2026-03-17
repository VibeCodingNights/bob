"""Devpost API client — no browser needed."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

API_BASE = "https://devpost.com/api/hackathons"


def _parse_date(date_str: str) -> datetime | None:
    """Parse Devpost date strings like 'Mar 15 - 17, 2026'."""
    if not date_str:
        return None
    # Devpost returns "submission_period_dates" as human-readable strings.
    # Try common formats.
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    # Range format: "Mar 15 - 17, 2026" — take the start
    parts = date_str.split(" - ")
    if len(parts) == 2:
        # "Mar 15" + "17, 2026" → reconstruct "Mar 15, 2026"
        end_part = parts[1].strip()
        if "," in end_part:
            year = end_part.split(",")[-1].strip()
            start_with_year = f"{parts[0].strip()}, {year}"
            for fmt in ("%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(start_with_year, fmt)
                except ValueError:
                    continue
    return None


def _parse_hackathon(entry: dict) -> Hackathon:
    """Convert a Devpost API entry to our canonical model."""
    location = entry.get("displayed_location", {})
    location_str = (location.get("location") if isinstance(location, dict) else None) or "Online"

    # Determine format from challenge_type or location
    is_online = location_str.lower() in ("online", "") or not location_str
    fmt = Format.VIRTUAL if is_online else Format.IN_PERSON

    # Registration status
    state = entry.get("open_state", "")
    if state == "open":
        reg = RegistrationStatus.OPEN
    elif state == "upcoming":
        reg = RegistrationStatus.UPCOMING
    else:
        reg = RegistrationStatus.CLOSED

    # Dates
    date_str = entry.get("submission_period_dates", "")
    start = _parse_date(date_str)

    # Themes
    themes = [t["name"] for t in entry.get("themes", []) if "name" in t]

    # Prize
    prize = entry.get("prize_amount", "")

    return Hackathon(
        name=entry.get("title", "Untitled"),
        url=entry.get("url", ""),
        source="devpost",
        format=fmt,
        location=location_str,
        start_date=start,
        organizer=entry.get("organization_name", ""),
        registration_status=reg,
        themes=themes,
        prize_amount=prize,
        participants=entry.get("registrations_count", 0),
        image_url=entry.get("thumbnail_url", ""),
    )


class DevpostSource(Source):
    name = "devpost"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch open + upcoming hackathons
            for status in ("open", "upcoming"):
                page = 1
                while True:
                    params: dict = {
                        "page": page,
                        "status[]": status,
                    }

                    try:
                        resp = await client.get(API_BASE, params=params)
                        resp.raise_for_status()
                    except httpx.HTTPError as e:
                        logger.warning(f"Devpost API error (page {page}): {e}")
                        break

                    data = resp.json()
                    hackathons = data.get("hackathons", [])
                    if not hackathons:
                        break

                    for entry in hackathons:
                        h = _parse_hackathon(entry)
                        # Filter: SF in-person or virtual
                        if sf and h.format == Format.IN_PERSON and not h.is_sf:
                            continue
                        if not virtual and h.is_virtual:
                            continue
                        results.append(h)

                    # Pagination — Devpost returns 9 per page
                    total = data.get("meta", {}).get("total_count", 0)
                    if page * 9 >= total:
                        break
                    page += 1

        logger.info(f"Devpost: found {len(results)} hackathons")
        return results
