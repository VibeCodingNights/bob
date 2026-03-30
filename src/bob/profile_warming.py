"""GitHub profile warming agent — fills profile fields to make accounts look real.

Launches a Claude agent that navigates to GitHub settings/profile, fills in
display name, bio, location, company, and website based on the member's
persona, then saves the profile.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from bob.accounts.registry import AccountRegistry
from bob.personas.generator import compose_persona
from bob.roster.store import RosterStore
from bob.telemetry import AgentSession, run_agent
from bob.tools.browser import BrowserSessionManager, _make_browser_tools
from bob.tools.mcp import _resp

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Profile warming should be quick, but 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")


# ---------------------------------------------------------------------------
# Terminal tool schema
# ---------------------------------------------------------------------------

CONFIRM_WARMING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
            "description": "Whether profile warming completed successfully",
        },
        "error": {
            "type": "string",
            "description": "Error message if warming failed",
        },
    },
    "required": ["success"],
}


# ---------------------------------------------------------------------------
# Allowed tools list
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = [
    "mcp__warming__browser_create_session",
    "mcp__warming__browser_navigate",
    "mcp__warming__browser_click",
    "mcp__warming__browser_fill",
    "mcp__warming__browser_extract_text",
    "mcp__warming__browser_screenshot",
    "mcp__warming__browser_close_session",
    "mcp__warming__browser_save_session",
    "mcp__warming__browser_evaluate",
    "mcp__warming__browser_wait_for_navigation",
    "mcp__warming__browser_select_option",
    "mcp__warming__confirm_warming",
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_WARMING_SYSTEM_PROMPT = """\
You are updating a GitHub profile to make it look like a real developer account.

## Steps

1. Call browser_create_session with the provided session_id and account_id.
2. Navigate to https://github.com/settings/profile.
3. Fill in the profile fields with the provided information:
   - Name (display name)
   - Bio (keep it natural and developer-focused)
   - Company
   - Location (if provided)
   - Website (if provided)
4. Click the "Update profile" button to save.
5. Take a screenshot to verify the profile was saved.
6. Call browser_save_session to persist the session state.
7. Call confirm_warming with success=true.
8. Call browser_close_session to clean up.

If any step fails, take a screenshot, then call confirm_warming with \
success=false and describe the error.

IMPORTANT: Do NOT mention AI, agents, automation, or bots in any profile field. \
The bio should read like a real developer wrote it."""


# ---------------------------------------------------------------------------
# Bio generator
# ---------------------------------------------------------------------------


def _generate_bio(member, persona) -> str:
    """Generate a natural-sounding developer bio from member profile.

    Avoids anything that sounds like AI/bot. Keeps it short and human.
    """
    skills = [s.name for s in member.skills[:3]]
    interests = member.interests[:2]

    parts = []
    if skills:
        parts.append(f"Building with {', '.join(skills)}.")
    if interests:
        parts.append(f"Interested in {' and '.join(interests)}.")

    bio = " ".join(parts)

    # Fall back to persona bio_short if we couldn't build one, but strip
    # any "Display Name —" prefix that compose_persona adds
    if not bio and persona.bio_short:
        bio = persona.bio_short
        if " — " in bio:
            bio = bio.split(" — ", 1)[1]

    return bio[:160]  # GitHub bio limit


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------


def _create_warming_server(
    session_manager: BrowserSessionManager,
    registry: AccountRegistry,
    capture: dict,
) -> dict:
    """Create an MCP server with browser tools + confirm_warming."""

    async def confirm_warming(args: dict) -> dict:
        capture["data"] = args
        return _resp("Warming result recorded.")

    tools = [
        *_make_browser_tools(session_manager, account_registry=registry),
        SdkMcpTool(
            name="confirm_warming",
            description=(
                "Submit the profile warming result. Call this exactly once "
                "when warming is complete (success or failure)."
            ),
            input_schema=CONFIRM_WARMING_SCHEMA,
            handler=confirm_warming,
        ),
    ]

    return create_sdk_mcp_server(name="warming", tools=tools)


# ---------------------------------------------------------------------------
# Core warming function
# ---------------------------------------------------------------------------


async def warm_github_profile(
    account_id: str,
    roster: RosterStore,
    registry: AccountRegistry,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 15,
) -> bool:
    """Fill out a GitHub profile to make the account look real.

    1. Load the member profile and generate a persona
    2. Open GitHub settings/profile in stealth browser (using account's session)
    3. Fill: Name, Bio, Location, Company, Website
    4. Save profile
    5. Return True on success

    Args:
        account_id: The GitHub account to warm.
        roster: RosterStore for member profile lookups.
        registry: AccountRegistry for account/session lookups.
        model: Claude model ID.
        max_turns: Max agent turns.

    Returns:
        True if profile warming succeeded.
    """
    # Load account
    account = registry.get_account(account_id)
    if account is None:
        logger.error("Account not found: %s", account_id)
        return False

    if account.platform.value != "github":
        logger.error("Account %s is not a GitHub account (platform=%s)", account_id, account.platform.value)
        return False

    # Verify session exists
    if not account.session_state_path or not Path(account.session_state_path).exists():
        logger.error(
            "No valid session for %s — log in first with `bob login %s`",
            account_id,
            account_id,
        )
        return False

    # Load member profile
    member = roster.load_member(account.member_id)
    if member is None:
        logger.error("Member not found: %s", account.member_id)
        return False

    # Generate persona for bio content
    persona = compose_persona(
        member=member,
        account_ids=[account_id],
        event_name="github-profile",
    )

    # Build profile data
    bio = _generate_bio(member, persona)
    location = member.attributes.get("location", "")
    website = member.attributes.get("website", "")

    session_manager = BrowserSessionManager(headless=False)
    capture: dict = {}

    server = _create_warming_server(session_manager, registry, capture)

    options = ClaudeAgentOptions(
        system_prompt=_WARMING_SYSTEM_PROMPT,
        model=model,
        mcp_servers={"warming": server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    # Build profile info for the agent
    profile_lines = [
        f"Name: {member.display_name}",
        f"Bio: {bio}",
        f"Company: VCN",
    ]
    if location:
        profile_lines.append(f"Location: {location}")
    if website:
        profile_lines.append(f"Website: {website}")

    user_message = (
        f"Update the GitHub profile for account {account_id}.\n\n"
        f"Session ID: warming-{account_id}\n"
        f"Account ID: {account_id}\n"
        f"Session save path: {account.session_state_path}\n"
        f"\nProfile information to set:\n"
        + "\n".join(f"  {line}" for line in profile_lines)
        + "\n"
    )

    agent_session = AgentSession(f"warming:{account_id}", max_turns=max_turns)

    try:
        result = await run_agent(user_message, options, agent_session)

        if result.error:
            logger.warning(
                "Profile warming for %s failed: %s",
                account_id,
                result.error,
            )
            return False
    finally:
        await session_manager.close_all()

    # Check result
    data = capture.get("data")
    if data is None:
        logger.warning(
            "Warming agent for %s did not call confirm_warming",
            account_id,
        )
        return False

    if not data.get("success"):
        logger.warning(
            "Profile warming failed for %s: %s",
            account_id,
            data.get("error", "unknown"),
        )
        return False

    logger.info(
        "Profile warming succeeded for %s (tokens: %d/%d)",
        account_id,
        result.input_tokens,
        result.output_tokens,
    )
    return True
