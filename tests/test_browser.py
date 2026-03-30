"""Tests for stealth-browser MCP tools and BrowserSessionManager."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# conftest.py already installed stealth_browser mock and claude_agent_sdk
# fakes permanently in sys.modules.
# Grab the shared stealth mock for assertions.
_mock_stealth = sys.modules["stealth_browser"]

from bob.tools.browser import (
    BROWSER_CLICK_TOOL,
    BROWSER_CLOSE_SESSION_TOOL,
    BROWSER_CREATE_SESSION_TOOL,
    BROWSER_EVALUATE_TOOL,
    BROWSER_EXTRACT_TEXT_TOOL,
    BROWSER_FILL_TOOL,
    BROWSER_NAVIGATE_TOOL,
    BROWSER_SAVE_SESSION_TOOL,
    BROWSER_SCREENSHOT_TOOL,
    BROWSER_SELECT_OPTION_TOOL,
    BROWSER_WAIT_FOR_NAVIGATION_TOOL,
    BrowserSession,
    BrowserSessionManager,
    HAS_STEALTH_BROWSER,
    _make_browser_tools,
)


# ── BrowserSession tests ────────────────────────────────────────────


class TestBrowserSession:
    def test_creation(self):
        session = BrowserSession(
            session_id="test-1",
            browser=MagicMock(),
            context=MagicMock(),
            page=MagicMock(),
        )
        assert session.session_id == "test-1"
        assert session.account_id is None
        assert session.created_at > 0

    def test_with_account(self):
        session = BrowserSession(
            session_id="test-2",
            browser=MagicMock(),
            context=MagicMock(),
            page=MagicMock(),
            account_id="devpost-alice",
        )
        assert session.account_id == "devpost-alice"


# ── BrowserSessionManager tests ─────────────────────────────────────


class TestBrowserSessionManager:
    @pytest.mark.asyncio
    async def test_create_session(self):
        mgr = BrowserSessionManager()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        _mock_stealth.patchright.create_stealth_browser.return_value = mock_browser
        _mock_stealth.patchright.create_stealth_context.return_value = mock_context
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        session = await mgr.create_session("sess-1")
        assert session.session_id == "sess-1"
        assert session.browser == mock_browser
        assert session.page == mock_page

    @pytest.mark.asyncio
    async def test_get_session(self):
        mgr = BrowserSessionManager()
        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()

        await mgr.create_session("sess-get")
        session = await mgr.get_session("sess-get")
        assert session.session_id == "sess-get"

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self):
        mgr = BrowserSessionManager()
        with pytest.raises(ValueError, match="No such session"):
            await mgr.get_session("nonexistent")

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self):
        mgr = BrowserSessionManager()
        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()

        await mgr.create_session("dup")
        with pytest.raises(ValueError, match="already exists"):
            await mgr.create_session("dup")

    @pytest.mark.asyncio
    async def test_close_session(self):
        mgr = BrowserSessionManager()
        mock_browser = MagicMock()
        _mock_stealth.patchright.create_stealth_browser.return_value = mock_browser
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()
        _mock_stealth.patchright.close_stealth_browser.reset_mock()

        await mgr.create_session("to-close")
        await mgr.close_session("to-close")

        _mock_stealth.patchright.close_stealth_browser.assert_called_once_with(mock_browser)
        # Session should be removed
        with pytest.raises(ValueError):
            await mgr.get_session("to-close")

    @pytest.mark.asyncio
    async def test_close_nonexistent_is_noop(self):
        mgr = BrowserSessionManager()
        await mgr.close_session("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_close_all(self):
        mgr = BrowserSessionManager()
        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()
        _mock_stealth.patchright.close_stealth_browser.reset_mock()

        await mgr.create_session("a")
        await mgr.create_session("b")
        await mgr.close_all()

        assert _mock_stealth.patchright.close_stealth_browser.call_count == 2

    @pytest.mark.asyncio
    async def test_close_all_continues_on_individual_error(self):
        mgr = BrowserSessionManager()
        browser_a = MagicMock()
        browser_b = MagicMock()
        call_count = 0

        async def create_browser_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            return browser_a if call_count == 1 else browser_b

        _mock_stealth.patchright.create_stealth_browser.side_effect = create_browser_side_effect
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()

        # First close raises, second should still be called
        _mock_stealth.patchright.close_stealth_browser.reset_mock()
        _mock_stealth.patchright.close_stealth_browser.side_effect = [
            Exception("browser crashed"),
            None,
        ]

        await mgr.create_session("err")
        await mgr.create_session("ok")
        await mgr.close_all()

        # Both sessions should be removed despite the error
        assert _mock_stealth.patchright.close_stealth_browser.call_count == 2
        # Reset side_effect for other tests
        _mock_stealth.patchright.close_stealth_browser.side_effect = None
        _mock_stealth.patchright.create_stealth_browser.side_effect = None


# ── Tool schema tests ────────────────────────────────────────────────


class TestBrowserToolSchemas:
    def test_eleven_tools_returned(self):
        mgr = BrowserSessionManager()
        tools = _make_browser_tools(mgr)
        assert len(tools) == 11

    def test_tool_names(self):
        mgr = BrowserSessionManager()
        tools = _make_browser_tools(mgr)
        names = {t.name for t in tools}
        assert names == {
            "browser_create_session",
            "browser_navigate",
            "browser_click",
            "browser_fill",
            "browser_extract_text",
            "browser_screenshot",
            "browser_close_session",
            "browser_save_session",
            "browser_evaluate",
            "browser_wait_for_navigation",
            "browser_select_option",
        }

    def test_schemas_have_required_fields(self):
        assert "session_id" in BROWSER_CREATE_SESSION_TOOL["input_schema"]["properties"]
        assert "url" in BROWSER_NAVIGATE_TOOL["input_schema"]["properties"]
        assert "selector" in BROWSER_CLICK_TOOL["input_schema"]["properties"]
        assert "value" in BROWSER_FILL_TOOL["input_schema"]["properties"]
        assert "session_id" in BROWSER_SCREENSHOT_TOOL["input_schema"]["properties"]

    def test_new_tool_schemas_have_required_fields(self):
        assert "path" in BROWSER_SAVE_SESSION_TOOL["input_schema"]["properties"]
        assert "expression" in BROWSER_EVALUATE_TOOL["input_schema"]["properties"]
        assert "url_pattern" in BROWSER_WAIT_FOR_NAVIGATION_TOOL["input_schema"]["properties"]
        assert "selector" in BROWSER_SELECT_OPTION_TOOL["input_schema"]["properties"]
        assert "value" in BROWSER_SELECT_OPTION_TOOL["input_schema"]["properties"]


# ── Tool handler tests ───────────────────────────────────────────────


class TestBrowserToolHandlers:
    @pytest.mark.asyncio
    async def test_navigate_returns_title_and_url(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Test Page")
        mock_page.url = "https://example.com"

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page
        _mock_stealth.patchright.stealth_goto.reset_mock()

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        nav_tool = next(t for t in tools if t.name == "browser_navigate")

        await create_tool.handler({"session_id": "nav-test"})
        result = await nav_tool.handler({"session_id": "nav-test", "url": "https://example.com"})

        text = result["content"][0]["text"]
        assert "https://example.com" in text
        assert "Test Page" in text

    @pytest.mark.asyncio
    async def test_click_returns_element_text(self):
        mgr = BrowserSessionManager()
        mock_el = MagicMock()
        mock_el.text_content = AsyncMock(return_value="Click Me")
        mock_el.click = AsyncMock()

        mock_page = MagicMock()
        mock_page.locator.return_value.first = mock_el

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        click_tool = next(t for t in tools if t.name == "browser_click")

        await create_tool.handler({"session_id": "click-test"})
        result = await click_tool.handler({"session_id": "click-test", "selector": "button"})

        text = result["content"][0]["text"]
        assert "Click Me" in text

    @pytest.mark.asyncio
    async def test_fill_confirms(self):
        mgr = BrowserSessionManager()
        mock_el = MagicMock()
        mock_el.fill = AsyncMock()

        mock_page = MagicMock()
        mock_page.locator.return_value.first = mock_el

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        fill_tool = next(t for t in tools if t.name == "browser_fill")

        await create_tool.handler({"session_id": "fill-test"})
        result = await fill_tool.handler({
            "session_id": "fill-test",
            "selector": "#email",
            "value": "test@example.com",
        })

        text = result["content"][0]["text"]
        assert "Filled" in text
        mock_el.fill.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_extract_text_returns_content(self):
        mgr = BrowserSessionManager()
        mock_el = MagicMock()
        mock_el.text_content = AsyncMock(return_value="Page body content")

        mock_page = MagicMock()
        mock_page.locator.return_value.first = mock_el

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        extract_tool = next(t for t in tools if t.name == "browser_extract_text")

        await create_tool.handler({"session_id": "extract-test"})
        result = await extract_tool.handler({"session_id": "extract-test"})

        text = result["content"][0]["text"]
        assert "Page body content" in text

    @pytest.mark.asyncio
    async def test_screenshot_returns_path(self, tmp_path):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock()

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        ss_tool = next(t for t in tools if t.name == "browser_screenshot")

        await create_tool.handler({"session_id": "ss-test"})
        ss_path = str(tmp_path / "shot.png")
        result = await ss_tool.handler({"session_id": "ss-test", "path": ss_path})

        text = result["content"][0]["text"]
        assert ss_path in text
        mock_page.screenshot.assert_called_once_with(path=ss_path)

    @pytest.mark.asyncio
    async def test_save_session_calls_storage_state(self, tmp_path):
        mgr = BrowserSessionManager()
        mock_context = MagicMock()
        mock_context.storage_state = AsyncMock()

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = mock_context
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        save_tool = next(t for t in tools if t.name == "browser_save_session")

        await create_tool.handler({"session_id": "save-test"})
        save_path = str(tmp_path / "session.json")
        result = await save_tool.handler({"session_id": "save-test", "path": save_path})

        text = result["content"][0]["text"]
        assert "saved" in text.lower()
        # Path is resolved to canonical form, so compare with resolved path
        resolved_path = str(Path(save_path).resolve())
        mock_context.storage_state.assert_called_once_with(path=resolved_path)

    @pytest.mark.asyncio
    async def test_save_session_sanitizes_traversal(self, tmp_path):
        """Path traversal via '..' in parent is resolved away."""
        mgr = BrowserSessionManager()
        mock_context = MagicMock()
        mock_context.storage_state = AsyncMock()

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = mock_context
        _mock_stealth.patchright.new_stealth_page.return_value = MagicMock()

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        save_tool = next(t for t in tools if t.name == "browser_save_session")

        await create_tool.handler({"session_id": "save-traversal"})
        # Attempt path traversal
        traversal_path = str(tmp_path / ".." / ".." / "etc" / "passwd")
        result = await save_tool.handler({"session_id": "save-traversal", "path": traversal_path})

        text = result["content"][0]["text"]
        assert "saved" in text.lower()
        # The resolved path should NOT contain ".."
        actual_path = mock_context.storage_state.call_args[1]["path"]
        assert ".." not in actual_path

    @pytest.mark.asyncio
    async def test_evaluate_returns_result(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=42)

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        eval_tool = next(t for t in tools if t.name == "browser_evaluate")

        await create_tool.handler({"session_id": "eval-test"})
        result = await eval_tool.handler({"session_id": "eval-test", "expression": "1 + 1"})

        text = result["content"][0]["text"]
        assert "42" in text

    @pytest.mark.asyncio
    async def test_evaluate_truncates_long_result(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        long_result = "x" * 20000
        mock_page.evaluate = AsyncMock(return_value=long_result)

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        eval_tool = next(t for t in tools if t.name == "browser_evaluate")

        await create_tool.handler({"session_id": "eval-trunc"})
        result = await eval_tool.handler({"session_id": "eval-trunc", "expression": "x"})

        text = result["content"][0]["text"]
        assert len(text) < 20000
        assert "truncated" in text

    @pytest.mark.asyncio
    async def test_wait_for_navigation_calls_wait_for_url(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.wait_for_url = AsyncMock()
        mock_page.url = "https://example.com/dashboard"

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        wait_tool = next(t for t in tools if t.name == "browser_wait_for_navigation")

        await create_tool.handler({"session_id": "wait-test"})
        result = await wait_tool.handler({
            "session_id": "wait-test",
            "url_pattern": "/dashboard",
        })

        text = result["content"][0]["text"]
        assert "dashboard" in text
        mock_page.wait_for_url.assert_called_once_with("**/dashboard**", timeout=30000)

    @pytest.mark.asyncio
    async def test_wait_for_navigation_custom_timeout(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.wait_for_url = AsyncMock()
        mock_page.url = "https://example.com/done"

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        wait_tool = next(t for t in tools if t.name == "browser_wait_for_navigation")

        await create_tool.handler({"session_id": "wait-timeout"})
        await wait_tool.handler({
            "session_id": "wait-timeout",
            "url_pattern": "/done",
            "timeout": 5000,
        })

        mock_page.wait_for_url.assert_called_once_with("**/done**", timeout=5000)

    @pytest.mark.asyncio
    async def test_select_option_calls_page_method(self):
        mgr = BrowserSessionManager()
        mock_page = MagicMock()
        mock_page.select_option = AsyncMock()

        _mock_stealth.patchright.create_stealth_browser.return_value = MagicMock()
        _mock_stealth.patchright.create_stealth_context.return_value = MagicMock()
        _mock_stealth.patchright.new_stealth_page.return_value = mock_page

        tools = _make_browser_tools(mgr)
        create_tool = next(t for t in tools if t.name == "browser_create_session")
        select_tool = next(t for t in tools if t.name == "browser_select_option")

        await create_tool.handler({"session_id": "select-test"})
        result = await select_tool.handler({
            "session_id": "select-test",
            "selector": "#country",
            "value": "US",
        })

        text = result["content"][0]["text"]
        assert "US" in text
        assert "#country" in text
        mock_page.select_option.assert_called_once_with("#country", "US")

    @pytest.mark.asyncio
    async def test_session_not_found_returns_error(self):
        mgr = BrowserSessionManager()
        tools = _make_browser_tools(mgr)
        nav_tool = next(t for t in tools if t.name == "browser_navigate")

        result = await nav_tool.handler({"session_id": "ghost", "url": "https://x.com"})
        text = result["content"][0]["text"]
        assert "Error" in text
        assert "No such session" in text


# ── HAS_STEALTH_BROWSER flag test ────────────────────────────────────


class TestStealthBrowserFlag:
    def test_has_stealth_browser_is_true_with_mock(self):
        # Since we mocked the import, HAS_STEALTH_BROWSER should be True
        assert HAS_STEALTH_BROWSER is True
