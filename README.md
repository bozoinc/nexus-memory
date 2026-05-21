# NEXUS — Neural Experience Unified Storage

**Local-first, cross-agent AI memory system.** SQLite backend with FTS5 search, natural language interface, memory versioning, predictive preloading, emotional weighting, salience scoring, consolidation, and cross-agent sync.

## Why NEXUS?

Every AI agent memory system today treats memory as a flat retrieval problem: store facts → search → inject into prompt. NEXUS treats memory as a **living cognitive architecture** — memory that reasons about itself, restructures itself, grows organically, and predicts what will be needed before it's asked for.

**Key differentiators:**
- **Local-first** — No cloud. No API keys. No subscription. Your data stays on your machine.
- **Cross-agent** — Share memory across Hermes, OpenClaw, Claude Code, Cursor, and any MCP-compatible agent.
- **Versioning** — Git-like snapshots and branches for memory. Roll back, fork, merge.
- **Prediction** — Preloads memories you'll need before you ask.
- **Emotional weighting** — Memories carry emotional context, not just facts.
- **NL interface** — Ask questions in plain English. "What did we decide about the database?"
- **Consolidation** — Automatic memory consolidation (like human sleep cycles).
- **Open source** — MIT license. Free forever.

## Competitive Position

| Capability | NEXUS | Mem0 | Hindsight | Zep | Vektor | Letta |
|------------|-------|------|-----------|-----|--------|-------|
| Local-first | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Cross-agent | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Versioning | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Prediction | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Emotional weight | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| NL interface | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Python SDK | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| MCP server | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |

## Quick Start

### Install

```bash
pip install nexus-local
```

Or install from source:
```bash
git clone https://github.com/bozoinc/nexus-memory.git
cd nexus-memory
pip install -e .
```

Or with pipx (recommended for CLI tools):
```bash
pipx install nexus-local
```

### CLI Usage

After `pip install -e .`:

```bash
# Add a memory
nexus add "We decided to use PostgreSQL for the project" --category decision --tags database,backend

# Search memories
nexus search "database decision"

# Ask in natural language
nexus ask "What did we decide about the database?"

# List all memories
nexus list

# Get memory stats
nexus stats
```

Or run directly without installing:
```bash
python -m nexus add "..." --category decision
python -m nexus search "..."
```

### MCP Server (for Claude Code, Cursor, Windsurf, etc.)

Add to your MCP client config:

**Claude Code** (`~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "nexus": {
      "command": "nexus-mcp"
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "nexus": {
      "command": "nexus-mcp"
    }
  }
}
```

**Generic (any MCP client)**:
```json
{
  "mcpServers": {
    "nexus": {
      "command": "python",
      "args": ["-m", "nexus_mcp.server"],
      "env": {
        "NEXUS_DB": "~/.nexus/memory.db"
      }
    }
  }
}
```

Available MCP tools:
- `nexus_add_memory` — Store a new memory
- `nexus_search` — Search memories by keyword
- `nexus_ask` — Natural language question answering
- `nexus_list` — List recent memories
- `nexus_get` — Get a memory by ID
- `nexus_delete` — Delete a memory
- `nexus_stats` — Memory statistics
- `nexus_consolidate` — Run memory consolidation
- `nexus_export` — Export all memories (JSON or Markdown)
- `nexus_predict` — Predict context needed

### HTTP API

```bash
# Start the API server
python -m nexus_mcp.server  # or use the CLI
python -c "from src.api import app; import uvicorn; uvicorn.run(app, host='127.0.0.1', port=1818)"

# Add a memory
curl -X POST http://localhost:1818/api/memory/add \
  -H "Content-Type: application/json" \
  -d '{"content": "We decided to use PostgreSQL", "category": "decision"}'

# Search
curl "http://localhost:1818/api/memory/search?q=database"
```

### Python API

```python
from src.storage import NexusStorage

db = NexusStorage()

# Add memory
mem = db.add_memory(
    content="We decided to use PostgreSQL for the project",
    category="decision",
    tags=["database", "backend"],
    emotional_weight=0.7
)

# Search
results = db.search("database decision")

# Get stats
stats = db.stats()
print(f"Total memories: {stats['total_memories']}")

db.close()
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│              NEXUS MEMORY SYSTEM                 │
├─────────────────────────────────────────────────┤
│                                                   │
│  ┌──────────┐ ┌───────────┐ ┌────────────────┐  │
│  │ NL Memory│ │ Predictive│ │   Memory       │  │
│  │ Interface│ │ Preloader │ │   Consolidator │  │
│  └────┬─────┘ └─────┬─────┘ └───────┬────────┘  │
│       │              │               │            │
│  ┌────▼──────────────▼───────────────▼────────┐  │
│  │        Episodic-Temporal Graph             │  │
│  │      (SQLite + Graph Relations + FTS5)     │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                           │
│  ┌────────────────────▼───────────────────────┐  │
│  │        Semantic Compression Engine          │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                           │
│  ┌────────────────────▼───────────────────────┐  │
│  │        Cross-Agent Memory Mesh              │  │
│  │  (Hermes, OpenClaw, Claude Code, Cursor)   │  │
│  └────────────────────────────────────────────┘  │
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │       Memory Versioning & Branching         │  │
│  └────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Project Structure

```
nexus/
├── nexus                    # CLI entry point
├── src/
│   ├── storage.py           # SQLite + FTS5 storage engine
│   ├── api.py               # HTTP API server (FastAPI)
│   ├── nl_interface.py      # Natural language interface
│   ├── predictor.py         # Predictive preloading
│   ├── consolidation.py     # Memory consolidation engine
│   ├── cross_agent_sync.py  # Cross-agent sync
│   ├── versioning.py        # Git-like versioning
│   ├── salience.py          # Salience scoring
│   └── nexus_hermes.py      # Hermes integration
├── tests/
│   └── test_storage.py      # 22 tests, all passing
├── requirements.txt
├── LICENSE
└── README.md
```

## Cross-Agent Sync

NEXUS can sync memory across multiple AI agents:

- **Hermes Agent** — Native integration via skill
- **OpenClaw** — Bidirectional sync with workspace .md files
- **Claude Code** — CLAUDE.md context generation
- **Cursor IDE** — .cursorrules context generation

```bash
# Register an agent
python -m nexus agents register claude-code --categories decisions,preferences,context

# Sync all agents
python -m nexus sync

# Generate context for a specific agent
python -m nexus context claude-code
```

## Roadmap

- [x] Core storage engine (SQLite + FTS5)
- [x] Natural language interface
- [x] Predictive preloading
- [x] Memory consolidation
- [x] Cross-agent sync
- [x] Versioning and branching
- [x] Salience scoring
- [x] Emotional weighting
- [x] HTTP API server
- [x] CLI interface
- [ ] MCP server (in progress)
- [ ] LongMemEval benchmarks
- [ ] TypeScript SDK
- [ ] Managed hosting option

## Benchmarks

*Coming soon. LongMemEval evaluation in progress.*

## License

MIT License. See [LICENSE](LICENSE) for details.

## Credits

Built by OWL for Tansi. Designed for Sturgeon Lake First Nation and the Indigenous tech community. Open source for everyone.
