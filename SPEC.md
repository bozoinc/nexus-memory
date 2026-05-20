# NEXUS — Neural Experience Unified Storage
## Next-Generation Memory System for Hermes Agent

### Version: 0.1.0 (Design Spec)
### Date: May 20, 2026
### Author: OWL for Tansi

---

## 1. VISION

Current memory systems (Mem0, Zep, Letta, Hermes markdown, OpenClaw markdown) all treat memory as a **flat retrieval problem**: store facts → search by keyword/embedding → inject into prompt.

NEXUS treats memory as a **living cognitive architecture** — memory that reasons about itself, restructures itself, grows organically, and predicts what will be needed before it's asked for.

**Design principle:** Build for the supercomputer era. Every component is designed to scale from a single WSL instance to a distributed cluster. The data model is the same whether running on a laptop or a future supercomputer — only the compute layer changes.

---

## 2. CORE ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                    NEXUS MEMORY SYSTEM                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  NL Memory   │  │  Predictive  │  │   Memory       │  │
│  │  Interface   │  │  Preloader   │  │   Consolidator │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                │                   │            │
│  ┌──────▼────────────────▼───────────────────▼────────┐  │
│  │              Episodic-Temporal Graph                │  │
│  │         (SQLite + Graph Relations + FTS5)           │  │
│  └──────────────────────┬─────────────────────────────┘  │
│                         │                                 │
│  ┌──────────────────────▼─────────────────────────────┐  │
│  │           Semantic Compression Engine               │  │
│  │     (Pluggable: TF-IDF → Embeddings → Neural)      │  │
│  └──────────────────────┬─────────────────────────────┘  │
│                         │                                 │
│  ┌──────────────────────▼─────────────────────────────┐  │
│  │            Cross-Agent Memory Mesh                  │  │
│  │    (Hermes, OpenClaw, Claude Code, Cursor, etc.)   │  │
│  └────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │          Memory Versioning & Branching              │  │
│  │            (Git-like snapshot system)               │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 3. DATA MODEL

### 3.1 Memory Node (Core Unit)

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,           -- UUID v7 (time-sortable)
    content TEXT NOT NULL,         -- Raw memory content
    semantic_hash TEXT,            -- Compressed semantic representation
    category TEXT NOT NULL,        -- episodic | semantic | procedural | preference | correction
    source_agent TEXT NOT NULL,    -- hermes | openclaw | claude-code | cursor | user
    tags TEXT DEFAULT '[]',        -- JSON array of tags
    salience REAL DEFAULT 1.0,     -- Dynamic relevance score (0.0 - 1.0)
    emotional_weight REAL DEFAULT 0.5, -- User corrections = higher weight
    created_at INTEGER NOT NULL,   -- Unix timestamp (ms)
    updated_at INTEGER NOT NULL,   -- Unix timestamp (ms)
    access_count INTEGER DEFAULT 0,
    last_accessed INTEGER DEFAULT 0,
    consolidated INTEGER DEFAULT 0, -- Has been through consolidation
    branch_id TEXT DEFAULT 'main'  -- Git-like branching
);

-- Full-text search
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, tags, category,
    content='memories',
    content_rowid='rowid'
);

-- Temporal index for time-based queries
CREATE INDEX idx_memories_temporal ON memories(created_at, category);
CREATE INDEX idx_memories_salience ON memories(salience DESC);
CREATE INDEX idx_memories_agent ON memories(source_agent);
CREATE INDEX idx_memories_branch ON memories(branch_id);
```

### 3.2 Episodic-Temporal Graph

```sql
CREATE TABLE memory_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,       -- FK → memories.id
    target_id TEXT NOT NULL,       -- FK → memories.id
    relation_type TEXT NOT NULL,   -- causes | follows | contradicts | supports | contextualizes
    strength REAL DEFAULT 1.0,     -- Edge weight
    created_at INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id),
    FOREIGN KEY (target_id) REFERENCES memories(id)
);

