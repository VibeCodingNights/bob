"""Tests for the Eventbrite source parser."""

import json
from datetime import datetime, timezone, timedelta

import pytest

from hackathon_finder.models import Format, RegistrationStatus
from hackathon_finder.sources.eventbrite import _extract_events_from_html


def _wrap_json_ld(items: list[dict]) -> str:
    """Wrap JSON-LD items in the expected script tag."""
    return f'<script type="application/ld+json">{json.dumps(items)}</script>'


class TestExtractEventsJsonLD:
    @pytest.fixture
    def in_person_event_html(self):
        event = {
            "@type": "Event",
            "name": "SF AI Hackathon",
            "url": "https://www.eventbrite.com/e/sf-ai-hack",
            "startDate": "2026-06-15T09:00:00-07:00",
            "endDate": "2026-06-16T18:00:00-07:00",
            "location": {
                "@type": "Place",
                "name": "Tech Center",
                "address": {
                    "addressLocality": "San Francisco",
                    "addressRegion": "CA",
                },
            },
            "organizer": {"name": "TechOrg"},
            "image": "https://example.com/img.jpg",
        }
        return _wrap_json_ld([event])

    def test_parse_in_person_event(self, in_person_event_html):
        results = _extract_events_from_html(in_person_event_html, is_online=False)
        assert len(results) == 1
        h = results[0]
        assert h.name == "SF AI Hackathon"
        assert h.source == "eventbrite"
        assert h.format == Format.IN_PERSON
        assert h.location == "San Francisco, CA"
        pdt = timezone(timedelta(hours=-7))
        assert h.start_date == datetime(2026, 6, 15, 9, 0, 0, tzinfo=pdt)
        assert h.end_date is not None
        assert h.organizer == "TechOrg"
        assert h.image_url == "https://example.com/img.jpg"
        assert h.registration_status == RegistrationStatus.OPEN

    def test_virtual_location(self):
        event = {
            "@type": "Event",
            "name": "Online Hack",
            "url": "https://x.com",
            "location": {"@type": "VirtualLocation"},
        }
        results = _extract_events_from_html(_wrap_json_ld([event]), is_online=False)
        assert len(results) == 1
        assert results[0].format == Format.VIRTUAL
        assert results[0].location == "Online"

    def test_is_online_flag_forces_virtual(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "location": {
                "@type": "Place",
                "address": {"addressLocality": "NYC", "addressRegion": "NY"},
            },
        }
        results = _extract_events_from_html(_wrap_json_ld([event]), is_online=True)
        assert results[0].format == Format.VIRTUAL

    def test_skips_non_event_types(self):
        items = [
            {"@type": "Organization", "name": "Org"},
            {"@type": "Event", "name": "Hack", "url": "https://x.com"},
        ]
        results = _extract_events_from_html(_wrap_json_ld(items))
        assert len(results) == 1
        assert results[0].name == "Hack"

    def test_skips_event_without_name(self):
        event = {"@type": "Event", "url": "https://x.com"}
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert len(results) == 0

    def test_invalid_start_date(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "startDate": "not-a-date",
        }
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert len(results) == 1
        assert results[0].start_date is None

    def test_image_as_list(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "image": ["https://img1.com", "https://img2.com"],
        }
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert results[0].image_url == "https://img1.com"

    def test_image_as_string(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "image": "https://single.com/img.jpg",
        }
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert results[0].image_url == "https://single.com/img.jpg"

    def test_organizer_not_dict(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "organizer": "A string organizer",
        }
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert results[0].organizer == ""

    def test_single_json_ld_object_not_list(self):
        event = {"@type": "Event", "name": "Solo", "url": "https://x.com"}
        html = f'<script type="application/ld+json">{json.dumps(event)}</script>'
        results = _extract_events_from_html(html)
        assert len(results) == 1

    def test_invalid_json_ld_skipped(self):
        html = '<script type="application/ld+json">{broken json</script>'
        results = _extract_events_from_html(html)
        assert len(results) == 0

    def test_location_missing_address_fields(self):
        event = {
            "@type": "Event",
            "name": "Hack",
            "url": "https://x.com",
            "location": {"@type": "Place", "name": "Cool Venue", "address": {}},
        }
        results = _extract_events_from_html(_wrap_json_ld([event]))
        assert results[0].location == "Cool Venue"


class TestExtractEventsFallbackCards:
    def test_fallback_card_extraction(self):
        html = """
        <div>
            <a href="https://www.eventbrite.com/e/ai-hack-123">
                <h2>AI Hackathon</h2>
            </a>
            <a href="https://www.eventbrite.com/e/web-hack-456">
                <h2>Web <b>Hackathon</b></h2>
            </a>
        </div>
        """
        results = _extract_events_from_html(html, is_online=False)
        assert len(results) == 2
        assert results[0].name == "AI Hackathon"
        assert results[0].format == Format.IN_PERSON
        assert results[0].location == "San Francisco, CA"
        # HTML tags stripped from name
        assert results[1].name == "Web Hackathon"

    def test_fallback_online(self):
        html = """
        <a href="https://www.eventbrite.com/e/hack-123">
            <h2>Virtual Hack</h2>
        </a>
        """
        results = _extract_events_from_html(html, is_online=True)
        assert len(results) == 1
        assert results[0].format == Format.VIRTUAL
        assert results[0].location == "Online"

    def test_fallback_empty_name_skipped(self):
        html = """
        <a href="https://www.eventbrite.com/e/hack-123">
            <h2>   </h2>
        </a>
        """
        results = _extract_events_from_html(html)
        assert len(results) == 0

    def test_no_events_at_all(self):
        results = _extract_events_from_html("<html><body>Nothing here</body></html>")
        assert len(results) == 0
