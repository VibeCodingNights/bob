"""Tests for account lifecycle — ensure_account and ensure_all_accounts."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.platform_fields import PlatformFieldRegistry
from bob.roster.models import MemberProfile
from bob.roster.store import RosterStore


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_roster(tmp_path) -> RosterStore:
    roster_dir = tmp_path / "roster"
    roster_dir.mkdir(exist_ok=True)
    return RosterStore(base_dir=roster_dir)


def _make_field_registry(tmp_path) -> PlatformFieldRegistry:
    fr_dir = tmp_path / "platform_fields"
    fr_dir.mkdir(exist_ok=True)
    return PlatformFieldRegistry(base_dir=fr_dir)


def _make_member(member_id="alice", email="alice@example.com"):
    attrs = {"email": email} if email else {}
    return MemberProfile(
        member_id=member_id,
        display_name=member_id.capitalize(),
        attributes=attrs,
    )


def _make_account(
    registry: AccountRegistry,
    account_id: str = "alice-devpost",
    platform: Platform = Platform.DEVPOST,
    member_id: str = "alice",
    session_state_path: str | None = None,
) -> PlatformAccount:
    account = PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=f"{member_id}123",
        credential_ref=f"{account_id}-cred",
        member_id=member_id,
        session_state_path=session_state_path,
    )
    registry.save_account(account)
    return account


# ── _session_is_valid ────────────────────────────────────────────────


class TestSessionIsValid:
    def test_returns_false_when_no_path(self):
        from bob.account_lifecycle import _session_is_valid

        account = PlatformAccount(
            account_id="a",
            platform=Platform.DEVPOST,
            username="u",
            credential_ref="r",
            member_id="m",
            session_state_path=None,
        )
        assert _session_is_valid(account) is False

    def test_returns_false_when_file_missing(self, tmp_path):
        from bob.account_lifecycle import _session_is_valid

        account = PlatformAccount(
            account_id="a",
            platform=Platform.DEVPOST,
            username="u",
            credential_ref="r",
            member_id="m",
            session_state_path=str(tmp_path / "nonexistent.json"),
        )
        assert _session_is_valid(account) is False

    def test_returns_true_when_file_exists(self, tmp_path):
        from bob.account_lifecycle import _session_is_valid

        state_file = tmp_path / "session.json"
        state_file.write_text("{}")
        account = PlatformAccount(
            account_id="a",
            platform=Platform.DEVPOST,
            username="u",
            credential_ref="r",
            member_id="m",
            session_state_path=str(state_file),
        )
        assert _session_is_valid(account) is True


# ── ensure_account ───────────────────────────────────────────────────


class TestEnsureAccount:
    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.auto_login", new_callable=AsyncMock)
    @patch("bob.account_lifecycle.signup_account", new_callable=AsyncMock)
    async def test_existing_valid_session_returns_immediately(
        self, mock_signup, mock_login, tmp_path
    ):
        """Account with valid session file returns without signup or login."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        state_file = tmp_path / "session.json"
        state_file.write_text("{}")
        _make_account(registry, session_state_path=str(state_file))

        from bob.account_lifecycle import ensure_account

        result = await ensure_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is not None
        assert result.account_id == "alice-devpost"
        mock_signup.assert_not_called()
        mock_login.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.auto_login", new_callable=AsyncMock)
    @patch("bob.account_lifecycle.signup_account", new_callable=AsyncMock)
    async def test_stale_session_calls_auto_login(
        self, mock_signup, mock_login, tmp_path
    ):
        """Account with missing session file triggers auto_login."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        # Account exists but no session file
        _make_account(registry, session_state_path=str(tmp_path / "gone.json"))

        mock_login.return_value = True

        from bob.account_lifecycle import ensure_account

        result = await ensure_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is not None
        mock_login.assert_called_once()
        mock_signup.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.auto_login", new_callable=AsyncMock)
    @patch("bob.account_lifecycle.signup_account", new_callable=AsyncMock)
    async def test_no_account_calls_signup(
        self, mock_signup, mock_login, tmp_path
    ):
        """No existing account triggers signup_account."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        fake_account = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )
        mock_signup.return_value = fake_account

        from bob.account_lifecycle import ensure_account

        result = await ensure_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is not None
        assert result.account_id == "alice-devpost"
        mock_signup.assert_called_once()
        mock_login.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.auto_login", new_callable=AsyncMock)
    @patch("bob.account_lifecycle.signup_account", new_callable=AsyncMock)
    async def test_signup_fails_returns_none(
        self, mock_signup, mock_login, tmp_path
    ):
        """When signup fails, ensure_account returns None."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        mock_signup.return_value = None

        from bob.account_lifecycle import ensure_account

        result = await ensure_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.auto_login", new_callable=AsyncMock)
    @patch("bob.account_lifecycle.signup_account", new_callable=AsyncMock)
    async def test_auto_login_fails_returns_none(
        self, mock_signup, mock_login, tmp_path
    ):
        """When auto_login fails, ensure_account returns None."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        _make_account(registry, session_state_path=str(tmp_path / "gone.json"))
        mock_login.return_value = False

        from bob.account_lifecycle import ensure_account

        result = await ensure_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is None


