# Brutalist Audit — Round 2 Findings

Second-pass critique against the hardened codebase. Focus: what's STILL wrong after P0/P1 remediation.

**Status: COMPLETE** — 360/360 tests pass, all P0+P1 findings remediated

---

## Triage

### P0 — Fix Now

#### R1. SSRF bypass via redirect following [CONFIRMED — unanimous]
**Source:** All critics across codebase + test coverage verticals
**Files:** `tools/web.py:345,381`, `tools/platforms.py:97,241`

`_validate_url()` checks the initial URL, but `follow_redirects=True` means httpx will silently follow a 302 from a safe public URL to `http://169.254.169.254/`. The redirect target is never validated.

**Solution:** Create `_safe_get()` helper in tools/web.py that:
- Makes request with `follow_redirects=False`
- On 3xx, extracts `Location` header, resolves relative URL, validates with `_validate_url()`
- Follows up to 5 redirects
- Raises on blocked redirect target

Replace all `http_client.get(url, follow_redirects=True)` in web tools AND platform tools with `_safe_get()`.

**Pitfall:** HEAD requests (check_link) need same treatment → create `_safe_head()` too, or parameterize method.
**Pitfall:** Relative redirects need URL resolution against the response URL.
**Pitfall:** Platform tools (`_retry_http(lambda: http_client.get(url, follow_redirects=True), url)`) need to switch to `_retry_http(lambda: _safe_get(url, http_client), url)`.

---

#### R2. Devpost URL validation userinfo bypass [CONFIRMED]
**Source:** Codex test coverage critique
**Files:** `tools/platforms.py:77-82`

`_is_devpost_url()` splits netloc on `:` to strip port, but `urlparse("https://devpost.com:443@evil.com").netloc` returns `devpost.com:443@evil.com`. The `split(":")[0]` yields `devpost.com` which passes the check, but the actual request goes to `evil.com`.

**Solution:** Strip userinfo before checking hostname:
```python
from urllib.parse import urlparse
parsed = urlparse(url)
hostname = parsed.hostname  # Already strips port AND userinfo
return hostname == "devpost.com" or (hostname and hostname.endswith(".devpost.com"))
```
Use `parsed.hostname` (which handles userinfo) instead of `parsed.netloc.split(":")[0]`.

---

#### R3. Unbounded pagination in source adapters [CONFIRMED]
**Source:** Codebase critiques
**Files:** `sources/devpost.py:98-131`, `sources/devfolio.py:96-128`

No max-page cap. A misbehaving API can loop indefinitely.

**Solution:** Add `MAX_PAGES = 50` constant and break after that limit in both adapters.

---

#### R4. max_results unbounded in tool schemas [CONFIRMED]
**Source:** Codebase critique
**Files:** `tools/web.py:283-286`, `tools/github.py:65-69`

LLM controls max_results with no upper bound. Can waste resources.

**Solution:** Clamp in executors: `max_results = min(max_results, 20)`.

---

#### R5. No lock file [CONFIRMED — unanimous]
**Source:** All dependency critics
**File:** project root

No `uv.lock` or pinned requirements. Builds are non-reproducible.

**Solution:** `uv lock`, commit `uv.lock`. Add upper bounds: `anthropic>=0.49.0,<1.0`, `httpx>=0.27.0,<1.0`.

---

#### R6. stealth-browser is dead code [CONFIRMED]
**Source:** All dependency critics
**Files:** `pyproject.toml:15`

`stealth-browser[patchright]` declared but never imported anywhere. Adds 100MB+ browser bloat.

**Solution:** Remove from pyproject.toml.

---

### P1 — Fix Next

#### R7. Unbounded cache growth [CONFIRMED]
**Files:** `tools/web.py:165-201`

Cache dict has no size limit. Long-running processes can OOM.

**Solution:** Add `_MAX_CACHE_ENTRIES = 200`. In `_cache_put`, if `len(_cache) >= _MAX_CACHE_ENTRIES`, evict oldest entry.

---

#### R8. oauth.py zero test coverage [CONFIRMED]
**Source:** Test coverage critique (unanimous)
**File:** `src/hackathon_finder/oauth.py` (311 lines, 0 tests)

Most security-sensitive module. PKCE, token storage, CSRF state, file permissions — all untested.

**Solution:** Create `tests/test_oauth.py` with basic tests for `_generate_pkce`, `_parse_token_response`, `_save_cached`/`_load_cached`, file permissions.

---

