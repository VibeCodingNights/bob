"""Tests for the Devpost source parser."""

from datetime import datetime

import pytest

from bob.models import Format, RegistrationStatus
from bob.sources.devpost import _parse_date, _parse_hackathon


class TestParseDate:
    def test_short_month_day_year(self):
        assert _parse_date("Mar 15, 2026") == datetime(2026, 3, 15)

    def test_full_month_day_year(self):
        assert _parse_date("March 15, 2026") == datetime(2026, 3, 15)

    def test_numeric_format(self):
        assert _parse_date("03/15/2026") == datetime(2026, 3, 15)

    def test_range_format(self):
        result = _parse_date("Mar 15 - 17, 2026")
        assert result == datetime(2026, 3, 15)

    def test_range_full_month(self):
        result = _parse_date("January 10 - 12, 2026")
        assert result == datetime(2026, 1, 10)

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_none_returns_none(self):
        # The function checks `if not date_str` which covers None
        assert _parse_date(None) is None

    def test_garbage_returns_none(self):
        assert _parse_date("not a date") is None

    def test_whitespace_stripped(self):
        assert _parse_date("  Mar 15, 2026  ") == datetime(2026, 3, 15)


class TestParseHackathon:
    @pytest.fixture
    def full_entry(self):
        return {
            "title": "TreeHacks 2026",
            "url": "https://treehacks-2026.devpost.com/",
            "displayed_location": {"location": "San Francisco, CA"},
            "open_state": "open",
            "submission_period_dates": "Mar 15, 2026",
            "themes": [{"name": "AI"}, {"name": "Health"}],
            "prize_amount": "$50,000",
            "organization_name": "Stanford",
            "registrations_count": 1500,
            "thumbnail_url": "https://example.com/img.png",
        }

    def test_full_entry(self, full_entry):
        h = _parse_hackathon(full_entry)
        assert h.name == "TreeHacks 2026"
        assert h.url == "https://treehacks-2026.devpost.com/"
        assert h.source == "devpost"
        assert h.format == Format.IN_PERSON
        assert h.location == "San Francisco, CA"
        assert h.start_date == datetime(2026, 3, 15)
        assert h.registration_status == RegistrationStatus.OPEN
        assert h.themes == ["AI", "Health"]
        assert h.prize_amount == "$50,000"
        assert h.organizer == "Stanford"
        assert h.participants == 1500
        assert h.image_url == "https://example.com/img.png"

    def test_online_location(self):
        entry = {
            "title": "Virtual Hack",
            "url": "https://example.com",
            "displayed_location": {"location": "Online"},
            "open_state": "open",
        }
        h = _parse_hackathon(entry)
        assert h.format == Format.VIRTUAL
        assert h.location == "Online"

    def test_empty_location_is_virtual(self):
        entry = {
            "title": "No Location",
            "url": "",
            "displayed_location": {},
            "open_state": "open",
        }
        h = _parse_hackathon(entry)
        assert h.format == Format.VIRTUAL
        assert h.location == "Online"

    def test_location_not_dict(self):
        """displayed_location can sometimes be a string or None."""
        entry = {
            "title": "Odd",
            "url": "",
            "displayed_location": "some string",
            "open_state": "open",
        }
        h = _parse_hackathon(entry)
        assert h.location == "Online"

    def test_upcoming_status(self):
        entry = {"title": "T", "url": "", "open_state": "upcoming"}
        h = _parse_hackathon(entry)
        assert h.registration_status == RegistrationStatus.UPCOMING

    def test_closed_status(self):
        entry = {"title": "T", "url": "", "open_state": "ended"}
        h = _parse_hackathon(entry)
        assert h.registration_status == RegistrationStatus.CLOSED

    def test_missing_title_defaults_untitled(self):
        entry = {"url": "https://x.com"}
        h = _parse_hackathon(entry)
        assert h.name == "Untitled"

    def test_themes_with_missing_name_key(self):
        entry = {
            "title": "T",
            "url": "",
            "themes": [{"name": "AI"}, {"id": 2}, {"name": "ML"}],
        }
        h = _parse_hackathon(entry)
        assert h.themes == ["AI", "ML"]

    def test_no_themes(self):
        entry = {"title": "T", "url": ""}
        h = _parse_hackathon(entry)
        assert h.themes == []

    def test_zero_participants(self):
        entry = {"title": "T", "url": ""}
        h = _parse_hackathon(entry)
        assert h.participants == 0
