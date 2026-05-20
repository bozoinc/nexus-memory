"""
NEXUS — Memory Versioning & Branching System.

Git-like snapshot, branch, merge, and rollback for memory.
Uses copy-on-write snapshots with delta tracking.
"""

import json
import time
import os
import shutil
from pathlib import Path
from src.storage import NexusStorage, _now_ms


class MemoryVersioning:
    """Git-like versioning for NEXUS memory."""
    
    def __init__(self, db_path: str = None, snapshots_dir: str = None):
        self.db = NexusStorage(db_path)
        self.snapshots_dir = snapshots_dir or str(Path(self.db.db_path).parent / "snapshots")
        os.makedirs(self.snapshots_dir, exist_ok=True)
    
    def snapshot(self, name: str = None) -> dict:
        """Create a named snapshot of current memory state."""
        name = name or f"snapshot-{_now_ms()}"
        snapshot_path = os.path.join(self.snapshots_dir, f"{name}.db")
        
        # Copy the database file
        shutil.copy2(self.db.db_path, snapshot_path)
        
        # Record metadata
        stats = self.db.stats()
        meta = {
            'name': name,
            'created_at': _now_ms(),
            'stats': stats,
            'path': snapshot_path
        }
        meta_path = os.path.join(self.snapshots_dir, f"{name}.json")
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2, default=str)
        
        return meta
    
    def list_snapshots(self) -> list:
        """List all snapshots."""
        snapshots = []
        for meta_file in sorted(Path(self.snapshots_dir).glob("*.json")):
            with open(meta_file) as f:
                snapshots.append(json.load(f))
        return snapshots
    
    def rollback(self, name: str) -> bool:
        """Restore memory to a previous snapshot."""
        snapshot_path = os.path.join(self.snapshots_dir, f"{name}.db")
        if not os.path.exists(snapshot_path):
            return False
        
        # Close current connection
        self.db.close()
        
        # Restore from snapshot
        shutil.copy2(snapshot_path, self.db.db_path)
        
        # Reopen
        self.db = NexusStorage(self.db.db_path)
        return True
    
    def diff(self, snapshot_a: str, snapshot_b: str = None) -> dict:
        """Compare two memory states."""
        # Load snapshot A
        path_a = os.path.join(self.snapshots_dir, f"{snapshot_a}.db")
        if not os.path.exists(path_a):
            return {'error': f'Snapshot {snapshot_a} not found'}
        
        db_a = NexusStorage(path_a)
        mems_a = {r['id']: dict(r) for r in db_a.conn.execute("SELECT * from memories").fetchall()}
        db_a.close()
        
        if snapshot_b:
            path_b = os.path.join(self.snapshots_dir, f"{snapshot_b}.db")
            if not os.path.exists(path_b):
                return {'error': f'Snapshot {snapshot_b} not found'}
            db_b = NexusStorage(path_b)
            mems_b = {r['id']: dict(r) for r in db_b.conn.execute("SELECT * from memories").fetchall()}
            db_b.close()
        else:
            mems_b = {r['id']: dict(r) for r in self.db.conn.execute("SELECT * from memories").fetchall()}
        
        added = []
        removed = []
        changed = []
        
        for mid, mem in mems_b.items():
            if mid not in mems_a:
                added.append({'id': mid, 'content': mem['content'][:100]})
            elif mems_a[mid]['content'] != mem['content']:
                changed.append({
                    'id': mid,
                    'before': mems_a[mid]['content'][:100],
                    'after': mem['content'][:100]
                })
        
        for mid in mems_a:
            if mid not in mems_b:
                removed.append({'id': mid, 'content': mems_a[mid]['content'][:100]})
        
        return {
            'snapshot_a': snapshot_a,
            'snapshot_b': snapshot_b or 'current',
            'added': added,
            'removed': removed,
            'changed': changed,
            'summary': {
                'total_a': len(mems_a),
                'total_b': len(mems_b),
                'added': len(added),
                'removed': len(removed),
                'changed': len(changed)
            }
        }
    
    def branch(self, branch_name: str, from_snapshot: str = None) -> dict:
        """Create a new branch (isolated memory space)."""
        if from_snapshot:
            # Restore from snapshot first
            self.rollback(from_snapshot)
        
        # Set all memories to the new branch
        self.db.conn.execute("UPDATE memories SET branch_id = ?", (branch_name,))
        self.db.conn.commit()
        
        return {
            'branch': branch_name,
            'from_snapshot': from_snapshot,
            'memory_count': self.db.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE branch_id = ?", (branch_name,)
            ).fetchone()[0]
        }
    
    def merge(self, branch_name: str, strategy: str = 'keep_both') -> dict:
        """Merge a branch back into main."""
        branch_memories = self.db.conn.execute(
            "SELECT * FROM memories WHERE branch_id = ?", (branch_name,)
        ).fetchall()
        
        merged = 0
        conflicts = 0
        
        for row in branch_memories:
            mem = dict(row)
            # Check for conflicts with main branch
            existing = self.db.conn.execute(
                "SELECT * FROM memories WHERE branch_id = 'main' AND semantic_hash = ?",
                (mem.get('semantic_hash', ''),)
            ).fetchone()
            
            if existing and strategy == 'keep_both':
                # Keep both: update branch_id to main
                self.db.conn.execute(
                    "UPDATE memories SET branch_id = 'main' WHERE id = ?",
                    (mem['id'],)
                )
                merged += 1
            elif existing and strategy == 'overwrite':
                self.db.conn.execute(
                    "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                    (mem['content'], _now_ms(), existing['id'])
                )
                merged += 1
            elif not existing:
                self.db.conn.execute(
                    "UPDATE memories SET branch_id = 'main' WHERE id = ?",
                    (mem['id'],)
                )
                merged += 1
            else:
                conflicts += 1
        
        self.db.conn.commit()
        return {'merged': merged, 'conflicts': conflicts, 'strategy': strategy}
    
    def list_branches(self) -> list:
        """List all branches."""
        rows = self.db.conn.execute(
            "SELECT branch_id, COUNT(*) as cnt FROM memories GROUP BY branch_id"
        ).fetchall()
        return [{'name': r[0], 'memory_count': r[1]} for r in rows]
