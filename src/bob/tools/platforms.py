"""Platform-specific tools for Devpost hackathon intelligence.

Provides tools for fetching winning projects and submission requirements
from Devpost hackathon pages.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from bob.tools.web import _html_to_text, _retry_http, _safe_get

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for Devpost HTML parsing
# ---------------------------------------------------------------------------

# Project gallery entry: each winner is in a gallery-entry div/link block
_GALLERY_ENTRY_RE = re.compile(
    r'<a[^>]+class="[^"]*gallery-entry[^"]*"[^>]+href="([^"]+)"[^>]*>'
    r'(.*?)</a>',
    re.I | re.DOTALL,
)

# Project name within a gallery entry
_PROJECT_NAME_RE = re.compile(
    r'<h5[^>]*>(.*?)</h5>',
    re.I | re.DOTALL,
)

# Tagline / subtitle within a gallery entry
_PROJECT_TAGLINE_RE = re.compile(
    r'<p[^>]*class="[^"]*tagline[^"]*"[^>]*>(.*?)</p>',
    re.I | re.DOTALL,
)

# Alternative: small text or subtitle paragraph
_PROJECT_SUBTITLE_RE = re.compile(
    r'<p[^>]*class="[^"]*small[^"]*"[^>]*>(.*?)</p>',
    re.I | re.DOTALL,
)

# Technologies / built-with spans
_BUILT_WITH_RE = re.compile(
    r'<span[^>]*class="[^"]*cp-tag[^"]*"[^>]*>(.*?)</span>',
    re.I | re.DOTALL,
)

# Winner badge / prize label
_WINNER_RE = re.compile(
    r'<(?:span|div)[^>]*class="[^"]*winner[^"]*"[^>]*>(.*?)</(?:span|div)>',
    re.I | re.DOTALL,
)

# Prize labels (more general)
_PRIZE_LABEL_RE = re.compile(
    r'<(?:span|div|p)[^>]*class="[^"]*prize[^"]*"[^>]*>(.*?)</(?:span|div|p)>',
    re.I | re.DOTALL,
)

# Strip HTML tags
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _TAG_RE.sub(' ', html)
    return _WS_RE.sub(' ', text).strip()


def _is_devpost_url(url: str) -> bool:
    """Check if URL is actually a Devpost domain."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        return hostname == "devpost.com" or hostname.endswith(".devpost.com")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# execute_fetch_devpost_winners
# ---------------------------------------------------------------------------


async def execute_fetch_devpost_winners(
    hackathon_url: str, http_client: httpx.AsyncClient
) -> str:
    """Fetch winning projects from a Devpost hackathon's project gallery."""
    # Validate it looks like a Devpost URL
    if not _is_devpost_url(hackathon_url):
        return (
            f"Error: {hackathon_url} does not appear to be a Devpost URL. "
            "This tool only works with Devpost hackathon pages."
        )

    # Normalize URL: ensure it ends with /project-gallery
    url = hackathon_url.rstrip("/")
    if not url.endswith("/project-gallery"):
        url = url + "/project-gallery"

    try:
        resp = await _retry_http(
            lambda: _safe_get(url, http_client), url
        )
    except Exception as e:
        return f"Error fetching project gallery at {url}: {e}"

    if resp.status_code != 200:
        return f"Error: received status {resp.status_code} from {url}"

    html = resp.text
    projects = _parse_gallery_entries(html)

    if not projects:
        # Fallback: return readable text from the page so the caller
        # still gets something useful
        readable = _html_to_text(html, max_chars=4000)
        if readable:
            return (
                "No structured project entries found in the gallery. "
                f"Page text:\n{readable}"
            )
        return "No projects found in the project gallery."

    # Format output
    lines = [f"Found {len(projects)} project(s):\n"]
    for i, p in enumerate(projects, 1):
        lines.append(f"  {i}. {p['name']}")
        if p.get("url"):
            lines.append(f"     URL: {p['url']}")
        if p.get("tagline"):
            lines.append(f"     Tagline: {p['tagline']}")
        if p.get("technologies"):
            lines.append(f"     Built with: {', '.join(p['technologies'])}")
        if p.get("prizes"):
            lines.append(f"     Prizes: {', '.join(p['prizes'])}")
        lines.append("")

    return "\n".join(lines).strip()


def _parse_gallery_entries(html: str) -> list[dict]:
    """Parse project entries from Devpost gallery HTML."""
    projects: list[dict] = []

    for m in _GALLERY_ENTRY_RE.finditer(html):
        project_url = m.group(1).strip()
        entry_html = m.group(2)

        # Project name
        name_m = _PROJECT_NAME_RE.search(entry_html)
        name = _strip_tags(name_m.group(1)) if name_m else "Unknown Project"

        # Tagline
        tagline = ""
        tag_m = _PROJECT_TAGLINE_RE.search(entry_html)
        if tag_m:
            tagline = _strip_tags(tag_m.group(1))
        else:
            sub_m = _PROJECT_SUBTITLE_RE.search(entry_html)
            if sub_m:
                tagline = _strip_tags(sub_m.group(1))

        # Technologies
        techs = [_strip_tags(t.group(1)) for t in _BUILT_WITH_RE.finditer(entry_html)]

        # Prizes
        prizes: list[str] = []
        for pm in _WINNER_RE.finditer(entry_html):
            prize_text = _strip_tags(pm.group(1))
            if prize_text:
                prizes.append(prize_text)
        for pm in _PRIZE_LABEL_RE.finditer(entry_html):
            prize_text = _strip_tags(pm.group(1))
            if prize_text and prize_text not in prizes:
                prizes.append(prize_text)

        projects.append({
            "name": name,
            "url": project_url,
            "tagline": tagline,
            "technologies": techs,
            "prizes": prizes,
        })

    return projects


