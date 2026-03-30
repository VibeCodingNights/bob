# Bob

**Bob goes to hackathons and wins them.**

Bob is a vibe coder. Not a tool for vibe coders — Bob *is* one. It discovers hackathons, reads every page of the brief, understands what the organizers are trying to create, figures out what to build for every track, builds it, and submits. You check back and there's a trophy.

Bob is a [Vibe Coding Nights](https://vibecodingnights.com) project. Every hackathon Bob enters is a live demonstration of what VCN builders and their tools can do. Every win validates the community. Every project becomes a showcase. The system that wins hackathons is also the system that grows the community that wins more hackathons.

This document describes what Bob is becoming. The [README](README.md) covers what Bob can do today.

---

## The game behind the game

To win a hackathon, you first have to understand what a hackathon actually is — not what it says on the landing page, but the mechanism underneath.

A hackathon is a coordination game with four principals. Each is optimizing for something different, and the winning project is the one that satisfies all four simultaneously.

### Organizers

An organizer is validating a thesis. A climate hackathon exists because someone believes technology can meaningfully address climate change. A fintech hackathon exists because a bank wants innovation it can't produce internally. The hackathon is their experiment: *if we put talented builders in a room with this problem, will something real emerge?*

The organizer's deepest desire is to be proven right — that the event was worth running, that the community they convened produced something they couldn't have predicted. The project that wins the organizer's heart is the one that embodies their reason for organizing. Not the most technically impressive entry. The one that makes them say, "This is why we do this."

Bob reads the organizer's story — their mission statement, their language, the specific words they chose for the event description. Language reveals values. An organizer who writes "sustainable impact" wants something different from one who writes "disruptive innovation," even if the hackathon topic is the same.

### Sponsors

A sponsor paying $50,000 for a hackathon track is purchasing distribution. What they want, concretely:

- **Developer adoption.** Projects that integrate their API in a way other developers will want to replicate. A creative use case that shows up in a "Built with [Sponsor]" blog post has more value than a technically complex integration nobody will read.
- **Content.** A project their DevRel team can put in a quarterly report, tweet about, present at the next conference. The submission README is marketing collateral in disguise.
- **Signal.** Evidence that talented builders choose their platform over alternatives. The caliber of the team matters almost as much as the project.
- **Relationships.** Meeting builders they might hire, partner with, or feature. The hackathon is a talent pipeline dressed as a competition.

The winning project for a sponsor prize is the one that makes the sponsor's investment look smart to their VP. Bob models this by researching what each sponsor is currently pushing — their recent blog posts, changelog entries, and newly released features. A company that just shipped v4 of their protocol wants to see v4 in action, not v3. A company that just launched a new API endpoint wants creative applications of that specific endpoint. Timing and specificity signal that the builder was paying attention, which is the meta-signal sponsors value most.

### Judges

A judge sees 30–60 projects in a few hours. They are pattern-matching under cognitive fatigue. What they evaluate is not the project — it's the *demo of the project*, compressed into a 3-to-5-minute window.

What judges reward, in order of impact:

1. **Clarity.** A sharp opening line that communicates what this is in three seconds. Judges who don't understand what they're looking at in the first ten seconds have already moved on mentally.
2. **A working demo.** Not a slide deck. Not a walkthrough of code. A live thing that does what it claims to do. The moment the demo works on screen, the judge's assessment shifts from skepticism to evaluation.
3. **Depth when probed.** Judges ask technical questions to calibrate whether the team understands what they built. The difference between "we used a transformer" and "we fine-tuned a LoRA adapter on the sponsor's dataset because the base model hallucinated on domain-specific terms" is the difference between top 10 and top 3.
4. **Vision.** Where does this go after the hackathon? Judges reward projects that feel like the start of something, not a one-off exercise.

Bob's structural advantage: it can research every judge before the event. Professional background, published work, recent public statements, past hackathon judging patterns if available. Not to manipulate — to communicate. A judge who's a design-focused founder responds to UX demonstrations. A judge from a research lab wants to see technical novelty. A judge who invests asks about market size. Calibrating the demo to the panel's composition is the kind of preparation human teams rarely do because it's tedious. For an agent, it's a Tuesday.

### The participant's real game

The most important thing about hackathons that nobody writes in the rules: **the best projects tend to be things the builders genuinely care about.** Authentic engagement with the problem reads in the demo. It reads in the Q&A. It reads in the README. Judges are humans, and humans detect sincerity.

Bob accounts for this by casting VCN members who actually care about each track's domain into the presenter role. An agent can build the code, but the human standing in front of the judges has to mean it. More on this in the section on assembling crews.

---

## The flywheel

Bob exists within a self-reinforcing loop:

```
Discover hackathons → Assemble VCN teams → Build with agentic tooling →
Win (or at minimum, ship impressive work) → Publish as VCN showcase →
Attract more builders to VCN → Deeper roster + accumulated knowledge →
Discover hackathons (with better strategic intelligence) → …
```

This is why Bob is a VCN project rather than a standalone tool. The competitive output (wins) and the community output (VCN growth) are the same thing. The system doesn't choose between winning and promoting — winning *is* promoting.

Each cycle strengthens the next:

- **The roster deepens.** More VCN members means more skills, more authentic domain interests, more hackathon-experienced presenters. Bob gets better at casting because the talent pool grows.
- **The playbook thickens.** Every hackathon teaches Bob about platform patterns, sponsor preferences, judge tendencies, and timing strategies. Institutional knowledge compounds.
- **The reputation builds.** VCN teams that consistently place become known quantities. Organizers invite them. Sponsors seek them out. Judges remember them favorably. Reputation reduces friction at every stage.
- **The content library grows.** Every project is a portfolio piece. The VCN showcase becomes a body of work that demonstrates capability more persuasively than any pitch.

The flywheel has a cold-start problem: Bob needs a roster to field teams, and VCN needs wins to attract builders. The discovery pipeline — what exists today — solves this by being independently useful. VCN members use it to find hackathons worth entering. That gets them into the ecosystem while the full system matures.

---

## Reading the room

When Bob encounters a new hackathon, the first thing it does is understand the event at a depth no human team will match. Not because the information is secret — it's all public. Because the effort of synthesizing it is tedious enough that nobody bothers. Bob always bothers.

This phase is the **Situation Room**: pure comprehension before any building starts.

### Ingestion

Bob reads everything public about the event:

- The event page, track descriptions, rules, FAQ, code of conduct
- Each sponsor's page, API documentation, recent changelog, developer blog
- Judge profiles — professional background, published work, recent public activity
- Past editions of the same hackathon — what won, what judges said, post-event writeups
- The submission platform and its specific requirements (GitHub link? Deployed URL? Video? Slide deck?)
- Community channels — Discord, Slack, Telegram — for tone, culture, recurring questions, and the things organizers say casually that aren't in the official docs

This is not a RAG pipeline. A typical hackathon brief is 5–20 pages. Sponsor API docs relevant to the hackathon's scope are another 10–30 pages. All of it fits in a single context window. Bob reads it whole, the way a careful human reads a contract — except Bob also reads the footnotes, the sponsor's API changelog, and the judges' conference talks from last year.

### The semantic map

Ingested context is structured into a markdown file tree — the **semantic map**. Not a vector database. Not a summary. A navigable, editable representation of everything Bob knows about this hackathon:

```
events/ethdenver-2026/
├── brief.md                  # Event description, rules, timeline, code of conduct
├── tracks/
│   ├── defi.md               # Track requirements, prizes, evaluation criteria
│   ├── social.md
│   ├── ai-ml.md
│   └── public-good.md
├── sponsors/
│   ├── uniswap.md            # Product focus, API surface, recent pushes, what they want
│   └── filecoin.md
├── judges/
│   ├── panel-defi.md         # Each judge's background, interests, communication style
│   └── panel-general.md
├── past/
│   └── 2025-winners.md       # What won last year, judge commentary, patterns
├── submission.md             # Platform, format, deadlines, asset requirements
├── comms/                    # Populated live during the event
│   ├── announcements.md
│   └── rule-changes.md
└── strategy.md               # Bob's analysis (generated after ingestion, updated live)
```

The semantic map is the single source of truth for the duration of the event. Every downstream agent reads from it. When the comms watcher detects a rule change mid-event, it updates the relevant file. When the planner makes a strategic decision, it writes it to `strategy.md` with reasoning. The map grows and evolves as the hackathon unfolds.

This structure also serves the learning loop: after the event, the map becomes an archived case study. Patterns across dozens of archived maps form the playbook.

### Sponsor modeling

For each sponsor, Bob constructs a model of what they're optimizing for at this event:

- **Product focus.** What feature, API, or SDK are they currently pushing? Companies reveal this through blog cadence — three posts about a new feature in the last month means that feature is what their leadership cares about. A project using the shiny new thing gets more internal attention than one using the stable workhorse.
- **Content appetite.** What kind of project would make this sponsor's DevRel team want to write about it? Look at what they've tweeted and blogged about previously. Some sponsors love flashy demos. Others want technically deep integrations with clear documentation that serves as a developer tutorial.
- **Judge alignment.** If the sponsor has people on the judging panel, their individual preferences weight the overall evaluation. A sponsor judge who's an engineer probes differently than one who's a product manager.
- **Historical pattern.** What has this sponsor's track winner looked like at the last three hackathons they've sponsored? Is there a formula? Can Bob either perfect the formula or deliberately break it with something unexpected enough to stand out?

### Judge modeling

The rubric tells you what judges *should* evaluate. The judge's background tells you what they *will* evaluate.

Bob researches each judge as a profile, not just a name:

- What is their professional focus? (An infrastructure engineer looks for different things than a VC.)
- What have they built or invested in? (This reveals aesthetic and technical preferences.)
- How do they communicate? (A judge who tweets in bullet points wants concise demos. A judge who writes long blog posts appreciates depth.)
- Have they judged before? (Public feedback from past hackathons, if available, is gold.)

The output is a **judge briefing** for each track's VCN presenter: anticipated questions by judge, the 2–3 talking points that resonate with this specific panel, and prepared responses to adversarial probes. "Isn't this just a wrapper around [API]?" has a better answer when you know the judge asking it just gave a talk about building on top of existing infrastructure.

---

## Assembling the crew

Bob doesn't submit six identical entries. Bob fields six distinct teams from the VCN roster, each with a human face and authentic enthusiasm for their track.

### Why distinct teams matter

If three submissions to the same hackathon share a code style, README structure, and a suspiciously consistent level of polish, someone notices. The response is disqualification or, worse, public callout. The "Claw Wars" already sensitized the hackathon ecosystem to automated submissions. Agentic participation at scale requires the social sophistication to present as what it actually is: a community of builders using powerful tools.

Each track submission needs:
- A VCN member who can present the demo and answer judge questions with genuine understanding
- A project that reflects that person's real technical interests, augmented by Bob's strategic intelligence and build speed
- A distinct technical approach and narrative voice

Bob isn't pretending humans built everything from scratch. Bob is building the case — through quality of output — that agent-augmented teams produce better work. The conversation about *how* the project was built should be a strength, not a liability. "We used agentic tooling to build across six tracks simultaneously" is a flex at an AI hackathon and an honest answer everywhere else.

### The roster

The **Hacker Flowmapper** maintains a living profile for each VCN member:

| Field | What it captures | Why it matters |
|---|---|---|
| **Identity** | Name, accounts across platforms | Registration, attribution |
| **Skills** | Languages, frameworks, domains, with depth | What they can build and review |
| **Interests** | Problems that excite them, what they want to learn | Authentic engagement reads in demos |
| **History** | Past hackathon entries, placements, judge feedback | Pattern matching, growth tracking |
| **Presentation style** | How they demo — energetic, methodical, narrative-driven | Matching presenter to panel |
| **Availability** | Schedule, timezone, commitment level | Practical constraint |

The last four fields matter as much as skills. A VCN member who's genuinely passionate about decentralized social protocols and presents with enthusiasm is the right cast for that track, even if someone else has deeper Solidity experience. Judges spend 3 minutes with each project. They detect authentic engagement faster than they assess technical depth.

### The portfolio

Bob approaches a multi-track hackathon the way a fund manager approaches a portfolio — diversified by risk, allocated by expected value:

**Execution plays (2–3 tracks).** Well-understood tech stack, clear sponsor alignment, high confidence in a polished submission. These are the consistent top-3 finishes that accumulate prizes and build reputation. Cast the VCN members who present most confidently and whose skills align tightly with the track.

**Moonshots (1–2 tracks).** Novel idea, ambitious scope, higher variance. These are the grand-prize swings — the entries that either win everything or flame out. Cast VCN members who thrive under pressure and can improvise a demo narrative when the live demo partially breaks. The idea matters more than polish here.

**The philosophical entry (1 track).** The project that doesn't optimize for the rubric — it optimizes for *meaning*. Built to embody the organizer's reason for creating the hackathon. This entry might not win a prize. But it's the one judges remember. It's the one that gets VCN invited back as mentors and organizers. It's the one that makes the promotional content most compelling. Over many events, the philosophical entries contribute more to the flywheel than the execution plays.

Bob evaluates each track with a model: `P(placement) × prize + reputation_value + learning_value + content_value`. Some tracks are worth entering at low win probability because the project itself becomes a VCN showcase or a genuine community contribution.

---

## Working backward from the demo

This principle restructures the entire build phase. It is counterintuitive enough to be worth stating emphatically:

**Judges do not evaluate your project. They evaluate your demo of your project.**

A hackathon demo occupies a fixed time window:

| Segment | Duration | Purpose |
|---|---|---|
| The opening line | ~3 seconds | What is this? |
| The hook | ~30 seconds | Why should I care? |
| The live demo | ~90 seconds | Does it work? |
| The landing | ~30 seconds | Where does this go? |
| Judge Q&A | 2–3 minutes | How deep does this go? |

Every segment earns the next. A confused judge at second 10 doesn't recover. A failed live demo at second 60 undermines everything that follows.

Bob works backward from this window. The planner agent's primary output is not a project specification. It is a **demo script**: the exact sequence of interactions that will be shown to judges, the narrative arc that connects them, and the three-sentence explanation that opens the presentation.

The build agents implement the demo script. If the script shows three features, Bob builds three features. Not five. The two un-demoed features are waste — build time that doesn't convert to judge impression.

For moonshot entries, the demo may be aspirational: showing what the system *would* do at production scale, with the hackathon build demonstrating the core mechanism. This is legitimate. Judges reward vision when the foundation works. But the demo still has to work live. A recorded video of something that used to work is not a demo.

### Time as a first-class constraint

A 24-hour hackathon is not 24 hours of build time. After ceremonies, strategy, and submission preparation, approximately 17 hours remain. Bob manages these with hard internal deadlines — not guidelines, not soft targets:

```
Phase 1 — Comprehension         T-24h → T-20h    Read everything, generate strategy
Phase 2 — Design                T-20h → T-18h    Architecture, demo script, planner sign-off
Phase 3 — Build                 T-18h → T-6h     Parallel agents per track
Phase 4 — Integration           T-6h  → T-4h     Assemble, deploy, end-to-end verification
Phase 5 — Polish                T-4h  → T-2h     README, demo prep, submission packaging
Phase 6 — Submit                T-2h  → T-0h     Submit early, buffer for failures
```

**At T-6h, new feature development stops.** This is enforced by the planner, not suggested by it. If a build agent is still debugging a feature at T-7h, the planner makes the call: cut the feature, simplify the approach, preserve what works. The demo script is revised to tell a coherent story about what's actually built, not what was planned.

Most hackathon teams — human and agentic — lose because they build until the deadline, then submit something half-deployed with a panicked README. Discipline in the final six hours is a structural advantage that costs nothing but willpower. Bob has infinite willpower.

For longer hackathons (48h, 72h, week-long), the phases scale proportionally but the principle holds: the last 25% of available time is reserved for integration, polish, and submission. The build window expands; the protection of the endgame does not shrink.

---

## The build

The build phase is where Bob's agentic capability is most visible. It is also where the temptation to over-engineer is highest. The strategic layers — reading the room, casting the crew, designing the demo — are harder to get right and more differentiating than code generation. The build is execution of a plan that's already been carefully shaped.

### The agent structure

Each track's build runs as an independent session:

1. **The architect** receives the demo script, the semantic map, and the track's strategy. It produces a technical design: components and their boundaries, data flow, API contracts between components, deployment target, and the dependency chain that determines build order.

2. **Builders** work in parallel on independent components. A web app might have a frontend builder, an API builder, and a data layer builder running simultaneously. Each operates in a sandboxed environment with file system, terminal, and browser tools scoped to its component. Builders see their component specification and the API contracts — not each other's implementation. This boundary prevents interference and enables parallelism.

3. **The integrator** assembles the components, resolves interface mismatches, runs end-to-end tests against the demo script, and deploys to the target platform. The integration phase is where most agent-built projects fail — it's the seam where individually correct components produce collectively wrong behavior. The integrator's test suite is derived directly from the demo script: if the demo says "user clicks button, data appears," there's a test for exactly that.

4. **The polisher** writes the README (optimized against the judging rubric — yes, explicitly), the project description for the submission platform, and any required assets. If the hackathon values documentation (check the rubric), the polisher produces a developer guide. If it values impact narrative, the polisher writes the impact section. The rubric is the specification.

### Sandboxing

Each track gets its own isolated build environment:

- A container with the language runtime, package manager, and framework dependencies for its tech stack
- A git repository initialized with the architect's scaffold
- Network access scoped to dependency registries and deployment targets
- No access to other tracks' environments, Bob's operational credentials, or the host system
- Compute and token budgets with hard ceilings

Credentials for sponsor APIs and deployment platforms are injected per-container, scoped to minimum necessary permissions, and revoked after submission. A build agent that enters an infinite debugging loop exhausts its container's budget. It does not drain the system.

### When the hackathon demands something new

The most important architectural property of the build system is that it is not templated. The architect agent doesn't select from pre-built scaffolds. It reads the demo script and the track requirements, then reasons about what technical capabilities the build requires.

For a DeFi track, the architect needs Solidity, a frontend framework, and a subgraph indexer. For an AI track, it needs model serving, data processing, and an evaluation harness. For a hardware integration track, it needs firmware interfaces and a physical I/O abstraction. These are fundamentally different builds, and the architect composes the right one each time.

When the hackathon requires a technology outside Bob's established repertoire — a sponsor's API that Bob has never integrated, a framework that emerged last month, a domain-specific protocol — the system enters a research-prototype-reassess loop:

1. A **research agent** reads the unfamiliar technology's documentation, tutorials, example code, and community discussions. It produces a condensed capability brief: what the technology does, how to use it, what the common pitfalls are, and how long integration is likely to take.
2. A **feasibility agent** writes a minimal proof-of-concept. Not a polished implementation — a 50-line script that proves the integration works at all. This takes minutes, not hours, and answers the binary question: can we use this?
3. The **planner reassesses.** If the proof-of-concept works, the architect incorporates the new technology into its design. If it doesn't — if the API is broken, the documentation is misleading, or the integration complexity exceeds the time budget — the planner redirects effort to a track where Bob is stronger.

This loop is runtime capability acquisition. It's the agentic equivalent of a human hacker skimming the docs and hacking together a prototype during a hackathon. Making it explicit — research, then prototype, then decide — prevents the common failure mode of committing to an unfamiliar technology and discovering it's unworkable at T-8h.

This is what "realizes responsibilities and evolves to fit the hackathon" means at the implementation level. Bob doesn't have a fixed set of capabilities. It has a method for acquiring new ones under time pressure.

---

## Adapting in flight

Hackathons are live events. The brief says one thing. Then:

- A sponsor posts a Discord announcement adding a $5,000 bonus prize for best use of their new feature
- The organizers extend the deadline by two hours
- A judge drops out and is replaced by someone with different expertise
- A mentor's offhand comment reveals that the judges are particularly interested in real-world data integrations
- A competing team demos something that overlaps with your approach at a mid-event check-in

Bob needs to absorb these signals and adapt — or consciously decide not to.

### The comms watcher

A background agent monitors all event channels and classifies signals by impact:

**Strategic** — changes to rules, prizes, deadlines, judging criteria, panel composition. These update the semantic map and notify the planner. The planner decides whether to reassess strategy for affected tracks.

**Tactical** — technical tips, API clarifications, mentor availability, workshop schedules. These are routed to the relevant track's architect. A clarification about how a sponsor's API handles edge cases might change a builder's approach but doesn't change the strategy.

**Ambient** — social chatter, food announcements, general encouragement, competitor activity. Logged for post-mortem analysis but not acted on in real time. Exception: if a competitor publicly demos something, that's intelligence, not noise.

### The adjustment spectrum

When a strategic signal arrives, the planner operates across three levels of response:

**Tactical adjustment.** Shift a builder's priority. Add a feature to an execution play that qualifies it for the new bonus prize. Cut a feature that's taking too long. The demo script's core narrative doesn't change. Cost: minutes.

**Strategic pivot.** Rethink a track's approach. Change the project idea. Swap the tech stack. Revise the demo script and reassign build priorities. This happens when new information significantly shifts the expected value — e.g., a new bonus prize worth more than the track's main prize and perfectly aligned with an existing capability. Cost: hours of rebuild, but potentially high payoff.

**Structural reallocation.** Abandon a track entirely and redistribute its compute and human attention to others. This only happens when new information makes a track definitively unviable — a required sponsor API goes down and stays down, or a rule change disqualifies the approach. Cost: sunk investment in the abandoned track.

Each level requires proportionally stronger evidence. A Discord rumor doesn't justify a strategic pivot. An official organizer announcement might. A confirmed API outage justifies structural reallocation. The planner's decision framework is explicitly conservative about disrupting work in progress — the cost of a false pivot (throwing away hours of build time) is usually higher than the cost of missing an opportunity.

---

## The memory

Every hackathon Bob enters is data for the next one. The system that compounds this knowledge across events develops an institutional advantage that grows with every competition.

### Post-mortem

After each hackathon, a post-mortem agent conducts a structured review:

- **Outcomes.** Tracks entered, projects submitted, placements achieved, prizes won.
- **Strategy assessment.** Which predictions about sponsors, judges, and competition were accurate? Which were wrong, and why?
- **Build assessment.** What was the actual time breakdown vs. the budget? Where did builds stall? What technical approaches worked for reliable demos? What broke during integration or live presentation?
- **Comms assessment.** What signals did the watcher catch that mattered? What did it miss? Were there signals that should have triggered a pivot but didn't?
- **Human assessment.** How did VCN presenters perform? What judge questions were unexpected? Where was the human-in-the-loop most valuable?
- **Competitive analysis.** What did winning projects (that we didn't build) do differently? What can Bob learn from them?

The post-mortem is not a report filed and forgotten. It updates the playbook.

### The playbook

Accumulated post-mortems crystallize into reusable knowledge:

**Platform patterns.** "Devpost hackathons with corporate sponsors reward API integration depth. ETHDenver judges are more technical than average. MLH events enforce originality requirements and have younger judge panels. Virtual hackathons with async judging weight the README more heavily than live-judged events."

**Sponsor patterns.** "Uniswap prizes go to projects using the latest protocol version with clear technical documentation. Twilio prizes favor creative use cases with demo-friendly UX. Presenting at sponsor office hours during the event correlates with winning their prize, independent of project quality."

**Timing patterns.** "72-hour hackathons produce better moonshots. 24-hour hackathons favor execution plays. Submitting in the final 30 minutes correlates with worse placement — the submission is rushed, not the project. Early submission allows time for README revision."

**Technical patterns.** "Vercel deployment is more reliable for demo day than Railway. React + FastAPI is the highest-throughput stack for agent-built web apps. Projects with pre-loaded demo data score better than projects requiring manual setup during judging."

The Situation Room consumes the playbook when analyzing each new hackathon. "This event is structurally similar to [past event] where strategy X produced a top-3 finish." Pattern recognition improves with volume. After 10 hackathons, Bob has knowledge no single team can match. After 50, the playbook is a genuine moat.

---

## The control plane

Bob running six tracks simultaneously with dozens of agents is an operational system. It needs observation, cost controls, and clear escalation paths to the VCN crew.

### Observability

The VCN member on watch sees a live dashboard:

```
ETHDenver 2026 — T-14:32:00 remaining
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Track 1 (DeFi)        ██████████░░░░  72%  Building — 2 tests failing
Track 2 (Social)       ████████████░░  85%  Integration — deploying to Vercel
Track 3 (AI/ML)        ██████░░░░░░░░  42%  BLOCKED — sponsor API rate limited
Track 4 (Public Good)  ████████████░░  88%  Polish — writing README
Track 5 (Moonshot)     ████░░░░░░░░░░  30%  Building — architect redesigned approach
Track 6 (Sponsor)      ██████████████  99%  Ready to submit

Comms: 3 new Discord messages (1 strategic — new $5k bonus prize announced)
Budget: $47.20 / $200.00 spent across all tracks
Alerts:
  ▸ Track 3 needs human decision: switch to lighter model or reduce demo scope?
  ▸ Track 5 architect requesting planner review of revised approach
  ▸ New bonus prize aligns with Track 2 — consider adding sponsor API integration
```

The on-watch human can:
- Approve or reject planner decisions (pivots, track abandonment, budget reallocation)
- Override strategy ("drop Track 3, redistribute to Track 5")
- Submit early for tracks that are ready
- Inject intelligence that agents can't access ("I talked to the Uniswap judge at the coffee line — she specifically cares about gas optimization")

Most of the time, the human watches. The system runs. The human intervenes when judgment, social information, or ethical assessment is needed — things agents handle poorly and humans handle instinctively.

### Cost controls

Each track has a compute budget (API tokens, container runtime, deployment costs). When a track hits 80% of budget, the planner is notified and can reallocate from lower-priority tracks or cut scope. A hard system-level ceiling prevents total spend from exceeding the expected value of the hackathon's prizes.

Token usage is tracked per-agent, per-track, per-phase. After the event, this data feeds the post-mortem — which tracks were cheap to build? Which were expensive? Cost efficiency per prize dollar is a metric that improves with playbook knowledge.

### Security

Bob operates in a hostile information environment. Hackathon briefs, sponsor pages, Discord channels, and submission platforms are all untrusted input.

**Ingestion defense.** The brief-reading pipeline treats all external content as data, not instructions. Structuring ingested content into the semantic map (discrete markdown files per topic) naturally segments it, reducing the blast radius of any single poisoned input. Build agents read from the semantic map, not raw web pages.

**Sandbox isolation.** Build containers have no access to other tracks, Bob's operational credentials, or the host system. A compromised build environment can waste compute on its own track. It cannot affect others.

**Credential hygiene.** Sponsor API keys are generated per-event, scoped to minimum permissions, and revoked after submission. Bob's core credentials (Anthropic API key, VCN accounts, deployment platform access) never enter a build container.

**Irreversibility gate.** Actions that can't be undone — submitting a project, posting publicly, registering with a real identity — require explicit human approval through the control plane. The on-watch human is the last line of defense against an agent that's confident but wrong.

---

## What's hard

Intellectual honesty about the problems without clean solutions.

### The idea

Hackathon judges reward novelty and narrative at least as much as execution quality. "Technically impressive but predictable" loses to "simple but surprising." Language models generate ideas from the distribution of what already exists. They produce the median of creative output, not the outlier.

The project idea is the point of highest leverage in the entire system. It's also where current agent capabilities are weakest.

Bob's approach: generate multiple ideas per track, informed by the sponsor/judge models, competitive analysis of past winners, and the VCN roster's authentic interests. Present these to the VCN human assigned to the track. The human selects, refines, or replaces. Over time, as the playbook accumulates patterns of what wins and what doesn't, Bob's proposals sharpen. But ideation may permanently be the stage where human taste has the highest marginal return.

### The live demo

Demos break. Not because the code is wrong — because the WiFi drops, the database cold-starts too slowly, the third-party API rate-limits during the presentation, the browser caches stale state. Agent-built projects that pass every test in CI can fail live for reasons no test anticipated.

Bob mitigates this with demo-hardened builds: pre-loaded sample data, offline fallback states, graceful error messages that tell a story ("loading from decentralized storage — this takes a moment"), and health checks that run before the presentation starts. But mitigation isn't elimination. The VCN presenter needs to be someone who can navigate a broken demo with composure — which loops back to casting.

### Video

Many hackathons require or heavily weight video submissions. Screen recording is automatable. Compelling narration is not — not yet, not reliably. A two-minute video that tells a story about why this project matters, with natural pacing and genuine enthusiasm, is a different production challenge than building the project.

Current approach: Bob provides the script, talking points, and a structured shot list. The VCN presenter records. This is a human-in-the-loop moment. It may become automatable as generative video and voice synthesis mature, but today it's a manual step in an otherwise automated pipeline.

### Platform evolution

If agentic hackathon participation becomes widespread, organizers will respond: proof-of-humanity requirements, mandatory live coding segments, in-person-only judging, account age thresholds. Bob's long-term resilience depends not on defeating these measures but on transcending them — building projects good enough that the method of construction is irrelevant. "Was this AI-generated?" has a weaker sting when the project genuinely solves the stated problem better than anything else submitted.

The VCN model helps here. Bob doesn't hide behind fake identities. VCN is a real community with real members who attend real events. The agent augments their capabilities. That's a different narrative than "a bot entered your hackathon," and it's a narrative that hackathon culture will eventually embrace — because builders using advanced tools is what hackathons are supposed to celebrate.

### Integration under pressure

The integration agent — the one that assembles independently built components into a working system — handles the hardest technical challenge in the pipeline. Components that are individually correct produce collectively wrong behavior when their assumptions about shared state, authentication, data format, or timing don't align.

Integration failures compound under time pressure. Debugging a mismatch between the frontend's expected API response shape and the backend's actual response shape is straightforward in isolation. Debugging it at T-5h while also deploying to production and writing the README, across six parallel tracks, is operationally intense.

The architectural defense is modularity — clean API contracts defined upfront by the architect, typed interfaces that catch mismatches at build time rather than demo time, and integration tests derived directly from the demo script. The operational defense is the time budget — the T-6h hard stop on feature development exists specifically to protect integration time.

---

## What exists today

### Discovery layer (production-ready)

- **Six source adapters** — Devpost, MLH, Devfolio, Luma, Eventbrite, Meetup. Concurrent fetch, each with platform-specific extraction (REST APIs, Inertia.js page data, `__SERVER_DATA__` brace-walking, Apollo cache resolution).
- **Two-pass deduplication** — exact key match (normalized names), then fuzzy token overlap (Jaccard similarity ≥ 0.7 with date alignment). Cross-platform: the same hackathon listed on Devpost and Luma is correctly identified as one event.
- **Structural triage** — keyword scoring, duration signals, and curated-source confidence to filter non-hackathons before expensive agentic investigation.
- **Agentic validation** — per-event investigation agent via the Claude Agent SDK. Each agent fetches pages, checks links, and submits a verdict with provenance: the source URL and the extracted text that supports each correction.

### Situation Room (battle-tested)

- **Orchestrated 6-phase pipeline** — overview → tracks → sponsors → judges → past winners → strategy synthesis. The overview agent writes YAML frontmatter with structured track/sponsor/judge arrays; Python parses this to fan out concurrent research agents per entity. Each phase gets its own agent, budget, and system prompt.
- **Concurrent research with semaphore(3)** — after the overview phase, track/sponsor/judge/past-winner research runs in parallel, bounded by `asyncio.Semaphore(3)` to limit concurrent CLI subprocesses. Phase budgets: overview:15, track:10, sponsor:8, judge:6, past:10, strategy:20 max_turns.
- **13 MCP tools** — web fetching (SSRF-safe, redirect-validated), GitHub API (user/repo/search), Devpost scraping (winners/submission requirements), semantic map operations (write/read/list/append with atomic writes and path traversal prevention).
- **Claude Agent SDK integration** — agents run via `claude-agent-sdk` with in-process MCP servers, `bypassPermissions` mode, and token tracking. Built-in CLI tools are blocked via `disallowed_tools` to enforce the MCP tool boundary.
- **Battle-tested** — ETHGlobal Cannes: 9/9 phases completed, 9 sections written, 1.0 confidence, ~1.1M input tokens. Strategy output includes concrete project recommendations with prize capture estimates per track.

The investigation agent pattern in `agent.py` — system prompt defining the role, tools for world interaction, multi-turn loop with token tracking, conservative fallback on failure, provenance on every claim — is the prototype for every agent in the system. The orchestrator in `situation.py` extends it to multi-agent coordination.

### SDK lessons learned

Two hard-won discoveries from battle testing:

- **Stream close timeout.** The SDK closes stdin after `CLAUDE_CODE_STREAM_CLOSE_TIMEOUT` (default 60s), killing MCP tool calls for any phase lasting longer. Fix: `os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")` at module level, before any SDK imports. The `env` option in `ClaudeAgentOptions` only affects the CLI subprocess, not the SDK's Python process where the timeout is read.
- **Built-in tool escape.** `allowed_tools` controls which MCP tools the agent can call, but doesn't restrict built-in Claude Code CLI tools. Without `disallowed_tools`, agents use Bash, Write, and WebFetch directly instead of the tracked MCP tools. Fix: block all 11 built-in tools via `disallowed_tools`.

### Crew pipeline (built)

The infrastructure between strategic analysis and building:

- **Roster** (`roster/`) — `MemberProfile` with skills, interests, availability, presentation style, and a flexible `attributes: dict[str, str]` for arbitrary platform-specific data (email, wallet address, shirt size — whatever platforms demand). YAML persistence via `platformdirs` (OS-agnostic). Query by skill domain, availability window.
- **Accounts** (`accounts/`) — `PlatformAccount` per member per platform (Devpost, ETHGlobal, GitHub, Luma, Devfolio). Fingerprint config (serialized stealth-browser `PlatformConfig`) bound to the account for cross-session consistency. Credentials isolated in OS keyring (macOS Keychain / Windows Credential Locker / Linux Secret Service) with `FileVault` fallback for CI. Session state (Patchright `storage_state` JSON) for login persistence.
- **Personas** (`personas/`) — Event-scoped identity per team member. `WritingStyle` (readme voice, commit style, communication tone) varies by `PresentationStyle` enum. Same member gets distinct persona per hackathon to prevent cross-submission pattern matching.
- **Browser tools** (`tools/browser.py`) — 7 MCP tools wrapping stealth-browser's Patchright async API. `BrowserSessionManager` holds live browser/context/page objects across tool calls within a phase. Import-guarded — module loads cleanly without stealth-browser installed.
- **Team Composer** (`composer.py`) — Agent-based portfolio allocation. Reads the Situation Room semantic map + roster, runs a Claude agent that assigns members to tracks as execution plays (2–3), moonshots (1–2), and philosophical entries (1). Output: `PortfolioPlan` with `TrackAssignment` per track.
- **Registration orchestrator** (`registration.py`) — Concurrent browser-automated sign-ups (`Semaphore(2)`). Platform-specific agent prompts (Devpost, ETHGlobal, Luma, generic fallback). Each registration gets its own browser session with the account's fingerprint binding. Escalation tools (`resolve_field`, `escalate`, `record_platform_field`) handle unknown form fields and teach the system for future registrations.

### Adaptive registration (built)

Registration forms vary wildly across platforms — and even across events on the same platform. Rather than hardcoding every possible field, the system learns what platforms need through experience:

**Profile attributes are open-ended.** `MemberProfile.attributes` is a `dict[str, str]` — no predefined schema. The first time ETHGlobal asks for a wallet address, it becomes a key. Forever.

**Escalation teaches the system.** When the registration agent encounters a form field it can't fill, it calls `resolve_field` to check the member's attributes, then `escalate` if missing. The escalation handler (pluggable — default is terminal I/O, replaceable with Slack/web/agent) surfaces the question to a human. The answer is written to both the member's profile and the `PlatformFieldRegistry`, so the system never asks the same question again for the same platform.

**Pre-flight validation.** `bob register` cross-references the `PlatformFieldRegistry` against each member's `attributes` before launching browser agents. Known gaps are resolved in batch. Login readiness is checked — accounts without valid session state are flagged. `--force` bypasses the login check.

**Profile data threading.** Registration agents receive the full member profile (attributes, skills, interests, persona bio) in their context, so they can fill forms with what's already known before escalating for what isn't.

### Account lifecycle (built)

**`bob account ensure <platform> <member_id>`** handles all three cases:

1. **Account exists, session fresh** → return immediately
2. **Account exists, session stale** → automated re-login, escalate only for 2FA/CAPTCHA
3. **No account** → autonomous signup via stealth-browser agent

**Signup agent** (`signup.py`) — Claude agent with browser tools navigates platform signup forms. Prefers OAuth over email/password (see Identity Architecture below). Fills fields from member attributes and generated credentials. Screenshots before every escalation. Marks account as "pending" during signup, "active" on success — failed signups are cleaned up and retried.

**Automated login agent** (`autologin.py`) — loads stored credentials from vault, fills login forms via browser tools. 2FA codes resolved via TOTP resolver (no human needed when secret is stored). Falls back to interactive (headless=False) on failure.

**Credential generation** (`accounts/credentials.py`) — `secrets.token_urlsafe` for passwords, stored in vault, fingerprint config generated per account. Credentials never logged or printed.

**Browser tools** — 11 MCP tools wrapping stealth-browser's Patchright API: navigate, click, fill, extract_text, screenshot, close_session, create_session, save_session, evaluate, wait_for_navigation, select_option. Sessions persist across tool calls within a phase. `BrowserSessionManager` accepts `headless` parameter.

**Pre-flight integration** — `bob register` calls `ensure_all_accounts()` after gap resolution. Missing accounts are created, stale sessions are refreshed, before any hackathon registration starts.

### Resolver chain (built)

`resolve_field` is a unified MCP tool backed by a `ResolverChain` — a dispatch over registered resolvers. The agent calls `resolve_field(field_name, member_id)` and the chain tries each resolver in order, returning the first non-None result. If all miss, returns "unknown" and the agent escalates.

```
resolve_field("2fa_code", "noot")
  → AttributeResolver:  member.attributes["2fa_code"]       → miss
  → TOTPResolver:        vault["noot-devpost-totp"]          → hit → pyotp.now() → "482937"
  → return "482937"

resolve_field("email", "noot")
  → AttributeResolver:  member.attributes["email"]           → "noot@vcn.dev"
  → return "noot@vcn.dev"

resolve_field("shirt_size", "noot")
  → all resolvers miss → return "unknown" → agent escalates
```

**Built-in resolvers** (cheapest first):
- `AttributeResolver` — `member.attributes[field_name]`
- `TOTPResolver` — vault TOTP secret → `pyotp.TOTP.now()` (lazy import, secret never logged)
- `CredentialResolver` — vault password lookup

New resolvers slot in without changing agent prompts or tool schemas. The escalation surface shrinks with every resolver added.

### Identity architecture (designed, not yet built)

Battle testing revealed the core identity problem: reCAPTCHA blocks direct email/password signup on Devpost because it detects the Chrome DevTools Protocol that Patchright uses for browser control. stealth-browser passes Cloudflare Turnstile but not Google's reCAPTCHA. This isn't fixable in JavaScript — it's a protocol-level signal.

The solution isn't to defeat reCAPTCHA. It's to avoid it entirely.

**OAuth as the primary authentication path.** Nearly every hackathon platform supports "Sign up with GitHub":

| Platform | GitHub OAuth | Google OAuth | Email/Password |
|----------|-------------|-------------|----------------|
| Devpost | ✓ | ✓ | ✓ (reCAPTCHA) |
| ETHGlobal | ✓ | — | ✓ + wallet |
| Devfolio | ✓ | — | ✓ |
| Luma | — | ✓ | magic link |
| GitHub | — | — | ✓ (CAPTCHA) |

GitHub is the root identity. One manually-created GitHub account unlocks every other platform via OAuth — no CAPTCHAs, no email verification, no per-platform password management. The OAuth flow is three clicks: "Sign up with GitHub" → authorize → done.

**The identity graph:**

```
GitHub account (root — created manually once, profile warmed)
  ├── OAuth → Devpost (auto-populates name, avatar, repos from GitHub)
  ├── OAuth → ETHGlobal (auto-populates profile from GitHub)
  ├── OAuth → Devfolio (auto-populates profile from GitHub)
  └── (GitHub profile IS the hackathon identity)

Google account (secondary — for platforms without GitHub OAuth)
  └── OAuth → Luma
```

**Why this is architecturally significant:**

1. **Profile warming is free.** When Bob signs up on Devpost via GitHub OAuth, Devpost auto-populates the profile — name, avatar, bio, linked repos. The "bare profile" problem vanishes. Bob's GitHub profile IS the profile, propagated everywhere through OAuth.

2. **One session to maintain.** Instead of N independent email/password credentials with N session states, Bob maintains one GitHub session. If it expires, one re-login refreshes the root; OAuth flows on downstream platforms just work because they redirect through GitHub's auth.

3. **The GitHub account is infrastructure, not just auth.** Hackathon projects live on GitHub. Judges click through to repos. The GitHub identity carries reputation — contribution history, stars, pinned repos. A Devpost submission linking to a GitHub org with real projects signals credibility in a way that an anonymous email signup never will.

4. **Credential surface area collapses.** No per-platform passwords to generate, store, rotate, or leak. The vault stores one GitHub session + TOTP secret. OAuth tokens are ephemeral and platform-managed.

**Auth strategy chain.** The signup agent tries authentication methods in order of preference, mirroring the resolver chain pattern:

```
Signup on Devpost:
  → GitHubOAuthStrategy: find "Sign up with GitHub" button → click → authorize → done
  → GoogleOAuthStrategy: find "Sign up with Google" → click → authorize → done
  → EmailPasswordStrategy: fill form → handle CAPTCHA → verify email
  → EscalateStrategy: human creates account manually

Login on Devpost:
  → SessionResumeStrategy: load storage_state → navigate → verify logged in → done
  → GitHubOAuthStrategy: find "Log in with GitHub" → click → authorize → done
  → EmailPasswordStrategy: fill form → TOTP for 2FA → done
  → EscalateStrategy: human logs in manually
```

The strategy chain is learned per platform. After Bob signs up on Devpost via GitHub OAuth, the auth strategy registry records: "devpost supports github_oauth for signup." Next signup on Devpost tries that first. Same learning loop as the `PlatformFieldRegistry`.

**What needs to be built:**

1. **GitHub session as prerequisite.** `bob account ensure github bob` must succeed before any OAuth-dependent signups. This is the one manual step — create the GitHub account by hand, run `bob login bob-github` to save the session.
2. **Auth strategy detection.** The signup agent's system prompt instructs: "Before filling any form, look for OAuth buttons ('Sign up with GitHub', 'Continue with GitHub', 'Log in with GitHub'). If found, prefer OAuth over the email/password form."
3. **Auth strategy registry** (`~/.bob/auth_strategies/`). Records which auth methods work on which platforms. Same YAML persistence pattern as `PlatformFieldRegistry`.
4. **OAuth session propagation.** After successful OAuth signup, the new platform's session state is saved. The GitHub session is implicitly re-validated.
5. **GitHub profile warming agent.** After the GitHub account is created: fill bio, set avatar, pin repos, ensure the profile looks real. This runs once, not per-hackathon.

The identity graph reduces Bob's external authentication surface to a single manually-created GitHub account. Everything downstream is automated through OAuth. The one human action — creating the GitHub account and completing its CAPTCHA — is a one-time cost that unlocks the entire platform ecosystem.

### Security posture

Four rounds of security auditing have hardened the system:
- SSRF protection with DNS resolution, private IP blocking, redirect-hop validation, and HTTPS downgrade prevention
- Path traversal prevention with symlink resolution, containment checks, and `_safe_filename()` sanitization on all user-controlled IDs
- Atomic file writes with pre-set permissions
- URL validation (scheme, userinfo, hostname) for all external fetches
- Pagination bounds, cache size limits, and rate limit awareness
- Credential isolation: vault-backed storage, never in YAML, restrictive file permissions (0o600)
- Browser fingerprint binding: deterministic per account, prevents cross-session detection
- Credential leakage prevention: negative assertions verify sensitive fields never appear in agent prompts

### Agent telemetry (designed, not yet built)

Battle testing exposed a structural visibility gap: 7 agent modules (situation, investigation, signup, autologin, registration, composer, profile warming) each contain a copy-pasted `async for message in query()` loop with ad-hoc logging. When an agent fails, the only output is "ExceptionGroup" — no trace of what it did, what it saw, or where it got stuck. Browser agents are especially opaque — the agent could click the same button 40 times with no external indication.

**AgentSession** — a structured event log per agent run. Every tool call, tool result, message, error, and escalation produces an `AgentEvent` written to a JSONL file as it happens (survives crashes). Fields: timestamp, agent name, turn number, event type, data dict.

**`run_agent()`** — a unified query runner that replaces all 7 duplicated loops. Handles the `async for message in query()` iteration, token tracking, error handling, and telemetry in one place. Every agent module calls `run_agent()` instead of managing its own loop.

**`instrument_tools()`** — wraps MCP tool handlers to log inputs and outputs automatically. No per-tool instrumentation needed — the wrapper captures tool name, args (redacting passwords), result summary, and duration.

**Live terminal output** — during agent execution, prints a status line per turn: `[signup:bob:github] Turn 5/50 | browser_fill(#email) → ok | 12s elapsed`. Replaces the current silence between "Ensuring..." and "Failed."

**Session logs** — persisted to `~/.bob/logs/{agent}-{timestamp}.jsonl`. `bob logs` CLI to replay. `bob logs --last` for the most recent.

### Test coverage

657 tests across discovery, analysis, crew pipeline, adaptive registration, account lifecycle, resolver chain, identity architecture, and CLI. All agent tests use mocks — no API calls in CI. Path traversal regression tests on all file-writing modules. Credential leakage negative assertions on all agent prompt paths.

---

## The path

Each layer depends on the ones below it. Each is independently useful before the next one exists.

**Done → Situation Room.** 6-phase orchestrated pipeline, battle-tested at 1.0 confidence. Four events analyzed (ETHGlobal Cannes, Grizzly Hacks III, HackAmerica, United Hacks V7).

**Done → Crew pipeline.** Roster (flexible attributes), accounts (fingerprint-bound), personas (event-scoped), composer, browser tools (11 MCP tools wrapping stealth-browser), registration orchestrator with escalation.

**Done → Adaptive registration.** Resolver chain (attribute + TOTP + credential), platform field registry, pre-flight validation, profile threading. The system learns what platforms need through experience.

**Done → Account lifecycle.** Signup agent, auto-login agent, `ensure_account` (3-way: fresh/stale/missing), credential generation. Pre-flight integration creates accounts and refreshes sessions before registration.

**Now → Identity architecture (OAuth cascade).** GitHub as root identity, OAuth into all downstream platforms. Auth strategy chain (GitHubOAuth → GoogleOAuth → EmailPassword → Escalate) mirrors the resolver chain. Auth strategy registry learns which methods work per platform. GitHub profile warming agent. One manual account creation unlocks the entire ecosystem.

**Now → Battle test on a real hackathon.** United Hacks V7 (July 10, $26K). Complete the pipeline: `bob discover` → `bob analyze` (done, 1.0 confidence) → `bob team` → `bob account ensure` (via OAuth) → `bob register`. Every failure teaches the system.

**Then → Cost optimization.** ~1.1M input tokens per large-event analysis. Per-phase model selection (Haiku for entity research, Sonnet for strategy), prompt caching, and entity prioritization.

**Then → The build system.** Architect → builders → integrator → polisher. Demo-first development. The novel engineering is dynamic builder composition for unfamiliar tech stacks.

**Then → The control plane and learning loop.** Dashboard, cost controls, post-mortem automation, playbook accumulation.

Each layer delivers value alone. Bob accretes capability without requiring the full vision to justify each step.
