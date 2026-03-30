"""Registration orchestrator — browser-automated hackathon sign-ups.

Takes a PortfolioPlan from the Team Composer and registers each team
on the appropriate platform using stealth-browser MCP tools.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from bob.accounts.registry import AccountRegistry
from bob.composer import PortfolioPlan, TrackAssignment
from bob.telemetry import AgentSession, run_agent
from bob.personas.generator import compose_persona
from bob.platform_fields import PlatformField, PlatformFieldRegistry
from bob.resolvers import ResolverChain, create_default_chain, make_resolve_field_tool
from bob.roster.store import RosterStore
from bob.tools.browser import (
    BrowserSessionManager,
    _make_browser_tools,
)
from bob.tools.mcp import _resp

# Type alias for escalation handler callback
EscalationHandler = Callable[[str, str, str], Awaitable[str]]

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Registration phases run several minutes; 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")

# Max concurrent browser registrations (browser sessions are heavy)
_MAX_CONCURRENT = 2

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RegistrationTask:
    track_assignment: TrackAssignment
    account_id: str  # which account registers
    hackathon_url: str
    team_name: str
    team_description: str


@dataclass
class RegistrationResult:
    task: RegistrationTask
    success: bool
    confirmation_url: str = ""
    screenshot_path: str = ""  # proof of registration
    error: str = ""


@dataclass
class RegistrationReport:
    event_url: str
    results: list[RegistrationResult] = field(default_factory=list)
    total_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Terminal tool schema
# ---------------------------------------------------------------------------

CONFIRM_REGISTRATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
            "description": "Whether registration completed successfully",
        },
        "confirmation_url": {
            "type": "string",
            "description": "URL of the registration confirmation page",
        },
        "screenshot_path": {
            "type": "string",
            "description": "Path to the confirmation screenshot",
        },
        "error": {
            "type": "string",
            "description": "Error message if registration failed",
        },
    },
    "required": ["success"],
}


# ---------------------------------------------------------------------------
# Platform-specific system prompts
# ---------------------------------------------------------------------------

_DEVPOST_PROMPT = """\
You are a registration agent. Register a team on Devpost for a hackathon.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the hackathon URL.
3. Look for a "Register" or "Join Hackathon" button and click it.
4. If prompted to log in, the session should already have credentials — \
look for a logged-in state or use stored session cookies.
5. Fill in the team name and team description in the registration form.
6. Accept any rules or terms of service checkboxes.
7. Submit the registration.
8. Take a screenshot of the confirmation page as proof.
9. Call confirm_registration with success=true, the confirmation URL, and screenshot path.
10. Call browser_close_session to clean up.

If registration fails at any step, take a screenshot, then call \
confirm_registration with success=false and describe the error."""

_ETHGLOBAL_PROMPT = """\
You are a registration agent. Register a team on ETHGlobal for a hackathon.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the hackathon URL.
3. Look for a "Register" or "Apply" button and click it.
4. If prompted to log in, the session should already have credentials.
5. Fill in the team name and description if the form allows it.
6. Complete any additional required fields (project category, etc.).
7. Submit the registration.
8. Take a screenshot of the confirmation page as proof.
9. Call confirm_registration with success=true, the confirmation URL, and screenshot path.
10. Call browser_close_session to clean up.

If registration fails at any step, take a screenshot, then call \
confirm_registration with success=false and describe the error."""

_LUMA_PROMPT = """\
You are a registration agent. RSVP to an event on Luma.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the event URL.
3. Look for "Register" or "RSVP" button and click it.
4. Fill in any required RSVP fields (name, email, etc.).
5. Submit the RSVP form.
6. Take a screenshot of the confirmation page as proof.
7. Call confirm_registration with success=true, the confirmation URL, and screenshot path.
8. Call browser_close_session to clean up.

If registration fails at any step, take a screenshot, then call \
confirm_registration with success=false and describe the error."""

_GENERIC_PROMPT = """\
You are a registration agent. Register a team for a hackathon.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to the hackathon URL.
3. Find the registration or sign-up flow.
4. Fill in the team name and team description.
5. Complete any required fields and accept terms.
6. Submit the registration.
7. Take a screenshot of the confirmation page as proof.
8. Call confirm_registration with success=true, the confirmation URL, and screenshot path.
9. Call browser_close_session to clean up.

