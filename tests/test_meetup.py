"""Tests for the Meetup source parser."""

import json

import pytest

from hackathon_finder.models import Format, RegistrationStatus
from hackathon_finder.sources.meetup import _extract_apollo_state, _extract_events


def _build_next_data_html(apollo_state: dict) -> str:
    """Build HTML with __NEXT_DATA__ containing the given Apollo state."""
    next_data = {
        "props": {
            "pageProps": {
                "__APOLLO_STATE__": apollo_state,
            }
        }
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'


class TestExtractApolloState:
    def test_extracts_state(self):
        state = {"Event:1": {"title": "Hack"}}
        html = _build_next_data_html(state)
        result = _extract_apollo_state(html)
        assert result == state

    def test_no_next_data(self):
        assert _extract_apollo_state("<html></html>") == {}

    def test_invalid_json(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{broken</script>'
        assert _extract_apollo_state(html) == {}

    def test_missing_props(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{}</script>'
        assert _extract_apollo_state(html) == {}


class TestExtractEvents:
    @pytest.fixture
    def basic_event_state(self):
        return {
            "Event:evt1": {
                "title": "SF Hackathon",
                "eventUrl": "https://www.meetup.com/group/sf-hack/",
                "eventType": "PHYSICAL",
                "dateTime": "2026-06-15T10:00:00-07:00",
                "endTime": "2026-06-15T22:00:00-07:00",
                "venue": {"city": "San Francisco", "state": "CA"},
                "group": {"name": "SF Hackers"},
                "featuredEventPhoto": {"source": "https://example.com/photo.jpg"},
            }
        }

    def test_basic_event(self, basic_event_state):
        html = _build_next_data_html(basic_event_state)
        results = _extract_events(html, is_online=False)
        assert len(results) == 1
        h = results[0]
        assert h.name == "SF Hackathon"
        assert h.source == "meetup"
        assert h.format == Format.IN_PERSON
        assert h.location == "San Francisco, CA"
        assert h.start_date is not None
        assert h.end_date is not None
        assert h.organizer == "SF Hackers"
        assert h.image_url == "https://example.com/photo.jpg"
        assert h.registration_status == RegistrationStatus.OPEN

    def test_online_event_by_type(self):
        state = {
            "Event:evt1": {
                "title": "Virtual Hack",
                "eventUrl": "https://meetup.com/e/1",
                "eventType": "ONLINE",
            }
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].format == Format.VIRTUAL
        assert results[0].location == "Online"

    def test_online_flag_overrides(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "eventType": "PHYSICAL",
                "venue": {"city": "NYC", "state": "NY"},
            }
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=True)
        assert results[0].format == Format.VIRTUAL

    def test_venue_ref(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "eventType": "PHYSICAL",
                "venue": {"__ref": "Venue:v1"},
            },
            "Venue:v1": {"city": "Austin", "state": "TX"},
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].location == "Austin, TX"

    def test_group_ref(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "group": {"__ref": "Group:g1"},
            },
            "Group:g1": {"name": "Awesome Hackers"},
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].organizer == "Awesome Hackers"

    def test_image_ref(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "featuredEventPhoto": {"__ref": "Photo:p1"},
            },
            "Photo:p1": {"source": "https://photo.com/big.jpg"},
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].image_url == "https://photo.com/big.jpg"

    def test_display_photo_fallback(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "displayPhoto": {"highResUrl": "https://photo.com/hi.jpg"},
            }
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].image_url == "https://photo.com/hi.jpg"

    def test_no_venue_defaults_sf(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "eventType": "PHYSICAL",
            }
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert results[0].location == "San Francisco, CA"

    def test_skips_non_event_keys(self):
        state = {
            "Group:g1": {"name": "Not an event"},
            "Event:evt1": {"title": "Real Hack", "eventUrl": "https://meetup.com/e/1"},
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert len(results) == 1
        assert results[0].name == "Real Hack"

    def test_skips_event_without_title(self):
        state = {"Event:evt1": {"eventUrl": "https://meetup.com/e/1"}}
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert len(results) == 0

    def test_no_apollo_state(self):
        results = _extract_events("<html></html>")
        assert len(results) == 0

    def test_multiple_events(self):
        state = {
            "Event:e1": {"title": "Hack A", "eventUrl": "https://meetup.com/e/1"},
            "Event:e2": {"title": "Hack B", "eventUrl": "https://meetup.com/e/2"},
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert len(results) == 2
        names = {h.name for h in results}
        assert names == {"Hack A", "Hack B"}

    def test_venue_only_city(self):
        state = {
            "Event:evt1": {
                "title": "Hack",
                "eventUrl": "https://meetup.com/e/1",
                "eventType": "PHYSICAL",
                "venue": {"city": "Portland"},
            }
        }
        html = _build_next_data_html(state)
        results = _extract_events(html, is_online=False)
        assert "Portland" in results[0].location
