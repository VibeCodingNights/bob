"""Signup agent — autonomous account creation via stealth-browser.

Launches a Claude agent that navigates to a platform's signup page,
fills the registration form using member attributes and generated credentials,
and handles email verification escalation.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)
from platformdirs import user_data_dir

from bob.accounts.credentials import create_account_with_credentials
from bob.accounts.models import PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.telemetry import AgentSession, run_agent
from bob.auth_strategy import AuthStrategyRegistry, build_auth_prompt_section
from bob.platform_fields import PlatformField, PlatformFieldRegistry
from bob.resolvers import ResolverChain, create_default_chain, make_resolve_field_tool
from bob.roster.store import RosterStore
from bob.tools.browser import BrowserSessionManager, _make_browser_tools
from bob.tools.mcp import _resp

# Type alias for escalation handler callback
EscalationHandler = Callable[[str, str, str], Awaitable[str]]

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Signup phases can run several minutes; 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")


# ---------------------------------------------------------------------------
# Platform signup URLs
# ---------------------------------------------------------------------------

_SIGNUP_URLS: dict[str, str] = {
    "devpost": "https://devpost.com/users/register",
    "ethglobal": "https://ethglobal.com/register",
    "luma": "https://lu.ma/signup",
    "github": "https://github.com/signup",
    "devfolio": "https://devfolio.co/signup",
}


# ---------------------------------------------------------------------------
# Default escalation handler
# ---------------------------------------------------------------------------


async def terminal_escalation_handler(
    field_name: str, description: str, context: str
) -> str:
    """Default: print prompt, read from stdin."""
    print(f"\n\u26a0 Signup needs: {description}")
    print(f"  Field: {field_name}")
    print(f"  Context: {context}")
    value = input("  Value: ")
    return value


# ---------------------------------------------------------------------------
# Terminal tool schema
# ---------------------------------------------------------------------------

CONFIRM_SIGNUP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
            "description": "Whether signup completed successfully",
        },
        "confirmation_url": {
            "type": "string",
            "description": "URL of the signup confirmation page",
        },
        "error": {
            "type": "string",
            "description": "Error message if signup failed",
        },
    },
    "required": ["success"],
}

ESCALATE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "field_name": {
            "type": "string",
            "description": "Name of the field that is needed",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of what is needed",
        },
        "context": {
            "type": "string",
            "description": "Additional context (e.g. what form page, what the field label says)",
        },
    },
    "required": ["field_name", "description", "context"],
}

RECORD_PLATFORM_FIELD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "platform": {
            "type": "string",
            "description": "Platform name (e.g. 'devpost', 'ethglobal')",
        },
        "field_name": {
            "type": "string",
            "description": "Normalized field key (e.g. 'wallet_address')",
        },
        "label": {
            "type": "string",
            "description": "Human-readable field label as shown on the form",
        },
        "required": {
            "type": "boolean",
            "description": "Whether this field is required for signup",
        },
    },
    "required": ["platform", "field_name", "label", "required"],
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
    "mcp__signup__browser_create_session",
    "mcp__signup__browser_navigate",
    "mcp__signup__browser_click",
    "mcp__signup__browser_fill",
    "mcp__signup__browser_extract_text",
    "mcp__signup__browser_screenshot",
    "mcp__signup__browser_close_session",
    "mcp__signup__browser_save_session",
    "mcp__signup__browser_evaluate",
    "mcp__signup__browser_wait_for_navigation",
    "mcp__signup__browser_select_option",
    "mcp__signup__confirm_signup",
    "mcp__signup__resolve_field",
    "mcp__signup__escalate",
    "mcp__signup__record_platform_field",
    "mcp__signup__check_github_session",
    "mcp__signup__record_auth_success",
]


# ---------------------------------------------------------------------------
# Platform-specific system prompts
# ---------------------------------------------------------------------------

_DEVPOST_SIGNUP_PROMPT = """\
You are a signup agent. Create a new account on Devpost.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL.
3. Fill in the registration form:
   - First name and last name (from the member display_name)
   - Email address
   - Username
   - Password
