import asyncio
import json
from pathlib import Path
from warden.memory.domain.models import KnowledgeGraph, Fact
from warden.memory.application.memory_manager import MemoryManager

async def test_memory_refactor():
    print("Testing KnowledgeGraph Refactor...")
    
    # 1. Test basic instantiation
    graph = KnowledgeGraph()
    print("✓ Initialized empty KnowledgeGraph")
    
    # 2. Add a fact
    fact = Fact(
        category="test_category",
        subject="TestSubject",
        predicate="test_predicate",
        object="TestObject",
        metadata={"detail": "some_info"}
    )
    graph.add_fact(fact)
    print(f"✓ Added fact: {fact.id}")
    
    # 3. Test serialization (to_json)
    data = graph.to_json()
    print("✓ Serialized to JSON")
    # print(json.dumps(data, indent=2))
    
    # 4. Test deserialization (from_json)
    new_graph = KnowledgeGraph.from_json(data)
    print("✓ Deserialized from JSON")
    
    assert len(new_graph.facts) == 1
    assert "TestSubject" in [f.subject for f in new_graph.facts.values()]
    print("✓ Validation passed: Data integrity maintained")

    # 5. Test MemoryManager integration
    tmp_root = Path("./tmp_test_project")
    tmp_root.mkdir(exist_ok=True)
    try:
        manager = MemoryManager(tmp_root)
        await manager.initialize_async()
        manager.add_fact(fact)
        await manager.save_async()
        print("✓ MemoryManager saved successfully")
        
        # Reload
        new_manager = MemoryManager(tmp_root)
        await new_manager.initialize_async()
        assert len(new_manager.knowledge_graph.facts) == 1
        print("✓ MemoryManager loaded successfully")
        
    finally:
        # Cleanup
        if (tmp_root / ".warden" / "memory" / "knowledge_graph.json").exists():
            (tmp_root / ".warden" / "memory" / "knowledge_graph.json").unlink()
        if (tmp_root / ".warden" / "memory").exists():
            (tmp_root / ".warden" / "memory").rmdir()
        if (tmp_root / ".warden").exists():
            (tmp_root / ".warden").rmdir()
        if tmp_root.exists():
            tmp_root.rmdir()

if __name__ == "__main__":
    asyncio.run(test_memory_refactor())
    print("\n--- ALL MEMORY TESTS PASSED ---")
