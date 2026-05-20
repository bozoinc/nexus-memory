"""
NEXUS — HTTP API server (FastAPI).
"""

import json
import time
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel

from src.storage import NexusStorage, _now_ms
from src.consolidation import ConsolidationEngine

app = FastAPI(title="NEXUS Memory System", version="0.1.0")

# Default storage instance
_db = None

def get_db():
    global _db
    if _db is None:
        _db = NexusStorage()
    return _db


class AddMemoryRequest(BaseModel):
    content: str
    category: str = "general"
    source_agent: str = "hermes"
    tags: list = []
    emotional_weight: float = 0.5
    branch_id: str = "main"


class SnapshotRequest(BaseModel):
    name: str = ""


@app.get("/api/health")
def health():
    db = get_db()
    stats = db.stats()
    return {"ok": True, "service": "nexus-memory", "stats": stats}


@app.post("/api/memory/add")
def add_memory(req: AddMemoryRequest):
    db = get_db()
    mem = db.add_memory(
        content=req.content,
        category=req.category,
        source_agent=req.source_agent,
        tags=req.tags,
        emotional_weight=req.emotional_weight,
        branch_id=req.branch_id
    )
    return {"ok": True, "memory": mem}


@app.get("/api/memory/search")
def search_memories(
    q: Optional[str] = None,
    category: Optional[str] = None,
    agent: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    mode: str = "keyword",
    project: Optional[str] = None,
    limit: int = Query(default=20, le=100)
):
    db = get_db()
    results = db.search(
        query=q, category=category, source_agent=agent,
        since=since, until=until, limit=limit, mode=mode,
        current_project=project
    )
    return {"ok": True, "results": results, "count": len(results)}


@app.get("/api/memory/graph/{mem_id}")
def graph_neighborhood(mem_id: str, depth: int = 2, relations: Optional[str] = None):
    db = get_db()
    rel_types = relations.split(",") if relations else None
    nodes = db.get_graph_neighborhood(mem_id, depth=depth, relation_types=rel_types)
    return {"ok": True, "center": mem_id, "nodes": nodes, "count": len(nodes)}


@app.get("/api/memory/get/{mem_id}")
def get_memory(mem_id: str):
    db = get_db()
    mem = db.get_memory(mem_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True, "memory": mem}


@app.post("/api/memory/ask")
def ask_memory(query: str = None):
    """Natural language memory interface endpoint."""
    if not query:
        raise HTTPException(status_code=400, detail="No query provided")
    from src.nl_interface import NLMemoryInterface
    nl = NLMemoryInterface()
    result = nl.process(query)
    return {"ok": True, **result}


@app.post("/api/memory/consolidate")
def consolidate(dry_run: bool = False):
    engine = ConsolidationEngine()
    stats = engine.run(dry_run=dry_run)
    return {"ok": True, "stats": stats, "dry_run": dry_run}


@app.get("/api/memory/predict")
def predict_context(project: Optional[str] = None, limit: int = 10):
    """Predict what context will be needed based on time and project."""
    db = get_db()
    now = datetime_now()
    
    # Get memories from this time window in previous weeks
    hour = now.hour
    weekday = now.weekday()
    
    # Simple: return high-salience memories from the same project/category
    results = db.search(category=project, limit=limit, mode='temporal', current_project=project)
    
    return {
        "ok": True,
        "context": {
            "hour": hour,
            "weekday": weekday,
            "project": project,
            "predicted_memories": results
        }
    }


@app.post("/api/memory/snapshot")
def create_snapshot(req: SnapshotRequest):
    """Create a named snapshot (placeholder for versioning)."""
    db = get_db()
    stats = db.stats()
    return {"ok": True, "name": req.name or f"snapshot-{_now_ms()}", "stats": stats}


@app.get("/api/stats")
def get_stats():
    db = get_db()
    return {"ok": True, "stats": db.stats()}


def datetime_now():
    from datetime import datetime
    return datetime.now()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=1919)
