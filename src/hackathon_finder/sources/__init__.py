"""Hackathon source adapters."""

from hackathon_finder.sources.devpost import DevpostSource
from hackathon_finder.sources.mlh import MLHSource
from hackathon_finder.sources.luma import LumaSource
from hackathon_finder.sources.eventbrite import EventbriteSource

ALL_SOURCES = [DevpostSource, MLHSource, LumaSource, EventbriteSource]

__all__ = ["DevpostSource", "MLHSource", "LumaSource", "EventbriteSource", "ALL_SOURCES"]
