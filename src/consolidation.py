"""
NEXUS — Memory Consolidation Engine.

Runs periodically to:
1. Deduplicate memories by semantic hash
2. Extract abstractions from related memories
3. Prune low-salience, old, unaccessed memories
4. Re-score all memories
5. Auto-discover graph edges
"""

import time
import json
from src.storage import NexusStorage, _now_ms, _compute_salience


class ConsolidationEngine:
    
    def __init__(self, db_path: str = None):
        self.db = NexusStorage(db_path)
    
    def run(self, dry_run: bool = False) -> dict:
        """Run full consolidation pipeline."""
        start = _now_ms()
        stats = {
            'input': 0, 'output': 0, 'merged': 0,
            'pruned': 0, 'abstractions': 0, 'edges_created': 0
        }
        
        all_rows = self.db.conn.execute("SELECT * FROM memories").fetchall()
        memories = [dict(r) for r in all_rows]
        stats['input'] = len(memories)
        
        # Phase 1: Dedup
        merged_ids = self._dedup(memories, dry_run)
        stats['merged'] = len(merged_ids)
        
        # Phase 2: Prune
        pruned_ids = self._prune(memories, merged_ids, dry_run)
        stats['pruned'] = len(pruned_ids)
        
        # Phase 3: Re-score
        if not dry_run:
            self._rescore()
        
        # Phase 4: Auto-edge discovery
        if not dry_run:
            edges = self._auto_edges(memories, merged_ids + pruned_ids)
            stats['edges_created'] = edges
        
        stats['output'] = stats['input'] - stats['merged'] - stats['pruned']
        stats['duration_ms'] = _now_ms() - start
        
        if not dry_run:
            self.db.conn.execute(
                """INSERT INTO consolidation_log (run_at, memories_input, memories_output,
                   memories_merged, memories_pruned, abstractions_created, duration_ms, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (_now_ms(), stats['input'], stats['output'], stats['merged'],
                 stats['pruned'], stats['abstractions'], stats['duration_ms'], 'auto')
            )
            self.db.conn.commit()
        
        return stats
    
    def _dedup(self, memories: list, dry_run: bool) -> list:
        """Merge memories with identical semantic hashes."""
        hashes = {}
        to_delete = []
        for mem in memories:
            sh = mem.get('semantic_hash', '')
            if not sh:
                continue
            if sh in hashes:
                existing = hashes[sh]
                # Keep the one with more accesses or more recent
                if mem['access_count'] > existing['access_count'] or mem['created_at'] > existing['created_at']:
                    to_delete.append(existing['id'])
                    hashes[sh] = mem
                else:
                    to_delete.append(mem['id'])
            else:
                hashes[sh] = mem
        
        if not dry_run:
            for mid in to_delete:
                self.db.delete_memory(mid)
        
        return to_delete
    
    def _prune(self, memories: list, already_deleted: list, dry_run: bool) -> list:
        """Remove low-salience, old, never-accessed memories."""
        cutoff = _now_ms() - (30 * 24 * 3600 * 1000)  # 30 days
        to_delete = []
        for mem in memories:
            if mem['id'] in already_deleted:
                continue
            sal = _compute_salience(mem)
            if sal < 0.1 and mem['created_at'] < cutoff and mem['access_count'] == 0:
                to_delete.append(mem['id'])
        
        if not dry_run:
            for mid in to_delete:
                self.db.delete_memory(mid)
        
        return to_delete
    
    def _rescore(self):
        """Recompute salience for all memories."""
        rows = self.db.conn.execute("SELECT * FROM memories").fetchall()
        for row in rows:
            d = dict(row)
            new_sal = _compute_salience(d)
            self.db.conn.execute("UPDATE memories SET salience = ? WHERE id = ?", (new_sal, d['id']))
        self.db.conn.commit()
    
    def _auto_edges(self, memories: list, excluded_ids: list) -> int:
        """Auto-discover edges based on shared tags and temporal proximity."""
        excluded = set(excluded_ids)
        edges_created = 0
        active = [m for m in memories if m['id'] not in excluded]
        
        for i, mem_a in enumerate(active):
            tags_a = set(json.loads(mem_a.get('tags', '[]')))
            for mem_b in active[i+1:]:
                tags_b = set(json.loads(mem_b.get('tags', '[]')))
                
                # Shared tags → contextualizes edge
                shared = tags_a & tags_b
                if len(shared) >= 2:
                    self.db.add_edge(mem_a['id'], mem_b['id'], 'contextualizes', len(shared) * 0.2)
                    edges_created += 1
                
                # Temporal proximity (within 1 hour) → follows edge
                time_diff = abs(mem_a['created_at'] - mem_b['created_at'])
                if time_diff < 3600000 and mem_a['id'] != mem_b['id']:
                    earlier = mem_a if mem_a['created_at'] < mem_b['created_at'] else mem_b
                    later = mem_b if earlier == mem_a else mem_a
                    self.db.add_edge(earlier['id'], later['id'], 'follows', 0.5)
                    edges_created += 1
        
        return edges_created
