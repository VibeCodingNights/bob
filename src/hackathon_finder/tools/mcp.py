"""MCP tool registration bridge for claude-agent-sdk.

Wraps existing tool executors as SdkMcpTool instances and provides factory
functions to create in-process MCP servers for each agent type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

from hackathon_finder.tools.github import (
    FETCH_GITHUB_REPO_TOOL,
    FETCH_GITHUB_USER_TOOL,
    SEARCH_GITHUB_REPOS_TOOL,
    execute_fetch_github_repo,
    execute_fetch_github_user,
    execute_search_github_repos,
)
from hackathon_finder.tools.map import (
    APPEND_LOG_TOOL,
    LIST_SECTIONS_TOOL,
    READ_SECTION_TOOL,
    WRITE_SECTION_TOOL,
    execute_map_tool,
)
from hackathon_finder.tools.platforms import (
    FETCH_DEVPOST_SUBMISSION_REQS_TOOL,
    FETCH_DEVPOST_WINNERS_TOOL,
    execute_fetch_devpost_submission_reqs,
    execute_fetch_devpost_winners,
)
from hackathon_finder.tools.web import (
    CHECK_LINK_TOOL,
    FETCH_PAGE_TOOL,
    SEARCH_WEB_TOOL,
    execute_check_link,
    execute_fetch_page,
    execute_search_web,
)

# ---------------------------------------------------------------------------
# Result capture — shared mutable container for terminal tool data
# ---------------------------------------------------------------------------


@dataclass
class ResultCapture:
    """Mutable container to capture terminal tool invocations and side effects."""

    data: dict[str, Any] | None = None
    sections_written: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Terminal tool schemas (submit_verdict, submit_analysis)
# ---------------------------------------------------------------------------

SUBMIT_VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean", "description": "Whether this is a real hackathon"},
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in your verdict (0.0 to 1.0)",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of your reasoning",
        },
        "corrections": {
            "type": "array",
            "description": "Corrections to event details, each with evidence",
            "items": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
                            "location",
                            "start_date",
                            "end_date",
                            "format",
                            "registration_status",
                        ],
                    },
                    "value": {"type": "string", "description": "Corrected value"},
                    "source_url": {"type": "string", "description": "URL where you found this"},
                    "extracted_text": {
                        "type": "string",
                        "description": "Supporting text from the page",
                    },
                },
                "required": ["field", "value", "source_url", "extracted_text"],
            },
        },
    },
    "required": ["valid", "confidence", "reasoning"],
}

SUBMIT_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "High-level summary of the hackathon and strategic opportunities",
        },
        "tracks_found": {
            "type": "integer",
            "description": "Number of tracks/categories identified",
        },
        "sections_written": {
            "type": "integer",
            "description": "Number of map sections you wrote",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in completeness of your analysis",
        },
    },
    "required": ["summary", "tracks_found", "sections_written", "confidence"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(text: str) -> dict[str, Any]:
    """Format a plain-text result as an MCP tool response."""
    return {"content": [{"type": "text", "text": text}]}


def _wrap(tool_def: dict, handler) -> SdkMcpTool:
    """Create an SdkMcpTool from an existing tool definition dict and handler."""
    return SdkMcpTool(
        name=tool_def["name"],
        description=tool_def["description"],
        input_schema=tool_def["input_schema"],
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tool factory helpers (bind runtime dependencies via closure)
# ---------------------------------------------------------------------------


def _make_web_tools(http: httpx.AsyncClient) -> list[SdkMcpTool]:
    """Create web tools bound to an HTTP client."""

    async def fetch_page(args: dict) -> dict:
        return _resp(await execute_fetch_page(args["url"], http))

    async def check_link(args: dict) -> dict:
        return _resp(await execute_check_link(args["url"], http))

    async def search_web(args: dict) -> dict:
        return _resp(await execute_search_web(args["query"], http, args.get("max_results", 5)))

    return [
        _wrap(FETCH_PAGE_TOOL, fetch_page),
        _wrap(CHECK_LINK_TOOL, check_link),
        _wrap(SEARCH_WEB_TOOL, search_web),
    ]


def _make_github_tools(http: httpx.AsyncClient) -> list[SdkMcpTool]:
    """Create GitHub tools bound to an HTTP client."""

    async def fetch_user(args: dict) -> dict:
        return _resp(await execute_fetch_github_user(args["username"], http))

    async def fetch_repo(args: dict) -> dict:
        return _resp(await execute_fetch_github_repo(args["owner"], args["repo"], http))

    async def search_repos(args: dict) -> dict:
        return _resp(
            await execute_search_github_repos(args["query"], http, args.get("max_results", 5))
        )

    return [
        _wrap(FETCH_GITHUB_USER_TOOL, fetch_user),
        _wrap(FETCH_GITHUB_REPO_TOOL, fetch_repo),
        _wrap(SEARCH_GITHUB_REPOS_TOOL, search_repos),
    ]


def _make_platform_tools(http: httpx.AsyncClient) -> list[SdkMcpTool]:
    """Create platform tools bound to an HTTP client."""

    async def devpost_winners(args: dict) -> dict:
        return _resp(await execute_fetch_devpost_winners(args["hackathon_url"], http))

    async def devpost_reqs(args: dict) -> dict:
        return _resp(await execute_fetch_devpost_submission_reqs(args["hackathon_url"], http))

    return [
        _wrap(FETCH_DEVPOST_WINNERS_TOOL, devpost_winners),
        _wrap(FETCH_DEVPOST_SUBMISSION_REQS_TOOL, devpost_reqs),
    ]


def _make_map_tools(
    map_root: str, capture: ResultCapture | None = None
) -> list[SdkMcpTool]:
    """Create semantic-map tools bound to a map root directory."""

    async def write_section(args: dict) -> dict:
        try:
            result = execute_map_tool("write_section", args, map_root)
        except (KeyError, TypeError) as e:
            return _resp(f"Error: missing required argument: {e}")
        except Exception as e:
            return _resp(f"Error: {e}")
        if capture is not None and result.startswith("Written:"):
            path = args.get("path", "")
            if path and path not in capture.sections_written:
                capture.sections_written.append(path)
        return _resp(result)

    async def read_section(args: dict) -> dict:
        return _resp(execute_map_tool("read_section", args, map_root))

    async def list_sections(args: dict) -> dict:
        return _resp(execute_map_tool("list_sections", args, map_root))

    async def append_log(args: dict) -> dict:
        return _resp(execute_map_tool("append_log", args, map_root))

    return [
        _wrap(WRITE_SECTION_TOOL, write_section),
        _wrap(READ_SECTION_TOOL, read_section),
        _wrap(LIST_SECTIONS_TOOL, list_sections),
        _wrap(APPEND_LOG_TOOL, append_log),
    ]


# ---------------------------------------------------------------------------
# Server factories
# ---------------------------------------------------------------------------


def create_investigation_server(
    http: httpx.AsyncClient,
    capture: ResultCapture,
) -> dict:
    """Create an MCP server for the investigation agent.

    Tools: fetch_page, check_link, search_web, submit_verdict.
    """

    async def submit_verdict(args: dict) -> dict:
        capture.data = args
        return _resp("Verdict recorded.")

    tools = [
        *_make_web_tools(http),
        SdkMcpTool(
            name="submit_verdict",
            description=(
                "Submit your final verdict on whether this event is a valid hackathon. "
                "Call this exactly once when you have enough evidence."
            ),
            input_schema=SUBMIT_VERDICT_SCHEMA,
            handler=submit_verdict,
        ),
    ]

    return create_sdk_mcp_server(name="investigation", tools=tools)


def create_situation_server(
    http: httpx.AsyncClient,
    map_root: str,
    capture: ResultCapture,
) -> dict:
    """Create an MCP server for the Situation Room agent.

    Tools: web, GitHub, platform, map, submit_analysis.
    """

    async def submit_analysis(args: dict) -> dict:
        capture.data = args
        return _resp("Analysis submitted.")

    tools = [
        *_make_web_tools(http),
        *_make_github_tools(http),
        *_make_platform_tools(http),
        *_make_map_tools(map_root, capture),
        SdkMcpTool(
            name="submit_analysis",
            description=(
                "Submit your final analysis summary. Call this ONLY after you have "
                "completed all research phases: overview, tracks, sponsors, judges, "
                "past winners, and strategy."
            ),
            input_schema=SUBMIT_ANALYSIS_SCHEMA,
            handler=submit_analysis,
        ),
    ]

    return create_sdk_mcp_server(name="situation-room", tools=tools)
