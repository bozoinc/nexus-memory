#!/usr/bin/env python3
"""
NEXUS — Hermes Integration Module.

Replaces the markdown-based memory system with NEXUS.
Provides functions for Hermes to read/write memory via NEXUS API.

Usage in Hermes skill:
    from nexus_hermes import remember, recall, search_memory, memory_stats
    
    # Remember something
    remember("Tansi prefers edge-tts", category="preference", weight=0.9)
    
    # Recall context
    context = recall(project="youtube", limit=10)
    
    # Search
    results = search_memory("GPU issues")
    
    # Stats
    stats = memory_stats()
"""

import os
import sys
import json
import urllib.request
import urllib.error

NEXUS_API = os.environ.get("NEXUS_API", "http://127.0.0.1:1919")
NEXUS_DB = os.environ.get("NEXUS_DB", os.path.expanduser("~/.nexus/memory.db"))

# Ensure NEXUS is in path
NEXUS_DIR = os.path.expanduser("~/projects/orchestrator_work/nexus")
if NEXUS_DIR not in sys.path:
    sys.path.insert(0, NEXUS_DIR)


def _api_call(method, endpoint, data=None):
    """Make an API call to NEXUS."""
    url = f"{NEXUS_API}{endpoint}"
    try:
        if data:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
                method=method
            )
        else:
            req = urllib.request.Request(url, method=method)
        
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, ConnectionRefusedError):
        # Fallback: use direct DB access
        return _direct_db_call(method, endpoint, data)


def _direct_db_call(method, endpoint, data=None):
    """Fallback: access NEXUS database directly."""
    try:
        from src.storage import NexusStorage
        db = NexusStorage(NEXUS_DB)
        
        if endpoint == "/api/memory/add" and method == "POST":
            mem = db.add_memory(
                content=data.get("content", ""),
                category=data.get("category", "general"),
                source_agent=data.get("source_agent", "hermes"),
                tags=data.get("tags", []),
                emotional_weight=data.get("emotional_weight", 0.5)
            )
            return {"ok": True, "memory": mem}
        
        elif endpoint == "/api/memory/search" and method == "GET":
            results = db.search(
                query=data.get("query") if data else None,
                category=data.get("category") if data else None,
                limit=data.get("limit", 20) if data else 20,
                mode=data.get("mode", "keyword") if data else "keyword",
                current_project=data.get("project") if data else None
            )
            return {"ok": True, "results": results, "count": len(results)}
        
        elif endpoint == "/api/stats" and method == "GET":
            return {"ok": True, "stats": db.stats()}
        
        elif endpoint == "/api/health" and method == "GET":
            return {"ok": True, "stats": db.stats()}
        
        return {"ok": False, "error": "Not implemented in direct DB mode"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remember(content, category="general", tags=None, weight=0.5, agent="hermes"):
    """Store a memory in NEXUS."""
    result = _api_call("POST", "/api/memory/add", {
        "content": content,
        "category": category,
        "source_agent": agent,
        "tags": tags or [],
        "emotional_weight": weight
    })
    return result


def recall(query=None, category=None, project=None, limit=20, mode="keyword"):
    """Search memories in NEXUS."""
    result = _api_call("POST", "/api/memory/search", {
        "query": query,
        "category": category,
        "project": project,
        "limit": limit,
        "mode": mode
    })
    if result.get("ok"):
        return result.get("results", [])
    return []


def search_memory(query, limit=10):
    """Simple search interface."""
    return recall(query=query, limit=limit)


def memory_stats():
    """Get NEXUS memory statistics."""
    result = _api_call("GET", "/api/stats")
    if result.get("ok"):
        return result.get("stats", {})
    return {}


def get_context_for_session(project=None, limit=15):
    """Get relevant context for the current session."""
    memories = recall(project=project, limit=limit, mode="keyword")
    
    # Format for system prompt injection
    if not memories:
        return ""
    
    lines = ["# NEXUS Memory Context (auto-loaded)\n"]
    
    # Group by category
    by_cat = {}
    for m in memories:
        cat = m.get("category", "general")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(m)
    
    for cat, mems in by_cat.items():
        lines.append(f"\n## {cat.title()}\n")
        for m in mems[:5]:  # Max 5 per category
            lines.append(f"- {m['content'][:200]}")
    
    return "\n".join(lines)


def consolidate():
    """Trigger memory consolidation."""
    try:
        from src.consolidation import ConsolidationEngine
        engine = ConsolidationEngine(NEXUS_DB)
        return engine.run(dry_run=False)
    except Exception as e:
        return {"error": str(e)}


def snapshot(name=None):
    """Create a memory snapshot."""
    try:
        from src.versioning import MemoryVersioning
        v = MemoryVersioning(NEXUS_DB)
        return v.snapshot(name)
    except Exception as e:
        return {"error": str(e)}


def health_check():
    """Check if NEXUS is running."""
    result = _api_call("GET", "/api/health")
    return result.get("ok", False)


# --- Migration helpers ---

def migrate_from_markdown(memory_dir=None):
    """Migrate all Hermes markdown memory files to NEXUS."""
    memory_dir = memory_dir or os.path.expanduser("~/.hermes/memory")
    
    try:
        from src.storage import NexusStorage
        db = NexusStorage(NEXUS_DB)
        results = db.import_hermes_memory(memory_dir)
        total = sum(results.values())
        return {"ok": True, "imported": total, "by_file": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def export_to_markdown(output_dir=None):
    """Export NEXUS memories back to markdown (for backup/migration)."""
    output_dir = output_dir or os.path.expanduser("~/.hermes/memory-nexus-backup")
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        from src.storage import NexusStorage
        db = NexusStorage(NEXUS_DB)
        
        # Get all memories grouped by category
        memories = db.search(limit=1000, mode="temporal")
        
        by_cat = {}
        for m in memories:
            cat = m.get("category", "general")
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(m)
        
        # Write markdown files
        for cat, mems in by_cat.items():
            filepath = os.path.join(output_dir, f"{cat}.md")
            with open(filepath, "w") as f:
                f.write(f"# {cat.title()}\n\n")
                f.write(f"*Exported from NEXUS on {__import__('datetime').datetime.now().isoformat()}*\n\n")
                for m in mems:
                    f.write(f"- {m['content']}\n")
        
        return {"ok": True, "files": len(by_cat), "output_dir": output_dir}
    except Exception as e:
        return {"ok": False, "error": str(e)}
