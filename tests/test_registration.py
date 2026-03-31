"""Tests for the registration orchestrator."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest.py already:
#  - patched sys.modules["claude_agent_sdk"] with shared fakes
#  - installed stealth_browser mock permanently in sys.modules

from bob.telemetry import AgentResult

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.composer import (
    PortfolioPlan,
    TeamMember,
    TrackAssignment,
)
from bob.registration import (
    RegistrationReport,
    RegistrationResult,
    RegistrationTask,
    _build_registration_tasks,
    _get_system_prompt,
    register_teams,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_account(
    account_id: str = "acc-1",
    platform: Platform = Platform.DEVPOST,
    member_id: str = "alice",
) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=f"user-{member_id}",
        credential_ref=f"vault://{account_id}",
        member_id=member_id,
    )


def _make_assignment(
    track_name: str = "DeFi",
    play_type: str = "execution",
    member_ids: list[str] | None = None,
    platform: str = "devpost",
) -> TrackAssignment:
    if member_ids is None:
        member_ids = ["alice"]
    return TrackAssignment(
        track_name=track_name,
        track_prize="$10K",
        play_type=play_type,
        ev_score=0.8,
        project_idea="Test project",
        sponsor_apis=["TestAPI"],
        team=[TeamMember(m, "builder", "skill match") for m in member_ids],
        persona_ids=[f"{m}-test" for m in member_ids],
        registration_platform=platform,
    )


def _make_portfolio(
    assignments: list[TrackAssignment] | None = None,
) -> PortfolioPlan:
    return PortfolioPlan(
        event_id="evt-1",
        event_name="Test Hackathon",
        situation_map_root="/tmp/maps/evt-1",
        assignments=assignments or [_make_assignment()],
        unassigned_tracks=[],
        budget_notes="",
    )


def _agent_result(**kw):
    """Create an AgentResult for testing."""
    defaults = dict(input_tokens=100, output_tokens=50, total_turns=1, success=True)
    defaults.update(kw)
    return AgentResult(**defaults)


# ── Data model tests ─────────────────────────────────────────────────


class TestRegistrationTask:
    def test_creation(self):
        assignment = _make_assignment()
        task = RegistrationTask(
            track_assignment=assignment,
            account_id="acc-1",
            hackathon_url="https://example.com/hack",
            team_name="VCN - DeFi",
            team_description="Test project",
        )
        assert task.account_id == "acc-1"
        assert task.hackathon_url == "https://example.com/hack"
        assert task.team_name == "VCN - DeFi"


class TestRegistrationResult:
    def test_success(self):
        task = RegistrationTask(
            track_assignment=_make_assignment(),
            account_id="acc-1",
            hackathon_url="https://example.com",
            team_name="VCN",
            team_description="desc",
        )
        result = RegistrationResult(
            task=task,
            success=True,
            confirmation_url="https://example.com/confirm",
            screenshot_path="/tmp/shot.png",
        )
        assert result.success is True
        assert result.confirmation_url == "https://example.com/confirm"

    def test_failure(self):
        task = RegistrationTask(
            track_assignment=_make_assignment(),
            account_id="acc-1",
            hackathon_url="https://example.com",
            team_name="VCN",
            team_description="desc",
        )
        result = RegistrationResult(
            task=task,
            success=False,
            error="Login required",
        )
        assert result.success is False
        assert result.error == "Login required"

    def test_defaults(self):
        task = RegistrationTask(
            track_assignment=_make_assignment(),
            account_id="acc-1",
            hackathon_url="https://example.com",
            team_name="VCN",
            team_description="desc",
        )
        result = RegistrationResult(task=task, success=True)
        assert result.confirmation_url == ""
        assert result.screenshot_path == ""
        assert result.error == ""


class TestRegistrationReport:
    def test_creation(self):
        report = RegistrationReport(event_url="https://example.com/hack")
        assert report.event_url == "https://example.com/hack"
        assert report.results == []
        assert report.total_turns == 0
        assert report.input_tokens == 0
        assert report.output_tokens == 0


# ── _build_registration_tasks tests ──────────────────────────────────


class TestBuildRegistrationTasks:
    def test_builds_tasks_from_portfolio(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        portfolio = _make_portfolio([
            _make_assignment(track_name="DeFi", member_ids=["alice"]),
            _make_assignment(track_name="AI", member_ids=["alice"]),
        ])

        tasks = _build_registration_tasks(portfolio, "https://hack.com", registry)
        assert len(tasks) == 2
        assert tasks[0].track_assignment.track_name == "DeFi"
        assert tasks[0].account_id == "acc-alice"
        assert "VCN" in tasks[0].team_name

    def test_skips_track_without_account(self, tmp_path):
        registry = _make_registry(tmp_path)
        portfolio = _make_portfolio([
            _make_assignment(track_name="Ghost", member_ids=["bob"]),
        ])

        tasks = _build_registration_tasks(portfolio, "https://hack.com", registry)
        assert len(tasks) == 0

    def test_team_description_includes_project(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-1", member_id="alice"))

        portfolio = _make_portfolio([_make_assignment()])
        tasks = _build_registration_tasks(portfolio, "https://hack.com", registry)

        assert "Test project" in tasks[0].team_description
        assert "TestAPI" in tasks[0].team_description

    def test_uses_first_members_account(self, tmp_path):
        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))
        registry.save_account(_make_account(account_id="acc-bob", member_id="bob"))

        portfolio = _make_portfolio([
            _make_assignment(member_ids=["alice", "bob"]),
        ])
        tasks = _build_registration_tasks(portfolio, "https://hack.com", registry)
        assert tasks[0].account_id == "acc-alice"


# ── Platform prompt tests ────────────────────────────────────────────


class TestPlatformPrompts:
    def test_devpost_prompt(self):
        prompt = _get_system_prompt("devpost")
        assert "Devpost" in prompt

    def test_ethglobal_prompt(self):
        prompt = _get_system_prompt("ethglobal")
        assert "ETHGlobal" in prompt

    def test_luma_prompt(self):
        prompt = _get_system_prompt("luma")
        assert "Luma" in prompt

    def test_unknown_platform_uses_generic(self):
        prompt = _get_system_prompt("unknown-platform")
        assert "registration" in prompt.lower()
        assert "Devpost" not in prompt
        assert "ETHGlobal" not in prompt

    def test_case_insensitive(self):
        prompt = _get_system_prompt("DEVPOST")
        assert "Devpost" in prompt

    def test_all_prompts_include_escalation_instructions(self):
        for platform in ["devpost", "ethglobal", "luma", "unknown"]:
            prompt = _get_system_prompt(platform)
            assert "resolve_field" in prompt
            assert "escalate" in prompt
            assert "record_platform_field" in prompt


# ── register_teams agent test ────────────────────────────────────────


class TestRegisterTeams:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_register_returns_report(self, mock_run_agent, MockSession, tmp_path):
        """Mocked agent calls confirm_registration, report is returned."""

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            tools = server["tools"]
            confirm = next(t for t in tools if t.name == "confirm_registration")
            await confirm.handler({
                "success": True,
                "confirmation_url": "https://example.com/confirmed",
                "screenshot_path": "/tmp/proof.png",
            })
            return _agent_result(input_tokens=500, output_tokens=100, total_turns=3)

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        portfolio = _make_portfolio([_make_assignment()])

        report = await register_teams(
            portfolio=portfolio,
            hackathon_url="https://example.com/hack",
            registry=registry,
        )

        assert isinstance(report, RegistrationReport)
        assert len(report.results) == 1
        assert report.results[0].success is True
        assert report.results[0].confirmation_url == "https://example.com/confirmed"

    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_register_token_tracking(self, mock_run_agent, MockSession, tmp_path):
        """Token counts accumulate across registrations."""

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            confirm = next(t for t in server["tools"] if t.name == "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result(input_tokens=300, output_tokens=80, total_turns=2)

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))
        registry.save_account(_make_account(account_id="acc-bob", member_id="bob"))

        portfolio = _make_portfolio([
            _make_assignment(track_name="DeFi", member_ids=["alice"]),
            _make_assignment(track_name="AI", member_ids=["bob"]),
        ])

        report = await register_teams(
            portfolio=portfolio,
            hackathon_url="https://example.com",
            registry=registry,
        )

        assert len(report.results) == 2
        assert report.input_tokens == 600  # 300 * 2
        assert report.output_tokens == 160  # 80 * 2

    @pytest.mark.asyncio
    async def test_register_no_tasks_returns_empty(self, tmp_path):
        """Empty portfolio -> empty report, no agent calls."""
        registry = _make_registry(tmp_path)
        portfolio = _make_portfolio(assignments=[])

        report = await register_teams(
            portfolio=portfolio,
            hackathon_url="https://example.com",
            registry=registry,
        )

        assert report.results == []
        assert report.input_tokens == 0


# ── Escalation tool tests ──────────────────────────────────────────


def _make_roster(tmp_path):
    from bob.roster.store import RosterStore

    roster_dir = tmp_path / "roster"
    roster_dir.mkdir(exist_ok=True)
    return RosterStore(base_dir=roster_dir)


def _make_member(member_id="alice", attributes=None):
    from bob.roster.models import MemberProfile

    return MemberProfile(
        member_id=member_id,
        display_name=member_id.capitalize(),
        attributes=attributes or {},
    )


def _make_field_registry(tmp_path):
    from bob.platform_fields import PlatformFieldRegistry

    fr_dir = tmp_path / "platform_fields"
    fr_dir.mkdir(exist_ok=True)
    return PlatformFieldRegistry(base_dir=fr_dir)


def _get_tool(server, name):
    """Extract a tool by name from a fake registration server."""
    return next(t for t in server["tools"] if t.name == name)


class TestResolveField:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_resolve_field_returns_value(self, mock_run_agent, MockSession, tmp_path):
        """resolve_field returns attribute value when member has it."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", {"wallet_address": "0xABC"}))

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            resolve = _get_tool(server, "resolve_field")
            result = await resolve.handler({"field_name": "wallet_address", "member_id": "alice"})
            assert result["content"][0]["text"] == "0xABC"

            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
        )

    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_resolve_field_missing_attribute_returns_unknown(self, mock_run_agent, MockSession, tmp_path):
        """resolve_field returns 'unknown' when attribute not in profile."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", {}))

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            resolve = _get_tool(server, "resolve_field")
            result = await resolve.handler({"field_name": "shirt_size", "member_id": "alice"})
            assert result["content"][0]["text"] == "unknown"

            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
        )

    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_resolve_field_member_not_found_returns_unknown(self, mock_run_agent, MockSession, tmp_path):
        """resolve_field returns 'unknown' for nonexistent member."""
        roster = _make_roster(tmp_path)

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            resolve = _get_tool(server, "resolve_field")
            result = await resolve.handler({"field_name": "email", "member_id": "ghost"})
            assert result["content"][0]["text"] == "unknown"

            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
        )


class TestEscalateTool:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_escalate_calls_handler_and_persists(self, mock_run_agent, MockSession, tmp_path):
        """escalate calls the handler, writes to roster, and records platform field."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", {}))
        field_registry = _make_field_registry(tmp_path)

        async def mock_handler(field_name, description, context):
            return "0xDEADBEEF"

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            escalate = _get_tool(server, "escalate")
            result = await escalate.handler({
                "field_name": "wallet_address",
                "description": "Ethereum wallet address",
                "context": "Registration form requires it",
            })
            # Handler return value is passed back to agent
            assert result["content"][0]["text"] == "0xDEADBEEF"

            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
            field_registry=field_registry,
            escalation_handler=mock_handler,
        )

        # Verify value was written to member profile
        updated_member = roster.load_member("alice")
        assert updated_member is not None
        assert updated_member.attributes["wallet_address"] == "0xDEADBEEF"

        # Verify field was recorded in platform field registry
        fields = field_registry.get_fields("devpost")
        assert len(fields) == 1
        assert fields[0].name == "wallet_address"
        assert fields[0].required is True


