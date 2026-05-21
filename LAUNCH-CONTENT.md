# NEXUS Launch Content

GitHub: https://github.com/bozoinc/nexus-memory

---

## 1. Hacker News — Show HN

**Title:**
Show HN: NEXUS — Local-first, cross-agent memory for AI agents (free, open source)

**Body:**

I built NEXUS because I was tired of every AI agent having amnesia — and the only fixes were cloud services charging $249/mo.

NEXUS is a local-first memory system that works across all your AI agents. Hermes, Claude Code, Cursor, OpenClaw — they all share one memory store. It runs on your machine, costs $0, and is MIT licensed.

The problem: every agent has its own siloed memory. Claude Code doesn't know what Cursor learned. Your Hermes agent can't recall what OpenClaw discussed yesterday. You end up re-explaining context constantly, or you pay for a cloud service to centralize it.

NEXUS solves this with a SQLite backend (with FTS5 full-text search) that every agent connects to locally. No cloud. No API keys. No subscription.

Key features:

- **Cross-agent sync** — Hermes, Claude Code, Cursor, OpenClaw all read/write to the same memory store
- **10 MCP tools** — add_memory, search, ask, list, get, delete, stats, consolidate, export, predict. Works with any MCP client (Claude Code, Cursor, Windsurf, etc.)
- **Versioning** — every memory is versioned, so you can track how context evolves
- **Prediction** — NEXUS can predict which memories you'll need before you ask
- **Emotional weighting** — memories carry emotional context, so the system knows what matters most
- **Natural language interface** — just ask it questions about what it remembers
- **Consolidation** — automatic memory consolidation prevents bloat and keeps retrieval fast

The competitive landscape:

- **Mem0** — $249/mo, cloud-only, vendor lock-in
- **Hindsight** — cloud-first, requires their infrastructure
- **Zep** — cloud-only, enterprise pricing

NEXUS is the only system I'm aware of that combines local-first + cross-agent + versioning + prediction + emotional weighting + NL interface + consolidation + MCP server support + open source + zero cost. If I'm missing something, I genuinely want to know.

Install: `pip install nexus-local`, then run `nexus-mcp` to start the MCP server. Point your MCP client at it. Done.

Built by Tansi for Sturgeon Lake First Nation.

Repo: https://github.com/bozoinc/nexus-memory

---

## 2. Reddit — r/LocalLLaMA

**Title:**
NEXUS: Local-first, cross-agent memory for AI agents — no cloud, no subscription, MCP server included

**Body:**

If you're running local LLMs and using multiple AI agents (Claude Code, Cursor, Hermes, etc.), you've probably hit the memory problem: every agent is an island. None of them share context. You re-explain things constantly.

Existing solutions like Mem0, Hindsight, and Zep solve this by putting your memories in the cloud — and charging you $200+/mo for the privilege. That defeats the purpose of running local.

**NEXUS is different.** It runs entirely on your machine. SQLite backend with FTS5 search. No cloud. No API keys. No subscription. MIT licensed, free forever.

**What it does:**

- Gives all your AI agents a shared memory store. Hermes, Claude Code, Cursor, OpenClaw — they all read and write to the same local database.
- Ships an MCP server out of the box. Plug it into Claude Code, Cursor, Windsurf, or any MCP client and your agents instantly get persistent, shared memory.
- 10 MCP tools: add_memory, search, ask, list, get, delete, stats, consolidate, export, predict.
- Memory versioning, emotional weighting, natural language queries, and automatic consolidation.

**Why not just use Mem0?**

Mem0 is cloud-only and costs $249/mo at scale. Your memories leave your machine. NEXUS keeps everything local and costs nothing. If you care about privacy and you're already running local LLMs, this should be a no-brainer.

**Install:**

```
pip install nexus-local
nexus-mcp
```

That's it. The MCP server starts and your agents can connect to it. Full setup instructions in the repo.

**Tech stack:** Python, SQLite + FTS5, MCP protocol. MIT license.

Repo: https://github.com/bozoinc/nexus-memory

Happy to answer questions. Built this because I needed it and couldn't find anything that didn't require surrendering my data or my wallet.

---

## 3. Twitter/X Thread

**Tweet 1 (hook):**
Your AI agents can't share memory. I fixed that.

Introducing NEXUS — a local-first, cross-agent memory system that's free, open source, and runs on your machine.

Thread:

**Tweet 2 (problem):**
Right now every AI agent is an island. Claude Code doesn't know what Cursor learned. Your Hermes agent can't recall what OpenClaw discussed yesterday.

You either re-explain everything constantly, or you pay a cloud service to centralize it.

**Tweet 3 (solution):**
NEXUS gives all your agents one shared memory store. SQLite backend, FTS5 search, runs locally. No cloud. No API keys. No subscription.

MIT licensed. Free forever.

**Tweet 4 (features):**
What's in the box:
- Cross-agent sync (Hermes, Claude Code, Cursor, OpenClaw)
- 10 MCP tools (add, search, ask, predict, consolidate, etc.)
- Memory versioning + emotional weighting
- Natural language interface
- Automatic consolidation

**Tweet 5 (MCP):**
The MCP server is the killer feature. Run `nexus-mcp`, point Claude Code or Cursor at it, and your agents instantly get persistent shared memory.

Works with any MCP client. No vendor lock-in.

**Tweet 6 (competitive):**
Mem0 charges $249/mo and your data lives in their cloud. Hindsight and Zep are cloud-first.

NEXUS is the only system combining local-first + cross-agent + versioning + prediction + emotional weighting + MCP server + open source + zero cost.

**Tweet 7 (CTA):**
Install: `pip install nexus-local`
Repo: https://github.com/bozoinc/nexus-memory

Built by Tansi for Sturgeon Lake First Nation. Star it if you think AI memory should be free and local.

