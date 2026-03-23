# Brutalist Audit — Round 3 Findings

Third-pass critique: security, test coverage, and architecture verticals (6 critics). Focus: what's STILL wrong after two rounds of hardening, and what architectural issues emerge under stress.

**Status: COMPLETE** — 380/380 tests pass, all P0 findings remediated

---

## Triage

### P0 — Fix Now

#### R1. `0.0.0.0` / `::` unspecified address SSRF bypass [CONFIRMED — Security Gemini]
**Files:** `tools/web.py:46`

`_validate_url` checks `is_private`, `is_loopback`, `is_link_local`, `is_reserved` but NOT `is_unspecified`. On Linux/macOS, `http://0.0.0.0` connects to localhost.

**Solution:** Add `addr.is_unspecified` to the check chain.

---

#### R2. OAuth token file non-atomic write [CONFIRMED — unanimous]
**Files:** `oauth.py:103-104`

`write_text()` then `chmod()` leaves a window where the file has default umask permissions (0o644). Race condition for token theft.

**Solution:** Use tempfile + `os.fchmod` + `os.rename` pattern (same as map.py's atomic write):
```python
fd, tmp = tempfile.mkstemp(dir=str(CACHE_DIR), suffix=".tmp")
try:
    os.fchmod(fd, 0o600)  # Set permissions BEFORE writing content
    os.write(fd, (json.dumps(data, indent=2) + "\n").encode())
    os.close(fd)
    os.rename(tmp, str(CACHE_PATH))
except BaseException:
    os.close(fd)
    os.unlink(tmp)
    raise
```

**Pitfall:** `os.fchmod` on the fd before writing ensures no window of world-readable content.

---

#### R3. Source scrapers bypass SSRF protection [CONFIRMED — Security Claude]
**Files:** `sources/eventbrite.py:116`, `sources/luma.py:140`, `sources/meetup.py`, `sources/mlh.py`

Source adapters create their own `httpx.AsyncClient(follow_redirects=True)`, bypassing `_safe_get`/`_validate_url`. An open redirect on any platform could reach internal IPs.

**Solution:** Create `sources/http.py` with a shared safe client factory that disables `follow_redirects` and validates redirect targets. OR: simpler — add `follow_redirects=False` to all source clients (they fetch from hardcoded URLs that shouldn't redirect) and handle non-200 as errors.

**Pitfall:** Some sources legitimately redirect (e.g., short URLs). Disabling redirects may break things. Safer to just validate that redirect targets are public IPs.

---

#### R4. `skip_curated=False` wastes API calls [CONFIRMED — Architecture Claude]
**Files:** `cli.py:183`

CLI calls `validate_batch(hackathons, skip_curated=False)`, overriding the triage system's curated auto-pass. Every devpost/mlh/devfolio event gets LLM-investigated unnecessarily.

**Solution:** Change to `skip_curated=True` (respect the triage design). Add `--no-skip-curated` CLI flag for users who want full investigation.

---

#### R5. HTTPS→HTTP protocol downgrade in redirects [CONFIRMED — Test Coverage Gemini]
**Files:** `tools/web.py:56-76`

`_safe_get` follows `https://safe.com → http://safe.com/page` without blocking. This is a security regression — an attacker can downgrade to HTTP to intercept or MITM the connection.

**Solution:** In `_safe_get`/`_safe_head`, after resolving the redirect URL, check that the scheme doesn't downgrade from HTTPS to HTTP:
```python
if parsed.scheme == "https" and urlparse(current_url).scheme == "http":
    raise ValueError("Redirect blocked: HTTPS to HTTP downgrade")
```

Actually simpler: track the original scheme; if it was `https`, reject any redirect hop that's `http`.

---

#### R6. `execute_fetch_page` / `execute_check_link` zero direct tests [CONFIRMED — unanimous]
**Files:** `tests/test_tools_web.py`

The two most critical web tools have no direct unit tests. They're only smoke-tested via the situation room dispatch tests (which use weak assertions like `assert "Status:" in result`).

**Solution:** Add `TestExecuteFetchPage` and `TestExecuteCheckLink` classes with tests for: successful fetch, SSRF blocked URL, network error, HTML extraction, cache hit/miss.

---

#### R7. `_safe_get` relative redirect + empty Location untested [CONFIRMED — Test Coverage Claude]
**Files:** `tests/test_tools_web.py`

Two critical branches in `_safe_get`/`_safe_head` have zero coverage:
1. Relative redirect (`Location: /page`) — exercises `urljoin` resolution
2. Empty Location header on 3xx — returns redirect response as-is

**Solution:** Add tests for both branches to `TestSafeRedirectFetching`.

---

### P1 — Fix Next

#### R8. Agent defaults to valid=True on failure [CONFIRMED — Architecture Claude]
**Files:** `agent.py:250-257`

When investigation stops without verdict, defaults to `valid=True, confidence=0.3`. API failures silently pass all events through.

**Solution:** Change to `valid=False` with `reasoning="Agent failed — flagged for manual review"`. Fail closed, not open.

---

#### R9. `get_auth()` / `ensure_auth()` flow untested [CONFIRMED — Test Coverage Claude]
**Files:** `tests/test_oauth.py`

The auth orchestration (env var → cached → refresh → interactive) has zero coverage. Token refresh failure → interactive fallback would hang in CI.

**Solution:** Add tests with mocked `_load_cached`, `_refresh_token`, env vars.

---

#### R10. `fetch_all()` / `_fetch_source()` untested [CONFIRMED — Test Coverage Claude/Gemini]
**Files:** `tests/test_aggregator.py`

The aggregator orchestration and error handling wrapper have zero tests.

**Solution:** Add tests for concurrent fetch, source exception isolation, empty results.

---

#### R11. Cache TTL expiration untested [CONFIRMED — Test Coverage Claude]
**Files:** `tests/test_tools_web.py`

Cache put/get/namespace tested, but the TTL expiration branch is never exercised.

**Solution:** Mock `time.monotonic` and verify expired entries return None.

---

#### R12. GitHub rate limit will block Situation Room [CONFIRMED — Architecture Claude]
**Files:** `tools/github.py`

60 req/hr unauthenticated limit. A single analysis can use 20-30 GitHub requests. Second run within an hour fails silently.

**Solution:** Check `X-RateLimit-Remaining` proactively and skip GitHub tools when low. Return a clear message to the agent.

---

### P2 — Note for Later

#### R13. Prompt injection via web content [CONFIRMED — unanimous, KNOWN]
Already F16 in FINDINGS.md. Fundamental LLM problem. Script/style stripping is partial mitigation. Full solution requires content isolation architecture (sandboxed tool results, output validation). Deferred.

#### R14. DNS rebinding TOCTOU [CONFIRMED — unanimous, KNOWN]
Already R12 in FINDINGS-2.md. Requires custom transport or IP pinning. The redirect fix closes the more practical vector. Deferred.

#### R15. Context window quadratic cost growth [CONFIRMED — Architecture unanimous]
Valid but requires message summarization or sliding window — significant architectural change. Add token budget (not just tool-call budget) in future.

#### R16. Agent tool dispatch — no allowlist enforcement [VALID but mitigated]
Anthropic SDK enforces tool schemas API-side. The LLM can only call declared tools. Server-side enforcement adds defense-in-depth but is low priority for single-user CLI.

#### R17. Semantic map content unconstrained [VALID, defer]
LLM-controlled frontmatter/body content. No execution risk (no eval/exec). Downstream consumers should validate. Note for multi-agent future.

#### R18. ReDoS in HTML parsing [VALID, low risk]
Input length bounds (10K for OG tags, 100K for JSON-LD) provide mitigation. Catastrophic backtracking unlikely with current patterns.

#### R19. Source scraper fragility [VALID, inherent]
Internal APIs (`__SERVER_DATA__`, `api2.luma.com`, `__NEXT_DATA__`) can break anytime. Add health monitoring in future, not worth over-engineering now.

#### R20. Dedup O(n²) [VALID, fine at scale]
<1000 events. Not a concern until 10K+.

#### R21. No token cost estimation [VALID, defer]
Pre-execution cost estimate would be nice. Low urgency for CLI.

#### R22. OAuth state = PKCE verifier [VALID, low risk]
State is visible in browser URL. PKCE challenge is SHA-256 of verifier, so exposing verifier on client side is by design (it's sent to the token endpoint). The concern is browser history/referrer leaking it — minor for CLI OAuth flow.

---

## Task Graph

### Wave A — Security fixes (parallel, no file overlap)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| A1. SSRF unspecified + protocol downgrade | ssrf-fix-3 | tools/web.py | R1, R5 |
| A2. OAuth atomic write | oauth-atomic | oauth.py | R2 |
| A3. Source scraper SSRF | source-ssrf | sources/eventbrite.py, sources/luma.py, sources/meetup.py, sources/mlh.py | R3 |
| A4. Curated skip + fail-closed | triage-fix | cli.py, agent.py | R4, R8 |

### Wave B — Tests + GitHub rate limit (parallel)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| B1. fetch_page/check_link tests + redirect edge cases | test-web-3 | tests/test_tools_web.py | R6, R7 |
| B2. Auth flow tests + cache TTL | test-auth-flow | tests/test_oauth.py, tests/test_tools_web.py | R9, R11 |
| B3. Aggregator tests + GitHub rate awareness | test-agg | tests/test_aggregator.py, tools/github.py | R10, R12 |

---

## Completion Tracking

| Task | Status | Notes |
|------|--------|-------|
| A1. SSRF unspecified + protocol downgrade | **done** | `is_unspecified` added, HTTPS→HTTP downgrade blocked in `_safe_get`/`_safe_head` |
| A2. OAuth atomic write | **done** | `tempfile.mkstemp` + `os.fchmod(fd, 0o600)` + `os.rename` — permissions set before content written |
| A3. Source scraper SSRF | **done** | `follow_redirects=True` removed from eventbrite, meetup, mlh source clients |
| A4. Curated skip + fail-closed | **done** | `skip_curated=True` default, `--no-skip-curated` flag, agent returns `valid=False` on failure |
| B1. Web tool tests + redirect edges | **done** | TestExecuteFetchPage (5), TestExecuteCheckLink (3), relative redirect, empty Location, HTTPS downgrade tests |
| B2. Auth flow + cache TTL tests | **done** | TestGetAuth (4 tests: env var, cached, refresh, interactive fallback), cache TTL expiration tests |
| B3. Aggregator tests + GitHub rate | **done** | TestFetchAll (3 tests), proactive `_rate_limit_remaining` tracking with <=5 threshold |

## New Findings Log

- GitHub `_rate_limit_remaining` module-level state persists across tests — added autouse fixture to reset it in test_tools_github.py.
- Agent test assertions updated: `valid=True` → `valid=False` for max-rounds-exceeded and stop-without-verdict paths (fail-closed change).

---