# ── ensure_all_accounts ──────────────────────────────────────────────


class TestEnsureAllAccounts:
    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_processes_all_assignments(self, mock_ensure, tmp_path):
        """ensure_all_accounts calls ensure_account for each assignment's first member."""
        from bob.composer import PortfolioPlan, TeamMember, TrackAssignment

        mock_ensure.return_value = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[
                TrackAssignment(
                    track_name="Track A",
                    track_prize="$1k",
                    play_type="execution",
                    ev_score=0.8,
                    project_idea="idea",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="builder", reason="test")],
                    persona_ids=[],
                    registration_platform="devpost",
                ),
                TrackAssignment(
                    track_name="Track B",
                    track_prize="$2k",
                    play_type="moonshot",
                    ev_score=0.6,
                    project_idea="idea2",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="bob", role="presenter", reason="test")],
                    persona_ids=[],
                    registration_platform="ethglobal",
                ),
            ],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        results = await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        # GitHub-first phase adds github calls for each member before platform calls
        calls = mock_ensure.call_args_list
        call_args = [(c.kwargs.get("member_id") or c.args[0], c.kwargs.get("platform") or c.args[1]) for c in calls]
        # GitHub ensured first for both members
        assert ("alice", "github") in call_args
        assert ("bob", "github") in call_args
        # Then platform-specific
        assert ("alice", "devpost") in call_args
        assert ("bob", "ethglobal") in call_args

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_deduplicates_by_member_platform(self, mock_ensure, tmp_path):
        """Same member+platform across assignments is only ensured once."""
        from bob.composer import PortfolioPlan, TeamMember, TrackAssignment

        mock_ensure.return_value = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[
                TrackAssignment(
                    track_name="Track A",
                    track_prize="$1k",
                    play_type="execution",
                    ev_score=0.8,
                    project_idea="idea",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="builder", reason="test")],
                    persona_ids=[],
                    registration_platform="devpost",
                ),
                TrackAssignment(
                    track_name="Track B",
                    track_prize="$2k",
                    play_type="moonshot",
                    ev_score=0.6,
                    project_idea="idea2",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="presenter", reason="test")],
                    persona_ids=[],
                    registration_platform="devpost",
                ),
            ],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        results = await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        # GitHub-first adds alice:github, then alice:devpost (deduped across assignments)
        calls = mock_ensure.call_args_list
        call_args = [(c.kwargs.get("member_id") or c.args[0], c.kwargs.get("platform") or c.args[1]) for c in calls]
        assert call_args.count(("alice", "devpost")) == 1  # deduped
        assert ("alice", "github") in call_args  # GitHub-first phase

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_empty_portfolio_returns_empty(self, mock_ensure, tmp_path):
        """Empty portfolio returns empty dict without calling ensure_account."""
        from bob.composer import PortfolioPlan

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        results = await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert results == {}
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_skips_assignments_without_platform(self, mock_ensure, tmp_path):
        """Assignments with empty registration_platform are skipped."""
        from bob.composer import PortfolioPlan, TeamMember, TrackAssignment

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[
                TrackAssignment(
                    track_name="Track A",
                    track_prize="$1k",
                    play_type="execution",
                    ev_score=0.8,
                    project_idea="idea",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="builder", reason="test")],
                    persona_ids=[],
                    registration_platform="",
                ),
            ],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        results = await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert results == {}
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_github_processed_before_other_platforms(self, mock_ensure, tmp_path):
        """GitHub accounts are ensured in phase 1, before any non-GitHub platforms."""
        from bob.composer import PortfolioPlan, TeamMember, TrackAssignment

        mock_ensure.return_value = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[
                TrackAssignment(
                    track_name="Track A",
                    track_prize="$1k",
                    play_type="execution",
                    ev_score=0.8,
                    project_idea="idea",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="builder", reason="test")],
                    persona_ids=[],
                    registration_platform="devpost",
                ),
                TrackAssignment(
                    track_name="Track B",
                    track_prize="$2k",
                    play_type="moonshot",
                    ev_score=0.6,
                    project_idea="idea2",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="presenter", reason="test")],
                    persona_ids=[],
                    registration_platform="ethglobal",
                ),
            ],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        calls = mock_ensure.call_args_list
        call_args = [(c.args[0], c.args[1]) for c in calls]

        # Find indices: all github calls must come before any non-github calls
        github_indices = [i for i, (_, p) in enumerate(call_args) if p == "github"]
        other_indices = [i for i, (_, p) in enumerate(call_args) if p != "github"]

        assert len(github_indices) > 0, "Expected at least one GitHub call"
        assert len(other_indices) > 0, "Expected at least one non-GitHub call"
        assert max(github_indices) < min(other_indices), (
            f"GitHub calls {github_indices} must all come before "
            f"non-GitHub calls {other_indices}. Order was: {call_args}"
        )

    @pytest.mark.asyncio
    @patch("bob.account_lifecycle.ensure_account", new_callable=AsyncMock)
    async def test_github_assignment_not_duplicated(self, mock_ensure, tmp_path):
        """If a member already needs GitHub explicitly, it isn't called twice."""
        from bob.composer import PortfolioPlan, TeamMember, TrackAssignment

        mock_ensure.return_value = PlatformAccount(
            account_id="alice-github",
            platform=Platform.GITHUB,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )

        portfolio = PortfolioPlan(
            event_id="test",
            event_name="Test Hack",
            situation_map_root=".",
            assignments=[
                TrackAssignment(
                    track_name="Track A",
                    track_prize="$1k",
                    play_type="execution",
                    ev_score=0.8,
                    project_idea="idea",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="builder", reason="test")],
                    persona_ids=[],
                    registration_platform="github",
                ),
                TrackAssignment(
                    track_name="Track B",
                    track_prize="$2k",
                    play_type="moonshot",
                    ev_score=0.6,
                    project_idea="idea2",
                    sponsor_apis=[],
                    team=[TeamMember(member_id="alice", role="presenter", reason="test")],
                    persona_ids=[],
                    registration_platform="devpost",
                ),
            ],
            unassigned_tracks=[],
            budget_notes="",
        )

        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.account_lifecycle import ensure_all_accounts

        await ensure_all_accounts(
            portfolio=portfolio,
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        calls = mock_ensure.call_args_list
        call_args = [(c.args[0], c.args[1]) for c in calls]

        # alice:github should only be called once (not duplicated)
        assert call_args.count(("alice", "github")) == 1
        assert ("alice", "devpost") in call_args
