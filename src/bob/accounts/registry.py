"""Account CRUD and session lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from platformdirs import user_data_dir

from .models import Platform, PlatformAccount
from .vault import Vault, FileVault, create_vault

log = logging.getLogger(__name__)


def _account_to_dict(account: PlatformAccount) -> dict:
    """Serialize a PlatformAccount to a plain dict for YAML persistence."""
    return {
        "account_id": account.account_id,
        "platform": account.platform.value,
        "username": account.username,
        "credential_ref": account.credential_ref,
        "member_id": account.member_id,
        "fingerprint_config": account.fingerprint_config,
        "session_state_path": account.session_state_path,
        "last_login": account.last_login,
        "status": account.status,
    }


def _dict_to_account(data: dict) -> PlatformAccount:
    """Deserialize a dict from YAML into a PlatformAccount."""
    return PlatformAccount(
        account_id=data["account_id"],
        platform=Platform(data["platform"]),
        username=data["username"],
        credential_ref=data["credential_ref"],
        member_id=data["member_id"],
        fingerprint_config=data.get("fingerprint_config", {}),
        session_state_path=data.get("session_state_path"),
        last_login=data.get("last_login"),
        status=data.get("status", "active"),
    )


class AccountRegistry:
    """CRUD for platform accounts with YAML persistence and vault-backed credentials."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        vault: Vault | FileVault | None = None,
    ) -> None:
        self._dir = Path(base_dir) if base_dir else Path(user_data_dir("bob")) / "accounts"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._vault = vault or create_vault()

    @staticmethod
    def _safe_filename(account_id: str) -> str:
        """Sanitize account_id to prevent path traversal."""
        safe = account_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        if not safe or safe.startswith("."):
            safe = "_" + safe
        return safe

    def _path(self, account_id: str) -> Path:
        return self._dir / f"{self._safe_filename(account_id)}.yaml"

    def save_account(self, account: PlatformAccount) -> Path:
        """Persist account metadata to YAML. Never writes credentials."""
        p = self._path(account.account_id)
        p.write_text(yaml.safe_dump(_account_to_dict(account), sort_keys=False))
        return p

    def get_account(self, account_id: str) -> PlatformAccount | None:
        p = self._path(account_id)
        if not p.exists():
            return None
        data = yaml.safe_load(p.read_text())
        return _dict_to_account(data)

    def list_accounts(self) -> list[PlatformAccount]:
        accounts = []
        for p in sorted(self._dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(p.read_text())
                accounts.append(_dict_to_account(data))
            except Exception:
                log.warning("Skipping malformed account file: %s", p)
        return accounts

    def get_accounts_for_member(self, member_id: str) -> list[PlatformAccount]:
        return [a for a in self.list_accounts() if a.member_id == member_id]

    def get_accounts_by_platform(self, platform: Platform) -> list[PlatformAccount]:
        return [a for a in self.list_accounts() if a.platform == platform]

    def delete_account(self, account_id: str) -> bool:
        p = self._path(account_id)
        if not p.exists():
            return False
        # Also remove credential from vault
        account = self.get_account(account_id)
        if account:
            try:
                self._vault.delete_credential(account.credential_ref)
            except Exception:
                log.warning("Could not remove credential for %s", account_id)
        p.unlink()
        return True

    def store_credential(self, account_id: str, credential: str) -> None:
        """Store a credential in the vault using the account's credential_ref."""
        account = self.get_account(account_id)
        if account is None:
            raise ValueError(f"Account not found: {account_id}")
        self._vault.store_credential(account.credential_ref, credential)

    def get_credential(self, account_id: str) -> str | None:
        """Retrieve a credential from the vault."""
        account = self.get_account(account_id)
        if account is None:
            return None
        return self._vault.get_credential(account.credential_ref)
