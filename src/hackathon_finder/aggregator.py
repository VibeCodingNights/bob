"""Aggregate and deduplicate hackathons across sources."""

from __future__ import annotations

import asyncio
import logging

from hackathon_finder.models import Hackathon
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)


async def _fetch_source(source: Source, sf: bool, virtual: bool) -> list[Hackathon]:
    """Fetch from a single source, catching errors."""
    try:
        return await source.fetch(sf=sf, virtual=virtual)
    except Exception as e:
        logger.error(f"{source.name} failed: {e}")
        return []


def deduplicate(hackathons: list[Hackathon]) -> list[Hackathon]:
    """Deduplicate by normalized name. Prefers sources with more data."""
    seen: dict[str, Hackathon] = {}
    # Priority: devpost > mlh > devfolio > luma > eventbrite > meetup
    priority = {"devpost": 0, "mlh": 1, "devfolio": 2, "luma": 3, "eventbrite": 4, "meetup": 5}

    for h in hackathons:
        key = h.dedup_key()
        if key not in seen or priority.get(h.source, 9) < priority.get(seen[key].source, 9):
            seen[key] = h

    return list(seen.values())


def sort_hackathons(hackathons: list[Hackathon]) -> list[Hackathon]:
    """Sort by start date (soonest first), then name."""
    def key(h: Hackathon):
        # None dates go to the end
        from datetime import datetime
        return (h.start_date or datetime.max, h.name.lower())
    return sorted(hackathons, key=key)


async def fetch_all(
    sources: list[Source],
    sf: bool = True,
    virtual: bool = True,
) -> list[Hackathon]:
    """Fetch from all sources concurrently, deduplicate, and sort."""
    tasks = [_fetch_source(s, sf=sf, virtual=virtual) for s in sources]
    results = await asyncio.gather(*tasks)

    all_hackathons: list[Hackathon] = []
    for batch in results:
        all_hackathons.extend(batch)

    deduped = deduplicate(all_hackathons)
    return sort_hackathons(deduped)
