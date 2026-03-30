"""Resolver chain — unified field resolution for registration, signup, and login agents.

Replaces duplicated resolve_field closures with an extensible chain-of-responsibility
dispatch. Each Resolver handles specific field types; the chain tries them in order
and returns the first non-None result (or "unknown").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from claude_agent_sdk import SdkMcpTool

from bob.accounts.registry import AccountRegistry
from bob.roster.store import RosterStore


# ---------------------------------------------------------------------------
# Context + Protocol
# ---------------------------------------------------------------------------


@dataclass
class ResolverContext:
    member_id: str
    platform: str
    roster: RosterStore
    registry: AccountRegistry


class Resolver(Protocol):
    async def resolve(self, field_name: str, context: ResolverContext) -> str | None:
        """Return value if this resolver handles the field, None to pass to next."""
        ...


# ---------------------------------------------------------------------------
# Built-in resolvers
# ---------------------------------------------------------------------------


class AttributeResolver:
    """Look up member.attributes[field_name]."""

    async def resolve(self, field_name: str, context: ResolverContext) -> str | None:
        member = context.roster.load_member(context.member_id)
        if member is None:
            return None
        return member.attributes.get(field_name)


class TOTPResolver:
    """Generate TOTP codes from vault-stored secrets."""

    _FIELD_ALIASES = {"2fa_code", "totp_code", "verification_code", "mfa_code"}

    async def resolve(self, field_name: str, context: ResolverContext) -> str | None:
        if field_name not in self._FIELD_ALIASES:
            return None
        totp_ref = f"{context.member_id}-{context.platform}-totp"
        secret = context.registry._vault.get_credential(totp_ref)
        if not secret:
            return None
        import pyotp

        return pyotp.TOTP(secret).now()


class CredentialResolver:
    """Resolve passwords from vault."""

    _FIELD_ALIASES = {"password", "passwd", "pass"}

    async def resolve(self, field_name: str, context: ResolverContext) -> str | None:
        if field_name not in self._FIELD_ALIASES:
            return None
        accounts = context.registry.get_accounts_for_member(context.member_id)
        account = next(
            (a for a in accounts if a.platform.value == context.platform), None
        )
        if account is None:
            return None
        return context.registry.get_credential(account.account_id)


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


class ResolverChain:
    def __init__(self, resolvers: list[Resolver] | None = None):
        self._resolvers = resolvers or []

    def add(self, resolver: Resolver) -> None:
        self._resolvers.append(resolver)

    async def resolve(self, field_name: str, context: ResolverContext) -> str:
        for resolver in self._resolvers:
            result = await resolver.resolve(field_name, context)
            if result is not None:
                return result
        return "unknown"


def create_default_chain() -> ResolverChain:
    return ResolverChain([AttributeResolver(), TOTPResolver(), CredentialResolver()])


# ---------------------------------------------------------------------------
# MCP tool factory
# ---------------------------------------------------------------------------

RESOLVE_FIELD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "field_name": {
            "type": "string",
            "description": "Name of the field to resolve",
        },
        "member_id": {
            "type": "string",
            "description": "Member ID (optional, uses default if omitted)",
        },
    },
    "required": ["field_name"],
}


def make_resolve_field_tool(
    chain: ResolverChain,
    default_member_id: str,
    platform: str,
    roster: RosterStore,
    registry: AccountRegistry,
) -> SdkMcpTool:
    async def handler(args: dict) -> dict:
        context = ResolverContext(
            member_id=args.get("member_id", default_member_id),
            platform=platform,
            roster=roster,
            registry=registry,
        )
        value = await chain.resolve(args["field_name"], context)
        return {"content": [{"type": "text", "text": value}]}

    return SdkMcpTool(
        name="resolve_field",
        description="Look up a field value for a team member. Returns the value or 'unknown'.",
        input_schema=RESOLVE_FIELD_SCHEMA,
        handler=handler,
    )
