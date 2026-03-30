"""Tests for the Team Composer — data models, serialization, and agent pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml

from bob.telemetry import AgentResult

from bob.composer import (
    PortfolioPlan,
    TeamMember,
    TrackAssignment,
    _COMPOSER_PROMPT,
    _parse_portfolio,
    compose_teams,
    portfolio_from_dict,
    portfolio_to_dict,
)
from bob.roster.models import (
    Availability,
    MemberProfile,
    PresentationStyle,
    Skill,
)
from bob.roster.store import RosterStore


# ── Helpers ──────────────────────────────────────────────────────────


def _member(member_id: str = "alice", **kw) -> MemberProfile:
    defaults = dict(
        member_id=member_id,
        display_name=member_id.title(),
        skills=[Skill("Python", "backend", 5)],
        interests=["AI"],
        presentation_style=PresentationStyle.TECHNICAL,
        availability=Availability(timezone="UTC"),
    )
    defaults.update(kw)
    return MemberProfile(**defaults)


def _plan() -> PortfolioPlan:
    return PortfolioPlan(
        event_id="abc123",
        event_name="ETHGlobal 2026",
        situation_map_root="/tmp/maps/abc123",
        assignments=[
            TrackAssignment(
                track_name="DeFi",
                track_prize="$10,000",
                play_type="execution",
                ev_score=0.75,
                project_idea="Lending aggregator",
                sponsor_apis=["Uniswap v4", "Aave v3"],
                team=[
                    TeamMember(member_id="alice", role="presenter", reason="DeFi expert"),
                    TeamMember(member_id="bob", role="builder", reason="Solidity depth"),
                ],
                persona_ids=["alice-ethglobal-2026", "bob-ethglobal-2026"],
                registration_platform="devpost",
            ),
            TrackAssignment(
                track_name="AI/ML",
                track_prize="$5,000",
                play_type="moonshot",
                ev_score=0.3,
                project_idea="On-chain ML inference",
                sponsor_apis=["OpenAI"],
                team=[
                    TeamMember(member_id="carol", role="builder", reason="ML expert"),
                ],
                persona_ids=["carol-ethglobal-2026"],
                registration_platform="ethglobal",
            ),
        ],
        unassigned_tracks=["Gaming"],
        budget_notes="3 members allocated",
    )


def _agent_result(**kw):
    """Create an AgentResult for testing."""
    defaults = dict(input_tokens=100, output_tokens=50, total_turns=1, success=True)
    defaults.update(kw)
    return AgentResult(**defaults)


# ── Data model tests ─────────────────────────────────────────────────


class TestTeamMember:
    def test_creation(self):
        tm = TeamMember(member_id="alice", role="presenter", reason="strong demos")
        assert tm.member_id == "alice"
        assert tm.role == "presenter"
        assert tm.reason == "strong demos"


class TestTrackAssignment:
    def test_creation(self):
        ta = TrackAssignment(
            track_name="DeFi",
            track_prize="$10K",
            play_type="execution",
            ev_score=0.8,
            project_idea="DEX aggregator",
            sponsor_apis=["Uniswap"],
            team=[TeamMember("alice", "builder", "Solidity")],
            persona_ids=["alice-eth"],
            registration_platform="devpost",
        )
        assert ta.track_name == "DeFi"
        assert ta.play_type == "execution"
        assert len(ta.team) == 1
        assert ta.team[0].member_id == "alice"


class TestPortfolioPlan:
    def test_creation(self):
        plan = _plan()
        assert plan.event_id == "abc123"
        assert len(plan.assignments) == 2
        assert plan.unassigned_tracks == ["Gaming"]
        assert plan.budget_notes == "3 members allocated"

    def test_empty_plan(self):
        plan = PortfolioPlan(
            event_id="",
            event_name="",
            situation_map_root="",
            assignments=[],
            unassigned_tracks=[],
            budget_notes="",
        )
        assert len(plan.assignments) == 0


# ── Serialization tests ─────────────────────────────────────────────


class TestPortfolioSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        original = _plan()
        d = portfolio_to_dict(original)
        raw = yaml.safe_dump(d, sort_keys=False)
        loaded = yaml.safe_load(raw)
        restored = portfolio_from_dict(loaded)

        assert restored.event_id == original.event_id
        assert restored.event_name == original.event_name
        assert len(restored.assignments) == 2
        assert restored.assignments[0].track_name == "DeFi"
        assert restored.assignments[0].play_type == "execution"
        assert restored.assignments[0].ev_score == 0.75
        assert len(restored.assignments[0].team) == 2
        assert restored.assignments[0].team[0].member_id == "alice"
        assert restored.assignments[0].team[0].role == "presenter"
        assert restored.assignments[0].persona_ids == ["alice-ethglobal-2026", "bob-ethglobal-2026"]
        assert restored.assignments[1].play_type == "moonshot"
        assert restored.unassigned_tracks == ["Gaming"]

    def test_to_dict_yaml_safe(self):
        plan = _plan()
        d = portfolio_to_dict(plan)
        raw = yaml.safe_dump(d)
        assert isinstance(raw, str)


# ── _parse_portfolio tests ───────────────────────────────────────────


class TestParsePortfolio:
    def test_from_agent_dict(self):
        data = {
            "event_id": "xyz",
            "event_name": "Test Hack",
            "assignments": [
                {
                    "track_name": "AI",
                    "track_prize": "$5k",
                    "play_type": "moonshot",
                    "ev_score": 0.3,
                    "project_idea": "AGI in 48h",
                    "sponsor_apis": ["OpenAI"],
                    "team": [{"member_id": "eve", "role": "builder", "reason": "ML expert"}],
                    "persona_ids": ["eve-test-hack"],
                    "registration_platform": "devfolio",
                },
            ],
            "unassigned_tracks": ["Web3"],
            "budget_notes": "All in",
        }
        plan = _parse_portfolio(data, "/tmp/maps")
        assert plan.event_id == "xyz"
        assert plan.situation_map_root == "/tmp/maps"
        assert plan.assignments[0].play_type == "moonshot"
        assert plan.assignments[0].team[0].role == "builder"
        assert plan.unassigned_tracks == ["Web3"]

    def test_missing_optional_fields(self):
        data = {
            "event_id": "min",
            "event_name": "Minimal",
            "assignments": [
                {
                    "track_name": "Solo",
                    "play_type": "execution",
                    "team": [],
                },
            ],
        }
        plan = _parse_portfolio(data, "/tmp")
        assert plan.assignments[0].track_prize == ""
        assert plan.assignments[0].ev_score == 0.0
        assert plan.assignments[0].sponsor_apis == []
        assert plan.assignments[0].persona_ids == []
        assert plan.unassigned_tracks == []


# ── System prompt tests ──────────────────────────────────────────────


class TestComposerPrompt:
    def test_prompt_includes_portfolio_rules(self):
        assert "Execution plays" in _COMPOSER_PROMPT
        assert "Moonshots" in _COMPOSER_PROMPT
        assert "Philosophical entry" in _COMPOSER_PROMPT

    def test_prompt_has_roster_placeholder(self):
        assert "{roster_yaml}" in _COMPOSER_PROMPT

    def test_prompt_includes_instructions(self):
        assert "submit_portfolio" in _COMPOSER_PROMPT
        assert "list_sections" in _COMPOSER_PROMPT
        assert "read_section" in _COMPOSER_PROMPT


# ── compose_teams agent test ─────────────────────────────────────────


class TestComposeTeams:
    @pytest.mark.asyncio
    @patch("bob.composer.AgentSession")
    @patch("bob.composer.run_agent", new_callable=AsyncMock)
    async def test_compose_returns_plan(self, mock_run_agent, MockSession, tmp_path):
        """Mocked agent calls submit_portfolio, compose_teams returns plan."""
        fixture_data = {
            "event_id": "test-event",
            "event_name": "Test Hackathon",
            "assignments": [
                {
                    "track_name": "DeFi",
                    "track_prize": "$10K",
                    "play_type": "execution",
                    "ev_score": 0.8,
                    "project_idea": "DEX aggregator",
                    "sponsor_apis": ["Uniswap"],
                    "team": [
                        {"member_id": "alice", "role": "presenter", "reason": "DeFi expert"},
                    ],
                    "persona_ids": ["alice-test-hackathon"],
                    "registration_platform": "devpost",
                },
            ],
            "unassigned_tracks": [],
            "budget_notes": "Full team allocated",
        }

        async def fake_run_agent(prompt, options, session):
            server = options.mcp_servers["composer"]
            tools = server["tools"]
            submit_tool = next(t for t in tools if t.name == "submit_portfolio")
            await submit_tool.handler(fixture_data)
            return _agent_result(input_tokens=1000, output_tokens=200, total_turns=5)

        mock_run_agent.side_effect = fake_run_agent

        store = RosterStore(base_dir=tmp_path / "roster")
        store.save_member(_member("alice"))

        plan = await compose_teams(
            event_url="https://example.com/hack",
            map_root=str(tmp_path / "map"),
            roster=store,
        )

        assert plan.event_id == "test-event"
        assert len(plan.assignments) == 1
        assert plan.assignments[0].track_name == "DeFi"
        assert plan.assignments[0].team[0].member_id == "alice"

    @pytest.mark.asyncio
    @patch("bob.composer.AgentSession")
    @patch("bob.composer.run_agent", new_callable=AsyncMock)
    async def test_compose_no_submit_returns_empty(self, mock_run_agent, MockSession, tmp_path):
        """Agent that doesn't call submit_portfolio returns empty plan."""
        mock_run_agent.return_value = _agent_result()

        store = RosterStore(base_dir=tmp_path / "roster")
        store.save_member(_member("alice"))

        plan = await compose_teams(
            event_url="https://example.com",
            map_root=str(tmp_path / "map"),
            roster=store,
        )

        assert plan.assignments == []
        assert "did not produce" in plan.budget_notes

    @pytest.mark.asyncio
    @patch("bob.composer.AgentSession")
    @patch("bob.composer.run_agent", new_callable=AsyncMock)
    async def test_compose_prompt_includes_roster(self, mock_run_agent, MockSession, tmp_path):
        """System prompt should contain serialized roster data."""
        captured_prompt = None

        async def fake_run_agent(prompt, options, session):
            nonlocal captured_prompt
            captured_prompt = options.system_prompt

            server = options.mcp_servers["composer"]
            submit = next(t for t in server["tools"] if t.name == "submit_portfolio")
            await submit.handler({
                "event_id": "x",
                "event_name": "X",
                "assignments": [],
                "unassigned_tracks": [],
                "budget_notes": "",
            })
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        store = RosterStore(base_dir=tmp_path / "roster")
        store.save_member(_member("alice", display_name="Alice Chen"))

        await compose_teams(
            event_url="https://example.com",
            map_root=str(tmp_path / "map"),
            roster=store,
        )

        assert captured_prompt is not None
        assert "Alice Chen" in captured_prompt
        assert "Execution plays" in captured_prompt
