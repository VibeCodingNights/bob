"""Hackathon source adapters."""

from hackathon_finder.sources.devpost import DevpostSource
from hackathon_finder.sources.mlh import MLHSource
from hackathon_finder.sources.luma import LumaSource
from hackathon_finder.sources.eventbrite import EventbriteSource
from hackathon_finder.sources.devfolio import DevfolioSource
from hackathon_finder.sources.meetup import MeetupSource

ALL_SOURCES = [
    DevpostSource, MLHSource, LumaSource, EventbriteSource,
    DevfolioSource, MeetupSource,
]

__all__ = [
    "DevpostSource", "MLHSource", "LumaSource", "EventbriteSource",
    "DevfolioSource", "MeetupSource", "ALL_SOURCES",
]
