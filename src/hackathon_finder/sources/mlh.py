"""MLH scraper — hackathon-native platform, no public API."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

MLH_URL = "https://mlh.io/seasons/2026/events"


def _parse_mlh_date(date_text: str) -> datetime | None:
    """Parse MLH date like 'MAR 13 - 19, 2026' or 'MAR 13 - APR 2, 2026'."""
    if not date_text:
        return None
    # Normalize
    text = date_text.strip().upper()
    # "MAR 13 - 19, 2026" → start = "MAR 13, 2026"
    parts = text.split(" - ")
    if len(parts) == 2:
        end = parts[1].strip()
        if "," in end:
            year = end.split(",")[-1].strip()
            start_str = f"{parts[0].strip()}, {year}"
        else:
            start_str = parts[0].strip()
    else:
        start_str = text

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(start_str, fmt)
        except ValueError:
            continue
    return None


class MLHSource(Source):
    name = "mlh"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available for MLH scraping")
            return []

        results: list[Hackathon] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(MLH_URL, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                })
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"MLH fetch failed: {e}")
                return []

            html = resp.text

            # MLH uses structured event cards. Parse with regex (no lxml dependency).
            # Each event is in a div.event-wrapper or similar.
            # Look for event links + metadata.
            event_blocks = re.findall(
                r'<div[^>]*class="[^"]*event[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
                html,
                re.DOTALL | re.IGNORECASE,
            )

            if not event_blocks:
                # Fallback: extract all event links
                links = re.findall(
                    r'href="(https?://[^"]*)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
                    html,
                    re.DOTALL,
                )
                dates = re.findall(
                    r'<p[^>]*class="[^"]*event-date[^"]*"[^>]*>(.*?)</p>',
                    html,
                    re.DOTALL,
                )
                locations = re.findall(
                    r'<span[^>]*class="[^"]*event-location[^"]*"[^>]*>(.*?)</span>',
                    html,
                    re.DOTALL,
                )

                for i, (url, name) in enumerate(links):
                    name = re.sub(r"<[^>]+>", "", name).strip()
                    if not name:
                        continue

                    loc = re.sub(r"<[^>]+>", "", locations[i]).strip() if i < len(locations) else ""
                    date_text = re.sub(r"<[^>]+>", "", dates[i]).strip() if i < len(dates) else ""

                    is_digital = "digital" in loc.lower() or "virtual" in loc.lower() or "online" in loc.lower()
                    fmt = Format.VIRTUAL if is_digital else Format.IN_PERSON

                    h = Hackathon(
                        name=name,
                        url=url,
                        source="mlh",
                        format=fmt,
                        location=loc if loc else "Online",
                        start_date=_parse_mlh_date(date_text),
                        registration_status=RegistrationStatus.OPEN,
                    )

                    if sf and fmt == Format.IN_PERSON and not h.is_sf:
                        continue
                    if not virtual and h.is_virtual:
                        continue
                    results.append(h)

        logger.info(f"MLH: found {len(results)} hackathons")
        return results
