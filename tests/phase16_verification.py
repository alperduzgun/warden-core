"""
Verification script for Phase 16: Dependency-Aware Incremental Scanning.
"""

import asyncio
from pathlib import Path
import os
import shutil

# Mocking some parts for isolated testing if needed, 
# but better to run a small project scan.

PROJECT_DIR = Path("temp/dep_test_project")

def setup_project():
    """Setup a small project with dependencies."""
    if PROJECT_DIR.exists():
        shutil.rmtree(PROJECT_DIR)
    PROJECT_DIR.mkdir(parents=True)
    
    # Create a base utility
    (PROJECT_DIR / "utils.py").write_text("def sanitize(data): return data.strip()")
    
    # Create a consumer
    (PROJECT_DIR / "app.py").write_text("from utils import sanitize\n\ndef run(): return sanitize(' hello ')")
    
    # Create an unrelated file
    (PROJECT_DIR / "config.py").write_text("VERSION = '1.0.0'")

async def verify_dependency_extraction():
    """Test AST-based dependency extraction."""
    from warden.ast.providers.python_ast_provider import PythonASTProvider
    from warden.ast.domain.enums import CodeLanguage
    
    provider = PythonASTProvider()
    code = "from utils import sanitize\nimport os"
    deps = provider.extract_dependencies(code, CodeLanguage.PYTHON)
    print(f"Extracted Python deps: {deps}")
    assert "utils" in deps
    assert "os" in deps

async def verify_impact_propagation():
    """Test transitive impact calculation."""
    from warden.analysis.application.dependency_graph import DependencyGraph
    from warden.ast.application.provider_registry import ASTProviderRegistry
    from warden.ast.providers.python_ast_provider import PythonASTProvider
    from warden.analysis.domain.project_context import ProjectContext
    
    registry = ASTProviderRegistry()
    registry.register(PythonASTProvider())
    
    ctx = ProjectContext(project_root=str(PROJECT_DIR), project_name="dep_test")
    graph = DependencyGraph(PROJECT_DIR, ctx, registry)
    
    from warden.ast.domain.enums import CodeLanguage
    await graph.scan_file_async(PROJECT_DIR / "app.py", CodeLanguage.PYTHON)
    
    changed = [PROJECT_DIR / "utils.py"]
    impacted = graph.get_transitive_impact(changed)
    print(f"Impacted files by utils.py: {[str(p) for p in impacted]}")
    assert any("app.py" in str(p) for p in impacted)

if __name__ == "__main__":
    setup_project()
    asyncio.run(verify_dependency_extraction())
    asyncio.run(verify_impact_propagation())
    print("Verification tests PASSED!")
    shutil.rmtree(PROJECT_DIR)
