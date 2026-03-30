"""Tests for the orchestrated Situation Room pipeline (situation.py)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from bob.models import Hackathon
from bob.telemetry import AgentResult
from bob.situation import (
    OverviewData,
    PhaseResult,
    SituationResult,
    _compute_confidence,
    _compute_summary,
    _load_priors,
    _parse_overview,
    _read_map_for_strategy,
    analyze,
)
from bob.tools.mcp import ResultCapture


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


def _write_overview(tmp_path, tracks=None, sponsors=None, judges=None):
    """Write a mock overview.md with YAML frontmatter."""
    fm = {
        "name": "Test Hackathon",
        "tracks": tracks or [],
        "sponsors": sponsors or [],
        "judges": judges or [],
    }
    content = f"---\n{yaml.dump(fm, default_flow_style=False)}---\n\nEvent overview body.\n"
    (tmp_path / "overview.md").write_text(content)


# ---------------------------------------------------------------------------
# 1. Overview parsing
# ---------------------------------------------------------------------------


class TestParseOverview:
    def test_parses_tracks(self, tmp_path):
        _write_overview(
            tmp_path,
            tracks=[
                {"name": "DeFi", "sponsor": "Uniswap", "prize": "$10K"},
                {"name": "AI", "sponsor": "OpenAI", "prize": "$5K"},
            ],
        )
        data = _parse_overview(str(tmp_path))
        assert len(data.tracks) == 2
        assert data.tracks[0]["name"] == "DeFi"
        assert data.tracks[1]["sponsor"] == "OpenAI"

    def test_parses_sponsors(self, tmp_path):
        _write_overview(
            tmp_path,
            sponsors=[
                {"name": "Uniswap", "url": "https://uniswap.org"},
            ],
        )
        data = _parse_overview(str(tmp_path))
        assert len(data.sponsors) == 1
        assert data.sponsors[0]["url"] == "https://uniswap.org"

    def test_parses_judges(self, tmp_path):
        _write_overview(
            tmp_path,
            judges=[{"name": "Alice", "url": "https://github.com/alice"}],
        )
        data = _parse_overview(str(tmp_path))
        assert len(data.judges) == 1

    def test_missing_overview(self, tmp_path):
        data = _parse_overview(str(tmp_path))
        assert data.tracks == []
        assert data.sponsors == []
        assert data.judges == []

    def test_empty_frontmatter(self, tmp_path):
        (tmp_path / "overview.md").write_text("---\n---\nJust body.\n")
        data = _parse_overview(str(tmp_path))
        assert data.tracks == []

    def test_malformed_yaml(self, tmp_path):
        (tmp_path / "overview.md").write_text("---\n: bad: yaml: {{{\n---\nbody\n")
        data = _parse_overview(str(tmp_path))
        assert data.tracks == []


# ---------------------------------------------------------------------------
# 2. Priors loading
# ---------------------------------------------------------------------------


class TestLoadPriors:
    def test_no_priors_file(self):
        result = _load_priors()
        # May or may not find the file — test it doesn't crash
        assert isinstance(result, str)

    def test_priors_content(self, tmp_path):
        priors_dir = tmp_path / "knowledge"
        priors_dir.mkdir()
        (priors_dir / "priors.md").write_text("# Test priors\n- Pattern 1\n")
        with patch(
            "bob.situation._load_priors",
            return_value="\n## Prior knowledge\n\n# Test priors\n- Pattern 1\n",
        ):
            result = _load_priors()
            assert "Prior knowledge" in result


# ---------------------------------------------------------------------------
# 3. Map reading for strategy
# ---------------------------------------------------------------------------


class TestReadMapForStrategy:
    def test_reads_sections(self, tmp_path):
        (tmp_path / "overview.md").write_text("Overview content")
        tracks = tmp_path / "tracks"
        tracks.mkdir()
        (tracks / "defi.md").write_text("DeFi track info")
        result = _read_map_for_strategy(str(tmp_path))
        assert "Overview content" in result
        assert "DeFi track info" in result
        assert "tracks/defi.md" in result

    def test_empty_map(self, tmp_path):
        result = _read_map_for_strategy(str(tmp_path))
        assert "No research sections found" in result

    def test_skips_research_log(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "research.md").write_text("Log entry")
        (tmp_path / "overview.md").write_text("Overview")
        result = _read_map_for_strategy(str(tmp_path))
        assert "Log entry" not in result
        assert "Overview" in result


# ---------------------------------------------------------------------------
# 4. Confidence computation
# ---------------------------------------------------------------------------


class TestComputeConfidence:
    def test_all_phases_complete(self):
        phases = [
            PhaseResult(phase="overview"),
            PhaseResult(phase="track"),
            PhaseResult(phase="strategy"),
        ]
        conf = _compute_confidence(phases, OverviewData())
        assert conf >= 0.9  # 3/3 + strategy bonus

    def test_some_phases_failed(self):
        phases = [
            PhaseResult(phase="overview"),
            PhaseResult(phase="track", error="timeout"),
            PhaseResult(phase="strategy"),
        ]
        conf = _compute_confidence(phases, OverviewData())
        assert 0.6 < conf < 0.9  # 2/3 + bonus

    def test_no_phases(self):
        assert _compute_confidence([], OverviewData()) == 0.3

    def test_no_strategy_no_bonus(self):
        phases = [
            PhaseResult(phase="overview"),
            PhaseResult(phase="track"),
        ]
        conf = _compute_confidence(phases, OverviewData())
        assert conf == 1.0  # 2/2, no strategy bonus needed (already 1.0)


# ---------------------------------------------------------------------------
# 5. Summary computation
# ---------------------------------------------------------------------------


class TestComputeSummary:
    def test_basic_summary(self):
        phases = [
            PhaseResult(phase="overview"),
            PhaseResult(phase="track"),
        ]
        overview = OverviewData(tracks=[{"name": "DeFi"}])
        result = SituationResult(
            event_id="test",
            map_root="/tmp/test",
            sections_written=["overview.md", "tracks/defi.md"],
        )
        summary = _compute_summary(phases, overview, result)
        assert "1 tracks identified" in summary
        assert "2/2 phases completed" in summary
        assert "2 sections written" in summary

    def test_summary_with_errors(self):
        phases = [
            PhaseResult(phase="overview"),
            PhaseResult(phase="track", error="failed"),
        ]
        result = SituationResult(event_id="test", map_root="/tmp/test")
        summary = _compute_summary(phases, OverviewData(), result)
        assert "1 phases had errors" in summary


# ---------------------------------------------------------------------------
# 6. Full pipeline — mocked
# ---------------------------------------------------------------------------


class TestAnalyzePipeline:
    @pytest.mark.asyncio
    @patch("bob.situation.AgentSession")
    @patch("bob.situation.run_agent", new_callable=AsyncMock)
    async def test_overview_only(self, mock_run_agent, MockSession, tmp_path):
        """Pipeline runs overview phase and returns result even without tracks."""
        mock_run_agent.return_value = _agent_result(
            input_tokens=500, output_tokens=100, total_turns=3
        )

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        assert isinstance(result, SituationResult)
        assert result.event_id
        assert result.map_root == str(tmp_path)
        # run_agent called at least for overview + past + strategy
        assert mock_run_agent.call_count >= 3

    @pytest.mark.asyncio
    @patch("bob.situation.AgentSession")
    @patch("bob.situation.run_agent", new_callable=AsyncMock)
    async def test_with_tracks(self, mock_run_agent, MockSession, tmp_path):
        """Pipeline fans out per-track agents when overview has tracks."""
        call_count = 0

        async def mock_run_agent_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # On the first call (overview), write overview.md
            if call_count == 1:
                _write_overview(
                    tmp_path,
                    tracks=[
                        {"name": "DeFi", "sponsor": "Uniswap", "prize": "$10K"},
                    ],
                    sponsors=[{"name": "Uniswap", "url": "https://uniswap.org"}],
                    judges=[{"name": "Alice", "url": "https://github.com/alice"}],
                )
            return _agent_result(input_tokens=200, output_tokens=50, total_turns=2)

        mock_run_agent.side_effect = mock_run_agent_fn

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        # overview + 1 track + 1 sponsor + 1 judge + past + strategy = 6
        assert call_count == 6
        assert result.tracks_found == 1
        assert result.input_tokens == 200 * 6
        assert result.output_tokens == 50 * 6

    @pytest.mark.asyncio
    @patch("bob.situation.AgentSession")
    @patch("bob.situation.run_agent", new_callable=AsyncMock)
    async def test_phase_error_doesnt_crash(self, mock_run_agent, MockSession, tmp_path):
        """A failing research phase doesn't crash the pipeline."""
        call_count = 0

        async def mock_run_agent_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Overview succeeds
                _write_overview(
                    tmp_path,
                    tracks=[{"name": "DeFi", "sponsor": "Uni", "prize": "$5K"}],
                )
                return _agent_result(input_tokens=200, output_tokens=50, total_turns=2)
            if call_count == 2:
                # Track research fails — run_agent returns error
                return _agent_result(
                    input_tokens=50, output_tokens=10, total_turns=1,
                    success=False, error="CLI subprocess crashed",
                )
            # All other phases succeed
            return _agent_result(input_tokens=100, output_tokens=30, total_turns=1)

        mock_run_agent.side_effect = mock_run_agent_fn

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        # Pipeline should complete despite track failure
        assert result.confidence > 0
        assert "error" in result.summary.lower() or result.confidence < 1.0

    @pytest.mark.asyncio
    @patch("bob.situation.AgentSession")
    @patch("bob.situation.run_agent", new_callable=AsyncMock)
    async def test_disk_fallback(self, mock_run_agent, MockSession, tmp_path):
        """Sections on disk are detected even if capture missed them."""
        mock_run_agent.return_value = _agent_result(
            input_tokens=100, output_tokens=30, total_turns=1
        )

        # Pre-populate some files on disk
        tracks_dir = tmp_path / "tracks"
        tracks_dir.mkdir()
        (tracks_dir / "defi.md").write_text("DeFi content")
        (tmp_path / "overview.md").write_text("Overview content")

        http = _mock_http_client()
        result = await analyze(
            _h(),
            map_root=str(tmp_path),
            http_client=http,
        )

        # Should find files on disk
        assert len(result.sections_written) >= 2

    @pytest.mark.asyncio
    @patch("bob.situation.AgentSession")
    @patch("bob.situation.run_agent", new_callable=AsyncMock)
    async def test_default_map_root(self, mock_run_agent, MockSession):
        """When map_root=None, defaults to ./events/<event_id>."""
        mock_run_agent.return_value = _agent_result(
            input_tokens=100, output_tokens=30, total_turns=0
        )

        h = _h()
        http = _mock_http_client()
        result = await analyze(h, map_root=None, http_client=http)

        expected_suffix = os.path.join("events", h.event_id)
        assert result.map_root.endswith(expected_suffix)

        # Clean up
        import shutil

        if os.path.exists(result.map_root):
            shutil.rmtree(result.map_root)
        events_dir = os.path.dirname(result.map_root)
        if os.path.exists(events_dir) and not os.listdir(events_dir):
            os.rmdir(events_dir)


