"""Telemetry: structured agent session logging and unified query runner."""

from __future__ import annotations

import json
import re
import sys
import time
import traceback as _traceback_mod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AgentEvent:
    """Single event emitted during an agent session."""

    timestamp: str  # ISO 8601
    agent: str  # e.g. "signup:bob:github"
    turn: int
    event_type: str  # tool_call, tool_result, message, error, escalation, status
    data: dict


@dataclass
class AgentResult:
    """Outcome of a single run_agent() invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_turns: int = 0
    success: bool = False
    error: str | None = None
    session_log_path: Path | None = None


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_REDACT_KEYS = {"password", "secret", "credential", "token", "totp", "api_key"}


def _redact(args: dict) -> dict:
    """Shallow copy with sensitive values replaced by '***'."""
    return {
        k: "***" if any(s in k.lower() for s in _REDACT_KEYS) else v
        for k, v in args.items()
    }


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------

_UNSAFE_RE = re.compile(r"[:/\\]|\.\.")


class AgentSession:
    """Structured JSONL logger for a single agent run."""

    def __init__(
        self,
        agent_name: str,
        log_dir: Path | None = None,
        max_turns: int = 0,
    ) -> None:
        self._agent = agent_name
        self._max_turns = max_turns
        self._events: list[AgentEvent] = []
        self._start = time.monotonic()
        self._turn = 0

        base = log_dir or Path(user_data_dir("bob")) / "logs"
        base.mkdir(parents=True, exist_ok=True)

        safe_name = _UNSAFE_RE.sub("-", agent_name)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._path = base / f"{safe_name}-{ts}.jsonl"
        self._fh = open(self._path, "a", encoding="utf-8")  # noqa: SIM115

    # -- internal ----------------------------------------------------------

    def _elapsed(self) -> int:
        return int(time.monotonic() - self._start)

    def _write(self, event: AgentEvent) -> None:
        self._events.append(event)
        self._fh.write(json.dumps(vars(event), default=str) + "\n")
        self._fh.flush()

        # Live status on stderr
        summary = event.event_type
        if event.event_type == "tool_call":
            summary = f"tool:{event.data.get('tool', '')}"
        elif event.event_type == "error":
            summary = f"ERR:{event.data.get('error_type', '')}"
        max_label = f"/{self._max_turns}" if self._max_turns else ""
        print(
            f"[{self._agent}] Turn {event.turn}{max_label}"
            f" | {summary} | {self._elapsed()}s",
            file=sys.stderr,
        )

    # -- public logging methods --------------------------------------------

    def log_tool_call(self, tool_name: str, args: dict, turn: int) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="tool_call",
                data={"tool": tool_name, "args": _redact(args)},
            )
        )

    def log_tool_result(
        self, tool_name: str, result_summary: str, duration_ms: int, turn: int
    ) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="tool_result",
                data={
                    "tool": tool_name,
                    "summary": result_summary[:200],
                    "duration_ms": duration_ms,
                },
            )
        )

    def log_message(self, role: str, content: str, turn: int) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="message",
                data={"role": role, "content": content[:500]},
            )
        )

    def log_error(
        self, error_type: str, error_msg: str, traceback_str: str, turn: int
    ) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="error",
                data={
                    "error_type": error_type,
                    "error_msg": error_msg,
                    "traceback": traceback_str,
                },
            )
        )
        # Red error on stderr when terminal supports it
        msg = f"[{self._agent}] ERROR {error_type}: {error_msg}"
        try:
            print(f"\033[91m{msg}\033[0m", file=sys.stderr)
        except Exception:
            print(msg, file=sys.stderr)

    def log_escalation(self, field_name: str, description: str, turn: int) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="escalation",
                data={"field": field_name, "description": description},
            )
        )

    def log_status(self, msg: str, turn: int) -> None:
        self._turn = turn
        self._write(
            AgentEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=self._agent,
                turn=turn,
                event_type="status",
                data={"message": msg},
            )
        )

    # -- summary / lifecycle -----------------------------------------------

    def replay(self) -> str:
        """Return a human-readable formatted log of all events."""
        lines: list[str] = []
        for e in self._events:
            ts = e.timestamp.split("T")[1].rstrip("Z") if "T" in e.timestamp else e.timestamp
            prefix = f"[{ts}] T{e.turn} "
            if e.event_type == "tool_call":
                args_str = ", ".join(f"{k}={v!r}" for k, v in e.data.get("args", {}).items())
                lines.append(f"{prefix}CALL  {e.data.get('tool', '?')}({args_str})")
            elif e.event_type == "tool_result":
                lines.append(
                    f"{prefix}RESULT {e.data.get('tool', '?')}"
                    f" ({e.data.get('duration_ms', 0)}ms)"
                    f" {e.data.get('summary', '')}"
                )
            elif e.event_type == "message":
                lines.append(f"{prefix}{e.data.get('role', '?').upper()} {e.data.get('content', '')}")
            elif e.event_type == "error":
                lines.append(f"{prefix}ERROR {e.data.get('error_type', '')}: {e.data.get('error_msg', '')}")
            elif e.event_type == "escalation":
                lines.append(f"{prefix}ESCALATION [{e.data.get('field', '')}] {e.data.get('description', '')}")
            elif e.event_type == "status":
                lines.append(f"{prefix}STATUS {e.data.get('message', '')}")
            else:
                lines.append(f"{prefix}{e.event_type} {e.data}")
        return "\n".join(lines)

    def summary(self) -> str:
        tool_events = [e for e in self._events if e.event_type == "tool_call"]
        last_tool = tool_events[-1].data.get("tool", "?") if tool_events else "-"
        max_label = f"/{self._max_turns}" if self._max_turns else ""
        return (
            f"Turn {self._turn}{max_label}"
            f" | {len(tool_events)} tools"
            f" | last: {last_tool}"
            f" | {self._elapsed()}s"
        )

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    @property
    def log_path(self) -> Path:
        return self._path

    @property
    def events(self) -> list[AgentEvent]:
        return list(self._events)


# ---------------------------------------------------------------------------
# run_agent — unified query runner
# ---------------------------------------------------------------------------


async def run_agent(
    prompt: str,
    options: object,  # ClaudeAgentOptions
    session: AgentSession,
    auth_env: dict | None = None,
) -> AgentResult:
    """Run a Claude Agent SDK query loop with structured telemetry."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock, query

    # Merge auth env (e.g. ANTHROPIC_API_KEY) into options.env
    if auth_env:
        if not getattr(options, "env", None):
            options.env = {}  # type: ignore[attr-defined]
        options.env.update(auth_env)  # type: ignore[attr-defined]

    result = AgentResult(session_log_path=session.log_path)
    turn = 0

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn += 1
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        session.log_tool_call(block.name, block.input or {}, turn)
                    elif hasattr(block, "text"):
                        session.log_message("assistant", block.text, turn)

            if isinstance(message, ResultMessage):
                result.total_turns = getattr(message, "num_turns", turn)
                if message.usage:
                    u = message.usage
                    result.input_tokens += (
                        u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0)
                    )
                    result.output_tokens += u.get("output_tokens", 0)

        result.success = True
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        session.log_error(
            type(e).__name__, str(e), _traceback_mod.format_exc(), turn
        )
        result.error = str(e)
    finally:
        session.close()

    return result


# ---------------------------------------------------------------------------
# instrument_tools — automatic MCP tool logging wrapper
# ---------------------------------------------------------------------------


def instrument_tools(
    tools: list,  # list[SdkMcpTool]
    session: AgentSession,
) -> list:
    """Wrap MCP tool handlers to log calls and results via *session*."""
    from claude_agent_sdk import SdkMcpTool

    def _wrap(name: str, handler):  # noqa: ANN001
        async def wrapper(args: dict) -> dict:
            session.log_tool_call(name, args, session._turn)
            start = time.time()
            try:
                result = await handler(args)
                ms = int((time.time() - start) * 1000)
                summary = ""
                if isinstance(result, dict) and "content" in result:
                    for c in result["content"]:
                        if isinstance(c, dict) and c.get("type") == "text":
                            summary = c["text"][:200]
                            break
                session.log_tool_result(name, summary, ms, session._turn)
                return result
            except Exception as exc:
                session.log_error(type(exc).__name__, str(exc), "", session._turn)
                raise

        return wrapper

    return [
        SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=_wrap(t.name, t.handler),
        )
        for t in tools
    ]
