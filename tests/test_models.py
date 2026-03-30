"""Tests for the Hackathon model."""

import re
from datetime import datetime

from bob.models import Format, Hackathon, RegistrationStatus


class TestHackathonModel:
    def test_defaults(self):
        h = Hackathon(name="Test", url="https://example.com", source="devpost")
        assert h.format == Format.VIRTUAL
        assert h.location == "Online"
        assert h.start_date is None
        assert h.end_date is None
        assert h.organizer == ""
        assert h.registration_status == RegistrationStatus.UNKNOWN
        assert h.themes == []
        assert h.prize_amount == ""
        assert h.participants == 0
        assert h.image_url == ""
        assert h.description == ""

    def test_is_sf_positive(self):
        for loc in ("San Francisco, CA", "SF Bay Area", "bay area", "Silicon Valley"):
            h = Hackathon(name="Test", url="", source="test", location=loc)
            assert h.is_sf, f"Expected is_sf=True for location={loc!r}"

    def test_is_sf_negative(self):
        for loc in ("New York", "Online", "Boston, MA", ""):
            h = Hackathon(name="Test", url="", source="test", location=loc)
            assert not h.is_sf, f"Expected is_sf=False for location={loc!r}"

    def test_is_virtual(self):
        assert Hackathon(name="T", url="", source="t", format=Format.VIRTUAL).is_virtual
        assert Hackathon(name="T", url="", source="t", format=Format.HYBRID).is_virtual
        assert not Hackathon(name="T", url="", source="t", format=Format.IN_PERSON).is_virtual

    def test_dedup_key_strips_noise(self):
        h = Hackathon(name="Cool Hackathon 2026", url="", source="test")
        assert h.dedup_key() == "cool"

    def test_dedup_key_collapses_whitespace(self):
        h = Hackathon(name="  AI  ML  Hack  ", url="", source="test")
        assert h.dedup_key() == "aiml"

    def test_dedup_key_consistent(self):
        h1 = Hackathon(name="TreeHacks Hackathon", url="", source="devpost")
        h2 = Hackathon(name="TreeHacks Hack 2026", url="", source="mlh")
        assert h1.dedup_key() == h2.dedup_key()

    def test_event_id_deterministic(self):
        h = Hackathon(name="Test", url="https://example.com", source="devpost")
        assert h.event_id == h.event_id

    def test_event_id_unique(self):
        h1 = Hackathon(name="Alpha", url="https://a.com", source="devpost")
        h2 = Hackathon(name="Beta", url="https://b.com", source="devpost")
        assert h1.event_id != h2.event_id

    def test_event_id_with_start_date(self):
        dt = datetime(2026, 6, 1, 12, 0)
        h = Hackathon(name="HackDay", url="https://x.com", source="luma", start_date=dt)
        # Should use dedup_key + date, so same name+date from different URL gives same ID
        h2 = Hackathon(name="HackDay", url="https://y.com", source="devpost", start_date=dt)
        assert h.event_id == h2.event_id

    def test_event_id_without_start_date(self):
        h1 = Hackathon(name="Same", url="https://a.com", source="devpost")
        h2 = Hackathon(name="Same", url="https://b.com", source="devpost")
        # Falls back to URL, so different URLs produce different IDs
        assert h1.event_id != h2.event_id

    def test_event_id_length(self):
        h = Hackathon(name="Test", url="https://example.com", source="devpost")
        assert len(h.event_id) == 12
        assert re.fullmatch(r"[0-9a-f]{12}", h.event_id)

    def test_event_id_different_urls_same_name(self):
        dt = datetime(2026, 7, 15)
        h1 = Hackathon(name="Global Hackathon", url="https://devpost.com/g", source="devpost", start_date=dt)
        h2 = Hackathon(name="Global Hack 2026", url="https://mlh.io/g", source="mlh", start_date=dt)
        # Both have start_dates and same dedup_key + date => same event_id (cross-platform dedup)
        assert h1.event_id == h2.event_id


class TestFormat:
    def test_string_values(self):
        assert Format.IN_PERSON == "in-person"
        assert Format.VIRTUAL == "virtual"
        assert Format.HYBRID == "hybrid"


class TestRegistrationStatus:
    def test_string_values(self):
        assert RegistrationStatus.OPEN == "open"
        assert RegistrationStatus.UPCOMING == "upcoming"
        assert RegistrationStatus.CLOSED == "closed"
        assert RegistrationStatus.WAITLIST == "waitlist"
        assert RegistrationStatus.UNKNOWN == "unknown"
