"""
NEXUS — Natural Language Memory Interface.

Converts natural language queries into NEXUS operations.
Uses pattern matching + keyword extraction (no ML dependency).
Designed to be upgraded to LLM-based parsing in the future.

Examples:
  "Remember that I prefer edge-tts" → add_memory(category='preference')
  "What was I working on last Tuesday?" → search(mode='temporal')
  "Why did I stop using SD 1.5?" → search(mode='causal')
  "Show me everything about YouTube" → search + graph traversal
  "I was wrong about X, it's actually Y" → update + contradiction edge
  "What do I know about GPU issues?" → keyword search
  "Delete the memory about X" → delete
  "How many memories do I have?" → stats
  "Back up my memory" → export
  "What's important right now?" → predict + high-salience search
"""

import re
import json
import time
from datetime import datetime, timedelta
from src.storage import NexusStorage, _now_ms
from src.predictor import PredictivePreloader
from src.versioning import MemoryVersioning


# --- Intent Patterns ---

INTENT_PATTERNS = {
    'add': [
        r'remember (?:that )?(.+)',
        r'save (?:that )?(.+)',
        r'note (?:that )?(.+)',
        r'don\'t forget (?:that )?(.+)',
        r'keep in mind (?:that )?(.+)',
        r'add (?:a memory )?(?:that )?(.+)',
        r'learn (?:that )?(.+)',
        r'make sure (?:I )?(?:remember )?(?:that )?(.+)',
    ],
    'search': [
        r'what (?:was|am|are|were|is) (.+?)(?:\?|$)',
        r'find (?:memories? (?:about|on|regarding) )?(.+?)(?:\?|$)',
        r'search (?:for )?(.+?)(?:\?|$)',
        r'show me (?:everything (?:about|on) )?(.+?)(?:\?|$)',
        r'tell me (?:about )?(.+?)(?:\?|$)',
        r'what do (?:I|you) (?:know|remember) (?:about )?(.+?)(?:\?|$)',
        r'look (?:up|for) (.+?)(?:\?|$)',
    ],
    'temporal_search': [
        r'what (?:was I|was) (?:working on|doing) (.+?)(?:\?|$)',
        r'what happened (.+?)(?:\?|$)',
        r'when (?:did|was|were) (.+?)(?:\?|$)',
        r'recent (?:activity|work|changes) (?:on |about )?(.+?)?(?:\?|$)',
    ],
    'causal_search': [
        r'why (?:did|do|is|are|was|were) (.+?)(?:\?|$)',
        r'what (?:caused|led to|made) (.+?)(?:\?|$)',
        r'how (?:did|does) (.+?)(?:\?|$)',
        r'reason (?:for|why) (.+?)(?:\?|$)',
    ],
    'correction': [
        r'(?:I was wrong|actually|correction)[:,]? (.+?)(?:\?|$)',
        r'(?:it\'s|it is) (?:actually|not) (.+?)(?:\?|$)',
        r'update (?:that )?(?:to )?(.+)',
        r'change (?:that )?(?:to )?(.+)',
        r'(?:don\'t|do not) (.+?)(?:,|;|\.)(.+)',
    ],
    'delete': [
        r'delete (?:the memory (?:about|on) )?(.+)',
        r'remove (?:the memory (?:about|on) )?(.+)',
        r'forget (?:about )?(.+)',
    ],
    'stats': [
        r'how many memories',
        r'what(?:\'s| is) (?:in )?(?:my )?memory',
        r'memory (?:stats|statistics|status|size)',
        r'how big is (?:my )?memory',
    ],
    'predict': [
        r'what(?:\'s| is) important (?:right )?now',
        r'what should I (?:be )?(?:working on|doing|remembering)',
        r'what(?:\'s| is) (?:my )?(?:current )?context',
        r'what do I need (?:to know|right now)',
    ],
    'snapshot': [
        r'(?:create |take |make )?(?:a )?snapshot',
        r'back up (?:my )?memory',
        r'save (?:a )?(?:memory )?state',
    ],
    'help': [
        r'what can (?:I|you) (?:do|ask)',
        r'help',
        r'how (?:do|does) (?:this|memory) work',
        r'commands',
    ],
}

# --- Category Detection ---

