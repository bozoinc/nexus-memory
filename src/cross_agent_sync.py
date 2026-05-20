"""
NEXUS — Cross-Agent Memory Mesh.

Enables multiple AI agents to share a single NEXUS memory instance.

Supported agents:
- Hermes Agent (primary, via HTTP API)
- OpenClaw (via file sync adapter)
- Claude Code (via MCP server + file sync)
- Cursor IDE (via .cursorrules sync)
- Any agent (via HTTP API)

Architecture:
- All agents read/write to the same NEXUS SQLite DB via HTTP API (port 1919)
- File-based agents (OpenClaw, Claude Code, Cursor) use sync adapters
- Sync is bidirectional: NEXUS <-> agent workspace files
- Conflict resolution: NEXUS is source of truth, agent files are mirrors
- Each agent has a "perspective layer" — sees only relevant memories
"""

import os
import sys
import json
import time
import hashlib
import re
import threading
from pathlib import Path
from datetime import datetime

NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, NEXUS_DIR)

from src.storage import NexusStorage, _now_ms


# --- Agent Registry ---

AGENT_CONFIGS = {
    'hermes': {
        'name': 'Hermes Agent',
        'type': 'api',
        'api_url': 'http://127.0.0.1:1919',
        'workspace': None,
        'categories': ['user', 'environment', 'projects', 'lessons', 'skills', 'preference'],
        'salience_threshold': 0.3,
        'description': 'Primary agent. Full read/write access to all memories.',
    },
    'openclaw': {
        'name': 'OpenClaw',
        'type': 'file',
        'workspace': os.path.expanduser('~/.openclaw-hermes/workspace'),
        'files': {
            'AGENTS.md': ['projects', 'environment', 'preference'],
            'SOUL.md': ['user', 'preference'],
            'IDENTITY.md': ['user'],
        },
        'categories': ['user', 'projects', 'environment', 'preference'],
        'salience_threshold': 0.5,
        'description': 'Secondary agent. Syncs via workspace markdown files.',
    },
    'claude-code': {
        'name': 'Claude Code',
        'type': 'file',
        'workspace': os.path.expanduser('~/.claude'),
        'files': {
            'CLAUDE.md': ['projects', 'environment', 'lesson', 'preference'],
        },
        'categories': ['projects', 'environment', 'lesson', 'preference'],
        'salience_threshold': 0.6,
        'description': 'Coding agent. Syncs via CLAUDE.md in ~/.claude/',
    },
    'cursor': {
        'name': 'Cursor IDE',
        'type': 'file',
        'workspace': None,  # Per-project
        'files': {
            '.cursorrules': ['projects', 'environment', 'lesson', 'preference'],
        },
        'categories': ['projects', 'environment', 'lesson'],
        'salience_threshold': 0.7,
        'description': 'IDE agent. Syncs via .cursorrules in project directories.',
    },
}


class AgentSyncAdapter:
    """Base class for agent sync adapters."""
    
    def __init__(self, agent_id: str, db: NexusStorage = None):
        self.agent_id = agent_id
        self.config = AGENT_CONFIGS.get(agent_id, {})
        self.db = db or NexusStorage()
    
    def import_to_nexus(self) -> int:
        """Import memories from agent workspace into NEXUS."""
        raise NotImplementedError
    
    def export_from_nexus(self) -> int:
        """Export memories from NEXUS to agent workspace."""
        raise NotImplementedError
    
    def sync(self) -> dict:
        """Bidirectional sync."""
        imported = self.import_to_nexus()
        exported = self.export_from_nexus()
        return {'imported': imported, 'exported': exported}


