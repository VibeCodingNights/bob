"""Tests for the investigation agent (tools, loop, token tracking)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from hackathon_finder.agent import (
    InvestigationResult,
    PageMeta,
    TokenUsage,
    _execute_check_link,
    _execute_fetch_page,
    _extract_page_meta,
    _format_hackathon_message,
    investigate,
)
from hackathon_finder.models import Hackathon


def _h(**kw) -> Hackathon:
    defaults = {"name": "Test Hackathon", "url": "https://example.com/hack", "source": "eventbrite"}
    defaults.update(kw)
    return Hackathon(**defaults)


# --- Mock helpers for Anthropic SDK ---


@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "toolu_test_001"
    name: str = "fetch_page"
    input: dict = None

    def __post_init__(self):
        if self.input is None:
            self.input = {"url": "https://example.com"}


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class MockUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class MockResponse:
    content: list = None
    stop_reason: str = "tool_use"
    usage: MockUsage = None

    def __post_init__(self):
        if self.content is None:
            self.content = []
        if self.usage is None:
            self.usage = MockUsage()


def _mock_anthropic_client(*responses: MockResponse) -> MagicMock:
    """Build a mock AsyncAnthropic client that returns responses in sequence."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(responses))
    return client


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
        result = await _execute_fetch_page("https://example.com", http)
        assert "Status: 200" in result
        assert "Title: Hack Event" in result
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_fetch_with_og_tags(self):
        html = '<meta property="og:title" content="OG Hack" /><meta property="og:description" content="A great hack" />'
        http = _mock_http_client(200, html)
        result = await _execute_fetch_page("https://example.com", http)
        assert "OG Title: OG Hack" in result
        assert "OG Description: A great hack" in result

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        http = _mock_http_client()
        http.get = AsyncMock(side_effect=ConnectionError("refused"))
        result = await _execute_fetch_page("https://down.com", http)
        assert "Error fetching" in result
        assert "refused" in result


class TestCheckLinkTool:
    @pytest.mark.asyncio
    async def test_ok(self):
        http = _mock_http_client(200)
        result = await _execute_check_link("https://example.com", http)
        assert "Status: 200" in result

    @pytest.mark.asyncio
    async def test_error(self):
        http = _mock_http_client()
        http.head = AsyncMock(side_effect=TimeoutError("timed out"))
        result = await _execute_check_link("https://slow.com", http)
        assert "Error checking" in result


# --- Investigation Agent Loop ---


