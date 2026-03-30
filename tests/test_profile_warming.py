"""Tests for the GitHub profile warming agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.roster.models import MemberProfile, Skill
from bob.roster.store import RosterStore
from bob.telemetry import AgentResult


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


def _make_member(member_id="alice", **extra_attrs):
    attrs = {"email": "alice@example.com"}
    attrs.update(extra_attrs)
    return MemberProfile(
        member_id=member_id,
        display_name=member_id.capitalize(),
        skills=[
            Skill(name="Python", domain="backend", depth=4),
            Skill(name="React", domain="frontend", depth=3),
        ],
        interests=["web3", "AI"],
        attributes=attrs,
    )


def _make_github_account(
    registry: AccountRegistry,
    member_id: str = "alice",
    session_state_path: str | None = None,
) -> PlatformAccount:
    account = PlatformAccount(
        account_id=f"{member_id}-github",
        platform=Platform.GITHUB,
        username=f"{member_id}gh",
        credential_ref=f"{member_id}-github-cred",
        member_id=member_id,
        session_state_path=session_state_path,
    )
    registry.save_account(account)
    return account


def _agent_result(**kw):
    defaults = dict(input_tokens=100, output_tokens=50, total_turns=1, success=True)
    defaults.update(kw)
    return AgentResult(**defaults)


def _get_tool(server, name):
    return next(t for t in server["tools"] if t.name == name)


# ── Profile warming tests ────────────────────────────────────────────


class TestWarmGitHubProfile:
    @pytest.mark.asyncio
    async def test_returns_false_for_missing_account(self, tmp_path):
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)

        from bob.profile_warming import warm_github_profile

        result = await warm_github_profile(
            account_id="ghost-github",
            roster=roster,
            registry=registry,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_non_github_account(self, tmp_path):
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)

        # Create a devpost account
        account = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="ref",
            member_id="alice",
        )
        registry.save_account(account)

        from bob.profile_warming import warm_github_profile

        result = await warm_github_profile(
            account_id="alice-devpost",
            roster=roster,
            registry=registry,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_missing_session(self, tmp_path):
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        _make_github_account(registry, session_state_path=str(tmp_path / "gone.json"))

        from bob.profile_warming import warm_github_profile

        result = await warm_github_profile(
            account_id="alice-github",
            roster=roster,
            registry=registry,
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("bob.profile_warming.compose_persona")
    @patch("bob.profile_warming.AgentSession")
    @patch("bob.profile_warming.run_agent", new_callable=AsyncMock)
    async def test_warming_success(self, mock_run_agent, MockSession, mock_compose, tmp_path):
        """Successful warming returns True and navigates to settings/profile."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))

        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(registry, session_state_path=str(session_file))

        # Mock persona
        mock_persona = MagicMock()
        mock_persona.bio_short = "Building cool things"
        mock_compose.return_value = mock_persona

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["user_message"] = prompt
            captured["system_prompt"] = options.system_prompt
            server = options.mcp_servers["warming"]
            confirm = _get_tool(server, "confirm_warming")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.profile_warming import warm_github_profile

        result = await warm_github_profile(
            account_id="alice-github",
            roster=roster,
            registry=registry,
        )

        assert result is True
        assert "github.com/settings/profile" in captured["system_prompt"]

    @pytest.mark.asyncio
    @patch("bob.profile_warming.compose_persona")
    @patch("bob.profile_warming.AgentSession")
    @patch("bob.profile_warming.run_agent", new_callable=AsyncMock)
    async def test_bio_does_not_contain_bot_or_ai_agent(
        self, mock_run_agent, MockSession, mock_compose, tmp_path
    ):
        """System prompt forbids AI/bot mentions in profile."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))

        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(registry, session_state_path=str(session_file))

        mock_persona = MagicMock()
        mock_persona.bio_short = "Building cool things"
        mock_compose.return_value = mock_persona

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["system_prompt"] = options.system_prompt
            captured["user_message"] = prompt
            server = options.mcp_servers["warming"]
            confirm = _get_tool(server, "confirm_warming")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.profile_warming import warm_github_profile

        await warm_github_profile(
            account_id="alice-github",
            roster=roster,
            registry=registry,
        )

        # System prompt must warn against AI/bot mentions
        assert "AI" in captured["system_prompt"] or "bot" in captured["system_prompt"]
        assert "Do NOT mention" in captured["system_prompt"] or "IMPORTANT" in captured["system_prompt"]

        # User message (bio) should not contain problematic words
        bio_line = [l for l in captured["user_message"].split("\n") if "Bio:" in l]
        if bio_line:
            bio_text = bio_line[0].lower()
            assert "ai agent" not in bio_text
            assert "bot" not in bio_text

    @pytest.mark.asyncio
    @patch("bob.profile_warming.compose_persona")
    @patch("bob.profile_warming.AgentSession")
    @patch("bob.profile_warming.run_agent", new_callable=AsyncMock)
    async def test_session_saved_on_success(self, mock_run_agent, MockSession, mock_compose, tmp_path):
        """User message includes session save path."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))

        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(registry, session_state_path=str(session_file))

        mock_persona = MagicMock()
        mock_persona.bio_short = "Building cool things"
        mock_compose.return_value = mock_persona

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["user_message"] = prompt
            server = options.mcp_servers["warming"]
            confirm = _get_tool(server, "confirm_warming")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.profile_warming import warm_github_profile

        await warm_github_profile(
            account_id="alice-github",
            roster=roster,
            registry=registry,
        )

        assert "Session save path:" in captured["user_message"]

    @pytest.mark.asyncio
    @patch("bob.profile_warming.compose_persona")
    @patch("bob.profile_warming.AgentSession")
    @patch("bob.profile_warming.run_agent", new_callable=AsyncMock)
    async def test_warming_failure_returns_false(
        self, mock_run_agent, MockSession, mock_compose, tmp_path
    ):
        """Agent reporting failure -> warm_github_profile returns False."""
        registry = _make_registry(tmp_path)
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))

        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(registry, session_state_path=str(session_file))

        mock_persona = MagicMock()
        mock_persona.bio_short = "Building cool things"
        mock_compose.return_value = mock_persona

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["warming"]
            confirm = _get_tool(server, "confirm_warming")
            await confirm.handler({"success": False, "error": "page not found"})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.profile_warming import warm_github_profile

        result = await warm_github_profile(
            account_id="alice-github",
            roster=roster,
            registry=registry,
        )

        assert result is False
