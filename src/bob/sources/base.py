"""Base class for hackathon sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bob.models import Hackathon


class Source(ABC):
    """Base hackathon source."""

    name: str = "unknown"

    @abstractmethod
    async def fetch(self, sf: bool = True, virtual: bool = True) -> list[Hackathon]:
        """Fetch hackathons. Returns deduplicated list from this source."""
        ...