class FileSyncAdapter(AgentSyncAdapter):
    """Sync adapter for file-based agents (OpenClaw, Claude Code, Cursor)."""
    
    def import_to_nexus(self) -> int:
        """Read agent workspace files and import into NEXUS."""
        workspace = self.config.get('workspace')
        if not workspace or not os.path.exists(workspace):
            return 0
        
        files = self.config.get('files', {})
        count = 0
        
        for filename, categories in files.items():
            filepath = os.path.join(workspace, filename)
            if not os.path.exists(filepath):
                continue
            
            content = Path(filepath).read_text()
            # Parse sections from the file
            sections = self._parse_markdown_sections(content)
            
            for section_title, section_content in sections:
                if not section_content.strip():
                    continue
                
                full_content = f"{section_title}: {section_content.strip()}"
                category = self._detect_category(section_title, categories)
                
                self.db.add_memory(
                    content=full_content[:2000],
                    category=category,
                    source_agent=self.agent_id,
                    tags=[self.agent_id, category, section_title.lower().replace(' ', '-')],
                    emotional_weight=0.6
                )
                count += 1
        
        return count
    
    def export_from_nexus(self) -> int:
        """Export NEXUS memories to agent workspace files."""
        workspace = self.config.get('workspace')
        if not workspace:
            return 0
        
        os.makedirs(workspace, exist_ok=True)
        files = self.config.get('files', {})
        allowed_categories = self.config.get('categories', [])
        threshold = self.config.get('salience_threshold', 0.5)
        
        # Get relevant memories from NEXUS
        memories = self.db.search(
            category=allowed_categories[0] if allowed_categories else None,
            limit=100,
            mode='temporal'
        )
        
        # Filter by salience and categories
        filtered = [
            m for m in memories
            if m['salience'] >= threshold
            and (not allowed_categories or m['category'] in allowed_categories)
        ]
        
        if not filtered:
            return 0
        
        # Group memories by target file
        file_contents = {filename: {} for filename in files}
        
        for mem in filtered:
            # Find the best file for this memory
            for filename, categories in files.items():
                if mem['category'] in categories:
                    section = mem['category']
                    if section not in file_contents[filename]:
                        file_contents[filename][section] = []
                    file_contents[filename][section].append(mem['content'])
                    break
        
        # Write files
        count = 0
        for filename, sections in file_contents.items():
            if not sections:
                continue
            
            filepath = os.path.join(workspace, filename)
            
            # Build file content
            lines = [f"# {filename.replace('.md', '').replace('.', ' ').title()}\n"]
            lines.append(f"*Synced from NEXUS on {datetime.now().isoformat()}*\n\n")
            
            for section_title, contents in sections.items():
                lines.append(f"## {section_title.title()}\n\n")
                for content in contents[:10]:  # Max 10 per section
                    # Convert to bullet points
                    for line in content.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            lines.append(f"- {line}\n")
                    lines.append("\n")
            
            with open(filepath, 'w') as f:
                f.write(''.join(lines))
            
            count += 1
        
        return count
    
    def _parse_markdown_sections(self, content: str) -> list:
        """Parse markdown content into (title, content) sections."""
        sections = []
        current_title = 'General'
        current_lines = []
        
        for line in content.split('\n'):
            if line.startswith('## '):
                if current_lines:
                    sections.append((current_title, '\n'.join(current_lines)))
                current_title = line[3:].strip()
                current_lines = []
            elif line.startswith('# ') and not line.startswith('## '):
                continue  # Skip top-level title
            elif line.startswith('*') and 'Synced' in line:
                continue  # Skip sync markers
            else:
                current_lines.append(line)
        
        if current_lines:
            sections.append((current_title, '\n'.join(current_lines)))
        
        return sections
    
    def _detect_category(self, section_title: str, allowed_categories: list) -> str:
        """Detect memory category from section title."""
        title_lower = section_title.lower()
        
        category_map = {
            'user': ['user', 'profile', 'identity', 'who am i', 'about'],
            'projects': ['project', 'active', 'working', 'building', 'status'],
            'environment': ['environment', 'system', 'setup', 'config', 'tools', 'paths'],
            'lesson': ['lesson', 'learned', 'mistake', 'error', 'fix', 'pitfall'],
            'preference': ['prefer', 'always', 'never', 'use', 'choice'],
            'capabilities': ['capability', 'can', 'skills', 'abilities'],
            'values': ['value', 'principle', 'belief'],
        }
        
        for category, keywords in category_map.items():
            if any(kw in title_lower for kw in keywords):
                return category
        
        return allowed_categories[0] if allowed_categories else 'general'


class APISyncAdapter(AgentSyncAdapter):
    """Sync adapter for API-based agents (Hermes)."""
    
    def import_to_nexus(self) -> int:
        """Hermes writes directly to NEXUS via API. No import needed."""
        return 0
    
    def export_from_nexus(self) -> int:
        """Hermes reads directly from NEXUS via API. No export needed."""
        return 0
    
    def sync(self) -> dict:
        """API agents are always in sync."""
        return {'imported': 0, 'exported': 0, 'note': 'API agent — always in sync'}


