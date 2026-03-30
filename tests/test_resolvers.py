"""Tests for the resolver chain — field resolution dispatch."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest.py already installed shared fakes in sys.modules
_FakeSdkMcpTool = sys.modules["claude_agent_sdk"].SdkMcpTool

from bob.accounts.models import Platform, PlatformAccount
from bob.accounts.registry import AccountRegistry
from bob.accounts.vault import FileVault
from bob.resolvers import (
    AttributeResolver,
    CredentialResolver,
    ResolverChain,
    ResolverContext,
    TOTPResolver,
    create_default_chain,
    make_resolve_field_tool,
)
from bob.roster.models import MemberProfile
from bob.roster.store import RosterStore


# ── Helpers ──────────────────────────────────────────────────────────


def _make_roster(tmp_path) -> RosterStore:
    roster_dir = tmp_path / "roster"
    roster_dir.mkdir(exist_ok=True)
    return RosterStore(base_dir=roster_dir)


def _make_registry(tmp_path) -> AccountRegistry:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(exist_ok=True)
    vault = FileVault(base_dir=vault_dir)
    reg_dir = tmp_path / "accounts"
    reg_dir.mkdir(exist_ok=True)
    return AccountRegistry(base_dir=reg_dir, vault=vault)


def _make_member(member_id="alice", **extra_attrs):
    attrs = dict(extra_attrs)
    return MemberProfile(
        member_id=member_id,
        display_name=member_id.capitalize(),
        attributes=attrs,
    )


def _make_account(
    account_id="acc-alice",
    platform=Platform.DEVPOST,
    member_id="alice",
) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        platform=platform,
        username=f"user-{member_id}",
        credential_ref=f"cred-{account_id}",
        member_id=member_id,
    )


def _ctx(roster, registry, member_id="alice", platform="devpost") -> ResolverContext:
    return ResolverContext(
        member_id=member_id,
        platform=platform,
        roster=roster,
        registry=registry,
    )


# ── ResolverChain ────────────────────────────────────────────────────


class TestResolverChain:
    @pytest.mark.asyncio
    async def test_empty_chain_returns_unknown(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        chain = ResolverChain([])
        result = await chain.resolve("anything", _ctx(roster, registry))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_single_resolver_returns_value(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", wallet_address="0xABC"))
        registry = _make_registry(tmp_path)

        chain = ResolverChain([AttributeResolver()])
        result = await chain.resolve("wallet_address", _ctx(roster, registry))
        assert result == "0xABC"

    @pytest.mark.asyncio
    async def test_chain_short_circuits(self, tmp_path):
        """First resolver hit wins; second resolver is never called."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", name="Alice"))
        registry = _make_registry(tmp_path)

        second = AsyncMock(return_value="should not reach")
        chain = ResolverChain([AttributeResolver()])
        chain.add(MagicMock(resolve=second))

        result = await chain.resolve("name", _ctx(roster, registry))
        assert result == "Alice"
        second.assert_not_called()

    @pytest.mark.asyncio
    async def test_chain_fallthrough_returns_unknown(self, tmp_path):
        """All resolvers miss → 'unknown'."""
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)

        r1 = MagicMock(resolve=AsyncMock(return_value=None))
        r2 = MagicMock(resolve=AsyncMock(return_value=None))
        chain = ResolverChain([r1, r2])

        result = await chain.resolve("nonexistent", _ctx(roster, registry))
        assert result == "unknown"
        r1.resolve.assert_called_once()
        r2.resolve.assert_called_once()


# ── AttributeResolver ───────────────────────────────────────────────