#### R9. cli.py zero test coverage [CONFIRMED]
**Source:** Test coverage critique (unanimous)
**File:** `src/hackathon_finder/cli.py` (325 lines, 0 tests)

Date filtering, JSON output, argument parsing, backward compat — all untested.

**Solution:** Create `tests/test_cli.py` with tests for `_filter_by_date`, `_normalize_utc`, `_to_json_obj`, subcommand routing.

---

#### R10. Budget overshoot test is weak [CONFIRMED]
**Source:** Test coverage critique
**File:** `tests/test_situation.py`

The test doesn't verify the "Budget exhausted" error message for skipped tools. Dead code in the test.

**Solution:** Strengthen: verify third tool_result contains `is_error: True` and "Budget exhausted" text.

---

#### R11. Symlink tests missing for append_log/list_sections [CONFIRMED]
**Source:** Test coverage critique
**File:** `tests/test_tools_map.py`

Only write_section and read_section have symlink tests. append_log and list_sections don't.

**Solution:** Add symlink escape tests for both functions.

---

### P2 — Note for Later

#### R12. DNS rebinding TOCTOU [VALID but hard to fix]
`_validate_url` resolves DNS, then httpx resolves again. Fix requires custom transport or IP pinning, which httpx doesn't natively support. **Documented as known limitation.** The redirect fix (R1) closes the more practical attack vector.

#### R13. Duplicate scoring logic (luma.py + validate.py) [VALID, defer]
Extract to shared module when scoring logic changes next.

#### R14. No Anthropic API timeout [VALID, defer]
Add timeout parameter in future. Low risk for CLI tool.

#### R15. Lambda late-binding in retry [VALID but benign]
Currently safe because url isn't reassigned in scope. Defensive fix when touching these functions next.

#### R16. event_id unstable without start_date [KNOWN]
Already documented in ARCHITECTURE.md. Falls back to URL when no date available.

#### R17. append_log bypasses ownership [REJECTED — by design]
Third time flagged, third time rejected. Append-only logs are intentionally multi-writer per ARCHITECTURE.md.

---

## Task Graph

### Wave A — Security + Dependencies (parallel, no file overlap)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| A1. Redirect-safe fetching + cache limit + max_results clamp | redirect-fix | tools/web.py | R1, R4, R7 |
| A2. Pagination bounds | source-bounds | sources/devpost.py, sources/devfolio.py | R3 |
| A3. Platform redirect safety + userinfo fix | platform-fix-2 | tools/platforms.py | R1 (platform side), R2 |
| A4. Dependency hygiene | deps-fix | pyproject.toml | R5, R6 |

**Note:** A1 creates `_safe_get`/`_safe_head` in web.py. A3 imports and uses it in platforms.py. Both can run in parallel — A3 knows the function signature from the spec.

### Wave B — Tests (parallel)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| B1. OAuth tests | test-oauth | tests/test_oauth.py | R8 |
| B2. CLI tests | test-cli | tests/test_cli.py | R9 |
| B3. Security test hardening | test-sec-2 | tests/test_situation.py, tests/test_tools_map.py, tests/test_tools_web.py | R10, R11, redirect tests |

---

## Completion Tracking

| Task | Status | Notes |
|------|--------|-------|
| A1. Redirect-safe fetching + cache + clamp | **done** | `_safe_get`/`_safe_head` with per-hop validation, `_MAX_CACHE_ENTRIES=200`, `max_results` clamped to 20 |
| A2. Pagination bounds | **done** | `MAX_PAGES=50` in devpost.py and devfolio.py |
| A3. Platform redirect + userinfo | **done** | `parsed.hostname` replaces `netloc.split(":")`, `_safe_get` imported for platform HTTP calls |
| A4. Dependency hygiene | **done** | Upper bounds on all deps, stealth-browser removed, uv.lock committed |
| B1. OAuth tests | **done** | 12 tests: PKCE generation, token parsing, cache round-trip, file permissions, AuthResult |
| B2. CLI tests | **done** | 17 tests: date normalization, date filtering, JSON output, format_date, argument parsing |
| B3. Security test hardening | **done** | Budget overshoot verified, symlink tests for append_log + list_sections, 7 redirect SSRF tests |

## New Findings Log

- Budget overshoot test required restructuring: after budget exhaustion, the while loop exits without making another API call, so error results are appended to messages but never sent. Test redesigned to verify observable behavior (tool_calls count, summary text, HTTP call count) rather than internal message inspection.
- `_safe_get`/`_safe_head` use local `from urllib.parse import urljoin` for relative redirect resolution.

---
