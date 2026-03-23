# Brutalist Audit Findings — Triage & Remediation

Post-implementation security and quality audit across codebase, security, and test coverage verticals.

**Status: COMPLETE** — 307/307 tests pass, all P0+P1 findings remediated

---

## Triage Methodology

Each finding rated: **CONFIRMED** (valid, fix it), **PARTIAL** (valid concern, scoped fix), **REJECTED** (misunderstands design or premature).

---

## P0 — Fix Now

### F1. SSRF — No URL validation [CONFIRMED]
**Source:** All three critiques (unanimous)
**Files:** `tools/web.py:300-344`, `situation.py:297`

`fetch_page`, `check_link`, `search_web` accept arbitrary LLM-controlled URLs with `follow_redirects=True`. No scheme, host, or private IP blocking. Cloud metadata, localhost, internal networks all reachable.

**Solution:** Add `_validate_url(url)` that:
- Restricts to `http://` and `https://` schemes only
- Resolves DNS and blocks private/reserved IPs (RFC1918, link-local, loopback, metadata `169.254.169.254`)
- Blocks `file://`, `ftp://`, etc.
- Apply before every outbound request in all three web executors

**Pitfall:** DNS rebinding can bypass hostname-based checks. Must resolve DNS to IP and validate the *resolved* IP, not just the hostname string. httpx doesn't expose pre-connect IP easily — use `socket.getaddrinfo` before the request.

**Pitfall:** Must also validate redirect targets. httpx `follow_redirects=True` may land on a blocked IP after initial fetch succeeds. Consider using an httpx event hook or disabling auto-redirects and following manually with validation.

---

### F2. Budget overshoot on multi-tool responses [CONFIRMED]
**Source:** All three critiques (unanimous)
**Files:** `situation.py:249,290-305`, `agent.py:215,264-274`

The `while tool_calls_used < max_tool_calls` check is only at the top of the loop. If a response contains 5 tool_use blocks and budget has 1 call left, all 5 execute. Budget can overshoot by up to N-1 tools.

**Solution:** Check budget inside the per-tool for loop. Break when exhausted.

**Pitfall:** Anthropic API expects tool_result for every tool_use in a response. Skipped tools need error results ("Budget exhausted, tool not executed") so the API doesn't reject the message.

---

### F3. Devpost URL validation bypass [CONFIRMED]
**Source:** Codebase + Security critiques
**Files:** `tools/platforms.py:86,213`

`"devpost.com" in url` accepts `devpost.com.evil.tld`, `evil.tld/?x=devpost.com`, etc.

**Solution:** `urlparse(url).netloc.endswith(".devpost.com") or urlparse(url).netloc == "devpost.com"`

---

### F4. Path traversal via symlinks [CONFIRMED]
**Source:** Codebase + Security critiques
**Files:** `tools/map.py:21-29,81,124,175`

`_validate_path` checks string patterns but doesn't resolve symlinks. A symlink inside map_root can escape to arbitrary paths.

**Solution:** After constructing `full_path`:
```python
resolved = full_path.resolve()
if not resolved.is_relative_to(Path(map_root).resolve()):
    return "Invalid path (escapes map root)"
```
Apply in write_section, read_section, append_log, and list_sections.

---

### F5. sections_written records before execution [CONFIRMED]
**Source:** Codebase critique
**Files:** `situation.py:291-295`

Path added to `sections_written` before `_execute_tool` runs. Failed writes (ownership conflict, invalid path) still get recorded.

**Solution:** Move tracking after execution; check result string starts with "Written:" before recording.

---

### F6. Cache key collision between tools [CONFIRMED]
**Source:** Codebase + Test coverage critiques
**Files:** `tools/web.py:133,150,164,302,334`

`check_link` (HEAD) and `fetch_page` (GET) share the same cache keyed by URL. HEAD response can poison GET cache.

**Solution:** Namespace cache keys: `f"{tool_name}:{url}"`. Modify `_cache_get` and `_cache_put` to accept a tool name parameter.

---

### F7. Atomic write cleanup bug [CONFIRMED]
**Source:** Codebase critique
**Files:** `tools/map.py:109-112`

`os.get_inheritable(fd)` tests the FD_CLOEXEC flag, not whether the fd is open. Can leak file descriptors or raise on already-closed fd.

**Solution:** Simplify:
```python
except BaseException:
    try:
        os.close(fd)
    except OSError:
        pass
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    raise
```

---

## P1 — Fix Next

### F8. GitHub URL parameter injection [CONFIRMED]
**Files:** `tools/github.py:105,135,158,194`

f-string interpolation without URL encoding. `username = "../../orgs/secret"` traverses API paths.

**Solution:** `urllib.parse.quote(username, safe="")` for path params, `urllib.parse.urlencode` for query params.

---

### F9. OAuth token file permissions [CONFIRMED]
**Files:** `oauth.py:92-102`

No `os.chmod(CACHE_PATH, 0o600)` — token file may be world-readable depending on umask.

**Solution:** Add `os.chmod(CACHE_PATH, 0o600)` after writing.

