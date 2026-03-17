"""Tests for the Luma source parser."""


import pytest

from hackathon_finder.models import Format, Hackathon, RegistrationStatus
from hackathon_finder.sources.luma import _parse_iso, _parse_luma_event, _is_hackathon, _hackathon_score


class TestParseIso:
    def test_standard_iso(self):
        assert _parse_iso("2026-06-01T09:00:00Z") is not None

    def test_empty(self):
        assert _parse_iso("") is None

    def test_none(self):
        assert _parse_iso(None) is None

    def test_invalid(self):
        assert _parse_iso("nope") is None


class TestParseLumaEvent:
    @pytest.fixture
    def full_entry(self):
        return {
            "event": {
                "name": "SF Hack Night",
                "url": "sf-hack-night",
                "api_id": "evt_123",
                "geo_address_info": {"city": "San Francisco", "region": "CA"},
                "is_online": False,
                "start_at": "2026-06-01T18:00:00Z",
                "end_at": "2026-06-02T06:00:00Z",
                "cover_url": "https://example.com/cover.png",
                "description_short": "A great hackathon",
            },
            "hosts": [
                {"name": "Hacker Club"},
                {"name": "TechCo"},
            ],
        }

    def test_full_entry(self, full_entry):
        h = _parse_luma_event(full_entry)
        assert h is not None
        assert h.name == "SF Hack Night"
        assert h.source == "luma"
        assert h.format == Format.IN_PERSON
        assert "San Francisco" in h.location
        assert h.start_date is not None
        assert h.end_date is not None
        assert h.organizer == "Hacker Club, TechCo"
        assert h.registration_status == RegistrationStatus.OPEN
        assert h.image_url == "https://example.com/cover.png"
        assert h.description == "A great hackathon"

    def test_url_uses_url_field(self):
        entry = {"event": {"name": "T", "url": "my-event"}, "hosts": []}
        h = _parse_luma_event(entry)
        assert h.url == "https://luma.com/my-event"

    def test_url_falls_back_to_api_id(self):
        entry = {"event": {"name": "T", "api_id": "evt_abc"}, "hosts": []}
        h = _parse_luma_event(entry)
        assert h.url == "https://luma.com/evt_abc"

    def test_online_event(self):
        entry = {"event": {"name": "T", "url": "x", "is_online": True}, "hosts": []}
        h = _parse_luma_event(entry)
        assert h.format == Format.VIRTUAL

    def test_no_geo_with_location_string(self):
        entry = {
            "event": {"name": "T", "url": "x", "location": "My Venue, NYC"},
            "hosts": [],
        }
        h = _parse_luma_event(entry)
        assert h.location == "My Venue, NYC"

    def test_no_geo_no_location(self):
        entry = {"event": {"name": "T", "url": "x"}, "hosts": []}
        h = _parse_luma_event(entry)
        assert h.location == "Online"

    def test_empty_event_returns_none(self):
        assert _parse_luma_event({"event": {}}) is None

    def test_missing_event_returns_none(self):
        assert _parse_luma_event({}) is None

    def test_no_name_returns_none(self):
        assert _parse_luma_event({"event": {"url": "x"}}) is None

    def test_hosts_limited_to_three(self):
        entry = {
            "event": {"name": "T", "url": "x"},
            "hosts": [{"name": f"H{i}"} for i in range(5)],
        }
        h = _parse_luma_event(entry)
        assert h.organizer == "H0, H1, H2"

    def test_hosts_skip_empty_names(self):
        entry = {
            "event": {"name": "T", "url": "x"},
            "hosts": [{"name": "A"}, {"name": ""}, {"name": "B"}],
        }
        h = _parse_luma_event(entry)
        assert h.organizer == "A, B"

    def test_geo_only_city(self):
        entry = {
            "event": {"name": "T", "url": "x", "geo_address_info": {"city": "Austin"}},
            "hosts": [],
        }
        h = _parse_luma_event(entry)
        assert "Austin" in h.location