class TestAttributeResolver:
    @pytest.mark.asyncio
    async def test_returns_value_when_field_exists(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", email="alice@example.com"))
        registry = _make_registry(tmp_path)

        resolver = AttributeResolver()
        result = await resolver.resolve("email", _ctx(roster, registry))
        assert result == "alice@example.com"

    @pytest.mark.asyncio
    async def test_returns_none_when_field_missing(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice"))
        registry = _make_registry(tmp_path)

        resolver = AttributeResolver()
        result = await resolver.resolve("nonexistent", _ctx(roster, registry))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_member_not_found(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)

        resolver = AttributeResolver()
        result = await resolver.resolve("email", _ctx(roster, registry, member_id="ghost"))
        assert result is None


# ── TOTPResolver ─────────────────────────────────────────────────────


def _install_mock_pyotp():
    """Install a mock pyotp module so the inline import inside TOTPResolver works."""
    mock_pyotp = MagicMock()
    mock_totp_instance = MagicMock()
    mock_totp_instance.now.return_value = "123456"
    mock_pyotp.TOTP.return_value = mock_totp_instance
    sys.modules["pyotp"] = mock_pyotp
    return mock_pyotp


class TestTOTPResolver:
    @pytest.mark.asyncio
    async def test_returns_code_when_secret_in_vault(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        registry._vault.store_credential("alice-devpost-totp", "JBSWY3DPEHPK3PXP")

        mock_pyotp = _install_mock_pyotp()
        try:
            resolver = TOTPResolver()
            result = await resolver.resolve("2fa_code", _ctx(roster, registry))
        finally:
            sys.modules.pop("pyotp", None)

        assert result == "123456"
        mock_pyotp.TOTP.assert_called_once_with("JBSWY3DPEHPK3PXP")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_secret(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)

        # No secret stored — resolver returns None before importing pyotp
        resolver = TOTPResolver()
        result = await resolver.resolve("2fa_code", _ctx(roster, registry))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_2fa_field(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        registry._vault.store_credential("alice-devpost-totp", "JBSWY3DPEHPK3PXP")

        resolver = TOTPResolver()
        result = await resolver.resolve("email", _ctx(roster, registry))
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("alias", ["2fa_code", "totp_code", "verification_code", "mfa_code"])
    async def test_handles_all_aliases(self, alias, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        registry._vault.store_credential("alice-devpost-totp", "JBSWY3DPEHPK3PXP")

        mock_pyotp = _install_mock_pyotp()
        mock_pyotp.TOTP.return_value.now.return_value = "654321"
        try:
            resolver = TOTPResolver()
            result = await resolver.resolve(alias, _ctx(roster, registry))
        finally:
            sys.modules.pop("pyotp", None)

        assert result == "654321"


# ── CredentialResolver ───────────────────────────────────────────────


class TestCredentialResolver:
    @pytest.mark.asyncio
    async def test_returns_password_from_vault(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)
        registry._vault.store_credential(account.credential_ref, "s3cret!")

        resolver = CredentialResolver()
        result = await resolver.resolve("password", _ctx(roster, registry))
        assert result == "s3cret!"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_account(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)

        resolver = CredentialResolver()
        result = await resolver.resolve("password", _ctx(roster, registry))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_password_field(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)
        registry._vault.store_credential(account.credential_ref, "s3cret!")

        resolver = CredentialResolver()
        result = await resolver.resolve("email", _ctx(roster, registry))
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("alias", ["password", "passwd", "pass"])
    async def test_handles_all_aliases(self, alias, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        account = _make_account()
        registry.save_account(account)
        registry._vault.store_credential(account.credential_ref, "hunter2")

        resolver = CredentialResolver()
        result = await resolver.resolve(alias, _ctx(roster, registry))
        assert result == "hunter2"


# ── make_resolve_field_tool ──────────────────────────────────────────


class TestMakeResolveFieldTool:
    def test_returns_tool_with_correct_name_and_schema(self, tmp_path):
        roster = _make_roster(tmp_path)
        registry = _make_registry(tmp_path)
        chain = create_default_chain()

        tool = make_resolve_field_tool(chain, "alice", "devpost", roster, registry)
        assert tool.name == "resolve_field"
        assert "field_name" in tool.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_handler_delegates_to_chain(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", email="a@b.com"))
        registry = _make_registry(tmp_path)
        chain = create_default_chain()

        tool = make_resolve_field_tool(chain, "alice", "devpost", roster, registry)
        result = await tool.handler({"field_name": "email"})
        assert result == {"content": [{"type": "text", "text": "a@b.com"}]}

    @pytest.mark.asyncio
    async def test_default_member_id_used_when_not_in_args(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", city="SF"))
        registry = _make_registry(tmp_path)
        chain = create_default_chain()

        tool = make_resolve_field_tool(chain, "alice", "devpost", roster, registry)
        # No member_id in args — should use default "alice"
        result = await tool.handler({"field_name": "city"})
        assert result == {"content": [{"type": "text", "text": "SF"}]}

    @pytest.mark.asyncio
    async def test_explicit_member_id_overrides_default(self, tmp_path):
        roster = _make_roster(tmp_path)
        roster.save_member(_make_member("alice", city="SF"))
        roster.save_member(_make_member("bob", city="NYC"))
        registry = _make_registry(tmp_path)
        chain = create_default_chain()

        tool = make_resolve_field_tool(chain, "alice", "devpost", roster, registry)
        result = await tool.handler({"field_name": "city", "member_id": "bob"})
        assert result == {"content": [{"type": "text", "text": "NYC"}]}


# ── create_default_chain ─────────────────────────────────────────────


class TestCreateDefaultChain:
    def test_includes_all_three_resolvers(self):
        chain = create_default_chain()
        types = [type(r).__name__ for r in chain._resolvers]
        assert types == ["AttributeResolver", "TOTPResolver", "CredentialResolver"]