class TestRecordPlatformField:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_record_platform_field_writes_to_registry(self, mock_run_agent, MockSession, tmp_path):
        """record_platform_field adds field to PlatformFieldRegistry."""
        field_registry = _make_field_registry(tmp_path)

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            record = _get_tool(server, "record_platform_field")
            result = await record.handler({
                "platform": "ethglobal",
                "field_name": "github_url",
                "label": "GitHub profile URL",
                "required": True,
            })
            assert "Recorded" in result["content"][0]["text"]

            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            field_registry=field_registry,
        )

        fields = field_registry.get_fields("ethglobal")
        assert len(fields) == 1
        assert fields[0].name == "github_url"
        assert fields[0].label == "GitHub profile URL"
        assert fields[0].required is True


# ── Profile data threading tests ───────────────────────────────────


class TestProfileDataThreading:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_user_message_includes_member_attributes(self, mock_run_agent, MockSession, tmp_path):
        """User message sent to agent includes member attributes and skills."""
        roster = _make_roster(tmp_path)
        from bob.roster.models import MemberProfile, Skill

        member = MemberProfile(
            member_id="alice",
            display_name="Alice",
            skills=[Skill(name="Solidity", domain="blockchain", depth=4)],
            interests=["DeFi", "ZK proofs"],
            attributes={"wallet_address": "0xABC", "email": "alice@example.com"},
        )
        roster.save_member(member)

        captured_prompt = {}

        async def fake_run_agent(prompt, options, session, **kwargs):
            captured_prompt["text"] = prompt
            server = options.mcp_servers["registration"]
            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
        )

        prompt_text = captured_prompt["text"]
        assert "wallet_address: 0xABC" in prompt_text
        assert "email: alice@example.com" in prompt_text
        assert "Solidity" in prompt_text
        assert "DeFi" in prompt_text
        assert "Member ID: alice" in prompt_text

        # Sensitive fields must NOT leak into agent prompt
        assert "credential_ref" not in prompt_text
        assert "vault://" not in prompt_text
        assert "session_state_path" not in prompt_text
        assert "fingerprint_config" not in prompt_text

    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_user_message_includes_persona_bio(self, mock_run_agent, MockSession, tmp_path):
        """User message includes generated persona bio."""
        roster = _make_roster(tmp_path)
        from bob.roster.models import MemberProfile, Skill

        member = MemberProfile(
            member_id="alice",
            display_name="Alice",
            skills=[Skill(name="Rust", domain="systems", depth=5)],
            interests=["WebAssembly"],
        )
        roster.save_member(member)

        captured_prompt = {}

        async def fake_run_agent(prompt, options, session, **kwargs):
            captured_prompt["text"] = prompt
            server = options.mcp_servers["registration"]
            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
        )

        prompt_text = captured_prompt["text"]
        assert "Persona bio (short):" in prompt_text
        assert "Alice" in prompt_text

    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_register_teams_accepts_field_registry(self, mock_run_agent, MockSession, tmp_path):
        """register_teams works when field_registry and escalation_handler are passed."""
        field_registry = _make_field_registry(tmp_path)

        async def noop_handler(f, d, c):
            return "test"

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            confirm = _get_tool(server, "confirm_registration")
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        report = await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            field_registry=field_registry,
            escalation_handler=noop_handler,
        )

        assert len(report.results) == 1
        assert report.results[0].success is True


