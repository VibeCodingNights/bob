# Situation Room — Implementation Plan

Bob's next layer: the system that reads a hackathon deeply and produces a living semantic map every downstream agent consumes.

**Status: COMPLETE**

---

## Architecture Decisions (from brutalist review)

These are load-bearing. Every task must respect them.

1. **Ownership model for map files.** Each file has exactly one writer agent. No concurrent writes per file. Cross-cutting updates flow through append-only logs.
2. **Two-tier failure policy.** Reversible tools (fetch, search, analyze) fail open with degraded results. Irreversible tools (submit, register, deploy) fail closed and escalate to human.
3. **Canonical event ID.** Derived from `(normalized_name, start_date.date())` or `(source, url)` for single-source events. Stable across the lifecycle.
4. **Retry + cache in web tools.** 3 attempts with exponential backoff. 1-hour response cache. Explicit gap markers when fetches fail.
5. **Tool schemas generate YAML.** The LLM never writes raw YAML/frontmatter. The `write_section` tool accepts structured parameters and produces valid files mechanically.

---

## Task Breakdown

### Wave 1 — Foundation (parallel, no dependencies)

**Task 1: Extract shared web tools → `tools/web.py`**

Move `fetch_page`, `_extract_page_meta`, `_html_to_text`, `_summarize_json_ld`, and `check_link` from `agent.py` into `src/hackathon_finder/tools/web.py`. Create both:
- Async execution functions (what the agent loop calls)
- Anthropic tool definitions (JSON schemas the model sees)

Add retry with exponential backoff (3 attempts, 1s/2s/4s) and a simple response cache (dict keyed by URL, 1-hour TTL, optional).

`agent.py` must still work — import from `tools/web.py` instead of defining its own. All 186 existing tests must pass.

Files: `src/hackathon_finder/tools/__init__.py`, `src/hackathon_finder/tools/web.py`, update `src/hackathon_finder/agent.py`

**Task 2: Implement semantic map tools → `tools/map.py`**

Build the map file operations. The semantic map lives at a configurable root directory (default: `./events/<event-id>/`).

Tools:
- `write_section(path, frontmatter: dict, body: str, owner: str)` — writes a markdown file with YAML frontmatter. Rejects if `owner` doesn't match the file's existing owner (or if file is new, stamps it). Atomic write (temp file + rename).
- `read_section(path) → {frontmatter: dict, body: str}` — reads and parses a map file, returning structured frontmatter and prose body separately.
- `list_sections(prefix?: str) → list[{path, name, type, owner, updated_at}]` — lists map files, optionally filtered by directory prefix. Returns frontmatter metadata only.
- `append_log(path, entry: str, owner: str)` — append-only timestamped entry to a log file (for comms, decisions, progress). Creates file if needed.

All tools must handle: missing files gracefully, invalid YAML in existing files (log warning, return raw), and path traversal prevention (paths must stay within the map root).

Files: `src/hackathon_finder/tools/map.py`

**Task 3: Add canonical event_id to Hackathon model**

Add an `event_id` property to the `Hackathon` dataclass:
- Derived from `hashlib.sha256(f"{normalized_name}:{start_date.date()}")[:12]` when start_date exists
- Falls back to `hashlib.sha256(url)[:12]` when start_date is None
- Deterministic: same inputs always produce same ID
- Used as the semantic map directory name

Add `event_id` to JSON output in `cli.py:_to_json_obj`.

Update existing tests in `test_models.py` to cover `event_id` generation.

Files: `src/hackathon_finder/models.py`, `src/hackathon_finder/cli.py`, `tests/test_models.py`

### Wave 2 — Intelligence tools (depends on Wave 1)

**Task 4: Implement `search_web` in `tools/web.py`**

Add a web search tool using DuckDuckGo HTML search (no API key needed):
- `search_web(query, max_results=5) → list[{title, url, snippet}]`
- Fetches `https://html.duckduckgo.com/html/?q={query}`, parses result entries
- Returns structured results with title, URL, and snippet text
- Same retry/backoff as fetch_page
- Anthropic tool definition included

Depends on Task 1 (shares the retry/cache infrastructure).

Files: `src/hackathon_finder/tools/web.py`

**Task 5: Implement `tools/github.py`**

GitHub public API tools (no auth required, 60 req/hr rate limit):
- `fetch_github_user(username) → {name, bio, company, location, public_repos, top_languages, recent_repos}`
- `fetch_github_repo(owner, repo) → {description, language, stars, forks, open_issues, recent_commits, topics}`
- `fetch_github_releases(owner, repo, limit=5) → list[{tag, date, body_summary}]`
- `search_github_repos(query, limit=5) → list[{full_name, description, stars, language}]`

All tools include Anthropic tool definitions. Handle 403/rate-limit responses with explicit "rate limited" return (not silent failure). Use the retry infrastructure from tools/web.py.

Files: `src/hackathon_finder/tools/github.py`

**Task 6: Implement `tools/platforms.py`**