CATEGORY_KEYWORDS = {
    'preference': ['prefer', 'like', 'always', 'never', 'use', 'choose', 'favorite', 'best', 'better', 'rather'],
    'lesson': ['learned', 'lesson', 'mistake', 'error', 'broken', 'failed', 'fix', 'solution', 'workaround', 'avoid'],
    'project': ['working on', 'project', 'building', 'creating', 'developing', 'planning'],
    'correction': ['wrong', 'actually', 'correction', 'update', 'change', 'not true', 'incorrect'],
    'procedural': ['how to', 'steps', 'process', 'workflow', 'procedure', 'method', 'way to'],
    'episodic': ['yesterday', 'today', 'last week', 'this morning', 'recently', 'before', 'after'],
}

# --- Temporal Parsing ---

TEMPORAL_PATTERNS = {
    'today': lambda: (int((datetime.now().replace(hour=0, minute=0, second=0)).timestamp() * 1000), _now_ms()),
    'yesterday': lambda: _day_range(-1),
    'last week': lambda: _day_range(-7),
    'this week': lambda: _day_range(0, -7),
    'last month': lambda: _day_range(-30),
    'this month': lambda: _day_range(0, -30),
    'last tuesday': lambda: _weekday_range(1, -1),
    'last monday': lambda: _weekday_range(0, -1),
    'last friday': lambda: _weekday_range(4, -1),
    'this morning': lambda: _hour_range(0, 12),
    'this afternoon': lambda: _hour_range(12, 18),
    'this evening': lambda: _hour_range(18, 24),
}


def _day_range(offset_days, span_days=None):
    now = datetime.now()
    if span_days:
        end = now.replace(hour=23, minute=59, second=59)
        start = (now + timedelta(days=span_days)).replace(hour=0, minute=0, second=0)
    else:
        target = now + timedelta(days=offset_days)
        start = target.replace(hour=0, minute=0, second=0)
        end = target.replace(hour=23, minute=59, second=59)
    return (int(start.timestamp() * 1000), int(end.timestamp() * 1000))


def _weekday_range(weekday, weeks_ago):
    now = datetime.now()
    days_since = (now.weekday() - weekday) % 7
    target = now - timedelta(days=days_since + (weeks_ago * 7))
    start = target.replace(hour=0, minute=0, second=0)
    end = target.replace(hour=23, minute=59, second=59)
    return (int(start.timestamp() * 1000), int(end.timestamp() * 1000))


def _hour_range(start_h, end_h):
    now = datetime.now()
    start = now.replace(hour=start_h, minute=0, second=0)
    end = now.replace(hour=end_h, minute=59, second=59)
    return (int(start.timestamp() * 1000), int(end.timestamp() * 1000))


def _detect_category(text: str) -> str:
    """Detect memory category from content."""
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return 'general'


def _detect_emotional_weight(text: str) -> float:
    """Detect emotional weight from content."""
    text_lower = text.lower()
    # Explicit importance markers
    if any(w in text_lower for w in ['important', 'critical', 'crucial', 'must', 'always remember']):
        return 1.0
    # User corrections
    if any(w in text_lower for w in ['wrong', 'actually', 'correction', 'update', 'change']):
        return 0.9
    # Preferences
    if any(w in text_lower for w in ['prefer', 'always use', 'never use']):
        return 0.8
    # Lessons
    if any(w in text_lower for w in ['learned', 'lesson', 'mistake', 'broken', 'failed']):
        return 0.8
    return 0.5


def _parse_temporal(query: str) -> tuple:
    """Extract temporal range from query. Returns (since, until) or (None, None)."""
    query_lower = query.lower()
    for pattern, fn in TEMPORAL_PATTERNS.items():
        if pattern in query_lower:
            return fn()
    return (None, None)


