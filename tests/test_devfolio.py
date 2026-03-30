"""Tests for the Devfolio source parser."""


import pytest

from bob.models import Format
from bob.sources.devfolio import _parse_hackathon, _parse_iso


class TestParseIso:
    def test_utc_z(self):
        result = _parse_iso("2026-06-01T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_empty(self):
        assert _parse_iso("") is None

    def test_none(self):
        assert _parse_iso(None) is None

    def test_invalid(self):
        assert _parse_iso("garbage") is None


class TestParseHackathon:
    @pytest.fixture
    def full_entry(self):
        return {
            "name": "ETHGlobal SF",
            "slug": "ethglobal-sf",
            "is_online": False,
            "hackathon_setting": {"is_hybrid": False},
            "city": "San Francisco",
            "state": "CA",
            "starts_at": "2026-07-01T09:00:00Z",
            "ends_at": "2026-07-03T18:00:00Z",
            "themes": [{"name": "Web3"}, {"name": "DeFi"}],
            "prizes": [
                {"amount": 10000, "currency": "USD"},
                {"amount": 5000, "currency": "USD"},
            ],
            "participants_count": 800,
            "cover_img": "https://example.com/cover.png",
            "tagline": "Build the future of finance",
        }

    def test_full_entry(self, full_entry):
        h = _parse_hackathon(full_entry)
        assert h.name == "ETHGlobal SF"
        assert h.url == "https://ethglobal-sf.devfolio.co/"
        assert h.source == "devfolio"
        assert h.format == Format.IN_PERSON
        assert h.location == "San Francisco, CA"
        assert h.start_date is not None
        assert h.end_date is not None
        assert h.themes == ["Web3", "DeFi"]
        assert h.prize_amount == "15,000 USD"
        assert h.participants == 800
        assert h.image_url == "https://example.com/cover.png"
        assert h.description == "Build the future of finance"

    def test_online_event(self):
        entry = {"name": "Virtual", "slug": "v", "is_online": True}
        h = _parse_hackathon(entry)
        assert h.format == Format.VIRTUAL
        assert h.location == "Online"

    def test_hybrid_event(self):
        entry = {
            "name": "Hybrid",
            "slug": "h",
            "is_online": False,
            "hackathon_setting": {"is_hybrid": True},
            "city": "NYC",
            "state": "NY",
        }
        h = _parse_hackathon(entry)
        assert h.format == Format.HYBRID

    def test_in_person_no_city_state(self):
        entry = {
            "name": "T",
            "slug": "t",
            "is_online": False,
            "location": "Some Venue",
        }
        h = _parse_hackathon(entry)
        assert h.format == Format.IN_PERSON
        assert h.location == "Some Venue"

    def test_in_person_no_location_at_all(self):
        entry = {"name": "T", "slug": "t", "is_online": False}
        h = _parse_hackathon(entry)
        assert h.location == "Online"

    def test_no_slug_empty_url(self):
        entry = {"name": "T"}
        h = _parse_hackathon(entry)
        assert h.url == ""

    def test_slug_builds_url(self):
        entry = {"name": "T", "slug": "my-hack"}
        h = _parse_hackathon(entry)
        assert h.url == "https://my-hack.devfolio.co/"

    def test_no_prizes(self):
        entry = {"name": "T", "slug": "t"}
        h = _parse_hackathon(entry)
        assert h.prize_amount == ""

    def test_prizes_empty_list(self):
        entry = {"name": "T", "slug": "t", "prizes": []}
        h = _parse_hackathon(entry)
        assert h.prize_amount == ""

    def test_prizes_mixed_currencies(self):
        entry = {
            "name": "T",
            "slug": "t",
            "prizes": [
                {"amount": 100, "currency": "USD"},
                {"amount": 200, "currency": "EUR"},
            ],
        }
        h = _parse_hackathon(entry)
        # Mixed currencies defaults to USD
        assert "USD" in h.prize_amount

    def test_prizes_zero_amount_filtered(self):
        entry = {
            "name": "T",
            "slug": "t",
            "prizes": [{"amount": 0, "currency": "USD"}, {"amount": 500, "currency": "USD"}],
        }
        h = _parse_hackathon(entry)
        assert "500" in h.prize_amount

    def test_themes_missing_name_key(self):
        entry = {"name": "T", "slug": "t", "themes": [{"name": "AI"}, {"id": 2}]}
        h = _parse_hackathon(entry)
        assert h.themes == ["AI"]

    def test_missing_name_defaults_untitled(self):
        entry = {"slug": "t"}
        h = _parse_hackathon(entry)
        assert h.name == "Untitled"

    def test_hackathon_setting_none(self):
        entry = {"name": "T", "slug": "t", "hackathon_setting": None, "is_online": True}
        h = _parse_hackathon(entry)
        assert h.format == Format.VIRTUAL

    def test_only_city_no_state(self):
        entry = {"name": "T", "slug": "t", "is_online": False, "city": "Austin"}
        h = _parse_hackathon(entry)
        assert h.location == "Austin"