Deeper platform intelligence, extending existing source patterns:
- `fetch_devpost_winners(hackathon_url) → list[{name, tagline, url, techs, prizes_won}]` — scrape the project gallery for a hackathon
- `fetch_devpost_submission_reqs(hackathon_url) → {fields, required_assets, judging_criteria}` — extract submission format

Use the same httpx patterns as the existing source adapters. Reuse `_html_to_text` and `_extract_page_meta` from tools/web.py.

Files: `src/hackathon_finder/tools/platforms.py`

### Wave 3 — The Agent (depends on Wave 1 + 2)

**Task 7: Build the Situation Room agent → `situation.py`**

The core agent loop for hackathon analysis. Same pattern as `agent.py` but with:
- Research budget (max_tool_calls, not max_rounds) — the agent allocates calls across research directions
- Tool set composed from: tools/web.py (fetch_page, search_web), tools/github.py, tools/platforms.py, tools/map.py (write_section, read_section, list_sections), plus `submit_analysis` termination tool
- System prompt that instructs the agent to:
  1. Fetch the event page and identify tracks, sponsors, judges
  2. Research each (following links, searching the web)
  3. Write map sections as it goes (using write_section)
  4. Cross-reference sections for strategic insights
  5. Write strategy.md as synthesis
  6. Call submit_analysis with a summary when budget is spent or research is complete

The agent returns a `SituationResult` dataclass: `{event_id, map_root, sections_written, token_usage, summary}`.

Key differences from investigation agent:
- Budget counted in tool calls, not rounds
- Writes persistent files during execution (not just a final verdict)
- Larger context (inject the event's full brief into the first user message)
- More tools (8-12 vs 3)
- Longer runs (20-40 tool calls vs 3-5 rounds)

Files: `src/hackathon_finder/situation.py`

**Task 8: Add `analyze` CLI command**

Add `hackathon-finder analyze <url>` (or `--analyze <url>`) to the CLI:
- Takes a hackathon event URL
- Runs the Situation Room agent
- Writes the semantic map to `./events/<event-id>/`
- Prints a Rich-formatted summary to the terminal
- Supports `--json` for structured output
- Supports `--model` for model selection (default: claude-sonnet-4-5-20250929 — analysis needs more capability than haiku)
- Supports `--budget` for max tool calls (default: 30)

Uses argparse subcommands: `hackathon-finder discover` (current behavior) and `hackathon-finder analyze <url>` (new).

Files: `src/hackathon_finder/cli.py`

### Wave 4 — Tests (parallel with Wave 3, depends on Wave 1+2)

**Task 9: Tests for tools/**

Full test coverage for all tool modules:
- `tests/test_tools_web.py` — test fetch_page extraction, retry behavior, cache hits/misses, search_web parsing
- `tests/test_tools_map.py` — test write/read/list/append operations, ownership enforcement, atomic writes, path traversal prevention, malformed YAML handling
- `tests/test_tools_github.py` — test API response parsing, rate limit handling
- `tests/test_tools_platforms.py` — test Devpost gallery parsing, submission requirements extraction

All tests use mocks (httpx mock responses). No real HTTP calls.

Files: `tests/test_tools_web.py`, `tests/test_tools_map.py`, `tests/test_tools_github.py`, `tests/test_tools_platforms.py`

**Task 10: Tests for situation.py**

Agent-level tests matching the pattern in `tests/test_agent.py`:
- Mock the Anthropic client with predetermined responses
- Verify the agent writes map sections via tool calls
- Verify budget enforcement (agent stops when budget exhausted)
- Verify submit_analysis produces correct SituationResult
- Verify the agent handles fetch failures gracefully (gap markers in map)
- Verify ownership stamps on written files

Files: `tests/test_situation.py`

**Task 11: Verify all existing tests still pass**

Run the full test suite (186 existing tests + all new tests). Fix any regressions from the agent.py refactor (Task 1).

---

## Completion Tracking

| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| 1. Extract web tools | **done** | web-tools-agent | Verified: agent.py imports clean, 220 tests pass |
| 2. Map tools | **done** | map-tools-agent | 28 tests in test_tools_map.py |
| 3. Event ID | **done** | model-agent | 7 tests in test_models.py, added to CLI JSON |
| 4. Search web | **done** | search-agent | 15 tests in test_tools_web.py |
| 5. GitHub tools | **done** | github-agent | 14 tests in test_tools_github.py |
| 6. Platform tools | **done** | platforms-agent | 23 tests in test_tools_platforms.py |
| 7. Situation agent | **done** | situation-agent | situation.py: analyze(), SituationResult, 12-tool dispatch |
| 8. CLI command | **done** | cli-agent | Subcommands: discover (default) + analyze |
| 9. Tool tests | **done** | — | Covered by tasks 4,5,6 (52 new tests) |
| 10. Agent tests | **done** | test-agent | 11 tests in test_situation.py |
| 11. Regression check | **done** | — | 283/283 pass, zero failures |

## Findings & Decisions Log

_Updated during implementation. New architectural decisions, surprises, and course corrections go here._

---
