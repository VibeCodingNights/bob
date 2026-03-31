"""Stealth-browser MCP tools + session manager.

Provides 11 MCP tools for browser automation within agent phases.
Stealth-browser is an optional dependency — this module degrades gracefully
when it is not installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guard stealth-browser imports
# ---------------------------------------------------------------------------

try:
    from stealth_browser.patchright import (
        create_stealth_browser,
        create_stealth_context,
        new_stealth_page,
        stealth_goto,
        close_stealth_browser,
    )
    from stealth_browser.config import PlatformConfig, HardwareConfig, NetworkConfig, LocaleConfig

    HAS_STEALTH_BROWSER = True
except ImportError:
    HAS_STEALTH_BROWSER = False


def _require_stealth_browser() -> None:
    if not HAS_STEALTH_BROWSER:
        raise RuntimeError(
            "stealth-browser is not installed. "
            "Install with: pip install stealth-browser"
        )


# ---------------------------------------------------------------------------
# Reconstruct PlatformConfig from serialized dict
# ---------------------------------------------------------------------------


def _dict_to_platform_config(d: dict) -> Any:
    """Reconstruct a stealth_browser PlatformConfig from a plain dict."""
    _require_stealth_browser()
    hw = d.get("hardware", {})
    nw = d.get("network", {})
    lc = d.get("locale", {})
    return PlatformConfig(
        platform=d["platform"],
        platform_key=d["platform_key"],
        user_agent=d["user_agent"],
        window_size=d["window_size"],
        viewport_width=d["viewport_width"],
        viewport_height=d["viewport_height"],
        platform_version=d["platform_version"],
        hardware=HardwareConfig(
            cores=hw.get("cores", 8),
            memory=hw.get("memory", 16),
            gpu=hw.get("gpu", ""),
        ),
        network=NetworkConfig(
            downlink=nw.get("downlink", 50),
            rtt=nw.get("rtt", 30),
        ),
        locale=LocaleConfig(
            timezone=lc.get("timezone", "America/Los_Angeles"),
            timezone_offset=lc.get("timezone_offset", 480),
            locale=lc.get("locale", "en-US"),
            languages=lc.get("languages", ["en-US", "en"]),
        ),
        touch_enabled=d.get("touch_enabled", False),
    )


# ---------------------------------------------------------------------------
# Native engine wrappers — make sync StealthBrowser look like async Patchright
# ---------------------------------------------------------------------------


class AsyncNativeLocatorWrapper:
    """Wraps StealthBrowser element interactions to match Patchright's Locator API."""

    def __init__(self, sb: Any, selector: str):
        self._sb = sb
        self._selector = selector

    @property
    def first(self) -> "AsyncNativeLocatorWrapper":
        return self  # native engine doesn't need .first

    async def click(self) -> None:
        await asyncio.to_thread(self._sb.click, self._selector)

    async def fill(self, value: str) -> None:
        await asyncio.to_thread(self._sb.fill, self._selector, value)

    async def text_content(self) -> str | None:
        return await asyncio.to_thread(self._sb.get_text, self._selector)

    async def select_option(self, value: str) -> None:
        # StealthBrowser has no select_option — use JS
        script = (
            f"document.querySelector('{self._selector}').value = "
            f"'{value}';"
            f"document.querySelector('{self._selector}')"
            f".dispatchEvent(new Event('change', {{bubbles: true}}))"
        )
        await asyncio.to_thread(self._sb.execute_script, script)


