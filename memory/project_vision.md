---
name: Bob project vision and current state
description: Bob is an agentic system that finds and wins hackathons for VCN at Frontier Tower SF. Current state as of 2026-03-21 plus architectural roadmap.
type: project
---

Bob is a vibe coder — an autonomous system that discovers hackathons, reads briefs, builds projects for every track, and submits. Every win promotes Vibe Coding Nights (VCN) at Frontier Tower, 995 Market St, SF.

**Why:** VCN is building a community of builders at Frontier Tower. Hackathon wins validate the community and attract more members. The flywheel: win → promote → attract → deepen roster → win bigger.

**How to apply:** Bob is not a pipeline with fixed stages. It reads each hackathon and self-organizes — deciding what to build, who to cast from the VCN roster, how to allocate effort across tracks. When working on Bob, respect this adaptive architecture. Don't template or rigidly define agent roles — the planner agent should compose the right team dynamically based on what the hackathon demands.

**Current state (2026-03-21):**

Built and working:
- Discovery layer: 6 source adapters, 2-pass dedup, structural triage, agentic validation
- SDK migration complete: both agents run via `claude-agent-sdk` v0.1.50 (MCP tool servers, bypassPermissions, cache-aware token tracking)
- Situation Room agent: 13-tool dispatch, semantic map generation, 8-phase workflow in prompt
- 3 rounds of security hardening (SSRF, path traversal, redirect safety, protocol downgrade, atomic writes)
- 356 tests, all passing
- CLI: `hackathon-finder discover` + `hackathon-finder analyze <url>`
- OAuth removed — SDK uses Claude CLI's stored credentials

Known issues:
- Situation Room doesn't reliably complete all 8 phases within budget (spends all turns on deep per-track research)
- ExceptionGroup from SDK's asyncio.TaskGroup — fixed with BaseException catch (uncommitted)
- Empty playbook — no accumulated knowledge from past events
- No downstream consumers of the semantic map yet

**Key architectural principles:**
- Demo-first development: work backward from the 3-minute demo, not forward from a feature list
- Portfolio strategy: execution plays + moonshots + philosophical entries per event
- Hard time budgets: T-6h feature freeze enforced by planner
- Runtime capability acquisition: research → prototype → reassess loop for unfamiliar tech
- The VCN roster is a casting system, not just a skills database — enthusiasm and presentation style matter as much as technical depth
- Social sophistication required: the Claw Wars (OpenClaw/Clawdbot controversy Feb 2026) sensitized the hackathon ecosystem to automated submissions. Bob presents through real VCN members, not fake identities.

**Roadmap (each layer independently useful):**
1. ~~Discovery~~ — done
2. Situation Room — built, needs reliability tuning (prompt pacing, playbook seed)
3. Hacker Flowmapper — VCN roster, team composition, track casting
4. Build system — architect → builders → integrator → polisher
5. Registration/submission — browser automation via Playwright MCP
6. Control plane + learning loop — dashboard, cost controls, post-mortems, playbook accumulation
