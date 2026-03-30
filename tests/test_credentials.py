"""Tests for credential generation and account provisioning."""

from __future__ import annotations

import pytest

from bob.accounts.credentials import create_account_with_credentials, generate_password
from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


# ── generate_password tests ──────────────────────────────────────────


class TestGeneratePassword:
    def test_returns_string(self):
        pw = generate_password()
        assert isinstance(pw, str)

    def test_default_length_produces_nonempty(self):
        pw = generate_password()
        # token_urlsafe(24) produces a 32-char base64 string
        assert len(pw) > 0

    def test_custom_length(self):
        pw = generate_password(length=16)
        assert isinstance(pw, str)
        assert len(pw) > 0

    def test_different_each_call(self):
        passwords = {generate_password() for _ in range(10)}
        # Cryptographic randomness — all 10 should be unique
        assert len(passwords) == 10


# ── create_account_with_credentials tests ────────────────────────────


class TestCreateAccountWithCredentials:
    def test_creates_account(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        assert isinstance(account, PlatformAccount)
        assert account.username == "alice123"

    def test_account_id_format(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        assert account.account_id == "alice-devpost"

    def test_credential_ref_format(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        assert account.credential_ref == "alice-devpost-password"

    def test_credential_stored_in_vault(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        # Credential should be retrievable from vault
        stored = registry._vault.get_credential(account.credential_ref)
        assert stored is not None
        assert len(stored) > 0

    def test_account_saved_to_registry(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        loaded = registry.get_account(account.account_id)
        assert loaded is not None
        assert loaded.account_id == account.account_id
        assert loaded.username == "alice123"

    def test_platform_enum_set(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="bob",
            platform="ethglobal",
            username="bob_eth",
            registry=registry,
        )
        assert account.platform == Platform.ETHGLOBAL

    def test_member_id_set(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="bob",
            platform="github",
            username="bobgit",
            registry=registry,
        )
        assert account.member_id == "bob"

    def test_fingerprint_config_is_dict(self, tmp_path):
        registry = _make_registry(tmp_path)
        account = create_account_with_credentials(
            member_id="alice",
            platform="devpost",
            username="alice123",
            registry=registry,
        )
        # stealth-browser mock is installed, but BrowserConfig.get_config()
        # may return a MagicMock. Either way, fingerprint_config should be a dict.
        assert isinstance(account.fingerprint_config, dict)