class AsyncNativePageWrapper:
    """Makes a sync StealthBrowser look like an async Patchright Page for MCP tool handlers."""

    def __init__(self, sb: Any):
        self._sb = sb

    async def goto(self, url: str, **kwargs: Any) -> None:
        await asyncio.to_thread(self._sb.navigate, url)

    def locator(self, selector: str) -> AsyncNativeLocatorWrapper:
        return AsyncNativeLocatorWrapper(self._sb, selector)

    async def evaluate(self, expression: str) -> Any:
        return await asyncio.to_thread(self._sb.execute_script, expression)

    async def wait_for_url(self, pattern: str, **kwargs: Any) -> None:
        timeout = kwargs.get("timeout", 30000) / 1000
        # Strip glob wildcards that Patchright uses
        substring = pattern.strip("*")
        await asyncio.to_thread(self._sb.wait_for_url, substring, timeout)

    async def screenshot(self, **kwargs: Any) -> str:
        path = kwargs.get("path", "")
        return await asyncio.to_thread(self._sb.screenshot, path or None)

    async def select_option(self, selector: str, value: str) -> None:
        loc = self.locator(selector)
        await loc.select_option(value)

    @property
    def url(self) -> str:
        return self._sb.get_url()

    async def title(self) -> str:
        return await asyncio.to_thread(self._sb.get_title)


class AsyncNativeContextWrapper:
    """Wraps StealthBrowser to provide a context-like interface (storage_state)."""

    def __init__(self, sb: Any):
        self._sb = sb

    async def storage_state(self, path: str | None = None) -> dict:
        """Save browser state. Native engine uses profile_dir for persistence.

        We extract cookies via JS and save them; localStorage is persisted
        automatically by the browser profile directory.
        """
        import json

        cookies_js = "JSON.stringify(document.cookie.split('; ').map(c => { let [k,v] = c.split('='); return {name:k, value:v||''}; }))"
        cookies_str = await asyncio.to_thread(self._sb.execute_script, cookies_js)
        cookies = json.loads(cookies_str) if cookies_str else []
        state = {"cookies": cookies, "origins": []}
        if path:
            import pathlib

            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_text(json.dumps(state, indent=2))
        return state


# ---------------------------------------------------------------------------
# BrowserSession + BrowserSessionManager
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    session_id: str
    browser: Any  # Patchright Browser or StealthBrowser instance
    context: Any  # Patchright BrowserContext or AsyncNativeContextWrapper
    page: Any  # active Page or AsyncNativePageWrapper
    account_id: str | None = None
    engine: str = "patchright"  # "patchright" or "native"
    created_at: float = field(default_factory=time.time)


def _find_chrome_binary() -> str:
    """Find the system Chrome binary path, OS-agnostic."""
    import platform as _platform
    import shutil

    system = _platform.system()
    if system == "Darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(path):
            return path
    elif system == "Linux":
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                return found
    elif system == "Windows":
        for path in (
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ):
            if os.path.exists(path):
                return path
    raise RuntimeError(
        "Chrome not found. Install Google Chrome or pass cdp_endpoint manually."
    )