class NLMemoryInterface:
    """Natural language interface to NEXUS memory."""
    
    def __init__(self, db_path: str = None):
        self.db = NexusStorage(db_path)
        self.predictor = PredictivePreloader(db_path)
        self.versioning = MemoryVersioning(db_path)
    
    def process(self, query: str) -> dict:
        """Process a natural language query and return results."""
        query = query.strip()
        if not query:
            return {'action': 'error', 'message': 'Empty query'}
        
        # Try to match intent
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    return self._execute(intent, match, query)
        
        # Fallback: treat as search
        return self._execute('search', None, query)
    
    def _execute(self, intent: str, match, query: str) -> dict:
        """Execute the matched intent."""
        
        if intent == 'add':
            content = match.group(1).strip().rstrip('.')
            category = _detect_category(content)
            weight = _detect_emotional_weight(content)
            tags = self._extract_tags(content)
            
            mem = self.db.add_memory(
                content=content,
                category=category,
                emotional_weight=weight,
                tags=tags
            )
            return {
                'action': 'add',
                'message': f"Remembered: \"{content[:80]}\" [{category}]",
                'memory': mem
            }
        
        elif intent == 'search':
            search_query = match.group(1).strip() if match else query
            category = _detect_category(search_query)
            results = self.db.search(
                query=search_query,
                category=category if category != 'general' else None,
                mode='keyword',
                limit=10
            )
            return {
                'action': 'search',
                'query': search_query,
                'count': len(results),
                'results': results,
                'message': self._format_search_results(results, search_query)
            }
        
        elif intent == 'temporal_search':
            search_query = match.group(1).strip() if match else query
            since, until = _parse_temporal(query)
            
            if since is None:
                # Default to last 7 days
                since = _day_range(-7)[0]
                until = _now_ms()
            
            results = self.db.search(
                query=search_query,
                mode='temporal',
                since=since,
                until=until,
                limit=20
            )
            return {
                'action': 'temporal_search',
                'query': search_query,
                'since': since,
                'until': until,
                'count': len(results),
                'results': results,
                'message': self._format_search_results(results, search_query, temporal=True)
            }
        
        elif intent == 'causal_search':
            search_query = match.group(1).strip() if match else query
            results = self.db.search(query=search_query, mode='causal', limit=10)
            
            # Also do keyword search for broader results
            keyword_results = self.db.search(query=search_query, mode='keyword', limit=5)
            
            return {
                'action': 'causal_search',
                'query': search_query,
                'count': len(results) + len(keyword_results),
                'graph_results': results,
                'keyword_results': keyword_results,
                'message': self._format_causal_results(results, keyword_results, search_query)
            }
        
        elif intent == 'correction':
            correction_text = match.group(1).strip() if match else query
            # Find the memory being corrected
            search_results = self.db.search(query=correction_text, limit=5)
            
            if search_results:
                # Create a new memory with the correction
                category = 'correction'
                weight = 0.9
                tags = self._extract_tags(correction_text)
                
                mem = self.db.add_memory(
                    content=correction_text,
                    category=category,
                    emotional_weight=weight,
                    tags=tags
                )
                
                # Create contradiction edges to similar memories
                for r in search_results[:3]:
                    self.db.add_edge(mem['id'], r['id'], 'contradicts', 0.8)
                
                return {
                    'action': 'correction',
                    'message': f"Corrected: \"{correction_text[:80]}\" (contradicts {len(search_results)} existing memories)",
                    'memory': mem
                }
            else:
                # Just add as a new memory
                mem = self.db.add_memory(
                    content=correction_text,
                    category='correction',
                    emotional_weight=0.9
                )
                return {
                    'action': 'add',
                    'message': f"Added correction: \"{correction_text[:80]}\"",
                    'memory': mem
                }
        
        elif intent == 'delete':
            search_query = match.group(1).strip() if match else query
            results = self.db.search(query=search_query, limit=5)
            
            if results:
                # Delete the best match
                best = results[0]
                self.db.delete_memory(best['id'])
                return {
                    'action': 'delete',
                    'message': f"Deleted: \"{best['content'][:80]}\"",
                    'deleted': best
                }
            return {
                'action': 'delete',
                'message': f"No matching memory found for: \"{search_query}\""
            }
        
        elif intent == 'stats':
            stats = self.db.stats()
            return {
                'action': 'stats',
                'stats': stats,
                'message': self._format_stats(stats)
            }
        
        elif intent == 'predict':
            project = self._extract_project(query)
            result = self.predictor.predict(project_context=project, limit=10)
            return {
                'action': 'predict',
                'prediction': result,
                'message': self._format_prediction(result)
            }
        
        elif intent == 'snapshot':
            name = f"nl-snapshot-{_now_ms()}"
            meta = self.versioning.snapshot(name)
            return {
                'action': 'snapshot',
                'message': f"Snapshot created: {meta['name']} ({meta['stats']['total_memories']} memories)",
                'snapshot': meta
            }
        
        elif intent == 'help':
            return {
                'action': 'help',
                'message': self._help_text()
            }
        
        return {
            'action': 'unknown',
            'message': f"I don't understand: \"{query}\". Try 'help' for available commands."
        }
    
    def _extract_tags(self, text: str) -> list:
        """Extract potential tags from text."""
        tags = []
        text_lower = text.lower()
        
        # Known tag mappings
        tag_map = {
            'youtube': ['youtube', 'video', 'channel', '1stnationstation'],
            'tts': ['tts', 'text to speech', 'edge-tts', 'chatterbox', 'voice'],
            'gpu': ['gpu', 'gtx', 'nvidia', 'cuda', 'graphics'],
            'sd': ['stable diffusion', 'sd 1.5', 'sdxl', 'image gen'],
            'dashboard': ['dashboard', 'neon', 'web dashboard'],
            'memory': ['memory', 'nexus', 'remember', 'storage'],
            'project': ['project', 'building', 'creating', 'developing'],
            'lesson': ['lesson', 'learned', 'mistake', 'error', 'fix'],
            'preference': ['prefer', 'always', 'never', 'use'],
            'first-nation': ['sturgeon lake', 'first nation', 'band', 'indigenous'],
            'saas': ['saas', 'stripe', 'billing', 'subscription'],
            'quantum': ['quantum', 'simulator', 'qubit', 'circuit'],
        }
        
        for tag, keywords in tag_map.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(tag)
        
        return tags[:5]  # Max 5 tags
    
    def _extract_project(self, text: str) -> str:
        """Extract project name from text."""
        text_lower = text.lower()
        projects = ['youtube', 'nexus', 'dashboard', 'quantum', 'saas', 'analytics', 'sturgeon lake']
        for p in projects:
            if p in text_lower:
                return p
        return None
    
    def _format_search_results(self, results: list, query: str, temporal: bool = False) -> str:
        if not results:
            return f"No memories found for: \"{query}\""
        
        lines = [f"Found {len(results)} memories for \"{query}\":\n"]
        for i, r in enumerate(results[:5], 1):
            ts = datetime.fromtimestamp(r['created_at'] / 1000).strftime('%b %d %H:%M')
            lines.append(f"  {i}. [{r['category']}] {r['content'][:70]}... (salience: {r['salience']:.2f}, {ts})")
        
        if len(results) > 5:
            lines.append(f"  ... and {len(results) - 5} more")
        
        return '\n'.join(lines)
    
    def _format_causal_results(self, graph_results: list, keyword_results: list, query: str) -> str:
        all_results = graph_results + keyword_results
        if not all_results:
            return f"No causal chain found for: \"{query}\""
        
        lines = [f"Causal analysis for \"{query}\":\n"]
        
        if graph_results:
            lines.append("  Graph connections:")
            for r in graph_results[:5]:
                lines.append(f"    → [{r['category']}] {r['content'][:60]}...")
        
        if keyword_results:
            lines.append("  Related memories:")
            for r in keyword_results[:3]:
                lines.append(f"    • [{r['category']}] {r['content'][:60]}...")
        
        return '\n'.join(lines)
    
    def _format_stats(self, stats: dict) -> str:
        lines = [
            f"NEXUS Memory Statistics:",
            f"  Total memories: {stats['total_memories']}",
            f"  Total edges: {stats['total_edges']}",
            f"  Average salience: {stats['avg_salience']:.3f}",
            f"  Database size: {stats['db_size_mb']} MB",
        ]
        if stats.get('by_category'):
            lines.append(f"  By category: {', '.join(f'{k}: {v}' for k, v in stats['by_category'].items())}")
        if stats.get('by_agent'):
            lines.append(f"  By agent: {', '.join(f'{k}: {v}' for k, v in stats['by_agent'].items())}")
        return '\n'.join(lines)
    
    def _format_prediction(self, result: dict) -> str:
        ctx = result['context']
        lines = [
            f"Predicted context for {ctx['weekday_name']} {ctx['hour']:02d}:00:",
            f"  Confidence: {result['confidence']:.0%}",
            f"  Categories: {', '.join(result['predicted_categories'][:5])}",
            f"",
            f"  Top memories:",
        ]
        for m in result['predicted_memories'][:5]:
            lines.append(f"    [{m['salience']:.2f}] {m['content'][:60]}...")
        return '\n'.join(lines)
    
    def _help_text(self) -> str:
        return """NEXUS Natural Language Memory Interface

You can talk to your memory naturally:

  REMEMBER:
    "Remember that I prefer edge-tts"
    "Save that SD 1.5 is broken on GTX 1650"
    "Note that the dashboard runs on port 8080"

  SEARCH:
    "What do I know about GPU issues?"
    "Show me everything about YouTube"
    "Find memories about TTS"

  TEMPORAL:
    "What was I working on last Tuesday?"
    "What happened yesterday?"
    "Recent activity on the dashboard"

  CAUSAL:
    "Why did I stop using SD 1.5?"
    "What caused the animation engine switch?"

  CORRECTIONS:
    "Actually, the port is 8081 not 8080"
    "I was wrong about X, it's actually Y"

  MANAGE:
    "How many memories do I have?"
    "What's important right now?"
    "Take a snapshot"
    "Delete the memory about X"

  HELP:
    "What can I ask?"
    "Help"
"""
