"""Anthropic OAuth (Claude Pro/Max) — PKCE authorization code flow.

Ported from @mariozechner/pi-ai's TypeScript OAuth implementation.
Provides free API access via Claude login with sk-ant-oat* tokens.

Token cache: ~/.hackathon-finder/oauth.json
Callback server: http://localhost:53692/callback
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CALLBACK_PORT = 53692
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)
CACHE_DIR = Path.home() / ".hackathon-finder"
CACHE_PATH = CACHE_DIR / "oauth.json"
LOGIN_TIMEOUT = 120  # seconds


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code verifier and S256 challenge."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    challenge_hash = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(challenge_hash).rstrip(b"=").decode()
    return verifier, challenge


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_token_response(data: dict) -> dict:
    """Parse token endpoint response into our credential format."""
    return {
        "refresh": data["refresh_token"],
        "access": data["access_token"],
        "expires": _now_ms() + data["expires_in"] * 1000 - 5 * 60 * 1000,
    }


# --- Token cache (compatible with pi-ai format) ---


def _load_cached() -> dict | None:
    """Load cached credentials. Returns {refresh, access, expires} or None.

    Handles both formats:
    - Nested (our format): {"anthropic": {"refresh": ..., "access": ..., "expires": ...}}
    - Flat (pi-ai legacy): {"refresh": ..., "access": ..., "expires": ...}
    """
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text())
        # Nested format
        creds = data.get("anthropic")
        if creds and "access" in creds and "refresh" in creds and "expires" in creds:
            return creds
        # Flat format (pi-ai legacy)
        if "access" in data and "refresh" in data and "expires" in data:
            return {"refresh": data["refresh"], "access": data["access"], "expires": data["expires"]}
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_cached(creds: dict) -> None:
    """Save credentials to cache, preserving other providers."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    data["anthropic"] = creds
    CACHE_PATH.write_text(json.dumps(data, indent=2) + "\n")


# --- Token refresh ---


def _refresh_token(refresh_token: str) -> dict:
    """Exchange refresh token for new access + refresh tokens."""
    resp = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return _parse_token_response(resp.json())


# --- Interactive browser login ---


def _login_interactive() -> dict:
    """Run full PKCE OAuth flow: browser → callback server → token exchange."""
    verifier, challenge = _generate_pkce()

    # Callback server to receive the authorization code
    received: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            error = qs.get("error", [None])[0]

            if error:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<p>Authentication failed: {error}</p>".encode())
                received["error"] = error
                return

            if code and state:
                received["code"] = code
                received["state"] = state
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<p>Authentication successful. Return to your terminal.</p>"
                )
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass  # suppress request logs

    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        params = urlencode({
            "code": "true",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": verifier,
        })
        auth_url = f"{AUTHORIZE_URL}?{params}"

        print(f"Opening browser for Claude authentication...")
        print(f"If the browser doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        # Wait for callback
        deadline = time.time() + LOGIN_TIMEOUT
        while "code" not in received and "error" not in received and time.time() < deadline:
            time.sleep(0.1)

        if "error" in received:
            raise RuntimeError(f"OAuth error: {received['error']}")
        if "code" not in received:
            raise RuntimeError(f"OAuth login timed out ({LOGIN_TIMEOUT}s)")
        if received.get("state") != verifier:
            raise RuntimeError("OAuth state mismatch — possible CSRF")

        # Exchange authorization code for tokens
        resp = httpx.post(
            TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": received["code"],
                "state": received["state"],
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return _parse_token_response(resp.json())
    finally:
        server.shutdown()


# --- Public API ---


_OAUTH_HEADERS = {
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
    "user-agent": "claude-cli/2.1.75",
    "x-app": "cli",
}


@dataclass
class AuthResult:
    """Authentication result with the correct SDK parameter."""
    token: str
    is_oauth: bool

    @property
    def client_kwargs(self) -> dict:
        """Kwargs for AsyncAnthropic() — uses auth_token + identity headers for OAuth."""
        if self.is_oauth:
            return {"auth_token": self.token, "default_headers": _OAUTH_HEADERS}
        return {"api_key": self.token}


def get_auth() -> AuthResult:
    """Get Anthropic authentication. Priority: env var → cached OAuth → refresh → interactive login.

    Returns:
        AuthResult with the token and whether it's OAuth (determines SDK parameter).

    Raises:
        RuntimeError: If interactive login fails or times out.
    """
    # 1. Environment variable (standard API key → x-api-key header)
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return AuthResult(token=env_key, is_oauth=False)

    # 2. Cached OAuth token (not expired)
    creds = _load_cached()
    if creds:
        if _now_ms() < creds["expires"]:
            logger.debug("Using cached OAuth token (expires in %ds)", (creds["expires"] - _now_ms()) // 1000)
            return AuthResult(token=creds["access"], is_oauth=True)

        # 3. Refresh expired token
        try:
            logger.debug("Refreshing expired OAuth token...")
            creds = _refresh_token(creds["refresh"])
            _save_cached(creds)
            return AuthResult(token=creds["access"], is_oauth=True)
        except Exception as e:
            logger.warning("Token refresh failed: %s", e)
            # Fall through to interactive login

    # 4. Interactive browser login
    creds = _login_interactive()
    _save_cached(creds)
    return AuthResult(token=creds["access"], is_oauth=True)


def ensure_auth() -> AuthResult:
    """Ensure we have valid auth, with user-facing status messages.

    Returns AuthResult. Safe to call before validation — handles the
    interactive browser flow if needed.
    """
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return AuthResult(token=env_key, is_oauth=False)

    creds = _load_cached()
    if creds and _now_ms() < creds["expires"]:
        return AuthResult(token=creds["access"], is_oauth=True)

    if creds:
        try:
            creds = _refresh_token(creds["refresh"])
            _save_cached(creds)
            return AuthResult(token=creds["access"], is_oauth=True)
        except Exception:
            print("OAuth token expired and refresh failed. Re-authenticating...")

    # Interactive login
    return get_auth()