# ---------------------------------------------------------------------------
# execute_fetch_devpost_submission_reqs
# ---------------------------------------------------------------------------

# Section header patterns for requirements extraction
_SECTION_PATTERNS = [
    re.compile(r'(?:what\s+to\s+submit|submission\s+requirements?|how\s+to\s+submit)', re.I),
    re.compile(r'(?:judging\s+criteria|judging)', re.I),
    re.compile(r'(?:rules|eligibility)', re.I),
    re.compile(r'(?:requirements?|deliverables?)', re.I),
    re.compile(r'(?:prizes?|awards?)', re.I),
]

_HEADING_RE = re.compile(
    r'<h[1-6][^>]*>(.*?)</h[1-6]>',
    re.I | re.DOTALL,
)

_SECTION_BLOCK_RE = re.compile(
    r'(<h[1-6][^>]*>.*?</h[1-6]>)(.*?)(?=<h[1-6][^>]*>|$)',
    re.I | re.DOTALL,
)


async def execute_fetch_devpost_submission_reqs(
    hackathon_url: str, http_client: httpx.AsyncClient
) -> str:
    """Fetch submission requirements from a Devpost hackathon page."""
    if not _is_devpost_url(hackathon_url):
        return (
            f"Error: {hackathon_url} does not appear to be a Devpost URL. "
            "This tool only works with Devpost hackathon pages."
        )

    url = hackathon_url.rstrip("/")
    # Strip any sub-path to get the main hackathon page
    # e.g. https://example.devpost.com/project-gallery -> https://example.devpost.com
    for suffix in ("/project-gallery", "/participants", "/submissions", "/updates"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break

    try:
        resp = await _retry_http(
            lambda: _safe_get(url, http_client), url
        )
    except Exception as e:
        return f"Error fetching hackathon page at {url}: {e}"

    if resp.status_code != 200:
        return f"Error: received status {resp.status_code} from {url}"

    html = resp.text
    sections = _extract_requirement_sections(html)

    if not sections:
        # Fallback: return page text
        readable = _html_to_text(html, max_chars=4000)
        if readable:
            return (
                "No structured requirement sections found. "
                f"Page text:\n{readable}"
            )
        return "No submission requirements found on the page."

    lines = ["Submission Requirements:\n"]
    for heading, content in sections:
        lines.append(f"## {heading}")
        lines.append(content)
        lines.append("")

    return "\n".join(lines).strip()


def _extract_requirement_sections(html: str) -> list[tuple[str, str]]:
    """Extract relevant requirement sections from hackathon page HTML."""
    sections: list[tuple[str, str]] = []
    seen_headings: set[str] = set()

    for block_m in _SECTION_BLOCK_RE.finditer(html):
        heading_html = block_m.group(1)
        body_html = block_m.group(2)

        heading_text = _strip_tags(heading_html)

        # Check if this heading matches any of our target patterns
        for pattern in _SECTION_PATTERNS:
            if pattern.search(heading_text):
                if heading_text not in seen_headings:
                    seen_headings.add(heading_text)
                    body_text = _strip_tags(body_html).strip()
                    if body_text:
                        sections.append((heading_text, body_text))
                break

    return sections


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

FETCH_DEVPOST_WINNERS_TOOL: dict = {
    "name": "fetch_devpost_winners",
    "description": (
        "Fetch winning projects from a Devpost hackathon's project gallery. "
        "Returns project names, taglines, URLs, technologies used, and prizes won. "
        "Only works with Devpost hackathon URLs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hackathon_url": {
                "type": "string",
                "description": "The Devpost hackathon URL (e.g. https://hackathon-name.devpost.com)",
            },
        },
        "required": ["hackathon_url"],
    },
}

FETCH_DEVPOST_SUBMISSION_REQS_TOOL: dict = {
    "name": "fetch_devpost_submission_reqs",
    "description": (
        "Fetch submission requirements and judging criteria from a Devpost hackathon page. "
        "Extracts sections like 'What to Submit', 'Judging Criteria', 'Rules', and prize info. "
        "Only works with Devpost hackathon URLs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hackathon_url": {
                "type": "string",
                "description": "The Devpost hackathon URL (e.g. https://hackathon-name.devpost.com)",
            },
        },
        "required": ["hackathon_url"],
    },
}

PLATFORM_TOOLS: list[dict] = [FETCH_DEVPOST_WINNERS_TOOL, FETCH_DEVPOST_SUBMISSION_REQS_TOOL]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def execute_platform_tool(
    name: str, input_data: dict, http_client: httpx.AsyncClient
) -> str | None:
    """Dispatch a platform tool by name. Returns None if name is not recognized."""
    if name == "fetch_devpost_winners":
        return await execute_fetch_devpost_winners(
            input_data["hackathon_url"], http_client
        )
    elif name == "fetch_devpost_submission_reqs":
        return await execute_fetch_devpost_submission_reqs(
            input_data["hackathon_url"], http_client
        )
    return None