If registration fails at any step, take a screenshot, then call \
confirm_registration with success=false and describe the error."""

_FIELD_ESCALATION_INSTRUCTIONS = """

## Handling form fields

When you encounter a form field you need to fill:
1. Call resolve_field with the field name and member_id to look up the value.
2. If the result is "unknown", call escalate with a description of what's needed.
3. After successfully filling any field, call record_platform_field to log it \
for future registrations.

## IMPORTANT: Try first, escalate only after failure

For CAPTCHAs: DO NOT ESCALATE just because you see a CAPTCHA element. ALWAYS try \
to click the submit/continue button first. The stealth browser passes most CAPTCHAs \
automatically. Only escalate if submission FAILS and the page shows an error.

Before every escalation, take a browser_screenshot and include the path in context."""

_PLATFORM_PROMPTS: dict[str, str] = {
    "devpost": _DEVPOST_PROMPT,
    "ethglobal": _ETHGLOBAL_PROMPT,
    "luma": _LUMA_PROMPT,
}


def _get_system_prompt(platform: str) -> str:
    base = _PLATFORM_PROMPTS.get(platform.lower(), _GENERIC_PROMPT)
    return base + _FIELD_ESCALATION_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Default escalation handler
# ---------------------------------------------------------------------------


async def terminal_escalation_handler(
    field_name: str, description: str, context: str
) -> str:
    """Default: print prompt, display screenshot if present, read from stdin."""
    import re
    import subprocess
    import sys

    print(f"\n⚠ Escalation: {description}")
    print(f"  Field: {field_name}")

    # Extract and display screenshot path from context
    screenshot_match = re.search(r'Screenshot[:\s]+(\S+\.png)', context)
    if screenshot_match:
        screenshot_path = screenshot_match.group(1)
        # Try inline terminal rendering first (imgcat for iTerm2, then fallback)
        rendered = False
        for cmd in ["imgcat", "chafa", "timg"]:
            import shutil
            if shutil.which(cmd):
                try:
                    subprocess.run([cmd, screenshot_path], timeout=5)
                    rendered = True
                    break
                except Exception:
                    pass
        if not rendered:
            print(f"  📸 Screenshot: {screenshot_path}")

    if context:
        # Print context without the screenshot path (already shown above)
        ctx_display = re.sub(r'Screenshot:\s*\S+\.png\s*[—\-]*\s*', '', context).strip()
        if ctx_display:
            print(f"  Context: {ctx_display}")

    if "INTERACTIVE" in description.upper():
        print("\n  ⚡ This requires browser interaction (CAPTCHA, 2FA, etc.)")
        print("  The browser window should be visible. Complete the challenge there.")
        input("  Press Enter when done...")
        return "completed"

    value = input("  Value: ")
    return value


# ---------------------------------------------------------------------------
# MCP server factory for a single registration
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = [
    "mcp__registration__browser_create_session",
    "mcp__registration__browser_navigate",
    "mcp__registration__browser_click",
    "mcp__registration__browser_fill",
    "mcp__registration__browser_extract_text",
    "mcp__registration__browser_screenshot",
    "mcp__registration__browser_close_session",
    "mcp__registration__confirm_registration",
    "mcp__registration__resolve_field",
    "mcp__registration__escalate",
    "mcp__registration__record_platform_field",
]

# ---------------------------------------------------------------------------
# Escalation tool schemas
# ---------------------------------------------------------------------------

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
            "description": "Whether this field is required for registration",
        },
    },
    "required": ["platform", "field_name", "label", "required"],
}


def _create_registration_server(
    session_manager: BrowserSessionManager,
    registry: AccountRegistry,
    capture: dict,
    chain: ResolverChain,
    roster: RosterStore | None = None,
    field_registry: PlatformFieldRegistry | None = None,
    escalation_handler: EscalationHandler | None = None,
    platform: str = "",
    member_id: str = "",
) -> dict:
    """Create an MCP server with browser tools + escalation tools + confirm_registration."""
    _handler = escalation_handler or terminal_escalation_handler

    async def confirm_registration(args: dict) -> dict:
        capture["data"] = args
        return _resp("Registration result recorded.")

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

    tools = [
        *_make_browser_tools(session_manager, account_registry=registry),
        SdkMcpTool(
            name="confirm_registration",
            description=(
                "Submit the registration result. Call this exactly once when "
                "registration is complete (success or failure)."
            ),
            input_schema=CONFIRM_REGISTRATION_SCHEMA,
            handler=confirm_registration,
        ),
        resolve_field_tool,
        SdkMcpTool(
            name="escalate",
            description=(
                "Escalate to the user when a required field value is unknown. "
                "Prompts the user and returns their answer."
            ),
            input_schema=ESCALATE_SCHEMA,
            handler=escalate,
        ),
        SdkMcpTool(
            name="record_platform_field",
            description=(
                "Record a platform field that was encountered during registration, "
                "so it can be pre-filled in future registrations."
            ),
            input_schema=RECORD_PLATFORM_FIELD_SCHEMA,
            handler=record_platform_field,
        ),
    ]

    return create_sdk_mcp_server(name="registration", tools=tools)


# ---------------------------------------------------------------------------
# Build registration tasks from portfolio
# ---------------------------------------------------------------------------


def _build_registration_tasks(
    portfolio: PortfolioPlan,
    hackathon_url: str,
    registry: AccountRegistry,
) -> list[RegistrationTask]:
    """Create a RegistrationTask for each TrackAssignment in the portfolio."""
    tasks = []
    for assignment in portfolio.assignments:
        # Find the first account_id from the assigned team members
        account_id = ""
        for member in assignment.team:
            accounts = registry.get_accounts_for_member(member.member_id)
            if accounts:
                account_id = accounts[0].account_id
                break

        if not account_id:
            logger.warning(
                "No account found for track %s — skipping registration",
                assignment.track_name,
            )
            continue

        # Build team name/description from the assignment
        member_names = [m.member_id for m in assignment.team]
        team_name = f"VCN — {assignment.track_name}"
        team_description = (
            f"Project: {assignment.project_idea}\n"
            f"Track: {assignment.track_name} ({assignment.play_type})\n"
            f"Team: {', '.join(member_names)}\n"
            f"APIs: {', '.join(assignment.sponsor_apis)}"
        )

        tasks.append(
            RegistrationTask(
                track_assignment=assignment,
                account_id=account_id,
                hackathon_url=hackathon_url,
                team_name=team_name,
                team_description=team_description,
            )
        )

    return tasks


# ---------------------------------------------------------------------------
# Single registration runner
# ---------------------------------------------------------------------------


async def _run_registration(
    task: RegistrationTask,
    registry: AccountRegistry,
    model: str,
    max_turns: int,
    chain: ResolverChain | None = None,
    roster: RosterStore | None = None,
    field_registry: PlatformFieldRegistry | None = None,
    escalation_handler: EscalationHandler | None = None,
) -> tuple[RegistrationResult, int, int]:
    """Run a single registration with its own browser session."""
    session_manager = BrowserSessionManager()
    capture: dict = {}

    platform = task.track_assignment.registration_platform

    # Determine member_id for the registering account
    account = registry.get_account(task.account_id)
    member_id = account.member_id if account else ""

    server = _create_registration_server(
        session_manager,
        registry,
        capture,
        chain=chain or create_default_chain(),
        roster=roster,
        field_registry=field_registry,
        escalation_handler=escalation_handler,
        platform=platform,
        member_id=member_id,
    )

    system_prompt = _get_system_prompt(platform)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        mcp_servers={"registration": server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    # Build profile context from roster if available
    profile_block = ""
    account = registry.get_account(task.account_id)
    if roster and account:
        member = roster.load_member(account.member_id)
        if member:
            # Attributes block
            if member.attributes:
                attr_lines = "\n".join(
                    f"  {k}: {v}" for k, v in member.attributes.items()
                )
                profile_block += f"\nProfile data:\n{attr_lines}\n"

            top_skills = ", ".join(s.name for s in member.skills[:5]) or "N/A"
            interests_summary = ", ".join(member.interests[:5]) or "N/A"
            profile_block += (
                f"\nMember: {member.display_name}\n"
                f"Top skills: {top_skills}\n"
                f"Interests: {interests_summary}\n"
            )

            # Generate persona
            account_ids = [a.account_id for a in registry.get_accounts_for_member(member.member_id)]
            persona = compose_persona(
                member=member,
                account_ids=account_ids,
                event_name=task.team_name,
            )
            profile_block += (
                f"\nPersona bio (short): {persona.bio_short}\n"
                f"Persona bio (long): {persona.bio_long}\n"
            )

            if account.username:
                profile_block += f"\nAccount username: {account.username}\n"

    user_message = (
        f"Register for this hackathon.\n\n"
        f"Session ID: reg-{task.track_assignment.track_name}\n"
        f"Account ID: {task.account_id}\n"
        f"Member ID: {member_id}\n"
        f"Hackathon URL: {task.hackathon_url}\n"
        f"Team name: {task.team_name}\n"
        f"Team description: {task.team_description}\n"
        f"Platform: {platform}"
        f"{profile_block}"
    )

    session = AgentSession(
        f"registration:{task.track_assignment.track_name}", max_turns=max_turns,
    )

    try:
        result = await run_agent(user_message, options, session)

        if result.error:
            return (
                RegistrationResult(task=task, success=False, error=result.error),
                result.input_tokens,
                result.output_tokens,
            )
    finally:
        await session_manager.close_all()

    # Parse the capture result
    data = capture.get("data")
    if data is None:
        return (
            RegistrationResult(
                task=task,
                success=False,
                error="Agent did not call confirm_registration",
            ),
            result.input_tokens,
            result.output_tokens,
        )

    return (
        RegistrationResult(
            task=task,
            success=data.get("success", False),
            confirmation_url=data.get("confirmation_url", ""),
            screenshot_path=data.get("screenshot_path", ""),
            error=data.get("error", ""),
        ),
        result.input_tokens,
        result.output_tokens,
    )


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


async def register_teams(
    portfolio: PortfolioPlan,
    hackathon_url: str,
    registry: AccountRegistry,
    model: str = "claude-sonnet-4-6",
    max_turns_per_registration: int = 25,
    max_concurrent: int = _MAX_CONCURRENT,
    chain: ResolverChain | None = None,
    roster: RosterStore | None = None,
    field_registry: PlatformFieldRegistry | None = None,
    escalation_handler: EscalationHandler | None = None,
) -> RegistrationReport:
    """Register all teams from a PortfolioPlan concurrently.

    Runs up to _MAX_CONCURRENT browser registrations in parallel.
    Each registration gets its own agent, browser session, and tool set.

    Args:
        portfolio: The PortfolioPlan from the Team Composer.
        hackathon_url: The hackathon event URL.
        registry: AccountRegistry for account lookups and credentials.
        model: Claude model ID.
        max_turns_per_registration: Max agent turns per registration.
        max_concurrent: Max parallel browser sessions.
        roster: RosterStore for member profile lookups.
        field_registry: PlatformFieldRegistry for field discovery.
        escalation_handler: Callback for interactive escalation.

    Returns:
        RegistrationReport with results for each track.
    """
    report = RegistrationReport(event_url=hackathon_url)

    tasks = _build_registration_tasks(portfolio, hackathon_url, registry)
    if not tasks:
        logger.warning("No registration tasks to run")
        return report

    logger.info(
        "Starting %d registrations (max %d concurrent)",
        len(tasks),
        max_concurrent,
    )

    sem = asyncio.Semaphore(max_concurrent)

    _chain = chain or create_default_chain()

    async def _guarded_registration(
        task: RegistrationTask,
    ) -> tuple[RegistrationResult, int, int]:
        async with sem:
            return await _run_registration(
                task, registry, model, max_turns_per_registration,
                chain=_chain,
                roster=roster,
                field_registry=field_registry,
                escalation_handler=escalation_handler,
            )

    coros = [_guarded_registration(t) for t in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)

    for r in results:
        if isinstance(r, tuple):
            result, inp, out = r
            report.results.append(result)
            report.input_tokens += inp
            report.output_tokens += out
            report.total_turns += 1
        elif isinstance(r, BaseException):
            logger.warning("Registration task failed: %s", r)

    succeeded = sum(1 for r in report.results if r.success)
    logger.info(
        "Registration complete: %d/%d succeeded, tokens=%d/%d",
        succeeded,
        len(report.results),
        report.input_tokens,
        report.output_tokens,
    )

    return report
