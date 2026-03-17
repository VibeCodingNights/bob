"""Tests for the Hackathon model."""



from hackathon_finder.models import Format, Hackathon, RegistrationStatus


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
