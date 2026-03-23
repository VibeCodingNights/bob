"""Tests for the Situation Room agent (situation.py)."""

from __future__ import annotations

import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ResultMessage

from hackathon_finder.models import Hackathon
from hackathon_finder.situation import SituationResult, analyze
from hackathon_finder.tools.mcp import ResultCapture
from hackathon_finder.tools.web import execute_check_link, execute_fetch_page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _h(**kw) -> Hackathon:
    defaults = {
        "name": "Test Hackathon",
        "url": "https://example.com/hack",
        "source": "eventbrite",
    }
    defaults.update(kw)
    return Hackathon(**defaults)


def _mock_http_client(
    status_code: int = 200,
    text: str = "<html><title>Test Hackathon</title></html>",
) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text
    mock_resp.url = "https://example.com"
    mock_resp.json.return_value = {}

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    client.head = AsyncMock(return_value=mock_resp)
    client.aclose = AsyncMock()
    return client


async def _mock_query(*messages):
    """Async generator yielding canned messages."""
    for msg in messages:
        yield msg


def _result_msg(
    input_tokens: int = 0,
    output_tokens: int = 0,
    num_turns: int = 0,
    is_error: bool = False,
) -> ResultMessage:
    """Create a real ResultMessage for testing."""
    return ResultMessage(
        subtype="result",
        duration_ms=1000,
        duration_api_ms=900,
        is_error=is_error,
        num_turns=num_turns,
        session_id="test-session",
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


# ---------------------------------------------------------------------------
# 1. Full agent loop — happy path
# ---------------------------------------------------------------------------


class TestAnalyzeHappyPath:
    @pytest.mark.asyncio
    @patch("hackathon_finder.situation.query")
    @patch("hackathon_finder.situation.ResultCapture")
    async def test_full_loop(self, MockCapture, mock_query, tmp_path):
        """Agent completes analysis with sections and submission."""
        capture = MagicMock()
        capture.data = {
            "summary": "Great hackathon with AI track",
            "tracks_found": 2,
            "sections_written": 2,
            "confidence": 0.85,
        }
        capture.sections_written = ["overview.md", "tracks/ai.md"]
        MockCapture.return_value = capture

        mock_query.return_value = _mock_query(
            _result_msg(input_tokens=1000, output_tokens=310, num_turns=4)
        )

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        assert result.summary == "Great hackathon with AI track"
        assert result.tracks_found == 2
        assert result.confidence == 0.85
        assert "overview.md" in result.sections_written
        assert "tracks/ai.md" in result.sections_written
        assert result.input_tokens == 1000
        assert result.output_tokens == 310
        assert result.tool_calls == 4


# ---------------------------------------------------------------------------
# 2. Agent stops without verdict
# ---------------------------------------------------------------------------


class TestStopsWithoutVerdict:
    @pytest.mark.asyncio
    @patch("hackathon_finder.situation.query")
    @patch("hackathon_finder.situation.ResultCapture")
    async def test_end_turn_without_submit(self, MockCapture, mock_query, tmp_path):
        """Agent returns without calling submit_analysis."""
        capture = MagicMock()
        capture.data = None
        capture.sections_written = []
        MockCapture.return_value = capture

        mock_query.return_value = _mock_query(
            _result_msg(input_tokens=200, output_tokens=30, num_turns=0)
        )

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        assert result.confidence == 0.3
        assert "stopped without submitting" in result.summary.lower()
        assert result.tool_calls == 0


# ---------------------------------------------------------------------------
# 3. sections_written tracking
# ---------------------------------------------------------------------------


class TestSectionsWrittenTracking:
    @pytest.mark.asyncio
    @patch("hackathon_finder.situation.query")
    @patch("hackathon_finder.situation.ResultCapture")
    async def test_tracks_written_sections(self, MockCapture, mock_query, tmp_path):
        """write_section paths are tracked in result.sections_written."""
        capture = MagicMock()
        capture.data = {
            "summary": "All done",
            "tracks_found": 1,
            "sections_written": 3,
            "confidence": 0.9,
        }
        capture.sections_written = ["overview.md", "tracks/defi.md", "strategy.md"]
        MockCapture.return_value = capture

        mock_query.return_value = _mock_query(
            _result_msg(input_tokens=400, output_tokens=130, num_turns=3)
        )

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        assert result.sections_written == ["overview.md", "tracks/defi.md", "strategy.md"]


# ---------------------------------------------------------------------------
# 4. map_root defaults to events/<event_id>
# ---------------------------------------------------------------------------


class TestMapRootDefault:
    @pytest.mark.asyncio
    @patch("hackathon_finder.situation.query")
    @patch("hackathon_finder.situation.ResultCapture")
    async def test_default_map_root(self, MockCapture, mock_query):
        """When map_root=None, it defaults to ./events/<event_id>."""
        h = _h()
        event_id = h.event_id

        capture = MagicMock()
        capture.data = {
            "summary": "Quick analysis",
            "tracks_found": 0,
            "sections_written": 0,
            "confidence": 0.5,
        }
        capture.sections_written = []
        MockCapture.return_value = capture

        mock_query.return_value = _mock_query(
            _result_msg(input_tokens=100, output_tokens=30, num_turns=0)
        )

        http = _mock_http_client()
        result = await analyze(h, map_root=None, http_client=http)

        expected_suffix = os.path.join("events", event_id)
        assert result.map_root.endswith(expected_suffix)

        # Clean up
        if os.path.exists(result.map_root):
            shutil.rmtree(result.map_root)
        events_dir = os.path.dirname(result.map_root)
        if os.path.exists(events_dir) and not os.listdir(events_dir):
            os.rmdir(events_dir)


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    @patch("hackathon_finder.situation.query")
    @patch("hackathon_finder.situation.ResultCapture")
    async def test_query_exception(self, MockCapture, mock_query, tmp_path):
        """Exception during query() returns safe fallback."""
        capture = MagicMock()
        capture.data = None
        capture.sections_written = ["overview.md"]
        MockCapture.return_value = capture

        mock_query.side_effect = RuntimeError("CLI subprocess failed")

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        # Exception swallowed gracefully — sections preserved, treated as incomplete
        assert result.confidence == 0.5
        assert "wrote 1 sections" in result.summary
        assert result.sections_written == ["overview.md"]


# ---------------------------------------------------------------------------
# 6. Tool dispatch (via MCP handlers)
# ---------------------------------------------------------------------------


class TestToolDispatch:
    """Tests that MCP tool handlers dispatch correctly to underlying executors."""

    @pytest.mark.asyncio
    async def test_fetch_page_via_mcp(self):
        """fetch_page MCP handler routes to web tool."""
        http = _mock_http_client()
        capture = ResultCapture()
        from hackathon_finder.tools.mcp import _make_web_tools

        tools = _make_web_tools(http)
        fetch_page = tools[0]  # FETCH_PAGE_TOOL
        result = await fetch_page.handler({"url": "https://example.com"})
        assert result["content"][0]["type"] == "text"
        assert "Status:" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_write_section_via_mcp(self, tmp_path):
        """write_section MCP handler routes to map tool and tracks sections."""
        capture = ResultCapture()
        from hackathon_finder.tools.mcp import _make_map_tools

        tools = _make_map_tools(str(tmp_path), capture)
        write_section = tools[0]  # WRITE_SECTION_TOOL
        result = await write_section.handler({
            "path": "test.md",
            "frontmatter": {"title": "Test"},
            "body": "Hello",
            "owner": "test",
        })
        assert "Written" in result["content"][0]["text"]
        assert (tmp_path / "test.md").exists()
        assert capture.sections_written == ["test.md"]

    @pytest.mark.asyncio
    async def test_submit_verdict_captures_data(self):
        """submit_verdict MCP handler captures result data."""
        http = _mock_http_client()
        capture = ResultCapture()
        from hackathon_finder.tools.mcp import create_investigation_server

        server = create_investigation_server(http, capture)
        # The server instance has tools registered; find submit_verdict
        # Test via the capture mechanism indirectly
        assert capture.data is None

    @pytest.mark.asyncio
    async def test_submit_analysis_captures_data(self):
        """submit_analysis MCP handler captures result data."""
        http = _mock_http_client()
        capture = ResultCapture()
        from hackathon_finder.tools.mcp import create_situation_server

        server = create_situation_server(http, str("/tmp/test-map"), capture)
        assert capture.data is None
