"""Tests for the investigation agent (tools, loop, token tracking)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bob.agent import (
    InvestigationResult,
    TokenUsage,
    _format_hackathon_message,
    investigate,
)
from bob.models import Hackathon
from bob.telemetry import AgentResult
from bob.tools.web import (
    PageMeta,
    _extract_page_meta,
    execute_check_link,
    execute_fetch_page,
)


def _h(**kw) -> Hackathon:
    defaults = {"name": "Test Hackathon", "url": "https://example.com/hack", "source": "eventbrite"}
    defaults.update(kw)
    return Hackathon(**defaults)


# --- Mock helpers ---


def _mock_http_client(status_code: int = 200, text: str = "<html></html>", url: str = "https://example.com") -> MagicMock:
    """Build a mock httpx.AsyncClient."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text
    mock_resp.url = url

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    client.head = AsyncMock(return_value=mock_resp)
    client.aclose = AsyncMock()
    return client


def _agent_result(
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_turns: int = 0,
    success: bool = True,
    error: str | None = None,
) -> AgentResult:
    """Create an AgentResult for testing."""
    return AgentResult(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_turns=total_turns,
        success=success,
        error=error,
    )


# --- Page Metadata Extraction ---


class TestExtractPageMeta:
    def test_title(self):
        html = "<html><head><title>My Hackathon</title></head></html>"
        meta = _extract_page_meta("https://x.com", html, 200)
        assert meta.title == "My Hackathon"

    def test_og_tags(self):
        html = """<html><head>
        <meta property="og:title" content="OG Title" />
        <meta property="og:description" content="OG Desc" />
        </head></html>"""
        meta = _extract_page_meta("https://x.com", html, 200)
        assert meta.og_title == "OG Title"
        assert meta.og_description == "OG Desc"

    def test_json_ld_event(self):
        ld = {"@type": "Event", "name": "Hackathon", "startDate": "2026-06-01T09:00:00Z"}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        meta = _extract_page_meta("https://x.com", html, 200)
        assert meta.json_ld.get("@type") == "Event"
        assert meta.json_ld.get("startDate") == "2026-06-01T09:00:00Z"

    def test_json_ld_non_event(self):
        ld = {"@type": "Organization", "name": "Acme"}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        meta = _extract_page_meta("https://x.com", html, 200)
        assert meta.json_ld == {}

    def test_no_metadata(self):
        meta = _extract_page_meta("https://x.com", "<html></html>", 200)
        assert meta.title == ""
        assert meta.json_ld == {}


# --- Tool Execution ---


class TestFetchPageTool:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        html = '<html><head><title>Hack Event</title></head><body>Hello world</body></html>'
        http = _mock_http_client(200, html)
        result = await execute_fetch_page("https://example.com", http)
        assert "Status: 200" in result
        assert "Title: Hack Event" in result
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_fetch_with_og_tags(self):
        html = '<meta property="og:title" content="OG Hack" /><meta property="og:description" content="A great hack" />'
        http = _mock_http_client(200, html)
        result = await execute_fetch_page("https://example.com", http)
        assert "OG Title: OG Hack" in result
        assert "OG Description: A great hack" in result

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        http = _mock_http_client()
        http.get = AsyncMock(side_effect=ConnectionError("refused"))
        result = await execute_fetch_page("https://down.com", http)
        assert "Error fetching" in result
        assert "refused" in result


class TestCheckLinkTool:
    @pytest.mark.asyncio
    async def test_ok(self):
        http = _mock_http_client(200)
        result = await execute_check_link("https://example.com", http)
        assert "Status: 200" in result

    @pytest.mark.asyncio
    async def test_error(self):
        http = _mock_http_client()
        http.head = AsyncMock(side_effect=TimeoutError("timed out"))
        result = await execute_check_link("https://slow.com", http)
        assert "Error checking" in result


# --- Investigation Agent Loop ---


