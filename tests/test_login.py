"""Tests for the interactive login flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.login import _LOGIN_URLS, login_account


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_account(
    account_id: str = "acc-1",
    platform: Platform = Platform.DEVPOST,
    member_id: str = "alice",
) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=f"user-{member_id}",
        credential_ref=f"vault://{account_id}",
        member_id=member_id,
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestLoginAccount:
    @pytest.mark.asyncio
    async def test_missing_account_returns_false(self, tmp_path):
        registry = _make_registry(tmp_path)
        result = await login_account("nonexistent", registry)
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_login_saves_session(self, tmp_path):
        """Full login flow: browser opens, user presses Enter, state saved."""
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)

        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={"cookies": []})
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_close = AsyncMock()

        with patch("bob.login.create_stealth_browser", new=AsyncMock(return_value=mock_browser)), \
             patch("bob.login.create_stealth_context", new=AsyncMock(return_value=mock_context)), \
             patch("bob.login.new_stealth_page", new=AsyncMock(return_value=mock_page)), \
             patch("bob.login.stealth_goto", new=AsyncMock()), \
             patch("bob.login.close_stealth_browser", new=mock_close), \
             patch("bob.login.input", return_value=""), \
             patch("builtins.print"):
            result = await login_account("acc-1", registry)

        assert result is True

        updated = registry.get_account("acc-1")
        assert updated is not None
        assert updated.session_state_path is not None
        assert "acc-1.json" in updated.session_state_path
        assert updated.last_login is not None
        assert updated.status == "active"

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_login_navigates_to_correct_url(self, tmp_path):
        """Verifies the browser navigates to the platform-specific login URL."""
        registry = _make_registry(tmp_path)
        account = _make_account(platform=Platform.GITHUB)
        registry.save_account(account)

        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={})
        mock_goto = AsyncMock()

        with patch("bob.login.create_stealth_browser", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.create_stealth_context", new=AsyncMock(return_value=mock_context)), \
             patch("bob.login.new_stealth_page", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.stealth_goto", new=mock_goto), \
             patch("bob.login.close_stealth_browser", new=AsyncMock()), \
             patch("bob.login.input", return_value=""), \
             patch("builtins.print"):
            await login_account("acc-1", registry)

        mock_goto.assert_awaited_once()
        call_args = mock_goto.call_args
        assert call_args[0][1] == _LOGIN_URLS["github"]

    @pytest.mark.asyncio
    async def test_login_cancelled_returns_false(self, tmp_path):
        """User pressing Ctrl-C during login returns False."""
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)

        mock_close = AsyncMock()

        with patch("bob.login.create_stealth_browser", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.create_stealth_context", new=AsyncMock(return_value=AsyncMock())), \
             patch("bob.login.new_stealth_page", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.stealth_goto", new=AsyncMock()), \
             patch("bob.login.close_stealth_browser", new=mock_close), \
             patch("bob.login.input", side_effect=KeyboardInterrupt), \
             patch("builtins.print"):
            result = await login_account("acc-1", registry)

        assert result is False
        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_credential_still_succeeds(self, tmp_path):
        """When no credential stored, login still proceeds (user types manually)."""
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)

        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={})

        with patch("bob.login.create_stealth_browser", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.create_stealth_context", new=AsyncMock(return_value=mock_context)), \
             patch("bob.login.new_stealth_page", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.stealth_goto", new=AsyncMock()), \
             patch("bob.login.close_stealth_browser", new=AsyncMock()), \
             patch("bob.login.input", return_value=""), \
             patch("builtins.print"):
            result = await login_account("acc-1", registry)

        assert result is True


class TestLoginSessionPathSafety:
    @pytest.mark.asyncio
    async def test_session_path_sanitizes_traversal(self, tmp_path):
        """account_id with path traversal chars is sanitized in session filename."""
        registry = _make_registry(tmp_path)
        account = _make_account(account_id="../../etc/passwd", platform=Platform.DEVPOST)
        registry.save_account(account)

        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={})

        with patch("bob.login.create_stealth_browser", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.create_stealth_context", new=AsyncMock(return_value=mock_context)), \
             patch("bob.login.new_stealth_page", new=AsyncMock(return_value=MagicMock())), \
             patch("bob.login.stealth_goto", new=AsyncMock()), \
             patch("bob.login.close_stealth_browser", new=AsyncMock()), \
             patch("bob.login.input", return_value=""), \
             patch("builtins.print"):
            result = await login_account("../../etc/passwd", registry)

        assert result is True
        updated = registry.get_account("../../etc/passwd")
        assert updated is not None
        # Session path should NOT contain traversal
        assert ".." not in updated.session_state_path
        assert "/" not in updated.session_state_path.split("/")[-1].replace(".json", "")


class TestLoginUrls:
    def test_all_platforms_have_urls(self):
        for platform in ["devpost", "ethglobal", "luma", "devfolio", "github"]:
            assert platform in _LOGIN_URLS
