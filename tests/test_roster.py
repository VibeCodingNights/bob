"""Tests for roster models and YAML-based RosterStore."""

import yaml

from bob.roster.models import (
    Availability,
    HackathonEntry,
    MemberProfile,
    PresentationStyle,
    Skill,
)
from bob.roster.store import RosterStore


# ── Model tests ───────────────────────────────────────────────────────


class TestPresentationStyle:
    def test_enum_values(self):
        assert PresentationStyle.ENERGETIC == "energetic"
        assert PresentationStyle.METHODICAL == "methodical"
        assert PresentationStyle.NARRATIVE == "narrative"
        assert PresentationStyle.TECHNICAL == "technical"


class TestSkill:
    def test_creation_with_defaults(self):
        s = Skill(name="Python", domain="backend", depth=4)
        assert s.name == "Python"
        assert s.domain == "backend"
        assert s.depth == 4
        assert s.evidence == []

    def test_creation_with_evidence(self):
        s = Skill(name="Rust", domain="systems", depth=5, evidence=["https://github.com/example"])
        assert s.evidence == ["https://github.com/example"]


class TestMemberProfile:
    def test_defaults(self):
        m = MemberProfile(member_id="alice", display_name="Alice")
        assert m.member_id == "alice"
        assert m.display_name == "Alice"
        assert m.platform_account_ids == []
        assert m.skills == []
        assert m.interests == []
        assert m.history == []
        assert m.presentation_style == PresentationStyle.TECHNICAL
        assert m.availability.timezone == "UTC"
        assert m.attributes == {}
        assert m.notes == ""

    def test_all_fields(self):
        skill = Skill(name="ML", domain="ai", depth=5, evidence=["https://arxiv.org"])
        entry = HackathonEntry(
            event_name="HackMIT",
            event_url="https://hackmit.org",
            track="AI",
            placement="1st",
            role="lead",
            feedback="great demo",
        )
        avail = Availability(
            timezone="America/New_York",
            commitment="partial",
            blackout_dates=["2026-03-25"],
        )
        m = MemberProfile(
            member_id="bob",
            display_name="Bob Builder",
            platform_account_ids=["devpost-bob"],
            skills=[skill],
            interests=["AI", "crypto"],
            history=[entry],
            presentation_style=PresentationStyle.ENERGETIC,
            availability=avail,
            notes="likes pizza",
        )
        assert m.member_id == "bob"
        assert m.skills[0].domain == "ai"
        assert m.history[0].placement == "1st"
        assert m.presentation_style == PresentationStyle.ENERGETIC
        assert m.availability.commitment == "partial"
        assert m.availability.blackout_dates == ["2026-03-25"]
        assert m.notes == "likes pizza"


# ── RosterStore tests ─────────────────────────────────────────────────


def _make_profile(
    member_id: str = "test-member",
    display_name: str = "Test Member",
    **kwargs,
) -> MemberProfile:
    return MemberProfile(member_id=member_id, display_name=display_name, **kwargs)


class TestRosterStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        original = _make_profile(
            member_id="noot",
            display_name="Noot",
            skills=[Skill(name="Go", domain="backend", depth=5)],
            presentation_style=PresentationStyle.NARRATIVE,
            availability=Availability(timezone="America/Los_Angeles"),
        )
        store.save_member(original)
        loaded = store.load_member("noot")
        assert loaded is not None
        assert loaded.member_id == original.member_id
        assert loaded.display_name == original.display_name
        assert loaded.skills[0].name == "Go"
        assert loaded.presentation_style == PresentationStyle.NARRATIVE
        assert loaded.availability.timezone == "America/Los_Angeles"

    def test_load_missing_returns_none(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        assert store.load_member("ghost") is None

    def test_list_members(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(_make_profile(member_id="alice", display_name="Alice"))
        store.save_member(_make_profile(member_id="bob", display_name="Bob"))
        store.save_member(_make_profile(member_id="carol", display_name="Carol"))
        members = store.list_members()
        assert len(members) == 3
        ids = {m.member_id for m in members}
        assert ids == {"alice", "bob", "carol"}

    def test_get_available_members_excludes_blackout(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        available = _make_profile(
            member_id="free",
            display_name="Free",
            availability=Availability(timezone="UTC"),
        )
        busy = _make_profile(
            member_id="busy",
            display_name="Busy",
            availability=Availability(
                timezone="UTC",
                blackout_dates=["2026-04-01", "2026-04-02", "2026-04-03"],
            ),
        )
        store.save_member(available)
        store.save_member(busy)

        result = store.get_available_members("2026-04-01", "2026-04-03")
        ids = [m.member_id for m in result]
        assert "free" in ids
        assert "busy" not in ids

    def test_get_available_members_includes_non_overlapping(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        member = _make_profile(
            member_id="partial",
            display_name="Partial",
            availability=Availability(
                timezone="UTC",
                blackout_dates=["2026-05-10"],
            ),
        )
        store.save_member(member)

        result = store.get_available_members("2026-06-01", "2026-06-05")
        assert len(result) == 1
        assert result[0].member_id == "partial"

    def test_get_members_by_skill(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(
            _make_profile(
                member_id="ml-dev",
                display_name="ML Dev",
                skills=[Skill(name="PyTorch", domain="AI", depth=4)],
            )
        )
        store.save_member(
            _make_profile(
                member_id="web-dev",
                display_name="Web Dev",
                skills=[Skill(name="React", domain="frontend", depth=3)],
            )
        )

        ai_members = store.get_members_by_skill("ai")
        assert len(ai_members) == 1
        assert ai_members[0].member_id == "ml-dev"

    def test_get_members_by_skill_case_insensitive(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(
            _make_profile(
                member_id="dev",
                display_name="Dev",
                skills=[Skill(name="Solidity", domain="Blockchain", depth=4)],
            )
        )
        assert len(store.get_members_by_skill("blockchain")) == 1
        assert len(store.get_members_by_skill("BLOCKCHAIN")) == 1

    def test_delete_member_exists(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(_make_profile(member_id="doomed"))
        assert store.delete_member("doomed") is True
        assert store.load_member("doomed") is None

    def test_delete_member_missing(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        assert store.delete_member("nonexistent") is False

    def test_yaml_preserves_enums(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(
            _make_profile(
                member_id="enumtest",
                display_name="Enum Test",
                presentation_style=PresentationStyle.ENERGETIC,
            )
        )
        # Read raw YAML and verify enums are stored as plain strings
        raw = (tmp_path / "enumtest.yaml").read_text()
        data = yaml.safe_load(raw)
        assert data["presentation_style"] == "energetic"
        assert isinstance(data["presentation_style"], str)

    def test_save_overwrites_existing(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(_make_profile(member_id="update-me", display_name="V1"))
        store.save_member(_make_profile(member_id="update-me", display_name="V2"))
        loaded = store.load_member("update-me")
        assert loaded is not None
        assert loaded.display_name == "V2"
        assert len(store.list_members()) == 1

    def test_full_roundtrip_fidelity(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        original = MemberProfile(
            member_id="full",
            display_name="Full Profile",
            platform_account_ids=["devpost-full", "ethglobal-full"],
            skills=[
                Skill(name="Python", domain="backend", depth=5, evidence=["https://gh.com/a"]),
                Skill(name="React", domain="frontend", depth=3),
            ],
            interests=["AI", "web3"],
            history=[
                HackathonEntry(
                    event_name="HackMIT",
                    event_url="https://hackmit.org",
                    track="AI",
                    placement="1st",
                    role="lead",
                    feedback="great",
                ),
            ],
            presentation_style=PresentationStyle.NARRATIVE,
            availability=Availability(
                timezone="America/Chicago",
                commitment="partial",
                blackout_dates=["2026-04-01", "2026-04-02"],
            ),
            notes="test notes",
        )
        store.save_member(original)
        loaded = store.load_member("full")
        assert loaded is not None
        assert loaded.member_id == original.member_id
        assert loaded.display_name == original.display_name
        assert loaded.platform_account_ids == original.platform_account_ids
        assert len(loaded.skills) == 2
        assert loaded.skills[0].evidence == ["https://gh.com/a"]
        assert loaded.skills[1].evidence == []
        assert loaded.interests == original.interests
        assert loaded.history[0].event_name == "HackMIT"
        assert loaded.history[0].feedback == "great"
        assert loaded.presentation_style == PresentationStyle.NARRATIVE
        assert loaded.availability.commitment == "partial"
        assert loaded.availability.blackout_dates == ["2026-04-01", "2026-04-02"]
        assert loaded.notes == "test notes"

    def test_member_id_path_traversal_sanitized(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(_make_profile(member_id="../../../etc/passwd"))
        # File should be written inside tmp_path, not outside it
        files = list(tmp_path.glob("*.yaml"))
        assert len(files) == 1
        assert files[0].parent == tmp_path

    def test_attributes_roundtrip(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        original = _make_profile(
            member_id="attr-test",
            display_name="Attr Test",
            attributes={"github": "attruser", "role": "lead", "team": "alpha"},
        )
        store.save_member(original)
        loaded = store.load_member("attr-test")
        assert loaded is not None
        assert loaded.attributes == {"github": "attruser", "role": "lead", "team": "alpha"}

    def test_attributes_empty_default(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        store.save_member(_make_profile(member_id="no-attrs", display_name="No Attrs"))
        loaded = store.load_member("no-attrs")
        assert loaded is not None
        assert loaded.attributes == {}

    def test_attributes_special_characters(self, tmp_path):
        store = RosterStore(base_dir=tmp_path)
        original = _make_profile(
            member_id="special-attrs",
            display_name="Special Attrs",
            attributes={
                "bio": "Hello, world! I'm a developer & designer.",
                "motto": 'Code "fast", ship faster.',
                "emoji": "rockets and stars",
                "url": "https://example.com/profile?user=test&lang=en",
            },
        )
        store.save_member(original)
        loaded = store.load_member("special-attrs")
        assert loaded is not None
        assert loaded.attributes == original.attributes

    def test_attributes_yaml_coerces_non_string_values(self, tmp_path):
        """YAML loads int/bool natively; attributes must coerce to str."""
        raw = {
            "member_id": "coerce",
            "display_name": "Coerce Test",
            "attributes": {"age": 25, "verified": True, "score": 3.14},
        }
        (tmp_path / "coerce.yaml").write_text(yaml.safe_dump(raw))

        store = RosterStore(base_dir=tmp_path)
        loaded = store.load_member("coerce")
        assert loaded is not None
        for v in loaded.attributes.values():
            assert isinstance(v, str), f"expected str, got {type(v).__name__}: {v!r}"
        assert loaded.attributes["age"] == "25"
        assert loaded.attributes["verified"] == "True"
        assert loaded.attributes["score"] == "3.14"

    def test_load_with_missing_optional_fields(self, tmp_path):
        # Write a minimal YAML file manually (missing optional fields)
        minimal = {
            "member_id": "minimal",
            "display_name": "Minimal Member",
        }
        (tmp_path / "minimal.yaml").write_text(yaml.safe_dump(minimal))

        store = RosterStore(base_dir=tmp_path)
        loaded = store.load_member("minimal")
        assert loaded is not None
        assert loaded.member_id == "minimal"
        assert loaded.skills == []
        assert loaded.interests == []
        assert loaded.history == []
        assert loaded.platform_account_ids == []
        assert loaded.presentation_style == PresentationStyle.TECHNICAL
        assert loaded.availability.timezone == "UTC"
        assert loaded.notes == ""