CREATE INDEX idx_edges_source ON memory_edges(source_id);
CREATE INDEX idx_edges_target ON memory_edges(target_id);
CREATE INDEX idx_edges_type ON memory_edges(relation_type);
```

### 3.3 Consolidation Log

```sql
CREATE TABLE consolidation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at INTEGER NOT NULL,
    memories_input INTEGER,
    memories_output INTEGER,
    memories_merged INTEGER,
    memories_pruned INTEGER,
    abstractions_created INTEGER,
    duration_ms INTEGER,
    notes TEXT
);
```

### 3.4 Predictive Patterns

```sql
CREATE TABLE access_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_of_day INTEGER,           -- 0-23
    day_of_week INTEGER,           -- 0-6
    project_context TEXT,          -- Current project/category
    memory_categories_accessed TEXT, -- JSON array
    access_count INTEGER DEFAULT 1
);

CREATE INDEX idx_patterns_temporal ON access_patterns(hour_of_day, day_of_week);
CREATE INDEX idx_patterns_project ON access_patterns(project_context);
```

### 3.5 Agent Registry

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,           -- Agent identifier
    name TEXT NOT NULL,
    type TEXT NOT NULL,            -- hermes | openclaw | claude-code | cursor | custom
    permissions TEXT DEFAULT 'read,write', -- read | write | admin
    last_seen INTEGER,
    context_preferences TEXT DEFAULT '{}' -- JSON: preferred categories, salience threshold
);
```

---

## 4. KEY INNOVATIONS

### 4.1 Episodic-Temporal Graph

Unlike flat memory stores, NEXUS connects memories in a graph:

- **Temporal edges:** "Memory B happened after Memory A" (automatic)
- **Causal edges:** "SD 1.5 float16 causes NaN black images" (learned)
- **Contextual edges:** "This memory is related to YouTube project" (auto-tagged)
- **Contradiction edges:** "User said X, then later said Y" (flagged for review)

Query: "Why did I stop using SD 1.5?" → traverses causal chain:
  `SD 1.5 float16 → NaN black images → switched to CPU float32 → Pillow animation engine`

### 4.2 Memory Consolidation Engine

Runs periodically (configurable, default: nightly via cron):

1. **Deduplication:** Semantic hash comparison → merge near-duplicates
2. **Abstraction:** Extract higher-level patterns from specific memories
   - "SD 1.5 broken on GTX 1650" + "Chatterbox breaks torch" + "edge-tts reliable"
   - → Abstract: "On this machine, stick to CPU-based tools and edge-tts"
3. **Pruning:** Low-salience + old + never-accessed → archive (not delete)
4. **Re-scoring:** Update salience based on access patterns and recency
5. **Edge creation:** Auto-discover new graph relationships

### 4.3 Contextual Salience Scoring

Dynamic score (0.0 - 1.0) based on:
- **Recency:** Newer memories score higher (decay curve)
- **Access frequency:** Frequently accessed = more relevant
- **Emotional weight:** User corrections score 2x, explicit "remember this" = 3x
- **Project context:** Memories related to current project get boosted
- **Contradiction penalty:** Contradicted memories score lower

Formula:
```
salience = (recency_score * 0.25) + (access_score * 0.20) + (emotional_weight * 0.25) + (context_boost * 0.20) + (contradiction_penalty * -0.10)
```

### 4.4 Predictive Preloading

Learns from access patterns:
- If Tansi works on YouTube videos every Monday 9AM → pre-load YouTube context Sunday night
- If Tansi always checks projects after boot → pre-load project summaries
- Time-of-day, day-of-week, and project context as features

Implementation: Lightweight pattern matching (no ML needed initially). Can be upgraded to a small neural net when compute allows.

### 4.5 Semantic Compression

Pluggable compression tiers:
- **Tier 1 (current):** TF-IDF keyword extraction → 50-char semantic hash
- **Tier 2 (near-future):** Local embedding model (e.g., all-MiniLM) → 384-dim vector
- **Tier 3 (supercomputer):** Neural compression → learned semantic representations

The data model stores both raw content AND compressed representation. As hardware improves, swap the compression engine without migrating data.

### 4.6 Memory Versioning & Branching

Git-like operations:
- `nexus snapshot` — Create named snapshot of current memory state
- `nexus branch <name>` — Create experimental branch
- `nexus merge <branch>` — Merge branch into main
- `nexus rollback <snapshot>` — Restore to previous state
- `nexus diff <a> <b>` — Compare two memory states

