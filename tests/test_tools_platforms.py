"""Tests for Devpost platform tools."""

from __future__ import annotations

import pytest
import httpx

from bob.tools.platforms import (
    _is_devpost_url,
    execute_fetch_devpost_winners,
    execute_fetch_devpost_submission_reqs,
    execute_platform_tool,
    _parse_gallery_entries,
    _extract_requirement_sections,
    PLATFORM_TOOLS,
)


# ---------------------------------------------------------------------------
# Mock HTML fixtures
# ---------------------------------------------------------------------------

GALLERY_HTML = """
<html>
<body>
<div class="gallery">
  <a class="gallery-entry" href="https://devpost.com/software/cool-project">
    <h5>Cool Project</h5>
    <p class="tagline">A tool that does cool things</p>
    <span class="cp-tag">Python</span>
    <span class="cp-tag">React</span>
    <span class="winner">Best Overall</span>
  </a>
  <a class="gallery-entry" href="https://devpost.com/software/neat-hack">
    <h5>Neat Hack</h5>
    <p class="small">Makes life easier</p>
    <span class="cp-tag">JavaScript</span>
    <div class="winner">Most Creative</div>
    <div class="prize">$500 Prize</div>
  </a>
</div>
</body>
</html>
"""

GALLERY_EMPTY_HTML = """
<html>
<body>
<div class="gallery">
  <p>No submissions yet.</p>
</div>
</body>
</html>
"""

REQUIREMENTS_HTML = """
<html>
<body>
<h2>About</h2>
<p>Welcome to the hackathon!</p>

<h2>What to Submit</h2>
<p>Your submission must include a working demo, source code on GitHub, and a 2-minute video walkthrough.</p>

<h2>Judging Criteria</h2>
<p>Projects will be judged on innovation (25%), technical complexity (25%), design (25%), and impact (25%).</p>

<h2>Rules</h2>
<p>Teams of up to 4 people. All code must be written during the hackathon. Open source libraries are allowed.</p>

<h2>Prizes</h2>
<p>Grand Prize: $10,000. Runner Up: $5,000. Best Design: $2,500.</p>
</body>
</html>
"""

