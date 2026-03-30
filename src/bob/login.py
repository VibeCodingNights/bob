"""Interactive login flow — launch a stealth browser for manual 2FA/CAPTCHA handling."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

from bob.accounts.registry import AccountRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guard stealth-browser imports
# ---------------------------------------------------------------------------

try:
    from stealth_browser.patchright import (
        create_stealth_browser,
        create_stealth_context,
        new_stealth_page,
        stealth_goto,
        close_stealth_browser,
    )

    HAS_STEALTH_BROWSER = True
except ImportError:
    HAS_STEALTH_BROWSER = False


def _require_stealth_browser() -> None:
    if not HAS_STEALTH_BROWSER:
        raise RuntimeError(
            "stealth-browser is not installed. "
            "Install with: pip install stealth-browser"
        )


# ---------------------------------------------------------------------------
# Platform login URLs
# ---------------------------------------------------------------------------

_LOGIN_URLS: dict[str, str] = {
    "devpost": "https://devpost.com/users/login",
    "ethglobal": "https://ethglobal.com/login",
    "luma": "https://lu.ma/signin",
    "devfolio": "https://devfolio.co/login",
    "github": "https://github.com/login",
}


# ---------------------------------------------------------------------------
# Core login function
# ---------------------------------------------------------------------------


async def login_account(
    account_id: str,
    registry: AccountRegistry,
    headless: bool = False,
) -> bool:
    """Launch a stealth browser for interactive login.

    Opens the platform login page so the user can handle 2FA/CAPTCHAs manually.
    After the user confirms login is complete, saves the browser session state
    for future automated use.

    Args:
        account_id: The account to log in.
        registry: AccountRegistry for account lookup and persistence.
        headless: If False (default), opens a visible browser window.

    Returns:
        True if session state was saved successfully.
    """
    _require_stealth_browser()
    from bob.tools.browser import _dict_to_platform_config

    account = registry.get_account(account_id)
    if account is None:
        log.error("Account not found: %s", account_id)
        return False

    platform_name = account.platform.value
    login_url = _LOGIN_URLS.get(platform_name)
    if login_url is None:
        log.error("No login URL known for platform: %s", platform_name)
        return False

    # Get credential for display hint (we don't auto-fill — user handles it)
    credential = registry.get_credential(account_id)
    if credential:
        log.info("Credential available for %s (username: %s)", account_id, account.username)

    # Build platform config from fingerprint if available
    platform_config = None
    if account.fingerprint_config:
        platform_config = _dict_to_platform_config(account.fingerprint_config)

    # Launch browser
    browser = await create_stealth_browser(headless=headless)
    if platform_config is not None:
        browser._stealth_config = platform_config

    context = await create_stealth_context(browser, config=platform_config)
    page = await new_stealth_page(context)

    try:
        print(f"\nOpening {platform_name} login page for: {account.username}")
        print(f"URL: {login_url}")
        await stealth_goto(page, login_url)

        print("\nPlease log in using the browser window.")
        print("Handle any 2FA or CAPTCHAs as needed.")
        input("\nPress Enter when login is complete...")

        # Save session state
        sessions_dir = Path(user_data_dir("bob")) / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        safe_id = account_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        state_path = sessions_dir / f"{safe_id}.json"

        storage_state = await context.storage_state(path=str(state_path))
        log.info("Session state saved to %s", state_path)

        # Update account with session info
        account.session_state_path = str(state_path)
        account.last_login = datetime.now(timezone.utc).isoformat()
        account.status = "active"
        registry.save_account(account)

        print(f"Login successful. Session saved for {account.username}.")
        return True

    except (EOFError, KeyboardInterrupt):
        print("\nLogin cancelled.")
        return False
    finally:
        await close_stealth_browser(browser)
