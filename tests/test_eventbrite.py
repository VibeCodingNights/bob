"""Tests for the Eventbrite source parser."""

import json

import pytest

from bob.models import Format, RegistrationStatus
from bob.sources.eventbrite import _extract_events, _extract_server_data, _parse_date


def _wrap_server_data(events: list[dict], pagination: dict | None = None) -> str:
    """Build HTML with embedded __SERVER_DATA__."""
    data = {
        "search_data": {
            "events": {
                "results": events,
                "pagination": pagination or {"object_count": len(events)},
            }
        }
    }
    return f"<script>window.__SERVER_DATA__ = {json.dumps(data)};</script>"


def _make_event(**overrides) -> dict:
    """Build a sample Eventbrite event dict."""
    base = {
        "name": "SF Hackathon",
        "url": "https://www.eventbrite.com/e/sf-hackathon-123",
        "start_date": "2026-06-15",
        "start_time": "09:00",
        "end_date": "2026-06-16",
        "end_time": "18:00",
        "is_online_event": False,
        "primary_venue": {
            "name": "Tech Center",
            "address": {"city": "San Francisco", "region": "CA"},
        },
        "image": {"url": "https://example.com/img.jpg"},
        "summary": "A weekend hackathon",
    }
    base.update(overrides)
    return base


class TestParseDate:
    def test_date_and_time(self):
        dt = _parse_date("2026-06-15", "09:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.hour == 9

    def test_date_only(self):
        dt = _parse_date("2026-06-15", None)
        assert dt is not None
        assert dt.hour == 0

    def test_none_date(self):
        assert _parse_date(None, "09:00") is None

    def test_empty_date(self):
        assert _parse_date("", "09:00") is None

    def test_invalid_format(self):
        assert _parse_date("not-a-date", "09:00") is None


class TestExtractServerData:
    def test_extracts_json(self):
        html = '<script>window.__SERVER_DATA__ = {"key": "value"};</script>'
        data = _extract_server_data(html)
        assert data == {"key": "value"}

    def test_no_server_data(self):
        data = _extract_server_data("<html><body>Nothing</body></html>")
        assert data == {}

    def test_malformed_json(self):
        html = '<script>window.__SERVER_DATA__ = {broken;</script>'
        data = _extract_server_data(html)
        assert data == {}


class TestExtractEvents:
    def test_parse_in_person_event(self):
        html = _wrap_server_data([_make_event()])
        results = _extract_events(html, is_online=False)
        assert len(results) == 1
        h = results[0]
        assert h.name == "SF Hackathon"
        assert h.source == "eventbrite"
        assert h.format == Format.IN_PERSON
        assert h.location == "San Francisco, CA"
        assert h.start_date is not None
        assert h.start_date.month == 6
        assert h.start_date.hour == 9
        assert h.end_date is not None
        assert h.image_url == "https://example.com/img.jpg"
        assert h.description == "A weekend hackathon"

    def test_online_event_flag(self):
        html = _wrap_server_data([_make_event(is_online_event=True)])
        results = _extract_events(html, is_online=False)
        assert results[0].format == Format.VIRTUAL
        assert results[0].location == "Online"

    def test_is_online_param_forces_virtual(self):
        html = _wrap_server_data([_make_event()])
        results = _extract_events(html, is_online=True)
        assert results[0].format == Format.VIRTUAL

    def test_skips_event_without_name(self):
        html = _wrap_server_data([_make_event(name="")])
        assert len(_extract_events(html)) == 0

    def test_skips_event_without_url(self):
        html = _wrap_server_data([_make_event(url="")])
        assert len(_extract_events(html)) == 0

    def test_no_venue_defaults_online(self):
        html = _wrap_server_data([_make_event(primary_venue=None)])
        results = _extract_events(html, is_online=False)
        assert results[0].location == "Online"

    def test_venue_name_fallback(self):
        venue = {"name": "Cool Space", "address": {}}
        html = _wrap_server_data([_make_event(primary_venue=venue)])
        results = _extract_events(html)
        assert results[0].location == "Cool Space"

    def test_image_none(self):
        html = _wrap_server_data([_make_event(image=None)])
        results = _extract_events(html)
        assert results[0].image_url == ""

    def test_multiple_events(self):
        events = [
            _make_event(name="Hack 1", url="https://www.eventbrite.com/e/1"),
            _make_event(name="Hack 2", url="https://www.eventbrite.com/e/2"),
            _make_event(name="Hack 3", url="https://www.eventbrite.com/e/3"),
        ]
        html = _wrap_server_data(events)
        assert len(_extract_events(html)) == 3

    def test_missing_dates(self):
        html = _wrap_server_data([_make_event(start_date=None, end_date=None)])
        results = _extract_events(html)
        assert results[0].start_date is None
        assert results[0].end_date is None

    def test_empty_html(self):
        assert len(_extract_events("<html></html>")) == 0
