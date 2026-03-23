"""Canonical hackathon event model."""

from __future__ import annotations

import re
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
        for noise in (" hackathon", " hack"):
            name = name.replace(noise, "")
        name = re.sub(r'\s*20\d{2}\b', '', name)
        return "".join(name.split())

    @property
    def event_id(self) -> str:
        """Stable canonical ID for this event, used as semantic map directory name."""
        import hashlib
        if self.start_date:
            key = f"{self.dedup_key()}:{self.start_date.date().isoformat()}"
        else:
            key = self.url
        return hashlib.sha256(key.encode()).hexdigest()[:12]
