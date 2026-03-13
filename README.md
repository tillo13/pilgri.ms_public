# Pilgrims

**[Play Pilgrims](https://pilgri.ms)** | Mars colony management game with real blockchain integration and AI-generated content

---

## What Is This

A Mars colony management game where players mine Sepolia shards, build infrastructure on real NASA Mars coordinates, and explore with AI-generated captains. Deep web3 integration under the hood (every game action is a real Ethereum Sepolia transaction), but the UX is pure game — players never see the word "blockchain."

Your colony runs itself while you sleep. No FOMO, no streaks, no guilt trips. Check in when you want. Or don't. Your Mars colony keeps building either way.

---

## How It Started

This project started at [pilgrim.games](https://pilgrim.games) as a radical experiment: **what if blockchain IS the database?**

No PostgreSQL, no traditional DB — the Ethereum Sepolia testnet was the sole system of record. Every player action, every purchase, every transfer lived entirely on-chain. It worked (and still works), but as the game grew from a tech demo into a real platform with dozens of systems, the pattern needed a traditional database alongside it.

That evolution — from blockchain-as-DB to blockchain-plus-DB — is one of the more interesting technical journeys in this codebase. The Sepolia chain still records every meaningful game action, but PostgreSQL now handles the session state, caching, and complex queries that make the game fast.

---

## The Agentic AI Experiment

**This is the real reason this repo is public.**

Pilgrims is an agentic AI project at two levels: the game is **built by** an AI agent, and it **contains** AI agents that learn and grow alongside the players. The codebase is a living case study in what happens when you give an AI persistent memory, operational skills, and a long-running project.

### How The Game Is Built: Claude Code as Dev Partner

The entire codebase was built through agentic AI collaboration — tracking Claude's evolution from web-only to Claude Code as a persistent development partner. This isn't "AI-generated code." It's a continuous partnership where the AI accumulates institutional knowledge across hundreds of sessions.

The key patterns that emerged:

- **`CLAUDE.md` as the agent's operational brain** — Not a README. A living instruction set that compounds over time. Every bug caught, every convention established, every "never do this again" gets encoded. Each session is smarter than the last because this file grew from a few paragraphs to a dense operational document that prevents repeated mistakes.

- **Skills system** — Reusable multi-step workflows as slash commands. Bug investigation, deployment checklists, QA coverage checks — discovered once, encoded permanently. Every future session inherits them.

- **Auto-memory** — Session continuity across conversations. The AI remembers architectural decisions, user preferences, what failed and why. No more re-explaining context every time.

- **Git as institutional knowledge** — Every commit is a checkpoint the agent can reference. History becomes searchable context for future decisions.

This pattern was proved on [another agentic project](https://github.com/tillo13/mrbeast_puzzle) — 26 days of intensive AI-coordinated work with zero secret leaks, showing the public/private repo split works at scale.

### How The Game Plays: ARIA — An AI That Learns You

ARIA is the colony's AI assistant, and she's the in-game expression of the same agentic philosophy. She's not a static chatbot with canned responses — she's a Claude-powered agent with full awareness of your colony state and a relationship that evolves over time.

**She knows everything about your colony.** Every chat loads a live snapshot: your balance, buildings under construction, active research, crew on expeditions, discoveries, upgrades. Ask "when is my solar array ready?" and she gives you the exact countdown. Ask "what should I research next?" and she reasons from your actual tech tree state.

**She remembers your conversations.** ARIA maintains memory summaries across sessions. She'll reference what you talked about last time, notice patterns in your questions, and build context over weeks of play.

**She evolves through relationship tiers.** New captains meet a mysterious, lore-heavy ARIA (Stranger). As you play — run expeditions, chat more, build your colony — she progresses through Acquaintance, Familiar, and eventually Trusted. A Trusted ARIA drops the mystery act entirely: warm, direct, sometimes dry humor, like a colleague who's been through it all with you. The personality shift is dramatic and earned.

**She gets smarter as we build.** Every new game system we add gets wired into ARIA's colony snapshot. New building type? ARIA can answer questions about it. New research branch? She knows your progress. The agent that builds the game and the agent that lives in the game grow in capability together.

### PilgrimBot: The Codebase Talks Back

PilgrimBot is the meta layer — a bot that reads the live codebase on GCP via Claude API to answer questions about game mechanics. Ask "how is shard generation calculated?" and get a plain-English answer with real math, no code terms, no filenames. A `codemap.json` index (auto-generated on every deploy) maps every file to its purpose and exports, so PilgrimBot finds the right code fast. No rate limits, no sync delays — it reads the same code that's running in production.

When PilgrimBot can't find an answer, it doesn't silently fail — it tells the user honestly and offers to flag the question for the dev team. Bug reports only happen with explicit user confirmation. No auto-filing, no phantom tickets.

### The Public/Private Repo Pattern

- **Private repo**: Operations tooling, credentials, deployment scripts, QA automation, internal bug tracking
- **Public repo** (this one): The full application codebase — routes, utilities, templates, static assets
- **Automated sync**: The deploy tool pushes to both repos on every deploy. An allowlist + secrets scanner ensures nothing sensitive ever reaches the public side. Enforced mechanically, not by discipline.

---

## Engineering Patterns & Architecture

### Flask + PostgreSQL (Cloud SQL)
Single `app.py` routes dispatching to domain-specific utility modules. Hard cap: 1000 lines per file. The codebase went through a full refactoring — a 4,146-line monolithic database file was split into clean domain modules (`db_users.py`, `db_expeditions.py`, `db_map.py`, etc.).

### GCP App Engine
One environment: production. Every `deploy` command goes live to real users at [pilgri.ms](https://pilgri.ms). A centralized deploy tool handles the full pipeline: smoke tests, git push, gcloud deploy, cron.yaml, version cleanup (keeps last 3), and post-deploy health checks with speed benchmarks.

### Performance Discipline
N+1 query detection via automated smoke tests. Caught a regression that ballooned from 22 to 64 DB calls per page load (30+ second response times). Now every deploy runs query-count assertions. Bulk fetching patterns, session caching, lazy-loading tabs, client-side tab switching — speed is treated as a feature, not an afterthought.

### Ethereum Sepolia Integration
Optimistic UI updates with background blockchain threads (transactions take 10-60 seconds). Players see instant feedback while the chain confirms in the background. Deep web3 integration via `web3.py` — real on-chain transactions for every game action, not simulated. Every transaction carries encoded data that's permanently recorded on the Sepolia testnet.

### AI Image Generation
Replicate Flux API generates unique captain portraits, upgrade reveal images, and Mars-material-aesthetic items. A "first reveal" celebration system triggers when players see their unique generated content for the first time.

### Economy System
11 upgrade paths x 10 levels, 4 tech branches x 10 levels, 13 infrastructure buildings x 10 levels. The 1.12x cost multiplier was chosen after extensive balancing to target 3-7 day payoff periods with a 14-day maximum build time cap.

### ARIA (Colony AI)
Claude-powered conversational AI described in detail above. Technically: a live colony snapshot is injected into every chat as system context, conversation memory is summarized and persisted across sessions, and a four-tier relationship system (Stranger → Acquaintance → Familiar → Trusted) switches between entirely different system prompts based on account age, expedition count, and chat history. The Trusted prompt is a fundamentally different personality — concise, warm, zero drama.

### There Are Secrets In This Game
We won't spoil them here. Curious players who dig deep enough will find... things.

### Accessibility
High-contrast, colorblind-safe UI throughout. Custom Mars-themed icon system — zero Unicode emoji in the entire application. CSS theme system with time-of-day variations and forced contrast overrides.

### Frontend Architecture
External JS/CSS only (no inline scripts or styles in templates). A `PAGE_DATA` bridge passes Jinja2 server data to external JavaScript via JSON. Client-side tab switching with lazy-loaded content. All scripts use `defer`, all below-fold images use `loading="lazy"`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask |
| Database | PostgreSQL (GCP Cloud SQL) |
| Blockchain | Ethereum Sepolia testnet (web3.py) |
| AI Images | Replicate Flux API |
| AI Chat | Anthropic Claude API |
| Auth | Google OAuth 2.0 |
| Hosting | GCP App Engine |
| Storage | Google Cloud Storage |
| Frontend | Vanilla JS, CSS (no framework) |

---

## What's In This Repo

All application code: Python routes and utilities, Jinja2 templates, CSS stylesheets, JavaScript modules, configuration files, tool scripts, and documentation.

Credentials, service account keys, and deployment operations live in a separate private repository.

---

## Community

This is a real, open repo — not a mirror or archive.

- **Found a bug?** [Open a GitHub Issue](https://github.com/tillo13/pilgri.ms_public/issues) — we actively triage them
- **Question about how something works?** PilgrimBot answers by reading this codebase — try it in-game.
- **Want to understand the architecture?** Browse the `utilities/` directory — each file has a clear domain. Or ask PilgrimBot!

---

*Built on Mars. Powered by shards. Guided by ARIA.*
