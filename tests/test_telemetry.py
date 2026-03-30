"""Tests for telemetry — AgentSession, run_agent, instrument_tools."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, patch

import pytest

# conftest.py already installed shared fakes in sys.modules
_sdk = sys.modules["claude_agent_sdk"]
_FakeResultMessage = _sdk.ResultMessage
_FakeAssistantMessage = _sdk.AssistantMessage
_FakeToolUseBlock = _sdk.ToolUseBlock
_FakeSdkMcpTool = _sdk.SdkMcpTool

from bob.telemetry import (
    AgentEvent,
    AgentResult,
    AgentSession,
    _redact,
    instrument_tools,
    run_agent,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_session(tmp_path, name="test:agent", max_turns=10):
    return AgentSession(name, log_dir=tmp_path, max_turns=max_turns)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


def _tool_use_block(name, input_dict=None):
    block = _FakeToolUseBlock()
    block.name = name
    block.input = input_dict
    return block


def _text_block(text):
    return type("TextBlock", (), {"text": text})()


def _assistant_msg(*blocks):
    return _FakeAssistantMessage(content=list(blocks))


def _result_msg(num_turns=1, usage=None, is_error=False):
    return _FakeResultMessage(
        num_turns=num_turns,
        is_error=is_error,
        usage=usage,
    )


# ====================================================================
# AgentSession
# ====================================================================


class TestAgentSessionInit:
    def test_creates_jsonl_file(self, tmp_path):
        s = _make_session(tmp_path)
        assert s.log_path.exists()
        assert s.log_path.suffix == ".jsonl"
        s.close()

    def test_log_path_contains_safe_name(self, tmp_path):
        s = _make_session(tmp_path, name="signup:bob:github")
        assert "signup-bob-github" in s.log_path.name
        s.close()

    def test_log_dir_created_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        s = AgentSession("x", log_dir=nested)
        assert nested.is_dir()
        assert s.log_path.exists()
        s.close()


class TestSafeFilename:
    @pytest.mark.parametrize(
        "raw,expected_substr",
        [
            ("signup:bob:github", "signup-bob-github"),
            ("a/b\\c", "a-b-c"),
            ("foo..bar", "foo-bar"),
            ("simple", "simple"),
        ],
    )
    def test_safe_filename_substitutions(self, tmp_path, raw, expected_substr):
        s = _make_session(tmp_path, name=raw)
        assert expected_substr in s.log_path.name
        s.close()


class TestLogToolCall:
    def test_writes_event(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("click", {"selector": "#btn"}, 1)
        assert len(s.events) == 1
        e = s.events[0]
        assert e.event_type == "tool_call"
        assert e.data["tool"] == "click"
        assert e.turn == 1
        s.close()

    def test_correct_fields_in_jsonl(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("fill", {"value": "hello"}, 3)
        s.close()
        records = _read_jsonl(s.log_path)
        assert len(records) == 1
        r = records[0]
        assert r["event_type"] == "tool_call"
        assert r["agent"] == "test:agent"
        assert r["turn"] == 3
        assert r["data"]["tool"] == "fill"

    def test_flushes_immediately(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("click", {}, 1)
        # Read file before close — should already have content
        content = s.log_path.read_text()
        assert "tool_call" in content
        s.close()

    @pytest.mark.parametrize("key", ["password", "secret", "credential", "token", "totp"])
    def test_redacts_sensitive_keys(self, tmp_path, key):
        s = _make_session(tmp_path)
        s.log_tool_call("fill", {key: "hunter2", "username": "bob"}, 1)
        e = s.events[0]
        assert e.data["args"][key] == "***"
        assert e.data["args"]["username"] == "bob"
        s.close()

    def test_redacts_compound_keys(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("fill", {"api_token": "abc", "user_password": "xyz"}, 1)
        e = s.events[0]
        assert e.data["args"]["api_token"] == "***"
        assert e.data["args"]["user_password"] == "***"
        s.close()


class TestLogToolResult:
    def test_truncates_to_200(self, tmp_path):
        s = _make_session(tmp_path)
        long_summary = "x" * 500
        s.log_tool_result("click", long_summary, 100, 1)
        e = s.events[0]
        assert len(e.data["summary"]) == 200
        assert e.event_type == "tool_result"
        s.close()

    def test_records_duration(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_result("click", "ok", 42, 1)
        assert s.events[0].data["duration_ms"] == 42
        s.close()


class TestLogMessage:
    def test_truncates_to_500(self, tmp_path):
        s = _make_session(tmp_path)
        long_msg = "y" * 1000
        s.log_message("assistant", long_msg, 1)
        e = s.events[0]
        assert len(e.data["content"]) == 500
        assert e.event_type == "message"
        s.close()

    def test_role_recorded(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_message("system", "hello", 1)
        assert s.events[0].data["role"] == "system"
        s.close()


class TestLogError:
    def test_captures_error_fields(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_error("TimeoutError", "timed out", "traceback line 1\nline 2", 3)
        e = s.events[0]
        assert e.event_type == "error"
        assert e.data["error_type"] == "TimeoutError"
        assert e.data["error_msg"] == "timed out"
        assert "traceback line 1" in e.data["traceback"]
        assert e.turn == 3
        s.close()


class TestLogEscalation:
    def test_correct_event_type(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_escalation("captcha", "CAPTCHA detected", 2)
        e = s.events[0]
        assert e.event_type == "escalation"
        assert e.data["field"] == "captcha"
        assert e.data["description"] == "CAPTCHA detected"
        s.close()


class TestLogStatus:
    def test_correct_event_type(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_status("navigating to page", 1)
        e = s.events[0]
        assert e.event_type == "status"
        assert e.data["message"] == "navigating to page"
        s.close()


class TestSummary:
    def test_includes_turn_and_last_tool(self, tmp_path):
        s = _make_session(tmp_path, max_turns=20)
        s.log_tool_call("click", {}, 5)
        s.log_tool_call("fill", {}, 7)
        summary = s.summary()
        assert "7/20" in summary
        assert "2 tools" in summary
        assert "fill" in summary
        s.close()

    def test_no_tools_shows_dash(self, tmp_path):
        s = _make_session(tmp_path)
        assert "last: -" in s.summary()
        s.close()


class TestClose:
    def test_file_handle_closed(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("x", {}, 1)
        s.close()
        assert s._fh.closed

    def test_double_close_safe(self, tmp_path):
        s = _make_session(tmp_path)
        s.close()
        s.close()  # should not raise


class TestEventsGrow:
    def test_events_accumulate(self, tmp_path):
        s = _make_session(tmp_path)
        assert len(s.events) == 0
        s.log_tool_call("a", {}, 1)
        assert len(s.events) == 1
        s.log_message("assistant", "hi", 1)
        assert len(s.events) == 2
        s.log_status("ok", 2)
        assert len(s.events) == 3
        s.close()


class TestJsonlValidity:
    def test_each_line_is_valid_json(self, tmp_path):
        s = _make_session(tmp_path)
        s.log_tool_call("a", {"k": "v"}, 1)
        s.log_tool_result("a", "ok", 10, 1)
        s.log_message("assistant", "done", 1)
        s.log_error("Err", "msg", "tb", 2)
        s.log_escalation("f", "d", 2)
        s.log_status("s", 2)
        s.close()
        records = _read_jsonl(s.log_path)
        assert len(records) == 6
        for r in records:
            assert "timestamp" in r
            assert "agent" in r
            assert "turn" in r
            assert "event_type" in r
            assert "data" in r


# ====================================================================
# AgentResult
# ====================================================================


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult()
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.total_turns == 0
        assert r.success is False
        assert r.error is None
        assert r.session_log_path is None

    def test_creation_with_values(self, tmp_path):
        r = AgentResult(
            input_tokens=100,
            output_tokens=50,
            total_turns=3,
            success=True,
            error=None,
            session_log_path=tmp_path / "test.jsonl",
        )
        assert r.input_tokens == 100
        assert r.success is True


# ====================================================================
# _redact
# ====================================================================


class TestRedact:
    def test_redacts_exact_keys(self):
        assert _redact({"password": "x"}) == {"password": "***"}
        assert _redact({"secret": "x"}) == {"secret": "***"}
        assert _redact({"credential": "x"}) == {"credential": "***"}
        assert _redact({"token": "x"}) == {"token": "***"}
        assert _redact({"totp": "x"}) == {"totp": "***"}

    def test_redacts_substring_match(self):
        assert _redact({"api_token": "abc"})["api_token"] == "***"
        assert _redact({"user_password": "abc"})["user_password"] == "***"

    def test_preserves_safe_keys(self):
        r = _redact({"username": "bob", "selector": "#btn"})
        assert r == {"username": "bob", "selector": "#btn"}

    def test_case_insensitive(self):
        assert _redact({"Password": "x"})["Password"] == "***"
        assert _redact({"API_TOKEN": "x"})["API_TOKEN"] == "***"


# ====================================================================
# run_agent
# ====================================================================


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_tool_call_logged(self, tmp_path):
        block = _tool_use_block("browser_click", {"selector": "#go"})
        messages = [_assistant_msg(block), _result_msg(num_turns=1)]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)

        assert result.success is True
        tool_events = [e for e in s.events if e.event_type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].data["tool"] == "browser_click"

    @pytest.mark.asyncio
    async def test_text_block_logged_as_message(self, tmp_path):
        block = _text_block("I will click the button")
        messages = [_assistant_msg(block), _result_msg()]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)

        msg_events = [e for e in s.events if e.event_type == "message"]
        assert len(msg_events) == 1
        assert msg_events[0].data["content"] == "I will click the button"

    @pytest.mark.asyncio
    async def test_tokens_accumulated(self, tmp_path):
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 10,
        }
        messages = [_result_msg(num_turns=3, usage=usage)]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)

        assert result.input_tokens == 130  # 100 + 20 + 10
        assert result.output_tokens == 50
        assert result.total_turns == 3
        assert result.success is True

    @pytest.mark.asyncio
    async def test_tokens_accumulate_across_messages(self, tmp_path):
        u1 = {"input_tokens": 50, "output_tokens": 20,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        u2 = {"input_tokens": 30, "output_tokens": 10,
               "cache_creation_input_tokens": 5, "cache_read_input_tokens": 0}
        messages = [
            _assistant_msg(_text_block("first")),
            _result_msg(num_turns=1, usage=u1),
            _assistant_msg(_text_block("second")),
            _result_msg(num_turns=2, usage=u2),
        ]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)

        assert result.input_tokens == 85  # 50 + 30 + 5
        assert result.output_tokens == 30  # 20 + 10

    @pytest.mark.asyncio
    async def test_exception_logged(self, tmp_path):
        async def fake_query(**kw):
            yield _assistant_msg(_text_block("starting"))
            raise RuntimeError("connection lost")

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)

        assert result.success is False
        assert result.error == "connection lost"
        err_events = [e for e in s.events if e.event_type == "error"]
        assert len(err_events) == 1
        assert err_events[0].data["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_reraised(self, tmp_path):
        async def fake_query(**kw):
            yield _assistant_msg(_text_block("start"))
            raise KeyboardInterrupt()

        s = _make_session(tmp_path)
        with pytest.raises(KeyboardInterrupt):
            with patch.object(_sdk, "query", fake_query):
                await run_agent("do it", object(), s)

    @pytest.mark.asyncio
    async def test_session_closed_in_finally(self, tmp_path):
        messages = [_result_msg()]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            await run_agent("do it", object(), s)
        assert s._fh.closed

    @pytest.mark.asyncio
    async def test_session_closed_after_exception(self, tmp_path):
        async def fake_query(**kw):
            yield _assistant_msg(_text_block("start"))
            raise ValueError("boom")

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            await run_agent("do it", object(), s)
        assert s._fh.closed

    @pytest.mark.asyncio
    async def test_session_log_path_set(self, tmp_path):
        messages = [_result_msg()]

        async def fake_query(**kw):
            for m in messages:
                yield m

        s = _make_session(tmp_path)
        with patch.object(_sdk, "query", fake_query):
            result = await run_agent("do it", object(), s)
        assert result.session_log_path == s.log_path


# ====================================================================
# instrument_tools
# ====================================================================


class TestInstrumentTools:
    def _make_tool(self, name="test_tool", handler=None):
        if handler is None:
            handler = AsyncMock(
                return_value={"content": [{"type": "text", "text": "result ok"}]}
            )
        return _FakeSdkMcpTool(
            name=name,
            description=f"A {name}",
            input_schema={"type": "object"},
            handler=handler,
        )

    def test_returns_same_count_and_names(self, tmp_path):
        s = _make_session(tmp_path)
        tools = [self._make_tool("a"), self._make_tool("b"), self._make_tool("c")]
        wrapped = instrument_tools(tools, s)
        assert len(wrapped) == 3
        assert [t.name for t in wrapped] == ["a", "b", "c"]
        s.close()

    @pytest.mark.asyncio
    async def test_wrapper_calls_original_handler(self, tmp_path):
        handler = AsyncMock(return_value={"content": []})
        tool = self._make_tool(handler=handler)
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)
        result = await wrapped[0].handler({"x": 1})
        handler.assert_awaited_once_with({"x": 1})
        assert result == {"content": []}
        s.close()

    @pytest.mark.asyncio
    async def test_returns_same_result(self, tmp_path):
        expected = {"content": [{"type": "text", "text": "hello world"}]}
        handler = AsyncMock(return_value=expected)
        tool = self._make_tool(handler=handler)
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)
        result = await wrapped[0].handler({})
        assert result == expected
        s.close()

    @pytest.mark.asyncio
    async def test_tool_call_event_logged(self, tmp_path):
        tool = self._make_tool()
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)
        await wrapped[0].handler({"selector": "#btn"})
        call_events = [e for e in s.events if e.event_type == "tool_call"]
        assert len(call_events) == 1
        assert call_events[0].data["tool"] == "test_tool"
        assert call_events[0].data["args"]["selector"] == "#btn"
        s.close()

    @pytest.mark.asyncio
    async def test_tool_result_event_logged(self, tmp_path):
        tool = self._make_tool()
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)
        await wrapped[0].handler({})
        result_events = [e for e in s.events if e.event_type == "tool_result"]
        assert len(result_events) == 1
        assert result_events[0].data["tool"] == "test_tool"
        assert "duration_ms" in result_events[0].data
        assert result_events[0].data["summary"] == "result ok"
        s.close()

    @pytest.mark.asyncio
    async def test_password_redacted_in_log_but_not_handler(self, tmp_path):
        handler = AsyncMock(return_value={"content": []})
        tool = self._make_tool(handler=handler)
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)
        await wrapped[0].handler({"password": "secret123", "user": "bob"})

        # Handler receives the real password
        handler.assert_awaited_once_with({"password": "secret123", "user": "bob"})

        # But logged event has it redacted
        call_events = [e for e in s.events if e.event_type == "tool_call"]
        assert call_events[0].data["args"]["password"] == "***"
        assert call_events[0].data["args"]["user"] == "bob"
        s.close()

    @pytest.mark.asyncio
    async def test_exception_logged_and_reraised(self, tmp_path):
        handler = AsyncMock(side_effect=RuntimeError("browser crashed"))
        tool = self._make_tool(handler=handler)
        s = _make_session(tmp_path)
        wrapped = instrument_tools([tool], s)

        with pytest.raises(RuntimeError, match="browser crashed"):
            await wrapped[0].handler({})

        err_events = [e for e in s.events if e.event_type == "error"]
        assert len(err_events) == 1
        assert err_events[0].data["error_type"] == "RuntimeError"
        assert err_events[0].data["error_msg"] == "browser crashed"
        s.close()

    @pytest.mark.asyncio
    async def test_closure_captures_correct_tool_name(self, tmp_path):
        """Each wrapper logs the right tool name (no closure-over-loop-var bug)."""
        tools = [self._make_tool(f"tool_{i}") for i in range(3)]
        s = _make_session(tmp_path)
        wrapped = instrument_tools(tools, s)

        for w in wrapped:
            await w.handler({})

        call_events = [e for e in s.events if e.event_type == "tool_call"]
        logged_names = [e.data["tool"] for e in call_events]
        assert logged_names == ["tool_0", "tool_1", "tool_2"]
        s.close()
