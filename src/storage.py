"""
NEXUS — Neural Experience Unified Storage
Storage engine: SQLite + FTS5 + Episodic-Temporal Graph
"""

import sqlite3
import json
import time
import os
import hashlib
import uuid
import math
import re
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = os.environ.get("NEXUS_DB", str(Path.home() / ".nexus" / "memory.db"))

# --- Schema ---

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    semantic_hash TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    source_agent TEXT NOT NULL DEFAULT 'unknown',
    tags TEXT DEFAULT '[]',
    salience REAL DEFAULT 1.0,
    emotional_weight REAL DEFAULT 0.5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    access_count INTEGER DEFAULT 0,
    last_accessed INTEGER DEFAULT 0,
    consolidated INTEGER DEFAULT 0,
    branch_id TEXT DEFAULT 'main'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, tags, category,
    content='memories',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tags, category)
    VALUES (new.rowid, new.content, new.tags, new.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags, category)
    VALUES ('delete', old.rowid, old.content, old.tags, old.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags, category)
    VALUES ('delete', old.rowid, old.content, old.tags, old.category);
    INSERT INTO memories_fts(rowid, content, tags, category)
    VALUES (new.rowid, new.content, new.tags, new.category);
END;

CREATE TABLE IF NOT EXISTS memory_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consolidation_log (
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

CREATE TABLE IF NOT EXISTS access_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_of_day INTEGER,
    day_of_week INTEGER,
    project_context TEXT,
    memory_categories_accessed TEXT,
    access_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    permissions TEXT DEFAULT 'read,write',
    last_seen INTEGER,
    context_preferences TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_temporal ON memories(created_at, category);
CREATE INDEX IF NOT EXISTS idx_memories_salience ON memories(salience DESC);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(source_agent);
CREATE INDEX IF NOT EXISTS idx_memories_branch ON memories(branch_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON memory_edges(relation_type);
CREATE INDEX IF NOT EXISTS idx_patterns_temporal ON access_patterns(hour_of_day, day_of_week);
CREATE INDEX IF NOT EXISTS idx_patterns_project ON access_patterns(project_context);
"""

# --- Helpers ---

def _now_ms() -> int:
    return int(time.time() * 1000)

def _uuid7() -> str:
    """Time-sortable UUID (simplified v7)."""
    ts = int(time.time() * 1000)
    hex_ts = format(ts, '012x')
    rand_part = uuid.uuid4().hex[:12]
    # Format: 8-4-4-12 (total 32 hex chars, no dashes in standard positions)
    return f"{hex_ts[:8]}-{hex_ts[8:12]}-7{hex_ts[12:]}-{rand_part[:4]}-{rand_part[4:]}"

def _semantic_hash(content: str) -> str:
    """Simple TF-IDF-like semantic fingerprint (upgradeable to embeddings later)."""
    words = re.findall(r'\b[a-z]{3,}\b', content.lower())
    stopwords = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'were', 'they', 'their', 'what', 'when', 'where', 'which', 'this', 'that', 'with', 'from', 'will', 'would', 'there', 'these', 'than', 'then', 'them', 'into', 'some', 'could', 'other', 'about', 'more', 'very', 'just', 'also', 'only', 'such', 'like', 'does', 'each', 'make', 'over', 'most', 'made', 'after', 'before', 'between', 'through', 'being', 'under', 'should', 'because', 'while', 'during', 'without', 'again', 'further', 'once', 'here', 'how', 'too', 'very', 'what', 'which', 'who', 'whom'}
    keywords = [w for w in words if w not in stopwords]
    freq = {}
    for w in keywords:
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: -x[1])[:8]
    return hashlib.md5(' '.join(f"{k}:{v}" for k, v in top).encode()).hexdigest()[:16]

def _compute_salience(row: dict, current_project: str = None) -> float:
    """Compute dynamic salience score."""
    now = _now_ms()
    age_hours = max((now - row['created_at']) / 3600000, 0.001)
    
    # Recency: exponential decay (half-life 72 hours)
    recency_score = math.exp(-0.693 * age_hours / 72)
    
    # Access frequency: logarithmic
    access_score = math.log1p(row.get('access_count', 0)) / 5.0
    access_score = min(access_score, 1.0)
    
    # Emotional weight: stored directly
    emotional_weight = row.get('emotional_weight', 0.5)
    
    # Context boost: match current project
    context_boost = 0.0
    if current_project:
        tags_raw = row.get('tags', '[]')
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = []
        else:
            tags = tags_raw or []
        content = str(row.get('content', '')).lower()
        if current_project.lower() in content or current_project.lower() in [str(t).lower() for t in tags]:
            context_boost = 0.3
    
    # Contradiction penalty
    contradiction_penalty = 0.0  # Set by graph traversal
    
    salience = (recency_score * 0.25) + (access_score * 0.20) + (emotional_weight * 0.25) + (context_boost * 0.20) - (contradiction_penalty * 0.10)
    return max(0.0, min(1.0, salience))


class NexusStorage:
    """Core storage engine for NEXUS memory system."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
    
    def close(self):
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    # --- CRUD ---
    
    def add_memory(self, content: str, category: str = 'general', source_agent: str = 'hermes',
                   tags: list = None, emotional_weight: float = 0.5, branch_id: str = 'main') -> dict:
        """Add a new memory node."""
        now = _now_ms()
        mem_id = _uuid7()
        semantic_hash = _semantic_hash(content)
        tags_json = json.dumps(tags or [])
        
        self.conn.execute(
            """INSERT INTO memories (id, content, semantic_hash, category, source_agent, tags,
               salience, emotional_weight, created_at, updated_at, branch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem_id, content, semantic_hash, category, source_agent, tags_json,
             1.0, emotional_weight, now, now, branch_id)
        )
        self.conn.commit()
        return self.get_memory(mem_id)
    
    def get_memory(self, mem_id: str) -> dict:
        """Get a memory by ID and increment access count."""
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (_now_ms(), mem_id)
            )
            self.conn.commit()
            return dict(row)
        return None
    
    def update_memory(self, mem_id: str, **kwargs) -> dict:
        """Update memory fields."""
        allowed = {'content', 'category', 'tags', 'emotional_weight', 'branch_id'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_memory(mem_id)
        
        if 'tags' in updates:
            updates['tags'] = json.dumps(updates['tags'])
        if 'content' in updates:
            updates['semantic_hash'] = _semantic_hash(updates['content'])
        
        updates['updated_at'] = _now_ms()
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [mem_id]
        
        self.conn.execute(f"UPDATE memories SET {set_clause} WHERE id = ?", values)
        self.conn.commit()
        return self.get_memory(mem_id)
    
    def delete_memory(self, mem_id: str) -> bool:
        """Delete a memory and its edges."""
        cursor = self.conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    # --- Search ---
    
    def search(self, query: str = None, category: str = None, source_agent: str = None,
               since: int = None, until: int = None, limit: int = 20,
               mode: str = 'keyword', current_project: str = None,
               match_mode: str = 'AND') -> list:
        """Search memories by keyword, temporal range, or causal chain.
        
        match_mode: 'AND' requires all terms to match (precise), 'OR' matches any term (broad).
        """
        
        if mode == 'temporal' and not query:
            # Time-based search
            sql = "SELECT * FROM memories WHERE 1=1"
            params = []
            if since:
                sql += " AND created_at >= ?"
                params.append(since)
            if until:
                sql += " AND created_at <= ?"
                params.append(until)
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        
        elif mode == 'causal' and query:
            # Find the memory, then traverse its causal chain
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE id IN (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?) LIMIT 1",
                (query,)
            ).fetchall()
            if not rows:
                return []
            return self.get_graph_neighborhood(dict(rows[0])['id'], relation_types=['causes', 'follows', 'supports'])
        
        else:
            # Keyword search via FTS5
            if query:
                # Sanitize FTS5 query: replace dots and special chars
                safe_query = query.replace('.', ' ').replace('-', ' ').strip()
                # Split into terms and join with AND or OR
                terms = [t for t in safe_query.split() if len(t) >= 2]
                if not terms:
                    terms = [safe_query]
                joiner = ' AND ' if match_mode == 'AND' else ' OR '
                fts_query = joiner.join(terms)
                try:
                    rows = self.conn.execute(
                        """SELECT m.* FROM memories m
                           JOIN memories_fts f ON m.rowid = f.rowid
                           WHERE memories_fts MATCH ?
                           ORDER BY rank LIMIT ?""",
                        (fts_query, limit)
                    ).fetchall()
                except sqlite3.OperationalError:
                    # Fallback: LIKE search
                    like_q = f"%{query}%"
                    rows = self.conn.execute(
                        "SELECT * FROM memories WHERE content LIKE ? OR tags LIKE ? ORDER BY salience DESC LIMIT ?",
                        (like_q, like_q, limit)
                    ).fetchall()
            else:
                sql = "SELECT * FROM memories WHERE 1=1"
                params = []
                if category:
                    sql += " AND category = ?"
                    params.append(category)
                if source_agent:
                    sql += " AND source_agent = ?"
                    params.append(source_agent)
                sql += " ORDER BY salience DESC LIMIT ?"
                params.append(limit)
                rows = self.conn.execute(sql, params).fetchall()
            
            results = [dict(r) for r in rows]
            # Re-score with current project context
            if current_project:
                for r in results:
                    r['salience'] = _compute_salience(r, current_project)
                results.sort(key=lambda x: x['salience'], reverse=True)
            return results
    
    # --- Graph ---
    
    def add_edge(self, source_id: str, target_id: str, relation_type: str,
                 strength: float = 1.0) -> int:
        """Add a graph edge between two memories."""
        now = _now_ms()
        cursor = self.conn.execute(
            """INSERT INTO memory_edges (source_id, target_id, relation_type, strength, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, target_id, relation_type, strength, now)
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def get_graph_neighborhood(self, mem_id: str, depth: int = 2,
                                relation_types: list = None) -> list:
        """Get connected memories up to N hops."""
        visited = set()
        frontier = {mem_id}
        results = []
        
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ','.join('?' * len(frontier))
            sql = f"""SELECT DISTINCT m.* FROM memories m
                      JOIN memory_edges e ON (m.id = e.source_id OR m.id = e.target_id)
                      WHERE (e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders}))
                      AND m.id != ?"""
            params = list(frontier) + list(frontier) + [mem_id]
            
            if relation_types:
                rt_placeholders = ','.join('?' * len(relation_types))
                sql += f" AND e.relation_type IN ({rt_placeholders})"
                params.extend(relation_types)
            
            rows = self.conn.execute(sql, params).fetchall()
            new_frontier = set()
            for row in rows:
                d = dict(row)
                if d['id'] not in visited:
                    visited.add(d['id'])
                    results.append(d)
                    new_frontier.add(d['id'])
            frontier = new_frontier - visited
        
        return results
    
    # --- Consolidation ---
    
    def consolidate(self, dry_run: bool = False) -> dict:
        """Run consolidation: dedup, abstract, prune, re-score."""
        start = _now_ms()
        stats = {'input': 0, 'output': 0, 'merged': 0, 'pruned': 0, 'abstractions': 0}
        
        all_rows = self.conn.execute("SELECT * FROM memories").fetchall()
        stats['input'] = len(all_rows)
        
        # Dedup by semantic_hash
        hashes = {}
        to_delete = []
        for row in all_rows:
            d = dict(row)
            sh = d.get('semantic_hash', '')
            if sh in hashes:
                # Merge: keep the one with higher access count
                existing = hashes[sh]
                if d['access_count'] > existing['access_count']:
                    to_delete.append(existing['id'])
                    hashes[sh] = d
                else:
                    to_delete.append(d['id'])
                stats['merged'] += 1
            else:
                hashes[sh] = d
        
        if not dry_run:
            for mid in to_delete:
                self.delete_memory(mid)
        
        # Prune: salience < 0.1 and older than 30 days and never accessed
        cutoff = _now_ms() - (30 * 24 * 3600 * 1000)
        for row in all_rows:
            d = dict(row)
            if d['id'] in to_delete:
                continue
            salience = _compute_salience(d)
            if salience < 0.1 and d['created_at'] < cutoff and d['access_count'] == 0:
                if not dry_run:
                    self.delete_memory(d['id'])
                stats['pruned'] += 1
        
        # Re-score all remaining
        if not dry_run:
            remaining = self.conn.execute("SELECT * FROM memories").fetchall()
            for row in remaining:
                d = dict(row)
                new_salience = _compute_salience(d)
                self.conn.execute("UPDATE memories SET salience = ? WHERE id = ?", (new_salience, d['id']))
            self.conn.commit()
        
        stats['output'] = stats['input'] - stats['merged'] - stats['pruned']
        duration = _now_ms() - start
        
        if not dry_run:
            self.conn.execute(
                """INSERT INTO consolidation_log (run_at, memories_input, memories_output,
                   memories_merged, memories_pruned, abstractions_created, duration_ms, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (_now_ms(), stats['input'], stats['output'], stats['merged'],
                 stats['pruned'], stats['abstractions'], duration, 'auto')
            )
            self.conn.commit()
        
        stats['duration_ms'] = duration
        return stats
    
    # --- Import ---
    
    def import_from_markdown(self, md_path: str, source_agent: str = 'hermes') -> int:
        """Import memories from a markdown file."""
        path = Path(md_path)
        if not path.exists():
            return 0
        
        content = path.read_text()
        category = path.stem  # user, projects, lessons, environment, etc.
        
        # Split by ## headings
        sections = re.split(r'\n## ', content)
        count = 0
        
        for section in sections:
            lines = section.strip().split('\n')
            if not lines:
                continue
            
            # First line is the section title
            title = lines[0].strip().lstrip('#').strip()
            body = '\n'.join(lines[1:]).strip()
            
            if not body:
                continue
            
            full_content = f"{title}: {body}" if body else title
            tags = [category, title.lower().replace(' ', '-')]
            
            self.add_memory(
                content=full_content[:2000],  # Cap length
                category=category,
                source_agent=source_agent,
                tags=tags,
                emotional_weight=0.7 if 'lesson' in category or 'preference' in category else 0.5
            )
            count += 1
        
        return count
    
    def import_hermes_memory(self, memory_dir: str = None) -> dict:
        """Import all Hermes markdown memory files."""
        memory_dir = memory_dir or str(Path.home() / '.hermes' / 'memory')
        results = {}
        for md_file in Path(memory_dir).glob('*.md'):
            count = self.import_from_markdown(str(md_file))
            results[md_file.stem] = count
        return results
    
    # --- Stats ---
    
    def stats(self) -> dict:
        """Get memory system statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        by_category = {}
        for row in self.conn.execute("SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"):
            by_category[row[0]] = row[1]
        by_agent = {}
        for row in self.conn.execute("SELECT source_agent, COUNT(*) as cnt FROM memories GROUP BY source_agent"):
            by_agent[row[0]] = row[1]
        edges = self.conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        avg_salience = self.conn.execute("SELECT AVG(salience) FROM memories").fetchone()[0]
        
        return {
            'total_memories': total,
            'total_edges': edges,
            'by_category': by_category,
            'by_agent': by_agent,
            'avg_salience': round(avg_salience or 0, 3),
            'db_path': self.db_path,
            'db_size_mb': round(os.path.getsize(self.db_path) / 1048576, 2)
        }