class TestInvestigate:
    @pytest.mark.asyncio
    async def test_single_round_verdict(self):
        """Agent calls submit_verdict on first round (no prior tool use)."""
        verdict_block = MockToolUseBlock(
            name="submit_verdict",
            id="toolu_verdict_001",
            input={
                "valid": True,
                "confidence": 0.95,
                "reasoning": "Event page confirms hackathon",
            },
        )
        response = MockResponse(
            content=[verdict_block],
            stop_reason="tool_use",
            usage=MockUsage(input_tokens=200, output_tokens=80),
        )
        client = _mock_anthropic_client(response)
        http = _mock_http_client()

        result = await investigate(_h(), client=client, http_client=http)

        assert result.valid is True
        assert result.confidence == 0.95
        assert result.reasoning == "Event page confirms hackathon"
        assert result.corrections == []
        assert result.input_tokens == 200
        assert result.output_tokens == 80

    @pytest.mark.asyncio
    async def test_fetch_then_verdict(self):
        """Agent fetches page, then submits verdict (2 API calls)."""
        # Round 1: fetch_page
        fetch_block = MockToolUseBlock(
            name="fetch_page",
            id="toolu_fetch_001",
            input={"url": "https://example.com/hack"},
        )
        r1 = MockResponse(
            content=[fetch_block],
            stop_reason="tool_use",
            usage=MockUsage(input_tokens=200, output_tokens=60),
        )

        # Round 2: submit_verdict
        verdict_block = MockToolUseBlock(
            name="submit_verdict",
            id="toolu_verdict_001",
            input={
                "valid": False,
                "confidence": 0.9,
                "reasoning": "Page is a meetup, not a hackathon",
            },
        )
        r2 = MockResponse(
            content=[verdict_block],
            stop_reason="tool_use",
            usage=MockUsage(input_tokens=800, output_tokens=100),
        )

        client = _mock_anthropic_client(r1, r2)
        http = _mock_http_client(200, "<html><title>Python Meetup</title></html>")

        result = await investigate(_h(), client=client, http_client=http)

        assert result.valid is False
        assert result.confidence == 0.9
        assert result.tool_rounds == 1  # One round of actual tool execution
        assert result.input_tokens == 1000  # 200 + 800
        assert result.output_tokens == 160  # 60 + 100

    @pytest.mark.asyncio
    async def test_verdict_with_corrections(self):
        """Agent submits corrections with evidence."""
        verdict_block = MockToolUseBlock(
            name="submit_verdict",
            id="toolu_verdict_001",
            input={
                "valid": True,
                "confidence": 0.85,
                "reasoning": "Location corrected from page",
                "corrections": [{
                    "field": "location",
                    "value": "San Francisco, CA",
                    "source_url": "https://example.com/hack",
                    "extracted_text": "Venue: Moscone Center, San Francisco",
                }],
            },
        )
        response = MockResponse(content=[verdict_block], stop_reason="tool_use")
        client = _mock_anthropic_client(response)
        http = _mock_http_client()

        result = await investigate(_h(), client=client, http_client=http)

        assert len(result.corrections) == 1
        assert result.corrections[0]["field"] == "location"
        assert result.corrections[0]["value"] == "San Francisco, CA"
        assert result.corrections[0]["source_url"] == "https://example.com/hack"

    @pytest.mark.asyncio
    async def test_max_rounds_exceeded(self):
        """Agent hits max_rounds without submitting verdict."""
        fetch_block = MockToolUseBlock(
            name="fetch_page",
            id="toolu_fetch_001",
            input={"url": "https://example.com"},
        )
        # Every round returns another fetch_page call, never a verdict
        response = MockResponse(
            content=[fetch_block],
            stop_reason="tool_use",
            usage=MockUsage(input_tokens=200, output_tokens=60),
        )
        client = _mock_anthropic_client(response, response, response)
        http = _mock_http_client()

        result = await investigate(_h(), client=client, http_client=http, max_rounds=3)

        assert result.valid is True  # conservative fallback
        assert result.confidence == 0.3
        assert "Exceeded" in result.reasoning

    @pytest.mark.asyncio
    async def test_model_ends_without_tool_call(self):
        """Agent returns text without calling any tool."""
        text_block = MockTextBlock(text="This looks like a hackathon to me.")
        response = MockResponse(
            content=[text_block],
            stop_reason="end_turn",
            usage=MockUsage(input_tokens=200, output_tokens=30),
        )
        client = _mock_anthropic_client(response)
        http = _mock_http_client()

        result = await investigate(_h(), client=client, http_client=http)

        assert result.valid is True
        assert result.confidence == 0.3
        assert "without submitting verdict" in result.reasoning

    @pytest.mark.asyncio
    async def test_token_accumulation(self):
        """Tokens accumulate across multi-round investigation."""
        fetch = MockToolUseBlock(name="fetch_page", id="toolu_f1", input={"url": "https://a.com"})
        r1 = MockResponse(content=[fetch], stop_reason="tool_use", usage=MockUsage(300, 70))

        check = MockToolUseBlock(name="check_link", id="toolu_c1", input={"url": "https://b.com"})
        r2 = MockResponse(content=[check], stop_reason="tool_use", usage=MockUsage(900, 90))

        verdict = MockToolUseBlock(
            name="submit_verdict", id="toolu_v1",
            input={"valid": True, "confidence": 0.8, "reasoning": "ok"},
        )
        r3 = MockResponse(content=[verdict], stop_reason="tool_use", usage=MockUsage(1200, 110))

        client = _mock_anthropic_client(r1, r2, r3)
        http = _mock_http_client()

        result = await investigate(_h(), client=client, http_client=http)

        assert result.input_tokens == 2400  # 300 + 900 + 1200
        assert result.output_tokens == 270  # 70 + 90 + 110
        assert result.tool_rounds == 2  # fetch + check_link (verdict round doesn't count)


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