4. Accept any terms of service checkboxes.
5. Click the "Create Account" or "Sign Up" button.
6. If email verification is required, call escalate with \
field_name="email_verification" and description="Check {email} for verification link from Devpost".
7. After verification, call browser_save_session to save the session state.
8. Call confirm_signup with success=true and the confirmation URL.
9. Call browser_close_session to clean up.

If signup fails at any step, take a screenshot, then call \
confirm_signup with success=false and describe the error."""

_ETHGLOBAL_SIGNUP_PROMPT = """\
You are a signup agent. Create a new account on ETHGlobal.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL.
3. Fill in the registration form with the provided email, username, and password.
4. Complete any additional required fields (use resolve_field to look up values).
5. Accept terms of service.
6. Click the signup/register button.
7. If email verification is required, call escalate with \
field_name="email_verification" and description="Check {email} for verification link from ETHGlobal".
8. After verification, call browser_save_session to save session state.
9. Call confirm_signup with success=true.
10. Call browser_close_session to clean up.

If signup fails, take a screenshot and call confirm_signup with success=false."""

_LUMA_SIGNUP_PROMPT = """\
You are a signup agent. Create a new account on Luma.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL.
3. Fill in the email field.
4. Luma may use magic link / email-based signup. If so, call escalate with \
field_name="email_verification" and description="Check {email} for sign-in link from Luma".
5. Fill in any profile fields (name, username, etc.) using the provided member info.
6. Set the password if prompted.
7. Call browser_save_session to save session state.
8. Call confirm_signup with success=true.
9. Call browser_close_session to clean up.

If signup fails, take a screenshot and call confirm_signup with success=false."""

_GITHUB_SIGNUP_PROMPT = """\
You are a signup agent. Create a new GitHub account.

## CRITICAL: GitHub signup is a multi-step wizard

