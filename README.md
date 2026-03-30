# Bob

Bob goes to hackathons and wins them.

He discovers events across six platforms, reads every page of the brief, understands what the organizers and sponsors actually want, figures out what to build for every track, builds it, and submits. You check back and there's a trophy.

Bob is a [Vibe Coding Nights](https://vibecodingnights.com) project. Every hackathon Bob enters promotes VCN. Every win validates the community. The system that wins hackathons is also the system that grows the community that wins more hackathons.

The full vision is in [ARCHITECTURE.md](ARCHITECTURE.md).

## What's built

### Hackathon discovery

The foundation everything else depends on. Bob scrapes Devpost, MLH, Devfolio, Luma, Eventbrite, and Meetup, deduplicates across all of them, then sends an investigation agent to every event to verify it's real. Organizers list in-person hackathons as "Online" all the time. Bob catches that. Every correction carries provenance: the source URL and the extracted text that proves it.

### Situation Room

Deep strategic analysis of individual hackathons. Given an event URL, an orchestrated 6-phase pipeline (overview → tracks → sponsors → judges → past winners → strategy) fans out concurrent research agents per entity, then synthesizes a strategic playbook. Output is a semantic map — a markdown file tree with YAML frontmatter that downstream agents will consume. Tracks are ranked by expected value, sponsor integrations are mapped, judge panels are profiled, and a strategic playbook with concrete project recommendations is synthesized.

Battle-tested on ETHGlobal Cannes: 28 tracks, 29 sponsors, 47 judges researched across 9 completed phases at 1.0 confidence.

The Situation Room runs via [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python) with 13 MCP tools: web fetching with SSRF protection, GitHub API research, Devpost scraping, and semantic map file operations.

## How it works

Six sources, fetched concurrently. Cross-platform dedup (fuzzy + exact). Structural triage via keyword scoring, duration signals, and curated-source confidence. Then every event gets its own investigation agent — a multi-turn tool-use loop via the Claude Agent SDK that fetches pages, checks links, and submits a grounded verdict.

For deep analysis, the Situation Room runs an orchestrated 6-phase pipeline: overview → tracks → sponsors → judges → past winners → strategy synthesis. The overview agent extracts structured entity data; Python fans out concurrent research agents (semaphore-bounded) per track, sponsor, judge, and past edition. Output is a navigable semantic map at `./events/<event-id>/`.

## Install

```
uv sync
```

Or with pip:

```
pip install -e ".[dev]"
```

## Auth

Bob runs through the Claude Agent SDK, which uses your Claude CLI credentials. Log in with:

```
claude login
```

No API key or OAuth flow needed — the SDK spawns Claude CLI as a subprocess and uses its stored token.

## Usage

```
bob                                               # Discover hackathons (SF in-person + virtual)
bob --json                                        # JSON output
bob --source devpost,luma                         # Filter by source
bob --after 2026-03-01 --before 2026-04-01
bob --no-validate                                 # Skip validation (no API calls)
bob --model claude-sonnet-4-6                     # Stronger investigation model

bob analyze <url>                                 # Situation Room analysis
bob analyze <url> --json                          # JSON output
bob analyze <url> --budget 200                    # Max tool calls (default: 200)

bob team <url>                                    # Team composition from analysis
bob register <url>                                # Register teams on platforms
```

## Tests

```
pytest
```

492 tests. All agent tests use mocks — no API calls.

## Architecture

```
src/bob/
├── sources/          # 6 platform adapters (async, independent)
│   ├── devpost.py        # REST API
│   ├── mlh.py            # Inertia.js page data extraction
│   ├── devfolio.py       # REST API
│   ├── luma.py           # Internal API + hackathon scoring
│   ├── eventbrite.py     # __SERVER_DATA__ brace-walking
│   └── meetup.py         # Apollo cache + __ref resolution
├── tools/            # MCP tool system
│   ├── mcp.py            # MCP server factory + tool registration bridge
│   ├── browser.py        # stealth-browser MCP tools + session manager
│   ├── web.py            # fetch_page, check_link, search_web (SSRF-safe)
│   ├── github.py         # GitHub API (user, repo, search)
│   ├── map.py            # Semantic map file ops (YAML frontmatter, atomic writes)
│   └── platforms.py      # Devpost winners + submission requirements
├── roster/           # VCN member profiles (Flowmapper)
│   ├── models.py         # MemberProfile, Skill, Availability, HackathonEntry
│   └── store.py          # YAML persistence, query by skill/availability
├── accounts/         # Platform identity management
│   ├── models.py         # PlatformAccount, Platform enum
│   ├── vault.py          # OS-agnostic credential storage (keyring + file fallback)
│   └── registry.py       # Account CRUD, session lifecycle
├── personas/         # Event-scoped team identities
│   ├── models.py         # Persona, WritingStyle
│   └── generator.py      # Deterministic persona composition
├── aggregator.py     # Concurrent fetch, 2-pass dedup (exact + fuzzy Jaccard)
├── validate.py       # Triage → investigate → apply corrections
├── agent.py          # Per-event investigation agent (claude-agent-sdk)
├── situation.py      # Situation Room strategic analyzer (claude-agent-sdk)
├── composer.py       # Team Composer (strategy + roster → PortfolioPlan)
├── registration.py   # Registration orchestrator (browser automation per platform)
├── models.py         # Hackathon, Format, RegistrationStatus, event_id
└── cli.py            # Rich terminal UI (bob discover/analyze/team/register)
```

## What's next

The [architecture doc](ARCHITECTURE.md) describes the full system — from discovery through strategic analysis, team assembly, agentic builds, and submission. Each layer is built on the one before it. Current focus: cost optimization for large-event fan-out, registration/submission automation, and deepening the playbook with real post-mortem data.