---

### F10. OAuth callback XSS [CONFIRMED]
**Files:** `oauth.py:151`

Error parameter reflected into HTML without escaping.

**Solution:** `html.escape(error)` before reflection.

---

### F11. CLI analyze seeds false defaults [CONFIRMED]
**Files:** `cli.py:216`, `situation.py:173`

`Hackathon(name="", url=args.url, source="manual")` sends format=VIRTUAL, location="Online" as if they're facts. Agent starts anchored on false premises.

**Solution:** In `_format_hackathon_message`, omit fields that are at their default values. Add: `if h.name: parts.append(f"Name: {h.name}")` and skip format/location when they're defaults from a URL-only construction.

---

### F12. Script/style tag content survives in _html_to_text [PARTIAL]
**Files:** `tools/web.py:92-96`

`_html_to_text` strips tags but preserves text content of `<script>`, `<style>`, and `display:none` elements. This is a prompt injection vector.

**Solution:** Strip `<script>...</script>` and `<style>...</style>` blocks (including content) before tag stripping. Add regex: `re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I|re.DOTALL)`

---

### F13. Hardcoded year in dedup_key [CONFIRMED]
**Files:** `models.py:54`

Strips `" 2026"` and `" 2025"` — breaks in 2027.

**Solution:** Replace with `re.sub(r'\s*20\d{2}\b', '', name)`

---

## P2 — Note for Later

### F14. Token growth in message history [VALID, defer]
Full message history sent every API call. Known limitation of multi-turn agent loops. Future: message summarization or sliding window.

### F15. Agent loop duplication [PARTIAL, defer]
agent.py and situation.py have similar but genuinely different loops (round-based vs tool-call budget). Premature to abstract until more agent types exist.

### F16. Prompt injection [VALID, partially mitigated by F12]
Fundamental to all LLM agents processing web content. F1 (SSRF) and F12 (script stripping) reduce blast radius. Full solution requires content isolation architecture — future work.

### F17. append_log cross-owner writes [REJECTED]
**By design.** append_log is intentionally multi-writer — it's an append-only log for cross-agent communication. The architecture explicitly calls for this (ARCHITECTURE.md ownership model). The critique misunderstands the design intent.

### F18. list_sections reads every file [VALID, defer]
For 10-30 files per hackathon, acceptable. Add index when map grows past ~100 files.

### F19. Serialized tool execution [VALID, defer]
Parallel tool execution would improve wall-clock time but adds complexity to budget accounting and message ordering.

### F20. Ownership is prompt-based [PARTIAL, defer]
In single-agent architecture, the situation room is the only caller. Server-side enforcement requires multi-agent coordination architecture — future work.

---

## Test Gaps to Address

### T1. Budget overshoot test (multi-tool response exceeding budget)
### T2. Cache collision test (enable cache, HEAD then GET same URL)
### T3. SSRF protection tests (blocked schemes, private IPs, metadata endpoints)
### T4. Strengthen weak assertions in test_situation.py (tautological OR conditions)
### T5. fetch_page and check_link coverage in test_tools_web.py

---

## Task Graph

### Wave A — Security & Correctness (parallel, no file overlap)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| A1. URL validation + cache fix + script strip | web-sec | tools/web.py | F1, F6, F12 |
| A2. Budget overshoot + sections tracking | agent-fix | situation.py, agent.py | F2, F5 |
| A3. Path traversal + atomic write | map-sec | tools/map.py | F4, F7 |
| A4. Devpost URL + GitHub URL encoding | platform-fix | tools/platforms.py, tools/github.py | F3, F8 |

### Wave B — Secondary fixes (parallel, no file overlap)

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| B1. OAuth permissions + XSS | oauth-fix | oauth.py | F9, F10 |
| B2. CLI defaults + dedup_key year | misc-fix | cli.py, models.py, situation.py | F11, F13 |

### Wave C — Tests for all fixes

| Task | Agent | Files | Findings |
|------|-------|-------|----------|
| C1. Security + correctness tests | test-sec | tests/* | T1-T5 |

---

## Completion Tracking

| Task | Status | Notes |
|------|--------|-------|
| A1. URL validation + cache + script strip | **done** | _validate_url blocks private IPs, cache namespaced, script/style stripped |
| A2. Budget overshoot + sections tracking | **done** | Inner-loop budget check with is_error results, sections tracked after success |
| A3. Path traversal + atomic write | **done** | resolve() containment check, simplified cleanup |
| A4. Devpost URL + GitHub URL encoding | **done** | urlparse hostname check, quote() on all path params |
| B1. OAuth permissions + XSS | **done** | chmod 600 on token file, html.escape on callback error |
| B2. CLI defaults + dedup_key year | **done** | Skip default format/location in prompts, regex year stripping |
| C1. Security + correctness tests | **done** | 24 new tests: SSRF (10), cache (3), XSS strip (3), budget overshoot (1), symlink (2), Devpost URL (5) + 3 assertion fixes |

## New Findings Log

_Discoveries during implementation go here._

---
