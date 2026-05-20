"""
NEXUS — Unit tests for storage engine.
"""

import os
import sys
import json
import time
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage import NexusStorage, _uuid7, _semantic_hash, _compute_salience


@pytest.fixture
def db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    storage = NexusStorage(db_path)
    yield storage
    storage.close()
    os.unlink(db_path)


class TestAddMemory:
    def test_add_basic(self, db):
        mem = db.add_memory("Test memory content")
        assert mem is not None
        assert mem['content'] == "Test memory content"
        assert mem['category'] == 'general'
        assert mem['salience'] == 1.0
    
    def test_add_with_category(self, db):
        mem = db.add_memory("Lesson learned", category='lesson')
        assert mem['category'] == 'lesson'
    
    def test_add_with_tags(self, db):
        mem = db.add_memory("Tagged memory", tags=['test', 'important'])
        tags = json.loads(mem['tags'])
        assert 'test' in tags
        assert 'important' in tags
    
    def test_add_with_emotional_weight(self, db):
        mem = db.add_memory("Important correction", emotional_weight=0.9)
        assert mem['emotional_weight'] == 0.9
    
    def test_add_generates_uuid(self, db):
        mem = db.add_memory("UUID test")
        assert mem['id'] is not None
        assert len(mem['id']) > 20  # Reasonable UUID length
    
    def test_add_generates_semantic_hash(self, db):
        mem = db.add_memory("SD 1.5 produces black images on GTX 1650")
        assert mem['semantic_hash'] is not None
        assert len(mem['semantic_hash']) == 16


class TestGetMemory:
    def test_get_existing(self, db):
        added = db.add_memory("Get test")
        fetched = db.get_memory(added['id'])
        assert fetched is not None
        assert fetched['content'] == "Get test"
    
    def test_get_nonexistent(self, db):
        result = db.get_memory("nonexistent-id")
        assert result is None
    
    def test_get_increments_access_count(self, db):
        mem = db.add_memory("Access count test")
        assert mem['access_count'] == 0
        fetched = db.get_memory(mem['id'])
        assert fetched['access_count'] == 1
        fetched2 = db.get_memory(mem['id'])
        assert fetched2['access_count'] == 2


class TestUpdateMemory:
    def test_update_content(self, db):
        mem = db.add_memory("Original content")
        updated = db.update_memory(mem['id'], content="Updated content")
        assert updated['content'] == "Updated content"
    
    def test_update_tags(self, db):
        mem = db.add_memory("Tag update test")
        updated = db.update_memory(mem['id'], tags=['new-tag'])
        tags = json.loads(updated['tags'])
        assert 'new-tag' in tags
    
    def test_update_emotional_weight(self, db):
        mem = db.add_memory("Weight test")
        updated = db.update_memory(mem['id'], emotional_weight=0.9)
        assert updated['emotional_weight'] == 0.9


class TestDeleteMemory:
    def test_delete_existing(self, db):
        mem = db.add_memory("Delete me")
        assert db.delete_memory(mem['id']) is True
        assert db.get_memory(mem['id']) is None
    
    def test_delete_nonexistent(self, db):
        assert db.delete_memory("nonexistent") is False


class TestSearch:
    def test_keyword_search(self, db):
        db.add_memory("SD 1 point 5 produces black images", category='lesson')
        db.add_memory("edge-tts is reliable", category='lesson')
        results = db.search(query="SD 1 point 5", mode='keyword')
        assert len(results) >= 1
        assert any("SD 1 point 5" in r['content'] for r in results)
    
    def test_search_by_category(self, db):
        db.add_memory("Memory A", category='project')
        db.add_memory("Memory B", category='lesson')
        results = db.search(category='project')
        assert all(r['category'] == 'project' for r in results)
    
    def test_search_by_agent(self, db):
        db.add_memory("From hermes", source_agent='hermes')
        db.add_memory("From openclaw", source_agent='openclaw')
        results = db.search(source_agent='hermes')
        assert all(r['source_agent'] == 'hermes' for r in results)
    
    def test_temporal_search(self, db):
        db.add_memory("Old memory")
        time.sleep(0.01)
        db.add_memory("New memory")
        now = int(time.time() * 1000)
        results = db.search(mode='temporal', since=now - 1000)
        assert len(results) >= 1
    
    def test_context_boost(self, db):
        db.add_memory("Working on YouTube video production", tags=['youtube'])
        db.add_memory("Random unrelated memory")
        results = db.search(current_project='youtube')
        # YouTube memory should be boosted
        youtube_results = [r for r in results if 'youtube' in r.get('content', '').lower()]
        assert len(youtube_results) >= 1


