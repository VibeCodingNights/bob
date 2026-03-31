"""Tests for AuthConfig, AuthManager, and auth_env wiring."""

from __future__ import annotations

import pytest
import yaml

from bob.accounts.vault import FileVault
from bob.auth import AuthConfig, AuthManager, AuthMethod


# ── Helpers ──────────────────────────────────────────────────────────


def _make_manager(tmp_path) -> AuthManager:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    return AuthManager(vault=vault, base_dir=auth_dir)


# ── AuthConfig tests ────────────────────────────────────────────────


class TestAuthConfig:
    def test_create_api_key_config(self):
        config = AuthConfig(name="work", method=AuthMethod.API_KEY, credential_ref="ref-1")
        assert config.name == "work"
        assert config.method == AuthMethod.API_KEY
        assert config.credential_ref == "ref-1"
        assert config.email is None

    def test_create_oauth_config(self):
        config = AuthConfig(name="personal", method=AuthMethod.OAUTH, email="me@example.com")
        assert config.name == "personal"
        assert config.method == AuthMethod.OAUTH
        assert config.email == "me@example.com"
        assert config.credential_ref is None

    def test_enum_values(self):
        assert AuthMethod.API_KEY.value == "api_key"
        assert AuthMethod.OAUTH.value == "oauth"


# ── AuthManager: add_api_key ────────────────────────────────────────


