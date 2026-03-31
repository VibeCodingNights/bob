"""Unified account lifecycle — ensure members have working platform accounts.

Combines signup (new account creation) and auto-login (re-authentication)
into a single entry point that the registration pre-flight can call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable

from bob.accounts.models import PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.auth_strategy import AuthStrategyRegistry
from bob.autologin import auto_login
from bob.autologin import terminal_escalation_handler as _default_escalation
from bob.composer import PortfolioPlan
from bob.platform_fields import PlatformFieldRegistry
from bob.roster.store import RosterStore
from bob.signup import signup_account

# Type alias for escalation handler callback
EscalationHandler = Callable[[str, str, str], Awaitable[str]]

terminal_escalation_handler = _default_escalation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session validity check
# ---------------------------------------------------------------------------


def _session_is_valid(account: PlatformAccount) -> bool:
    """Check if account has a valid session state file."""
    if not account.session_state_path:
        return False
    return Path(account.session_state_path).exists()


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------


async def ensure_account(
    member_id: str,
    platform: str,
    roster: RosterStore,
    registry: AccountRegistry,
    field_registry: PlatformFieldRegistry,
    escalation_handler: EscalationHandler = terminal_escalation_handler,
    headless: bool = False,  # default visible — signup needs user for email verification
    cdp_endpoint: str | None = None,
    model: str = "claude-sonnet-4-6",
    auth_registry: AuthStrategyRegistry | None = None,
    auth_env: dict | None = None,
) -> PlatformAccount | None:
    """Ensure member has a working account on platform.

    1. If no account exists -> signup
    2. If account exists but session is stale -> auto-login
    3. If account exists and session is valid -> return as-is

    For non-GitHub platforms, checks whether a valid GitHub session exists
    for this member (enables OAuth signup/login on downstream platforms).

    Args:
        member_id: The team member who needs the account.
        platform: Platform name (devpost, ethglobal, github, etc.).
        roster: RosterStore for member profile lookups.
        registry: AccountRegistry for account persistence.
        field_registry: PlatformFieldRegistry for field discovery.
        escalation_handler: Callback for interactive escalation.
        headless: Whether to run browser headlessly for login.
        model: Claude model ID.
        auth_registry: Optional AuthStrategyRegistry for OAuth strategy tracking.

    Returns:
        The working PlatformAccount, or None if all attempts failed.
    """
    # For non-GitHub platforms, check if GitHub OAuth is available
    if platform != "github":
        github_accounts = registry.get_accounts_for_member(member_id)
        github_account = next(
            (a for a in github_accounts if a.platform.value == "github"),
            None,
        )
        if github_account and _session_is_valid(github_account):
            logger.info(
                "GitHub session valid for %s — OAuth available for %s signup/login",
                member_id,
                platform,
            )
        else:
            logger.warning(
                "GitHub session not available for %s — %s will use email/password fallback",
                member_id,
                platform,
            )

    # 1. Find existing account for this member+platform
    accounts = registry.get_accounts_for_member(member_id)
    account = next(
        (a for a in accounts if a.platform.value == platform),
        None,
    )

    # 2. No account, or pending (failed prior signup) -> signup
    if account is None or account.status == "pending":
        if account is not None:
            logger.info("Retrying signup for %s on %s (prior attempt pending)", member_id, platform)
            registry.delete_account(account.account_id)
        else:
            logger.info("No %s account for %s — creating via signup", platform, member_id)
        return await signup_account(
            member_id,
            platform,
            roster,
            registry,
            field_registry,
            escalation_handler=escalation_handler,
            model=model,
            headless=headless,
            cdp_endpoint=cdp_endpoint,
            auth_registry=auth_registry,
            auth_env=auth_env,
        )

    # 3. Check session freshness
    if not _session_is_valid(account):
        logger.info(
            "Session stale for %s on %s — re-authenticating",
            member_id,
            platform,
        )
        success = await auto_login(
            account.account_id,
            registry,
            escalation_handler,
            model,
            headless=headless,
            auth_registry=auth_registry,
            auth_env=auth_env,
        )
        if not success:
            logger.warning(
                "Re-authentication failed for %s on %s",
                member_id,
                platform,
            )
            return None
        # Reload account after login updated it
        account = registry.get_account(account.account_id)

    return account


# ---------------------------------------------------------------------------
# Portfolio-wide entry point
# ---------------------------------------------------------------------------


async def ensure_all_accounts(
    portfolio: PortfolioPlan,
    roster: RosterStore,
    registry: AccountRegistry,
    field_registry: PlatformFieldRegistry,
    escalation_handler: EscalationHandler = terminal_escalation_handler,
    headless: bool = True,
    cdp_endpoint: str | None = None,
    model: str = "claude-sonnet-4-6",
    auth_registry: AuthStrategyRegistry | None = None,
    auth_env: dict | None = None,
) -> dict[str, PlatformAccount]:
    """Ensure all team members in portfolio have working accounts.

    Processes GitHub accounts FIRST (OAuth root), then ensures remaining
    platforms which can use GitHub OAuth for signup/login.

    Returns:
        Dict mapping "member_id:platform" to the working PlatformAccount.
    """
    results: dict[str, PlatformAccount] = {}

    # Collect all (member_id, platform) pairs needed
    needed: list[tuple[str, str]] = []
    for assignment in portfolio.assignments:
        platform = assignment.registration_platform
        if not platform:
            continue
        for member in assignment.team:
            key = f"{member.member_id}:{platform}"
            if key not in {f"{m}:{p}" for m, p in needed}:
                needed.append((member.member_id, platform))
            break  # only need first member's account per track

    # Partition: GitHub first, then everything else
    github_needed = [(m, p) for m, p in needed if p == "github"]
    other_needed = [(m, p) for m, p in needed if p != "github"]

    # Also ensure GitHub for members who need any other platform (OAuth root)
    members_needing_accounts = {m for m, _ in other_needed}
    for member_id in members_needing_accounts:
        if not any(m == member_id for m, _ in github_needed):
            github_needed.append((member_id, "github"))

    # Phase 1: Ensure GitHub accounts (OAuth root)
    for member_id, platform in github_needed:
        key = f"{member_id}:{platform}"
        account = await ensure_account(
            member_id,
            platform,
            roster,
            registry,
            field_registry,
            escalation_handler,
            headless,
            model,
            auth_registry=auth_registry,
            auth_env=auth_env,
        )
        if account:
            results[key] = account
            logger.info("GitHub session ready for %s — OAuth available for downstream platforms", member_id)
        else:
            logger.warning("GitHub session not available for %s — downstream platforms will use email/password fallback", member_id)

    # Phase 2: Ensure remaining platforms (can now use OAuth)
    for member_id, platform in other_needed:
        key = f"{member_id}:{platform}"
        if key in results:
            continue
        account = await ensure_account(
            member_id,
            platform,
            roster,
            registry,
            field_registry,
            escalation_handler,
            headless,
            model,
            auth_registry=auth_registry,
            auth_env=auth_env,
        )
        if account:
            results[key] = account

    return results