Implementation: Copy-on-write snapshots. Each snapshot stores delta from previous.

### 4.7 Cross-Agent Memory Mesh

All agents connect to the same NEXUS instance:
- **Shared layer:** Facts, preferences, project context (all agents read)
- **Agent-private layer:** Agent-specific working memory (only that agent reads)
- **Perspective filtering:** Each agent sees memories through its own context preferences

Protocol: HTTP API (REST) + file-based sync for offline agents.

### 4.8 Natural Language Memory Interface

Instead of CLI commands, talk to memory:

- "Remember that I always use edge-tts" → auto-categorized as preference
- "What was I working on last Tuesday?" → temporal search
- "Why did I stop using SD 1.5?" → causal chain traversal
- "Show me everything about the YouTube project" → graph traversal from project node
- "I was wrong about X, it's actually Y" → creates contradiction edge, re-scores

---

## 5. API DESIGN

### 5.1 HTTP API (for cross-agent access)

```
POST   /api/memory/add          -- Add memory
GET    /api/memory/search       -- Search (NL, keyword, temporal)
GET    /api/memory/graph/:id    -- Get graph neighborhood
POST   /api/memory/consolidate  -- Trigger consolidation
GET    /api/memory/predict      -- Get predicted context for current time
POST   /api/memory/snapshot     -- Create snapshot
POST   /api/memory/branch       -- Create branch
POST   /api/memory/merge        -- Merge branch
GET    /api/memory/diff         -- Compare states
GET    /api/health              -- Health check
```

### 5.2 CLI Interface

```bash
nexus add "Tansi prefers edge-tts over Chatterbox" --category preference --tags audio,tts
nexus search "why did I stop using SD 1.5?" --mode causal
nexus graph --project youtube --depth 3
nexus consolidate --dry-run
nexus snapshot --name "pre-consolidation"
nexus branch experiment
nexus merge experiment
nexus predict --context "Monday morning"
nexus stats
nexus export --format json --output backup.json
nexus import --file backup.json
```

---

## 6. INTEGRATION WITH HERMES

### 6.1 Hermes Skill

NEXUS replaces the current markdown-based memory system:
- On session start: NEXUS preloads relevant context based on time/project
- During session: Hermes reads/writes via HTTP API
- On session end: Hermes writes session summary to NEXUS
- Nightly: Consolidation cron runs automatically

### 6.2 Migration Path

1. Import existing `~/.hermes/memory/*.md` files into NEXUS
2. Categorize and tag during import
3. Build initial graph edges from co-occurrence
4. Run first consolidation pass
5. Hermes skill updated to use NEXUS API instead of markdown files

---

## 7. FUTURE-PROOFING FOR SUPERCOMPUTER ERA

Every component designed for horizontal scaling:

| Component | Laptop (Now) | Supercomputer (Future) |
|-----------|---------------|------------------------|
| Storage | SQLite | Distributed graph DB |
| Compression | TF-IDF | Neural semantic compression |
| Consolidation | Nightly cron | Real-time streaming |
| Preloading | Pattern matching | Predictive neural model |
| Graph | In-memory traversal | Distributed graph compute |
| API | Local HTTP | Distributed mesh protocol |

The data model (memories + edges + salience) stays the same. Only the compute layer upgrades.

---

## 8. IMPLEMENTATION PLAN

### Phase 1: Core Engine (Week 1-2)
- SQLite schema + CRUD operations
- FTS5 search
- Basic HTTP API
- CLI interface
- Import from existing Hermes markdown

### Phase 2: Intelligence Layer (Week 3-4)
- Salience scoring engine
- Consolidation engine (dedup, abstraction, pruning)
- Graph edge auto-discovery
- Semantic compression (TF-IDF tier)

### Phase 3: Advanced Features (Week 5-6)
- Predictive preloading
- Memory versioning/branching
- NL memory interface
- Cross-agent sync

### Phase 4: Integration (Week 7-8)
- Hermes skill replacement
- OpenClaw adapter
- Claude Code MCP server
- Dashboard panel
- Migration and testing