class TestAddApiKey:
    def test_stores_in_vault_and_persists(self, tmp_path):
        mgr = _make_manager(tmp_path)
        config = mgr.add_api_key("work", "sk-ant-test-key-123")

        assert config.name == "work"
        assert config.method == AuthMethod.API_KEY
        assert config.credential_ref == "claude-auth-work"

        # Verify vault has the key
        vault_dir = tmp_path / "vault"
        vault = FileVault(base_dir=vault_dir)
        assert vault.get_credential("claude-auth-work") == "sk-ant-test-key-123"

        # Verify YAML was saved
        config_path = tmp_path / "auth" / "configs.yaml"
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert len(data["configs"]) == 1
        assert data["configs"][0]["name"] == "work"
        assert data["configs"][0]["method"] == "api_key"

    def test_first_added_becomes_active(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("first", "key-1")
        active = mgr.get_active()
        assert active is not None
        assert active.name == "first"

    def test_second_added_does_not_change_active(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("first", "key-1")
        mgr.add_api_key("second", "key-2")
        active = mgr.get_active()
        assert active is not None
        assert active.name == "first"


# ── AuthManager: add_oauth ──────────────────────────────────────────


class TestAddOAuth:
    def test_stores_config_no_vault_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        config = mgr.add_oauth("personal", email="me@example.com")

        assert config.name == "personal"
        assert config.method == AuthMethod.OAUTH
        assert config.email == "me@example.com"
        assert config.credential_ref is None

    def test_first_oauth_becomes_active(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_oauth("personal")
        assert mgr.get_active().name == "personal"


# ── AuthManager: list_configs ───────────────────────────────────────


class TestListConfigs:
    def test_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.list_configs() == []

    def test_multiple(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("work", "key-1")
        mgr.add_oauth("personal", email="a@b.com")
        configs = mgr.list_configs()
        assert len(configs) == 2
        names = {c.name for c in configs}
        assert names == {"work", "personal"}


# ── AuthManager: get_active / set_active ────────────────────────────


class TestActiveConfig:
    def test_get_active_none_when_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_active() is None

    def test_set_active(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("work", "key-1")
        mgr.add_oauth("personal")
        mgr.set_active("personal")
        assert mgr.get_active().name == "personal"

    def test_set_active_unknown_raises(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(KeyError, match="nonexistent"):
            mgr.set_active("nonexistent")


# ── AuthManager: get_env ────────────────────────────────────────────


class TestGetEnv:
    def test_api_key_returns_anthropic_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("work", "sk-ant-secret")
        env = mgr.get_env()
        assert env == {"ANTHROPIC_API_KEY": "sk-ant-secret"}

    def test_oauth_returns_empty_dict(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_oauth("personal")
        env = mgr.get_env()
        assert env == {}

    def test_get_env_by_name(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("work", "sk-work")
        mgr.add_api_key("personal", "sk-personal")
        mgr.set_active("work")
        # Get specific config's env, not active
        env = mgr.get_env("personal")
        assert env == {"ANTHROPIC_API_KEY": "sk-personal"}

    def test_get_env_empty_when_no_configs(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_env() == {}


# ── AuthManager: remove ─────────────────────────────────────────────


class TestRemove:
    def test_remove_deletes_config_and_vault(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("work", "sk-ant-remove-me")
        assert mgr.remove("work") is True
        assert mgr.list_configs() == []

        # Vault cred should also be gone
        vault = FileVault(base_dir=tmp_path / "vault")
        assert vault.get_credential("claude-auth-work") is None

    def test_remove_nonexistent_returns_false(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.remove("ghost") is False

    def test_remove_active_reassigns(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("first", "key-1")
        mgr.add_api_key("second", "key-2")
        mgr.set_active("first")
        mgr.remove("first")
        active = mgr.get_active()
        assert active is not None
        assert active.name == "second"

    def test_remove_last_sets_active_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_api_key("only", "key-1")
        mgr.remove("only")
        assert mgr.get_active() is None


# ── YAML roundtrip ──────────────────────────────────────────────────


class TestYamlRoundtrip:
    def test_persists_across_instances(self, tmp_path):
        vault_dir = tmp_path / "vault"
        vault_dir.mkdir(exist_ok=True)
        auth_dir = tmp_path / "auth"
        auth_dir.mkdir(exist_ok=True)

        vault = FileVault(base_dir=vault_dir)

        # Instance 1: add configs
        mgr1 = AuthManager(vault=vault, base_dir=auth_dir)
        mgr1.add_api_key("work", "sk-ant-persist")
        mgr1.add_oauth("personal", email="me@test.com")
        mgr1.set_active("personal")

        # Instance 2: reload from disk
        mgr2 = AuthManager(vault=vault, base_dir=auth_dir)
        configs = mgr2.list_configs()
        assert len(configs) == 2

        active = mgr2.get_active()
        assert active is not None
        assert active.name == "personal"
        assert active.method == AuthMethod.OAUTH
        assert active.email == "me@test.com"

        env = mgr2.get_env("work")
        assert env == {"ANTHROPIC_API_KEY": "sk-ant-persist"}


# ── run_agent auth_env wiring ───────────────────────────────────────


class TestRunAgentAuthEnv:
    @pytest.mark.asyncio
    async def test_auth_env_merged_into_options(self):
        """Verify run_agent merges auth_env into options.env."""
        from unittest.mock import patch

        from bob.telemetry import AgentSession, run_agent

        session = AgentSession("test-auth", log_dir=None)

        class FakeOptions:
            pass

        options = FakeOptions()

        async def fake_query(**kwargs):
            return
            yield  # make it an async generator

        with patch.dict("sys.modules", {}):
            # Patch at the SDK module level since run_agent imports query inside
            import sys
            sdk = sys.modules["claude_agent_sdk"]
            original_query = sdk.query
            sdk.query = fake_query
            try:
                result = await run_agent(
                    "test prompt",
                    options,
                    session,
                    auth_env={"ANTHROPIC_API_KEY": "sk-merged"},
                )
            finally:
                sdk.query = original_query

        assert getattr(options, "env", None) is not None
        assert options.env["ANTHROPIC_API_KEY"] == "sk-merged"
        session.close()

    @pytest.mark.asyncio
    async def test_auth_env_none_leaves_options_unchanged(self):
        """Verify run_agent with auth_env=None doesn't touch options.env."""
        from unittest.mock import patch

        from bob.telemetry import AgentSession, run_agent

        session = AgentSession("test-noauth", log_dir=None)

        class FakeOptions:
            pass

        options = FakeOptions()

        async def fake_query(**kwargs):
            return
            yield

        import sys
        sdk = sys.modules["claude_agent_sdk"]
        original_query = sdk.query
        sdk.query = fake_query
        try:
            result = await run_agent("test prompt", options, session)
        finally:
            sdk.query = original_query

        assert not hasattr(options, "env")
        session.close()


# ── Redaction covers ANTHROPIC_API_KEY ──────────────────────────────


class TestRedaction:
    def test_api_key_redacted(self):
        from bob.telemetry import _redact

        data = {"ANTHROPIC_API_KEY": "sk-ant-secret-123", "name": "test"}
        redacted = _redact(data)
        assert redacted["ANTHROPIC_API_KEY"] == "***"
        assert redacted["name"] == "test"
