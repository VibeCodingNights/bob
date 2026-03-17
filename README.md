# Bob

Bob is the vibe coder you send to the hackathon in your place.

This repo is the **hackathon discovery** component — an agentic pipeline that scrapes six platforms, deduplicates across them, and investigates each event with a per-event AI agent to verify legitimacy and correct bad metadata.

## What it does

```
6 sources (Devpost, MLH, Devfolio, Luma, Eventbrite, Meetup)
    ↓
Concurrent async fetch + cross-platform deduplication (fuzzy + exact)
    ↓
Structural triage (keyword scoring, duration signals, curated-source confidence)
    ↓
Per-event investigation agent (multi-turn tool use via Anthropic SDK)
    Each event gets its own agent loop:
    ├─ fetch_page(url) → metadata + readable text
    ├─ check_link(url) → HEAD status + redirects
    └─ submit_verdict → valid/invalid + grounded corrections with evidence
    ↓
Validated, corrected hackathon list
```

The investigation agent catches things like organizers listing in-person hackathons as "Online" in their API metadata while the actual page says "Hickman Building, Room 105, University of Victoria." Every correction carries provenance: source URL and extracted text.

## Install

```bash
pip install -e ".[dev]"
```

For sources that require browser scraping (MLH):
```bash
pip install -e ".[scrape]"
```

## Usage

```bash
# Default: SF in-person + virtual, with agent validation
hackathon-finder

# JSON output
hackathon-finder --json

# Filter by source
hackathon-finder --source devpost,luma

# Date range
hackathon-finder --after 2026-03-01 --before 2026-04-01

# Skip validation (no API calls)
hackathon-finder --no-validate

# Use a stronger model for investigation
hackathon-finder --model claude-sonnet-4-5-20250929
```

## Auth

The validation agent needs Anthropic API access. Either:

- Set `ANTHROPIC_API_KEY` env var, or
- Log in with your Claude account (OAuth flow opens browser automatically)

OAuth tokens are cached at `~/.hackathon-finder/oauth.json`.

## Tests

```bash
pytest
```

186 tests. All validation/agent tests use mocks — no API calls.

## Architecture

```
src/hackathon_finder/
├── sources/          # 6 platform adapters (async, independent)
│   ├── devpost.py    #   Devpost HTTP API
│   ├── mlh.py        #   MLH (Inertia.js scrape)
│   ├── devfolio.py   #   Devfolio HTTP API
│   ├── luma.py       #   Luma HTTP API
│   ├── eventbrite.py #   Eventbrite HTTP API
│   └── meetup.py     #   Meetup GraphQL API
├── aggregator.py     # Concurrent fetch, 2-pass dedup (exact + fuzzy Jaccard)
├── validate.py       # Triage → investigate → apply corrections
├── agent.py          # Per-event investigation agent (Anthropic SDK tool use)
├── oauth.py          # PKCE OAuth for Claude Pro/Max (free API access)
├── models.py         # Hackathon, Format, RegistrationStatus
└── cli.py            # Rich terminal UI
```
