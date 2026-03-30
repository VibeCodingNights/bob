"""Team Composer — agent-based portfolio allocation across hackathon tracks.

Reads a Situation Room semantic map and roster, then runs a Claude agent
to produce a PortfolioPlan: which members play which tracks, in what roles,
with what personas.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from bob.roster.store import RosterStore
from bob.telemetry import AgentSession, run_agent
from bob.tools.map import (
    LIST_SECTIONS_TOOL,
    READ_SECTION_TOOL,
    execute_map_tool,
)
from bob.tools.mcp import ResultCapture, _resp, _wrap

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Composer runs several minutes; 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TeamMember:
    member_id: str
    role: str       # "presenter" | "builder" | "reviewer"
    reason: str     # why this person for this track


@dataclass
class TrackAssignment:
    track_name: str
    track_prize: str
    play_type: str          # "execution" | "moonshot" | "philosophical"
    ev_score: float         # expected value from Situation Room
    project_idea: str       # from strategy.md
    sponsor_apis: list[str]
    team: list[TeamMember]
    persona_ids: list[str]
    registration_platform: str


@dataclass
class PortfolioPlan:
    event_id: str
    event_name: str
    situation_map_root: str     # path to semantic map
    assignments: list[TrackAssignment]
    unassigned_tracks: list[str]
    budget_notes: str


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_COMPOSER_PROMPT = """\
You are a hackathon team composer. Your job is to allocate VCN roster members \
across hackathon tracks to maximize expected value.

## Portfolio allocation rules

Apply the portfolio approach described below:

**Execution plays (2-3 tracks).** Well-understood tech stack, clear sponsor \
alignment, high confidence in a polished submission. Cast members who present \
most confidently and whose skills align tightly with the track.

**Moonshots (1-2 tracks).** Novel idea, ambitious scope, higher variance. \
Grand-prize swings. Cast members who thrive under pressure and can improvise.

**Philosophical entry (1 track).** The project that embodies the organizer's \
reason for creating the hackathon. May not win a prize but gets the team \
invited back. Cast members with authentic interest in the theme.

Evaluate each track: `P(placement) x prize + reputation_value + learning_value`.

## Roster

{roster_yaml}

## Instructions

