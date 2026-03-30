"""Shared fixtures and SDK mocking for tests.

Sets up claude_agent_sdk fakes and stealth_browser mocks once so all test
files share the same class identities and module references.  This prevents
isinstance() mismatches when modules are reimported across test files, and
avoids patch.dict restoring sys.modules and breaking module references.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock


# ── Shared fake SDK classes ──────────────────────────────────────────
# These MUST be defined exactly once and reused everywhere.


class FakeResultMessage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeAssistantMessage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeClaudeAgentOptions:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeSdkMcpTool:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


FakeToolUseBlock = type("ToolUseBlock", (), {})


def _fake_create_server(name, tools):
    return {"name": name, "tools": tools}


# ── Install SDK into sys.modules if the real SDK is not present ──────

if "claude_agent_sdk" not in sys.modules:
    _sdk = MagicMock()
    sys.modules["claude_agent_sdk"] = _sdk

_sdk_mod = sys.modules["claude_agent_sdk"]
_sdk_mod.ResultMessage = FakeResultMessage
_sdk_mod.AssistantMessage = FakeAssistantMessage
_sdk_mod.ClaudeAgentOptions = FakeClaudeAgentOptions
_sdk_mod.SdkMcpTool = FakeSdkMcpTool
_sdk_mod.ToolUseBlock = FakeToolUseBlock
_sdk_mod.create_sdk_mcp_server = _fake_create_server


# ── Stealth browser mock — permanently in sys.modules ───────────────
# Using patch.dict("sys.modules", ...) reverts ALL sys.modules changes on
# exit, removing modules imported during the `with` block.  This breaks
# @patch("bob.registration.query") because it resolves to a
# different module object.  Instead, install the mock permanently.

mock_stealth = MagicMock()
mock_stealth.patchright.create_stealth_browser = AsyncMock()
mock_stealth.patchright.create_stealth_context = AsyncMock()
mock_stealth.patchright.new_stealth_page = AsyncMock()
mock_stealth.patchright.stealth_goto = AsyncMock()
mock_stealth.patchright.close_stealth_browser = AsyncMock()
mock_stealth.config.PlatformConfig = MagicMock
mock_stealth.config.HardwareConfig = MagicMock
mock_stealth.config.NetworkConfig = MagicMock
mock_stealth.config.LocaleConfig = MagicMock

if "stealth_browser" not in sys.modules:
    sys.modules["stealth_browser"] = mock_stealth
    sys.modules["stealth_browser.patchright"] = mock_stealth.patchright
    sys.modules["stealth_browser.config"] = mock_stealth.config
