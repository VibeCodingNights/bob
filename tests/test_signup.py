"""Tests for the signup agent — autonomous account creation."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest.py already installed shared fakes in sys.modules

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.telemetry import AgentResult
from bob.auth_strategy import AuthStrategyRegistry
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


def _make_member(member_id="alice", email="alice@example.com", **extra_attrs):
    attrs = {"email": email} if email else {}
    attrs.update(extra_attrs)
    return MemberProfile(
        member_id=member_id,
        display_name=member_id.capitalize(),
        attributes=attrs,
    )


def _agent_result(**kw):
    defaults = dict(input_tokens=100, output_tokens=50, total_turns=1, success=True)
    defaults.update(kw)
    return AgentResult(**defaults)


def _get_tool(server, name):
    return next(t for t in server["tools"] if t.name == name)


# ── Signup agent tests ───────────────────────────────────────────────


class TestSignupAccount:
    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_calls_create_account_with_credentials(self, mock_run_agent, MockSession, tmp_path):
        """signup_account creates an account via create_account_with_credentials."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert account is not None
        assert isinstance(account, PlatformAccount)
        assert account.account_id == "alice-devpost"
        # Credential should exist in vault
        cred = registry.get_credential(account.account_id)
        assert cred is not None

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_user_message_includes_credentials(self, mock_run_agent, MockSession, tmp_path):
        """User message contains email, username, password, and signup URL."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", email="alice@test.com"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        captured_prompt = {}

        async def fake_run_agent(prompt, options, session):
            captured_prompt["text"] = prompt
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        text = captured_prompt["text"]
        assert "alice@test.com" in text
        assert "alice" in text  # username
        assert "devpost.com" in text  # signup URL
        # Password should be present
        assert "Password:" in text

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_password_not_in_system_prompt(self, mock_run_agent, MockSession, tmp_path):
        """Password must appear in user_message only, not in the system prompt."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        captured_options = {}

        async def fake_run_agent(prompt, options, session):
            captured_options["system_prompt"] = options.system_prompt
            captured_options["user_message"] = prompt
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        # Get the actual password from vault
        cred = registry.get_credential(account.account_id)
        assert cred is not None
        # System prompt must NOT contain the password
        assert cred not in captured_options["system_prompt"]
        # User message MUST contain it
        assert cred in captured_options["user_message"]

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_escalates_when_email_missing(self, mock_run_agent, MockSession, tmp_path):
        """When member has no email, signup calls escalation_handler."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", email=None))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        escalation_called = {}

        async def mock_escalation(field_name, description, context):
            escalation_called["field"] = field_name
            return "alice@escalated.com"

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
            escalation_handler=mock_escalation,
        )

        assert account is not None
        assert escalation_called["field"] == "email"
        # Email should be saved back to member profile
        member = roster.load_member("alice")
        assert member.attributes["email"] == "alice@escalated.com"

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_session_saved_on_success(self, mock_run_agent, MockSession, tmp_path):
        """On success, account should have session_state_path set."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert account is not None
        assert account.session_state_path is not None
        assert account.session_state_path.endswith(".json")
        assert account.status == "active"

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_returns_correct_fields(self, mock_run_agent, MockSession, tmp_path):
        """Returned PlatformAccount has correct member_id, platform, username."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("bob", email="bob@test.com", username="bobdev"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="bob",
            platform="ethglobal",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert account is not None
        assert account.member_id == "bob"
        assert account.platform == Platform.ETHGLOBAL
        # ethglobal is an email-login platform, so username = email
        assert account.username == "bob@test.com"
        assert account.account_id == "bob-ethglobal"

    @pytest.mark.asyncio
    async def test_signup_returns_none_for_unknown_platform(self, tmp_path):
        """signup_account returns None for unknown platforms."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.signup import signup_account

        result = await signup_account(
            member_id="alice",
            platform="unknown_platform",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_signup_returns_none_for_unknown_member(self, tmp_path):
        """signup_account returns None if member not in roster."""
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        from bob.signup import signup_account

        result = await signup_account(
            member_id="ghost",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_returns_none_on_failure(self, mock_run_agent, MockSession, tmp_path):
        """signup_account returns None when agent reports failure."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": False, "error": "CAPTCHA blocked"})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        result = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert result is None


# ── OAuth tool tests ─────────────────────────────────────────────────


def _make_auth_registry(tmp_path) -> AuthStrategyRegistry:
    auth_dir = tmp_path / "auth_strategies"
    auth_dir.mkdir(exist_ok=True)
    return AuthStrategyRegistry(base_dir=auth_dir)


class TestSignupOAuth:
    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_system_prompt_includes_oauth_preference(self, mock_run_agent, MockSession, tmp_path):
        """System prompt includes OAuth preference instructions."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["system_prompt"] = options.system_prompt
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert "OAuth" in captured["system_prompt"]
        assert "check_github_session" in captured["system_prompt"]

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_check_github_session_returns_valid(self, mock_run_agent, MockSession, tmp_path):
        """check_github_session returns valid when GitHub session exists."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        # Create a GitHub account with valid session
        session_file = tmp_path / "gh_session.json"
        session_file.write_text("{}")
        gh_account = PlatformAccount(
            account_id="alice-github",
            platform=Platform.GITHUB,
            username="alicegh",
            credential_ref="alice-github-cred",
            member_id="alice",
            session_state_path=str(session_file),
            status="active",
        )
        registry.save_account(gh_account)

        check_result = {}

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            check_tool = _get_tool(server, "check_github_session")
            result = await check_tool.handler({})
            check_result["text"] = result["content"][0]["text"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert check_result["text"].startswith("valid:")

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_check_github_session_returns_no_session(self, mock_run_agent, MockSession, tmp_path):
        """check_github_session returns no_session when no GitHub account."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)

        check_result = {}

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            check_tool = _get_tool(server, "check_github_session")
            result = await check_tool.handler({})
            check_result["text"] = result["content"][0]["text"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
        )

        assert check_result["text"] == "no_session"

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_record_auth_success_writes_to_registry(self, mock_run_agent, MockSession, tmp_path):
        """record_auth_success persists strategy to AuthStrategyRegistry."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)
        auth_registry = _make_auth_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            record_tool = _get_tool(server, "record_auth_success")
            await record_tool.handler({"strategy_name": "github_oauth"})
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
            auth_registry=auth_registry,
        )

        assert "github_oauth" in auth_registry.get_strategies("devpost")

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_signup_accepts_auth_registry_param(self, mock_run_agent, MockSession, tmp_path):
        """signup_account accepts auth_registry without error."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)
        auth_registry = _make_auth_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        account = await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
            auth_registry=auth_registry,
        )

        assert account is not None

    @pytest.mark.asyncio
    @patch("bob.signup.AgentSession")
    @patch("bob.signup.run_agent", new_callable=AsyncMock)
    async def test_auth_prompt_section_injected_when_github_valid(
        self, mock_run_agent, MockSession, tmp_path
    ):
        """System prompt includes PREFERRED when github session valid + known strategy."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)
        field_registry = _make_field_registry(tmp_path)
        auth_registry = _make_auth_registry(tmp_path)

        # Record github_oauth as known for devpost
        auth_registry.record_success("devpost", "github_oauth", "signup")

        # Create valid GitHub session
        session_file = tmp_path / "gh_session.json"
        session_file.write_text("{}")
        gh_account = PlatformAccount(
            account_id="alice-github",
            platform=Platform.GITHUB,
            username="alicegh",
            credential_ref="alice-github-cred",
            member_id="alice",
            session_state_path=str(session_file),
            status="active",
        )
        registry.save_account(gh_account)

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["system_prompt"] = options.system_prompt
            server = options.mcp_servers["signup"]
            confirm = _get_tool(server, "confirm_signup")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.signup import signup_account

        await signup_account(
            member_id="alice",
            platform="devpost",
            roster=roster,
            registry=registry,
            field_registry=field_registry,
            auth_registry=auth_registry,
        )

        assert "PREFERRED" in captured["system_prompt"]
