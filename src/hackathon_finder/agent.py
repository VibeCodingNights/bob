"""Per-event investigation agent using Anthropic Python SDK.

Each ambiguous hackathon gets its own multi-turn agent loop with tools
to fetch pages, check links, and submit grounded verdicts.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from hackathon_finder.models import Hackathon

logger = logging.getLogger(__name__)

# --- Page metadata extraction (moved from validate.py) ---


@dataclass
class PageMeta:
    """Metadata extracted from an event's actual page."""
    url: str
    title: str = ""
    og_title: str = ""
    og_description: str = ""
    og_type: str = ""
    meta_description: str = ""
    json_ld: dict = field(default_factory=dict)
    status_code: int = 0
    error: str = ""


_OG_RE = {
    "og_title": re.compile(r'<meta\s+(?:property|name)=["\']og:title["\']\s+content=["\'](.*?)["\']', re.I),
    "og_description": re.compile(r'<meta\s+(?:property|name)=["\']og:description["\']\s+content=["\'](.*?)["\']', re.I),
    "og_type": re.compile(r'<meta\s+(?:property|name)=["\']og:type["\']\s+content=["\'](.*?)["\']', re.I),
}
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.I)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.DOTALL,
)

# Regex to strip HTML tags for readable text extraction
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _extract_page_meta(url: str, html: str, status_code: int) -> PageMeta:
    """Extract metadata from HTML."""
    meta = PageMeta(url=url, status_code=status_code)
    head = html[:10_000]

    m = _TITLE_RE.search(head)
    if m:
        meta.title = m.group(1).strip()

    for attr, regex in _OG_RE.items():
        m = regex.search(head)
        if m:
            setattr(meta, attr, m.group(1).strip())

    m = _META_DESC_RE.search(head)
    if m:
        meta.meta_description = m.group(1).strip()

    for m in _JSON_LD_RE.finditer(html[:100_000]):
        try:
            ld = json.loads(m.group(1))
            if isinstance(ld, dict) and ld.get("@type") == "Event":
                meta.json_ld = ld
                break
            if isinstance(ld, list):
                for item in ld:
                    if isinstance(item, dict) and item.get("@type") == "Event":
                        meta.json_ld = item
                        break
                if meta.json_ld:
                    break
        except json.JSONDecodeError:
            continue

    return meta


def _html_to_text(html: str, max_chars: int = 6000) -> str:
    """Strip HTML tags and collapse whitespace for readable text."""
    text = _TAG_RE.sub(' ', html)
    text = _WS_RE.sub(' ', text).strip()
    return text[:max_chars]


def _summarize_json_ld(ld: dict) -> str:
    """Extract key fields from JSON-LD Event, avoiding huge description blobs."""
    parts = []
    if ld.get("name"):
        parts.append(f"Name: {ld['name']}")
    if ld.get("eventAttendanceMode"):
        mode = ld["eventAttendanceMode"].split("/")[-1]
        parts.append(f"Attendance Mode: {mode}")
    loc = ld.get("location", {})
    if isinstance(loc, dict):
        addr = loc.get("address", {})
        if isinstance(addr, dict):
            loc_parts = [addr.get("name", ""), addr.get("addressLocality", ""),
                         addr.get("addressRegion", ""), addr.get("streetAddress", "")]
            loc_str = ", ".join(p for p in loc_parts if p)
            if loc_str:
                parts.append(f"Location: {loc_str}")
        elif loc.get("name"):
            parts.append(f"Location: {loc['name']}")
    if ld.get("startDate"):
        parts.append(f"Start: {ld['startDate']}")
    if ld.get("endDate"):
        parts.append(f"End: {ld['endDate']}")
    # Extract venue info from description (often has "Where:" lines)
    desc = ld.get("description", "")
    if desc:
        desc_text = _TAG_RE.sub(' ', desc)
        desc_text = _WS_RE.sub(' ', desc_text).strip()
        parts.append(f"Description: {desc_text[:1500]}")
    return "\n".join(parts)


# --- Agent system prompt and tools ---

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

TOOLS = [
    {
        "name": "fetch_page",
        "description": "Fetch a URL and extract its title, OpenGraph tags, JSON-LD key fields, and a readable text snippet. Use this to verify event details. Pay close attention to the description text for venue/location info — structured metadata is often wrong.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "check_link",
        "description": "Send a HEAD request to a URL and return the HTTP status code and final redirect URL. Use this for quick link validation without downloading the full page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to check"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "submit_verdict",
        "description": "Submit your final verdict on whether this event is a valid hackathon. Call this exactly once when you have enough evidence.",
        "input_schema": {
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
                                "enum": ["location", "start_date", "end_date", "format", "registration_status"],
                            },
                            "value": {"type": "string", "description": "Corrected value. For format: use 'in-person', 'virtual', or 'hybrid'"},
                            "source_url": {"type": "string", "description": "URL where you found this"},
                            "extracted_text": {"type": "string", "description": "Text from the page supporting this correction"},
                        },
                        "required": ["field", "value", "source_url", "extracted_text"],
                    },
                },
            },
            "required": ["valid", "confidence", "reasoning"],
        },
    },
]


