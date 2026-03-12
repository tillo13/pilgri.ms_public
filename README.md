# Pilgrims

**[Play Pilgrims](https://pilgri.ms)** | Mars colony management game with real blockchain integration and AI-generated content

---

## What Is This

A Mars colony management game where players mine Sepolia shards, build infrastructure on real NASA Mars coordinates, and explore with AI-generated commanders. Deep web3 integration under the hood (every game action is a real Ethereum Sepolia transaction), but the UX is pure game — players never see the word "blockchain."

Your colony runs itself while you sleep. No FOMO, no streaks, no guilt trips. Check in when you want. Or don't. Your Mars colony keeps building either way.

---

## How It Started

This project started at [pilgrim.games](https://pilgrim.games) as a radical experiment: **what if blockchain IS the database?**

No PostgreSQL, no traditional DB — the Ethereum Sepolia testnet was the sole system of record. Every player action, every purchase, every transfer lived entirely on-chain. It worked (and still works), but as the game grew from a tech demo into a real platform with dozens of systems, the pattern needed a traditional database alongside it.

That evolution — from blockchain-as-DB to blockchain-plus-DB — is one of the more interesting technical journeys in this codebase. The Sepolia chain still records every meaningful game action, but PostgreSQL now handles the session state, caching, and complex queries that make the game fast.

---

## The Agentic AI Experiment

**This is the real reason this repo is public.**

The entire codebase was built through agentic AI collaboration — tracking Claude's evolution from web-only to Claude Code as a persistent development partner.

### Pre-Claude Code Era
Web Claude conversations, manual copy-paste between sessions, context lost every time the window closed. It worked, but every session started from scratch. You'd explain the same architectural decisions over and over.

### Claude Code Era
Everything changed. The key patterns that emerged:

- **`CLAUDE.md` as the agent's operational brain** — Not a README. A living instruction set that prevents repeated mistakes. Every bug caught, every convention established, every "never do this again" gets added. It compounds — each session is smarter than the last because the instruction file grew from a few paragraphs to a dense operational document.

- **Skills system** — Reusable multi-step workflows as slash commands. When you discover a pattern that works (like a bug investigation process or a deployment checklist), you encode it once. Every future session inherits it.

- **Auto-memory** — Session continuity across conversations. The AI remembers what was decided, what failed, what the user prefers. No more re-explaining.

- **Git as state machine** — Every commit is a checkpoint. The agent can look back at what changed, when, and why. Git history becomes institutional knowledge.

### The Public/Private Repo Pattern

This pattern was proved on [another agentic project](https://github.com/tillo13/mrbeast_puzzle) — 26 days of intensive AI-coordinated work with zero secret leaks. The approach:

- **Private repo**: Operations tooling, credentials, deployment scripts, QA automation, internal bug tracking
- **Public repo** (this one): The full application codebase — routes, utilities, templates, static assets, documentation
- **Automated sync**: The deploy tool pushes to both repos on every deploy. An allowlist + secrets scanner ensures nothing sensitive ever reaches the public side. Enforced mechanically, not by discipline.

### PilgrimBot (Coming Soon)

An in-game bot that queries THIS repo via Claude API to answer questions about game mechanics. Anyone can ask "how is shard generation calculated?" and get a plain-English answer. The public repo is the knowledge base. Meta.

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
Replicate Flux API generates unique commander portraits, upgrade reveal images, and Mars-material-aesthetic items. A "first reveal" celebration system triggers when players see their unique generated content for the first time.

### Economy System
11 upgrade paths x 10 levels, 4 tech branches x 10 levels, 13 infrastructure buildings x 10 levels. The 1.12x cost multiplier was chosen after extensive balancing to target 3-7 day payoff periods with a 14-day maximum build time cap.

### ARIA (Colony AI)
Claude-powered conversational AI with full colony state context injection. ARIA knows your balance, your buildings, your active research, your expeditions — she can answer any question about your colony's current state. Persistent conversation history with memory summaries. A relationship progression system (Stranger through Trusted) that evolves based on interaction patterns.

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
- **Question about how something works?** PilgrimBot (coming soon) will answer by reading this codebase. Until then, browse the docs.
- **Want to understand the architecture?** The `docs/` folder is thorough

---

## Explore The Docs

- **[PILGRIMS.md](docs/PILGRIMS.md)** — The design bible. Story, philosophy, game systems, visual style guide
- **[architecture.md](docs/architecture.md)** — File map, utility responsibilities, template/CSS/JS structure
- **[patterns.md](docs/patterns.md)** — Database access patterns, session caching, API conventions
- **[CLAUDE.md](CLAUDE.md)** — The agentic AI instruction file. Read this to understand the development pattern

---

*Built on Mars. Powered by shards. Guided by ARIA.*