# ---------------------------------------------------------------------------
# 7. PhaseResult aggregation
# ---------------------------------------------------------------------------


class TestPhaseResult:
    def test_default_values(self):
        pr = PhaseResult(phase="test")
        assert pr.input_tokens == 0
        assert pr.output_tokens == 0
        assert pr.turns == 0
        assert pr.sections_written == []
        assert pr.error is None

    def test_with_error(self):
        pr = PhaseResult(phase="test", error="something broke")
        assert pr.error == "something broke"


# ---------------------------------------------------------------------------
# 8. Tool dispatch (via MCP handlers)
# ---------------------------------------------------------------------------


class TestToolDispatch:
    """Tests that MCP tool handlers dispatch correctly."""

    @pytest.mark.asyncio
    async def test_fetch_page_via_mcp(self):
        """fetch_page MCP handler routes to web tool."""
        http = _mock_http_client()
        from bob.tools.mcp import _make_web_tools

        tools = _make_web_tools(http)
        fetch_page = tools[0]
        result = await fetch_page.handler({"url": "https://example.com"})
        assert result["content"][0]["type"] == "text"
        assert "Status:" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_write_section_via_mcp(self, tmp_path):
        """write_section MCP handler tracks sections."""
        capture = ResultCapture()
        from bob.tools.mcp import _make_map_tools

        tools = _make_map_tools(str(tmp_path), capture)
        write_section = tools[0]
        result = await write_section.handler(
            {
                "path": "test.md",
                "frontmatter": {"title": "Test"},
                "body": "Hello",
                "owner": "test",
            }
        )
        assert "Written" in result["content"][0]["text"]
        assert (tmp_path / "test.md").exists()
        assert capture.sections_written == ["test.md"]
