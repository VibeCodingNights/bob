"""Tests for account models, FileVault, vault creation, and AccountRegistry."""

import os
from unittest.mock import patch

import yaml

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault, create_vault


# ── Model tests ───────────────────────────────────────────────────────


class TestPlatform:
    def test_enum_values(self):
        assert Platform.DEVPOST == "devpost"
        assert Platform.ETHGLOBAL == "ethglobal"
        assert Platform.GITHUB == "github"
        assert Platform.LUMA == "luma"
        assert Platform.DEVFOLIO == "devfolio"


class TestPlatformAccount:
    def test_creation_with_defaults(self):
        a = PlatformAccount(
            account_id="acc-1",
            platform=Platform.DEVPOST,
            username="alice",
            credential_ref="vault://acc-1",
            member_id="alice",
        )
        assert a.account_id == "acc-1"
        assert a.platform == Platform.DEVPOST
        assert a.fingerprint_config == {}
        assert a.session_state_path is None
        assert a.last_login is None
        assert a.status == "active"

    def test_creation_with_all_fields(self):
        a = PlatformAccount(
            account_id="acc-2",
            platform=Platform.ETHGLOBAL,
            username="bob",
            credential_ref="vault://acc-2",
            member_id="bob",
            fingerprint_config={"viewport": "1920x1080"},
            session_state_path="/tmp/session.json",
            last_login="2026-03-20T10:00:00Z",
            status="needs-reauth",
        )
        assert a.platform == Platform.ETHGLOBAL
        assert a.fingerprint_config == {"viewport": "1920x1080"}
        assert a.session_state_path == "/tmp/session.json"
        assert a.last_login == "2026-03-20T10:00:00Z"
        assert a.status == "needs-reauth"


# ── FileVault tests ───────────────────────────────────────────────────


class TestFileVault:
    def test_store_get_roundtrip(self, tmp_path):
        vault = FileVault(base_dir=tmp_path)
        vault.store_credential("my-key", "s3cret")
        assert vault.get_credential("my-key") == "s3cret"

    def test_get_nonexistent_returns_none(self, tmp_path):
        vault = FileVault(base_dir=tmp_path)
        assert vault.get_credential("missing") is None

    def test_delete_roundtrip(self, tmp_path):
        vault = FileVault(base_dir=tmp_path)
        vault.store_credential("temp", "value")
        vault.delete_credential("temp")
        assert vault.get_credential("temp") is None

    def test_delete_nonexistent_is_noop(self, tmp_path):
        vault = FileVault(base_dir=tmp_path)
        vault.delete_credential("nope")  # should not raise

    def test_file_permissions_are_0600(self, tmp_path):
        vault = FileVault(base_dir=tmp_path)
        vault.store_credential("perm-test", "secret")
        p = tmp_path / "perm-test"
        mode = os.stat(p).st_mode & 0o777
        assert mode == 0o600


# ── create_vault tests ────────────────────────────────────────────────


class TestCreateVault:
    def test_falls_back_to_file_vault_when_keyring_unavailable(self, tmp_path):
        fake_errors = type("errors", (), {
            "NoKeyringError": type("NoKeyringError", (Exception,), {}),
        })()
        fake_keyring = type("keyring", (), {
            "get_password": staticmethod(lambda *a, **kw: (_ for _ in ()).throw(Exception("no backend"))),
            "errors": fake_errors,
        })()

        with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_errors}):
            vault = create_vault(file_vault_dir=tmp_path)
        assert isinstance(vault, FileVault)


# ── AccountRegistry tests ────────────────────────────────────────────


def _make_account(
    account_id: str = "acc-1",
    platform: Platform = Platform.DEVPOST,
    username: str = "testuser",
    member_id: str = "test-member",
    credential_ref: str | None = None,
) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=username,
        credential_ref=credential_ref or f"vault://{account_id}",
        member_id=member_id,
    )


