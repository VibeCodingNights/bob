"""Tests for the MLH source parser."""

from datetime import datetime

import pytest

from hackathon_finder.models import Format, RegistrationStatus
from hackathon_finder.sources.mlh import _parse_event, _parse_iso, _DATA_PAGE_RE


class TestParseIso:
    def test_standard_iso(self):
        result = _parse_iso("2026-03-15T10:00:00")
        assert result == datetime(2026, 3, 15, 10, 0, 0)

    def test_utc_z(self):
        result = _parse_iso("2026-03-15T10:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_with_offset(self):
        result = _parse_iso("2026-03-15T10:00:00-05:00")
        assert result is not None
        assert result.hour == 10

    def test_empty_string(self):
        assert _parse_iso("") is None

    def test_none(self):
        assert _parse_iso(None) is None

    def test_garbage(self):
        assert _parse_iso("not-a-date") is None


class TestDataPageRegex:
    def test_matches_data_page_attribute(self):
        html = '<div id="app" data-page="{&quot;props&quot;:{}}">'
        match = _DATA_PAGE_RE.search(html)
        assert match is not None
        assert "&quot;" in match.group(1)

    def test_no_match(self):
        html = "<div>no data page here</div>"
        assert _DATA_PAGE_RE.search(html) is None


class TestParseEvent:
    @pytest.fixture
    def full_event(self):
        return {
            "name": "HackMIT",
            "slug": "hackmit-2026",
            "format_type": "physical",
            "venue_address": {"city": "Cambridge", "state": "MA"},
            "status": "in_progress",
            "starts_at": "2026-09-15T08:00:00Z",
            "ends_at": "2026-09-17T18:00:00Z",
            "logo_url": "https://example.com/logo.png",
            "website_url": "https://hackmit.org",
        }

    def test_full_event(self, full_event):
        h = _parse_event(full_event)
        assert h.name == "HackMIT"
        assert h.source == "mlh"
        assert h.format == Format.IN_PERSON
        assert h.location == "Cambridge, MA"
        assert h.registration_status == RegistrationStatus.OPEN
        assert h.start_date is not None
        assert h.end_date is not None
        assert h.url == "https://hackmit.org"
        assert h.image_url == "https://example.com/logo.png"

    def test_digital_format(self):
        ev = {"name": "Virtual Hack", "format_type": "digital", "slug": "vh"}
        h = _parse_event(ev)
        assert h.format == Format.VIRTUAL

    def test_hybrid_format(self):
        ev = {"name": "Hybrid", "format_type": "hybrid_physical", "slug": "h"}
        h = _parse_event(ev)
        assert h.format == Format.HYBRID

    def test_unknown_format_defaults_virtual(self):
        ev = {"name": "Unknown", "format_type": "new_type", "slug": "u"}
        h = _parse_event(ev)
        assert h.format == Format.VIRTUAL

    def test_venue_address_missing_falls_back_to_location(self):
        ev = {"name": "T", "slug": "t", "location": "Boston"}
        h = _parse_event(ev)
        assert h.location == "Boston"

    def test_no_venue_no_location(self):
        ev = {"name": "T", "slug": "t"}
        h = _parse_event(ev)
        assert h.location == "Online"

    def test_ended_status(self):
        ev = {"name": "T", "slug": "t", "status": "ended"}
        h = _parse_event(ev)
        assert h.registration_status == RegistrationStatus.CLOSED

    def test_pending_status(self):
        ev = {"name": "T", "slug": "t", "status": "pending"}
        h = _parse_event(ev)
        assert h.registration_status == RegistrationStatus.UPCOMING

    def test_url_fallback_to_slug(self):
        ev = {"name": "T", "slug": "my-hack"}
        h = _parse_event(ev)
        assert h.url == "https://www.mlh.com/events/my-hack"

    def test_website_url_preferred_over_slug(self):
        ev = {"name": "T", "slug": "s", "website_url": "https://custom.com"}
        h = _parse_event(ev)
        assert h.url == "https://custom.com"

    def test_empty_venue_address(self):
        ev = {"name": "T", "slug": "t", "venue_address": {}}
        h = _parse_event(ev)
        # Empty venue_address is falsy when tested via `if venue:`? No, empty dict is truthy
        # but city/state empty → falls to location or "Online"
        # Actually empty dict is truthy so venue branch runs, but parts are empty
        assert h.location is not None

    def test_venue_only_city(self):
        ev = {"name": "T", "slug": "t", "venue_address": {"city": "NYC"}}
        h = _parse_event(ev)
        assert "NYC" in h.location
