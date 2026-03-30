"""Automated login agent — credential-based re-authentication via stealth-browser.

Launches a Claude agent that fills login forms using stored credentials,
handles 2FA/CAPTCHA escalation, and saves session state on success.
Falls back to interactive login if the automated attempt fails.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)
from platformdirs import user_data_dir

from bob.accounts.registry import AccountRegistry
from bob.auth_strategy import AuthStrategyRegistry, build_auth_prompt_section
from bob.login import _LOGIN_URLS, login_account
from bob.telemetry import AgentSession, run_agent
from bob.tools.browser import BrowserSessionManager, _make_browser_tools
from bob.tools.mcp import _resp

# Type alias for escalation handler callback
EscalationHandler = Callable[[str, str, str], Awaitable[str]]

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Login phases can run several minutes; 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")


# ---------------------------------------------------------------------------
# Default escalation handler
# ---------------------------------------------------------------------------


async def terminal_escalation_handler(
    field_name: str, description: str, context: str
) -> str:
    """Default: print prompt, read from stdin."""
    print(f"\n\u26a0 Login needs: {description}")
    print(f"  Field: {field_name}")
    print(f"  Context: {context}")
    value = input("  Value: ")
    return value


# ---------------------------------------------------------------------------
# Terminal tool schema
# ---------------------------------------------------------------------------

CONFIRM_LOGIN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
            "description": "Whether login completed successfully",
        },
        "error": {
            "type": "string",
            "description": "Error message if login failed",
        },
    },
    "required": ["success"],
}

ESCALATE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "field_name": {
            "type": "string",
            "description": "Name of the field that is needed (e.g. '2fa_code', 'captcha_help')",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of what is needed",
        },
        "context": {
            "type": "string",
            "description": "Additional context (e.g. what the page shows)",
        },
    },
    "required": ["field_name", "description", "context"],
}

CHECK_GITHUB_SESSION_SCHEMA: dict = {
    "type": "object",
    "properties": {},
}

RECORD_AUTH_SUCCESS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "strategy_name": {
            "type": "string",
            "description": (
                "Auth strategy that succeeded, e.g. 'github_oauth', "
                "'google_oauth', 'email_password'"
            ),
        },
    },
    "required": ["strategy_name"],
}


# ---------------------------------------------------------------------------
# Allowed tools list
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = [
    "mcp__autologin__browser_create_session",
    "mcp__autologin__browser_navigate",
    "mcp__autologin__browser_click",
    "mcp__autologin__browser_fill",
    "mcp__autologin__browser_extract_text",
    "mcp__autologin__browser_screenshot",
    "mcp__autologin__browser_close_session",
    "mcp__autologin__browser_save_session",
    "mcp__autologin__browser_evaluate",
    "mcp__autologin__browser_wait_for_navigation",
    "mcp__autologin__browser_select_option",
    "mcp__autologin__confirm_login",
    "mcp__autologin__escalate",
    "mcp__autologin__check_github_session",
    "mcp__autologin__record_auth_success",
]


# ---------------------------------------------------------------------------
# Platform-specific system prompts
# ---------------------------------------------------------------------------

_DEVPOST_LOGIN_PROMPT = """\
You are a login agent. Log in to Devpost using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Fill in the email/username field and password field.
4. Click the "Log in" or "Sign in" button.
5. If a 2FA prompt appears, call escalate with field_name="2fa_code".
6. If a CAPTCHA appears that you cannot solve, call escalate with field_name="captcha_help".
7. Wait for the page to show a logged-in state (dashboard, profile, etc.).
8. Call browser_save_session to save cookies and session state.
9. Call confirm_login with success=true.
10. Call browser_close_session to clean up.

If login fails at any step, take a screenshot, then call \
confirm_login with success=false and describe the error."""

_ETHGLOBAL_LOGIN_PROMPT = """\
You are a login agent. Log in to ETHGlobal using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Fill in the email and password fields.
4. Click the login/sign-in button.
5. If a 2FA prompt appears, call escalate with field_name="2fa_code".
6. If a CAPTCHA appears, call escalate with field_name="captcha_help".
7. Wait for the dashboard or profile page to load.
8. Call browser_save_session to save session state.
9. Call confirm_login with success=true.
10. Call browser_close_session to clean up.

If login fails, take a screenshot and call confirm_login with success=false."""

_GITHUB_LOGIN_PROMPT = """\
You are a login agent. Log in to GitHub using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Fill in the "Username or email address" field and "Password" field.
4. Click the "Sign in" button.
5. If a 2FA/TOTP prompt appears, call escalate with field_name="2fa_code" \
and description="Enter the 2FA code for this GitHub account".
6. If a device verification prompt appears, call escalate with \
field_name="device_verification" and description="Check email for device verification code".
7. If a CAPTCHA appears, call escalate with field_name="captcha_help".
8. Wait for the GitHub dashboard to load.
9. Call browser_save_session to save session state.
10. Call confirm_login with success=true.
11. Call browser_close_session to clean up.

