"""Canonical hackathon event model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Format(str, Enum):
    IN_PERSON = "in-person"
    VIRTUAL = "virtual"
    HYBRID = "hybrid"


class RegistrationStatus(str, Enum):
    OPEN = "open"
    UPCOMING = "upcoming"
    CLOSED = "closed"
    WAITLIST = "waitlist"
    UNKNOWN = "unknown"


@dataclass
class Hackathon:
    name: str
    url: str
    source: str  # devpost, mlh, devfolio, luma, eventbrite, meetup
    format: Format = Format.VIRTUAL
    location: str = "Online"
    start_date: datetime | None = None
    end_date: datetime | None = None
    organizer: str = ""
    registration_status: RegistrationStatus = RegistrationStatus.UNKNOWN
    themes: list[str] = field(default_factory=list)
    prize_amount: str = ""
    participants: int = 0
    image_url: str = ""
    description: str = ""

    @property
    def is_sf(self) -> bool:
        loc = self.location.lower()
        return any(t in loc for t in ("san francisco", "sf", "bay area", "silicon valley"))

    @property
    def is_virtual(self) -> bool:
        return self.format in (Format.VIRTUAL, Format.HYBRID)

    def dedup_key(self) -> str:
        """Normalized key for cross-platform deduplication."""
        # Strip common suffixes, lowercase, collapse whitespace
        name = self.name.lower().strip()
        for noise in (" hackathon", " hack", " 2026", " 2025"):
            name = name.replace(noise, "")
        return "".join(name.split())