# ── Full flow test ─────────────────────────────────────────────────


class TestFullEscalationFlow:
    @pytest.mark.asyncio
    @patch("bob.registration.AgentSession")
    @patch("bob.registration.run_agent", new_callable=AsyncMock)
    async def test_resolve_then_escalate_then_confirm(self, mock_run_agent, MockSession, tmp_path):
        """Simulates: resolve_field → unknown → escalate → fill → record → confirm."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", {"email": "alice@example.com"}))
        field_registry = _make_field_registry(tmp_path)

        async def mock_handler(field_name, description, context):
            return "0xNEWWALLET"

        async def fake_run_agent(prompt, options, session, **kwargs):
            server = options.mcp_servers["registration"]
            resolve = _get_tool(server, "resolve_field")
            escalate = _get_tool(server, "escalate")
            record = _get_tool(server, "record_platform_field")
            confirm = _get_tool(server, "confirm_registration")

            # Step 1: resolve email → found
            r1 = await resolve.handler({"field_name": "email", "member_id": "alice"})
            assert r1["content"][0]["text"] == "alice@example.com"

            # Step 2: resolve wallet → unknown
            r2 = await resolve.handler({"field_name": "wallet_address", "member_id": "alice"})
            assert r2["content"][0]["text"] == "unknown"

            # Step 3: escalate wallet
            r3 = await escalate.handler({
                "field_name": "wallet_address",
                "description": "ETH wallet",
                "context": "registration form",
            })
            assert r3["content"][0]["text"] == "0xNEWWALLET"

            # Step 4: record the field
            await record.handler({
                "platform": "devpost",
                "field_name": "wallet_address",
                "label": "ETH wallet",
                "required": True,
            })

            # Step 5: confirm
            await confirm.handler({"success": True})
            return _agent_result()

        mock_run_agent.side_effect = fake_run_agent

        registry = _make_registry(tmp_path)
        registry.save_account(_make_account(account_id="acc-alice", member_id="alice"))

        report = await register_teams(
            portfolio=_make_portfolio(),
            hackathon_url="https://example.com",
            registry=registry,
            roster=roster,
            field_registry=field_registry,
            escalation_handler=mock_handler,
        )

        assert report.results[0].success is True

        # Wallet should be persisted on member
        member = roster.load_member("alice")
        assert member.attributes["wallet_address"] == "0xNEWWALLET"

        # Field should be recorded in registry
        fields = field_registry.get_fields("devpost")
        wallet_fields = [f for f in fields if f.name == "wallet_address"]
        assert len(wallet_fields) >= 1