1. Use list_sections and read_section to explore the semantic map — read \
strategy.md, overview.md, and any tracks/*.md files.
2. For each track, decide: execution, moonshot, philosophical, or skip.
3. Assign roster members to tracks based on skill match, interests, \
presentation style, and availability.
4. Generate persona_ids as {{member_id}}-{{slugified-event-name}} for each assignment.
5. When done, call submit_portfolio with your complete plan.

IMPORTANT: You MUST call submit_portfolio exactly once with your final plan. \
Do not end without calling it."""

# ---------------------------------------------------------------------------
# Terminal tool schema
# ---------------------------------------------------------------------------

SUBMIT_PORTFOLIO_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string"},
        "event_name": {"type": "string"},
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "track_name": {"type": "string"},
                    "track_prize": {"type": "string"},
                    "play_type": {
                        "type": "string",
                        "enum": ["execution", "moonshot", "philosophical"],
                    },
                    "ev_score": {"type": "number"},
                    "project_idea": {"type": "string"},
                    "sponsor_apis": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "team": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "member_id": {"type": "string"},
                                "role": {
                                    "type": "string",
                                    "enum": ["presenter", "builder", "reviewer"],
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["member_id", "role", "reason"],
                        },
                    },
                    "persona_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "registration_platform": {"type": "string"},
                },
                "required": [
                    "track_name",
                    "track_prize",
                    "play_type",
                    "ev_score",
                    "project_idea",
                    "sponsor_apis",
                    "team",
                    "persona_ids",
                    "registration_platform",
                ],
            },
        },
        "unassigned_tracks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "budget_notes": {"type": "string"},
    },
    "required": [
        "event_id",
        "event_name",
        "assignments",
        "unassigned_tracks",
        "budget_notes",
    ],
}

# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = [
    "mcp__composer__read_section",
    "mcp__composer__list_sections",
    "mcp__composer__submit_portfolio",
]


def _create_composer_server(
    map_root: str,
    capture: ResultCapture,
) -> dict:
    """Create an MCP server with map-reading tools + submit_portfolio."""

    async def read_section(args: dict) -> dict:
        return _resp(execute_map_tool("read_section", args, map_root))

    async def list_sections(args: dict) -> dict:
        return _resp(execute_map_tool("list_sections", args, map_root))

    async def submit_portfolio(args: dict) -> dict:
        capture.data = args
        return _resp("Portfolio plan recorded.")

    tools = [
        _wrap(READ_SECTION_TOOL, read_section),
        _wrap(LIST_SECTIONS_TOOL, list_sections),
        SdkMcpTool(
            name="submit_portfolio",
            description=(
                "Submit your final portfolio plan. Call this exactly once "
                "after you have assigned roster members to tracks."
            ),
            input_schema=SUBMIT_PORTFOLIO_SCHEMA,
            handler=submit_portfolio,
        ),
    ]

    return create_sdk_mcp_server(name="composer", tools=tools)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------


def _parse_portfolio(data: dict, map_root: str) -> PortfolioPlan:
    """Convert the raw dict from submit_portfolio into a PortfolioPlan."""
    assignments = []
    for a in data.get("assignments", []):
        team = [
            TeamMember(
                member_id=m["member_id"],
                role=m["role"],
                reason=m["reason"],
            )
            for m in a.get("team", [])
        ]
        assignments.append(
            TrackAssignment(
                track_name=a["track_name"],
                track_prize=a.get("track_prize", ""),
                play_type=a["play_type"],
                ev_score=float(a.get("ev_score", 0.0)),
                project_idea=a.get("project_idea", ""),
                sponsor_apis=a.get("sponsor_apis", []),
                team=team,
                persona_ids=a.get("persona_ids", []),
                registration_platform=a.get("registration_platform", ""),
            )
        )

    return PortfolioPlan(
        event_id=data.get("event_id", ""),
        event_name=data.get("event_name", ""),
        situation_map_root=map_root,
        assignments=assignments,
        unassigned_tracks=data.get("unassigned_tracks", []),
        budget_notes=data.get("budget_notes", ""),
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def portfolio_to_dict(plan: PortfolioPlan) -> dict:
    """Convert a PortfolioPlan to a plain dict safe for yaml.safe_dump."""
    return dataclasses.asdict(plan)


def portfolio_from_dict(data: dict) -> PortfolioPlan:
    """Reconstruct a PortfolioPlan from a plain dict (loaded from YAML)."""
    return _parse_portfolio(
        data,
        data.get("situation_map_root", ""),
    )


# ---------------------------------------------------------------------------
# Core compose function
# ---------------------------------------------------------------------------


async def compose_teams(
    event_url: str,
    map_root: str,
    roster: RosterStore,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 20,
) -> PortfolioPlan:
    """Run the team composer agent.

    Reads the semantic map produced by the Situation Room and the roster
    store, then uses a Claude agent to allocate members across tracks.

    Args:
        event_url: The hackathon event URL (for context).
        map_root: Path to the Situation Room semantic map directory.
        roster: RosterStore instance with available members.
        model: Claude model ID.
        max_turns: Maximum agent turns.

    Returns:
        A PortfolioPlan with track assignments and team allocations.
    """
    # Serialize roster for the system prompt (sanitize enums for YAML)
    from bob.roster.store import _sanitize

    members = roster.list_members()
    roster_dicts = [_sanitize(dataclasses.asdict(m)) for m in members]
    roster_yaml = yaml.safe_dump(roster_dicts, sort_keys=False, allow_unicode=True)

    system_prompt = _COMPOSER_PROMPT.format(roster_yaml=roster_yaml)

    capture = ResultCapture()
    server = _create_composer_server(map_root, capture)

    session = AgentSession(f"composer:{event_url}", max_turns=max_turns)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        mcp_servers={"composer": server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    user_message = (
        f"Compose teams for this hackathon.\n"
        f"Event URL: {event_url}\n"
        f"Semantic map root: {map_root}\n\n"
        f"Start by calling list_sections to see all available research, "
        f"then read strategy.md and the track files."
    )

    result = await run_agent(user_message, options, session)

    if capture.data is None:
        logger.warning("Composer agent did not call submit_portfolio")
        return PortfolioPlan(
            event_id="",
            event_name="",
            situation_map_root=map_root,
            assignments=[],
            unassigned_tracks=[],
            budget_notes="Agent did not produce a plan.",
        )

    plan = _parse_portfolio(capture.data, map_root)
    logger.info(
        "Composer done: %d assignments, %d unassigned, tokens=%d/%d",
        len(plan.assignments),
        len(plan.unassigned_tracks),
        result.input_tokens,
        result.output_tokens,
    )
    return plan