If login fails, take a screenshot and call confirm_login with success=false."""

_LUMA_LOGIN_PROMPT = """\
You are a login agent. Log in to Luma using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Fill in the email field and password field.
4. Click the sign-in button.
5. If a magic link or email verification is required, call escalate with \
field_name="email_verification" and description="Check email for Luma sign-in link".
6. If a CAPTCHA appears, call escalate with field_name="captcha_help".
7. Wait for the dashboard to load.
8. Call browser_save_session to save session state.
9. Call confirm_login with success=true.
10. Call browser_close_session to clean up.

If login fails, take a screenshot and call confirm_login with success=false."""

_DEVFOLIO_LOGIN_PROMPT = """\
You are a login agent. Log in to Devfolio using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Fill in the email and password fields.
4. Click the login button.
5. If a 2FA prompt appears, call escalate with field_name="2fa_code".
6. If a CAPTCHA appears, call escalate with field_name="captcha_help".
7. Wait for the dashboard to load.
8. Call browser_save_session to save session state.
9. Call confirm_login with success=true.
10. Call browser_close_session to clean up.

If login fails, take a screenshot and call confirm_login with success=false."""

_GENERIC_LOGIN_PROMPT = """\
You are a login agent. Log in to the platform using the provided credentials.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the login URL.
3. Find the login form and fill in the username/email and password fields.
4. Submit the login form.
5. If a 2FA prompt appears, call escalate with field_name="2fa_code".
6. If a CAPTCHA appears, call escalate with field_name="captcha_help".
7. Wait for the page to show a logged-in state.
8. Call browser_save_session to save session state.
9. Call confirm_login with success=true.
10. Call browser_close_session to clean up.

If login fails, take a screenshot and call confirm_login with success=false."""

_OAUTH_PREFERENCE_INSTRUCTIONS = """

## OAuth preference

