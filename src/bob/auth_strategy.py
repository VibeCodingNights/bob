"""Auth strategy registry — tracks which auth methods work on which platforms.

Records OAuth and email/password strategy successes per platform in YAML files.
Used to dynamically augment signup/login agent system prompts with preferred
auth methods (e.g. "This platform supports GitHub OAuth — click that button").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from platformdirs import user_data_dir

from bob.accounts.registry import AccountRegistry

log = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    """Sanitize a platform name for filesystem safety."""
    safe = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    if not safe or safe.startswith("."):
        safe = "_" + safe
    return safe


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrategyRecord:
    """A single recorded auth strategy success."""

    name: str  # e.g. "github_oauth", "google_oauth", "email_password"
    action: str  # "signup" or "login"
    last_success: str  # ISO date
    engine: str = "patchright"  # browser engine used: "patchright" or "native"


@dataclass
class PlatformAuthInfo:
    """Full auth context for a platform, used to build prompt sections."""

    platform: str
    known_strategies: list[str]  # ["github_oauth", "google_oauth", "email_password"]
    github_session_valid: bool
    google_session_valid: bool
    preferred_engine: str = "patchright"  # engine that last succeeded


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AuthStrategyRegistry:
    """Records which auth methods work on which platforms.

    Each platform gets one YAML file: ``{platform}.yaml`` with a list of
    strategy records (name, action, last_success).
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._dir = (
            Path(base_dir)
            if base_dir
            else Path(user_data_dir("bob")) / "auth_strategies"
        )
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, platform: str) -> Path:
        return self._dir / f"{_safe_filename(platform)}.yaml"

    def _load(self, platform: str) -> list[StrategyRecord]:
        p = self._path(platform)
        if not p.exists():
            return []
        data = yaml.safe_load(p.read_text())
        if not data or "strategies" not in data:
            return []
        return [
            StrategyRecord(
                name=d["name"],
                action=d.get("action", "signup"),
                last_success=d.get("last_success", ""),
                engine=d.get("engine", "patchright"),
            )
            for d in data["strategies"]
        ]

    def _save(self, platform: str, records: list[StrategyRecord]) -> None:
        p = self._path(platform)
        data = {
            "strategies": [
                {
                    "name": r.name,
                    "action": r.action,
                    "last_success": r.last_success,
                    "engine": r.engine,
                }
                for r in records
            ]
        }
        p.write_text(yaml.safe_dump(data, sort_keys=False))

    def get_strategies(self, platform: str) -> list[str]:
        """Known auth strategies for this platform, ordered by preference.

        OAuth strategies come first, then email_password.
        """
        records = self._load(platform)
        seen: set[str] = set()
        ordered: list[str] = []
        for r in records:
            if r.name not in seen:
                seen.add(r.name)
                ordered.append(r.name)
        # Sort: oauth strategies first
        oauth = [s for s in ordered if "oauth" in s]
        rest = [s for s in ordered if "oauth" not in s]
        return oauth + rest

    def record_success(
        self,
        platform: str,
        strategy: str,
        action: str,
        engine: str = "patchright",
    ) -> None:
        """Record that a strategy worked for signup/login on this platform."""
        records = self._load(platform)
        today = date.today().isoformat()
        # Update existing or append
        found = False
        for r in records:
            if r.name == strategy and r.action == action:
                r.last_success = today
                r.engine = engine
                found = True
                break
        if not found:
            records.append(
                StrategyRecord(
                    name=strategy, action=action,
                    last_success=today, engine=engine,
                )
            )
        self._save(platform, records)
        log.info(
            "Recorded auth success: %s/%s on %s (engine=%s)",
            strategy, action, platform, engine,
        )

    def get_preferred_engine(self, platform: str) -> str:
        """Return the engine that last succeeded on this platform."""
        records = self._load(platform)
        # Return the engine from the most recent success
        for r in sorted(records, key=lambda r: r.last_success, reverse=True):
            if r.engine:
                return r.engine
        return "patchright"

    def get_auth_info(
        self,
        platform: str,
        member_id: str,
        registry: AccountRegistry,
    ) -> PlatformAuthInfo:
        """Build full auth context: known strategies + session validity."""
        known = self.get_strategies(platform)

        # Check if member has a GitHub account with a valid session
        github_valid = False
        google_valid = False

        accounts = registry.get_accounts_for_member(member_id)
        for acct in accounts:
            if acct.platform.value == "github" and acct.status == "active":
                if acct.session_state_path and Path(acct.session_state_path).exists():
                    github_valid = True
            # Future: google_valid check when Google accounts are supported

        return PlatformAuthInfo(
            platform=platform,
            known_strategies=known,
            github_session_valid=github_valid,
            google_session_valid=google_valid,
            preferred_engine=self.get_preferred_engine(platform),
        )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_auth_prompt_section(auth_info: PlatformAuthInfo) -> str:
    """Generate the auth strategy section to inject into agent system prompts.

    Returns an empty string if no useful auth info is available.
    """
    lines: list[str] = []

    if auth_info.github_session_valid and "github_oauth" in auth_info.known_strategies:
        lines.append(
            "PREFERRED: This platform supports GitHub OAuth and you have a valid "
            "GitHub session. Look for a 'Sign up with GitHub' or 'Log in with GitHub' "
            "button and CLICK IT instead of filling the email/password form. "
            "This bypasses CAPTCHAs and is faster."
        )
    elif auth_info.github_session_valid:
        lines.append(
            "You have a valid GitHub session. If you see a 'Sign up with GitHub' or "
            "'Log in with GitHub' button on the page, PREFER clicking it over the "
            "email/password form — it bypasses CAPTCHAs entirely."
        )

    if auth_info.google_session_valid and "google_oauth" in auth_info.known_strategies:
        lines.append(
            "PREFERRED: This platform supports Google OAuth and you have a valid "
            "Google session. Look for 'Continue with Google' and click it."
        )
    elif auth_info.google_session_valid:
        lines.append(
            "You have a valid Google session. If you see 'Continue with Google' "
            "on the page, prefer it over the email/password form."
        )

    if auth_info.known_strategies:
        strats = ", ".join(auth_info.known_strategies)
        lines.append(f"Known working auth methods for this platform: {strats}.")

    if not lines:
        return ""

    section = "\n\n## Auth Strategy\n\n" + "\n\n".join(lines)
    return section
