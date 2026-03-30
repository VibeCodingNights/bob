"""OS-agnostic credential storage — keyring with file fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from platformdirs import user_data_dir

log = logging.getLogger(__name__)

SERVICE_NAME = "bob"


class Vault:
    """Primary credential store backed by the OS keyring."""

    def get_credential(self, ref: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE_NAME, ref)

    def store_credential(self, ref: str, value: str) -> None:
        import keyring

        keyring.set_password(SERVICE_NAME, ref, value)

    def delete_credential(self, ref: str) -> None:
        import keyring

        keyring.delete_password(SERVICE_NAME, ref)


class FileVault:
    """Fallback credential store for environments without a system keyring (CI, containers).

    Stores each secret as an individual file with restrictive permissions (0o600).
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else Path(user_data_dir("bob")) / "vault"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        # Sanitize ref to a safe filename
        safe = ref.replace("/", "_").replace("\\", "_")
        return self._dir / safe

    def get_credential(self, ref: str) -> str | None:
        p = self._path(ref)
        if not p.exists():
            return None
        return p.read_text()

    def store_credential(self, ref: str, value: str) -> None:
        p = self._path(ref)
        p.write_text(value)
        p.chmod(0o600)

    def delete_credential(self, ref: str) -> None:
        p = self._path(ref)
        if p.exists():
            p.unlink()


def create_vault(file_vault_dir: str | Path | None = None) -> Vault | FileVault:
    """Try keyring first; fall back to FileVault if unavailable."""
    try:
        import keyring
        from keyring.errors import NoKeyringError

        # Probe keyring to ensure a backend is available
        keyring.get_password(SERVICE_NAME, "__probe__")
        log.debug("Using OS keyring for credential storage")
        return Vault()
    except Exception as exc:
        log.info("Keyring unavailable (%s), falling back to FileVault", exc)
        return FileVault(base_dir=file_vault_dir)
