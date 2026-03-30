"""Tests for AuthStrategyRegistry, PlatformAuthInfo, and build_auth_prompt_section."""

from __future__ import annotations

import pytest

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.auth_strategy import (
    AuthStrategyRegistry,
    PlatformAuthInfo,
    build_auth_prompt_section,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_github_account(
    registry: AccountRegistry,
    member_id: str = "alice",
    session_state_path: str | None = None,
    status: str = "active",
) -> PlatformAccount:
    account = PlatformAccount(
        account_id=f"{member_id}-github",
        platform=Platform.GITHUB,
        username=f"{member_id}gh",
        credential_ref=f"{member_id}-github-cred",
        member_id=member_id,
        session_state_path=session_state_path,
        status=status,
    )
    registry.save_account(account)
    return account


# ── AuthStrategyRegistry ─────────────────────────────────────────────


class TestAuthStrategyRegistry:
    def test_empty_strategies_for_unknown_platform(self, tmp_path):
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        assert reg.get_strategies("unknown_platform") == []

    def test_record_success_persists(self, tmp_path):
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("devpost", "github_oauth", "signup")
        strategies = reg.get_strategies("devpost")
        assert "github_oauth" in strategies

    def test_record_multiple_strategies(self, tmp_path):
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("devpost", "github_oauth", "signup")
        reg.record_success("devpost", "email_password", "signup")
        strategies = reg.get_strategies("devpost")
        assert len(strategies) == 2

    def test_oauth_first_ordering(self, tmp_path):
        """OAuth strategies should come before email_password."""
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("devpost", "email_password", "signup")
        reg.record_success("devpost", "github_oauth", "signup")
        strategies = reg.get_strategies("devpost")
        assert strategies.index("github_oauth") < strategies.index("email_password")

    def test_record_success_updates_existing(self, tmp_path):
        """Recording the same strategy+action updates last_success, not duplicate."""
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("devpost", "github_oauth", "signup")
        reg.record_success("devpost", "github_oauth", "signup")
        strategies = reg.get_strategies("devpost")
        assert strategies.count("github_oauth") == 1

    def test_different_actions_are_separate_records(self, tmp_path):
        """Same strategy with different actions (signup vs login) are separate."""
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("devpost", "github_oauth", "signup")
        reg.record_success("devpost", "github_oauth", "login")
        # get_strategies deduplicates by name
        strategies = reg.get_strategies("devpost")
        assert strategies.count("github_oauth") == 1

    def test_safe_filename_for_platform_names(self, tmp_path):
        """Platforms with special characters are sanitized."""
        reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        reg.record_success("my/platform", "github_oauth", "signup")
        strategies = reg.get_strategies("my/platform")
        assert "github_oauth" in strategies

    def test_yaml_persistence_across_instances(self, tmp_path):
        """Registry data survives creating a new instance."""
        base = tmp_path / "auth"
        reg1 = AuthStrategyRegistry(base_dir=base)
        reg1.record_success("devpost", "github_oauth", "signup")

        reg2 = AuthStrategyRegistry(base_dir=base)
        assert "github_oauth" in reg2.get_strategies("devpost")


# ── PlatformAuthInfo via get_auth_info ───────────────────────────────


class TestGetAuthInfo:
    def test_no_github_account(self, tmp_path):
        """Member with no GitHub account -> github_session_valid=False."""
        auth_reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        acct_reg = _make_registry(tmp_path)
        info = auth_reg.get_auth_info("devpost", "alice", acct_reg)
        assert info.github_session_valid is False
        assert info.google_session_valid is False

    def test_github_account_no_session_file(self, tmp_path):
        """GitHub account exists but session file missing -> invalid."""
        auth_reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        acct_reg = _make_registry(tmp_path)
        _make_github_account(
            acct_reg,
            session_state_path=str(tmp_path / "nonexistent.json"),
        )
        info = auth_reg.get_auth_info("devpost", "alice", acct_reg)
        assert info.github_session_valid is False

    def test_github_account_with_valid_session(self, tmp_path):
        """GitHub account with existing session file -> valid."""
        auth_reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        acct_reg = _make_registry(tmp_path)
        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(acct_reg, session_state_path=str(session_file))
        info = auth_reg.get_auth_info("devpost", "alice", acct_reg)
        assert info.github_session_valid is True

    def test_github_account_suspended(self, tmp_path):
        """Suspended GitHub account -> invalid even with session file."""
        auth_reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        acct_reg = _make_registry(tmp_path)
        session_file = tmp_path / "session.json"
        session_file.write_text("{}")
        _make_github_account(
            acct_reg,
            session_state_path=str(session_file),
            status="suspended",
        )
        info = auth_reg.get_auth_info("devpost", "alice", acct_reg)
        assert info.github_session_valid is False

    def test_known_strategies_populated(self, tmp_path):
        """Known strategies from registry appear in auth info."""
        auth_reg = AuthStrategyRegistry(base_dir=tmp_path / "auth")
        auth_reg.record_success("devpost", "github_oauth", "signup")
        acct_reg = _make_registry(tmp_path)
        info = auth_reg.get_auth_info("devpost", "alice", acct_reg)
        assert "github_oauth" in info.known_strategies


# ── build_auth_prompt_section ────────────────────────────────────────


class TestBuildAuthPromptSection:
    def test_empty_when_no_info(self):
        """No strategies, no sessions -> empty string."""
        info = PlatformAuthInfo(
            platform="devpost",
            known_strategies=[],
            github_session_valid=False,
            google_session_valid=False,
        )
        assert build_auth_prompt_section(info) == ""

    def test_preferred_when_github_valid_and_known(self):
        """PREFERRED text when GitHub session valid + known strategy."""
        info = PlatformAuthInfo(
            platform="devpost",
            known_strategies=["github_oauth"],
            github_session_valid=True,
            google_session_valid=False,
        )
        section = build_auth_prompt_section(info)
        assert "PREFERRED" in section
        assert "GitHub OAuth" in section

    def test_suggest_github_when_valid_but_not_known(self):
        """Suggests GitHub when session valid but not a known strategy."""
        info = PlatformAuthInfo(
            platform="devpost",
            known_strategies=["email_password"],
            github_session_valid=True,
            google_session_valid=False,
        )
        section = build_auth_prompt_section(info)
        assert "GitHub session" in section
        assert "PREFERRED" not in section

    def test_includes_known_strategies_list(self):
        """Lists known strategies when present."""
        info = PlatformAuthInfo(
            platform="devpost",
            known_strategies=["github_oauth", "email_password"],
            github_session_valid=False,
            google_session_valid=False,
        )
        section = build_auth_prompt_section(info)
        assert "github_oauth" in section
        assert "email_password" in section

    def test_google_preferred_when_valid_and_known(self):
        """PREFERRED text for Google OAuth when session valid + known."""
        info = PlatformAuthInfo(
            platform="devpost",
            known_strategies=["google_oauth"],
            github_session_valid=False,
            google_session_valid=True,
        )
        section = build_auth_prompt_section(info)
        assert "PREFERRED" in section
        assert "Google OAuth" in section
