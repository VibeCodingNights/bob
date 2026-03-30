"""Credential generation and account provisioning."""

from __future__ import annotations

import secrets

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry


def generate_password(length: int = 24) -> str:
    """Generate a cryptographically secure random password."""
    return secrets.token_urlsafe(length)


def create_account_with_credentials(
    member_id: str,
    platform: str,
    username: str,
    registry: AccountRegistry,
) -> PlatformAccount:
    """Create a new PlatformAccount with generated credentials and fingerprint.

    1. Generate secure password, store in vault
    2. Generate fingerprint config (if stealth-browser available, else empty dict)
    3. Create and save PlatformAccount
    """
    account_id = f"{member_id}-{platform}"
    credential_ref = f"{member_id}-{platform}-password"

    password = generate_password()
    registry._vault.store_credential(credential_ref, password)

    # Generate fingerprint if stealth-browser available
    fingerprint_config: dict = {}
    try:
        from stealth_browser.config import BrowserConfig
        import dataclasses

        config = BrowserConfig.get_config()
        fingerprint_config = dataclasses.asdict(config)
    except (ImportError, TypeError):
        pass

    account = PlatformAccount(
        account_id=account_id,
        platform=Platform(platform),
        username=username,
        credential_ref=credential_ref,
        member_id=member_id,
        fingerprint_config=fingerprint_config,
    )
    registry.save_account(account)
    return account
