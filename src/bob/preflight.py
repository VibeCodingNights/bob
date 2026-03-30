"""Pre-registration readiness checks — find missing profile fields and stale logins."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from bob.accounts.registry import AccountRegistry
from bob.composer import PortfolioPlan
from bob.platform_fields import PlatformFieldRegistry
from bob.roster.store import RosterStore


@dataclass
class ProfileGap:
    member_id: str
    field_name: str
    label: str
    platform: str
    required: bool


def check_registration_readiness(
    portfolio: PortfolioPlan,
    roster: RosterStore,
    registry: AccountRegistry,
    field_registry: PlatformFieldRegistry,
) -> list[ProfileGap]:
    """Check all team members have required fields for their registration platforms."""
    gaps: list[ProfileGap] = []

    for assignment in portfolio.assignments:
        platform = assignment.registration_platform
        if not platform:
            continue
        required_fields = field_registry.get_required_fields(platform)
        if not required_fields:
            continue

        for tm in assignment.team:
            profile = roster.load_member(tm.member_id)
            if profile is None:
                # Member not found — every required field is a gap
                for rf in required_fields:
                    gaps.append(ProfileGap(
                        member_id=tm.member_id,
                        field_name=rf.name,
                        label=rf.label,
                        platform=platform,
                        required=rf.required,
                    ))
                continue

            for rf in required_fields:
                if rf.name not in profile.attributes or not profile.attributes[rf.name]:
                    gaps.append(ProfileGap(
                        member_id=tm.member_id,
                        field_name=rf.name,
                        label=rf.label,
                        platform=platform,
                        required=rf.required,
                    ))

    return gaps


def check_login_readiness(
    portfolio: PortfolioPlan,
    registry: AccountRegistry,
) -> list[str]:
    """Return account_ids that don't have valid session state (not logged in).

    .. deprecated::
        Use :func:`bob.account_lifecycle.ensure_all_accounts` instead,
        which automatically handles signup and re-authentication.
    """
    stale: list[str] = []
    seen: set[str] = set()

    for assignment in portfolio.assignments:
        for tm in assignment.team:
            accounts = registry.get_accounts_for_member(tm.member_id)
            for account in accounts:
                if account.account_id in seen:
                    continue
                seen.add(account.account_id)
                if (
                    account.session_state_path is None
                    or not Path(account.session_state_path).exists()
                ):
                    stale.append(account.account_id)

    return stale


def resolve_gaps_interactive(
    gaps: list[ProfileGap],
    roster: RosterStore,
) -> int:
    """Prompt user for each gap, write back to profile. Returns count resolved."""
    resolved = 0

    for gap in gaps:
        prompt = (
            f"[{gap.platform}] {gap.member_id} is missing "
            f"'{gap.label}' ({gap.field_name})"
        )
        print(prompt)
        try:
            value = input(f"  Enter value (or press Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not value:
            continue

        profile = roster.load_member(gap.member_id)
        if profile is None:
            print(f"  Warning: member '{gap.member_id}' not found in roster, skipping")
            continue

        profile.attributes[gap.field_name] = value
        roster.save_member(profile)
        resolved += 1

    return resolved
