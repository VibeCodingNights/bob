"""Auth configuration manager — manages Claude API key and OAuth auth configs.

Stores auth configs in YAML, API keys in the vault (keyring or file fallback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from platformdirs import user_data_dir

from bob.accounts.vault import FileVault, Vault, create_vault

log = logging.getLogger(__name__)


class AuthMethod(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"


@dataclass
class AuthConfig:
    name: str
    method: AuthMethod
    email: str | None = None
    credential_ref: str | None = None  # vault key for API key


class AuthManager:
    """Manage multiple Claude auth configurations with vault-backed API key storage."""

    def __init__(
        self,
        vault: Vault | FileVault | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._vault = vault or create_vault()
        self._dir = Path(base_dir) if base_dir else Path(user_data_dir("bob")) / "auth"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self._dir / "configs.yaml"
        self._configs: dict[str, AuthConfig] = {}
        self._active: str | None = None
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        data = yaml.safe_load(self._config_path.read_text())
        if not data:
            return
        self._active = data.get("active")
        for entry in data.get("configs", []):
            config = AuthConfig(
                name=entry["name"],
                method=AuthMethod(entry["method"]),
                email=entry.get("email"),
                credential_ref=entry.get("credential_ref"),
            )
            self._configs[config.name] = config

    def _save(self) -> None:
        entries = []
        for config in self._configs.values():
            entry: dict = {"name": config.name, "method": config.method.value}
            if config.email:
                entry["email"] = config.email
            if config.credential_ref:
                entry["credential_ref"] = config.credential_ref
            entries.append(entry)
        data = {"active": self._active, "configs": entries}
        self._config_path.write_text(yaml.safe_dump(data, sort_keys=False))

    def add_api_key(self, name: str, api_key: str) -> AuthConfig:
        """Add an API key auth config. Stores the key in the vault."""
        ref = f"claude-auth-{name}"
        self._vault.store_credential(ref, api_key)
        config = AuthConfig(name=name, method=AuthMethod.API_KEY, credential_ref=ref)
        self._configs[name] = config
        if self._active is None:
            self._active = name
        self._save()
        return config

    def add_oauth(self, name: str, email: str | None = None) -> AuthConfig:
        """Add an OAuth auth config (uses the CLI's stored session)."""
        config = AuthConfig(name=name, method=AuthMethod.OAUTH, email=email)
        self._configs[name] = config
        if self._active is None:
            self._active = name
        self._save()
        return config

    def remove(self, name: str) -> bool:
        """Remove an auth config. Deletes the vault credential if present."""
        config = self._configs.pop(name, None)
        if config is None:
            return False
        if config.credential_ref:
            try:
                self._vault.delete_credential(config.credential_ref)
            except Exception:
                pass
        if self._active == name:
            self._active = next(iter(self._configs), None)
        self._save()
        return True

    def list_configs(self) -> list[AuthConfig]:
        """Return all auth configs."""
        return list(self._configs.values())

    def get_active(self) -> AuthConfig | None:
        """Return the currently active auth config."""
        if self._active is None:
            return None
        return self._configs.get(self._active)

    def set_active(self, name: str) -> None:
        """Set the active auth config by name."""
        if name not in self._configs:
            raise KeyError(f"Auth config not found: {name}")
        self._active = name
        self._save()

    def get_env(self, name: str | None = None) -> dict:
        """Get env dict for ClaudeAgentOptions.

        Returns {"ANTHROPIC_API_KEY": "..."} for api_key configs,
        or {} for oauth configs (which use the CLI's stored session).
        """
        config = self._configs.get(name or self._active or "")
        if config is None:
            return {}
        if config.method == AuthMethod.API_KEY and config.credential_ref:
            key = self._vault.get_credential(config.credential_ref)
            if key:
                return {"ANTHROPIC_API_KEY": key}
        return {}