class TestInvestigate:
    @pytest.mark.asyncio
    @patch("bob.agent.AgentSession")
    @patch("bob.agent.run_agent", new_callable=AsyncMock)
    @patch("bob.agent.ResultCapture")
    async def test_single_round_verdict(self, MockCapture, mock_run_agent, MockSession):
        """Agent calls submit_verdict — result captured."""
        capture = MagicMock()
        capture.data = {
            "valid": True,
            "confidence": 0.95,
            "reasoning": "Event page confirms hackathon",
        }
        MockCapture.return_value = capture

        mock_run_agent.return_value = _agent_result(
            input_tokens=200, output_tokens=80, total_turns=1
        )

        http = _mock_http_client()
        result = await investigate(_h(), http_client=http)

        assert result.valid is True
        assert result.confidence == 0.95
        assert result.reasoning == "Event page confirms hackathon"
        assert result.corrections == []
        assert result.input_tokens == 200
        assert result.output_tokens == 80

    @pytest.mark.asyncio
    @patch("bob.agent.AgentSession")
    @patch("bob.agent.run_agent", new_callable=AsyncMock)
    @patch("bob.agent.ResultCapture")
    async def test_verdict_with_corrections(self, MockCapture, mock_run_agent, MockSession):
        """Agent submits corrections with evidence."""
        capture = MagicMock()
        capture.data = {
            "valid": True,
            "confidence": 0.85,
            "reasoning": "Location corrected from page",
            "corrections": [{
                "field": "location",
                "value": "San Francisco, CA",
                "source_url": "https://example.com/hack",
                "extracted_text": "Venue: Moscone Center, San Francisco",
            }],
        }
        MockCapture.return_value = capture

        mock_run_agent.return_value = _agent_result(
            input_tokens=500, output_tokens=100, total_turns=2
        )

        http = _mock_http_client()
        result = await investigate(_h(), http_client=http)

        assert len(result.corrections) == 1
        assert result.corrections[0]["field"] == "location"
        assert result.corrections[0]["value"] == "San Francisco, CA"

    @pytest.mark.asyncio
    @patch("bob.agent.AgentSession")
    @patch("bob.agent.run_agent", new_callable=AsyncMock)
    @patch("bob.agent.ResultCapture")
    async def test_no_verdict(self, MockCapture, mock_run_agent, MockSession):
        """Agent stops without calling submit_verdict."""
        capture = MagicMock()
        capture.data = None
        MockCapture.return_value = capture

        mock_run_agent.return_value = _agent_result(
            input_tokens=200, output_tokens=30, total_turns=0
        )

        http = _mock_http_client()
        result = await investigate(_h(), http_client=http)

        assert result.valid is False
        assert result.confidence == 0.3
        assert "without verdict" in result.reasoning

    @pytest.mark.asyncio
    @patch("bob.agent.AgentSession")
    @patch("bob.agent.run_agent", new_callable=AsyncMock)
    @patch("bob.agent.ResultCapture")
    async def test_token_tracking(self, MockCapture, mock_run_agent, MockSession):
        """Tokens reported from AgentResult."""
        capture = MagicMock()
        capture.data = {"valid": True, "confidence": 0.8, "reasoning": "ok"}
        MockCapture.return_value = capture

        mock_run_agent.return_value = _agent_result(
            input_tokens=2400, output_tokens=270, total_turns=2
        )

        http = _mock_http_client()
        result = await investigate(_h(), http_client=http)

        assert result.input_tokens == 2400
        assert result.output_tokens == 270
        assert result.tool_rounds == 2

    @pytest.mark.asyncio
    @patch("bob.agent.AgentSession")
    @patch("bob.agent.run_agent", new_callable=AsyncMock)
    @patch("bob.agent.ResultCapture")
    async def test_error_handling(self, MockCapture, mock_run_agent, MockSession):
        """run_agent returns error — no verdict."""
        MockCapture.return_value = MagicMock(data=None)
        mock_run_agent.return_value = _agent_result(
            success=False, error="CLI subprocess failed"
        )

        http = _mock_http_client()
        result = await investigate(_h(), http_client=http)

        assert result.valid is False
        assert result.confidence == 0.3
        assert "without verdict" in result.reasoning


# --- Token Usage Aggregator ---


class TestTokenUsage:
    def test_add_accumulates(self):
        usage = TokenUsage()
        usage.add(InvestigationResult(valid=True, confidence=0.9, reasoning="", input_tokens=500, output_tokens=200))
        usage.add(InvestigationResult(valid=False, confidence=0.8, reasoning="", input_tokens=300, output_tokens=100))
        assert usage.input_tokens == 800
        assert usage.output_tokens == 300
        assert usage.investigations == 2

    def test_summary_format(self):
        usage = TokenUsage()
        usage.add(InvestigationResult(valid=True, confidence=0.9, reasoning="", input_tokens=1500, output_tokens=500))
        s = usage.summary()
        assert "1 investigation" in s
        assert "1,500 input" in s
        assert "500 output" in s
        assert "2,000 total" in s


# --- Format Hackathon Message ---


class TestFormatMessage:
    def test_basic_fields(self):
        h = _h(name="SF Hack", location="San Francisco")
        msg = _format_hackathon_message(h)
        assert "SF Hack" in msg
        assert "San Francisco" in msg
        assert "eventbrite" in msg

    def test_optional_fields(self):
        h = _h(description="Build cool stuff")
        msg = _format_hackathon_message(h)
        assert "Build cool stuff" in msg
