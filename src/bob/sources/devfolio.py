"""Devfolio source — public REST API, no auth required."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from bob.models import Format, Hackathon, RegistrationStatus
from bob.sources.base import Source

logger = logging.getLogger(__name__)

API_BASE = "https://api.devfolio.co/api/hackathons"
MAX_PAGES = 50

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_hackathon(entry: dict) -> Hackathon:
    """Convert a Devfolio API entry to our canonical model."""
    settings = entry.get("hackathon_setting") or {}

    # Format: is_online + is_hybrid
    is_online = entry.get("is_online", False)
    is_hybrid = settings.get("is_hybrid", False)
    if is_hybrid:
        fmt = Format.HYBRID
    elif is_online:
        fmt = Format.VIRTUAL
    else:
        fmt = Format.IN_PERSON

    # Location
    if fmt == Format.VIRTUAL:
        location = "Online"
    else:
        parts = [entry.get("city", ""), entry.get("state", "")]
        location = ", ".join(p for p in parts if p) or entry.get("location", "") or "Online"

    # Prize: sum inline prizes
    total_prize = ""
    prizes = entry.get("prizes") or []
    if prizes:
        amounts = [p.get("amount", 0) for p in prizes if p.get("amount")]
        currencies = {p.get("currency", "USD") for p in prizes if p.get("currency")}
        if amounts:
            currency = currencies.pop() if len(currencies) == 1 else "USD"
            total_prize = f"{sum(amounts):,.0f} {currency}"

    # Themes
    themes = [t["name"] for t in entry.get("themes", []) if t.get("name")]

    # URL from slug
    slug = entry.get("slug", "")
    url = f"https://{slug}.devfolio.co/" if slug else ""

    return Hackathon(
        name=entry.get("name", "Untitled"),
        url=url,
        source="devfolio",
        format=fmt,
        location=location,
        start_date=_parse_iso(entry.get("starts_at")),
        end_date=_parse_iso(entry.get("ends_at")),
        registration_status=RegistrationStatus.OPEN,
        themes=themes,
        prize_amount=total_prize,
        participants=entry.get("participants_count", 0),
        image_url=entry.get("cover_img", ""),
        description=entry.get("tagline", ""),
    )


class DevfolioSource(Source):
    name = "devfolio"

    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        results: list[Hackathon] = []
        seen_slugs: set[str] = set()

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch application_open + live hackathons
            for status_filter in ("application_open", "live"):
                page = 1
                while True:
                    try:
                        resp = await client.get(
                            API_BASE,
                            params={"filter": status_filter, "page": page},
                            headers={"User-Agent": UA},
                        )
                        resp.raise_for_status()
                    except httpx.HTTPError as e:
                        logger.warning(f"Devfolio API error ({status_filter} p{page}): {e}")
                        break

                    data = resp.json()
                    entries = data.get("result", [])
                    if not entries:
                        break

                    for entry in entries:
                        slug = entry.get("slug", "")
                        if slug in seen_slugs:
                            continue
                        seen_slugs.add(slug)

                        h = _parse_hackathon(entry)
                        if sf and h.format == Format.IN_PERSON and not h.is_sf:
                            continue
                        if not virtual and h.is_virtual:
                            continue
                        results.append(h)

                    page += 1
                    if page > MAX_PAGES:
                        logger.warning("Devfolio: hit page limit (%d), stopping", MAX_PAGES)
                        break

        logger.info(f"Devfolio: found {len(results)} hackathons")
        return results