class TestIsHackathon:
    def test_hackathon_in_name(self):
        h = Hackathon(name="SF Hackathon 2026", url="", source="luma")
        assert _is_hackathon(h)

    def test_hack_night_in_name(self):
        h = Hackathon(name="Friday Hack Night", url="", source="luma")
        assert _is_hackathon(h)

    def test_buildathon_in_description(self):
        h = Hackathon(name="Tech Event", url="", source="luma", description="Join our buildathon!")
        assert _is_hackathon(h)

    def test_keyword_in_description(self):
        """Themes aren't checked by structural scorer — keywords must be in name or description."""
        h = Hackathon(name="Event", url="", source="luma", description="Join the code jam this weekend")
        assert _is_hackathon(h)

    def test_non_hackathon(self):
        h = Hackathon(name="AI Meetup", url="", source="luma", description="Learn about AI")
        assert not _is_hackathon(h)

    def test_case_insensitive(self):
        h = Hackathon(name="HACKATHON 2026", url="", source="luma")
        assert _is_hackathon(h)

    def test_hacking_with_duration(self):
        """'hacking' is a soft keyword (+1), needs duration signal (+2) to pass threshold."""
        from datetime import datetime, timezone
        h = Hackathon(
            name="Civic Hacking Day", url="", source="luma",
            start_date=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),  # Saturday
            end_date=datetime(2026, 3, 21, 20, 0, tzinfo=timezone.utc),   # 11h
        )
        assert _is_hackathon(h)

    def test_hacking_alone_insufficient(self):
        """'hacking' without structural support doesn't pass threshold."""
        h = Hackathon(name="Civic Hacking Day", url="", source="luma")
        assert not _is_hackathon(h)


class TestHackathonScore:
    """Test the structural scoring system directly."""

    def test_strong_keyword_alone(self):
        h = Hackathon(name="SF Hackathon 2026", url="", source="luma")
        assert _hackathon_score(h) == 3

    def test_anti_keyword_reduces(self):
        h = Hackathon(name="Hackathon Happy Hour", url="", source="luma")
        assert _hackathon_score(h) == 1  # +3 strong, -2 anti

    def test_duration_signal(self):
        from datetime import datetime, timezone
        h = Hackathon(
            name="Tech Event", url="", source="luma",
            start_date=datetime(2026, 3, 21, 9, 0, tzinfo=timezone.utc),
            end_date=datetime(2026, 3, 22, 18, 0, tzinfo=timezone.utc),  # 33h
        )
        assert _hackathon_score(h) == 4  # +2 (>6h) +1 (>12h) +1 (Saturday)

    def test_conference_anti_keyword_cancels_duration(self):
        from datetime import datetime, timezone
        h = Hackathon(
            name="AI Conference at Stanford", url="", source="luma",
            start_date=datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc),   # Thursday
            end_date=datetime(2026, 3, 20, 21, 0, tzinfo=timezone.utc),    # 36h
        )
        score = _hackathon_score(h)
        assert score < 2  # duration (+3) but conference anti (-2) = 1, doesn't pass

    def test_pure_happy_hour(self):
        h = Hackathon(name="GTC Happy Hour with Drinks", url="", source="luma")
        assert _hackathon_score(h) == -2

    def test_weekend_hack_sprint(self):
        from datetime import datetime, timezone
        h = Hackathon(
            name="AI Sprint: 48hr Challenge", url="", source="luma",
            start_date=datetime(2026, 3, 21, 18, 0, tzinfo=timezone.utc),  # Saturday
            end_date=datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc),    # 48h
        )
        score = _hackathon_score(h)
        assert score >= 2  # soft "sprint"/"challenge" (+1) + >6h (+2) + >12h (+1) + weekend (+1)

    def test_neutral_event_zero(self):
        h = Hackathon(name="Music and Philosophy of Life", url="", source="luma")
        assert _hackathon_score(h) == 0
