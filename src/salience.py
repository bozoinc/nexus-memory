"""
NEXUS — Salience scoring engine.
"""

import math
import time


def now_ms() -> int:
    return int(time.time() * 1000)


def recency_score(created_at_ms: int, half_life_hours: float = 72.0) -> float:
    """Exponential decay based on age. Default half-life: 72 hours."""
    age_hours = max((now_ms() - created_at_ms) / 3600000, 0.001)
    return math.exp(-0.693 * age_hours / half_life_hours)


def access_score(access_count: int) -> float:
    """Logarithmic scale: more accesses = higher score, but diminishing returns."""
    return min(math.log1p(access_count) / 5.0, 1.0)


def context_boost(memory_tags: list, memory_content: str, current_project: str) -> float:
    """Boost score if memory is related to current project context."""
    if not current_project:
        return 0.0
    cp = current_project.lower()
    if cp in memory_content.lower():
        return 0.3
    if any(cp in tag.lower() for tag in memory_tags):
        return 0.2
    return 0.0


def contradiction_penalty(memory_id: str, edges: list) -> float:
    """Penalty if memory is contradicted by another memory."""
    for edge in edges:
        if edge.get('relation_type') == 'contradicts' and edge.get('target_id') == memory_id:
            return 0.3 * edge.get('strength', 1.0)
    return 0.0


def compute_salience(memory: dict, edges: list = None, current_project: str = None) -> float:
    """
    Compute dynamic salience score (0.0 - 1.0).
    
    Formula:
        salience = (recency * 0.25) + (access * 0.20) + (emotional * 0.25) + (context * 0.20) - (contradiction * 0.10)
    """
    r = recency_score(memory.get('created_at', now_ms()))
    a = access_score(memory.get('access_count', 0))
    e = memory.get('emotional_weight', 0.5)
    c = context_boost(
        memory.get('tags', []),
        memory.get('content', ''),
        current_project
    )
    p = contradiction_penalty(memory.get('id', ''), edges or [])
    
    score = (r * 0.25) + (a * 0.20) + (e * 0.25) + (c * 0.20) - (p * 0.10)
    return max(0.0, min(1.0, score))