# --- Tool execution ---


async def _execute_fetch_page(url: str, http_client: httpx.AsyncClient) -> str:
    """Execute fetch_page tool — GET + extract metadata + readable text."""
    try:
        resp = await http_client.get(url, follow_redirects=True)
        meta = _extract_page_meta(url, resp.text, resp.status_code)
        readable = _html_to_text(resp.text)

        parts = [f"Status: {resp.status_code}", f"Final URL: {str(resp.url)}"]
        if meta.title:
            parts.append(f"Title: {meta.title}")
        if meta.og_title:
            parts.append(f"OG Title: {meta.og_title}")
        if meta.og_description:
            parts.append(f"OG Description: {meta.og_description}")
        if meta.meta_description:
            parts.append(f"Meta Description: {meta.meta_description}")
        if meta.json_ld:
            parts.append(f"JSON-LD Event:\n{_summarize_json_ld(meta.json_ld)}")
        if readable:
            parts.append(f"Readable text:\n{readable}")

        return "\n".join(parts)
    except Exception as e:
        return f"Error fetching {url}: {e}"


async def _execute_check_link(url: str, http_client: httpx.AsyncClient) -> str:
    """Execute check_link tool — HEAD request for status + redirect."""
    try:
        resp = await http_client.head(url, follow_redirects=True)
        return f"Status: {resp.status_code}\nFinal URL: {str(resp.url)}"
    except Exception as e:
        return f"Error checking {url}: {e}"


async def _execute_tool(
    name: str, input_data: dict, http_client: httpx.AsyncClient
) -> str:
    """Dispatch tool execution."""
    if name == "fetch_page":
        return await _execute_fetch_page(input_data["url"], http_client)
    elif name == "check_link":
        return await _execute_check_link(input_data["url"], http_client)
    else:
        return f"Unknown tool: {name}"


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


# --- Core agent loop ---


def _format_hackathon_message(h: Hackathon) -> str:
    """Format hackathon fields as a user message for the agent."""
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


async def investigate(
    hackathon: Hackathon,
    *,
    model: str = "claude-haiku-4-5-20251001",
    max_rounds: int = 5,
    client: Any = None,
    http_client: httpx.AsyncClient | None = None,
) -> InvestigationResult:
    """Run a multi-turn investigation agent for a single hackathon.

    Args:
        hackathon: The event to investigate.
        model: Anthropic model ID.
        max_rounds: Maximum tool-use rounds before giving up.
        client: Anthropic async client (injected for testing).
        http_client: httpx async client (injected for testing).
    """
    if client is None:
        from anthropic import AsyncAnthropic
        from hackathon_finder.oauth import get_auth
        client = AsyncAnthropic(**get_auth().client_kwargs)

    own_http = http_client is None
    if own_http:
        http_client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; hackathon-finder/0.1)"},
        )

    messages: list[dict] = [
        {"role": "user", "content": _format_hackathon_message(hackathon)},
    ]

    total_input = 0
    total_output = 0
    tool_rounds = 0

    try:
        for _ in range(max_rounds):
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Accumulate token usage
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            # Check for submit_verdict in tool calls
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            for tool_use in tool_uses:
                if tool_use.name == "submit_verdict":
                    inp = tool_use.input
                    return InvestigationResult(
                        valid=inp["valid"],
                        confidence=inp["confidence"],
                        reasoning=inp["reasoning"],
                        corrections=inp.get("corrections", []),
                        input_tokens=total_input,
                        output_tokens=total_output,
                        tool_rounds=tool_rounds,
                    )

            # If stop reason isn't tool_use, the model stopped without calling a tool
            if response.stop_reason != "tool_use":
                logger.warning(
                    "Agent stopped without verdict for %s (stop_reason=%s)",
                    hackathon.name, response.stop_reason,
                )
                return InvestigationResult(
                    valid=True,
                    confidence=0.3,
                    reasoning="Agent stopped without submitting verdict",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    tool_rounds=tool_rounds,
                )

            # Execute tools and feed results back
            tool_rounds += 1
            # Add assistant message with tool use blocks
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_use in tool_uses:
                result_text = await _execute_tool(
                    tool_use.name, tool_use.input, http_client
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})

        # Exceeded max rounds
        logger.warning("Agent exceeded %d rounds for %s", max_rounds, hackathon.name)
        return InvestigationResult(
            valid=True,
            confidence=0.3,
            reasoning=f"Exceeded {max_rounds} investigation rounds",
            input_tokens=total_input,
            output_tokens=total_output,
            tool_rounds=tool_rounds,
        )
    finally:
        if own_http:
            await http_client.aclose()