def _find_free_port() -> int:
    """Find a free TCP port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def launch_chrome_cdp(
    port: int = 0,
    headless: bool = False,
) -> tuple[Any, str]:
    """Launch Chrome via OS subprocess and return (process, cdp_endpoint).

    The Chrome binary is started by the OS — not by any automation framework —
    so there are zero CDP/automation artifacts in the process. This defeats
    TLS-level bot detection that flags Playwright/Patchright-launched browsers.
    """
    import asyncio
    import subprocess
    import tempfile

    import httpx

    if port == 0:
        port = _find_free_port()

    chrome = _find_chrome_binary()
    user_data = tempfile.mkdtemp(prefix="bob-chrome-")

    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
    ]
    if headless:
        args.append("--headless=new")

    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait for CDP to be ready (up to 15 seconds)
    endpoint = f"http://localhost:{port}"
    async with httpx.AsyncClient() as client:
        for _ in range(30):
            try:
                r = await client.get(f"{endpoint}/json/version", timeout=1)
                if r.status_code == 200:
                    log.info("Chrome launched on CDP port %d (pid %d)", port, proc.pid)
                    return proc, endpoint
            except Exception:
                pass
            await asyncio.sleep(0.5)

    proc.kill()
    raise RuntimeError(f"Chrome did not start CDP endpoint on port {port}")


class BrowserSessionManager:
    """Holds live Patchright browser/context/page objects keyed by session_id.

    Sessions persist across tool calls within an agent phase.

    When ``os_launch=True``, Chrome is launched via ``subprocess.Popen`` (OS-level)
    instead of through Patchright. This produces zero automation artifacts —
    the browser binary was started by the OS, not by any framework.

    When ``engine_default="native"``, sessions are created via stealth-browser's
    unified StealthBrowser API instead of the Patchright layer. The native engine
    uses Selenium under the hood and can run on Xvfb displays for headless servers.
    """

    def __init__(
        self,
        headless: bool = True,
        cdp_endpoint: str | None = None,
        os_launch: bool = False,
        engine_default: str = "patchright",
    ) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._headless = headless
        self._cdp_endpoint = cdp_endpoint
        self._os_launch = os_launch
        self._engine_default = engine_default
        self._chrome_proc: Any | None = None  # OS-launched Chrome process

    async def create_session(
        self,
        session_id: str,
        fingerprint_config: dict | None = None,
        storage_state_path: str | None = None,
        engine: str | None = None,
    ) -> BrowserSession:
        if session_id in self._sessions:
            raise ValueError(f"Session already exists: {session_id}")

        effective_engine = engine or self._engine_default

        if effective_engine == "native":
            return await self._create_native_session(
                session_id, storage_state_path,
            )

        # Patchright path (default)
        return await self._create_patchright_session(
            session_id, fingerprint_config, storage_state_path,
        )

    async def _create_native_session(
        self,
        session_id: str,
        storage_state_path: str | None = None,
    ) -> BrowserSession:
        """Create a session via stealth-browser's unified StealthBrowser API."""
        try:
            from stealth_browser import StealthBrowser
        except ImportError:
            raise RuntimeError(
                "stealth-browser is not installed. "
                "Install with: pip install stealth-browser"
            )

        profile_dir = None
        if storage_state_path:
            state_path = Path(storage_state_path)
            if state_path.exists():
                if state_path.name == "state.json":
                    profile_dir = state_path.parent
                else:
                    import shutil
                    import tempfile
                    td = Path(tempfile.mkdtemp(prefix="bob-native-"))
                    shutil.copy2(state_path, td / "state.json")
                    profile_dir = td

        # Native engine always needs headless=False (uses OS-level input).
        # On headless Linux, use Xvfb with DISPLAY set.
        sb = await asyncio.to_thread(
            StealthBrowser,
            headless=False,
            engine="native",
            profile_dir=profile_dir,
        )

        page = AsyncNativePageWrapper(sb)
        context = AsyncNativeContextWrapper(sb)

        session = BrowserSession(
            session_id=session_id,
            browser=sb,
            context=context,
            page=page,
            engine="native",
        )
        self._sessions[session_id] = session
        log.info("Native browser session created: %s", session_id)
        return session

    async def _create_patchright_session(
        self,
        session_id: str,
        fingerprint_config: dict | None = None,
        storage_state_path: str | None = None,
    ) -> BrowserSession:
        """Create a session via the Patchright stealth-browser layer."""
        _require_stealth_browser()

        # Reconstruct PlatformConfig for the context if provided
        platform_config = (
            _dict_to_platform_config(fingerprint_config)
            if fingerprint_config
            else None
        )

        # Determine CDP endpoint: OS-launched Chrome, explicit endpoint, or Patchright
        cdp = self._cdp_endpoint
        if cdp is None and self._os_launch:
            self._chrome_proc, cdp = await launch_chrome_cdp(
                headless=self._headless,
            )

        browser = await create_stealth_browser(
            headless=self._headless,
            cdp_endpoint=cdp,
        )

        # If we have a fingerprint config, override the browser's attached config
        # so create_stealth_context picks it up
        if platform_config is not None:
            browser._stealth_config = platform_config

        # Determine profile_dir for session resumption
        profile_dir = None
        if storage_state_path:
            state_path = Path(storage_state_path)
            if state_path.exists():
                # create_stealth_context expects profile_dir containing state.json
                # If the file is already named state.json, use its parent
                if state_path.name == "state.json":
                    profile_dir = state_path.parent
                else:
                    # Copy/symlink into a temp dir with the expected name
                    import shutil
                    import tempfile
                    td = Path(tempfile.mkdtemp(prefix="bob-session-"))
                    shutil.copy2(state_path, td / "state.json")
                    profile_dir = td

        context = await create_stealth_context(
            browser,
            config=platform_config,
            profile_dir=profile_dir,
        )
        page = await new_stealth_page(context)

        session = BrowserSession(
            session_id=session_id,
            browser=browser,
            context=context,
            page=page,
        )
        self._sessions[session_id] = session
        log.info("Browser session created: %s", session_id)
        return session

    async def get_session(self, session_id: str) -> BrowserSession:
        if session_id not in self._sessions:
            raise ValueError(f"No such session: {session_id}")
        return self._sessions[session_id]

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            if session.engine == "native":
                await asyncio.to_thread(session.browser.close)
            else:
                await close_stealth_browser(session.browser)
        except Exception as exc:
            log.warning("Error closing session %s: %s", session_id, exc)
        log.info("Browser session closed: %s", session_id)

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self.close_session(sid)
        # Kill the OS-launched Chrome process if we started one
        if self._chrome_proc is not None:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=5)
            except Exception:
                self._chrome_proc.kill()
            self._chrome_proc = None


