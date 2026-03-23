"""Situation Room — orchestrated multi-phase hackathon analysis.

Decomposes deep hackathon research into focused agent phases:
overview → tracks → sponsors → judges → past → strategy synthesis.
Each phase gets its own agent, budget, and tool set.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from hackathon_finder.models import Format, Hackathon
from hackathon_finder.tools.mcp import (
    ResultCapture,
    _make_github_tools,
    _make_map_tools,
    _make_platform_tools,
    _make_web_tools,
    create_sdk_mcp_server,
)

logger = logging.getLogger(__name__)

# SDK closes stdin after CLAUDE_CODE_STREAM_CLOSE_TIMEOUT (ms), killing MCP
# tool calls.  Phases run 2-5 min; 10 min is safe.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")

# ---------------------------------------------------------------------------
# Phase-specific system prompts
# ---------------------------------------------------------------------------

OVERVIEW_PROMPT = """\
You are a hackathon analyst. Fetch the event page and extract structured information.

## Your task

1. Fetch the event URL provided.
2. Identify: event name, dates, format (virtual/in-person/hybrid), location, \
registration status, prize pool, tracks/categories, sponsors, and judges.
3. Call write_section to create overview.md with:
   - YAML frontmatter containing structured data (see format below)
   - Body with a clear event summary

## Required frontmatter format

The frontmatter MUST include these arrays so downstream agents know what to research:

```yaml
name: "Event Name"
dates: "June 1-3, 2026"
format: "in-person"
location: "Prague, Czech Republic"
prize_pool: "$500,000"
tracks:
  - name: "Track Name"
    sponsor: "Sponsor Name"
    prize: "$10,000"
    description: "Brief description"
  - name: "Another Track"
    sponsor: "Another Sponsor"
    prize: "$5,000"
    description: "Brief description"
sponsors:
  - name: "Sponsor Name"
    url: "https://sponsor.com"
  - name: "Another Sponsor"
    url: "https://another.com"
judges:
  - name: "Judge Name"
    url: "https://github.com/judge"
  - name: "Another Judge"
    url: "https://twitter.com/judge"
```

If you can't find tracks, sponsors, or judges, use empty arrays.
Use owner "situation-room" for write_section.
IMPORTANT: Use path "overview.md" exactly — no subdirectories, no event name prefix.
Be thorough on the event page — follow links to tracks, rules, and about pages."""

TRACK_PROMPT = """\
You are a hackathon track researcher. Research a single hackathon track in depth.

## Your task

1. Fetch the sponsor's website and developer docs.
2. Search for the sponsor's GitHub repos and recent releases.
3. Understand what API/SDK the sponsor wants builders to use.
4. Write tracks/<track-name>.md with:
   - Prize amount and requirements
   - Sponsor's key APIs/SDKs and developer docs URL
   - What a winning project looks like for this track
   - Recent features the sponsor is pushing (check their blog/changelog)

Use owner "situation-room" for write_section.
Use kebab-case for the filename (e.g., tracks/defi-lending.md)."""

SPONSOR_PROMPT = """\
You are a hackathon sponsor researcher. Research a single sponsor in depth.

## Your task

1. Fetch the sponsor's website and developer platform.
2. Fetch their GitHub profile and popular repos.
3. Check recent blog posts or changelog for what they're currently pushing.
4. Write sponsors/<name>.md with:
   - Developer platform URL
   - Key APIs/SDKs and what they do
   - What the sponsor wants builders to use (recent pushes)
   - Integration requirements for hackathon projects

Use owner "situation-room" for write_section.
Use kebab-case for the filename (e.g., sponsors/uniswap.md)."""

JUDGE_PROMPT = """\
You are a hackathon judge researcher. Research a single judge.

## Your task

1. Fetch the judge's profile URL (GitHub, Twitter/X, LinkedIn).
2. Search for their recent talks, publications, or projects.
3. Write judges/<name>.md with:
   - Professional background and current role
   - Technical interests and expertise
   - What they likely evaluate (inferred from background)
   - Anticipated questions they might ask

Use owner "situation-room" for write_section.
Use kebab-case for the filename (e.g., judges/vitalik-buterin.md)."""

PAST_PROMPT = """\
You are a hackathon historian. Research past editions and winners.

## Your task

1. Search the web for past editions of this hackathon.
2. Use fetch_devpost_winners if the hackathon is on Devpost.
3. For each past edition you find, write past/<edition>.md with:
   - Winning project names and descriptions
   - Tech stacks used by winners
   - Prize amounts won
   - Patterns: what made winners stand out

If you can't find past editions, write past/no-history.md noting that.
Use owner "situation-room" for write_section."""

STRATEGY_PROMPT = """\
You are a hackathon strategist. Synthesize all research into an actionable strategy.

## Context

