"""Tests for pre-registration readiness checks (preflight.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.composer import PortfolioPlan, TeamMember, TrackAssignment
from bob.platform_fields import PlatformField, PlatformFieldRegistry
from bob.preflight import (
    ProfileGap,
    check_login_readiness,
    check_registration_readiness,
    resolve_gaps_interactive,
)
from bob.roster.models import MemberProfile
from bob.roster.store import RosterStore


# ── Helpers ──────────────────────────────────────────────────────────


def _make_portfolio(
    teams: list[tuple[str, list[str]]],
) -> PortfolioPlan:
    """Build a minimal PortfolioPlan.

    *teams* is a list of (registration_platform, [member_ids]).
    """
    assignments = []
    for platform, member_ids in teams:
        assignments.append(
            TrackAssignment(
                track_name="test-track",
                track_prize="$1000",
                play_type="execution",
                ev_score=0.8,
                project_idea="test idea",
                sponsor_apis=[],
                team=[TeamMember(member_id=mid, role="builder", reason="test") for mid in member_ids],
                persona_ids=[],
                registration_platform=platform,
            )
        )
    return PortfolioPlan(
        event_id="evt-1",
        event_name="Test Hackathon",
        situation_map_root="/tmp/map",
        assignments=assignments,
        unassigned_tracks=[],
        budget_notes="",
    )


def _make_registry(tmp_path: Path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir()
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_account(
    account_id: str,
    member_id: str,
    session_state_path: str | None = None,
) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        platform=Platform.DEVPOST,
        username=f"user-{account_id}",
        credential_ref=f"vault://{account_id}",
        member_id=member_id,
        session_state_path=session_state_path,
    )


# ── check_registration_readiness tests ───────────────────────────────


class TestCheckRegistrationReadiness:
    def test_member_missing_required_field_returns_gap(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        field_reg.add_field("devpost", PlatformField(name="email", label="Email", required=True))

        portfolio = _make_portfolio([("devpost", ["alice"])])
        registry = _make_registry(tmp_path)

        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert len(gaps) == 1
        assert gaps[0].member_id == "alice"
        assert gaps[0].field_name == "email"
        assert gaps[0].label == "Email"
        assert gaps[0].platform == "devpost"
        assert gaps[0].required is True

    def test_member_has_all_required_fields_no_gaps(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(
            MemberProfile(
                member_id="alice",
                display_name="Alice",
                attributes={"email": "alice@test.com"},
            )
        )

        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        field_reg.add_field("devpost", PlatformField(name="email", label="Email", required=True))

        portfolio = _make_portfolio([("devpost", ["alice"])])
        registry = _make_registry(tmp_path)

        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert gaps == []

    def test_unknown_platform_no_fields_no_gaps(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        # No fields registered for "unknown-platform"

        portfolio = _make_portfolio([("unknown-platform", ["alice"])])
        registry = _make_registry(tmp_path)

        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert gaps == []

    def test_empty_attribute_value_treated_as_missing(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(
            MemberProfile(
                member_id="alice",
                display_name="Alice",
                attributes={"email": ""},
            )
        )

        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        field_reg.add_field("devpost", PlatformField(name="email", label="Email", required=True))

        portfolio = _make_portfolio([("devpost", ["alice"])])
        registry = _make_registry(tmp_path)

        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert len(gaps) == 1
        assert gaps[0].field_name == "email"

    def test_member_not_in_roster_all_fields_are_gaps(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        # Don't save any member — "ghost" doesn't exist

        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        field_reg.add_field("devpost", PlatformField(name="email", label="Email", required=True))
        field_reg.add_field("devpost", PlatformField(name="team_name", label="Team", required=True))

        portfolio = _make_portfolio([("devpost", ["ghost"])])
        registry = _make_registry(tmp_path)

        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert len(gaps) == 2
        names = {g.field_name for g in gaps}
        assert names == {"email", "team_name"}

    def test_no_registration_platform_skipped(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        field_reg = PlatformFieldRegistry(base_dir=tmp_path / "fields")
        registry = _make_registry(tmp_path)

        portfolio = _make_portfolio([("", ["alice"])])
        gaps = check_registration_readiness(portfolio, roster, registry, field_reg)
        assert gaps == []


# ── check_login_readiness tests ──────────────────────────────────────


class TestCheckLoginReadiness:
    def test_account_with_no_session_state_path_returned(self, tmp_path):
        registry = _make_registry(tmp_path)
        acct = _make_account("acc-1", "alice", session_state_path=None)
        registry.save_account(acct)

        portfolio = _make_portfolio([("devpost", ["alice"])])
        stale = check_login_readiness(portfolio, registry)
        assert "acc-1" in stale

    def test_account_with_nonexistent_session_file_returned(self, tmp_path):
        registry = _make_registry(tmp_path)
        acct = _make_account("acc-1", "alice", session_state_path="/nonexistent/session.json")
        registry.save_account(acct)

        portfolio = _make_portfolio([("devpost", ["alice"])])
        stale = check_login_readiness(portfolio, registry)
        assert "acc-1" in stale

    def test_account_with_valid_session_file_not_returned(self, tmp_path):
        session_file = tmp_path / "session.json"
        session_file.write_text("{}")

        registry = _make_registry(tmp_path)
        acct = _make_account("acc-1", "alice", session_state_path=str(session_file))
        registry.save_account(acct)

        portfolio = _make_portfolio([("devpost", ["alice"])])
        stale = check_login_readiness(portfolio, registry)
        assert "acc-1" not in stale

    def test_dedup_accounts_across_assignments(self, tmp_path):
        registry = _make_registry(tmp_path)
        acct = _make_account("acc-1", "alice", session_state_path=None)
        registry.save_account(acct)

        # Alice appears in two assignments
        portfolio = _make_portfolio([
            ("devpost", ["alice"]),
            ("ethglobal", ["alice"]),
        ])
        stale = check_login_readiness(portfolio, registry)
        # Should only appear once despite two assignments
        assert stale.count("acc-1") == 1


# ── resolve_gaps_interactive tests ───────────────────────────────────


class TestResolveGapsInteractive:
    def test_mock_stdin_input_writes_back_to_profile(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        gaps = [
            ProfileGap(
                member_id="alice",
                field_name="email",
                label="Email",
                platform="devpost",
                required=True,
            ),
        ]

        with patch("builtins.input", return_value="alice@test.com"):
            resolved = resolve_gaps_interactive(gaps, roster)

        assert resolved == 1
        profile = roster.load_member("alice")
        assert profile is not None
        assert profile.attributes["email"] == "alice@test.com"

    def test_skip_on_empty_input(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        gaps = [
            ProfileGap(
                member_id="alice",
                field_name="email",
                label="Email",
                platform="devpost",
                required=True,
            ),
        ]

        with patch("builtins.input", return_value=""):
            resolved = resolve_gaps_interactive(gaps, roster)

        assert resolved == 0
        profile = roster.load_member("alice")
        assert profile is not None
        assert "email" not in profile.attributes

    def test_multiple_gaps_resolved(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        gaps = [
            ProfileGap(member_id="alice", field_name="email", label="Email", platform="devpost", required=True),
            ProfileGap(member_id="alice", field_name="team_name", label="Team", platform="devpost", required=True),
        ]

        responses = iter(["alice@test.com", "Team Alpha"])
        with patch("builtins.input", side_effect=responses):
            resolved = resolve_gaps_interactive(gaps, roster)

        assert resolved == 2
        profile = roster.load_member("alice")
        assert profile is not None
        assert profile.attributes["email"] == "alice@test.com"
        assert profile.attributes["team_name"] == "Team Alpha"

    def test_missing_member_in_roster_skipped(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        # Don't create "ghost" member

        gaps = [
            ProfileGap(member_id="ghost", field_name="email", label="Email", platform="devpost", required=True),
        ]

        with patch("builtins.input", return_value="ghost@test.com"):
            resolved = resolve_gaps_interactive(gaps, roster)

        assert resolved == 0

    def test_eof_stops_early(self, tmp_path):
        roster = RosterStore(base_dir=tmp_path / "roster")
        roster.save_member(MemberProfile(member_id="alice", display_name="Alice"))

        gaps = [
            ProfileGap(member_id="alice", field_name="email", label="Email", platform="devpost", required=True),
            ProfileGap(member_id="alice", field_name="team_name", label="Team", platform="devpost", required=True),
        ]

        with patch("builtins.input", side_effect=EOFError):
            resolved = resolve_gaps_interactive(gaps, roster)

        assert resolved == 0
