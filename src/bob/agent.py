"""Per-event investigation agent using claude-agent-sdk.

Each ambiguous hackathon gets its own agent query with MCP tools
to fetch pages, check links, and submit grounded verdicts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from claude_agent_sdk import ClaudeAgentOptions

from bob.models import Hackathon
from bob.telemetry import AgentSession, run_agent
from bob.tools.mcp import ResultCapture, create_investigation_server

logger = logging.getLogger(__name__)

# --- Agent system prompt ---

SYSTEM_PROMPT = """\
You are an event investigator. Your job is to determine whether a scraped event \
is a real hackathon and whether its details are accurate.

Rules:
- You MUST fetch the event page before making a judgment. Do not guess.
- A hackathon is a time-bounded event where participants build projects (software, \
hardware, or creative). Conferences, meetups, talks, socials, and pitch competitions \
are NOT hackathons.
- Every correction you submit MUST include the source_url you fetched and the \
extracted_text from that page that supports the correction.
- If the event page is unreachable or ambiguous, mark it valid with low confidence \
rather than guessing.
- Be strict: if it's clearly not a hackathon, mark it invalid.

Verify format and location carefully:
- The scraper often defaults to "virtual" when it can't determine format. Check the \
page for venue addresses, city names, campus/building references, or "in-person" \
language. If you find a physical location, correct format to "in-person".
- If the page says both online and in-person, correct to "hybrid".
- Correct the location field if the page shows a specific venue or city.
- IMPORTANT: Structured metadata (JSON-LD eventAttendanceMode, displayed_location) is \
frequently misconfigured by organizers. Many in-person hackathons have JSON-LD saying \
"OnlineEventAttendanceMode" or location "Online". Always read the actual description \
text and page content — if you see a venue name, building, room number, campus, or \
city in the description, trust that over the structured metadata.

Call submit_verdict when you have enough evidence. Do not fetch more than 3 pages \
unless the situation is genuinely ambiguous."""

# --- Data classes ---


@dataclass
class InvestigationResult:
    """Result of investigating a single hackathon event."""

    valid: bool
    confidence: float
    reasoning: str
    corrections: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    tool_rounds: int = 0


@dataclass
class TokenUsage:
    """Accumulates token usage across multiple investigations."""

    input_tokens: int = 0
    output_tokens: int = 0
    investigations: int = 0

    def add(self, result: InvestigationResult) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.investigations += 1

    def summary(self) -> str:
        total = self.input_tokens + self.output_tokens
        return (
            f"{self.investigations} investigations, "
            f"{self.input_tokens:,} input + {self.output_tokens:,} output = "
            f"{total:,} total tokens"
        )


# --- Core agent function ---


def _format_hackathon_message(h: Hackathon) -> str:
    """Format hackathon fields as a prompt for the agent."""
    parts = [
        f"Name: {h.name}",
        f"URL: {h.url}",
        f"Source: {h.source}",
        f"Format: {h.format.value}",
        f"Location: {h.location}",
    ]
    if h.start_date:
        parts.append(f"Start: {h.start_date.isoformat()}")
    if h.end_date:
        parts.append(f"End: {h.end_date.isoformat()}")
    if h.description:
        parts.append(f"Description: {h.description[:300]}")
    parts.append(f"Registration: {h.registration_status.value}")
    return "\n".join(parts)


_INVESTIGATION_TOOLS = [
    "mcp__tools__fetch_page",
    "mcp__tools__check_link",
    "mcp__tools__search_web",
    "mcp__tools__submit_verdict",
]


async def investigate(
    hackathon: Hackathon,
    *,
    model: str = "claude-haiku-4-5-20251001",
    max_rounds: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> InvestigationResult:
    """Run an investigation agent for a single hackathon.

    Args:
        hackathon: The event to investigate.
        model: Claude model ID.
        max_rounds: Maximum tool-use rounds.
        http_client: httpx async client (can be shared across investigations).
    """
    own_http = http_client is None
    if own_http:
        http_client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; hackathon-finder/0.1)"},
        )

    capture = ResultCapture()
    server = create_investigation_server(http_client, capture)

    session = AgentSession(
        f"investigate:{hackathon.event_id}", max_turns=max_rounds,
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        mcp_servers={"tools": server},
        allowed_tools=_INVESTIGATION_TOOLS,
        permission_mode="bypassPermissions",
        max_turns=max_rounds,
    )

    prompt = _format_hackathon_message(hackathon)

    try:
        result = await run_agent(prompt, options, session)

        if capture.data:
            inp = capture.data
            return InvestigationResult(
                valid=inp["valid"],
                confidence=inp["confidence"],
                reasoning=inp["reasoning"],
                corrections=inp.get("corrections", []),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_rounds=result.total_turns,
            )

        logger.warning(
            "Agent stopped without verdict for %s", hackathon.name,
        )
        return InvestigationResult(
            valid=False,
            confidence=0.3,
            reasoning="Agent stopped without verdict — flagged for manual review",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tool_rounds=result.total_turns,
        )
    finally:
        if own_http:
            await http_client.aclose()
