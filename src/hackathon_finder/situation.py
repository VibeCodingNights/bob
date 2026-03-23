"""Situation Room agent — deep hackathon analysis and semantic map generation.

Analyzes a hackathon event, researches its ecosystem (tracks, sponsors,
judges, past winners), and produces a living semantic map that downstream
agents consume.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from hackathon_finder.models import Format, Hackathon
from hackathon_finder.tools.mcp import ResultCapture, create_situation_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Situation Room — a strategic intelligence agent that deeply analyzes \
hackathon events. Your job is to research the hackathon and produce a comprehensive \
semantic map that downstream agents will use to plan, build, and win.

## Your workflow — complete ALL phases

1. **Fetch the event page first.** Identify the hackathon name, dates, tracks/categories, \
themes, sponsors, judges, prizes, and submission requirements.

2. **Write overview.md** with event basics using write_section (owner: "situation-room"). \
Include name, dates, format, location, registration status, prize pool, and a summary.

3. **Research each track/category.** What does the sponsor want? What do judges value? \
What are the prizes? Write tracks/<track-name>.md for each track you identify. \
Fetch sponsor developer docs, API references, and GitHub repos for each track's sponsor. \
Every track file should include: prize amount, sponsor integration requirements, \
relevant APIs/SDKs, and what a winning project looks like.

4. **Research every sponsor.** Fetch their websites, GitHub profiles, recent blog posts, \
developer docs. Understand what product/API they are currently pushing. \
Write sponsors/<name>.md for each sponsor. Include their developer platform URL, \
key APIs/SDKs, what they want builders to use, and judge alignment.

5. **Research judges.** Fetch their GitHub profiles, published work, recent talks. \
Understand their background, what they evaluate, and what impresses them. \
Write judges/<name>.md for each judge you can find info on.

6. **Search for past editions and past winners.** Use search_web and fetch_devpost_winners \
to find what won previously. Write past/<edition>.md for each edition you find. \
Include winning project names, tech stacks, prize amounts, and what made them win.

7. **Synthesize strategy.md** — your strategic analysis grounded in everything above:
   - Which tracks to enter and why (ranked by expected value)
   - What to build for each recommended track
   - Technical approach and stack recommendations
   - Key risks and how to mitigate them
   - Sponsor alignment opportunities
   - Judge panel composition insights
   - Detailed execution timeline (hour-by-hour for the hackathon)
   - Pitch preparation: key talking points, anticipated judge questions

8. **Call submit_analysis** with a comprehensive summary when ALL phases are complete.

## Guidelines

- Always use owner "situation-room" when calling write_section or append_log.
- **Be thorough.** Do not skip phases or cut corners. Complete every phase above \
before calling submit_analysis. The quality of downstream agents depends entirely \
on the depth of your research.
- Fetch every sponsor's developer docs page. Fetch every judge's GitHub profile. \
Search for every past edition. Write a dedicated file for each.
- Use append_log to record notable findings as you go (path: "logs/research.md").
- Every claim in strategy.md should be grounded in something you fetched.
- Do NOT call submit_analysis until you have completed all 7 phases above."""

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SituationResult:
    """Result of analyzing a hackathon event."""

    event_id: str
    map_root: str
    sections_written: list[str] = field(default_factory=list)
    summary: str = ""
    tracks_found: int = 0
    confidence: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0


# ---------------------------------------------------------------------------
# Hackathon message formatting
# ---------------------------------------------------------------------------


