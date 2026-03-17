"""Eventbrite scraper — public search UI, no OAuth needed."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

SF_SEARCH = "https://www.eventbrite.com/d/ca--san-francisco/hackathon/"
ONLINE_SEARCH = "https://www.eventbrite.com/d/online/hackathon/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _extract_events_from_html(html: str, is_online: bool = False) -> list[Hackathon]:
    """Extract event data from Eventbrite search results HTML."""
    results: list[Hackathon] = []

    # Eventbrite embeds structured data as JSON-LD
    json_ld_blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    )

    import json
    for block in json_ld_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue

        # Can be a single object or list
        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") != "Event":
                continue

            name = item.get("name", "")
            if not name:
                continue

            url = item.get("url", "")
            location_data = item.get("location", {})

            if is_online or location_data.get("@type") == "VirtualLocation":
                fmt = Format.VIRTUAL
                location_str = "Online"
            else:
                fmt = Format.IN_PERSON
                addr = location_data.get("address", {})
                city = addr.get("addressLocality", "")
                region = addr.get("addressRegion", "")
                location_str = f"{city}, {region}".strip(", ") or location_data.get("name", "")

            start = None
            if item.get("startDate"):
                try:
                    start = datetime.fromisoformat(item["startDate"])
                except (ValueError, TypeError):
                    pass

            end = None
            if item.get("endDate"):
                try:
                    end = datetime.fromisoformat(item["endDate"])
                except (ValueError, TypeError):
                    pass

            organizer = ""
            org = item.get("organizer", {})
            if isinstance(org, dict):
                organizer = org.get("name", "")

            image = ""
            if item.get("image"):
                img = item["image"]
                image = img if isinstance(img, str) else (img[0] if isinstance(img, list) else "")

            results.append(Hackathon(
                name=name,
                url=url,
                source="eventbrite",
                format=fmt,
                location=location_str,
                start_date=start,
                end_date=end,
                organizer=organizer,
                registration_status=RegistrationStatus.OPEN,
                image_url=image,
            ))

    # Fallback: parse event cards if no JSON-LD found
    if not results:
        cards = re.findall(
            r'<a[^>]*href="(https://www\.eventbrite\.com/e/[^"]*)"[^>]*>.*?'
            r'<h2[^>]*>(.*?)</h2>',
            html,
            re.DOTALL,
        )
        for url, name in cards:
            name = re.sub(r"<[^>]+>", "", name).strip()
            if name:
                results.append(Hackathon(
                    name=name,
                    url=url,
                    source="eventbrite",
                    format=Format.VIRTUAL if is_online else Format.IN_PERSON,
                    location="Online" if is_online else "San Francisco, CA",
                    registration_status=RegistrationStatus.OPEN,
                ))

    return results


class EventbriteSource(Source):
    name = "eventbrite"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []
        headers = {"User-Agent": UA}

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # SF in-person
            if sf:
                try:
                    resp = await client.get(SF_SEARCH, headers=headers)
                    resp.raise_for_status()
                    results.extend(_extract_events_from_html(resp.text, is_online=False))
                except Exception as e:
                    logger.warning(f"Eventbrite SF fetch failed: {e}")

            # Virtual
            if virtual:
                try:
                    resp = await client.get(ONLINE_SEARCH, headers=headers)
                    resp.raise_for_status()
                    results.extend(_extract_events_from_html(resp.text, is_online=True))
                except Exception as e:
                    logger.warning(f"Eventbrite online fetch failed: {e}")

        logger.info(f"Eventbrite: found {len(results)} hackathons")
        return results
