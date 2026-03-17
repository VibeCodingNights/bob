# Bob

Bob goes to hackathons and wins them.

He finds events across six platforms, registers, reads every page of the brief, figures out what to build, builds it, and submits. You check back and there's a trophy.

This repo is the first piece — **hackathon discovery**. Bob scrapes Devpost, MLH, Devfolio, Luma, Eventbrite, and Meetup, deduplicates across all of them, then sends an investigation agent to every event to verify it's real. Organizers list in-person hackathons as "Online" all the time. Bob catches that. Every correction carries provenance: the source URL and the extracted text that proves it.

Bob is a [Vibe Coding Nights](https://vibecodingnights.com) project.

## How it works

Six sources, fetched concurrently. Cross-platform dedup (fuzzy + exact). Structural triage via keyword scoring, duration signals, and curated-source confidence. Then every event gets its own investigation agent — a multi-turn tool-use loop via the Anthropic SDK that fetches pages, checks links, and submits a grounded verdict.

The output is a validated hackathon list where the metadata actually matches reality.

## Install

```
pip install -e ".[dev]"
```

For sources that need browser scraping (MLH):

```
pip install -e ".[scrape]"
```

## Usage

```
hackathon-finder                                  # SF in-person + virtual, validated
hackathon-finder --json                           # JSON output
hackathon-finder --source devpost,luma            # Filter by source
hackathon-finder --after 2026-03-01 --before 2026-04-01
hackathon-finder --no-validate                    # Skip validation (no API calls)
hackathon-finder --model claude-sonnet-4-5-20250929  # Stronger investigation model
```

## Auth

The investigation agent needs Anthropic API access:

- Set `ANTHROPIC_API_KEY`, or
- Let the OAuth flow open your browser (tokens cached at `~/.hackathon-finder/oauth.json`)

## Tests

```
pytest
```

186 tests. All agent tests use mocks — no API calls.

## Architecture

```
src/hackathon_finder/
├── sources/          # 6 platform adapters (async, independent)
│   ├── devpost.py
│   ├── mlh.py
│   ├── devfolio.py
│   ├── luma.py
│   ├── eventbrite.py
│   └── meetup.py
├── aggregator.py     # Concurrent fetch, 2-pass dedup (exact + fuzzy Jaccard)
├── validate.py       # Triage → investigate → apply corrections
├── agent.py          # Per-event investigation agent (Anthropic SDK tool use)
├── oauth.py          # PKCE OAuth for Claude Pro/Max
├── models.py         # Hackathon, Format, RegistrationStatus
└── cli.py            # Rich terminal UI
```
