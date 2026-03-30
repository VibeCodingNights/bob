"""Hackathon source adapters."""

from bob.sources.devpost import DevpostSource
from bob.sources.mlh import MLHSource
from bob.sources.luma import LumaSource
from bob.sources.eventbrite import EventbriteSource
from bob.sources.devfolio import DevfolioSource
from bob.sources.meetup import MeetupSource

ALL_SOURCES = [
    DevpostSource, MLHSource, LumaSource, EventbriteSource,
    DevfolioSource, MeetupSource,
]

__all__ = [
    "DevpostSource", "MLHSource", "LumaSource", "EventbriteSource",
    "DevfolioSource", "MeetupSource", "ALL_SOURCES",
]