You have access to a semantic map with research on this hackathon's tracks, \
sponsors, judges, and past winners. Use list_sections and read_section to \
review everything that's been written.

{priors}

## Your task

1. Read ALL sections in the map using list_sections, then read_section for each.
2. Write strategy.md with:

### Track Rankings
Rank every track by expected value. For each:
- Track name and prize
- Why this track is worth entering (or not)
- What to build — a specific, concrete project idea
- Which sponsor APIs/SDKs to integrate
- Estimated difficulty and risk

### Sponsor Alignment
- Which sponsors are pushing new features (opportunity for attention)
- Integration strategies that maximize sponsor impression

### Judge Briefing
- Panel composition and what they collectively value
- Anticipated questions per track
- Demo talking points calibrated to this panel

### Execution Plan
- Recommended tracks to enter (ranked)
- Hour-by-hour timeline for the hackathon duration
- Feature freeze point and submission preparation plan

### Pitch Preparation
- Opening line (3 seconds: what is this?)
- Hook (30 seconds: why should judges care?)
- Demo flow (90 seconds: what to show)
- Landing (30 seconds: where does this go?)

Use owner "situation-room" for write_section.
Ground every recommendation in specific research from the map."""

# ---------------------------------------------------------------------------
# Phase tool mapping
# ---------------------------------------------------------------------------

_PHASE_TOOLS: dict[str, list[str]] = {
    "overview": [
        "mcp__tools__fetch_page",
        "mcp__tools__check_link",
        "mcp__tools__search_web",
        "mcp__tools__write_section",
    ],
    "track": [
        "mcp__tools__fetch_page",
        "mcp__tools__check_link",
        "mcp__tools__search_web",
        "mcp__tools__fetch_github_repo",
        "mcp__tools__search_github_repos",
        "mcp__tools__write_section",
    ],
    "sponsor": [
        "mcp__tools__fetch_page",
        "mcp__tools__check_link",
        "mcp__tools__search_web",
        "mcp__tools__fetch_github_user",
        "mcp__tools__fetch_github_repo",
        "mcp__tools__write_section",
    ],
    "judge": [
        "mcp__tools__fetch_page",
        "mcp__tools__search_web",
        "mcp__tools__fetch_github_user",
        "mcp__tools__write_section",
    ],
    "past": [
        "mcp__tools__fetch_page",
        "mcp__tools__search_web",
        "mcp__tools__fetch_devpost_winners",
        "mcp__tools__write_section",
    ],
    "strategy": [
        "mcp__tools__read_section",
        "mcp__tools__list_sections",
        "mcp__tools__write_section",
    ],
}

# ---------------------------------------------------------------------------
# Phase budgets (max turns per phase type)
# ---------------------------------------------------------------------------

_PHASE_BUDGETS: dict[str, int] = {
    "overview": 15,
    "track": 10,
    "sponsor": 8,
    "judge": 6,
    "past": 10,
    "strategy": 20,
}

# Max concurrent agent subprocesses
_MAX_CONCURRENT = 3

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PhaseResult:
    """Result of running a single orchestrator phase."""

    phase: str
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    sections_written: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class OverviewData:
    """Structured data extracted from overview.md frontmatter."""

    name: str = ""
    tracks: list[dict] = field(default_factory=list)
    sponsors: list[dict] = field(default_factory=list)
    judges: list[dict] = field(default_factory=list)


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
    total_turns: int = 0


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
# Phase server factory
# ---------------------------------------------------------------------------


def _create_phase_server(
    phase: str,
    http: httpx.AsyncClient,
    map_root: str,
    capture: ResultCapture,
) -> dict:
    """Create an MCP server with tools appropriate for a specific phase."""
    tools = []

    tool_names = _PHASE_TOOLS.get(phase, [])

    # Include tool groups based on what this phase needs
    if any("fetch_page" in t or "check_link" in t or "search_web" in t for t in tool_names):
        tools.extend(_make_web_tools(http))
    if any("github" in t for t in tool_names):
        tools.extend(_make_github_tools(http))
    if any("devpost" in t for t in tool_names):
        tools.extend(_make_platform_tools(http))
    if any("section" in t or "log" in t for t in tool_names):
        tools.extend(_make_map_tools(map_root, capture))

    return create_sdk_mcp_server(name=f"situation-{phase}", tools=tools)


# ---------------------------------------------------------------------------
# Phase runner
# ---------------------------------------------------------------------------


async def _run_phase(
    phase_name: str,
    system_prompt: str,
    user_message: str,
    *,
    http_client: httpx.AsyncClient,
    map_root: str,
    model: str = "claude-sonnet-4-6",
    max_turns: int | None = None,
) -> PhaseResult:
    """Run a single agent phase with focused tools and budget."""
    if max_turns is None:
        max_turns = _PHASE_BUDGETS.get(phase_name, 10)

    capture = ResultCapture()
    server = _create_phase_server(phase_name, http_client, map_root, capture)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        mcp_servers={"tools": server},
        allowed_tools=_PHASE_TOOLS.get(phase_name, []),
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "ToolSearch", "Agent",
            "NotebookEdit",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    result = PhaseResult(phase=phase_name)

    try:
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        logger.debug("[%s] tool_use: %s", phase_name, block.name)
            if isinstance(message, ResultMessage):
                logger.debug(
                    "[%s] result: turns=%d error=%s",
                    phase_name, message.num_turns, message.is_error,
                )
                if message.usage:
                    u = message.usage
                    result.input_tokens += (
                        u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0)
                    )
                    result.output_tokens += u.get("output_tokens", 0)
                result.turns = message.num_turns
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        logger.debug("Phase %s ended with %s: %s", phase_name, type(e).__name__, e)
        result.error = str(e)

    result.sections_written = capture.sections_written
    return result


# ---------------------------------------------------------------------------
# Overview parsing
# ---------------------------------------------------------------------------


def _parse_overview(map_root: str) -> OverviewData:
    """Parse overview.md YAML frontmatter to extract tracks, sponsors, judges."""
    overview_path = os.path.join(map_root, "overview.md")
    if not os.path.exists(overview_path):
        # Fallback: search recursively for overview.md
        for p in Path(map_root).rglob("overview.md"):
            overview_path = str(p)
            break
        else:
            return OverviewData()

    text = Path(overview_path).read_text()

    # Extract YAML frontmatter between --- markers
    fm: dict = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                logger.warning("Failed to parse overview.md frontmatter")

    return OverviewData(
        name=fm.get("name", ""),
        tracks=fm.get("tracks", []) or [],
        sponsors=fm.get("sponsors", []) or [],
        judges=fm.get("judges", []) or [],
    )


# ---------------------------------------------------------------------------
# Priors loading
# ---------------------------------------------------------------------------


def _load_priors() -> str:
    """Load hackathon priors from knowledge/priors.md if it exists."""
    priors_path = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge", "priors.md")
    priors_path = os.path.normpath(priors_path)
    if os.path.exists(priors_path):
        content = Path(priors_path).read_text()
        return f"\n## Prior knowledge from past hackathons\n\n{content}\n"
    return ""


# ---------------------------------------------------------------------------
# Map reading for strategy synthesis
# ---------------------------------------------------------------------------


def _read_map_for_strategy(map_root: str) -> str:
    """Read all map sections as context for the strategy agent."""
    parts = []
    root = Path(map_root)
    if not root.is_dir():
        return "(No research sections found)"

    for md_file in sorted(root.rglob("*.md")):
        if md_file.name == "research.md":
            continue
        rel = str(md_file.relative_to(root))
        content = md_file.read_text()
        parts.append(f"### {rel}\n\n{content}")

    if not parts:
        return "(No research sections found)"
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Result computation
# ---------------------------------------------------------------------------


def _compute_confidence(phases: list[PhaseResult], overview: OverviewData) -> float:
    """Compute confidence based on phase completion."""
    if not phases:
        return 0.3

    completed = sum(1 for p in phases if p.error is None)
    total = len(phases)
    base = completed / total

    # Boost if strategy phase completed
    if any(p.phase == "strategy" and p.error is None for p in phases):
        base = min(base + 0.1, 1.0)

    return round(base, 2)


def _compute_summary(
    phases: list[PhaseResult],
    overview: OverviewData,
    result: SituationResult,
) -> str:
    """Generate summary from phase results."""
    parts = []
    if overview.tracks:
        parts.append(f"{len(overview.tracks)} tracks identified")
    completed = sum(1 for p in phases if p.error is None)
    parts.append(f"{completed}/{len(phases)} phases completed")
    parts.append(f"{len(result.sections_written)} sections written")
    failed = [p for p in phases if p.error]
    if failed:
        parts.append(f"{len(failed)} phases had errors")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


async def analyze(
    hackathon: Hackathon,
    *,
    map_root: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_tool_calls: int = 200,
    http_client: httpx.AsyncClient | None = None,
) -> SituationResult:
    """Run the orchestrated Situation Room pipeline.

    Phases:
        1. Overview — fetch event page, extract structure
        2. Tracks — concurrent per-track research
        3. Sponsors — concurrent per-sponsor research
        4. Judges — concurrent per-judge research
        5. Past — search for past editions and winners
        6. Strategy — synthesize all research into actionable strategy

    Args:
        hackathon: The event to analyze.
        map_root: Directory for the semantic map. Defaults to ./events/<event_id>/.
        model: Claude model ID.
        max_tool_calls: Total budget (informational — phases have individual budgets).
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

    result = SituationResult(event_id=event_id, map_root=map_root)
    all_phases: list[PhaseResult] = []

    try:
        # Phase 1: Overview
        logger.info("Phase 1/6: Overview")
        overview_phase = await _run_phase(
            "overview",
            OVERVIEW_PROMPT,
            _format_hackathon_message(hackathon),
            http_client=http_client,
            map_root=map_root,
            model=model,
        )
        all_phases.append(overview_phase)

        # Parse overview to drive fan-out
        overview = _parse_overview(map_root)
        logger.info(
            "Overview: %d tracks, %d sponsors, %d judges",
            len(overview.tracks),
            len(overview.sponsors),
            len(overview.judges),
        )

        # Phase 2-5: Research (concurrent with semaphore)
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _guarded_phase(
            phase_name: str,
            prompt: str,
            message: str,
            **kwargs,
        ) -> PhaseResult:
            async with sem:
                return await _run_phase(
                    phase_name,
                    prompt,
                    message,
                    http_client=http_client,
                    map_root=map_root,
                    model=model,
                    **kwargs,
                )

        research_tasks = []

        # Tracks
        for track in overview.tracks:
            name = track.get("name", "unknown")
            sponsor = track.get("sponsor", "")
            prize = track.get("prize", "")
            desc = track.get("description", "")
            msg = (
                f"Research this hackathon track:\n"
                f"Track: {name}\n"
                f"Sponsor: {sponsor}\n"
                f"Prize: {prize}\n"
                f"Description: {desc}\n"
                f"Event URL: {hackathon.url}"
            )
            research_tasks.append(_guarded_phase("track", TRACK_PROMPT, msg))

        # Sponsors
        for sponsor in overview.sponsors:
            name = sponsor.get("name", "unknown")
            url = sponsor.get("url", "")
            msg = (
                f"Research this hackathon sponsor:\n"
                f"Sponsor: {name}\n"
                f"URL: {url}\n"
                f"Event URL: {hackathon.url}"
            )
            research_tasks.append(_guarded_phase("sponsor", SPONSOR_PROMPT, msg))

        # Judges
        for judge in overview.judges:
            name = judge.get("name", "unknown")
            url = judge.get("url", "")
            msg = (
                f"Research this hackathon judge:\n"
                f"Judge: {name}\n"
                f"Profile: {url}\n"
                f"Event URL: {hackathon.url}"
            )
            research_tasks.append(_guarded_phase("judge", JUDGE_PROMPT, msg))

        # Past editions
        event_name = hackathon.name or overview.name or hackathon.url
        research_tasks.append(
            _guarded_phase(
                "past",
                PAST_PROMPT,
                f"Search for past editions and winners of: {event_name}\n"
                f"Event URL: {hackathon.url}",
            )
        )

        if research_tasks:
            logger.info(
                "Phase 2-5: %d research tasks (max %d concurrent)",
                len(research_tasks),
                _MAX_CONCURRENT,
            )
            research_results = await asyncio.gather(
                *research_tasks, return_exceptions=True
            )
            for r in research_results:
                if isinstance(r, PhaseResult):
                    all_phases.append(r)
                elif isinstance(r, BaseException):
                    logger.warning("Research task failed: %s", r)
                    all_phases.append(PhaseResult(
                        phase="research", error=str(r),
                    ))

        # Phase 6: Strategy synthesis
        logger.info("Phase 6/6: Strategy synthesis")
        priors = _load_priors()
        strategy_prompt = STRATEGY_PROMPT.format(priors=priors)

        # Pass map content as user message so the strategy agent
        # can work even without read_section tool calls
        map_content = _read_map_for_strategy(map_root)
        strategy_msg = (
            f"Synthesize a strategy for: {event_name}\n"
            f"Event URL: {hackathon.url}\n\n"
            f"## Research collected\n\n{map_content}"
        )

        strategy_phase = await _run_phase(
            "strategy",
            strategy_prompt,
            strategy_msg,
            http_client=http_client,
            map_root=map_root,
            model=model,
        )
        all_phases.append(strategy_phase)

        # Aggregate results across all phases
        for p in all_phases:
            result.sections_written.extend(p.sections_written)
            result.input_tokens += p.input_tokens
            result.output_tokens += p.output_tokens
            result.total_turns += p.turns

        # Fallback: scan disk if capture missed sections
        if not result.sections_written and os.path.isdir(map_root):
            result.sections_written = sorted(
                str(p.relative_to(map_root))
                for p in Path(map_root).rglob("*.md")
                if p.name != "research.md"
            )

        result.tracks_found = len(overview.tracks)
        result.confidence = _compute_confidence(all_phases, overview)
        result.summary = _compute_summary(all_phases, overview, result)

        return result
    finally:
        if own_http:
            await http_client.aclose()
