"""Tests for the automated login agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.auth_strategy import AuthStrategyRegistry
from bob.telemetry import AgentResult


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_account(
    registry: AccountRegistry,
    account_id: str = "alice-devpost",
    platform: Platform = Platform.DEVPOST,
    member_id: str = "alice",
    username: str = "alice123",
    password: str = "s3cret-passw0rd",
) -> PlatformAccount:
    account = PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=username,
        credential_ref=f"{account_id}-cred",
        member_id=member_id,
    )
    registry.save_account(account)
    registry._vault.store_credential(account.credential_ref, password)
    return account


def _agent_result(**kw):
    defaults = dict(input_tokens=100, output_tokens=50, total_turns=1, success=True)
    defaults.update(kw)
    return AgentResult(**defaults)


def _get_tool(server, name):
    return next(t for t in server["tools"] if t.name == name)


# ── Auto-login tests ────────────────────────────────────────────────


class TestAutoLogin:
    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_credential_fetched_from_vault(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """auto_login fetches the credential from vault and includes it in user_message."""
        registry = _make_registry(tmp_path)
        _make_account(registry, password="my-secret-pw")

        captured_prompt = {}

        async def fake_run_agent(prompt, options, session):
            captured_prompt["text"] = prompt
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="alice-devpost",
            registry=registry,
        )

        assert result is True
        assert "my-secret-pw" in captured_prompt["text"]

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_password_in_user_message_not_system_prompt(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """Password appears in user_message, not in system_prompt."""
        registry = _make_registry(tmp_path)
        _make_account(registry, password="vault-secret-123")

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["user_message"] = prompt
            captured["system_prompt"] = options.system_prompt
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(account_id="alice-devpost", registry=registry)

        assert "vault-secret-123" in captured["user_message"]
        assert "vault-secret-123" not in captured["system_prompt"]

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_session_saved_on_success(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """On success, account session_state_path and last_login are updated."""
        registry = _make_registry(tmp_path)
        _make_account(registry)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="alice-devpost",
            registry=registry,
        )

        assert result is True
        updated = registry.get_account("alice-devpost")
        assert updated.session_state_path is not None
        assert updated.session_state_path.endswith(".json")
        assert updated.last_login is not None
        assert updated.status == "active"

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_2fa_escalation(self, mock_run_agent, MockSession, mock_fallback, tmp_path):
        """When agent calls escalate for 2FA, the escalation_handler is invoked."""
        registry = _make_registry(tmp_path)
        _make_account(registry)

        escalation_called = {}

        async def mock_escalation(field_name, description, context):
            escalation_called["field"] = field_name
            return "123456"

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["autologin"]
            escalate = _get_tool(server, "escalate")
            result = await escalate.handler({
                "field_name": "2fa_code",
                "description": "Enter 2FA code",
                "context": "GitHub login requires TOTP",
            })
            assert result["content"][0]["text"] == "123456"

            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="alice-devpost",
            registry=registry,
            escalation_handler=mock_escalation,
        )

        assert result is True
        assert escalation_called["field"] == "2fa_code"

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_fallback_to_interactive_on_failure(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """When agent reports failure, auto_login falls back to interactive login."""
        registry = _make_registry(tmp_path)
        _make_account(registry)
        mock_fallback.return_value = True

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": False, "error": "CAPTCHA blocked"})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="alice-devpost",
            registry=registry,
        )

        assert result is True
        mock_fallback.assert_called_once_with("alice-devpost", registry, headless=False)

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_returns_false_for_missing_account(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """auto_login returns False if account_id not found."""
        registry = _make_registry(tmp_path)

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="ghost-devpost",
            registry=registry,
        )

        assert result is False
        mock_run_agent.assert_not_called()

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_returns_false_for_missing_credential(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """auto_login returns False if credential not in vault."""
        registry = _make_registry(tmp_path)
        # Save account but DON'T store credential
        account = PlatformAccount(
            account_id="alice-devpost",
            platform=Platform.DEVPOST,
            username="alice123",
            credential_ref="alice-devpost-cred",
            member_id="alice",
        )
        registry.save_account(account)

        from bob.autologin import auto_login

        result = await auto_login(
            account_id="alice-devpost",
            registry=registry,
        )

        assert result is False
        mock_run_agent.assert_not_called()


# ── OAuth tool tests ─────────────────────────────────────────────────


def _make_auth_registry(tmp_path) -> AuthStrategyRegistry:
    auth_dir = tmp_path / "auth_strategies"
    auth_dir.mkdir(exist_ok=True)
    return AuthStrategyRegistry(base_dir=auth_dir)


class TestAutoLoginOAuth:
    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_system_prompt_includes_oauth_preference(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """Login system prompt includes OAuth preference instructions."""
        registry = _make_registry(tmp_path)
        _make_account(registry)

        captured = {}

        async def fake_run_agent(prompt, options, session):
            captured["system_prompt"] = options.system_prompt
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(account_id="alice-devpost", registry=registry)

        assert "OAuth" in captured["system_prompt"]
        assert "check_github_session" in captured["system_prompt"]

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_check_github_session_tool_present(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """check_github_session tool is in the autologin MCP server."""
        registry = _make_registry(tmp_path)
        _make_account(registry)

        tool_found = {}

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["autologin"]
            tool_names = [t.name for t in server["tools"]]
            tool_found["check_github_session"] = "check_github_session" in tool_names
            tool_found["record_auth_success"] = "record_auth_success" in tool_names
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(account_id="alice-devpost", registry=registry)

        assert tool_found["check_github_session"] is True
        assert tool_found["record_auth_success"] is True

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_record_auth_success_writes_to_registry(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """record_auth_success persists strategy for login."""
        registry = _make_registry(tmp_path)
        _make_account(registry)
        auth_registry = _make_auth_registry(tmp_path)

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["autologin"]
            record_tool = _get_tool(server, "record_auth_success")
            await record_tool.handler({"strategy_name": "github_oauth"})
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(
            account_id="alice-devpost",
            registry=registry,
            auth_registry=auth_registry,
        )

        assert "github_oauth" in auth_registry.get_strategies("devpost")

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_check_github_session_returns_valid_for_member(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """check_github_session finds valid session for account's member."""
        registry = _make_registry(tmp_path)
        _make_account(registry)

        # Create a GitHub account for alice with valid session
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
            server = options.mcp_servers["autologin"]
            check_tool = _get_tool(server, "check_github_session")
            result = await check_tool.handler({})
            check_result["text"] = result["content"][0]["text"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(account_id="alice-devpost", registry=registry)

        assert check_result["text"].startswith("valid:")

    @pytest.mark.asyncio
    @patch("bob.autologin.login_account", new_callable=AsyncMock)
    @patch("bob.autologin.AgentSession")
    @patch("bob.autologin.run_agent", new_callable=AsyncMock)
    async def test_auth_prompt_section_injected(
        self, mock_run_agent, MockSession, mock_fallback, tmp_path
    ):
        """System prompt includes PREFERRED when auth_registry has info."""
        registry = _make_registry(tmp_path)
        _make_account(registry)
        auth_registry = _make_auth_registry(tmp_path)

        # Record github_oauth as known for devpost
        auth_registry.record_success("devpost", "github_oauth", "login")

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
            server = options.mcp_servers["autologin"]
            confirm = _get_tool(server, "confirm_login")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        from bob.autologin import auto_login

        await auto_login(
            account_id="alice-devpost",
            registry=registry,
            auth_registry=auth_registry,
        )

        assert "PREFERRED" in captured["system_prompt"]