# ---------------------------------------------------------------------------
# MCP tool schemas
# ---------------------------------------------------------------------------

BROWSER_CREATE_SESSION_TOOL: dict = {
    "name": "browser_create_session",
    "description": (
        "Launch a stealth browser session. Optionally provide an account_id "
        "to load that account's fingerprint and session state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Unique session identifier"},
            "account_id": {
                "type": "string",
                "description": "Optional account ID to load fingerprint/session from registry",
            },
        },
        "required": ["session_id"],
    },
}

BROWSER_NAVIGATE_TOOL: dict = {
    "name": "browser_navigate",
    "description": "Navigate the browser to a URL. Returns page title and current URL.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "url": {"type": "string", "description": "URL to navigate to"},
        },
        "required": ["session_id", "url"],
    },
}

BROWSER_CLICK_TOOL: dict = {
    "name": "browser_click",
    "description": "Click an element matching the given CSS selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "selector": {"type": "string", "description": "CSS selector of element to click"},
        },
        "required": ["session_id", "selector"],
    },
}

BROWSER_FILL_TOOL: dict = {
    "name": "browser_fill",
    "description": "Fill a form field matching the given CSS selector with a value.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "selector": {"type": "string", "description": "CSS selector of input to fill"},
            "value": {"type": "string", "description": "Value to type into the field"},
        },
        "required": ["session_id", "selector", "value"],
    },
}

BROWSER_EXTRACT_TEXT_TOOL: dict = {
    "name": "browser_extract_text",
    "description": "Extract text content from the page or a specific element.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "selector": {
                "type": "string",
                "description": "CSS selector (defaults to body if omitted)",
            },
        },
        "required": ["session_id"],
    },
}

BROWSER_SCREENSHOT_TOOL: dict = {
    "name": "browser_screenshot",
    "description": "Take a screenshot of the current page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "path": {
                "type": "string",
                "description": "File path to save screenshot (defaults to temp file)",
            },
        },
        "required": ["session_id"],
    },
}

BROWSER_CLOSE_SESSION_TOOL: dict = {
    "name": "browser_close_session",
    "description": "Close a browser session and release resources.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier to close"},
        },
        "required": ["session_id"],
    },
}

BROWSER_SAVE_SESSION_TOOL: dict = {
    "name": "browser_save_session",
    "description": "Save the current browser session state (cookies, localStorage) to a file for later reuse.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "path": {"type": "string", "description": "File path to save session state JSON"},
        },
        "required": ["session_id", "path"],
    },
}

