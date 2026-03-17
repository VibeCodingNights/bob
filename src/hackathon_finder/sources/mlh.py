"""MLH source — extracts structured JSON from Inertia.js data-page attribute."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

# MLH migrated from mlh.io → www.mlh.com (307 redirect still works)
MLH_URL = "https://www.mlh.com/seasons/2026/events"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Inertia.js embeds all page data as HTML-entity-encoded JSON in data-page="..."
_DATA_PAGE_RE = re.compile(r'data-page="(.*?)"', re.DOTALL)

_FORMAT_MAP = {
    "digital": Format.VIRTUAL,
    "physical": Format.IN_PERSON,
    "hybrid_physical": Format.HYBRID,
}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_event(ev: dict) -> Hackathon:
    """Convert an MLH Inertia.js event object to our canonical model."""
    fmt = _FORMAT_MAP.get(ev.get("format_type", ""), Format.VIRTUAL)

    # Location: prefer structured venue_address, fall back to freeform location string
    venue = ev.get("venue_address") or {}
    if venue:
        parts = [venue.get("city", ""), venue.get("state", "")]
        location = ", ".join(p for p in parts if p) or ev.get("location", "Online")
    else:
        location = ev.get("location", "") or "Online"

    # Registration status from event status field
    status = ev.get("status", "")
    if status == "ended":
        reg = RegistrationStatus.CLOSED
    elif status == "in_progress":
        reg = RegistrationStatus.OPEN
    else:  # "pending" = upcoming
        reg = RegistrationStatus.UPCOMING

    # URL: MLH returns relative paths like /events/slug/prizes
    slug = ev.get("slug", "")
    url = ev.get("website_url", "") or f"https://www.mlh.com/events/{slug}"

    return Hackathon(
        name=ev.get("name", "Untitled"),
        url=url,
        source="mlh",
        format=fmt,
        location=location,
        start_date=_parse_iso(ev.get("starts_at")),
        end_date=_parse_iso(ev.get("ends_at")),
        registration_status=reg,
        image_url=ev.get("logo_url", ""),
    )


class MLHSource(Source):
    name = "mlh"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(MLH_URL, headers={"User-Agent": UA})
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"MLH fetch failed: {e}")
                return []

            # Extract Inertia.js data-page JSON from the app div
            match = _DATA_PAGE_RE.search(resp.text)
            if not match:
                logger.warning("MLH: no data-page attribute found")
                return []

            try:
                page_data = json.loads(html.unescape(match.group(1)))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"MLH: failed to parse data-page JSON: {e}")
                return []

            props = page_data.get("props", {})

            # upcoming_events is the primary target; include in_progress from past_events
            for ev in props.get("upcoming_events", []):
                h = _parse_event(ev)

                if sf and h.format == Format.IN_PERSON and not h.is_sf:
                    continue
                if not virtual and h.is_virtual:
                    continue
                results.append(h)

        logger.info(f"MLH: found {len(results)} hackathons")
        return results