BEFORE filling any login form, look for OAuth buttons ('Log in with GitHub', \
'Continue with GitHub'). If found, call check_github_session first. If your \
GitHub session is valid, CLICK THE OAUTH BUTTON — it is faster and avoids 2FA \
entirely. Only use the email/password form if no OAuth option is available or \
if your OAuth sessions are not valid. After completing login via any method, \
call record_auth_success with the strategy you used (e.g. 'github_oauth' or \
'email_password')."""

_PLATFORM_LOGIN_PROMPTS: dict[str, str] = {
    "devpost": _DEVPOST_LOGIN_PROMPT,
    "ethglobal": _ETHGLOBAL_LOGIN_PROMPT,
    "github": _GITHUB_LOGIN_PROMPT,
    "luma": _LUMA_LOGIN_PROMPT,
    "devfolio": _DEVFOLIO_LOGIN_PROMPT,
}


def _get_login_system_prompt(platform: str) -> str:
    base = _PLATFORM_LOGIN_PROMPTS.get(platform.lower(), _GENERIC_LOGIN_PROMPT)
    return base + _OAUTH_PREFERENCE_INSTRUCTIONS


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------


def _create_autologin_server(
    session_manager: BrowserSessionManager,
    registry: AccountRegistry,
    capture: dict,
    escalation_handler: EscalationHandler | None = None,
    account_id: str = "",
    platform: str = "",
    auth_registry: AuthStrategyRegistry | None = None,
) -> dict:
    """Create an MCP server with browser tools + escalate + confirm_login."""
    _handler = escalation_handler or terminal_escalation_handler

    async def confirm_login(args: dict) -> dict:
        capture["data"] = args
        return _resp("Login result recorded.")

    async def escalate(args: dict) -> dict:
        fname = args["field_name"]
        desc = args["description"]
        ctx = args.get("context", "")
        value = await _handler(fname, desc, ctx)
        return _resp(value)

    # --- OAuth tools ---

    async def check_github_session(args: dict) -> dict:
        account = registry.get_account(account_id) if account_id else None
        if account is None:
            return _resp("no_session")
        member_id = account.member_id
        accounts = registry.get_accounts_for_member(member_id)
        for acct in accounts:
            if acct.platform.value == "github" and acct.status == "active":
                if acct.session_state_path and Path(acct.session_state_path).exists():
                    return _resp(f"valid: {acct.username}")
        return _resp("no_session")

    async def record_auth_success(args: dict) -> dict:
        strategy_name = args["strategy_name"]
        if auth_registry is not None and platform:
            auth_registry.record_success(platform, strategy_name, "login")
            return _resp(f"Recorded auth success: {strategy_name}")
        return _resp("No auth registry available.")

    tools = [
        *_make_browser_tools(session_manager, account_registry=registry),
        SdkMcpTool(
            name="confirm_login",
            description=(
                "Submit the login result. Call this exactly once when "
                "login is complete (success or failure)."
            ),
            input_schema=CONFIRM_LOGIN_SCHEMA,
            handler=confirm_login,
        ),
        SdkMcpTool(
            name="escalate",
            description=(
                "Escalate to the user when human intervention is needed "
                "(2FA code, CAPTCHA, email verification). "
                "Prompts the user and returns their answer."
            ),
            input_schema=ESCALATE_SCHEMA,
            handler=escalate,
        ),
        SdkMcpTool(
            name="check_github_session",
            description=(
                "Check if a valid GitHub session exists for this member. "
                "Returns 'valid: {username}' or 'no_session'."
            ),
            input_schema=CHECK_GITHUB_SESSION_SCHEMA,
            handler=check_github_session,
        ),
        SdkMcpTool(
            name="record_auth_success",
            description=(
                "Record which auth strategy succeeded (e.g. 'github_oauth', "
                "'email_password'). Call after login completes successfully."
            ),
            input_schema=RECORD_AUTH_SUCCESS_SCHEMA,
            handler=record_auth_success,
        ),
    ]

    return create_sdk_mcp_server(name="autologin", tools=tools)


# ---------------------------------------------------------------------------
# Core auto-login function
# ---------------------------------------------------------------------------


async def auto_login(
    account_id: str,
    registry: AccountRegistry,
    escalation_handler: EscalationHandler = terminal_escalation_handler,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 20,
    headless: bool = True,
    auth_registry: AuthStrategyRegistry | None = None,
) -> bool:
    """Attempt automated login using stored credentials.

    Launches a Claude agent that fills the login form, handles 2FA/CAPTCHA
    escalation, and saves session state on success. Falls back to interactive
    login (headless=False) if the agent fails.

    Args:
        account_id: The account to log in.
        registry: AccountRegistry for account lookup and persistence.
        escalation_handler: Callback for interactive escalation (2FA, CAPTCHA).
        model: Claude model ID.
        max_turns: Max agent turns.
        headless: Whether to run the browser headlessly.

    Returns:
        True if login succeeded.
    """
    account = registry.get_account(account_id)
    if account is None:
        logger.error("Account not found: %s", account_id)
        return False

    platform_name = account.platform.value
    login_url = _LOGIN_URLS.get(platform_name)
    if login_url is None:
        logger.error("No login URL known for platform: %s", platform_name)
        return False

    # Get credential from vault — never log it
    credential = registry.get_credential(account_id)
    if credential is None:
        logger.error("No credential found for account: %s", account_id)
        return False

    # Session save path
    sessions_dir = Path(user_data_dir("bob")) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    safe_id = account_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    session_state_path = str(sessions_dir / f"{safe_id}.json")

    session_manager = BrowserSessionManager()
    capture: dict = {}

    server = _create_autologin_server(
        session_manager,
        registry,
        capture,
        escalation_handler=escalation_handler,
        account_id=account_id,
        platform=platform_name,
        auth_registry=auth_registry,
    )

    system_prompt = _get_login_system_prompt(platform_name)

    # Augment system prompt with auth strategy info if registry available
    if auth_registry is not None and account:
        auth_info = auth_registry.get_auth_info(
            platform_name, account.member_id, registry
        )
        auth_section = build_auth_prompt_section(auth_info)
        if auth_section:
            system_prompt += auth_section

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        mcp_servers={"autologin": server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    # Build user message — credential goes here, NOT in system prompt
    user_message = (
        f"Log in to {platform_name}.\n\n"
        f"Session ID: login-{account_id}\n"
        f"Account ID: {account_id}\n"
        f"Login URL: {login_url}\n"
        f"Username: {account.username}\n"
        f"Password: {credential}\n"
        f"Session save path: {session_state_path}\n"
    )

    agent_session = AgentSession(f"autologin:{account_id}", max_turns=max_turns)

    try:
        result = await run_agent(user_message, options, agent_session)
    finally:
        await session_manager.close_all()

    # Check result
    data = capture.get("data")
    if data and data.get("success"):
        # Update account with session info
        account.session_state_path = session_state_path
        account.last_login = datetime.now(timezone.utc).isoformat()
        account.status = "active"
        registry.save_account(account)
        logger.info(
            "Auto-login succeeded for %s (tokens: %d/%d)",
            account_id,
            result.input_tokens,
            result.output_tokens,
        )
        return True

    error_msg = data.get("error", "unknown") if data else "agent did not call confirm_login"
    logger.warning(
        "Auto-login failed for %s: %s — falling back to interactive login",
        account_id,
        error_msg,
    )

    # Fallback to interactive login
    return await login_account(account_id, registry, headless=False)