def _format_hackathon_message(h: Hackathon) -> str:
    """Format hackathon fields as the initial user message."""
    parts = [
        "Analyze this hackathon event in depth.",
        "",
    ]
    if h.name:
        parts.append(f"Name: {h.name}")
    parts.append(f"URL: {h.url}")
    parts.append(f"Source: {h.source}")
    # Only include format/location if they're not defaults (i.e., actually known)
    if h.format != Format.VIRTUAL or h.location != "Online":
        parts.append(f"Format: {h.format.value}")
        parts.append(f"Location: {h.location}")
    if h.start_date:
        parts.append(f"Start: {h.start_date.isoformat()}")
    if h.end_date:
        parts.append(f"End: {h.end_date.isoformat()}")
    if h.organizer:
        parts.append(f"Organizer: {h.organizer}")
    if h.themes:
        parts.append(f"Themes: {', '.join(h.themes)}")
    if h.prize_amount:
        parts.append(f"Prize amount: {h.prize_amount}")
    if h.description:
        parts.append(f"Description: {h.description[:500]}")
    parts.append(f"Registration: {h.registration_status.value}")
    parts.append(f"Event ID: {h.event_id}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool name list for allowed_tools
# ---------------------------------------------------------------------------

_SITUATION_TOOLS = [
    "mcp__tools__fetch_page",
    "mcp__tools__check_link",
    "mcp__tools__search_web",
    "mcp__tools__fetch_github_user",
    "mcp__tools__fetch_github_repo",
    "mcp__tools__search_github_repos",
    "mcp__tools__fetch_devpost_winners",
    "mcp__tools__fetch_devpost_submission_reqs",
    "mcp__tools__write_section",
    "mcp__tools__read_section",
    "mcp__tools__list_sections",
    "mcp__tools__append_log",
    "mcp__tools__submit_analysis",
]

# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------


async def analyze(
    hackathon: Hackathon,
    *,
    map_root: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_tool_calls: int = 200,
    http_client: httpx.AsyncClient | None = None,
) -> SituationResult:
    """Run the Situation Room agent for a single hackathon.

    Args:
        hackathon: The event to analyze.
        map_root: Directory for the semantic map. Defaults to ./events/<event_id>/.
        model: Claude model ID.
        max_tool_calls: Safety limit (mapped to max_turns).
        http_client: httpx async client (injected for testing/sharing).
    """
    event_id = hackathon.event_id

    if map_root is None:
        map_root = os.path.join(".", "events", event_id)
    os.makedirs(map_root, exist_ok=True)

    own_http = http_client is None
    if own_http:
        http_client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; hackathon-finder/0.1)"},
        )

    capture = ResultCapture()
    server = create_situation_server(http_client, map_root, capture)

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        mcp_servers={"tools": server},
        allowed_tools=_SITUATION_TOOLS,
        permission_mode="bypassPermissions",
        max_turns=max_tool_calls,
    )

    prompt = _format_hackathon_message(hackathon)
    result = SituationResult(event_id=event_id, map_root=map_root)

    try:
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    if message.usage:
                        u = message.usage
                        result.input_tokens = (
                            u.get("input_tokens", 0)
                            + u.get("cache_creation_input_tokens", 0)
                            + u.get("cache_read_input_tokens", 0)
                        )
                        result.output_tokens = u.get("output_tokens", 0)
                    result.tool_calls = message.num_turns
        except BaseException as e:
            # CLIConnectionError, ExceptionGroup from TaskGroup, etc. — not fatal.
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            logger.debug("Query loop ended with %s: %s", type(e).__name__, e)

        # Extract results from capture (works regardless of how the loop ended)
        result.sections_written = capture.sections_written

        # Fallback: scan disk if capture missed sections
        if not result.sections_written and os.path.isdir(map_root):
            from pathlib import Path

            result.sections_written = sorted(
                str(p.relative_to(map_root))
                for p in Path(map_root).rglob("*.md")
                if p.name != "research.md"
            )

        if capture.data:
            inp = capture.data
            result.summary = inp["summary"]
            result.tracks_found = inp["tracks_found"]
            result.confidence = inp["confidence"]
        else:
            if result.sections_written:
                result.summary = (
                    f"Agent wrote {len(result.sections_written)} sections "
                    f"but did not call submit_analysis"
                )
                result.confidence = 0.5
            else:
                logger.warning(
                    "Situation Room stopped without submitting for %s",
                    hackathon.name,
                )
                result.summary = "Agent stopped without submitting analysis"
                result.confidence = 0.3

        return result
    finally:
        if own_http:
            await http_client.aclose()