REQUIREMENTS_EMPTY_HTML = """
<html>
<body>
<h2>About</h2>
<p>Welcome to the hackathon!</p>
<h2>Schedule</h2>
<p>Friday 6pm - Sunday 12pm</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helper: mock httpx.AsyncClient
# ---------------------------------------------------------------------------

class MockResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.url = httpx.URL("https://mock.devpost.com")


class MockClient:
    """A minimal mock that returns predefined responses by URL substring."""

    def __init__(self, responses: dict[str, MockResponse] | None = None, default: MockResponse | None = None):
        self.responses = responses or {}
        self.default = default or MockResponse("", 404)

    async def get(self, url: str, **kwargs) -> MockResponse:
        for pattern, resp in self.responses.items():
            if pattern in url:
                return resp
        return self.default


# Monkeypatch _retry_http to call directly (no retries needed in tests)
@pytest.fixture(autouse=True)
def _patch_retry(monkeypatch):
    async def _no_retry(coro_factory, url):
        return await coro_factory()
    monkeypatch.setattr("bob.tools.platforms._retry_http", _no_retry)


# ---------------------------------------------------------------------------
# Gallery entry parsing (unit)
# ---------------------------------------------------------------------------

class TestParseGalleryEntries:
    def test_parses_projects(self):
        projects = _parse_gallery_entries(GALLERY_HTML)
        assert len(projects) == 2

        p1 = projects[0]
        assert p1["name"] == "Cool Project"
        assert p1["url"] == "https://devpost.com/software/cool-project"
        assert p1["tagline"] == "A tool that does cool things"
        assert "Python" in p1["technologies"]
        assert "React" in p1["technologies"]
        assert "Best Overall" in p1["prizes"]

    def test_fallback_subtitle(self):
        projects = _parse_gallery_entries(GALLERY_HTML)
        p2 = projects[1]
        assert p2["name"] == "Neat Hack"
        assert p2["tagline"] == "Makes life easier"

    def test_multiple_prize_sources(self):
        projects = _parse_gallery_entries(GALLERY_HTML)
        p2 = projects[1]
        assert "Most Creative" in p2["prizes"]
        assert "$500 Prize" in p2["prizes"]

    def test_empty_gallery(self):
        projects = _parse_gallery_entries(GALLERY_EMPTY_HTML)
        assert projects == []


# ---------------------------------------------------------------------------
# Requirement sections parsing (unit)
# ---------------------------------------------------------------------------

class TestExtractRequirementSections:
    def test_extracts_relevant_sections(self):
        sections = _extract_requirement_sections(REQUIREMENTS_HTML)
        headings = [h for h, _ in sections]
        assert "What to Submit" in headings
        assert "Judging Criteria" in headings
        assert "Rules" in headings
        assert "Prizes" in headings
        # "About" should NOT be included
        assert "About" not in headings

    def test_section_content(self):
        sections = _extract_requirement_sections(REQUIREMENTS_HTML)
        reqs = dict(sections)
        assert "working demo" in reqs["What to Submit"]
        assert "innovation" in reqs["Judging Criteria"]
        assert "Teams of up to 4" in reqs["Rules"]
        assert "$10,000" in reqs["Prizes"]

    def test_no_matching_sections(self):
        sections = _extract_requirement_sections(REQUIREMENTS_EMPTY_HTML)
        assert sections == []


# ---------------------------------------------------------------------------
# execute_fetch_devpost_winners (integration with mock)
# ---------------------------------------------------------------------------

class TestFetchDevpostWinners:
    @pytest.mark.asyncio
    async def test_success(self):
        client = MockClient(responses={
            "project-gallery": MockResponse(GALLERY_HTML),
        })
        result = await execute_fetch_devpost_winners(
            "https://myhack.devpost.com", client
        )
        assert "Cool Project" in result
        assert "Neat Hack" in result
        assert "Python" in result
        assert "Best Overall" in result

    @pytest.mark.asyncio
    async def test_appends_gallery_path(self):
        """Should auto-append /project-gallery if not present."""
        called_urls = []
        original_get = MockClient.get

        async def tracking_get(self, url, **kwargs):
            called_urls.append(url)
            return MockResponse(GALLERY_HTML)

        MockClient.get = tracking_get
        try:
            client = MockClient()
            await execute_fetch_devpost_winners("https://hack.devpost.com", client)
            assert any("project-gallery" in u for u in called_urls)
        finally:
            MockClient.get = original_get

    @pytest.mark.asyncio
    async def test_non_devpost_url(self):
        client = MockClient()
        result = await execute_fetch_devpost_winners(
            "https://example.com/hackathon", client
        )
        assert "does not appear to be a Devpost URL" in result

    @pytest.mark.asyncio
    async def test_empty_gallery(self):
        client = MockClient(responses={
            "project-gallery": MockResponse(GALLERY_EMPTY_HTML),
        })
        result = await execute_fetch_devpost_winners(
            "https://myhack.devpost.com", client
        )
        assert "No structured project entries found" in result or "No projects found" in result

    @pytest.mark.asyncio
    async def test_http_error(self):
        client = MockClient(responses={
            "project-gallery": MockResponse("Not Found", 404),
        })
        result = await execute_fetch_devpost_winners(
            "https://myhack.devpost.com", client
        )
        assert "Error" in result
        assert "404" in result

    @pytest.mark.asyncio
    async def test_request_exception(self):
        class FailClient:
            async def get(self, url, **kwargs):
                raise httpx.ConnectError("Connection refused")

        result = await execute_fetch_devpost_winners(
            "https://myhack.devpost.com", FailClient()
        )
        assert "Error fetching" in result


# ---------------------------------------------------------------------------
# execute_fetch_devpost_submission_reqs (integration with mock)
# ---------------------------------------------------------------------------

class TestFetchDevpostSubmissionReqs:
    @pytest.mark.asyncio
    async def test_success(self):
        client = MockClient(default=MockResponse(REQUIREMENTS_HTML))
        result = await execute_fetch_devpost_submission_reqs(
            "https://myhack.devpost.com", client
        )
        assert "What to Submit" in result
        assert "Judging Criteria" in result
        assert "working demo" in result

    @pytest.mark.asyncio
    async def test_strips_subpaths(self):
        """Should strip /project-gallery before fetching main page."""
        called_urls = []

        class TrackingClient:
            async def get(self, url, **kwargs):
                called_urls.append(url)
                return MockResponse(REQUIREMENTS_HTML)

        client = TrackingClient()
        await execute_fetch_devpost_submission_reqs(
            "https://myhack.devpost.com/project-gallery", client
        )
        assert not any("project-gallery" in u for u in called_urls)

    @pytest.mark.asyncio
    async def test_non_devpost_url(self):
        client = MockClient()
        result = await execute_fetch_devpost_submission_reqs(
            "https://example.com/hackathon", client
        )
        assert "does not appear to be a Devpost URL" in result

    @pytest.mark.asyncio
    async def test_no_requirements_found(self):
        client = MockClient(default=MockResponse(REQUIREMENTS_EMPTY_HTML))
        result = await execute_fetch_devpost_submission_reqs(
            "https://myhack.devpost.com", client
        )
        assert "No structured requirement sections found" in result or "No submission requirements" in result

    @pytest.mark.asyncio
    async def test_http_error(self):
        client = MockClient(default=MockResponse("Error", 500))
        result = await execute_fetch_devpost_submission_reqs(
            "https://myhack.devpost.com", client
        )
        assert "Error" in result
        assert "500" in result


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_winners(self):
        client = MockClient(responses={
            "project-gallery": MockResponse(GALLERY_HTML),
        })
        result = await execute_platform_tool(
            "fetch_devpost_winners",
            {"hackathon_url": "https://myhack.devpost.com"},
            client,
        )
        assert result is not None
        assert "Cool Project" in result

    @pytest.mark.asyncio
    async def test_dispatch_submission_reqs(self):
        client = MockClient(default=MockResponse(REQUIREMENTS_HTML))
        result = await execute_platform_tool(
            "fetch_devpost_submission_reqs",
            {"hackathon_url": "https://myhack.devpost.com"},
            client,
        )
        assert result is not None
        assert "What to Submit" in result

    @pytest.mark.asyncio
    async def test_dispatch_unknown(self):
        client = MockClient()
        result = await execute_platform_tool("nonexistent_tool", {}, client)
        assert result is None


# ---------------------------------------------------------------------------
# Tool definitions sanity
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_platform_tools_list(self):
        assert len(PLATFORM_TOOLS) == 2
        names = {t["name"] for t in PLATFORM_TOOLS}
        assert "fetch_devpost_winners" in names
        assert "fetch_devpost_submission_reqs" in names

    def test_tool_schemas_valid(self):
        for tool in PLATFORM_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert "hackathon_url" in schema["properties"]
            assert "hackathon_url" in schema["required"]


# ---------------------------------------------------------------------------
# Devpost URL validation
# ---------------------------------------------------------------------------


class TestIsDevpostUrl:
    def test_valid_subdomain(self):
        assert _is_devpost_url("https://myhack.devpost.com") is True

    def test_valid_root(self):
        assert _is_devpost_url("https://devpost.com/hackathons") is True

    def test_rejects_fake_subdomain(self):
        assert _is_devpost_url("https://devpost.com.evil.tld") is False

    def test_rejects_substring_in_path(self):
        assert _is_devpost_url("https://evil.com/?x=devpost.com") is False

    def test_rejects_substring_in_param(self):
        assert _is_devpost_url("https://evil.com/devpost.com") is False
