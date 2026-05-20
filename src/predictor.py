"""
NEXUS — Predictive Preloading System.

Learns from access patterns to predict what context will be needed
based on time of day, day of week, and project context.
"""

import json
import time
import math
from datetime import datetime
from src.storage import NexusStorage, _now_ms


class PredictivePreloader:
    """Predicts what memory context will be needed."""
    
    def __init__(self, db_path: str = None):
        self.db = NexusStorage(db_path)
    
    def record_access(self, memory_ids: list, project_context: str = None):
        """Record which memories were accessed and when."""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        
        # Get categories of accessed memories
        categories = []
        for mid in memory_ids:
            row = self.db.conn.execute(
                "SELECT category FROM memories WHERE id = ?", (mid,)
            ).fetchone()
            if row:
                categories.append(row[0])
        
        cats_json = json.dumps(list(set(categories)))
        
        # Upsert pattern
        existing = self.db.conn.execute(
            """SELECT id, access_count FROM access_patterns
               WHERE hour_of_day = ? AND day_of_week = ? AND project_context = ?""",
            (hour, weekday, project_context)
        ).fetchone()
        
        if existing:
            self.db.conn.execute(
                "UPDATE access_patterns SET access_count = access_count + 1 WHERE id = ?",
                (existing[0],)
            )
        else:
            self.db.conn.execute(
                """INSERT INTO access_patterns
                   (hour_of_day, day_of_week, project_context, memory_categories_accessed, access_count)
                   VALUES (?, ?, ?, ?, 1)""",
                (hour, weekday, project_context, cats_json)
            )
        
        self.db.conn.commit()
    
    def predict(self, project_context: str = None, limit: int = 10) -> dict:
        """Predict what memories will be needed right now."""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        
        # Find matching patterns
        patterns = self.db.conn.execute(
            """SELECT memory_categories_accessed, access_count FROM access_patterns
               WHERE hour_of_day = ? AND day_of_week = ?
               ORDER BY access_count DESC LIMIT 5""",
            (hour, weekday)
        ).fetchall()
        
        # Also check project-specific patterns
        if project_context:
            project_patterns = self.db.conn.execute(
                """SELECT memory_categories_accessed, access_count FROM access_patterns
                   WHERE project_context = ? AND hour_of_day BETWEEN ? AND ?
                   ORDER BY access_count DESC LIMIT 5""",
                (project_context, max(0, hour - 2), min(23, hour + 2))
            ).fetchall()
            patterns = list(patterns) + list(project_patterns)
        
        # Extract predicted categories with weights
        category_weights = {}
        for cats_json, count in patterns:
            try:
                cats = json.loads(cats_json)
                for cat in cats:
                    category_weights[cat] = category_weights.get(cat, 0) + count
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Sort by weight
        sorted_cats = sorted(category_weights.items(), key=lambda x: -x[1])
        
        # Fetch top memories from predicted categories
        predicted_memories = []
        seen_ids = set()
        
        for cat, weight in sorted_cats[:5]:
            rows = self.db.conn.execute(
                """SELECT * FROM memories WHERE category = ?
                   ORDER BY salience DESC, access_count DESC LIMIT ?""",
                (cat, 3)
            ).fetchall()
            for row in rows:
                d = dict(row)
                if d['id'] not in seen_ids:
                    seen_ids.add(d['id'])
                    d['prediction_weight'] = weight
                    predicted_memories.append(d)
        
        # If not enough from patterns, add high-salience general memories
        if len(predicted_memories) < limit:
            existing_ids = set(m['id'] for m in predicted_memories)
            placeholders = ','.join('?' * len(existing_ids)) if existing_ids else "''"
            extra = self.db.conn.execute(
                f"""SELECT * FROM memories WHERE id NOT IN ({placeholders})
                    ORDER BY salience DESC LIMIT ?""",
                list(existing_ids) + [limit - len(predicted_memories)]
            ).fetchall()
            for row in extra:
                d = dict(row)
                d['prediction_weight'] = 0
                predicted_memories.append(d)
        
        return {
            'context': {
                'hour': hour,
                'weekday': weekday,
                'weekday_name': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][weekday],
                'project': project_context,
            },
            'predicted_categories': [c[0] for c in sorted_cats[:5]],
            'predicted_memories': predicted_memories[:limit],
            'confidence': min(len(patterns) / 5.0, 1.0)
        }
    
    def get_pattern_stats(self) -> dict:
        """Get statistics about learned patterns."""
        total = self.db.conn.execute("SELECT COUNT(*) FROM access_patterns").fetchone()[0]
        top_patterns = self.db.conn.execute(
            """SELECT hour_of_day, day_of_week, project_context, access_count
               FROM access_patterns ORDER BY access_count DESC LIMIT 10"""
        ).fetchall()
        
        return {
            'total_patterns': total,
            'top_patterns': [
                {
                    'hour': p[0],
                    'weekday': p[1],
                    'project': p[2],
                    'access_count': p[3]
                } for p in top_patterns
            ]
        }