Each field appears on its own page with a "Continue" button. You MUST click \
the Continue button after filling EACH field. Do NOT try to fill all fields \
at once — they are not all visible simultaneously.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL (https://github.com/signup).
3. Step-by-step — after each field, click the Continue button:
   a. Enter email address → click Continue
   b. Enter password → click Continue
   c. Enter username → click Continue
   d. Email preferences ("y" or "n") → click Continue
4. GitHub may show a CAPTCHA/puzzle area. IGNORE IT. Click the "Create account" \
button directly. Do NOT call escalate. Do NOT mention the CAPTCHA. Just click \
the submit button. The browser handles CAPTCHAs internally. If clicking "Create \
account" fails with a visible error message on the page, THEN take a screenshot \
and escalate. But try clicking first — always.
5. After account creation, GitHub sends a verification code to the email. Call escalate \
with field_name="email_verification" and \
description="Enter the verification code sent to {email} from GitHub".
6. Enter the verification code in the code input field.
7. Skip any onboarding/personalization screens — look for "Skip" or "Skip this step" links.
8. Call browser_save_session to save session state to the provided path.
9. Call confirm_signup with success=true.
10. Call browser_close_session to clean up.

## Navigation tips
- The Continue button may be labeled "Continue", "Next", or just be a green/blue button.
- Use browser_extract_text to read the current page and understand which step you're on.
- If a step fails or times out, take a screenshot and try again.
- The username might be rejected if taken — try appending numbers (e.g. vcn-bob → vcn-bob-42).

If signup fails, take a screenshot and call confirm_signup with success=false."""

_DEVFOLIO_SIGNUP_PROMPT = """\
You are a signup agent. Create a new account on Devfolio.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL.
3. Fill in the registration form with email, username, and password.
4. Complete any additional required profile fields using resolve_field.
5. Accept terms of service.
6. Click the signup button.
7. If email verification is required, call escalate with \
field_name="email_verification" and description="Check {email} for verification link from Devfolio".
8. After verification, call browser_save_session to save session state.
9. Call confirm_signup with success=true.
10. Call browser_close_session to clean up.

If signup fails, take a screenshot and call confirm_signup with success=false."""

_GENERIC_SIGNUP_PROMPT = """\
You are a signup agent. Create a new account on the platform.

## Steps

1. Call browser_create_session with the provided session_id.
2. Navigate to the signup URL.
3. Find and fill the registration form with the provided email, username, and password.
4. Fill any additional required fields using resolve_field to look up values.
5. Accept terms and conditions.
6. Submit the registration form.
7. If email verification is required, call escalate with \
field_name="email_verification" and description="Check email for verification link".
8. After verification, call browser_save_session to save session state.
9. Call confirm_signup with success=true.
10. Call browser_close_session to clean up.

If signup fails, take a screenshot and call confirm_signup with success=false."""

_OAUTH_PREFERENCE_INSTRUCTIONS = """

## OAuth preference

BEFORE filling any email/password form, look for OAuth buttons ('Sign up with GitHub', \
'Continue with GitHub', 'Sign up with Google'). If found, call check_github_session first. \
If your GitHub session is valid, CLICK THE OAUTH BUTTON. This bypasses CAPTCHAs entirely \
and is significantly faster. Only use the email/password form if no OAuth option is available \
or if your OAuth sessions are not valid. After completing signup via any method, call \
record_auth_success with the strategy you used (e.g. 'github_oauth' or 'email_password')."""

_FIELD_HANDLING_INSTRUCTIONS = """

## Handling form fields

When you encounter a form field you need to fill:
1. Call resolve_field with the field name and member_id to look up the value.
2. If the result is "unknown", call escalate with a description of what's needed.
3. After successfully filling any field, call record_platform_field to log it \
for future signups.

## CRITICAL RULE: Never escalate for CAPTCHAs

NEVER call escalate when you see a CAPTCHA, reCAPTCHA, OctoCaptcha, or puzzle. \
IGNORE the CAPTCHA element entirely. Click the submit/create/continue button \
directly. The browser solves CAPTCHAs internally — you do not need to interact \
with them. Only escalate if clicking submit produces a visible ERROR MESSAGE \
on the page (not just a CAPTCHA element existing).

Before every escalation, take a browser_screenshot and include the path in context."""

_PLATFORM_SIGNUP_PROMPTS: dict[str, str] = {
    "devpost": _DEVPOST_SIGNUP_PROMPT,
    "ethglobal": _ETHGLOBAL_SIGNUP_PROMPT,
    "luma": _LUMA_SIGNUP_PROMPT,
    "github": _GITHUB_SIGNUP_PROMPT,
    "devfolio": _DEVFOLIO_SIGNUP_PROMPT,
}


def _get_signup_system_prompt(platform: str) -> str:
    base = _PLATFORM_SIGNUP_PROMPTS.get(platform.lower(), _GENERIC_SIGNUP_PROMPT)
    return base + _OAUTH_PREFERENCE_INSTRUCTIONS + _FIELD_HANDLING_INSTRUCTIONS


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------


def _create_signup_server(
    session_manager: BrowserSessionManager,
    registry: AccountRegistry,
    capture: dict,
    chain: ResolverChain,
    roster: RosterStore | None = None,
    field_registry: PlatformFieldRegistry | None = None,
    escalation_handler: EscalationHandler | None = None,
    platform: str = "",
    member_id: str = "",
    auth_registry: AuthStrategyRegistry | None = None,
) -> dict:
    """Create an MCP server with browser tools + field tools + confirm_signup."""
    _handler = escalation_handler or terminal_escalation_handler

    async def confirm_signup(args: dict) -> dict:
        capture["data"] = args
        return _resp("Signup result recorded.")

    async def escalate(args: dict) -> dict:
        fname = args["field_name"]
        desc = args["description"]
        ctx = args.get("context", "")
        value = await _handler(fname, desc, ctx)
        # Write back to member profile
        if roster and member_id:
            member = roster.load_member(member_id)
            if member:
                member.attributes[fname] = value
                roster.save_member(member)
        # Record as a required platform field
        if field_registry and platform:
            field_registry.add_field(
                platform,
                PlatformField(
                    name=fname,
                    label=desc,
                    required=True,
                    discovered=date.today().isoformat(),
                ),
            )
        return _resp(value)

    async def record_platform_field(args: dict) -> dict:
        if field_registry is None:
            return _resp("No field registry available.")
        plat = args["platform"]
        field_registry.add_field(
            plat,
            PlatformField(
                name=args["field_name"],
                label=args["label"],
                required=args.get("required", False),
                discovered=date.today().isoformat(),
            ),
        )
        return _resp(f"Recorded field '{args['field_name']}' for {plat}.")

    # Build resolve_field tool from the resolver chain
    resolve_field_tool = make_resolve_field_tool(
        chain=chain,
        default_member_id=member_id,
        platform=platform,
        roster=roster or RosterStore(),
        registry=registry,
    )

    # --- OAuth tools ---

    async def check_github_session(args: dict) -> dict:
        accounts = registry.get_accounts_for_member(member_id)
        for acct in accounts:
            if acct.platform.value == "github" and acct.status == "active":
                if acct.session_state_path and Path(acct.session_state_path).exists():
                    return _resp(f"valid: {acct.username}")
        return _resp("no_session")

    async def record_auth_success(args: dict) -> dict:
        strategy_name = args["strategy_name"]
        if auth_registry is not None:
            auth_registry.record_success(platform, strategy_name, "signup")
            return _resp(f"Recorded auth success: {strategy_name}")
        return _resp("No auth registry available.")

    tools = [
        *_make_browser_tools(session_manager, account_registry=registry),
        SdkMcpTool(
            name="confirm_signup",
            description=(
                "Submit the signup result. Call this exactly once when "
                "signup is complete (success or failure)."
            ),
            input_schema=CONFIRM_SIGNUP_SCHEMA,
            handler=confirm_signup,
        ),
        resolve_field_tool,
        SdkMcpTool(
            name="escalate",
            description=(
                "Escalate to the user when a required field value is unknown "
                "or when email verification is needed. "
                "Prompts the user and returns their answer."
            ),
            input_schema=ESCALATE_SCHEMA,
            handler=escalate,
        ),
        SdkMcpTool(
            name="record_platform_field",
            description=(
                "Record a platform field that was encountered during signup, "
                "so it can be pre-filled in future signups."
            ),
            input_schema=RECORD_PLATFORM_FIELD_SCHEMA,
            handler=record_platform_field,
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
                "'email_password'). Call after signup completes successfully."
            ),
            input_schema=RECORD_AUTH_SUCCESS_SCHEMA,
            handler=record_auth_success,
        ),
    ]

    return create_sdk_mcp_server(name="signup", tools=tools)


# ---------------------------------------------------------------------------
# Core signup function
# ---------------------------------------------------------------------------


async def signup_account(
    member_id: str,
    platform: str,
    roster: RosterStore,
    registry: AccountRegistry,
    field_registry: PlatformFieldRegistry,
    chain: ResolverChain | None = None,
    escalation_handler: EscalationHandler = terminal_escalation_handler,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 50,
    headless: bool = False,  # default non-headless for signup (CAPTCHAs)
    cdp_endpoint: str | None = None,
    auth_registry: AuthStrategyRegistry | None = None,
) -> PlatformAccount | None:
    """Create a new platform account for a team member.

    1. Load member profile, validate email exists
    2. Generate credentials and create account
    3. Launch agent to fill signup form
    4. Handle email verification via escalation
    5. Save session state on success

    Args:
        member_id: The team member creating the account.
        platform: Platform to sign up on (devpost, ethglobal, etc.).
        roster: RosterStore for member profile lookups.
        registry: AccountRegistry for account persistence.
        field_registry: PlatformFieldRegistry for field discovery.
        escalation_handler: Callback for interactive escalation.
        model: Claude model ID.
        max_turns: Max agent turns.

    Returns:
        The created PlatformAccount, or None if signup failed.
    """
    # Validate platform
    signup_url = _SIGNUP_URLS.get(platform.lower())
    if signup_url is None:
        logger.error("No signup URL known for platform: %s", platform)
        return None

    # Load member profile
    member = roster.load_member(member_id)
    if member is None:
        logger.error("Member not found: %s", member_id)
        return None

    # Email is required for all signups
    email = member.attributes.get("email")
    if not email:
        logger.warning("No email found for %s — escalating", member_id)
        email = await escalation_handler(
            "email",
            f"Email address is required for {platform} signup",
            f"Member {member_id} has no email in their profile",
        )
        if not email:
            logger.error("No email provided for %s — cannot sign up", member_id)
            return None
        # Save it back
        member.attributes["email"] = email
        roster.save_member(member)

    # Username: for email-based login platforms, use email as username
    _EMAIL_LOGIN_PLATFORMS = {"devpost", "ethglobal", "luma", "devfolio"}
    if platform in _EMAIL_LOGIN_PLATFORMS:
        username = email
    else:
        username = member.attributes.get("username", member_id)

    # Create account with generated credentials
    # NOTE: saved to registry now so the agent can reference account_id,
    # but marked as "pending" until signup succeeds
    account = create_account_with_credentials(
        member_id=member_id,
        platform=platform,
        username=username,
        registry=registry,
    )
    account.status = "pending"
    registry.save_account(account)

    # Get the generated password from the vault for the agent
    password = registry.get_credential(account.account_id)
    if password is None:
        logger.error("Failed to retrieve generated password for %s", account.account_id)
        return None

    # Session save path
    sessions_dir = Path(user_data_dir("bob")) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    safe_id = account.account_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    session_state_path = str(sessions_dir / f"{safe_id}.json")

    # Use native engine for platforms with aggressive TLS detection (GitHub)
    # unless an explicit cdp_endpoint was provided (which implies OS-launched Chrome)
    os_launch = cdp_endpoint is None and platform in ("github",)
    engine = "native" if platform in ("github",) else "patchright"
    session_manager = BrowserSessionManager(
        headless=headless, cdp_endpoint=cdp_endpoint, os_launch=os_launch,
        engine_default=engine,
    )
    capture: dict = {}

    server = _create_signup_server(
        session_manager,
        registry,
        capture,
        chain=chain or create_default_chain(),
        roster=roster,
        field_registry=field_registry,
        escalation_handler=escalation_handler,
        platform=platform,
        member_id=member_id,
        auth_registry=auth_registry,
    )

    system_prompt = _get_signup_system_prompt(platform)

    # Augment system prompt with auth strategy info if registry available
    if auth_registry is not None:
        auth_info = auth_registry.get_auth_info(platform, member_id, registry)
        auth_section = build_auth_prompt_section(auth_info)
        if auth_section:
            system_prompt += auth_section

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        mcp_servers={"signup": server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    # Build attributes block
    attr_lines = "\n".join(f"  {k}: {v}" for k, v in member.attributes.items())

    # Build user message — credential goes here, NOT in system prompt
    user_message = (
        f"Create a new account on {platform}.\n\n"
        f"Session ID: signup-{member_id}-{platform}\n"
        f"Signup URL: {signup_url}\n"
        f"Email: {email}\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        f"Display name: {member.display_name}\n"
        f"Member ID: {member_id}\n"
        f"Session save path: {session_state_path}\n"
        f"\nMember attributes:\n{attr_lines}\n"
    )

    agent_session = AgentSession(
        f"signup:{member_id}:{platform}", max_turns=max_turns,
    )

    try:
        result = await run_agent(user_message, options, agent_session)

        if result.error:
            logger.error(
                "Signup for %s on %s failed: %s",
                member_id,
                platform,
                result.error,
            )
            return None
    finally:
        await session_manager.close_all()

    # Check result
    data = capture.get("data")
    if data is None:
        logger.warning(
            "Signup agent for %s on %s did not call confirm_signup",
            member_id,
            platform,
        )
        return None

    if not data.get("success"):
        logger.warning(
            "Signup failed for %s on %s: %s",
            member_id,
            platform,
            data.get("error", "unknown"),
        )
        return None

    # Update account with session state
    account.session_state_path = session_state_path
    account.status = "active"
    registry.save_account(account)

    logger.info(
        "Signup succeeded for %s on %s (tokens: %d/%d)",
        member_id,
        platform,
        result.input_tokens,
        result.output_tokens,
    )
    return account