BROWSER_EVALUATE_TOOL: dict = {
    "name": "browser_evaluate",
    "description": "Execute JavaScript on the page and return the result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
        },
        "required": ["session_id", "expression"],
    },
}

BROWSER_WAIT_FOR_NAVIGATION_TOOL: dict = {
    "name": "browser_wait_for_navigation",
    "description": "Wait for the page URL to match a pattern (substring or regex).",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "url_pattern": {"type": "string", "description": "URL substring or glob pattern to wait for"},
            "timeout": {"type": "number", "description": "Timeout in milliseconds (default 30000)"},
        },
        "required": ["session_id", "url_pattern"],
    },
}

BROWSER_SELECT_OPTION_TOOL: dict = {
    "name": "browser_select_option",
    "description": "Select an option from a dropdown/select element.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "selector": {"type": "string", "description": "CSS selector of the select element"},
            "value": {"type": "string", "description": "Option value or label to select"},
        },
        "required": ["session_id", "selector", "value"],
    },
}


# ---------------------------------------------------------------------------
# Tool response helper
# ---------------------------------------------------------------------------


def _resp(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def _make_browser_tools(
    session_manager: BrowserSessionManager,
    account_registry: Any | None = None,
) -> list[SdkMcpTool]:
    """Create browser MCP tools bound to a session manager.

    Args:
        session_manager: BrowserSessionManager instance.
        account_registry: Optional AccountRegistry for account_id lookups.
    """

    async def create_session(args: dict) -> dict:
        session_id = args["session_id"]
        account_id = args.get("account_id")
        fingerprint_config = None
        storage_state_path = None

        if account_id and account_registry is not None:
            account = account_registry.get_account(account_id)
            if account is None:
                return _resp(f"Error: account not found: {account_id}")
            fingerprint_config = account.fingerprint_config or None
            storage_state_path = account.session_state_path

        try:
            session = await session_manager.create_session(
                session_id=session_id,
                fingerprint_config=fingerprint_config,
                storage_state_path=storage_state_path,
            )
            session.account_id = account_id
            return _resp(f"Session '{session_id}' created.")
        except Exception as exc:
            return _resp(f"Error creating session: {exc}")

    async def navigate(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            if isinstance(session.page, AsyncNativePageWrapper):
                await session.page.goto(args["url"])
            else:
                await stealth_goto(session.page, args["url"])
            title = await session.page.title()
            url = session.page.url
            return _resp(f"Navigated to: {url}\nTitle: {title}")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def click(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            el = session.page.locator(args["selector"]).first
            text = await el.text_content() or ""
            await el.click()
            return _resp(f"Clicked element: {text.strip()[:200]}")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def fill(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            await session.page.locator(args["selector"]).first.fill(args["value"])
            return _resp(f"Filled '{args['selector']}' with value.")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def extract_text(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            selector = args.get("selector", "body")
            text = await session.page.locator(selector).first.text_content() or ""
            # Truncate to avoid massive responses
            if len(text) > 10000:
                text = text[:10000] + "\n... (truncated)"
            return _resp(text)
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def screenshot(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            path = args.get("path")
            if not path:
                import tempfile
                fd, path = tempfile.mkstemp(suffix=".png", prefix="bob-screenshot-")
                import os
                os.close(fd)
            await session.page.screenshot(path=path)
            return _resp(f"Screenshot saved: {path}")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def save_session(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            path = args["path"]
            # Resolve to eliminate ".." traversal, then sanitize filename
            p = Path(path).resolve()
            safe_name = p.name.replace("/", "_").replace("\\", "_").replace("..", "_")
            if not safe_name or safe_name.startswith("."):
                safe_name = "_" + safe_name
            safe_path = str(p.parent / safe_name)
            await session.context.storage_state(path=safe_path)
            return _resp(f"Session state saved to: {safe_path}")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def evaluate(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            result = await session.page.evaluate(args["expression"])
            text = str(result)
            if len(text) > 10000:
                text = text[:10000] + "\n... (truncated)"
            return _resp(text)
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def wait_for_navigation(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            url_pattern = args["url_pattern"]
            timeout = args.get("timeout") or 30000
            await session.page.wait_for_url(f"**{url_pattern}**", timeout=timeout)
            return _resp(f"Navigation complete. Current URL: {session.page.url}")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def select_option(args: dict) -> dict:
        try:
            session = await session_manager.get_session(args["session_id"])
            await session.page.select_option(args["selector"], args["value"])
            return _resp(f"Selected '{args['value']}' in '{args['selector']}'")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    async def close_session(args: dict) -> dict:
        try:
            await session_manager.close_session(args["session_id"])
            return _resp(f"Session '{args['session_id']}' closed.")
        except Exception as exc:
            return _resp(f"Error: {exc}")

    return [
        SdkMcpTool(
            name=BROWSER_CREATE_SESSION_TOOL["name"],
            description=BROWSER_CREATE_SESSION_TOOL["description"],
            input_schema=BROWSER_CREATE_SESSION_TOOL["input_schema"],
            handler=create_session,
        ),
        SdkMcpTool(
            name=BROWSER_NAVIGATE_TOOL["name"],
            description=BROWSER_NAVIGATE_TOOL["description"],
            input_schema=BROWSER_NAVIGATE_TOOL["input_schema"],
            handler=navigate,
        ),
        SdkMcpTool(
            name=BROWSER_CLICK_TOOL["name"],
            description=BROWSER_CLICK_TOOL["description"],
            input_schema=BROWSER_CLICK_TOOL["input_schema"],
            handler=click,
        ),
        SdkMcpTool(
            name=BROWSER_FILL_TOOL["name"],
            description=BROWSER_FILL_TOOL["description"],
            input_schema=BROWSER_FILL_TOOL["input_schema"],
            handler=fill,
        ),
        SdkMcpTool(
            name=BROWSER_EXTRACT_TEXT_TOOL["name"],
            description=BROWSER_EXTRACT_TEXT_TOOL["description"],
            input_schema=BROWSER_EXTRACT_TEXT_TOOL["input_schema"],
            handler=extract_text,
        ),
        SdkMcpTool(
            name=BROWSER_SCREENSHOT_TOOL["name"],
            description=BROWSER_SCREENSHOT_TOOL["description"],
            input_schema=BROWSER_SCREENSHOT_TOOL["input_schema"],
            handler=screenshot,
        ),
        SdkMcpTool(
            name=BROWSER_CLOSE_SESSION_TOOL["name"],
            description=BROWSER_CLOSE_SESSION_TOOL["description"],
            input_schema=BROWSER_CLOSE_SESSION_TOOL["input_schema"],
            handler=close_session,
        ),
        SdkMcpTool(
            name=BROWSER_SAVE_SESSION_TOOL["name"],
            description=BROWSER_SAVE_SESSION_TOOL["description"],
            input_schema=BROWSER_SAVE_SESSION_TOOL["input_schema"],
            handler=save_session,
        ),
        SdkMcpTool(
            name=BROWSER_EVALUATE_TOOL["name"],
            description=BROWSER_EVALUATE_TOOL["description"],
            input_schema=BROWSER_EVALUATE_TOOL["input_schema"],
            handler=evaluate,
        ),
        SdkMcpTool(
            name=BROWSER_WAIT_FOR_NAVIGATION_TOOL["name"],
            description=BROWSER_WAIT_FOR_NAVIGATION_TOOL["description"],
            input_schema=BROWSER_WAIT_FOR_NAVIGATION_TOOL["input_schema"],
            handler=wait_for_navigation,
        ),
        SdkMcpTool(
            name=BROWSER_SELECT_OPTION_TOOL["name"],
            description=BROWSER_SELECT_OPTION_TOOL["description"],
            input_schema=BROWSER_SELECT_OPTION_TOOL["input_schema"],
            handler=select_option,
        ),
    ]