class TestAccountRegistry:
    def _registry(self, tmp_path):
        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()
        vault = FileVault(base_dir=vault_dir)
        reg_dir = tmp_path / "accounts"
        reg_dir.mkdir()
        return AccountRegistry(base_dir=reg_dir, vault=vault), vault

    def test_save_get_roundtrip(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        acct = _make_account()
        reg.save_account(acct)
        loaded = reg.get_account("acc-1")
        assert loaded is not None
        assert loaded.account_id == "acc-1"
        assert loaded.platform == Platform.DEVPOST
        assert loaded.username == "testuser"

    def test_get_nonexistent_returns_none(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        assert reg.get_account("ghost") is None

    def test_list_accounts(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        reg.save_account(_make_account(account_id="a1", member_id="m1"))
        reg.save_account(_make_account(account_id="a2", member_id="m2"))
        accounts = reg.list_accounts()
        assert len(accounts) == 2
        ids = {a.account_id for a in accounts}
        assert ids == {"a1", "a2"}

    def test_get_accounts_for_member(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        reg.save_account(_make_account(account_id="a1", member_id="alice"))
        reg.save_account(_make_account(account_id="a2", member_id="bob"))
        reg.save_account(_make_account(account_id="a3", member_id="alice"))
        result = reg.get_accounts_for_member("alice")
        assert len(result) == 2
        assert all(a.member_id == "alice" for a in result)

    def test_get_accounts_by_platform(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        reg.save_account(_make_account(account_id="d1", platform=Platform.DEVPOST))
        reg.save_account(_make_account(account_id="g1", platform=Platform.GITHUB))
        reg.save_account(_make_account(account_id="d2", platform=Platform.DEVPOST))
        result = reg.get_accounts_by_platform(Platform.DEVPOST)
        assert len(result) == 2
        assert all(a.platform == Platform.DEVPOST for a in result)

    def test_delete_account_removes_yaml_and_vault_credential(self, tmp_path):
        reg, vault = self._registry(tmp_path)
        acct = _make_account(account_id="del-me")
        reg.save_account(acct)
        vault.store_credential(acct.credential_ref, "secret-token")
        assert reg.delete_account("del-me") is True
        assert reg.get_account("del-me") is None
        assert vault.get_credential(acct.credential_ref) is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        assert reg.delete_account("no-such") is False

    def test_store_and_get_credential(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        acct = _make_account(account_id="cred-test")
        reg.save_account(acct)
        reg.store_credential("cred-test", "my-api-key")
        assert reg.get_credential("cred-test") == "my-api-key"

    def test_get_credential_nonexistent_account(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        assert reg.get_credential("nonexistent") is None

    def test_store_credential_missing_account_raises(self, tmp_path):
        import pytest
        reg, _ = self._registry(tmp_path)
        with pytest.raises(ValueError, match="Account not found"):
            reg.store_credential("ghost", "secret")

    def test_save_account_overwrites_existing(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        reg.save_account(_make_account(account_id="dup", username="v1"))
        reg.save_account(_make_account(account_id="dup", username="v2"))
        loaded = reg.get_account("dup")
        assert loaded is not None
        assert loaded.username == "v2"
        assert len(reg.list_accounts()) == 1

    def test_list_accounts_skips_malformed_yaml(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        reg.save_account(_make_account(account_id="good"))
        # Write a malformed YAML file
        bad = tmp_path / "accounts" / "bad.yaml"
        bad.write_text("this: is: not: [valid yaml")
        accounts = reg.list_accounts()
        assert len(accounts) == 1
        assert accounts[0].account_id == "good"

    def test_account_id_path_traversal_sanitized(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        acct = _make_account(account_id="../../../etc/passwd")
        reg.save_account(acct)
        # File should be inside the accounts dir, not outside
        acct_dir = tmp_path / "accounts"
        files = list(acct_dir.glob("*.yaml"))
        assert len(files) == 1
        assert files[0].parent == acct_dir

    def test_full_roundtrip_preserves_all_fields(self, tmp_path):
        reg, _ = self._registry(tmp_path)
        acct = PlatformAccount(
            account_id="full",
            platform=Platform.ETHGLOBAL,
            username="fulluser",
            credential_ref="vault://full",
            member_id="member-full",
            fingerprint_config={"viewport": "1920x1080", "locale": "en-US"},
            session_state_path="/tmp/state.json",
            last_login="2026-03-20T10:00:00Z",
            status="needs-reauth",
        )
        reg.save_account(acct)
        loaded = reg.get_account("full")
        assert loaded is not None
        assert loaded.account_id == acct.account_id
        assert loaded.platform == acct.platform
        assert loaded.username == acct.username
        assert loaded.credential_ref == acct.credential_ref
        assert loaded.member_id == acct.member_id
        assert loaded.fingerprint_config == acct.fingerprint_config
        assert loaded.session_state_path == acct.session_state_path
        assert loaded.last_login == acct.last_login
        assert loaded.status == acct.status