class TestGraph:
    def test_add_edge(self, db):
        a = db.add_memory("Memory A")
        b = db.add_memory("Memory B causes A")
        edge_id = db.add_edge(b['id'], a['id'], 'causes', 0.9)
        assert edge_id > 0
    
    def test_graph_neighborhood(self, db):
        a = db.add_memory("Center node")
        b = db.add_memory("Connected node 1")
        c = db.add_memory("Connected node 2")
        db.add_edge(a['id'], b['id'], 'relates')
        db.add_edge(a['id'], c['id'], 'relates')
        
        neighbors = db.get_graph_neighborhood(a['id'], depth=1)
        assert len(neighbors) == 2
    
    def test_graph_depth(self, db):
        a = db.add_memory("A")
        b = db.add_memory("B")
        c = db.add_memory("C")
        db.add_edge(a['id'], b['id'], 'follows')
        db.add_edge(b['id'], c['id'], 'follows')
        
        neighbors_1 = db.get_graph_neighborhood(a['id'], depth=1)
        neighbors_2 = db.get_graph_neighborhood(a['id'], depth=2)
        assert len(neighbors_2) >= len(neighbors_1)


class TestConsolidation:
    def test_dedup(self, db):
        db.add_memory("Duplicate content here")
        db.add_memory("Duplicate content here")
        stats = db.consolidate(dry_run=False)
        assert stats['merged'] >= 1
    
    def test_dry_run(self, db):
        db.add_memory("Dry run test")
        stats = db.consolidate(dry_run=True)
        # Nothing should be deleted
        all_memories = db.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert all_memories >= 1
    
    def test_rescore(self, db):
        mem = db.add_memory("Rescore test", emotional_weight=0.9)
        db.consolidate(dry_run=False)
        updated = db.get_memory(mem['id'])
        assert updated is not None


class TestImport:
    def test_import_hermes_memory(self, db):
        results = db.import_hermes_memory()
        total = sum(results.values())
        assert total > 0  # Should import at least some memories
    
    def test_import_single_file(self, db):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Test Memory\n\n## Section One\nContent one\n\n## Section Two\nContent two\n")
            f.flush()
            count = db.import_from_markdown(f.name)
            assert count == 2
            os.unlink(f.name)


class TestStats:
    def test_stats(self, db):
        db.add_memory("Stat test 1")
        db.add_memory("Stat test 2")
        s = db.stats()
        assert s['total_memories'] >= 2
        assert 'by_category' in s
        assert 'db_size_mb' in s


class TestHelpers:
    def test_uuid7_format(self):
        uid = _uuid7()
        assert len(uid) > 20  # Reasonable UUID length
        assert '-' in uid
        assert uid.count('-') == 4
    
    def test_semantic_hash(self):
        h1 = _semantic_hash("SD 1.5 produces black images on GTX 1650")
        h2 = _semantic_hash("SD 1.5 produces black images on GTX 1650")
        h3 = _semantic_hash("Completely different content about cooking")
        assert h1 == h2  # Same content = same hash
        assert h1 != h3  # Different content = different hash
    
    def test_compute_salience(self):
        now = int(time.time() * 1000)
        mem = {
            'created_at': now,
            'access_count': 5,
            'emotional_weight': 0.8,
            'tags': '["youtube"]',
            'content': 'YouTube video production'
        }
        score = _compute_salience(mem, current_project='youtube')
        assert 0.0 <= score <= 1.0
        # With context boost, should be relatively high
        assert score > 0.3
