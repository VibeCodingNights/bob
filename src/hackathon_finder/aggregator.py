"""Aggregate and deduplicate hackathons across sources."""

from __future__ import annotations

import asyncio
import logging
import re

from hackathon_finder.models import Hackathon
from hackathon_finder.sources.base import Source

logger = logging.getLogger(__name__)

# Source priority: lower = preferred when merging duplicates.
SOURCE_PRIORITY = {"devpost": 0, "mlh": 1, "devfolio": 2, "luma": 3, "eventbrite": 4, "meetup": 5}

_FUZZY_THRESHOLD = 0.7


_NOISE_WORDS = frozenset({"hackathon", "hack", "hacks", "2025", "2026", "the", "a", "an", "edition", "spring", "fall", "winter", "summer"})


def _tokenize(name: str) -> set[str]:
    """Tokenize a hackathon name for fuzzy comparison.

    Splits on non-alnum boundaries AND camelCase boundaries (e.g. "HackSF" -> "hack", "sf"),
    then drops noise words.
    """
    # First split on non-alphanumeric
    raw = re.split(r"[^a-zA-Z0-9]+", name)
    tokens: set[str] = set()
    for part in raw:
        # Split camelCase: "HackSF" -> ["Hack", "SF"], "TreeHacks" -> ["Tree", "Hacks"]
        subparts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)", part)
        if subparts:
            for sp in subparts:
                tokens.add(sp.lower())
        elif part:
            tokens.add(part.lower())
    tokens -= _NOISE_WORDS
    tokens.discard("")
    return tokens


def _token_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_day(h1: Hackathon, h2: Hackathon) -> bool:
    """True if both have start_dates on the same calendar day."""
    if h1.start_date is None or h2.start_date is None:
        return False
    return h1.start_date.date() == h2.start_date.date()


def _pick_preferred(existing: Hackathon, candidate: Hackathon) -> Hackathon:
    """Return whichever hackathon comes from the higher-priority source."""
    if SOURCE_PRIORITY.get(candidate.source, 9) < SOURCE_PRIORITY.get(existing.source, 9):
        return candidate
    return existing


async def _fetch_source(source: Source, sf: bool, virtual: bool) -> list[Hackathon]:
    """Fetch from a single source, catching errors."""
    try:
        return await source.fetch(sf=sf, virtual=virtual)
    except Exception as e:
        logger.error(f"{source.name} failed: {e}")
        return []


def deduplicate(hackathons: list[Hackathon]) -> list[Hackathon]:
    """Deduplicate hackathons in two passes: exact key match, then fuzzy token overlap."""
    # --- Pass 1: exact dedup_key match ---
    seen: dict[str, Hackathon] = {}
    for h in hackathons:
        key = h.dedup_key()
        if key not in seen:
            seen[key] = h
        else:
            seen[key] = _pick_preferred(seen[key], h)

    # --- Pass 2: fuzzy token-overlap + same-day dedup ---
    unique = list(seen.values())
    tokens_cache = [_tokenize(h.name) for h in unique]
    merged = [False] * len(unique)

    for i in range(len(unique)):
        if merged[i]:
            continue
        for j in range(i + 1, len(unique)):
            if merged[j]:
                continue
            if (
                _token_similarity(tokens_cache[i], tokens_cache[j]) >= _FUZZY_THRESHOLD
                and _same_day(unique[i], unique[j])
            ):
                unique[i] = _pick_preferred(unique[i], unique[j])
                merged[j] = True
                logger.debug(
                    "Fuzzy dedup: merged %r (%s) into %r (%s)",
                    unique[j].name, unique[j].source,
                    unique[i].name, unique[i].source,
                )

    return [h for i, h in enumerate(unique) if not merged[i]]


def sort_hackathons(hackathons: list[Hackathon]) -> list[Hackathon]:
    """Sort by start date (soonest first), then name."""
    from datetime import datetime, timezone

    _MAX = datetime.max.replace(tzinfo=timezone.utc)

    def _normalize(dt: datetime | None) -> datetime:
        if dt is None:
            return _MAX
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return sorted(hackathons, key=lambda h: (_normalize(h.start_date), h.name.lower()))


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
