"""Platform account models for multi-identity management."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Platform(str, Enum):
    DEVPOST = "devpost"
    ETHGLOBAL = "ethglobal"
    GITHUB = "github"
    LUMA = "luma"
    DEVFOLIO = "devfolio"


@dataclass
class PlatformAccount:
    account_id: str
    platform: Platform
    username: str
    credential_ref: str  # opaque vault key — never a raw password
    member_id: str  # FK to MemberProfile
    fingerprint_config: dict = field(default_factory=dict)  # serialized PlatformConfig
    session_state_path: str | None = None  # path to Patchright storage_state JSON
    last_login: str | None = None  # ISO 8601 datetime
    status: str = "active"  # active | suspended | needs-reauth
