#!/usr/bin/env python3
"""
NEXUS MCP Server

Exposes NEXUS memory system tools via the Model Context Protocol (stdio transport).
Compatible with Claude Code, Cursor, Windsurf, and any MCP-compatible agent.

Usage:
    python -m nexus_mcp.server

Or configure in MCP client config:
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
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path so we can import NEXUS
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from src.storage import NexusStorage, _now_ms

# Initialize the MCP server
mcp = FastMCP("nexus-memory")

# Global storage instance (lazy init)
_db = None

def get_db():
    """Get or create the NEXUS database instance."""
    global _db
    if _db is None:
        db_path = os.environ.get("NEXUS_DB", str(Path.home() / ".nexus" / "memory.db"))
        _db = NexusStorage(db_path=db_path)
    return _db


@mcp.tool()
def nexus_add_memory(
    content: str,
    category: str = "general",
    tags: str = "",
    emotional_weight: float = 0.5,
    source_agent: str = "mcp"
) -> str:
    """Add a new memory to NEXUS.

    Args:
        content: The memory content to store.
        category: Category for the memory (e.g., 'decision', 'preference', 'context', 'general').
        tags: Comma-separated tags for the memory.
        emotional_weight: Importance from 0.0 (trivial) to 1.0 (critical).
        source_agent: The agent adding this memory.

    Returns:
        JSON with the created memory's ID and metadata.
    """
    db = get_db()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    mem = db.add_memory(
        content=content,
        category=category,
        source_agent=source_agent,
        tags=tag_list,
        emotional_weight=emotional_weight,
    )
    return json.dumps({"ok": True, "memory": mem}, indent=2)


@mcp.tool()
def nexus_search(
    query: str,
    category: str = None,
    limit: int = 10,
    mode: str = "keyword"
) -> str:
    """Search NEXUS memories.

    Args:
        query: Search query (natural language or keywords).
        category: Filter by category.
        limit: Maximum number of results (default 10, max 100).
        mode: Search mode - 'keyword' (FTS5), 'temporal' (time-based), or 'causal' (graph traversal).

    Returns:
        JSON array of matching memories with relevance scores.
    """
    db = get_db()
    results = db.search(
        query=query,
        category=category,
        limit=min(limit, 100),
        mode=mode,
    )
    return json.dumps({"ok": True, "results": results, "count": len(results)}, indent=2)


@mcp.tool()
def nexus_ask(question: str) -> str:
    """Ask NEXUS a natural language question about stored memories.

    Args:
        question: Natural language question (e.g., "What did we decide about the database?").

    Returns:
        Answer based on stored memories, with source references.
    """
    try:
        from src.nl_interface import NLMemoryInterface
        db_path = os.environ.get("NEXUS_DB", str(Path.home() / ".nexus" / "memory.db"))
        nl = NLMemoryInterface(db_path=db_path)
        result = nl.process(question)
        return json.dumps({"ok": True, **result}, indent=2)
    except Exception as e:
        # Fallback to simple search
        db = get_db()
        results = db.search(query=question, limit=5)
        if results:
            answers = [r.get("content", "") for r in results[:3]]
            return json.dumps({
                "ok": True,
                "answer": " ".join(answers),
                "results": results,
                "source": "search_fallback"
            }, indent=2)
        return json.dumps({
            "ok": False,
            "error": str(e),
            "answer": "I don't have enough information to answer this question."
        }, indent=2)


@mcp.tool()
def nexus_list(limit: int = 50, category: str = None) -> str:
    """List recent memories in NEXUS.

    Args:
        limit: Maximum number of memories to return.
        category: Filter by category.

    Returns:
        JSON array of memories, ordered by most recent first.
    """
    db = get_db()
    results = db.search(query=None, category=category, limit=limit, mode="temporal")
    return json.dumps({"ok": True, "memories": results, "count": len(results)}, indent=2)


@mcp.tool()
def nexus_get(memory_id: str) -> str:
    """Get a specific memory by ID.

    Args:
        memory_id: The unique ID of the memory.

    Returns:
        JSON with the memory content and metadata.
    """
    db = get_db()
    mem = db.get_memory(memory_id)
    if mem:
        return json.dumps({"ok": True, "memory": mem}, indent=2)
    return json.dumps({"ok": False, "error": "Memory not found"}, indent=2)


@mcp.tool()
def nexus_delete(memory_id: str) -> str:
    """Delete a memory from NEXUS.

    Args:
        memory_id: The unique ID of the memory to delete.

    Returns:
        JSON confirming deletion.
    """
    db = get_db()
    success = db.delete_memory(memory_id)
    return json.dumps({"ok": success, "deleted": memory_id if success else None}, indent=2)


@mcp.tool()
def nexus_stats() -> str:
    """Get NEXUS memory statistics.

    Returns:
        JSON with total memories, categories, agents, and storage info.
    """
    db = get_db()
    stats = db.stats()
    db_path = os.environ.get("NEXUS_DB", str(Path.home() / ".nexus" / "memory.db"))
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    stats["db_path"] = db_path
    stats["db_size_bytes"] = db_size
    stats["db_size_human"] = f"{db_size / 1024:.1f} KB" if db_size < 1024*1024 else f"{db_size / (1024*1024):.1f} MB"
    return json.dumps({"ok": True, "stats": stats}, indent=2)


@mcp.tool()
def nexus_consolidate(dry_run: bool = False) -> str:
    """Run memory consolidation on NEXUS.

    Consolidation merges similar memories, prunes low-salience entries,
    and creates abstractions (like human sleep cycles).

    Args:
        dry_run: If True, report what would be done without making changes.

    Returns:
        JSON with consolidation statistics.
    """
    try:
        from src.consolidation import ConsolidationEngine
        engine = ConsolidationEngine(db=get_db())
        stats = engine.run(dry_run=dry_run)
        return json.dumps({"ok": True, "stats": stats, "dry_run": dry_run}, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


@mcp.tool()
def nexus_export(format: str = "json") -> str:
    """Export all NEXUS memories.

    Args:
        format: Export format - 'json' or 'markdown'.

    Returns:
        All memories in the requested format.
    """
    db = get_db()
    results = db.search(query=None, limit=10000, mode="temporal")

    if format == "markdown":
        lines = ["# NEXUS Memory Export\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")
        lines.append(f"Total memories: {len(results)}\n\n---\n")
        for mem in results:
            lines.append(f"\n## {mem.get('category', 'general')} — {mem['id'][:12]}...")
            lines.append(f"**Created:** {datetime.fromtimestamp(mem['created_at']/1000).isoformat()}")
            lines.append(f"**Agent:** {mem.get('source_agent', 'unknown')}")
            lines.append(f"**Tags:** {mem.get('tags', '[]')}")
            lines.append(f"**Salience:** {mem.get('salience', 1.0):.2f}")
            lines.append(f"\n{mem['content']}\n\n---\n")
        return "".join(lines)
    else:
        return json.dumps({"ok": True, "memories": results, "count": len(results)}, indent=2)


@mcp.tool()
def nexus_predict(project: str = None, limit: int = 10) -> str:
    """Predict what context will be needed based on time and project.

    Args:
        project: Current project name for context prediction.
        limit: Maximum number of predicted memories.

    Returns:
        JSON with predicted relevant memories.
    """
    db = get_db()
    now = datetime.now()
    results = db.search(
        query=None,
        category=project,
        limit=limit,
        mode="temporal",
        current_project=project,
    )
    return json.dumps({
        "ok": True,
        "context": {
            "hour": now.hour,
            "weekday": now.strftime("%A"),
            "project": project,
            "predicted_memories": results
        }
    }, indent=2)


def main():
    """Run the MCP server via stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