class CrossAgentSync:
    """Orchestrates sync across all registered agents."""
    
    def __init__(self, db_path: str = None):
        self.db = NexusStorage(db_path)
        self.adapters = {}
        self._init_adapters()
    
    def _init_adapters(self):
        """Initialize sync adapters for all configured agents."""
        for agent_id, config in AGENT_CONFIGS.items():
            if config['type'] == 'file':
                self.adapters[agent_id] = FileSyncAdapter(agent_id, self.db)
            elif config['type'] == 'api':
                self.adapters[agent_id] = APISyncAdapter(agent_id, self.db)
    
    def register_agent(self, agent_id: str, name: str, agent_type: str,
                       workspace: str = None, files: dict = None,
                       categories: list = None) -> dict:
        """Register a new agent for cross-agent sync."""
        self.db.conn.execute(
            """INSERT OR REPLACE INTO agents (id, name, type, permissions, last_seen, context_preferences)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, name, agent_type, 'read,write', _now_ms(),
             json.dumps({'categories': categories or [], 'workspace': workspace}))
        )
        self.db.conn.commit()
        
        # Create adapter
        if agent_type == 'file':
            config = AGENT_CONFIGS.get(agent_id, {})
            config.update({
                'workspace': workspace,
                'files': files or {},
                'categories': categories or [],
            })
            self.adapters[agent_id] = FileSyncAdapter(agent_id, self.db)
        elif agent_type == 'api':
            self.adapters[agent_id] = APISyncAdapter(agent_id, self.db)
        
        return {'agent_id': agent_id, 'name': name, 'type': agent_type, 'status': 'registered'}
    
    def sync_agent(self, agent_id: str) -> dict:
        """Sync a specific agent."""
        adapter = self.adapters.get(agent_id)
        if not adapter:
            return {'error': f'Agent {agent_id} not registered'}
        
        result = adapter.sync()
        
        # Update last_seen
        self.db.conn.execute(
            "UPDATE agents SET last_seen = ? WHERE id = ?",
            (_now_ms(), agent_id)
        )
        self.db.conn.commit()
        
        return {'agent_id': agent_id, **result}
    
    def sync_all(self) -> dict:
        """Sync all registered agents."""
        results = {}
        for agent_id in self.adapters:
            results[agent_id] = self.sync_agent(agent_id)
        return results
    
    def get_agent_status(self) -> list:
        """Get status of all registered agents."""
        agents = self.db.conn.execute(
            "SELECT * FROM agents ORDER BY last_seen DESC"
        ).fetchall()
        
        return [dict(a) for a in agents]
    
    def get_shared_context(self, requesting_agent: str, limit: int = 20) -> dict:
        """Get the shared memory context for an agent."""
        config = AGENT_CONFIGS.get(requesting_agent, {})
        categories = config.get('categories', [])
        threshold = config.get('salience_threshold', 0.5)
        
        # Get memories relevant to this agent
        all_memories = []
        for category in categories:
            results = self.db.search(
                category=category,
                limit=limit // len(categories) if categories else limit,
                mode='temporal'
            )
            all_memories.extend(results)
        
        # Filter by salience
        filtered = [m for m in all_memories if m['salience'] >= threshold]
        
        # Deduplicate
        seen = set()
        unique = []
        for m in filtered:
            if m['id'] not in seen:
                seen.add(m['id'])
                unique.append(m)
        
        return {
            'agent': requesting_agent,
            'categories': categories,
            'threshold': threshold,
            'memories': unique[:limit],
            'count': len(unique[:limit])
        }
    
    def resolve_conflicts(self, strategy: str = 'nexus_wins') -> dict:
        """Resolve conflicts between agent memories."""
        # Find memories with the same semantic hash from different agents
        rows = self.db.conn.execute("""
            SELECT semantic_hash, COUNT(*) as cnt, GROUP_CONCAT(source_agent) as agents,
                   GROUP_CONCAT(id) as ids
            FROM memories
            WHERE semantic_hash IS NOT NULL
            GROUP BY semantic_hash
            HAVING cnt > 1
        """).fetchall()
        
        resolved = 0
        for row in rows:
            if row[0] and ',' in (row[2] or ''):
                # Multiple agents have memories with same hash
                ids = row[3].split(',')
                if strategy == 'nexus_wins':
                    # Keep the most recent, delete others
                    memories = [self.db.get_memory(i) for i in ids]
                    memories = [m for m in memories if m]
                    if memories:
                        best = max(memories, key=lambda m: m['created_at'])
                        for m in memories:
                            if m['id'] != best['id']:
                                self.db.delete_memory(m['id'])
                                resolved += 1
        
        return {'conflicts_found': len(rows), 'resolved': resolved, 'strategy': strategy}
